import streamlit as st
import pandas as pd
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import requests
import json
import datetime
import altair as alt
import re
from pypdf import PdfReader

# ==========================================
# 1. 페이지 설정
# ==========================================
st.set_page_config(page_title="강북청솔 학생 관리", layout="wide")
st.title("👨‍🏫 김성만 선생님의 학생 관리 시스템")

# ==========================================
# 2. 구글 시트 및 API 설정
# ==========================================
GOOGLE_SHEET_KEY = "1zJHY7baJgoxyFJ5cBduCPVEfQ-pBPZ8jvhZNaPpCLY4"

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

# ==========================================
# 3. 유틸리티 함수
# ==========================================
def sort_numbers_string(text):
    if not text: return ""
    numbers = re.findall(r'\d+', str(text))
    if not numbers: return text
    sorted_nums = sorted([int(n) for n in numbers])
    return ", ".join(map(str, sorted_nums))

def clean_school_name(text, target_type="middle"):
    if not text: return ""
    text = text.strip()
    root_name = re.sub(r'(고등학교|중학교|고등|중학|고|중)$', '', text)
    if target_type == "middle":
        return root_name + "중"
    else:
        return root_name + "고"

def clean_class_name(text):
    if not text: return ""
    return text.upper().strip()

# ==========================================
# 4. AI 함수 (Gemini)
# ==========================================
def refine_text_ai(raw_text, context_type, student_name):
    if not raw_text: return ""
    try:
        api_key = st.secrets["GENAI_API_KEY"]
        url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash-exp:generateContent?key={api_key}"
        headers = {'Content-Type': 'application/json'}
        prompt_text = f"""
        당신은 입시 수학 학원의 베테랑 선생님입니다. 
        아래 메모는 '{student_name}' 학생에 대한 내용입니다.
        학부모님께 전달할 수 있도록 '정중하고 전문적인 문체'로 다듬어주세요.
        핵심 내용은 유지하되 문장을 매끄럽게 교정하세요.
        [지침] 제목/인사말 제외, 본론만 작성, 학생 이름 주어 사용.
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

# [AI 분석 함수] - 학부모용 vs 학생용(따뜻한 버전)
def analyze_homework_ai(student_name, wrong_numbers, assignment_text, type_name="과제", target_audience="학부모 전송용"):
    if not wrong_numbers or not assignment_text:
        return "오답 번호와 PDF 내용이 필요합니다."
    
    try:
        api_key = st.secrets["GENAI_API_KEY"]
        url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash-exp:generateContent?key={api_key}"
        headers = {'Content-Type': 'application/json'}
        
        # ---------------------------------------------------------
        # 1. 학부모 전송용 프롬프트 (기존 유지)
        # ---------------------------------------------------------
        if target_audience == "학부모 전송용":
            prompt_text = f"""
            당신은 신뢰감 있는 입시 수학 선생님입니다.
            학생 이름: {student_name}
            틀린 문제: {wrong_numbers}
            분석 대상: {type_name}
            
            [과제/시험 텍스트 일부]:
            {assignment_text[:15000]}
            
            [요청 사항]
            **학부모님께 보낼 피드백 메시지**를 작성하세요.
            1. 학생이 틀린 문제들이 어떤 수학적 개념(유형)인지 전문가처럼 간략히 분석해주세요.
            2. 부모님이 안심할 수 있도록 아래 3가지 대책을 포함해주세요:
               - 수업 시간 내 해당 문항 상세 해설 진행
               - 밴드(Band)에 해설 영상 업로드 완료
               - 카카오톡 또는 대면을 통한 1:1 개별 질문 해결
            3. 문체: 정중하고 예의 바른 '해요체' (너무 딱딱하지 않게).
            4. 구성: 인사 생략, 분석 내용 -> 관리 계획 순서.
            """
            
        # ---------------------------------------------------------
        # 2. 학생 배부용 프롬프트 (따뜻하고 상세하게 수정됨)
        # ---------------------------------------------------------
        else:
            prompt_text = f"""
            당신은 학생을 진심으로 아끼는 따뜻하고 친절한 수학 멘토 선생님입니다.
            학생 이름: {student_name}
            틀린 문제: {wrong_numbers}
            분석 대상: {type_name}
            
            [과제/시험 텍스트 일부]:
            {assignment_text[:15000]}
            
            [요청 사항]
            **학생({student_name})에게 줄 따뜻하고 상세한 학습 가이드**를 작성하세요.
            
            1. **상세한 유형 분석**: 
               - 단순히 "너 이거 틀렸어"가 아니라, "이 문제는 A개념과 B개념이 섞여 있어서 접근하기 조금 까다로웠을 거야"라는 식으로 학생 입장에서 공감하며 문제의 핵심 원리를 자세히 설명해주세요.
            
            2. **따뜻한 격려와 학습 방향**:
               - "틀려도 괜찮아, 지금 알면 돼", "이 부분만 보완하면 훨씬 좋아질 거야" 같은 용기를 주는 말을 꼭 넣어주세요.
               - 구체적으로 어떤 공식을 다시 보면 좋을지 팁을 주세요.
            
            3. **질문 유도 (필수)**:
               - "혼자 끙끙 앓지 말고, 언제든 **밴드**나 **카톡**으로 쌤한테 질문해! 밤 늦게도 괜찮아, 쌤이 다 받아줄게!" 라는 뉘앙스로 마무리해주세요.
            
            4. **문체**: 
               - 친근한 선생님 말투 (반말과 존댓말을 자연스럽게 섞거나, 부드러운 해요체 사용). 딱딱하지 않게.
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
# 5. 콜백 함수
# ==========================================
def save_counseling_callback(student, date):
    raw = st.session_state.get('c_raw_input', "")
    final = st.session_state.get('c_final_input', "")
    content_to_save = final.strip() if final.strip() else raw.strip()
    
    if content_to_save:
        if add_row_to_sheet("counseling", [student, str(date), content_to_save]):
            st.toast(f"✅ {student} 상담 내용 저장 완료!")
            st.session_state['c_raw_input'] = ""
            st.session_state['c_final_input'] = ""
    else:
        st.toast("⚠️ 내용이 없어 저장하지 않았습니다.")

