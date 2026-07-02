"""
메인 페이지 — 지목 · 봉인
========================
상단 지표(저장 N건) + ① 악플 지목·봉인 + ② 봉인된 증거(표지, 저장≠열람).
라우터(app.py)가 src 경로·세션·set_page_config를 이미 처리하므로 여기선 하지 않는다.
"""

from __future__ import annotations

from datetime import datetime, time

import streamlit as st

from schema import EvidenceRecord
from ocr import extract_text, review_then_seal, strip_boilerplate
from seal import seal_record
from classify import classify
from views import GLOBAL_DISCLAIMER

records = st.session_state.records


# ── 헤더 ──────────────────────────────────────────────────────
st.title("🛡️ 악플 증거 정리 도구")
st.caption("혹시 모를 상황에 대비해, 사용자가 지목한 악플을 사라지기 전에 봉인해 두는 예방적 대비 도구. "
           "찾아주는 AI도, 판정하는 AI도 아니다 — 사람이 지목·확인하고, 도구는 보존·정리를 맡는다.")

# ── 상단 지표 ─────────────────────────────────────────────────
m1, m2 = st.columns([1, 3])
with m1:
    st.metric("저장된 증거", f"{len(records)}건")
with m2:
    st.caption("ℹ️ 임시 저장: 봉인된 증거는 현재 세션 메모리에만 있습니다. "
               "새로고침·탭 종료 시 사라집니다(영속 저장은 로드맵). "
               "정리·리포트는 왼쪽 사이드바에서 열 수 있습니다.")

with st.expander("이 도구가 하지 않는 것 (Non-Goals)", expanded=False):
    st.markdown(
        "- ❌ 악플 자동 수집·크롤링 (오수집 = 사찰화)\n"
        "- ❌ 법적 판정 — '이건 명예훼손/모욕이다' 확정 (변호사·법원 몫)\n"
        "- ❌ 진위(사실/허위) 판단\n"
        "- ❌ 동일인 추정 (다른 표기로 같은 사람 잇기)\n"
        "- ❌ 작성자 신상 수집 / 고소장 초안 생성"
    )

st.divider()


# ── ① 입력 — 캡처 지목 → OCR 자동 추출 → 교정 → 봉인 ──────────────
st.header("① 악플 지목 & 봉인")

col_in, col_meta = st.columns([3, 2])

with col_in:
    up = st.file_uploader("악플 캡처 이미지를 올리세요 (본인이 지목한 '내 악플')",
                          type=["png", "jpg", "jpeg", "webp"])
    image_bytes = up.read() if up else None
    if image_bytes:
        st.image(image_bytes, caption="지목한 캡처", width="stretch")

    # OCR 자동 추출 (사용자가 악플을 직접 다시 쓰지 않도록 — 입력 단계의 2차 노출 최소화)
    draft = ""
    if image_bytes:
        res = extract_text(image_bytes)
        draft = res.text
        if res.ok:
            body_only = st.checkbox("머리글·시간·버튼 걷어내고 본문만", value=True)
            if body_only:
                draft = strip_boilerplate(draft)
            st.caption("OCR이 자동으로 읽어 아래에 채웠습니다. 악플을 직접 다시 쓰지 않게 하려는 것이니, "
                       "틀린 글자만 고치면 됩니다.")
        else:
            st.warning("자동 추출이 안 됐어요. 이미지가 선명한지 확인하거나 한국어 OCR 엔진"
                       "(easyocr / tesseract 한국어 데이터)을 설치하면 자동으로 채워집니다.\n\n"
                       + res.note)
    corrected = st.text_area(
        "봉인될 텍스트 (OCR 자동 채움 — 필요한 글자만 수정)",
        value=draft, height=120,
        help="OCR이 자동으로 채운 초안입니다. 처음부터 다시 쓸 필요 없이, 원문과 다른 글자만 고친 뒤 봉인하세요.",
    )

with col_meta:
    author = st.text_input("작성자 표기 (보이는 그대로)", placeholder="예: user_1234")
    source = st.text_input("출처 메모", placeholder="예: OO커뮤니티 자유게시판")
    is_public = st.checkbox("공개된 위치에 게시됨", value=True)
    cap_date = st.date_input("캡처한 날짜")
    cap_time = st.time_input("캡처한 시각", value=time(12, 0))
    st.caption("※ 날짜·시각은 자기신고입니다. 자체 해시는 '안 바뀜(무결성)'은 증명하지만 "
               "'언제 존재했는지(시점)'는 보증하지 못합니다 — 시점 보증은 향후 TSA 확장 영역.")

seal_clicked = st.button("🔒 봉인하기", type="primary",
                         disabled=not (image_bytes and corrected.strip()))

if seal_clicked:
    rec = EvidenceRecord(
        author_id_raw=author.strip(),
        source_hint=source.strip(),
        captured_at=datetime.combine(cap_date, cap_time),
    )
    review_then_seal(image_bytes, corrected.strip(), rec, seal_record)   # 확인 텍스트+이미지 봉인
    rec.formal_features, rec.related_provisions = classify(              # 사용자 지목 → user_flagged=True
        rec.text, source_is_public=is_public, user_flagged=True)
    records.append(rec)
    st.success(f"봉인 완료 — 총 {len(records)}건. 봉인해시 {rec.seal_digest[:16]}…")
    st.rerun()   # 상단 지표 즉시 갱신


st.divider()


# ── ② 봉인된 증거 목록 — 저장 ≠ 열람 (표지만) ────────────────────
st.header("② 봉인된 증거 (표지만 표시)")

if not records:
    st.write("아직 봉인된 증거가 없습니다.")
else:
    st.caption("봉인된 증거는 '닫힌 봉투'처럼 다룹니다. 반복 정독은 도구가 대신하고, "
               "원문은 아래에서 명시적으로 펼칠 때만 엽니다(2차 노출 최소화).")
    for i, r in enumerate(records, 1):
        c = r.cover()
        st.markdown(f"**{i}. `{c['id']}`** · 캡처 {c['captured_at']} · 봉인 {c['sealed_at']} · "
                    f"{c['integrity']} · 관찰특징 {c['n_features']} · 참고유형 {c['n_provisions']}")
        with st.expander("원문 펼쳐보기 / 무결성", expanded=False):
            st.write("**원문(교정본):**")
            st.code(r.text)
            st.write(f"**seal_digest:** `{r.seal_digest}`")
            st.caption("무결성 재검증은 원본 이미지가 필요합니다(데모에선 세션 보관 생략). "
                       "src.seal.verify_record 로 확인.")

st.divider()
st.caption(GLOBAL_DISCLAIMER)
