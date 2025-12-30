import streamlit as st
import pandas as pd
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import requests
import json
import datetime
import altair as alt
import re

# ==========================================
# [중요] 페이지 설정 (맨 위 고정)
# ==========================================
st.set_page_config(page_title="강북청솔 학생 관리", layout="wide")
st.title("👨‍🏫 김성만 선생님의 학생 관리 시스템")

# ==========================================
# [설정 1] 구글 시트 ID
# ==========================================
GOOGLE_SHEET_KEY = "1zJHY7baJgoxyFJ5cBduCPVEfQ-pBPZ8jvhZNaPpCLY4"

# ==========================================
# [설정 2] 인증 및 연결 (캐시 적용)
# ==========================================
@st.cache_resource
def get_google_sheet_connection():
    try:
        scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
        creds_dict = dict(st.secrets["gcp_service_account"])
        creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
        client = gspread.authorize(creds)
        return client
    except Exception as e:
        return None

# 데이터를 60초 동안 기억 (429 에러 방지)
@st.cache_data(ttl=60)
def load_data_from_sheet(worksheet_name):
    try:
        client = get_google_sheet_connection()
        if not client: return pd.DataFrame()
        
        sheet = client.open_by_key(GOOGLE_SHEET_KEY).worksheet(worksheet_name)
        data = sheet.get_all_values()
        
        if len(data) < 2: return pd.DataFrame()
        
        headers = data[0]
        rows = data[1:]
        df = pd.DataFrame(rows, columns=headers)
        
        numeric_cols = ['주간점수', '주간평균', '성취도점수', '성취도평균', '과제']
        for col in numeric_cols:
            if col in df.columns:
                df[col] = df[col].astype(str).str.replace(',', '')
                df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0)
        return df
    except Exception as e:
        return pd.DataFrame()

def add_row_to_sheet(worksheet_name, row_data_list):
    try:
        client = get_google_sheet_connection()
        if not client: return False
        sheet = client.open_by_key(GOOGLE_SHEET_KEY).worksheet(worksheet_name)
        sheet.append_row(row_data_list)
        load_data_from_sheet.clear()
        return True
    except Exception as e:
        st.error(f"저장 실패: {e}")
        return False

# ==========================================
# [설정 3] Gemini 2.0 Flash API (REST API)
# ==========================================
def refine_text_ai(raw_text, context_type, student_name):
    if not raw_text:
        return ""
        
    try:
        api_key = st.secrets["GENAI_API_KEY"]
        url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash-exp:generateContent?key={api_key}"
        headers = {'Content-Type': 'application/json'}
        
        prompt_text = f"""
        당신은 입시 수학 학원의 베테랑 선생님입니다. 
        아래 메모는 '{student_name}' 학생에 대한 내용입니다.
        이 내용을 학부모님께 전달하거나 기록으로 남길 수 있도록 '정중하고 전문적인 문체'로 다듬어주세요.
        
        [강력한 지침사항]
        1. 제목, 소제목, 인사말(안녕하세요 등) 절대 금지.
        2. 바로 본론 문장부터 시작하세요.
        3. 학생 이름 '{student_name}'을 문장 주어로 자연스럽게 사용하세요.
        
        [원문]: {raw_text}
        """
        
        data = {"contents": [{"parts": [{"text": prompt_text}]}]}
        response = requests.post(url, headers=headers, data=json.dumps(data))
        
        if response.status_code == 200:
            return response.json()['candidates'][0]['content']['parts'][0]['text']
        else:
            return f"AI 에러: {response.status_code}"
    except Exception as e:
        return f"통신 에러: {e}"

# ==========================================
# 메인 앱 화면
# ==========================================

# [세션 상태 초기화]
if "edit_memo" not in st.session_state: st.session_state.edit_memo = ""
if "edit_rev" not in st.session_state: st.session_state.edit_rev = ""
if "counsel_res" not in st.session_state: st.session_state.counsel_res = ""
if "form_submitted" not in st.session_state: st.session_state.form_submitted = False

