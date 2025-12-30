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

# ------------------------------------------
# [유틸리티] 데이터 정리 함수들
# ------------------------------------------
def sort_numbers_string(text):
    """오답 번호 자동 정렬"""
    if not text: return ""
    numbers = re.findall(r'\d+', str(text))
    if not numbers: return text
    sorted_nums = sorted([int(n) for n in numbers])
    return ", ".join(map(str, sorted_nums))

def format_middle_school(text):
    """중학교 이름 자동 완성 (풍생 -> 풍생중, 풍생중학교 -> 풍생중)"""
    if not text: return ""
    text = text.strip()
    if text.endswith("중학교"):
        return text.replace("중학교", "중")
    if not text.endswith("중"):
        return text + "중"
    return text

def format_high_school(text):
    """고등학교 이름 자동 완성 (풍생 -> 풍생고, 풍생고등학교 -> 풍생고)"""
    if not text: return ""
    text = text.strip()
    if text.endswith("고등학교"):
        return text.replace("고등학교", "고")
    if not text.endswith("고"):
        return text + "고"
    return text

def clean_class_name(text):
    """반 이름 대문자 변환"""
    if not text: return ""
    return text.upper().strip()

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

menu = st.sidebar.radio("메뉴", ["학생 관리 (상담/성적)", "신규 학생 등록"])

# ------------------------------------------
# 1. 신규 학생 등록 (학교명 자동완성 적용)
# ------------------------------------------
if menu == "신규 학생 등록":
    st.header("📝 신규 학생 등록")
    st.info("💡 팁: 학교 이름에 '풍생'만 적어도 자동으로 '풍생중', '풍생고'로 저장됩니다.")
    
    with st.form("new_student_form"):
        col1, col2 = st.columns(2)
        name = col1.text_input("학생 이름")
        ban = col2.text_input("반 (예: m1 -> M1)")
        origin = st.text_input("출신 중학교 (예: 풍생 -> 풍생중)")
        target = st.text_input("배정 예정 고등학교 (예: 풍생 -> 풍생고)")
        addr = st.text_input("거주지 (대략적)")
        
        if st.form_submit_button("💾 학생 등록"):
            if name:
                # [핵심] 입력값 자동 표준화
                clean_ban = clean_class_name(ban)
                clean_origin = format_middle_school(origin) # 중학교 자동완성
                clean_target = format_high_school(target)   # 고등학교 자동완성
                
                if add_row_to_sheet("students", [name, clean_ban, clean_origin, clean_target, addr]):
                    st.success(f"{name} 학생 등록 완료! ({clean_ban}, {clean_origin} -> {clean_target})")

