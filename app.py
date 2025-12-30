import streamlit as st
import pandas as pd
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import google.generativeai as genai
import datetime
import altair as alt
import re

# ==========================================
# [설정 1] 구글 시트 ID
# ==========================================
GOOGLE_SHEET_KEY = "1zJHY7baJgoxyFJ5cBduCPVEfQ-pBPZ8jvhZNaPpCLY4"

# ==========================================
# [설정 2] 인증 및 연결 함수
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

def load_data_from_sheet(worksheet_name):
    try:
        client = get_google_sheet_connection()
        if not client: return pd.DataFrame()
        sheet = client.open_by_key(GOOGLE_SHEET_KEY).worksheet(worksheet_name)
        data = sheet.get_all_values() # 문자열로 안전하게 가져오기
        
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
        return True
    except Exception as e:
        st.error(f"저장 실패: {e}")
        return False

# ==========================================
# [설정 3] Gemini AI 설정
# ==========================================
try:
    genai.configure(api_key=st.secrets["GENAI_API_KEY"])
    # 현재 가장 최신 안정화 모델은 1.5-flash 입니다. (2.5는 아직 없습니다!)
    gemini_model = genai.GenerativeModel('gemini-1.5-flash')
except Exception as e:
    gemini_model = None

# AI 도우미 함수
def refine_text_ai(raw_text, context_type):
    if not gemini_model or not raw_text:
        return raw_text
    try:
        prompt = f"""
        당신은 입시 수학 학원의 베테랑 선생님입니다. 
        아래 내용을 학부모님께 보낼 {context_type} 목적으로, 정중하고 신뢰감 있으면서도 명확한 문체로 다듬어주세요.
        핵심 내용은 유지하되 문장을 매끄럽게 교정하세요.
        
        [원문]: {raw_text}
        """
        response = gemini_model.generate_content(prompt)
        return response.text.strip()
    except Exception as e:
        return f"AI 오류 발생: {e}"

# ==========================================
# 메인 앱 화면
# ==========================================
st.set_page_config(page_title="강북청솔 학생 관리", layout="wide")
st.title("👨‍🏫 김성만 선생님의 학생 관리 시스템")

# 세션 상태 초기화 (AI 변환 텍스트 저장용)
if "counsel_final" not in st.session_state: st.session_state.counsel_final = ""
if "weekly_memo_final" not in st.session_state: st.session_state.weekly_memo_final = ""
if "ach_review_final" not in st.session_state: st.session_state.ach_review_final = ""

menu = st.sidebar.radio("메뉴", ["학생 관리 (상담/성적)", "신규 학생 등록"])

# ------------------------------------------
# 1. 신규 학생 등록
# ------------------------------------------
if menu == "신규 학생 등록":
    st.header("📝 신규 학생 등록")
    with st.form("new_student"):
        col1, col2 = st.columns(2)
        name = col1.text_input("학생 이름")
        ban = col2.text_input("반 (Class)")
        origin = st.text_input("출신 중학교")
        target = st.text_input("배정 예정 고등학교")
        addr = st.text_input("거주지 (대략적)")
        
        if st.form_submit_button("등록"):
            if name:
                if add_row_to_sheet("students", [name, ban, origin, target, addr]):
                    st.success(f"{name} 학생 등록 완료!")
                    st.balloons()

