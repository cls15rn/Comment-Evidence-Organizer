"""
정리 · 리포트 페이지 — 세 가지 뷰 (한 데이터, 세 렌즈)
==================================================
메인에서 봉인한 증거(st.session_state.records)를 읽어 세 가지로 정리한다.
데이터를 새로 만들지 않고 렌더링만 → 출력이 늘어도 비용 거의 안 늚(설계확정 5).
라우터(app.py)가 src 경로·세션·set_page_config를 이미 처리한다.
"""

from __future__ import annotations

import tempfile

import streamlit as st

from views import to_csv, to_timeline, to_charges, to_pdf, GLOBAL_DISCLAIMER

records = st.session_state.records

st.title("🗂️ 정리 — 세 가지 뷰")
st.caption(f"봉인된 증거 {len(records)}건을 세 렌즈로 정리합니다. 봉인은 '지목 · 봉인' 페이지에서 합니다.")

if not records:
    st.info("아직 봉인된 증거가 없습니다. 왼쪽 사이드바 '지목 · 봉인'에서 먼저 봉인하세요.")
    st.stop()

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
