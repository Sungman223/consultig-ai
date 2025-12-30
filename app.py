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
        return True
    except Exception as e:
        st.error(f"저장 실패: {e}")
        return False

# ==========================================
# [설정 3] Gemini AI 설정
# ==========================================
try:
    genai.configure(api_key=st.secrets["GENAI_API_KEY"])
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
        return f"AI 오류: {e}"

# ==========================================
# 메인 앱 화면
# ==========================================
st.set_page_config(page_title="강북청솔 학생 관리", layout="wide")
st.title("👨‍🏫 김성만 선생님의 학생 관리 시스템")

# [세션 초기화] - AI 결과를 저장할 변수들
if "counsel_result" not in st.session_state: st.session_state.counsel_result = ""
if "memo_result" not in st.session_state: st.session_state.memo_result = ""
if "rev_result" not in st.session_state: st.session_state.rev_result = ""

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
# 2. 학생 관리
# ------------------------------------------
elif menu == "학생 관리 (상담/성적)":
    df_students = load_data_from_sheet("students")
    
    if df_students.empty:
        st.warning("학생 데이터가 없습니다.")
    else:
        student_list = df_students["이름"].tolist()
        selected_student = st.sidebar.selectbox("학생 선택", student_list)
        
        rows = df_students[df_students["이름"] == selected_student]
        if not rows.empty:
            info = rows.iloc[0]
            ban_txt = info['반'] if '반' in info else ''
            st.sidebar.info(f"**{info['이름']} ({ban_txt})**\n\n🏫 {info['출신중']} ➡️ {info['배정고']}\n🏠 {info['거주지']}")

        tab1, tab2, tab3 = st.tabs(["🗣️ 상담 일지 (AI)", "📊 주간 학습 & 성취도 입력", "👨‍👩‍👧‍👦 학부모 전송용 리포트"])

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
            
            # 1. 입력창
            raw_c = st.text_area("1. 상담 메모 (대충 적으세요)", height=80, key="input_counsel")
            
            # 2. AI 버튼
            if st.button("✨ AI 다듬기", key="btn_c"):
                if raw_c:
                    with st.spinner("AI가 문장을 다듬고 있습니다..."):
                        # AI 결과 -> 세션 저장
                        st.session_state.counsel_result = refine_text_ai(raw_c, "학부모 상담 일지")
                else:
                    st.warning("내용을 먼저 입력해주세요.")

            # 3. 결과창 (세션 값을 기본값으로 사용)
            # 사용자가 여기서 수정하면 그 값이 final_c에 담김
            final_c = st.text_area("2. 최종 저장될 내용 (수정 가능)", value=st.session_state.counsel_result, height=150)

            # 4. 저장 버튼
            if st.button("💾 상담 내용 저장", type="primary"):
                # AI 안 썼으면 원본(raw_c) 저장, 썼으면 수정본(final_c) 저장
                content_to_save = final_c if final_c else raw_c
                
                if content_to_save:
                    if add_row_to_sheet("counseling", [selected_student, str(c_date), content_to_save]):
                        st.success("저장되었습니다.")
                        st.session_state.counsel_result = "" # 저장 후 초기화
                        st.rerun()
                else:
                    st.warning("내용이 없습니다.")

        # --- [탭 2] 성적 입력 ---
        with tab2:
            st.subheader("📊 성적 데이터 입력")
            c1, c2 = st.columns(2)
            mon = c1.selectbox("월", [f"{i}월" for i in range(1, 13)])
            wk = c2.selectbox("주차", [f"{i}주차" for i in range(1, 6)])
            period = f"{mon} {wk}"

            st.markdown("##### 📝 주간 과제")
            cc1, cc2, cc3 = st.columns(3)
            hw = cc1.number_input("수행도(%)", 0, 100, 80)
            w_sc = cc2.number_input("점수", 0, 100, 0)
            w_av = cc3.number_input("반 평균", 0, 100, 0)
            wrong = st.text_input("주간 오답 (띄어쓰기 구분)", placeholder="예: 13 15 22")
            
            # 특이사항 AI
            raw_m = st.text_area("특이사항 메모 (대충 적기)", height=60, key="input_memo")
            if st.button("✨ 특이사항 다듬기", key="btn_m"):
                if raw_m:
                    with st.spinner("AI 작업 중..."):
                        st.session_state.memo_result = refine_text_ai(raw_m, "학습 태도 특이사항")
            
            final_m = st.text_area("최종 특이사항", value=st.session_state.memo_result, height=80)

            st.divider()

            st.markdown("##### 🏆 성취도 평가")
            with st.expander("입력창 열기", expanded=True):
                cc4, cc5 = st.columns(2)
                a_sc = cc4.number_input("성취도 점수", 0, 100, 0)
                a_av = cc5.number_input("성취도 평균", 0, 100, 0)
                a_wrong = st.text_input("성취도 오답 (띄어쓰기 구분)", placeholder="예: 21 29 30")
                
                # 총평 AI
                raw_r = st.text_area("총평 메모 (대충 적기)", height=60, key="input_rev")
                if st.button("✨ 총평 다듬기", key="btn_r"):
                    if raw_r:
                        with st.spinner("AI 작업 중..."):
                            st.session_state.rev_result = refine_text_ai(raw_r, "성취도 평가 총평")
                
                final_r = st.text_area("최종 총평", value=st.session_state.rev_result, height=100)

            st.write("")
            if st.button("💾 전체 성적 및 평가 저장", type="primary"):
                # AI 결과 없으면 원본 저장
                save_m = final_m if final_m else raw_m
                save_r = final_r if final_r else raw_r
                
                row = [selected_student, period, hw, w_sc, w_av, wrong, save_m, a_sc, a_av, a_wrong, save_r]
                if add_row_to_sheet("weekly", row):
                    st.success("저장 완료!")
                    # 초기화
                    st.session_state.memo_result = ""
                    st.session_state.rev_result = ""
                    st.rerun()

        # --- [탭 3] 학부모 리포트 ---
        with tab3:
