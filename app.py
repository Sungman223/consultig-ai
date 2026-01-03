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
        
        # 숫자형 변환 (에러 방지)
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

def analyze_homework_ai(student_name, wrong_numbers, assignment_text, type_name="과제", target_audience="학부모 전송용"):
    if not wrong_numbers or not assignment_text:
        return "오답 번호와 PDF 내용이 필요합니다."
    
    try:
        api_key = st.secrets["GENAI_API_KEY"]
        url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash-exp:generateContent?key={api_key}"
        headers = {'Content-Type': 'application/json'}
        
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
            1. **상세한 유형 분석**: "이 문제는 A개념과 B개념이 섞여 있어서 까다로웠을 거야"라고 학생 입장에서 공감하며 핵심 원리를 설명해주세요.
            2. **따뜻한 격려**: "틀려도 괜찮아", "이 부분만 보완하면 훨씬 좋아질 거야" 같은 용기를 주는 말을 넣어주세요.
            3. **질문 유도 (필수)**: "밴드나 카톡으로 언제든 질문해! 쌤이 다 받아줄게!"라는 내용을 꼭 포함해주세요.
            4. **문체**: 친근한 선생님 말투 (부드러운 해요체).
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
# 5. 콜백 함수 (데이터 저장 로직 수정됨)
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
    # [NEW] 과제명 & 시험명
    hw_name = st.session_state.get('g_hw_name', "-")
    ach_name = st.session_state.get('g_ach_name', "-")

    # 주간 과제 데이터
    hw = st.session_state.get('g_hw', 80)
    w_sc = st.session_state.get('g_w_sc', 0)
    w_av = st.session_state.get('g_w_av', 0)
    wrong = st.session_state.get('g_wrong', "")
    
    w_analysis = st.session_state.get('g_w_analysis', "")

    # 특이사항 (태도)
    raw_m = st.session_state.get('g_raw_m', "")
    final_m = st.session_state.get('g_final_m', "")
    save_m = final_m.strip() if final_m.strip() else raw_m.strip()
    
    # 성취도 평가 데이터
    a_sc = st.session_state.get('g_a_sc', 0)
    a_av = st.session_state.get('g_a_av', 0)
    a_wrong = st.session_state.get('g_a_wrong', "")
    
    a_analysis = st.session_state.get('g_a_analysis', "")

    # 총평
    raw_r = st.session_state.get('g_raw_r', "")
    final_r = st.session_state.get('g_final_r', "")
    save_r = final_r.strip() if final_r.strip() else raw_r.strip()
    
    sorted_wrong = sort_numbers_string(wrong)
    sorted_a_wrong = sort_numbers_string(a_wrong)
    
    # [데이터 저장 순서] (시트 헤더와 일치해야 함!)
    row = [
        student, period, 
        hw_name, hw, w_sc, w_av, sorted_wrong, w_analysis, # 과제명 추가됨
        save_m,
        ach_name, a_sc, a_av, sorted_a_wrong, a_analysis, # 시험명 추가됨
        save_r
    ]
    
    if add_row_to_sheet("weekly", row):
        st.toast(f"✅ {student} 성적 및 모든 분석 저장 완료!")
        # 초기화 (이름 필드도 초기화)
        keys = ['g_hw_name', 'g_hw', 'g_w_sc', 'g_w_av', 'g_wrong', 'g_w_analysis', 
                'g_raw_m', 'g_final_m', 
                'g_ach_name', 'g_a_sc', 'g_a_av', 'g_a_wrong', 'g_a_analysis', 
                'g_raw_r', 'g_final_r', 
                'g_pdf_text', 'g_ach_pdf_text']
        for k in keys:
            if k in st.session_state:
                if k == 'g_hw': st.session_state[k] = 80
                elif 'sc' in k or 'av' in k: st.session_state[k] = 0
                else: st.session_state[k] = ""

# ==========================================
# 6. 메인 앱 화면
# ==========================================
menu = st.sidebar.radio("메뉴", ["학생 관리 (상담/성적)", "신규 학생 등록"])

