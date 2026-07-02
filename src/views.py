"""
세 가지 뷰 (Views) — 한 데이터, 세 렌더링
========================================

입력은 항상 list[EvidenceRecord] 하나다. 같은 데이터를 세 렌즈로 비출 뿐,
데이터를 새로 만들지 않는다 → 출력이 늘어도 비용이 거의 안 는다(설계확정 5).

  1) 증거표  : CSV(가공용, Excel 한글 안전) + PDF(제출용, reportlab 한국어 CID)
  2) 타임라인: 시간순 정렬 → 지속성·반복성 '관찰' (동일인 추정은 안 함, 결정 5)
  3) 죄목별  : 참고 조항 유형별 묶음 + 근거 + 항목별 면책 (판정 아님, 결정 4)

■ 저장 ≠ 열람 (설계결정 6)과의 경계
    앱에서 '둘러볼 때'는 cover()로 표지만 본다(원문 반복 노출 최소화).
    여기 CSV/PDF export 는 사용자가 '명시적으로 내보내는' 제출용 산출물이라 원문을 포함한다
    (제출하려면 내용이 있어야 함). 즉 노출 최소화는 표시 레이어(app)의 몫, 여기는 산출물 생성.

■ PDF도 교체 가능 (OCR과 같은 패턴)
    reportlab 있으면 진짜 PDF(내장 한국어 폰트, 외부 폰트 파일 불필요),
    없으면 HTML로 폴백(브라우저 인쇄→PDF). 무거운 의존성을 강제하지 않는다.
"""

from __future__ import annotations

import csv
import io
import html
from collections import Counter, defaultdict
from datetime import datetime

from schema import EvidenceRecord, ProvisionType


GLOBAL_DISCLAIMER = (
    "본 문서는 사용자가 지목한 자료를 자동으로 정리·봉인한 결과이며, 법적 판단이 아니다. "
    "형식적 특징 관찰과 참고 조항 유형은 법률 전문가 검토를 위한 참고 자료일 뿐이며, "
    "죄목·진위(사실/허위)·동일인 여부를 확정하지 않는다. 최종 판단은 법률 전문가에게."
)


# ─────────────────────────────────────────────────────────────
# 공통 헬퍼
# ─────────────────────────────────────────────────────────────
def _dt(d: datetime | None) -> str:
    return d.strftime("%Y-%m-%d %H:%M") if d else ""

def _present_features(rec: EvidenceRecord) -> str:
    return ", ".join(f.feature.value for f in rec.formal_features if f.present)

def _provision_types(rec: EvidenceRecord) -> str:
    return ", ".join(p.provision.value for p in rec.related_provisions)


# ─────────────────────────────────────────────────────────────
# 1) 증거표 — CSV (가공용)
# ─────────────────────────────────────────────────────────────
CSV_COLUMNS = [
    "id", "캡처시점", "봉인시점", "작성자표기", "출처",
    "관찰된 형식적 특징", "참고 조항 유형", "전문(원문)",
    "image_hash", "text_hash", "seal_digest", "무결성",
]

def to_csv(records: list[EvidenceRecord]) -> bytes:
    """
    Excel에서 한글이 안 깨지도록 utf-8-sig(BOM) 로 인코딩해 bytes 반환.
    가공용이라 해시 전체·원문을 포함한다(제출 전 사용자가 다루는 원자료).
    """
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(CSV_COLUMNS)
    for r in records:
        w.writerow([
            r.id, _dt(r.captured_at), _dt(r.sealed_at), r.author_id_raw, r.source_hint,
            _present_features(r), _provision_types(r), r.text,
            r.image_hash, r.text_hash, r.seal_digest,
            "봉인됨" if r.seal_digest else "미봉인",
        ])
    return buf.getvalue().encode("utf-8-sig")


# ─────────────────────────────────────────────────────────────
# 2) 타임라인 — 시간순 + 반복성 '관찰' (동일인 추정 X)
# ─────────────────────────────────────────────────────────────
def to_timeline(records: list[EvidenceRecord]) -> dict:
    """
    captured_at 기준 시간순 정렬. 같은 '작성자 표기(author_id_raw)'가 몇 번 나왔는지
    세어 반복성을 '관찰'로만 표시한다.
    ⚠️ 동일인 추정 안 함(결정 5): 같은 표기의 반복은 관찰 O. 다른 표기를 '같은 사람'으로
       잇는 추정은 하지 않는다. 동일성 판단은 사람·수사기관 몫.
    """
    ordered = sorted(records, key=lambda r: (r.captured_at is None, r.captured_at))
    id_counts = Counter(r.author_id_raw for r in records if r.author_id_raw)
    items = []
    for r in ordered:
        n = id_counts.get(r.author_id_raw, 0)
        items.append({
            "when": _dt(r.captured_at),
            "author_id_raw": r.author_id_raw,       # 원본 표기 그대로 병기
            "repeat_note": (f"동일 표기 '{r.author_id_raw}' {n}회 관찰"
                            if n > 1 else "단발 관찰"),
            "features": _present_features(r),
            "provisions": _provision_types(r),
            "record_id": r.id,
        })
    return {
        "items": items,
        "span": (f"{items[0]['when']} ~ {items[-1]['when']}"
                 if items and items[0]["when"] else ""),
        "note": "반복은 '관찰'이며 동일인 추정이 아님. 동일성 판단은 사람·수사기관 몫.",
    }


