import streamlit as st
import pandas as pd
import requests
import json
import datetime
import altair as alt
import re
from pypdf import PdfReader
import gspread
from oauth2client.service_account import ServiceAccountCredentials

# ==========================================
# 1. 페이지 설정 및 구글 시트 연결
# ==========================================
st.set_page_config(page_title="GoodSense Math (Web)", layout="wide")
st.title("👨‍🏫 GoodSense Math 김성만 수학 연구소 (Web)")

# [중요] 시크릿에서 키와 인증 정보 가져오기
try:
    # 1. API 키 (secrets.toml에 GENAI_API_KEY로 저장되어 있어야 함)
    GEMINI_API_KEY = st.secrets["GENAI_API_KEY"]
    
    # 2. 구글 시트 인증 (secrets.toml에 gcp_service_account 섹션이 있어야 함)
    scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
    creds_dict = dict(st.secrets["gcp_service_account"])
    creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
    client = gspread.authorize(creds)
    
    # 3. 구글 시트 열기 (시트 이름: "학생관리데이터")
    # ※ 주의: 구글 드라이브에 있는 실제 파일명과 정확히 일치해야 합니다.
    SHEET_NAME = "학생관리데이터" 
    sh = client.open(SHEET_NAME) 

except Exception as e:
    st.error(f"❌ 설정 오류: Secrets 설정이나 구글 시트 연결을 확인해주세요.\n\n에러 내용: {e}")
    st.stop()

# ==========================================
# 2. 구글 시트 읽기/쓰기 함수 (gspread 사용)
# ==========================================
def load_data_from_gsheet(worksheet_name):
    try:
        worksheet = sh.worksheet(worksheet_name)
        data = worksheet.get_all_records()
        df = pd.DataFrame(data)
        
        # 숫자형 변환 (주간 시트)
        if worksheet_name == 'weekly':
            numeric_cols = ['주간점수', '주간평균', '성취도점수', '성취도평균', '과제']
            for col in numeric_cols:
                if col in df.columns:
                    # 빈 문자열이나 에러가 날 경우 0으로 처리
                    df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0)
        
        # 날짜/시기 문자열 변환
        if '날짜' in df.columns: df['날짜'] = df['날짜'].astype(str)
        if '시기' in df.columns: df['시기'] = df['시기'].astype(str)
        return df
    except Exception as e:
        st.warning(f"데이터 로드 중: '{worksheet_name}' 시트를 찾을 수 없거나 비어있습니다.")
        return pd.DataFrame()

def add_row_to_gsheet(worksheet_name, row_data_list):
    try:
        worksheet = sh.worksheet(worksheet_name)
        # 리스트 내용을 문자열로 변환해서 저장 (안전성 확보)
        safe_row = [str(x) if x is not None else "" for x in row_data_list]
        worksheet.append_row(safe_row)
        return True
    except Exception as e:
        st.error(f"저장 실패: {e}")
        return False

# ==========================================
# 3. 유틸리티 & AI (전문가 어조 적용됨)
# ==========================================
def sort_numbers_string(text):
    if not text: return ""
    numbers = re.findall(r'\d+', str(text))
    if not numbers: return text
    return ", ".join(map(str, sorted([int(n) for n in numbers])))

def clean_class_name(text):
    if not text: return ""
    return text.upper().strip()

def clean_school_name(text, target_type="middle"):
    if not text: return ""
    text = text.strip()
    root_name = re.sub(r'(고등학교|중학교|고등|중학|고|중)$', '', text)
    if target_type == "middle": return root_name + "중"
    else: return root_name + "고"

def refine_text_ai(raw_text, context_type, student_name):
    if not raw_text: return ""
    try:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash-exp:generateContent?key={GEMINI_API_KEY}"
        headers = {'Content-Type': 'application/json'}
        prompt = f"""
        학생: {student_name}
        내용: {raw_text}
        문맥: {context_type}
        
        [학부모 전송용 메시지 작성 지침]
        1. **금지어:** "믿고 맡겨주셔서 감사합니다", "책임지겠습니다" 같은 과도한 저자세나 모든 책임을 떠안는 표현 절대 금지.
        2. **필수 표현:** - "학생의 부족한 부분을 **꼼꼼히 관리하겠습니다**."
           - "**가정에서도 학생이 힘들어하거나 이상 동향이 보이면 바로 알려주십시오. 상담과 클리닉을 통해 지도하겠습니다.**"
        3. **어조:** - 학생의 성장은 강사의 지도와 학생의 의지, 가정의 관심이 함께해야 함을 전제하는 차분하고 객관적인 전문가의 말투.
           - 성적 향상에는 시간이 필요할 수 있음을(기다림의 여지) 내포할 것.
        """
        data = {"contents": [{"parts": [{"text": prompt}]}]}
        res = requests.post(url, headers=headers, data=json.dumps(data))
        if res.status_code == 200: return res.json()['candidates'][0]['content']['parts'][0]['text']
        else: return f"AI 에러: {res.status_code}"
    except Exception as e: return f"통신 에러: {e}"

