"""
증거 레코드 스키마 (Evidence Record Schema)
==========================================

이 파일은 이 프로젝트의 '척추'다. 봉인된 악플 1건이 어떤 필드를 갖는지를 정의하고,
세 가지 뷰(증거표·타임라인·죄목별)와 분류기는 전부 이 레코드를 채우거나 렌더링할 뿐이다.

산출물의 성격: 이 도구의 분류·정리 결과는 '판정'이 아니라, 나중에 법률 전문가에게
넘길 때 쓰는 '참고자료'다. 형식적 특징 관찰과 참고 조항 유형은 변호사가 검토할 때
참고하는 용도이지, 도구가 죄목을 확정하는 것이 아니다.

설계 원칙이 '필드의 존재/부재'로 못박혀 있다는 점이 이 스키마의 핵심이다.
  - 판정 안 함(설계결정 4)  → verdict/crime 같은 '단정' 필드가 없다. formal_features(관찰) +
                              related_provisions(참고 유형) + disclaimer(면책)만 있다.
  - 동일인 추정 안 함(결정 5) → author_id_raw를 '그대로' 보존만 한다. same_person_as 같은
                              추정 링크 필드가 없다. (같은 ID 반복은 뷰에서 관찰로 계산 O, 추정 X)
  - 무결성 봉인(결정 3)      → image_hash/text_hash/sealed_at. 단 자체 해시는 '무결성'이지
                              '시점 보증'이 아니다. 시점 보증(TSA)은 확장점으로만 표기.
  - 저장 ≠ 열람(결정 6)      → cover()가 원문 없이 '표지 정보'만 돌려준다.

상세 근거: 프로젝트 지식 LLM_아이디어_메모장.md '아이디어 3 → 설계 확정' 블록 + README.
표준 라이브러리만 사용한다(의존성 0 = 저비용 제약과 합치).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from enum import Enum
from typing import Optional
import uuid


# ─────────────────────────────────────────────────────────────
# 통제 어휘(controlled vocabulary)
#   자유서술이 아니라 '닫힌 목록'으로 둠으로써, 모델이 자유롭게 '판정'하는 것을
#   구조적으로 막는다. 관찰의 종류 자체를 스키마가 제한한다.
# ─────────────────────────────────────────────────────────────

class FormalFeature(Enum):
    """
    형식적 특징 — 겉으로 '관찰 가능한' 요소만. 진위·의도·죄목 판단이 아니다.

    ⚠️ 검토 지점: FACTUAL_DETAIL_FORM 은 델리케이트하다.
       설계확정에서 '사실적시' 라벨은 제거했다(사실/허위 구분 = 진위 판정이라 안 함).
       그래서 여기서 관찰하는 건 '사실이냐 허위냐'가 아니라, 구체적 사건·정황을
       '서술하는 형식'이 있느냐 없느냐(=명예훼손 유형 vs 모욕 유형을 '둘 다' 참고로
       띄우기 위한 형식적 단서)뿐이다. 진위는 절대 판정하지 않는다.
       → 이 항목이 그 선을 넘는다고 판단되면 통째로 빼도 된다. (뺄지 여부가 검토 대상)
    """
    TARGET_IDENTIFIED = "특정인 지목"          # 대상이 특정되는가 (실명·아이디·지칭 등)
    PUBLIC_LOCATION = "공개 위치 게시"          # 공개된 공간에 게시되었는가
    DEROGATORY_EXPRESSION = "비하·모욕 표현"    # 비하·경멸 표현이 포함되는가
    FACTUAL_DETAIL_FORM = "구체적 정황 서술 형식"  # 구체적 사건·정황을 '서술하는 형식'인가 (진위 판정 아님)


class ProvisionType(Enum):
    """
    참고용 관련 조항 유형.
    '이 조항에 해당한다'는 판정이 아니라 '이런 유형이 검토될 수 있다'는 참고다.
    분류기는 둘 중 하나를 '고르지' 않는다 — 해당 소지가 있으면 둘 다 참고로 띄운다.
    """
    DEFAMATION = "명예훼손 유형 (형법 제307조)"
    INSULT = "모욕 유형 (형법 제311조)"


# ─────────────────────────────────────────────────────────────
# 관찰 단위
# ─────────────────────────────────────────────────────────────

@dataclass
class ObservedFeature:
    """형식적 특징 하나의 관찰 결과. '관찰됨/안 됨'을 둘 다 기록해 무엇을 확인했는지 남긴다."""
    feature: FormalFeature
    present: bool                 # 관찰됨(True) / 관찰 안 됨(False)
    evidence_span: str = ""       # 근거가 된 원문 조각(최소 인용). present=False면 비움
    note: str = ""                # 관찰 서술 (판정 아님. 예: "특정 아이디를 직접 호명")


@dataclass
class ProvisionReference:
    """참고 조항 유형 하나. 근거 서술 + 항목별 면책이 '반드시' 함께 붙는다."""
    provision: ProvisionType
    rationale: str                # 왜 이 유형이 '검토될 수 있는지' 근거 서술 (LLM이 빛나는 지점)
    disclaimer: str = "자동 분류 결과이며 법적 판단이 아님. 최종 판단은 법률 전문가에게."


# ─────────────────────────────────────────────────────────────
# 증거 레코드 (척추)
# ─────────────────────────────────────────────────────────────

@dataclass
class EvidenceRecord:
    """봉인된 악플 1건. 세 가지 뷰와 분류기가 공유하는 단일 데이터."""

    # --- 식별 ---
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])

    # --- 사람이 넣는 것 (설계결정 1: 자동수집 아님, 사용자 지목) ---
    text: str = ""                # OCR로 뽑힌 악플 전문 (원문 = 민감정보)
    author_id_raw: str = ""       # 작성자 표기 '그대로'. 동일인 추정 안 함 → 원본 보존만
    source_hint: str = ""         # 어디서 왔는지 사용자 메모 (플랫폼·게시물 등)
    captured_at: Optional[datetime] = None   # 사용자가 밝힌 캡처 시점 (자기신고, 제3자 보증 X)

    # --- 봉인 (설계결정 3: 무결성 O, 시점 보증 X) ---
    image_hash: str = ""          # 원본 캡처 이미지의 SHA-256
    text_hash: str = ""           # OCR 텍스트의 SHA-256
    seal_digest: str = ""         # 위 해시들 + 핵심 메타데이터를 하나로 묶은 봉인 해시
                                  #   (이미지·텍스트·시점·작성자표기를 한 값으로 결속 → 부분 교체 탐지)
    sealed_at: Optional[datetime] = None     # 도구가 봉인한 시각 (이것도 자기신고 — 시점 보증 아님)
    # 확장점: TSA(RFC 3161) 제3자 시점 서명. 채워지면 '무결성 + 시점 보증'.
    #        데모 범위 밖이라 기본 None. (설계결정 3의 확장 라인)
    # 또 다른 확장 방향(향후): 캡처 자체를 이 도구(모바일 앱 등) 안에서 하게 만들면,
    #        도구가 캡처 시점을 직접 찍으므로 '사용자가 적은 날짜'보다 신뢰가 올라간다.
    #        단 이것도 서버/TSA 서명과 결합해야 완전한 제3자 보증이 됨 → 당장은 한계로 둔다.
    tsa_token: Optional[bytes] = None

    # --- 자동 관찰 (설계결정 4: 판정 아님, 형식적 특징만) ---
    formal_features: list[ObservedFeature] = field(default_factory=list)
    related_provisions: list[ProvisionReference] = field(default_factory=list)

    # --- 표지/상태 (설계결정 6: 저장 ≠ 열람) ---
    status: str = "sealed"        # sealed 등. 표지에 노출되는 값

    # 이 스키마에 '의도적으로 없는' 필드 (부재 자체가 설계) ──────────────
    #   verdict / crime / is_defamation  → 판정 안 함 (결정 4)
    #   is_factual / truth               → 진위(사실/허위) 판단 안 함 (설계확정 4)
    #   same_person_as / author_cluster  → 동일인 추정 안 함 (결정 5)
    #   author_realname / author_ip …    → 작성자 신상 수집 안 함 (Non-Goal, 수사기관 영역)
    #   complaint_draft                  → 고소장 초안 생성 안 함 (확장의 상한선)
    # 필드를 '안 만든 것'이 곧 Non-Goals의 코드 버전이다.

    def cover(self) -> dict:
        """
        표지 정보만 반환 (설계결정 6: 저장 ≠ 열람).
        원문(text)·작성자 원본을 포함하지 않는다. 봉인된 증거를 '닫힌 봉투'처럼 다루고,
        원문은 사용자가 명시적으로 펼칠 때만(=cover가 아닌 다른 경로로) 연다.
        """
        return {
            "id": self.id,
            "captured_at": self.captured_at.date() if self.captured_at else None,
            "sealed_at": self.sealed_at.date() if self.sealed_at else None,
            "status": self.status,
            "n_features": sum(1 for f in self.formal_features if f.present),
            "n_provisions": len(self.related_provisions),
            "integrity": "봉인됨(무결성)" if self.seal_digest else "미봉인",
        }
