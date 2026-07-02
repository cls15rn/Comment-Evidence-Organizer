"""
악플 증거 정리 도구 — Streamlit 라우터 (엔트리포인트)
==================================================

st.navigation 방식. 이 파일은 '라우터'다:
  - 공통 설정(set_page_config), src 경로, 세션 상태 초기화를 한곳에서.
  - 실제 화면은 page_main.py / page_report.py 에 있고, 사이드바 라벨은 여기서 한글로 지정.

이 구조의 이점: 파일명은 영어(URL·git·배포 안전) + 사이드바 라벨은 한글.

실행:  streamlit run app/app.py
"""

from __future__ import annotations

import sys
from pathlib import Path

# src/ 를 import 경로에 추가 (페이지들이 로드되기 전에) — app/ 의 부모 = 레포 루트 / src
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import streamlit as st

from schema import EvidenceRecord

st.set_page_config(page_title="악플 증거 정리 도구", page_icon="🛡️", layout="wide")

# 세션 상태(서버측 세션 메모리) — 페이지 간 공유. 브라우저 저장소 아님.
if "records" not in st.session_state:
    st.session_state.records: list[EvidenceRecord] = []

# 사이드바 라벨은 한글, 파일명은 영어
pages = [
    st.Page("page_main.py",   title="지목 · 봉인",   icon="🛡️", default=True),
    st.Page("page_report.py", title="정리 · 리포트", icon="🗂️"),
]
nav = st.navigation(pages)

# 사이드바: 현재 분류 엔진 표시 (모델 로드를 유발하지 않고 상태만 읽음)
from screen_model import status as _screen_status
_ENGINE_LABEL = {
    "model":   "🟢 UnSmile 모델",
    "rules":   "🟡 규칙(폴백)",
    "unknown": "⚪ 첫 분류 시 결정",
}
st.sidebar.caption(f"분류 엔진: {_ENGINE_LABEL[_screen_status()]}")

nav.run()