def save_grades_callback(student, period):
    hw = st.session_state.get('g_hw', 80)
    w_sc = st.session_state.get('g_w_sc', 0)
    w_av = st.session_state.get('g_w_av', 0)
    wrong = st.session_state.get('g_wrong', "")
    
    raw_m = st.session_state.get('g_raw_m', "")
    final_m = st.session_state.get('g_final_m', "")
    save_m = final_m.strip() if final_m.strip() else raw_m.strip()
    
    a_sc = st.session_state.get('g_a_sc', 0)
    a_av = st.session_state.get('g_a_av', 0)
    a_wrong = st.session_state.get('g_a_wrong', "")
    
    raw_r = st.session_state.get('g_raw_r', "")
    final_r = st.session_state.get('g_final_r', "")
    save_r = final_r.strip() if final_r.strip() else raw_r.strip()
    
    sorted_wrong = sort_numbers_string(wrong)
    sorted_a_wrong = sort_numbers_string(a_wrong)
    
    row = [student, period, hw, w_sc, w_av, sorted_wrong, save_m, a_sc, a_av, sorted_a_wrong, save_r]
    
    if add_row_to_sheet("weekly", row):
        st.toast(f"✅ {student} 성적 저장 완료! 입력창을 비웠습니다.")
        # 모든 입력창 초기화
        st.session_state['g_hw'] = 80
        st.session_state['g_w_sc'] = 0
        st.session_state['g_w_av'] = 0
        st.session_state['g_wrong'] = ""
        st.session_state['g_raw_m'] = ""
        st.session_state['g_final_m'] = ""
        st.session_state['g_a_sc'] = 0
        st.session_state['g_a_av'] = 0
        st.session_state['g_a_wrong'] = ""
        st.session_state['g_raw_r'] = ""
        st.session_state['g_final_r'] = ""
        if 'g_pdf_text' in st.session_state: st.session_state['g_pdf_text'] = ""
        if 'g_ach_pdf_text' in st.session_state: st.session_state['g_ach_pdf_text'] = ""