menu = st.sidebar.radio("메뉴", ["학생 관리 (상담/성적)", "신규 학생 등록"])

# ------------------------------------------
# 1. 신규 학생 등록
# ------------------------------------------
if menu == "신규 학생 등록":
    st.header("📝 신규 학생 등록")
    with st.form("new_student_form"):
        col1, col2 = st.columns(2)
        name = col1.text_input("학생 이름")
        ban = col2.text_input("반 (Class)")
        origin = st.text_input("출신 중학교")
        target = st.text_input("배정 예정 고등학교")
        addr = st.text_input("거주지 (대략적)")
        
        if st.form_submit_button("💾 학생 등록"):
            if name:
                if add_row_to_sheet("students", [name, ban, origin, target, addr]):
                    st.success(f"{name} 학생 등록 완료!")

# ------------------------------------------
# 2. 학생 관리
# ------------------------------------------
elif menu == "학생 관리 (상담/성적)":
    df_students = load_data_from_sheet("students")
    
    if df_students.empty:
        st.warning("학생 데이터가 없습니다. (구글 시트 연결 확인 필요)")
    else:
        student_list = df_students["이름"].tolist()
        selected_student = st.sidebar.selectbox("학생 선택", student_list)
        
        rows = df_students[df_students["이름"] == selected_student]
        if not rows.empty:
            info = rows.iloc[0]
            ban_txt = info['반'] if '반' in info else ''
            st.sidebar.info(f"**{info['이름']} ({ban_txt})**\n\n🏫 {info['출신중']} ➡️ {info['배정고']}\n🏠 {info['거주지']}")

        tab1, tab2, tab3 = st.tabs(["🗣️ 상담 일지", "📊 성적 입력", "👨‍👩‍👧‍👦 리포트"])

        # --- [탭 1] 상담 일지 ---
        with tab1:
            st.subheader(f"{selected_student} 상담 기록")
            df_c = load_data_from_sheet("counseling")
            with st.expander("📂 이전 상담 내역"):
                if not df_c.empty:
                    logs = df_c[df_c["이름"] == selected_student]
                    if '날짜' in logs.columns: logs = logs.sort_values(by='날짜', ascending=False)
                    for _, r in logs.iterrows():
                        st.markdown(f"**🗓️ {r['날짜']}**")
                        st.info(r['내용'])

            st.divider()
            
            st.write("#### ✍️ 새로운 상담 입력")
            c_date = st.date_input("날짜", datetime.date.today())
            raw_c = st.text_area("1. 상담 메모 (대충 적으세요)", height=80, key="c_raw")
            
            if st.button("✨ AI 변환 (상담)", key="btn_c_ai"):
                with st.spinner("변환 중..."):
                    st.session_state.counsel_res = refine_text_ai(raw_c, "학부모 상담 일지", selected_student)
                    # rerun 없음 -> 탭 유지

            final_c = st.text_area("2. 최종 내용 (여기서 직접 수정하세요)", value=st.session_state.counsel_res, height=150, key="c_final")

            if st.button("💾 상담 내용 저장", type="primary", key="btn_c_save"):
                if final_c:
                    if add_row_to_sheet("counseling", [selected_student, str(c_date), final_c]):
                        st.success("저장 완료!")
                        st.session_state.counsel_res = "" 
                        st.rerun()
                else:
                    st.warning("내용이 없습니다.")


        # --- [탭 2] 성적 입력 (폼 적용: 튕김 방지) ---
        with tab2:
            st.subheader("📊 성적 데이터 입력")
            st.info("💡 **[입력 확인 & AI 변환]** 버튼을 눌러야 내용이 확정되고 저장 버튼이 나타납니다.")

            # [핵심] 주차 선택이나 입력을 해도 절대 새로고침되지 않도록 Form으로 감싸기
            with st.form("grade_input_form"):
                c1, c2 = st.columns(2)
                # key를 지정해서 폼 밖에서도 값을 불러올 수 있게 함
                mon = c1.selectbox("월", [f"{i}월" for i in range(1, 13)], key="in_mon")
                wk = c2.selectbox("주차", [f"{i}주차" for i in range(1, 6)], key="in_wk")

                st.markdown("##### 📝 주간 과제 & 점수")
                cc1, cc2, cc3 = st.columns(3)
                hw = cc1.number_input("수행도(%)", 0, 100, 80, key="in_hw")
                w_sc = cc2.number_input("주간 과제 점수", 0, 100, 0, key="in_w_sc")
                w_av = cc3.number_input("주간과제 평균점수", 0, 100, 0, key="in_w_av")
                wrong = st.text_input("주간 과제 오답 번호 (띄어쓰기 구분)", placeholder="예: 13 15 22", key="in_wrong")
                
                st.markdown("---")
                st.markdown("##### 📢 학습 태도 및 특이사항")
                raw_m = st.text_area("특이사항 메모 (대충 적기)", height=70, key="in_raw_m")

                st.divider()
                st.markdown("##### 🏆 성취도 평가")
                cc4, cc5 = st.columns(2)
                a_sc = cc4.number_input("성취도 평가 점수", 0, 100, 0, key="in_a_sc")
                a_av = cc5.number_input("성취도 평가 점수 평균", 0, 100, 0, key="in_a_av")
                a_wrong = st.text_input("성취도평가 오답번호", placeholder="예: 21 29 30", key="in_a_wrong")
                
                st.markdown("##### 📝 성취도 총평")
                raw_r = st.text_area("총평 메모 (대충 적기)", height=70, key="in_raw_r")

                st.write("")
                # 이 버튼을 눌러야만 비로소 프로그램이 반응함 (탭 튕김 원천 봉쇄)
                submitted = st.form_submit_button("⬇️ 입력 확인 및 AI 변환", type="primary")

            # --- 폼 제출 후 처리 로직 (Form 바깥) ---
            if submitted:
                st.session_state.form_submitted = True # 제출 상태 기억
                
                # AI 변환 실행
                with st.spinner("AI가 내용을 다듬고 있습니다..."):
                    if raw_m:
                        st.session_state.edit_memo = refine_text_ai(raw_m, "학습 태도 특이사항", selected_student)
                    else:
                        st.session_state.edit_memo = "" # 내용 없으면 빈칸
                        
                    if raw_r:
                        st.session_state.edit_rev = refine_text_ai(raw_r, "성취도 평가 총평", selected_student)
                    else:
                        st.session_state.edit_rev = ""

            # --- 결과 확인 및 최종 저장 (폼이 제출된 상태여야 보임) ---
            if st.session_state.form_submitted:
                st.divider()
                st.write("### 🧐 최종 내용 확인 및 수정")
                st.write("아래 내용을 확인하고 수정할 부분이 있으면 고치세요. 완료되면 **[최종 저장]**을 누르세요.")
                
                final_m = st.text_area("최종 특이사항", value=st.session_state.edit_memo, height=80, key="final_m_input")
                final_r = st.text_area("최종 총평", value=st.session_state.edit_rev, height=80, key="final_r_input")
                
                if st.button("💾 구글 시트에 최종 저장", type="primary", use_container_width=True):
                    # 세션 스테이트(key)에서 입력값들을 가져옴
                    s_period = f"{st.session_state.in_mon} {st.session_state.in_wk}"
                    
                    row = [
                        selected_student, 
                        s_period, 
                        st.session_state.in_hw, 
                        st.session_state.in_w_sc, 
                        st.session_state.in_w_av, 
                        st.session_state.in_wrong, 
                        final_m, # 수정된 최종본
                        st.session_state.in_a_sc, 
                        st.session_state.in_a_av, 
                        st.session_state.in_a_wrong, 
                        final_r  # 수정된 최종본
                    ]
                    
                    if add_row_to_sheet("weekly", row):
                        st.success("✅ 성적 데이터가 안전하게 저장되었습니다!")
                        st.balloons()
                        # 저장 완료 후 상태 초기화
                        st.session_state.form_submitted = False
                        st.session_state.edit_memo = ""
                        st.session_state.edit_rev = ""
                        # 잠시 후 새로고침 (입력창 비우기)
                        import time
                        time.sleep(1)
                        st.rerun()


        # --- [탭 3] 학부모 리포트 ---
        with tab3:
            st.header(f"📑 {selected_student} 학생 학습 리포트")
            st.divider()

            df_w = load_data_from_sheet("weekly")
            if not df_w.empty:
                my_w = df_w[df_w["이름"] == selected_student]
                if not my_w.empty:
                    periods = my_w["시기"].tolist()
                    sel_p = st.multiselect("기간 선택:", periods, default=periods)
                    
                    if sel_p:
                        rep = my_w[my_w["시기"].isin(sel_p)].copy()

                        def format_wrong(x):
                            s = str(x).strip()
                            if not s or s == '0': return ""
                            s = s.replace(',', ' ')
                            parts = s.split()
                            return ', '.join(parts)

                        if '오답번호' in rep.columns: rep['오답번호'] = rep['오답번호'].apply(format_wrong)
                        if '성취도오답' in rep.columns: rep['성취도오답'] = rep['성취도오답'].apply(format_wrong)

                        st.subheader("1️⃣ 주간 과제 성취도")
                        base = alt.Chart(rep).encode(x=alt.X('시기', sort=None))
                        y_fix = alt.Scale(domain=[0, 100])
                        
                        c1 = (base.mark_line(color='#29b5e8').encode(y=alt.Y('주간점수', scale=y_fix)) + 
                              base.mark_point(color='#29b5e8', size=100).encode(y='주간점수') + 
                              base.mark_text(dy=-15, fontSize=14, color='#29b5e8', fontWeight='bold').encode(y='주간점수', text='주간점수') + 
                              base.mark_line(color='gray', strokeDash=[5,5]).encode(y='주간평균'))
                        st.altair_chart(c1, use_container_width=True)

                        if "성취도점수" in rep.columns and rep["성취도점수"].sum() > 0:
                            st.subheader("2️⃣ 성취도 평가 결과")
                            ach_d = rep[rep["성취도점수"] > 0]
                            base_ach = alt.Chart(ach_d).encode(x=alt.X('시기', sort=None))
                            
                            c2 = (base_ach.mark_line(color='#ff6c6c').encode(y=alt.Y('성취도점수', scale=y_fix)) + 
                                  base_ach.mark_point(color='#ff6c6c', size=100).encode(y='성취도점수') + 
                                  base_ach.mark_text(dy=-15, fontSize=14, color='#ff6c6c', fontWeight='bold').encode(y='성취도점수', text='성취도점수') + 
                                  base_ach.mark_line(color='gray', strokeDash=[5,5]).encode(y='성취도평균'))
                            st.altair_chart(c2, use_container_width=True)

                        st.subheader("3️⃣ 상세 학습 내역")
                        cols = ["시기", "과제", "주간점수", "주간평균", "오답번호", "특이사항", "성취도점수", "성취도평균", "성취도오답"]
                        disp = rep[[c for c in cols if c in rep.columns]].copy()
                        
                        rename_map = {"시기":"시기", "과제":"과제(%)", "주간점수":"점수", "주간평균":"반평균", 
                                      "오답번호":"주간오답", "특이사항":"코멘트", "성취도점수":"성취도", "성취도평균":"성취도평균", "성취도오답":"성취도오답"}
                        disp.rename(columns=rename_map, inplace=True)
                        st.table(disp.set_index("시기"))

                        for i, r in rep.iterrows():
                            if r.get('총평'):
                                st.info(f"**[{r['시기']} 성취도 총평]**\n\n{r['총평']}")
                    else:
                        st.warning("기간을 선택해주세요.")
                else:
                    st.info("데이터가 없습니다.")
