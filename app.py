import streamlit as st
import pandas as pd
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import requests # REST API 통신용
import json
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
# [설정 3] Gemini 2.0 Flash API 호출 (문체 수정판)
# ==========================================
def refine_text_ai(raw_text, context_type, student_name): # 학생 이름 추가
    if not raw_text:
        return raw_text
        
    try:
        api_key = st.secrets["GENAI_API_KEY"]
        url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash-exp:generateContent?key={api_key}"
        
        headers = {'Content-Type': 'application/json'}
        
        # [프롬프트 대폭 수정] : 편지 형식 금지, 이름 포함, 간결하게
        prompt_text = f"""
        당신은 입시 수학 학원의 김성만 선생님입니다.
        아래 메모는 '{student_name}' 학생에 대한 내용입니다.
        이 내용을 학부모님께 전달하거나 기록으로 남길 수 있도록 '정중하고 전문적인 문체'로 다듬어주세요.

        [지침사항]
        1. **절대 편지 형식으로 쓰지 마세요.** (안녕하세요, 드림, 날짜 등 금지)
        2. 학생 이름 '{student_name}'을 문장 주어로 자연스럽게 사용하세요.
        3. 너무 장황하게 늘리지 말고, 핵심 내용을 간결하게 요약/정리하세요.
        4. 오타나 비문이 있다면 자연스럽게 교정하세요.
        
        [원문]: {raw_text}
        """
        
        data = {
            "contents": [{
                "parts": [{"text": prompt_text}]
            }]
        }
        
        response = requests.post(url, headers=headers, data=json.dumps(data))
        
        if response.status_code == 200:
            result = response.json()
            return result['candidates'][0]['content']['parts'][0]['text']
        else:
            return f"AI 연결 오류 ({response.status_code}): {response.text}"
            
    except Exception as e:
        return f"통신 오류 발생: {e}"

# ==========================================
# 메인 앱 화면
# ==========================================
st.set_page_config(page_title="강북청솔 학생 관리", layout="wide")
st.title("👨‍🏫 김성만 선생님의 학생 관리 시스템")

# [세션 초기화]
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
