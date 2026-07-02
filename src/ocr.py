"""
OCR — 캡처 → 텍스트 (엔진 교체 가능한 구조)
==========================================

■ 왜 '엔진 교체 가능'하게 짜나
    easyocr(한국어 강함, 대신 PyTorch로 무거움) vs pytesseract(가벼움, 시스템 설치 필요)의
    선택을 '지금' 확정하지 않는다. 파이프라인은 엔진의 '결과 텍스트'만 필요로 하므로,
    인터페이스를 고정하고 실제 엔진은 배포 시점에 꽂는다. (스키마·분류계약을 먼저 잠근 것과 같은 전략)

■ 정확도가 make-or-break가 아닌 이유 (설계)
    1) 진짜 증거는 '이미지 자체'다 — 봉인에서 image_hash로 원본 캡처를 고정한다.
       OCR 텍스트는 그 위에 얹는 검색·분류용 편의 레이어일 뿐, 증거의 원본이 아니다.
    2) OCR은 '초안'이다 → 사용자가 훑어 고친 뒤 봉인한다(review_then_seal 흐름).
       "사람이 확인, 도구는 보조"라는 이 프로젝트의 관통 철학과 일치. 오탈자는 봉인 전에 사람이 잡는다.
    → 그래서 봉인되는 것은 '사용자가 확인·교정한 텍스트'이고, 원본 이미지는 그대로 별도 봉인된다.

■ 비용 성격 (README 비용 제약)
    OCR은 '로컬' 처리라 토큰 비용이 0이다. 여기서의 비용은 설치 용량·메모리·속도(무료 배포 환경 부담).
    → 큰 모델(④분류) 호출 비용과는 다른 종류. OCR 엔진 무게는 '배포 자원' 문제로 다룬다.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Optional


@dataclass
class OCRResult:
    text: str                 # 추출된 초안 텍스트 (교정 전)
    engine: str               # 어떤 엔진이 뽑았는지 (기록용)
    ok: bool = True           # 엔진이 실제로 돌았는지 (False = 스텁/미설치)
    note: str = ""


# ─────────────────────────────────────────────────────────────
# 엔진 어댑터 — import 가드로 '설치된 것만' 시도한다.
#   requirements.txt에 아직 아무 엔진도 못박지 않는다.
#   pip install easyocr / pytesseract 하면 해당 어댑터가 자동으로 살아난다.
# ─────────────────────────────────────────────────────────────
def _try_easyocr(image_bytes: bytes, langs: list[str]) -> Optional[OCRResult]:
    try:
        import easyocr  # noqa
        import numpy as np
        from PIL import Image
        import io
        reader = easyocr.Reader(langs, gpu=False)
        img = np.array(Image.open(io.BytesIO(image_bytes)))
        lines = reader.readtext(img, detail=0, paragraph=True)
        return OCRResult("\n".join(lines), engine="easyocr", ok=True)
    except ImportError:
        return None
    except Exception as e:
        return OCRResult("", engine="easyocr", ok=False, note=f"실행 오류: {e}")


def _try_pytesseract(image_bytes: bytes, langs: list[str]) -> Optional[OCRResult]:
    try:
        import pytesseract  # noqa
        from PIL import Image
        import io
        import os
        lang = "+".join("kor" if l == "ko" else "eng" if l == "en" else l for l in langs)
        # 댓글 캡처는 '한 덩어리 텍스트'에 가까움 → psm 6(단일 블록)이 레이아웃 오해를 크게 줄인다.
        # 그레이스케일 변환도 한글 인식률을 올린다.
        cfg = ["--psm 6"]
        # 시스템에 한국어팩이 없을 때, 직접 받은 traineddata 폴더를 가리키게 함(배포 유연성).
        tdir = os.environ.get("TESSDATA_DIR") or os.environ.get("TESSDATA_PREFIX")
        if tdir:
            cfg.append(f"--tessdata-dir {tdir}")
        img = Image.open(io.BytesIO(image_bytes)).convert("L")
        text = pytesseract.image_to_string(img, lang=lang, config=" ".join(cfg))
        return OCRResult(text.strip(), engine="pytesseract", ok=bool(text.strip()))
    except ImportError:
        return None
    except Exception as e:
        return OCRResult("", engine="pytesseract", ok=False, note=f"실행 오류: {e}")


# 우선순위: 설치돼 있으면 easyocr(한국어 강함) → 없으면 pytesseract → 둘 다 없으면 스텁
_ENGINE_CHAIN: list[Callable[[bytes, list[str]], Optional[OCRResult]]] = [
    _try_easyocr,
    _try_pytesseract,
]


def extract_text(image_bytes: bytes, langs: list[str] | None = None) -> OCRResult:
    """
    캡처 이미지에서 '초안' 텍스트를 뽑는다. 설치된 엔진을 순서대로 시도하고,
    아무 엔진도 없으면 스텁 결과(빈 텍스트 + 안내)를 돌려준다.
    반환 텍스트는 '교정 전 초안' — 봉인 전에 반드시 사용자 확인을 거친다(아래 review_then_seal).
    """
    langs = langs or ["ko", "en"]
    for engine in _ENGINE_CHAIN:
        res = engine(image_bytes, langs)
        if res is not None:
            return res
    return OCRResult(
        "", engine="none", ok=False,
        note="OCR 엔진 미설치. easyocr(한국어 강함) 또는 pytesseract + 한국어 데이터 설치 시 "
             "자동 인식이 켜집니다. 사용자가 악플을 직접 다시 쓰지 않도록 자동 추출을 권장.",
    )


import re as _re

def strip_boilerplate(text: str) -> str:
    """
    OCR 전체 텍스트에서 '댓글 본문'만 남기려는 가벼운 휴리스틱.
    아이디 줄·시간 줄·버튼 줄(추천/답글/신고 등)을 걷어낸다.
    → 사용자가 본문만 확인하면 되게 해서 손대는 양(=재노출)을 더 줄인다.
    완벽 추출이 아니라 '편집량 축소'가 목적. 지운 게 아쉬우면 원본 OCR을 쓰면 됨.
    """
    drop_line = _re.compile(
        r"^\s*(\d{4}[.\-/]\d{1,2}[.\-/]\d{1,2}.*"      # 날짜/시간 줄
        r"|.*(추천|답글|신고|좋아요|공유)\s*\d*\s*$"      # 버튼 줄
        r"|[\w.\-]{2,20}$)"                              # 아이디처럼 보이는 단독 토큰 줄
    )
    lines = [ln for ln in text.splitlines() if ln.strip()]
    body = [ln for ln in lines if not drop_line.match(ln.strip())]
    return "\n".join(body).strip() or text.strip()


# ─────────────────────────────────────────────────────────────
# 초안 → 교정 → 봉인 계약 (사람이 확인, 도구는 보조)
# ─────────────────────────────────────────────────────────────
def review_then_seal(image_bytes: bytes, corrected_text: str, record, seal_fn):
    """
    파이프라인의 OCR→봉인 접합부.
    corrected_text = 사용자가 OCR 초안을 훑어보고 확정한 텍스트(그대로 두든 고치든).
    이 확정 텍스트를 레코드에 넣고, 원본 이미지 바이트와 함께 봉인한다.

    seal_fn 은 seal.seal_record 를 주입받는다(모듈 간 결합 최소화 = 테스트 쉬움).
    """
    record.text = corrected_text          # 봉인되는 건 '사용자가 확인한' 텍스트
    return seal_fn(record, image_bytes)   # 이미지도 함께 봉인 (image_hash)


# ─────────────────────────────────────────────────────────────
# 엔진 없이도 인터페이스·접합부가 도는지 확인 (더미)
# ─────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from schema import EvidenceRecord
    from seal import seal_record, verify_record
    from datetime import datetime

    fake_image = b"\x89PNG...(dummy capture)..."

    # 1) 엔진 미설치 환경에서의 동작
    res = extract_text(fake_image)
    print("OCR 초안 추출:")
    print("  engine:", res.engine, "| ok:", res.ok)
    print("  note  :", res.note)

    # 2) 초안(여기선 붙여넣기로 대체) → 사용자 교정 → 봉인
    draft = res.text or "(엔진 미설치 → 붙여넣기 텍스트로 대체)"
    corrected = "야 너 진짜 병신 같다 꺼져"     # 사용자가 확인·확정한 텍스트
    rec = EvidenceRecord(author_id_raw="user_1234", source_hint="OO커뮤니티",
                         captured_at=datetime(2026, 6, 20, 14, 30))
    review_then_seal(fake_image, corrected, rec, seal_record)

    print("\n초안 → 교정 → 봉인 완료:")
    print("  봉인 텍스트:", rec.text)
    print("  seal_digest:", rec.seal_digest[:16], "…")
    print("  검증:", verify_record(rec, fake_image).detail)
