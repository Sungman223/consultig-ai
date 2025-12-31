import streamlit as st
import pandas as pd
import gspread
from oauth2client.service_account import ServiceAccountCredentials

# 페이지 설정
st.set_page_config(page_title="학생 관리 시스템", layout="wide")

# 제목
st.title("👨‍🏫 김성만 선생님의 학생 관리 시스템")

# ---------------------------------------------------------
# [중요] 데이터 로드 함수 (에러 추적 기능 포함)
# ---------------------------------------------------------
def load_data():
    try:
        # 1. Secrets 설정 확인
        if "gcp_service_account" not in st.secrets:
            st.error("🚨 [에러] Streamlit Cloud의 'Secrets' 설정이 비어있습니다!")
            st.info("관리자 페이지(Manage app) > Settings > Secrets 에 내용을 붙여넣어 주세요.")
            return None

        # 2. 구글 인증 범위 설정
        scope = [
            "https://spreadsheets.google.com/feeds",
            "https://www.googleapis.com/auth/drive",
        ]

        # 3. Secrets에서 인증 정보 가져오기
        creds_dict = st.secrets["gcp_service_account"]
        creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
        client = gspread.authorize(creds)

        # 4. 스프레드시트 열기 (이름 또는 URL로)
        # 주의: 아래 '학생관리데이터' 부분을 선생님의 실제 구글 시트 이름으로 바꿔주세요!
        sheet_name = "학생관리데이터"  # <-- 여기에 실제 구글 시트 파일 이름을 적어주세요
        
        try:
            sh = client.open(sheet_name)
        except gspread.SpreadsheetNotFound:
            st.error(f"🚨 [에러] '{sheet_name}'라는 이름의 구글 시트를 찾을 수 없습니다.")
            st.info("구글 시트 파일 이름이 정확한지, 공유 설정이 되어있는지 확인해주세요.")
            return None

        # 5. 첫 번째 워크시트(탭) 가져오기
        worksheet = sh.sheet1
        
        # 6. 데이터 가져와서 DataFrame으로 변환
        data = worksheet.get_all_records()
        
        if not data:
            st.warning("⚠️ 구글 시트는 연결되었으나, 데이터가 비어있습니다.")
            return pd.DataFrame() # 빈 데이터프레임 반환

        df = pd.DataFrame(data)
        return df

    except Exception as e:
        # 예상치 못한 다른 모든 에러를 화면에 출력
        st.error(f"🚨 알 수 없는 에러가 발생했습니다: {e}")
        return None

# ---------------------------------------------------------
# 메인 실행 로직
# ---------------------------------------------------------

# 데이터 불러오기 실행
df = load_data()

# 데이터가 정상적으로 있을 때만 화면 표시
if df is not None and not df.empty:
    st.success(f"데이터 로드 성공! 총 {len(df)}명의 학생이 있습니다.")
    
    # 탭 구성
    tab1, tab2 = st.tabs(["📋 학생 목록", "📊 통계"])
    
    with tab1:
        st.dataframe(df)
        
    with tab2:
        st.write("통계 화면 예시입니다.")
        
# 데이터가 없을 때 (위에서 에러 메시지가 이미 떴을 것임)
else:
    st.warning("학생 데이터가 없습니다. 위의 빨간색 에러 메시지를 확인해주세요.")
