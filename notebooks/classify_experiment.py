"""
분류기 실험 — 출력 계약 확정 (규칙 스텁, 비용 0)
================================================

이 파일의 목적은 '정확한 분류'가 아니라 **출력 계약(output contract)을 못박는 것**이다.
분류기가 EvidenceRecord의 formal_features / related_provisions를 '어떤 모양으로' 채우는지를
규칙 기반 더미로 먼저 확정해 두면, 나중에 로컬 모델은 이 계약을 '채우기만' 하면 된다.
(→ 모델 유무·종류와 무관하게 설계가 진행되고, 이 단계 비용은 0)

■ 저비용 제약을 '구조'로 박기 — 작은/큰 모델 2단 분리 (설계확정 6 / README 비용 제약)
    screen()          : 작은/로컬 모델 역할. 악플 '후보'인지 싸게 1차 거름.
    observe_features(): 형식적 특징 관찰(설계결정 4). 판정 아님.
    map_provisions()  : 큰 모델 역할. 걸러진 소수에만 근거(rationale) 생성.
    classify()        : 오케스트레이션. screen을 통과한 것만 큰 모델 단계로 보냄
                        → 큰 모델 도달량↓ = 비용↓. 놓쳐도 '사용자 지목'이 있어 안전.

지금은 세 함수 전부 규칙 더미다. 로컬 모델로 대체할 자리는 [MODEL] 태그로 표시.
상세 근거: LLM_아이디어_메모장.md '아이디어 3 → 설계 확정' 4·6 + README 설계결정 4·5.
"""

from __future__ import annotations

import sys
from pathlib import Path

# src/ 를 import 경로에 추가 (notebooks/ 와 src/ 는 형제)
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from schema import (
    EvidenceRecord,
    ObservedFeature,
    ProvisionReference,
    FormalFeature,
    ProvisionType,
)


# ─────────────────────────────────────────────────────────────
# [MODEL] 작은/로컬 모델 자리 — 1차 거름 (screening)
# ─────────────────────────────────────────────────────────────
def screen(text: str) -> bool:
    """
    악플 '후보'인지 싸게 판단. 큰 모델로 보낼지 말지를 결정하는 값싼 게이트.
    지금은 규칙 더미. 나중에 작은/로컬 분류 모델로 대체.

    ⚠️ 이 게이트는 '판정'이 아니다 — 통과 못 해도 사용자가 이미 지목했으므로
       classify()에서 강제 통과 옵션으로 덮을 수 있다(정확도 보완 = 사용자 지목).
    """
    # [MODEL] → 작은 모델의 이진 분류로 교체
    return _has_any(text, _DEROGATORY_LEXICON) or _looks_targeted(text)


# ─────────────────────────────────────────────────────────────
# 형식적 특징 관찰 (설계결정 4: 판정 아님, 겉으로 보이는 것만)
# ─────────────────────────────────────────────────────────────
def observe_features(text: str, source_is_public: bool | None = None) -> list[ObservedFeature]:
    """
    텍스트에서 '관찰 가능한 형식적 특징'만 뽑는다. 진위·의도·죄목은 판단하지 않는다.
    관찰됨/안 됨을 둘 다 기록해 '무엇을 확인했는지'를 남긴다.

    주의: 특징의 출처가 다르다.
      - 텍스트에서 옴 : 비하 표현 / 특정인 지목 / 구체적 정황 서술 형식
      - 맥락에서 옴   : 공개 위치 게시 → 텍스트가 아니라 source_hint(사용자 입력)에서 결정
    """
    feats: list[ObservedFeature] = []

    # 1) 특정인 지목 (텍스트)
    targeted = _looks_targeted(text)
    feats.append(ObservedFeature(
        FormalFeature.TARGET_IDENTIFIED, targeted,
        evidence_span=_first_hit(text, _TARGET_MARKERS) if targeted else "",
        note="특정 대상을 호명/지칭하는 표현 관찰" if targeted else "",
    ))

    # 2) 공개 위치 게시 (맥락 = source_hint에서 옴, 텍스트 아님)
    if source_is_public is not None:
        feats.append(ObservedFeature(
            FormalFeature.PUBLIC_LOCATION, bool(source_is_public),
            note="사용자가 지목한 게시 위치가 공개 공간" if source_is_public else "비공개/미상",
        ))

    # 3) 비하·모욕 표현 (텍스트)
    dero = _has_any(text, _DEROGATORY_LEXICON)
    feats.append(ObservedFeature(
        FormalFeature.DEROGATORY_EXPRESSION, dero,
        evidence_span=_first_hit(text, _DEROGATORY_LEXICON) if dero else "",
        note="비하·경멸로 읽히는 표현 관찰(단정 아님)" if dero else "",
    ))

    # 4) 구체적 정황 서술 형식 (텍스트) — ⚠️ 진위 판정 아님, '서술 형식' 유무만
    detailed = _looks_factual_form(text)
    feats.append(ObservedFeature(
        FormalFeature.FACTUAL_DETAIL_FORM, detailed,
        note="구체적 사건·정황을 서술하는 형식 관찰(사실/허위는 판정 안 함)" if detailed else "",
    ))

    return feats