def analyze_homework_ai(student_name, wrong_numbers, assignment_text, type_name="과제", target_audience="학부모 전송용"):
    if not wrong_numbers or not assignment_text: return "내용 부족"
    try:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash-exp:generateContent?key={GEMINI_API_KEY}"
        headers = {'Content-Type': 'application/json'}
        
        if target_audience == "학부모 전송용":
            prompt = f"""
            학생: {student_name}, 오답: {wrong_numbers}, 유형: {type_name}
            텍스트: {assignment_text[:15000]}
            
            [학부모 전송용 분석 보고서 작성 지침]
            1. **인사말 생략:** 불필요한 감사 인사 없이 바로 "금주 {type_name} 분석 결과입니다."로 시작.
            2. **분석:** 틀린 문제의 원인을 객관적 데이터(유형, 난이도)에 근거해 차갑고 정확하게 진단.
            3. **대책 및 협조 요청:** - "수업 시간에 해당 유형을 집중적으로 다루며 **꼼꼼히 관리하겠습니다**."
               - "**가정에서도 과제 수행 과정을 지켜봐 주시고, 어려워하는 점이 있다면 언제든 공유 부탁드립니다.**"
            4. **마무리:** 감정적인 약속보다는 "지속적으로 관찰하며 지도하겠습니다" 정도로 담백하게 맺음.
            """
        else:
            prompt = f"""
            학생: {student_name}, 오답: {wrong_numbers}, 유형: {type_name}
            텍스트: {assignment_text[:15000]}
            [학생 본인용 피드백] 따뜻하지만 단호한 선생님 말투. 1.유형 분석 2.노력 강조 3.질문 유도.
            """
        data = {"contents": [{"parts": [{"text": prompt}]}]}
        res = requests.post(url, headers=headers, data=json.dumps(data))
        if res.status_code == 200: return res.json()['candidates'][0]['content']['parts'][0]['text']
        else: return f"AI 에러: {res.status_code}"
    except Exception as e: return f"통신 에러: {e}"

# ==========================================
# 4. 메인 화면 로직 (리포트 UI 개선됨)
# ==========================================
menu = st.sidebar.radio("메뉴", ["학생 관리", "신규 등록"], label_visibility="collapsed")

if menu == "신규 등록":
    st.header("📝 신규 학생 등록 (Web)")
    with st.form("new"):
        c1, c2 = st.columns(2)
        name = c1.text_input("이름")
        ban = c2.text_input("반")
        origin = st.text_input("출신중")
        target = st.text_input("배정고")
        addr = st.text_input("거주지")
        if st.form_submit_button("저장"):
            if name:
                if add_row_to_gsheet("students", [name, clean_class_name(ban), clean_school_name(origin), clean_school_name(target,'high'), addr]):
                    st.success(f"{name} 등록 완료!")
                    st.cache_data.clear() # 데이터 갱신

