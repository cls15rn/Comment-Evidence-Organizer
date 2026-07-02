"""
[MODEL] screen() 백엔드 — 사전학습 UnSmile 모델 (있으면 사용, 없으면 규칙 폴백)
==========================================================================

classify.screen() 의 '작은 모델' 자리. 스마일게이트가 공개한 사전학습 모델
`smilegate-ai/kor_unsmile`(한국어 혐오·악플 다중 라벨)로 '악플 후보 여부'를 1차로 거른다.

■ 라이선스 안전 (kor_unsmile = CC-BY-NC-ND)
    - 모델 파일을 이 저장소에 넣지 않는다. 실행 시 Hugging Face에서 로드만 한다 → 재배포 아님.
    - 비상업 데모 목적. (README '데이터 · 출처' 참조)

■ 자원 안전 (폴백)
    - transformers/torch 미설치, 네트워크 불가, 로드 실패 등 어떤 이유로든 모델이 없으면
      조용히 None 을 반환한다 → screen()이 규칙 스텁으로 폴백. (무료 배포 자원 부족 대비)
    - 로드는 1회만 시도하고 결과를 캐시한다(실패 시 매번 재시도 안 함).
"""

from __future__ import annotations

from typing import Optional

_MODEL_NAME = "smilegate-ai/kor_unsmile"
_pipe = None
_load_failed = False


def _get_pipe():
    """파이프라인을 1회 지연 로드. 실패하면 None 을 반환하고 다시 시도하지 않는다."""
    global _pipe, _load_failed
    if _pipe is not None:
        return _pipe
    if _load_failed:
        return None
    try:
        from transformers import pipeline   # transformers 미설치면 ImportError
        _pipe = pipeline(
            "text-classification",
            model=_MODEL_NAME,
            top_k=None,                       # 모든 라벨 점수 반환(멀티라벨)
            function_to_apply="sigmoid",
        )
        return _pipe
    except Exception:
        _load_failed = True                   # 네트워크·메모리·미설치 등 → 폴백 신호
        return None


def is_available() -> bool:
    return _get_pipe() is not None


def status() -> str:
    """
    모델 로드를 '유발하지 않고' 현재 상태만 보고한다(사이드바 배지용).
      'model'   : 모델이 이미 로드됨
      'rules'   : 로드 시도 실패 → 규칙 폴백 중
      'unknown' : 아직 로드 시도 전(첫 분류 때 결정됨)
    """
    if _pipe is not None:
        return "model"
    if _load_failed:
        return "rules"
    return "unknown"


def model_screen(text: str, threshold: float = 0.5) -> Optional[bool]:
    """
    사전학습 UnSmile로 '악플 후보' 여부 판단.
    반환: True/False (모델 사용) | None (모델 없음 → 규칙 폴백하라는 신호)

    판단: 라벨 중 'clean'을 뺀 '나쁜' 라벨의 최고 점수가 임계 이상이거나 clean 점수보다 크면 후보.
    (임계는 느슨하게 — 놓쳐도 사용자 지목이 안전망이므로 과하게 엄격할 필요 없음)
    """
    pipe = _get_pipe()
    if pipe is None:
        return None
    try:
        out = pipe(text)
        rows = out[0] if out and isinstance(out[0], list) else out
        scores = {d["label"]: float(d["score"]) for d in rows}
    except Exception:
        return None
    clean = scores.get("clean", 0.0)
    bad_max = max((s for label, s in scores.items() if label != "clean"), default=0.0)
    return (bad_max >= threshold) or (bad_max > clean)