# ─────────────────────────────────────────────────────────────
# 3) 죄목별 — 참고 유형별 묶음 + 근거 + 면책 (판정 아님)
# ─────────────────────────────────────────────────────────────
def to_charges(records: list[EvidenceRecord]) -> dict:
    """
    참고 조항 '유형'별로 묶는다. 각 항목은 근거(rationale) + 면책(disclaimer)을 달고 온다.
    '이 죄에 해당한다'는 확정이 아니라 '이런 유형이 검토될 수 있다'는 참고.
    """
    grouped: dict[str, list[dict]] = defaultdict(list)
    for r in records:
        for p in r.related_provisions:
            grouped[p.provision.value].append({
                "record_id": r.id,
                "when": _dt(r.captured_at),
                "author_id_raw": r.author_id_raw,
                "rationale": p.rationale,
                "disclaimer": p.disclaimer,
            })
    return {
        "groups": dict(grouped),
        "global_disclaimer": GLOBAL_DISCLAIMER,
    }


# ─────────────────────────────────────────────────────────────
# 증거표 — HTML (PDF 폴백 & 일반 표시용)
# ─────────────────────────────────────────────────────────────
def to_html(records: list[EvidenceRecord]) -> str:
    e = html.escape
    rows = "".join(
        "<tr>"
        f"<td>{e(r.id)}</td><td>{e(_dt(r.captured_at))}</td>"
        f"<td>{e(r.author_id_raw)}</td><td>{e(_present_features(r))}</td>"
        f"<td>{e(_provision_types(r))}</td>"
        f"<td class='mono'>{e(r.seal_digest[:16])}…</td>"
        "</tr>"
        for r in records
    )
    return f"""<!doctype html><meta charset="utf-8">
<style>
 body{{font-family:sans-serif;margin:32px;color:#222}}
 h1{{font-size:18px}} table{{border-collapse:collapse;width:100%;font-size:12px}}
 th,td{{border:1px solid #ccc;padding:6px;text-align:left;vertical-align:top}}
 th{{background:#f2f2f2}} .mono{{font-family:monospace}}
 .disc{{font-size:11px;color:#666;margin-top:16px;line-height:1.5}}
</style>
<h1>악플 증거표 (제출용 초안)</h1>
<table><thead><tr>
 <th>ID</th><th>캡처시점</th><th>작성자표기</th>
 <th>관찰된 형식적 특징</th><th>참고 조항 유형</th><th>봉인해시</th>
</tr></thead><tbody>{rows}</tbody></table>
<p class="disc">※ {e(GLOBAL_DISCLAIMER)}</p>"""