# ==========================================
# 6. 메인 앱 화면
# ==========================================
menu = st.sidebar.radio("메뉴", ["학생 관리 (상담/성적)", "신규 학생 등록"])

if menu == "신규 학생 등록":
    st.header("📝 신규 학생 등록")
    st.info("💡 팁: '풍생'만 입력해도 '풍생중', '풍생고'로 자동 변환됩니다.")
    
    with st.form("new_student_form", clear_on_submit=True):
        col1, col2 = st.columns(2)
        name = col1.text_input("학생 이름")
        ban = col2.text_input("반 (예: M1, S1)")
        origin = st.text_input("출신 중학교 (예: 풍생)")
        target = st.text_input("배정 예정 고등학교 (예: 풍생)")
        addr = st.text_input("거주지 (대략적)")
        
        if st.form_submit_button("💾 학생 등록"):
            if name:
                clean_ban = clean_class_name(ban)
                clean_origin = clean_school_name(origin, "middle")
                clean_target = clean_school_name(target, "high")
                
                if add_row_to_sheet("students", [name, clean_ban, clean_origin, clean_target, addr]):
                    st.success(f"✅ {name} 등록 완료! ({clean_ban}, {clean_origin} -> {clean_target})")

elif menu == "학생 관리 (상담/성적)":
    df_students = load_data_from_sheet("students")
    
    if df_students.empty:
        st.warning("등록된 학생 데이터가 없습니다.")
    else:
        if '반' in df_students.columns:
            ban_list = sorted(df_students['반'].unique().tolist())
            selected_ban = st.sidebar.selectbox("📂 반 선택", ban_list)
            filtered_students = df_students[df_students['반'] == selected_ban]
            student_list = sorted(filtered_students['이름'].tolist())
            
            if student_list:
                selected_student = st.sidebar.selectbox("👤 학생 선택", student_list)
            else:
                st.sidebar.warning("해당 반에 학생이 없습니다.")
                selected_student = None
        else:
            st.error("데이터 시트에 '반' 컬럼이 없습니다.")
            selected_student = None

        if selected_student:
            rows = df_students[df_students["이름"] == selected_student]
            if not rows.empty:
                info = rows.iloc[0]
                ban_txt = info['반'] if '반' in info else ''
                st.sidebar.info(f"**{info['이름']} ({ban_txt})**\n\n🏫 {info['출신중']} ➡️ {info['배정고']}\n🏠 {info['거주지']}")

            st.write("")
            selected_tab = st.radio("작업 선택", ["🗣️ 상담 일지", "📊 성적 입력", "👨‍👩‍👧‍👦 리포트"], horizontal=True, label_visibility="collapsed")
            st.divider()

            # --- [탭 1] 상담 일지 ---
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
                
                if 'c_raw_input' not in st.session_state: st.session_state['c_raw_input'] = ""
                if 'c_final_input' not in st.session_state: st.session_state['c_final_input'] = ""

                raw_c = st.text_area("1. 상담 메모", height=80, key="c_raw_input")
                
                if st.button("✨ AI 변환", key="btn_c_ai"):
                    with st.spinner("변환 중..."):
                        ai_result = refine_text_ai(raw_c, "학부모 상담 일지", selected_student)
                        st.session_state['c_final_input'] = ai_result 
                        st.rerun()
                
                final_c = st.text_area("2. 최종 내용", height=150, key="c_final_input")
                st.button("💾 상담 내용 저장", type="primary", on_click=save_counseling_callback, args=(selected_student, c_date))

            # --- [탭 2] 성적 입력 ---
            elif selected_tab == "📊 성적 입력":
                st.subheader("📊 성적 데이터 입력")
                
                c1, c2 = st.columns(2)
                mon = c1.selectbox("월", [f"{i}월" for i in range(1, 13)])
                wk = c2.selectbox("주차", [f"{i}주차" for i in range(1, 6)])
                period = f"{mon} {wk}"

                # 세션 초기화
                if 'g_hw' not in st.session_state: st.session_state['g_hw'] = 80
                if 'g_w_sc' not in st.session_state: st.session_state['g_w_sc'] = 0
                if 'g_w_av' not in st.session_state: st.session_state['g_w_av'] = 0
                if 'g_wrong' not in st.session_state: st.session_state['g_wrong'] = ""
                if 'g_raw_m' not in st.session_state: st.session_state['g_raw_m'] = ""
                if 'g_final_m' not in st.session_state: st.session_state['g_final_m'] = ""
                if 'g_a_sc' not in st.session_state: st.session_state['g_a_sc'] = 0
                if 'g_a_av' not in st.session_state: st.session_state['g_a_av'] = 0
                if 'g_a_wrong' not in st.session_state: st.session_state['g_a_wrong'] = ""
                if 'g_raw_r' not in st.session_state: st.session_state['g_raw_r'] = ""
                if 'g_final_r' not in st.session_state: st.session_state['g_final_r'] = ""
                
                # PDF 텍스트 저장용 세션
                if 'g_pdf_text' not in st.session_state: st.session_state['g_pdf_text'] = ""
                if 'g_ach_pdf_text' not in st.session_state: st.session_state['g_ach_pdf_text'] = ""

                st.markdown("##### 📝 주간 과제 & 점수")
                cc1, cc2, cc3 = st.columns(3)
                st.number_input("수행도(%)", 0, 100, key="g_hw")
                st.number_input("주간 과제 점수", 0, 100, key="g_w_sc")
                st.number_input("주간과제 평균점수", 0, 100, key="g_w_av")
                st.text_input("주간 과제 오답 번호", placeholder="예: 3 1 2", key="g_wrong")
                
                # --- [주간과제] PDF 분석 ---
                with st.expander("✨ [AI] 주간과제 오답 분석", expanded=False):
                    uploaded_file = st.file_uploader("📄 과제 PDF 파일 업로드", type=["pdf"], key="file_homework")
                    if uploaded_file is not None:
                        try:
                            reader = PdfReader(uploaded_file)
                            text_content = ""
                            for page in reader.pages:
                                text_content += page.extract_text() + "\n"
                            st.session_state['g_pdf_text'] = text_content
                            st.success(f"PDF 로드 성공! (총 {len(reader.pages)}페이지)")
                        except Exception as e:
                            st.error(f"PDF 읽기 실패: {e}")
                    
                    target_h = st.radio("분석 글 대상 선택:", ["학부모 전송용", "학생 배부용"], horizontal=True, key="target_h")

                    if st.button("🚀 주간과제 분석 실행", type="secondary"):
                        wrong_nums = st.session_state.get('g_wrong', "")
                        pdf_text = st.session_state.get('g_pdf_text', "")

                        if not wrong_nums.strip():
                            st.error("오답 번호를 입력해주세요!")
                        elif not pdf_text.strip():
                            st.error("PDF 파일을 업로드해주세요!")
                        else:
                            with st.spinner(f"Gemini가 {target_h}으로 분석 중입니다..."):
                                analysis_msg = analyze_homework_ai(selected_student, wrong_nums, pdf_text, "주간과제", target_h)
                                st.session_state['g_raw_m'] = analysis_msg
                                st.rerun()
                
                st.markdown("##### 📢 학습 태도 및 특이사항")
                raw_m = st.text_area("특이사항 메모", height=150, key="g_raw_m")
                
                if st.button("✨ 문체 교정 (AI)", key="btn_m_ai"):
                    with st.spinner("변환 중..."):
                        res = refine_text_ai(raw_m, "학습 태도 특이사항", selected_student)
                        st.session_state['g_final_m'] = res
                        st.rerun()
                
                st.text_area("최종 특이사항", height=100, key="g_final_m")
                
                st.divider()

                st.markdown("##### 🏆 성취도 평가")
                cc4, cc5 = st.columns(2)
                st.number_input("성취도 평가 점수", 0, 100, key="g_a_sc")
                st.number_input("성취도 평가 점수 평균", 0, 100, key="g_a_av")
                st.text_input("성취도평가 오답번호", placeholder="예: 21 29 30", key="g_a_wrong")
                
                # --- [성취도평가] PDF 분석 ---
                with st.expander("✨ [AI] 성취도 시험지 분석", expanded=False):
                    ach_file = st.file_uploader("📄 성취도 시험지 PDF 업로드", type=["pdf"], key="file_achievement")
                    if ach_file is not None:
                        try:
                            reader_ach = PdfReader(ach_file)
                            ach_text_content = ""
                            for page in reader_ach.pages:
                                ach_text_content += page.extract_text() + "\n"
                            st.session_state['g_ach_pdf_text'] = ach_text_content
                            st.success(f"시험지 로드 성공! (총 {len(reader_ach.pages)}페이지)")
                        except Exception as e:
                            st.error(f"PDF 읽기 실패: {e}")

                    target_a = st.radio("분석 글 대상 선택:", ["학부모 전송용", "학생 배부용"], horizontal=True, key="target_a")

                    if st.button("🚀 성취도 오답 분석 실행", type="secondary"):
                        a_wrong_nums = st.session_state.get('g_a_wrong', "")
                        a_pdf_text = st.session_state.get('g_ach_pdf_text', "")

                        if not a_wrong_nums.strip():
                            st.error("성취도 오답 번호를 입력해주세요!")
                        elif not a_pdf_text.strip():
                            st.error("시험지 PDF를 업로드해주세요!")
                        else:
                            with st.spinner(f"Gemini가 {target_a}으로 분석 중입니다..."):
                                analysis_msg = analyze_homework_ai(selected_student, a_wrong_nums, a_pdf_text, "성취도평가", target_a)
                                st.session_state['g_raw_r'] = analysis_msg
                                st.rerun()

                st.markdown("##### 📝 성취도 총평")
                raw_r = st.text_area("총평 메모", height=150, key="g_raw_r")
                if st.button("✨ 단순 문체 교정 (AI)", key="btn_r_ai"):
                    with st.spinner("변환 중..."):
                        res = refine_text_ai(raw_r, "성취도 평가 총평", selected_student)
                        st.session_state['g_final_r'] = res
                        st.rerun()
                st.text_area("최종 총평", height=100, key="g_final_r")
                
                st.divider()
                
                st.button("💾 전체 성적 및 평가 저장", type="primary", use_container_width=True, on_click=save_grades_callback, args=(selected_student, period))

            # --- [탭 3] 리포트 ---
            elif selected_tab == "👨‍👩‍👧‍👦 리포트":
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
                            cols = ["시기", "과제", "주간점수", "주간평균", "오답번호", "특이사항", "성취도점수", "성취도평균", "성취도오답", "총평"]
                            disp = rep[[c for c in cols if c in rep.columns]].copy()
                            rename_map = {"시기":"시기", "과제":"과제(%)", "주간점수":"주간과제점수", "주간평균":"반평균", 
                                          "오답번호":"주간과제오답", "특이사항":"코멘트", "성취도점수":"성취도평가점수", "성취도평균":"성취도평균", 
                                          "성취도오답":"성취도오답", "총평":"성취도총평"}
                            disp.rename(columns=rename_map, inplace=True)
                            st.table(disp.set_index("시기"))
                        else:
                            st.warning("기간을 선택해주세요.")
                    else:
                        st.info("데이터가 없습니다.")