elif menu == "학생 관리":
    df_std = load_data_from_gsheet("students")
    if not df_std.empty:
        if '반' in df_std.columns:
            ban_list = sorted(df_std['반'].unique().tolist())
            sel_ban = st.sidebar.selectbox("반", ban_list)
            std_list = sorted(df_std[df_std['반']==sel_ban]['이름'].tolist())
            sel_std = st.sidebar.selectbox("학생", std_list)
        else: sel_std = None
        
        if sel_std:
            st.sidebar.markdown(f"**{sel_std}** 선택됨")
            tab = st.radio("기능", ["상담 일지", "성적 입력", "리포트"], horizontal=True, label_visibility="collapsed")
            st.divider()
            
            if tab == "상담 일지":
                df_c = load_data_from_gsheet("counseling")
                with st.expander("기록 보기"):
                    if not df_c.empty:
                        logs = df_c[df_c['이름']==sel_std].sort_values('날짜', ascending=False)
                        for _, r in logs.iterrows(): st.info(f"[{r['날짜']}] {r['내용']}")
                d = st.date_input("날짜", datetime.date.today())
                raw = st.text_area("메모", key="c_raw_input")
                if st.button("AI 변환"):
                    st.session_state['c_final_input'] = refine_text_ai(raw, "상담", sel_std)
                    st.rerun()
                st.text_area("최종", key="c_final_input")
                
                # 저장 콜백 함수 (인자 전달 방식 수정)
                def save_counseling():
                    content = st.session_state['c_final_input'] if st.session_state['c_final_input'] else st.session_state['c_raw_input']
                    if content:
                        add_row_to_gsheet("counseling", [sel_std, str(d), content])
                        st.toast("저장 완료!")
                        st.session_state['c_raw_input'] = ""
                        st.session_state['c_final_input'] = ""
                        st.cache_data.clear()

                st.button("저장", on_click=save_counseling)

            elif tab == "성적 입력":
                c1, c2 = st.columns(2)
                m = c1.selectbox("월", [f"{i}월" for i in range(1,13)])
                w = c2.selectbox("주", [f"{i}주차" for i in range(1,6)])
                period = f"{m} {w}"
                
                keys = ['g_hw_name', 'g_hw', 'g_w_sc', 'g_w_av', 'g_wrong', 'g_w_analysis', 
                        'g_raw_m', 'g_final_m', 'g_ach_name', 'g_a_sc', 'g_a_av', 'g_a_wrong', 
                        'g_a_analysis', 'g_raw_r', 'g_final_r', 'g_pdf_text', 'g_ach_pdf_text']
                for k in keys:
                    if k not in st.session_state: st.session_state[k] = 80 if k == 'g_hw' else (0 if 'sc' in k or 'av' in k else "")

                st.subheader("📝 주간 과제")
                st.text_input("과제명", key="g_hw_name")
                cc1, cc2, cc3 = st.columns(3)
                st.number_input("수행도", 0, 100, key="g_hw")
                st.number_input("점수", key="g_w_sc")
                st.number_input("평균", key="g_w_av")
                st.text_input("오답", key="g_wrong")
                with st.expander("PDF 분석"):
                    up = st.file_uploader("과제 PDF", type=["pdf"], key="f1")
                    if up: 
                        try: st.session_state['g_pdf_text'] = "".join([p.extract_text() for p in PdfReader(up).pages])
                        except: pass
                    tgt = st.radio("대상", ["학부모 전송용", "학생 배부용"], horizontal=True, key="t1")
                    if st.button("분석 실행", key="b1"):
                        st.session_state['g_w_analysis'] = analyze_homework_ai(sel_std, st.session_state['g_wrong'], st.session_state['g_pdf_text'], "주간과제", tgt)
                        st.rerun()
                st.text_area("분석결과", key="g_w_analysis")
                st.divider()
                st.subheader("📢 태도")
                rm = st.text_area("메모", key="g_raw_m")
                if st.button("다듬기", key="b2"):
                    st.session_state['g_final_m'] = refine_text_ai(rm, "태도", sel_std)
                    st.rerun()
                st.text_area("최종", key="g_final_m")
                st.divider()
                st.subheader("🏆 성취도")
                st.text_input("시험명", key="g_ach_name")
                c4, c5 = st.columns(2)
                st.number_input("점수", key="g_a_sc")
                st.number_input("평균", key="g_a_av")
                st.text_input("오답", key="g_a_wrong")
                with st.expander("시험지 분석"):
                    up2 = st.file_uploader("시험지 PDF", type=["pdf"], key="f2")
                    if up2:
                        try: st.session_state['g_ach_pdf_text'] = "".join([p.extract_text() for p in PdfReader(up2).pages])
                        except: pass
                    tgt2 = st.radio("대상", ["학부모 전송용", "학생 배부용"], horizontal=True, key="t2")
                    if st.button("분석 실행", key="b3"):
                        st.session_state['g_a_analysis'] = analyze_homework_ai(sel_std, st.session_state['g_a_wrong'], st.session_state['g_ach_pdf_text'], "성취도", tgt2)
                        st.rerun()
                st.text_area("분석결과", key="g_a_analysis")
                st.subheader("📝 총평")
                rr = st.text_area("메모", key="g_raw_r")
                if st.button("다듬기", key="b4"):
                    st.session_state['g_final_r'] = refine_text_ai(rr, "총평", sel_std)
                    st.rerun()
                st.text_area("최종", key="g_final_r")
                
                # 저장 콜백 (구글 시트용)
                def save_grades():
                    # 값 가져오기
                    hw_name = st.session_state.get('g_hw_name', "-")
                    ach_name = st.session_state.get('g_ach_name', "-")
                    hw = st.session_state.get('g_hw', 80)
                    w_sc = st.session_state.get('g_w_sc', 0)
                    w_av = st.session_state.get('g_w_av', 0)
                    wrong = st.session_state.get('g_wrong', "")
                    w_analysis = st.session_state.get('g_w_analysis', "")
                    raw_m = st.session_state.get('g_raw_m', "")
                    final_m = st.session_state.get('g_final_m', "")
                    save_m = final_m.strip() if final_m.strip() else raw_m.strip()
                    a_sc = st.session_state.get('g_a_sc', 0)
                    a_av = st.session_state.get('g_a_av', 0)
                    a_wrong = st.session_state.get('g_a_wrong', "")
                    a_analysis = st.session_state.get('g_a_analysis', "")
                    raw_r = st.session_state.get('g_raw_r', "")
                    final_r = st.session_state.get('g_final_r', "")
                    save_r = final_r.strip() if final_r.strip() else raw_r.strip()
                    
                    row = [sel_std, period, hw_name, hw, w_sc, w_av, sort_numbers_string(wrong), w_analysis, 
                           save_m, ach_name, a_sc, a_av, sort_numbers_string(a_wrong), a_analysis, save_r]
                    
                    if add_row_to_gsheet("weekly", row):
                        st.toast("구글 시트 저장 완료!")
                        # 초기화
                        for k in ['g_hw_name','g_ach_name','g_wrong','g_w_analysis','g_raw_m','g_final_m','g_a_wrong','g_a_analysis','g_raw_r','g_final_r']:
                            st.session_state[k] = ""
                        st.session_state['g_hw'] = 80
                        st.session_state['g_w_sc'] = 0
                        st.session_state['g_w_av'] = 0
                        st.session_state['g_a_sc'] = 0
                        st.session_state['g_a_av'] = 0
                        st.cache_data.clear()

                st.button("💾 저장하기", type="primary", on_click=save_grades)

            elif tab == "리포트":
                df_w = load_data_from_gsheet("weekly")
                if not df_w.empty:
                    my_w = df_w[df_w['이름']==sel_std]
                    if not my_w.empty:
                        pers = my_w['시기'].tolist()
                        
                        # [상단 배치] 리포트 설정
                        st.subheader("🖨️ 리포트 출력 설정")
                        sel_p = st.multiselect("출력할 주차(기간)를 선택하세요", pers, default=[pers[-1]])
                        with st.expander("✅ 표시할 항목 선택 (클릭하여 열기/닫기)", expanded=False):
                            st.caption("아래 체크박스를 해제하면 리포트에서 해당 내용이 사라집니다.")
                            c_opt1, c_opt2, c_opt3, c_opt4 = st.columns(4)
                            show_score = c_opt1.checkbox("점수/수행도", True)
                            show_weekly = c_opt2.checkbox("주간분석", True)
                            show_attitude = c_opt3.checkbox("태도/특이사항", True)
                            show_achieve = c_opt4.checkbox("성취도/총평", True)
                        st.divider() 

                        if sel_p:
                            if len(sel_p) > 1:
                                st.subheader("📊 성적 추이")
                                chart_data = my_w[my_w['시기'].isin(sel_p)][['시기','주간점수','성취도점수']].melt('시기', var_name='종류', value_name='점수')
                                chart = alt.Chart(chart_data).mark_line(point=True).encode(x=alt.X('시기', sort=None), y=alt.Y('점수', scale=alt.Scale(domain=[0,100])), color='종류').interactive()
                                st.altair_chart(chart, use_container_width=True)

                            for p in sel_p:
                                r = my_w[my_w['시기']==p].iloc[0]
                                st.markdown(f"### 🗓️ {p} 리포트")
                                if show_score:
                                    st.info(f"**{r.get('과제명','-')} / {r.get('시험명','-')}**")
                                    c1, c2, c3 = st.columns(3)
                                    c1.metric("주간", f"{r.get('주간점수',0)}", f"Avg {r.get('주간평균',0)}")
                                    c2.metric("성취도", f"{r.get('성취도점수',0)}", f"Avg {r.get('성취도평균',0)}")
                                    c3.metric("수행도", f"{r.get('과제',0)}%")
                                if show_weekly and r.get('주간분석'): st.success(f"**주간 과제 분석**\n\n{r.get('주간분석','')}")
                                if show_attitude and r.get('특이사항'): st.warning(f"**학습 태도**\n\n{r.get('특이사항','')}")
                                if show_achieve:
                                    content = ""
                                    if r.get('성취도분석'): content += f"**성취도 분석**\n{r.get('성취도분석','')}\n\n"
                                    if r.get('총평'): content += f"---\n**총평**\n{r.get('총평','')}"
                                    if content: st.error(content)
                                st.divider()
                    else: st.info("데이터 없음")
                else: st.info("데이터 없음")