# ─────────────────────────────────────────────────────────────
# 증거표 — PDF (reportlab 한국어 CID, 없으면 HTML 폴백)
# ─────────────────────────────────────────────────────────────
def to_pdf(records: list[EvidenceRecord], out_path: str) -> dict:
    """
    reportlab이 있으면 진짜 PDF를 out_path에 쓴다(내장 한국어 폰트 → 외부 폰트 파일 불필요).
    없으면 out_path 를 .html 로 바꿔 HTML을 쓰고 그 경로를 돌려준다(브라우저 인쇄→PDF).
    반환: {"path": ..., "format": "pdf"|"html"}
    """
    try:
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.units import mm
        from reportlab.lib import colors
        from reportlab.pdfbase import pdfmetrics
        from reportlab.pdfbase.cidfonts import UnicodeCIDFont
        from reportlab.platypus import (SimpleDocTemplate, Paragraph, Spacer,
                                        Table, TableStyle)
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    except ImportError:
        path = out_path.rsplit(".", 1)[0] + ".html"
        with open(path, "w", encoding="utf-8") as f:
            f.write(to_html(records))
        return {"path": path, "format": "html"}

    KFONT = "HYSMyeongJo-Medium"        # reportlab 내장 한국어 CID 폰트
    pdfmetrics.registerFont(UnicodeCIDFont(KFONT))
    styles = getSampleStyleSheet()
    body = ParagraphStyle("kbody", parent=styles["Normal"], fontName=KFONT,
                          fontSize=9, leading=13)
    title = ParagraphStyle("ktitle", parent=styles["Title"], fontName=KFONT, fontSize=16)
    small = ParagraphStyle("ksmall", parent=styles["Normal"], fontName=KFONT,
                           fontSize=8, leading=12, textColor=colors.grey)

    doc = SimpleDocTemplate(out_path, pagesize=A4,
                            topMargin=18*mm, bottomMargin=18*mm,
                            leftMargin=15*mm, rightMargin=15*mm)
    story = [Paragraph("악플 증거표 (제출용)", title), Spacer(1, 6)]
    story.append(Paragraph("무결성 봉인됨 — 각 건의 봉인해시로 제출 후 변경 여부를 확인할 수 있음.",
                           small))
    story.append(Spacer(1, 10))

    header = ["ID", "캡처시점", "작성자표기", "관찰 특징", "참고 유형", "봉인해시"]
    data = [[Paragraph(h, body) for h in header]]
    for r in records:
        data.append([
            Paragraph(r.id, body),
            Paragraph(_dt(r.captured_at), body),
            Paragraph(html.escape(r.author_id_raw), body),
            Paragraph(_present_features(r) or "-", body),
            Paragraph(_provision_types(r) or "-", body),
            Paragraph((r.seal_digest[:16] + "…") if r.seal_digest else "-", body),
        ])
    table = Table(data, colWidths=[22*mm, 26*mm, 26*mm, 38*mm, 38*mm, 30*mm], repeatRows=1)
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#eeeeee")),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.grey),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("FONTNAME", (0, 0), (-1, -1), KFONT),
    ]))
    story.append(table)
    story.append(Spacer(1, 14))
    story.append(Paragraph("※ " + GLOBAL_DISCLAIMER, small))

    doc.build(story)
    return {"path": out_path, "format": "pdf"}


# ─────────────────────────────────────────────────────────────
# 더미 3건으로 세 뷰 전부 확인 (실제 증거 아님)
# ─────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from seal import seal_record
    from schema import ObservedFeature, ProvisionReference, FormalFeature

    def mk(text, author, when, feats, provs):
        r = EvidenceRecord(text=text, author_id_raw=author, source_hint="OO커뮤니티",
                           captured_at=when, formal_features=feats, related_provisions=provs)
        return seal_record(r, b"\x89PNG" + text.encode())

    recs = [
        mk("야 너 진짜 병신 같다 꺼져", "user_1234", datetime(2026, 6, 20, 14, 30),
           [ObservedFeature(FormalFeature.TARGET_IDENTIFIED, True, note="아이디 호명"),
            ObservedFeature(FormalFeature.DEROGATORY_EXPRESSION, True, note="경멸 표현")],
           [ProvisionReference(ProvisionType.INSULT, "특정인 지목 + 비하 표현 관찰")]),
        mk("저놈 2024년에 회삿돈 횡령했다더라", "user_1234", datetime(2026, 6, 22, 9, 10),
           [ObservedFeature(FormalFeature.TARGET_IDENTIFIED, True),
            ObservedFeature(FormalFeature.FACTUAL_DETAIL_FORM, True, note="구체 정황 서술 형식")],
           [ProvisionReference(ProvisionType.DEFAMATION, "특정 대상 + 구체적 정황 서술 형식 관찰")]),
        mk("한심하다 진짜", "hater_77", datetime(2026, 6, 21, 20, 0),
           [ObservedFeature(FormalFeature.DEROGATORY_EXPRESSION, True)],
           []),
    ]

    print("=== CSV (앞 120바이트) ===")
    print(to_csv(recs)[:120], "…")

    print("\n=== 타임라인 ===")
    tl = to_timeline(recs)
    print("기간:", tl["span"])
    for it in tl["items"]:
        print(f"  {it['when']} | {it['author_id_raw']} | {it['repeat_note']} | 특징:{it['features']}")
    print("  주의:", tl["note"])

    print("\n=== 죄목별 ===")
    ch = to_charges(recs)
    for gtype, entries in ch["groups"].items():
        print(f"  [{gtype}] {len(entries)}건")
        for en in entries:
            print(f"    - {en['record_id']} | 근거: {en['rationale']}")
            print(f"      면책: {en['disclaimer']}")

    print("\n=== PDF ===")
    out = to_pdf(recs, "/tmp/evidence_report.pdf")
    print("  결과:", out)