# ------------------------------------------
# 2. 학생 관리
# ------------------------------------------
elif menu == "학생 관리 (상담/성적)":
    df_students = load_data_from_sheet("students")
    
    if df_students.empty:
        st.warning("학생 데이터가 없습니다. (구글 시트 연결 확인 필요)")
    else:
        # 사이드바 리스트 (이름 + 반)
        student_display_list = [f"{row['이름']} ({row['반']})" for idx, row in df_students.iterrows()]
        selected_display = st.sidebar.selectbox("학생 선택", student_display_list)
        selected_student = selected_display.split(" (")[0]
        
        rows = df_students[df_students["이름"] == selected_student]
        if not rows.empty:
            info = rows.iloc[0]
            ban_txt = info['반'] if '반' in info else ''
            st.sidebar.info(f"**{info['이름']} ({ban_txt})**\n\n🏫 {info['출신중']} ➡️ {info['배정고']}\n🏠 {info['거주지']}")

        st.write("")
        # 고정형 메뉴바 (튕김 방지)
        selected_tab = st.radio(
            "작업 선택", 
            ["🗣️ 상담 일지", "📊 성적 입력", "👨‍👩‍👧‍👦 리포트"], 
            horizontal=True,
            label_visibility="collapsed"
        )
        st.divider()

        # --- [화면 1] 상담 일지 ---
        if selected_tab == "🗣️ 상담 일지":
            st.subheader(f"{selected_student} 상담 기록")
            df_c = load_data_from_sheet("counseling")
            with st.expander("📂 이전 상담 내역"):
                if not df_c.empty:
                    logs = df_c[df_c["이름"] == selected_student]
                    if '날짜' in logs.columns: logs = logs.sort_values(by='날짜', ascending=False)
                    for _, r in logs.iterrows():
                        st.markdown(f"**🗓️ {r['날짜']}**")
                        st.info(r['내용'])

            st.write("#### ✍️ 새로운 상담 입력")
            c_date = st.date_input("날짜", datetime.date.today())
            raw_c = st.text_area("1. 상담 메모 (대충 적으세요)", height=80, key="raw_c_input")
            
            if st.button("✨ AI 변환 (선택 사항)", key="btn_c_ai"):
                with st.spinner("AI가 문장을 다듬는 중..."):
                    ai_result = refine_text_ai(raw_c, "학부모 상담 일지", selected_student)
                    st.session_state['final_c_input'] = ai_result 
                    st.rerun()

            final_c = st.text_area("2. 최종 내용 (변환된 내용을 수정하거나, 직접 입력하세요)", height=150, key="final_c_input")

            if st.button("💾 상담 내용 저장", type="primary", key="btn_c_save"):
                content_to_save = final_c if final_c.strip() else raw_c
                
                if content_to_save:
                    if add_row_to_sheet("counseling", [selected_student, str(c_date), content_to_save]):
                        st.success("저장 완료!")
                        if 'final_c_input' in st.session_state: del st.session_state['final_c_input']
                        st.rerun()
                else:
                    st.warning("내용이 없습니다.")


        # --- [화면 2] 성적 입력 ---
        elif selected_tab == "📊 성적 입력":
            st.subheader("📊 성적 데이터 입력")
            
            c1, c2 = st.columns(2)
            mon = c1.selectbox("월", [f"{i}월" for i in range(1, 13)])
            wk = c2.selectbox("주차", [f"{i}주차" for i in range(1, 6)])
            period = f"{mon} {wk}"

            st.markdown("##### 📝 주간 과제 & 점수")
            cc1, cc2, cc3 = st.columns(3)
            hw = cc1.number_input("수행도(%)", 0, 100, 80)
            w_sc = cc2.number_input("주간 과제 점수", 0, 100, 0)
            w_av = cc3.number_input("주간과제 평균점수", 0, 100, 0)
            wrong = st.text_input("주간 과제 오답 번호 (막 적어도 자동 정렬됨)", placeholder="예: 3 1 2")
            
            st.divider()

            # [특이사항 섹션]
            st.markdown("##### 📢 학습 태도 및 특이사항")
            raw_m = st.text_area("특이사항 메모 (대충 적기)", height=70, key="raw_m_input")
            
            if st.button("✨ 특이사항 AI 변환", key="btn_m_ai"):
                with st.spinner("AI 변환 중..."):
                    ai_result = refine_text_ai(raw_m, "학습 태도 특이사항", selected_student)
                    st.session_state['final_m_input'] = ai_result
                    st.rerun()

            final_m = st.text_area("최종 특이사항 (수정 가능)", height=80, key="final_m_input")

            st.divider()

            # [성취도 평가 섹션]
            st.markdown("##### 🏆 성취도 평가")
            cc4, cc5 = st.columns(2)
            a_sc = cc4.number_input("성취도 평가 점수", 0, 100, 0)
            a_av = cc5.number_input("성취도 평가 점수 평균", 0, 100, 0)
            a_wrong = st.text_input("성취도평가 오답번호 (막 적어도 자동 정렬됨)", placeholder="예: 21 29 30")
            
            st.markdown("##### 📝 성취도 총평")
            raw_r = st.text_area("총평 메모 (대충 적기)", height=70, key="raw_r_input")
            
            if st.button("✨ 총평 AI 변환", key="btn_r_ai"):
                with st.spinner("AI 변환 중..."):