# ------------------------------------------
# 2. 학생 관리 (상담/성적/리포트)
# ------------------------------------------
elif menu == "학생 관리 (상담/성적)":
    df_students = load_data_from_sheet("students")
    
    if df_students.empty:
        st.warning("학생 데이터가 없습니다. 먼저 학생을 등록해주세요.")
    else:
        student_list = df_students["이름"].tolist()
        selected_student = st.sidebar.selectbox("학생 선택", student_list)
        
        rows = df_students[df_students["이름"] == selected_student]
        if not rows.empty:
            info = rows.iloc[0]
            ban_txt = info['반'] if '반' in info else ''
            st.sidebar.info(f"**{info['이름']} ({ban_txt})**\n\n🏫 {info['출신중']} ➡️ {info['배정고']}\n🏠 {info['거주지']}")

        tab1, tab2, tab3 = st.tabs(["🗣️ 상담 일지", "📊 주간 학습 & 성취도 입력", "👨‍👩‍👧‍👦 학부모 전송용 리포트"])

        # --- [탭 1] 상담 일지 (AI 적용) ---
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
            
            # AI 입력 프로세스
            c1, c2 = st.columns([3, 1])
            with c1:
                raw_counsel = st.text_area("1. 상담 메모 (대충 적으세요)", height=80, key="raw_counsel_input")
            with c2:
                st.write("")
                st.write("")
                if st.button("✨ AI 다듬기", key="btn_refine_counsel"):
                    with st.spinner("AI가 문장을 다듬고 있습니다..."):
                        refined = refine_text_ai(raw_counsel, "학부모 상담 일지")
                        st.session_state.counsel_final = refined
            
            # 최종 결과 (직접 수정 가능)
            final_counsel = st.text_area("2. 최종 저장될 내용 (수정 가능)", value=st.session_state.counsel_final, height=150, key="final_counsel_input")

            if st.button("💾 상담 내용 저장", type="primary"):
                content_to_save = final_counsel if final_counsel else raw_counsel # 다듬기 안했으면 원본 저장
                if content_to_save:
                    if add_row_to_sheet("counseling", [selected_student, str(c_date), content_to_save]):
                        st.success("저장되었습니다.")
                        st.session_state.counsel_final = "" # 초기화
                        st.rerun()
                else:
                    st.warning("내용을 입력해주세요.")

        # --- [탭 2] 성적 입력 (AI 적용) ---
        with tab2:
            st.subheader("📊 성적 데이터 입력")
            c1, c2 = st.columns(2)
            mon = c1.selectbox("월", [f"{i}월" for i in range(1, 13)])
            wk = c2.selectbox("주차", [f"{i}주차" for i in range(1, 6)])
            period = f"{mon} {wk}"

            # 1. 주간 과제 섹션
            st.markdown("##### 📝 주간 과제")
            cc1, cc2, cc3 = st.columns(3)
            hw = cc1.number_input("수행도(%)", 0, 100, 80)
            w_sc = cc2.number_input("점수", 0, 100, 0)
            w_av = cc3.number_input("반 평균", 0, 100, 0)
            wrong = st.text_input("주간 오답 (띄어쓰기 구분)", placeholder="예: 13 15 22")
            
            # 특이사항 AI 적용
            mc1, mc2 = st.columns([3, 1])
            with mc1:
                raw_memo = st.text_area("특이사항 메모 (대충 적기)", height=60, key="raw_memo")
            with mc2:
                st.write("")
                if st.button("✨ 특이사항 다듬기", key="btn_refine_memo"):
                    with st.spinner("AI 작업 중..."):
                        st.session_state.weekly_memo_final = refine_text_ai(raw_memo, "학생 학습 태도 및 특이사항")
            
            final_memo = st.text_area("최종 특이사항 (확인 및 수정)", value=st.session_state.weekly_memo_final, height=80, key="final_memo")

            st.divider()

            # 2. 성취도 평가 섹션
            st.markdown("##### 🏆 성취도 평가 (해당 시 입력)")
            with st.expander("입력창 열기", expanded=True):
                cc4, cc5 = st.columns(2)
                a_sc = cc4.number_input("성취도 점수", 0, 100, 0)
                a_av = cc5.number_input("성취도 평균", 0, 100, 0)
                a_wrong = st.text_input("성취도 오답 (띄어쓰기 구분)", placeholder="예: 21 29 30")
                
                # 총평 AI 적용
                rc1, rc2 = st.columns([3, 1])
                with rc1:
                    raw_rev = st.text_area("총평 메모 (대충 적기)", height=60, key="raw_rev")
                with rc2:
                    st.write("")
                    if st.button("✨ 총평 다듬기", key="btn_refine_rev"):
                        with st.spinner("AI 작업 중..."):
                            st.session_state.ach_review_final = refine_text_ai(raw_rev, "성취도 평가 총평 및 분석")
                
                final_rev = st.text_area("최종 총평 (확인 및 수정)", value=st.session_state.ach_review_final, height=100, key="final_rev")

            st.write("")
            if st.button("💾 전체 성적 및 평가 저장", type="primary"):
                # 다듬기 버튼 안 눌렀으면 원본 텍스트 사용
                save_memo = final_memo if final_memo else raw_memo
                save_rev = final_rev if final_rev else raw_rev
                
                row = [selected_student, period, hw, w_sc, w_av, wrong, save_memo, a_sc, a_av, a_wrong, save_rev]
                if add_row_to_sheet("weekly", row):
                    st.success("저장 완료!")
                    # 저장 후 텍스트 초기화
                    st.session_state.weekly_memo_final = ""
                    st.session_state.ach_review_final = ""
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

                        # 오답 포맷팅
                        def format_wrong(x):
                            s = str(x).strip()
                            if not s or s == '0': return ""
                            s = s.replace(',', ' ')
                            parts = s.split()
                            return ', '.join(parts)

                        if '오답번호' in rep.columns: rep['오답번호'] = rep['오답번호'].apply(format_wrong)
                        if '성취도오답' in rep.columns: rep['성취도오답'] = rep['성취도오답'].apply(format_wrong)

                        # 1. 그래프 (주간)
                        st.subheader("1️⃣ 주간 과제 성취도")
                        base = alt.Chart(rep).encode(x=alt.X('시기', sort=None))
                        y_fix = alt.Scale(domain=[0, 100])
                        
                        chart1 = (base.mark_line(color='#29b5e8').encode(y=alt.Y('주간점수', scale=y_fix)) + 
                                  base.mark_point(color='#29b5e8', size=100).encode(y='주간점수') + 
                                  base.mark_text(dy=-15, fontSize=14, color='#29b5e8').encode(y='주간점수', text='주간점수') + 
                                  base.mark_line(color='gray', strokeDash=[5,5]).encode(y='주간평균'))
                        st.altair_chart(chart1, use_container_width=True)

                        # 2. 그래프 (성취도)
                        if "성취도점수" in rep.columns and rep["성취도점수"].sum() > 0:
                            st.subheader("2️⃣ 성취도 평가 결과")
                            ach_d = rep[rep["성취도점수"] > 0]
                            base_ach = alt.Chart(ach_d).encode(x=alt.X('시기', sort=None))
                            
                            chart2 = (base_ach.mark_line(color='#ff6c6c').encode(y=alt.Y('성취도점수', scale=y_fix)) + 
                                      base_ach.mark_point(color='#ff6c6c', size=100).encode(y='성취도점수') + 
                                      base_ach.mark_text(dy=-15, fontSize=14, color='#ff6c6c').encode(y='성취도점수', text='성취도점수') + 
                                      base_ach.mark_line(color='gray', strokeDash=[5,5]).encode(y='성취도평균'))
                            st.altair_chart(chart2, use_container_width=True)

                        # 3. 상세 표
                        st.subheader("3️⃣ 상세 학습 내역")
                        cols = ["시기", "과제", "주간점수", "주간평균", "오답번호", "특이사항", "성취도점수", "성취도평균", "성취도오답"]
                        disp = rep[[c for c in cols if c in rep.columns]].copy()
                        
                        rename_map = {"시기":"시기", "과제":"과제(%)", "주간점수":"점수", "주간평균":"반평균", 
                                      "오답번호":"주간오답", "특이사항":"코멘트", "성취도점수":"성취도", "성취도평균":"성취도평균", "성취도오답":"성취도오답"}
                        disp.rename(columns=rename_map, inplace=True)
                        st.table(disp.set_index("시기"))

                        # 4. 총평
                        for i, r in rep.iterrows():
                            if r.get('총평'):
                                st.info(f"**[{r['시기']} 성취도 총평]**\n\n{r['총평']}")
                    else:
                        st.warning("기간을 선택해주세요.")
                else:
                    st.info("데이터가 없습니다.")