# ─────────────────────────────────────────────────────────────
# [MODEL] 큰 모델 자리 — 참고 조항 유형 + 근거 생성
# ─────────────────────────────────────────────────────────────
def map_provisions(feats: list[ObservedFeature]) -> list[ProvisionReference]:
    """
    관찰된 형식적 특징 → 참고 조항 '유형' 연결 + 근거 서술.
    핵심 원칙(설계결정 4·5): 둘 중 하나를 '고르지' 않는다. 소지가 있으면 둘 다 참고로 띄운다.
    면책은 스키마에서 항목마다 강제로 붙는다.

    지금은 규칙 더미. rationale 생성이 큰 모델이 빛나는 지점 → [MODEL]로 교체 예정.
    """
    present = {f.feature for f in feats if f.present}
    refs: list[ProvisionReference] = []

    # 모욕 유형: 특정인 지목 + 비하 표현 (구체적 사건 서술 없이도 성립 가능)
    if FormalFeature.TARGET_IDENTIFIED in present and FormalFeature.DEROGATORY_EXPRESSION in present:
        refs.append(ProvisionReference(
            ProvisionType.INSULT,
            rationale=(  # [MODEL] → 큰 모델의 근거 서술로 교체
                "특정 대상을 지목한 상태에서 비하·경멸 표현이 관찰됨. "
                "이런 형식은 모욕 유형 검토 대상이 될 수 있음(구체적 사건 서술 유무와 무관)."
            ),
        ))

    # 명예훼손 유형: 특정인 지목 + 구체적 정황 서술 형식
    if FormalFeature.TARGET_IDENTIFIED in present and FormalFeature.FACTUAL_DETAIL_FORM in present:
        refs.append(ProvisionReference(
            ProvisionType.DEFAMATION,
            rationale=(  # [MODEL]
                "특정 대상 + 구체적 사건·정황을 서술하는 형식이 함께 관찰됨. "
                "이런 형식은 명예훼손 유형 검토 대상이 될 수 있음. "
                "다만 서술 내용의 사실/허위 여부는 이 도구가 판단하지 않음."
            ),
        ))

    return refs


# ─────────────────────────────────────────────────────────────
# 오케스트레이션 — 저비용 2단 구조
# ─────────────────────────────────────────────────────────────
def classify(
    text: str,
    source_is_public: bool | None = None,
    user_flagged: bool = True,
) -> tuple[list[ObservedFeature], list[ProvisionReference]]:
    """
    한 건을 분류한다. 값싼 screen()을 통과한 것만 비싼 map_provisions() 단계로 보낸다.

    user_flagged=True(사용자가 이미 지목)면 screen을 못 통과해도 강제로 관찰까지는 진행한다
    (정확도 보완 = 사용자 지목). 큰 모델 근거 생성은 관찰 결과가 있을 때만 돈다.
    """
    reached_big_model = screen(text) or user_flagged
    if not reached_big_model:
        return [], []

    feats = observe_features(text, source_is_public=source_is_public)
    provs = map_provisions(feats)   # 관찰 결과가 조건에 맞을 때만 실제로 채워짐
    return feats, provs


# ─────────────────────────────────────────────────────────────
# 규칙 더미의 내부 헬퍼 (전부 [MODEL]로 대체될 자리)
# ─────────────────────────────────────────────────────────────
_DEROGATORY_LEXICON = ["병신", "쓰레기", "꺼져", "죽어", "역겹", "한심", "멍청"]  # 더미 사전
_TARGET_MARKERS = ["@", "야 ", "너 ", "저 새끼", "저놈", "그 사람"]              # 더미 지목 단서

def _has_any(text: str, lexicon: list[str]) -> bool:
    return any(w in text for w in lexicon)

def _first_hit(text: str, lexicon: list[str]) -> str:
    for w in lexicon:
        if w in text:
            return w
    return ""

def _looks_targeted(text: str) -> bool:
    return _has_any(text, _TARGET_MARKERS)

def _looks_factual_form(text: str) -> bool:
    # 더미: 날짜·시간·수치·'했다' 서술 등 '구체적 서술 형식' 단서. (진위 아님)
    import re
    return bool(re.search(r"\d{4}[.\-/년]|\d+회|\d+명|했다|했음|저질", text))


# ─────────────────────────────────────────────────────────────
# 더미 데이터로 계약 확인 (실제 증거 아님)
# ─────────────────────────────────────────────────────────────
if __name__ == "__main__":
    samples = [
        # (설명, 텍스트, 공개여부)
        ("모욕 유형 예상", "야 너 진짜 병신 같다 꺼져", True),
        ("명예훼손 유형 예상", "저 사람 2024년에 회삿돈 횡령했다더라 특정 아이디임", True),
        ("게이트 탈락(일반)", "오늘 날씨 좋네요", True),
    ]
    for label, text, pub in samples:
        feats, provs = classify(text, source_is_public=pub, user_flagged=False)
        rec = EvidenceRecord(text=text, source_hint="예시", formal_features=feats,
                             related_provisions=provs)
        print(f"\n[{label}] user_flagged=False (사용자 미지목 가정)")
        print("  관찰:", [(f.feature.value, f.present) for f in feats] or "screen 탈락 → 큰 모델 미도달")
        print("  참고 유형:", [p.provision.value for p in provs])
        for p in provs:
            print("    -", p.provision.value, "| 근거:", p.rationale[:40], "…")
            print("      면책:", p.disclaimer)
        print("  표지(cover):", rec.cover())
