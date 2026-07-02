"""
분류 (Classify) — notebooks 실험을 src로 승격한 정식 모듈
======================================================

notebooks/classify_experiment.py 에서 '출력 계약'을 확정한 뒤, app이 깔끔히 가져다 쓰도록
src로 정리한 버전이다(개발 흐름: notebooks 실험 → src 정리 → app 조립).
로직·계약은 노트북과 동일하며, 아래 [MODEL] 슬롯이 나중에 로컬/오픈소스 모델로 교체될 자리다.

저비용 2단 구조(설계확정 6 / README 비용 제약):
    screen()          : 작은/로컬 모델 자리. 악플 후보인지 싸게 1차 거름.
    observe_features(): 형식적 특징 관찰(설계결정 4, 판정 아님).
    map_provisions()  : 큰 모델 자리. 걸러진 소수에만 근거 생성.
    classify()        : screen 통과분만 큰 모델 단계로 → 도달량↓ = 비용↓.
                        놓쳐도 사용자 지목(user_flagged)이 안전망.
"""

from __future__ import annotations

import re

from schema import (
    ObservedFeature, ProvisionReference, FormalFeature, ProvisionType,
)


# ─────────────────────────────────────────────────────────────
# [MODEL] 작은/로컬 모델 자리 — 1차 거름
#   사전학습 UnSmile 모델을 우선 사용, 없으면(미설치·네트워크·자원 부족) 규칙 스텁으로 폴백.
# ─────────────────────────────────────────────────────────────
def screen(text: str) -> bool:
    """악플 후보인지 1차로 거른다. 모델 있으면 모델, 없으면 규칙."""
    from screen_model import model_screen
    m = model_screen(text)
    if m is not None:          # 모델이 판단함
        return m
    # 폴백: 규칙 스텁 (사전·마커)
    return _has_any(text, _DEROGATORY_LEXICON) or _looks_targeted(text)


# ─────────────────────────────────────────────────────────────
# 형식적 특징 관찰 (판정 아님, 겉으로 보이는 것만)
# ─────────────────────────────────────────────────────────────
def observe_features(text: str, source_is_public: bool | None = None) -> list[ObservedFeature]:
    feats: list[ObservedFeature] = []

    targeted = _looks_targeted(text)
    feats.append(ObservedFeature(
        FormalFeature.TARGET_IDENTIFIED, targeted,
        evidence_span=_first_hit(text, _TARGET_MARKERS) if targeted else "",
        note="특정 대상을 호명/지칭하는 표현 관찰" if targeted else "",
    ))

    if source_is_public is not None:
        feats.append(ObservedFeature(
            FormalFeature.PUBLIC_LOCATION, bool(source_is_public),
            note="사용자가 지목한 게시 위치가 공개 공간" if source_is_public else "비공개/미상",
        ))

    dero = _has_any(text, _DEROGATORY_LEXICON)
    feats.append(ObservedFeature(
        FormalFeature.DEROGATORY_EXPRESSION, dero,
        evidence_span=_first_hit(text, _DEROGATORY_LEXICON) if dero else "",
        note="비하·경멸로 읽히는 표현 관찰(단정 아님)" if dero else "",
    ))

    detailed = _looks_factual_form(text)
    feats.append(ObservedFeature(
        FormalFeature.FACTUAL_DETAIL_FORM, detailed,
        note="구체적 사건·정황을 서술하는 형식 관찰(사실/허위는 판정 안 함)" if detailed else "",
    ))
    return feats


# ─────────────────────────────────────────────────────────────
# [MODEL] 큰 모델 자리 — 참고 조항 유형 + 근거
# ─────────────────────────────────────────────────────────────
def map_provisions(feats: list[ObservedFeature]) -> list[ProvisionReference]:
    present = {f.feature for f in feats if f.present}
    refs: list[ProvisionReference] = []

    if FormalFeature.TARGET_IDENTIFIED in present and FormalFeature.DEROGATORY_EXPRESSION in present:
        refs.append(ProvisionReference(
            ProvisionType.INSULT,
            rationale=("특정 대상을 지목한 상태에서 비하·경멸 표현이 관찰됨. "
                       "이런 형식은 모욕 유형 검토 대상이 될 수 있음(구체적 사건 서술 유무와 무관)."),
        ))
    if FormalFeature.TARGET_IDENTIFIED in present and FormalFeature.FACTUAL_DETAIL_FORM in present:
        refs.append(ProvisionReference(
            ProvisionType.DEFAMATION,
            rationale=("특정 대상 + 구체적 사건·정황을 서술하는 형식이 함께 관찰됨. "
                       "이런 형식은 명예훼손 유형 검토 대상이 될 수 있음. "
                       "다만 서술 내용의 사실/허위 여부는 이 도구가 판단하지 않음."),
        ))
    return refs


# ─────────────────────────────────────────────────────────────
# 오케스트레이션
# ─────────────────────────────────────────────────────────────
def classify(text: str, source_is_public: bool | None = None,
             user_flagged: bool = True) -> tuple[list[ObservedFeature], list[ProvisionReference]]:
    """screen 통과분(또는 사용자 지목분)만 관찰·근거 생성 단계로 보낸다."""
    if not (screen(text) or user_flagged):
        return [], []
    feats = observe_features(text, source_is_public=source_is_public)
    return feats, map_provisions(feats)


# ── 규칙 더미 내부 헬퍼 ([MODEL]로 대체될 자리) ──────────────
_DEROGATORY_LEXICON = ["병신", "쓰레기", "꺼져", "죽어", "역겹", "한심", "멍청"]
_TARGET_MARKERS = ["@", "야 ", "너 ", "저 새끼", "저놈", "그 사람"]

def _has_any(text, lex): return any(w in text for w in lex)
def _first_hit(text, lex):
    for w in lex:
        if w in text:
            return w
    return ""
def _looks_targeted(text): return _has_any(text, _TARGET_MARKERS)
def _looks_factual_form(text):
    return bool(re.search(r"\d{4}[.\-/년]|\d+회|\d+명|했다|했음|저질|횡령", text))
