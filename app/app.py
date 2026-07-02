"""
악플 증거 정리 도구 — Streamlit 데모 (파이프라인 조립)
=====================================================

조각들이 처음으로 하나로 이어지는 곳. 흐름:
    캡처 업로드 → OCR 초안 → 사용자 교정 → 봉인(해시) → (스텁)분류 → 세 뷰 출력

관통 원칙이 UI에 그대로 드러난다:
  - 사용자 지목(설계결정 1): 도구가 긁지 않는다. 사용자가 캡처를 올려 '이건 내 악플'이라 지목.
  - 초안→교정→봉인(ocr.review_then_seal): OCR은 초안, 사람이 확인한 뒤 봉인.
  - 저장 ≠ 열람(설계결정 6): 봉인되면 목록엔 '표지'만. 원문은 펼칠 때만 노출.
  - 판정 안 함(결정 4)·동일인 추정 안 함(결정 5)·면책: 뷰가 그대로 반영.

실행:  streamlit run app/app.py
(src/ 모듈을 가져오도록 경로를 잡는다. 배포 시 루트에서 실행 권장.)
"""

from __future__ import annotations

import sys
import tempfile
from datetime import datetime, time
from pathlib import Path

# src/ 를 import 경로에 추가 (app/ 의 부모/ src)
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

import streamlit as st

from schema import EvidenceRecord
from ocr import extract_text, review_then_seal, strip_boilerplate
from seal import seal_record, verify_record
from classify import classify
from views import to_csv, to_timeline, to_charges, to_pdf, GLOBAL_DISCLAIMER


st.set_page_config(page_title="악플 증거 정리 도구", page_icon="🛡️", layout="wide")

# 세션 상태: 봉인된 레코드 목록 (브라우저 저장소 아님 — 서버측 세션)
if "records" not in st.session_state:
    st.session_state.records: list[EvidenceRecord] = []


# ─────────────────────────────────────────────────────────────
# 헤더
# ─────────────────────────────────────────────────────────────
st.title("🛡️ 악플 증거 정리 도구")
st.caption("혹시 모를 상황에 대비해, 사용자가 지목한 악플을 사라지기 전에 봉인해 두는 예방적 대비 도구. "
           "찾아주는 AI도, 판정하는 AI도 아니다 — 사람이 지목·확인하고, 도구는 보존·정리를 맡는다.")

with st.expander("이 도구가 하지 않는 것 (Non-Goals)", expanded=False):
    st.markdown(
        "- ❌ 악플 자동 수집·크롤링 (오수집 = 사찰화)\n"
        "- ❌ 법적 판정 — '이건 명예훼손/모욕이다' 확정 (변호사·법원 몫)\n"
        "- ❌ 진위(사실/허위) 판단\n"
        "- ❌ 동일인 추정 (다른 표기로 같은 사람 잇기)\n"
        "- ❌ 작성자 신상 수집 / 고소장 초안 생성"
    )


# ─────────────────────────────────────────────────────────────
# 1) 입력 — 캡처 지목 → OCR 초안 → 교정 → 봉인
# ─────────────────────────────────────────────────────────────
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
    # 초안→교정→봉인 (사용자가 확인한 텍스트 + 원본 이미지 함께 봉인)
    review_then_seal(image_bytes, corrected.strip(), rec, seal_record)
    # 분류 (사용자가 지목했으므로 user_flagged=True)
    rec.formal_features, rec.related_provisions = classify(
        rec.text, source_is_public=is_public, user_flagged=True)
    st.session_state.records.append(rec)
    st.success(f"봉인 완료 — 건수 {len(st.session_state.records)}건. 봉인해시 {rec.seal_digest[:16]}…")


# ─────────────────────────────────────────────────────────────
# 2) 봉인된 증거 목록 — 저장 ≠ 열람 (표지만, 원문은 펼칠 때만)
# ─────────────────────────────────────────────────────────────
st.header("② 봉인된 증거 (표지만 표시)")

records = st.session_state.records
if not records:
    st.write("아직 봉인된 증거가 없습니다.")
else:
    st.caption("봉인된 증거는 '닫힌 봉투'처럼 다룹니다. 반복 정독은 도구가 대신하고, "
               "원문은 아래에서 명시적으로 펼칠 때만 엽니다(2차 노출 최소화).")
    for i, r in enumerate(records, 1):
        c = r.cover()
        st.markdown(f"**{i}. `{c['id']}`** · 캡처 {c['captured_at']} · 봉인 {c['sealed_at']} · "
                    f"{c['integrity']} · 관찰특징 {c['n_features']} · 참고유형 {c['n_provisions']}")
        with st.expander("원문 펼쳐보기 / 무결성 검증", expanded=False):
            st.write("**원문(교정본):**")
            st.code(r.text)
            st.write(f"**seal_digest:** `{r.seal_digest}`")
            st.caption("무결성 재검증은 원본 이미지가 필요합니다(데모에선 세션 보관 생략). "
                       "src.seal.verify_record 로 확인.")


# ─────────────────────────────────────────────────────────────
# 3) 세 가지 뷰 — 한 데이터, 세 렌즈
# ─────────────────────────────────────────────────────────────
st.header("③ 정리 — 세 가지 뷰")

if not records:
    st.write("봉인된 증거가 쌓이면 여기에 증거표·타임라인·죄목별 정리가 나옵니다.")
else:
    tab_tbl, tab_tl, tab_ch = st.tabs(["증거표 (CSV·PDF)", "타임라인", "죄목별"])

    with tab_tbl:
        st.write("한 건 = 한 행. 가공용 CSV, 제출용 PDF로 내보낼 수 있습니다.")
        st.dataframe([
            {"id": r.id, "캡처시점": r.cover()["captured_at"], "작성자표기": r.author_id_raw,
             "관찰특징": ", ".join(f.feature.value for f in r.formal_features if f.present),
             "참고유형": ", ".join(p.provision.value for p in r.related_provisions),
             "무결성": r.cover()["integrity"]}
            for r in records
        ], width="stretch")

        st.download_button("⬇️ 증거표 CSV (Excel 한글 안전)", data=to_csv(records),
                           file_name="evidence_table.csv", mime="text/csv")

        # PDF는 파일로 생성 후 bytes로 읽어 다운로드
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tf:
            out = to_pdf(records, tf.name)
        with open(out["path"], "rb") as f:
            pdf_bytes = f.read()
        label = "⬇️ 증거표 PDF (제출용)" if out["format"] == "pdf" else "⬇️ 증거표 HTML (인쇄→PDF)"
        st.download_button(label, data=pdf_bytes,
                           file_name=f"evidence_report.{out['format']}",
                           mime="application/pdf" if out["format"] == "pdf" else "text/html")

    with tab_tl:
        tl = to_timeline(records)
        st.write(f"**기간:** {tl['span']}")
        st.dataframe(tl["items"], width="stretch")
        st.caption(f"⚠️ {tl['note']}")

    with tab_ch:
        ch = to_charges(records)
        if not ch["groups"]:
            st.write("참고 조항 유형에 연결된 건이 아직 없습니다.")
        for gtype, entries in ch["groups"].items():
            st.subheader(f"{gtype} · {len(entries)}건")
            for en in entries:
                st.markdown(f"- `{en['record_id']}` ({en['when']}, {en['author_id_raw']})  \n"
                            f"  근거: {en['rationale']}  \n"
                            f"  <small>면책: {en['disclaimer']}</small>", unsafe_allow_html=True)
        st.info(ch["global_disclaimer"])

st.divider()
st.caption(GLOBAL_DISCLAIMER)