if menu == "신규 학생 등록":
    st.header("📝 신규 학생 등록")
    with st.form("new_student_form", clear_on_submit=True):
        col1, col2 = st.columns(2)
        name = col1.text_input("학생 이름")
        ban = col2.text_input("반 (예: M1, S1)")
        origin = st.text_input("출신 중학교")
        target = st.text_input("배정 예정 고등학교")
        addr = st.text_input("거주지")
        if st.form_submit_button("💾 학생 등록"):
            if name:
                clean_ban = clean_class_name(ban)
                clean_origin = clean_school_name(origin, "middle")
                clean_target = clean_school_name(target, "high")
                if add_row_to_sheet("students", [name, clean_ban, clean_origin, clean_target, addr]):
                    st.success(f"✅ {name} 등록 완료!")

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
            selected_student = st.sidebar.selectbox("👤 학생 선택", student_list) if student_list else None
        else:
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
                c_date = st.date_input("날짜", datetime.date.today())
                if 'c_raw_input' not in st.session_state: st.session_state['c_raw_input'] = ""
                raw_c = st.text_area("1. 상담 메모", height=80, key="c_raw_input")
                if st.button("✨ AI 변환", key="btn_c_ai"):
                    with st.spinner("변환 중..."):
                        ai_result = refine_text_ai(raw_c, "학부모 상담 일지", selected_student)
                        st.session_state['c_final_input'] = ai_result 
                        st.rerun()
                if 'c_final_input' not in st.session_state: st.session_state['c_final_input'] = ""
                final_c = st.text_area("2. 최종 내용", height=150, key="c_final_input")
                st.button("💾 상담 내용 저장", type="primary", on_click=save_counseling_callback, args=(selected_student, c_date))

            # --- [탭 2] 성적 입력 ---
            elif selected_tab == "📊 성적 입력":
                st.subheader("📊 성적 데이터 입력")
                
                c1, c2 = st.columns(2)
                mon = c1.selectbox("월", [f"{i}월" for i in range(1, 13)])
                wk = c2.selectbox("주차", [f"{i}주차" for i in range(1, 6)])
                period = f"{mon} {wk}"

                # 초기화 (이름 필드 포함)
                keys = ['g_hw_name', 'g_hw', 'g_w_sc', 'g_w_av', 'g_wrong', 'g_w_analysis', 
                        'g_raw_m', 'g_final_m', 
                        'g_ach_name', 'g_a_sc', 'g_a_av', 'g_a_wrong', 'g_a_analysis', 
                        'g_raw_r', 'g_final_r', 
                        'g_pdf_text', 'g_ach_pdf_text']
                for k in keys:
                    if k not in st.session_state:
                         st.session_state[k] = 80 if k == 'g_hw' else (0 if 'sc' in k or 'av' in k else "")

                # 1. 주간 과제 섹션
                st.markdown("##### 📝 주간 과제 & 점수")
                # [NEW] 과제명 입력칸
                st.text_input("📚 과제장 이름", placeholder="예: 쎈 수1, 마플시너지", key="g_hw_name")
                
                cc1, cc2, cc3 = st.columns(3)
                st.number_input("수행도(%)", 0, 100, key="g_hw")
                st.number_input("주간 과제 점수", 0, 100, key="g_w_sc")
                st.number_input("주간과제 평균점수", 0, 100, key="g_w_av")
                st.text_input("주간 과제 오답 번호", placeholder="예: 3 1 2", key="g_wrong")
                
                with st.expander("✨ [AI] 주간과제 PDF 분석", expanded=False):
                    uploaded_file = st.file_uploader("📄 과제 PDF 업로드", type=["pdf"], key="file_homework")
                    if uploaded_file is not None:
                        try:
                            reader = PdfReader(uploaded_file)
                            text_content = "".join([page.extract_text() for page in reader.pages])
                            st.session_state['g_pdf_text'] = text_content
                            st.success(f"PDF 로드 성공! ({len(reader.pages)}페이지)")
                        except: st.error("PDF 읽기 실패")
                    
                    target_h = st.radio("분석 대상:", ["학부모 전송용", "학생 배부용"], horizontal=True, key="target_h")
                    if st.button("🚀 주간과제 분석 실행"):
                        with st.spinner(f"{target_h}으로 분석 중..."):
                            analysis_msg = analyze_homework_ai(selected_student, st.session_state['g_wrong'], st.session_state['g_pdf_text'], "주간과제", target_h)
                            st.session_state['g_w_analysis'] = analysis_msg
                            st.rerun()

                st.text_area("주간 과제 분석 결과 (자동 생성)", height=150, key="g_w_analysis")
                st.divider()

                # 2. 태도 및 특이사항
                st.markdown("##### 📢 학습 태도 및 특이사항")
                raw_m = st.text_area("태도 메모", height=80, key="g_raw_m")
                if st.button("✨ 문체 교정", key="btn_m_ai"):
                    with st.spinner("변환 중..."):
                        res = refine_text_ai(raw_m, "학습 태도", selected_student)
                        st.session_state['g_final_m'] = res
                        st.rerun()
                st.text_area("최종 특이사항", height=80, key="g_final_m")
                st.divider()

                # 3. 성취도 평가 섹션
                st.markdown("##### 🏆 성취도 평가")
                # [NEW] 시험명 입력칸
                st.text_input("📄 시험지 이름", placeholder="예: 3월 월례고사, 1단원 테스트", key="g_ach_name")
                
                cc4, cc5 = st.columns(2)
                st.number_input("성취도 평가 점수", 0, 100, key="g_a_sc")
                st.number_input("성취도 평가 점수 평균", 0, 100, key="g_a_av")
                st.text_input("성취도평가 오답번호", placeholder="예: 21 29 30", key="g_a_wrong")
                
                with st.expander("✨ [AI] 성취도 시험지 분석", expanded=False):
                    ach_file = st.file_uploader("📄 시험지 PDF 업로드", type=["pdf"], key="file_achievement")
                    if ach_file is not None:
                        try:
                            reader_ach = PdfReader(ach_file)
                            ach_content = "".join([page.extract_text() for page in reader_ach.pages])
                            st.session_state['g_ach_pdf_text'] = ach_content
                            st.success(f"시험지 로드 성공! ({len(reader_ach.pages)}페이지)")
                        except: st.error("PDF 읽기 실패")

                    target_a = st.radio("분석 대상:", ["학부모 전송용", "학생 배부용"], horizontal=True, key="target_a")
                    if st.button("🚀 성취도 분석 실행"):
                        with st.spinner(f"{target_a}으로 분석 중..."):
                            analysis_msg = analyze_homework_ai(selected_student, st.session_state['g_a_wrong'], st.session_state['g_ach_pdf_text'], "성취도평가", target_a)
                            st.session_state['g_a_analysis'] = analysis_msg
                            st.rerun()

                st.text_area("성취도 분석 결과 (자동 생성)", height=150, key="g_a_analysis")
                st.markdown("##### 📝 성취도 총평 (종합 의견)")
                raw_r = st.text_area("총평 메모", height=80, key="g_raw_r")
                if st.button("✨ 문체 교정 (총평)", key="btn_r_ai"):
                    with st.spinner("변환 중..."):
                        res = refine_text_ai(raw_r, "총평", selected_student)
                        st.session_state['g_final_r'] = res
                        st.rerun()
                st.text_area("최종 총평", height=80, key="g_final_r")
                st.divider()
                st.button("💾 전체 성적 및 분석 저장", type="primary", use_container_width=True, on_click=save_grades_callback, args=(selected_student, period))

            # --- [탭 3] 리포트 (뽀로롱 기능) ---
            elif selected_tab == "👨‍👩‍👧‍👦 리포트":
                st.header(f"📑 {selected_student} 학습 리포트 마법사")
                st.divider()
                df_w = load_data_from_sheet("weekly")
                if not df_w.empty:
                    my_w = df_w[df_w["이름"] == selected_student]
                    if not my_w.empty:
                        periods = my_w["시기"].tolist()
                        sel_p = st.selectbox("기간을 선택하세요:", periods)
                        row_data = my_w[my_w["시기"] == sel_p].iloc[0]

                        # 뽀로롱 항목 선택
                        st.subheader("✨ 보고 싶은 항목을 선택하세요")
                        col_chk1, col_chk2, col_chk3, col_chk4 = st.columns(4)
                        show_score = col_chk1.checkbox("📊 점수표", value=True)
                        show_hw_anal = col_chk2.checkbox("📝 주간과제 분석", value=True)
                        show_att = col_chk3.checkbox("📢 학습 태도", value=True)
                        show_exam_anal = col_chk4.checkbox("🏆 성취도 분석", value=True)
                        
                        st.divider()
                        st.markdown(f"### 📋 {selected_student} - {sel_p} 리포트")
                        
                        if show_score:
                            st.info("📊 **성적 요약**")
                            # [NEW] 리포트에 이름 표시
                            st.write(f"📘 **과제명:** {row_data.get('과제명', '-')}")
                            st.write(f"📄 **시험명:** {row_data.get('시험명', '-')}")
                            metrics_col1, metrics_col2, metrics_col3 = st.columns(3)
                            metrics_col1.metric("주간 과제", f"{row_data.get('주간점수',0)}점", f"평균 {row_data.get('주간평균',0)}점")
                            metrics_col2.metric("성취도 평가", f"{row_data.get('성취도점수',0)}점", f"평균 {row_data.get('성취도평균',0)}점")
                            metrics_col3.metric("과제 수행도", f"{row_data.get('과제',0)}%")
                        
                        if show_hw_anal:
                            st.success("📝 **주간 과제 분석**")
                            st.write(row_data.get('주간분석', '내용 없음'))

                        if show_att:
                            st.warning("📢 **학습 태도 및 특이사항**")
                            st.write(row_data.get('특이사항', '내용 없음'))

                        if show_exam_anal:
                            st.error("🏆 **성취도 평가 분석 및 총평**")
                            st.markdown("**[문항 분석]**")
                            st.write(row_data.get('성취도분석', '내용 없음'))
                            st.markdown("---")
                            st.markdown("**[종합 총평]**")
                            st.write(row_data.get('총평', '내용 없음'))
                        
                        st.caption("💡 팁: 위 내용을 드래그해서 복사하거나 캡처해서 전송하세요!")
                    else: st.info("데이터가 없습니다.")
                else: st.info("데이터가 없습니다.")
