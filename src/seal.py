"""
무결성 봉인 (Integrity Seal) — SHA-256
======================================

이 도구의 간판 차별점. "제출 후 안 바뀜(무결성)"을 SHA-256 해시로 증명한다.
표준 라이브러리(hashlib, json)만 쓴다 → 의존성 0 = 저비용 제약과 합치.

■ 무엇을 증명하나 / 못 하나 (설계결정 3 — 정직하게)
    ✅ 무결성(integrity)  : 봉인된 이미지·텍스트·메타데이터가 그 뒤로 '안 바뀌었다'.
    ❌ 시점 보증(existence-time) : '언제' 존재했는지는 증명 못 한다.
       sealed_at·captured_at 은 모두 자기신고라 "그 날짜도 네가 적었잖아"를 못 막는다.
       → 무결성 ≠ 존재 시점 증명. 시점 보증은 TSA(RFC 3161) 확장 영역(데모 밖).

■ 왜 '묶음 해시(seal_digest)'인가
    이미지 해시 + 텍스트 해시만 따로 두면 각각의 무결성만 증명된다. 둘을 묶어(+ 캡처 시점,
    작성자 표기, 출처) 하나의 봉인 해시로 만들면, 나중에 '한 조각만 슬쩍 바꿔치기'하는
    것까지 탐지된다. 이게 "느슨한 해시 두 개"와 "봉인"의 차이.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime

from schema import EvidenceRecord


# ─────────────────────────────────────────────────────────────
# 기본 해시 (교체 불가 — 표준 SHA-256)
# ─────────────────────────────────────────────────────────────
def sha256_bytes(data: bytes) -> str:
    """원본 바이트(예: 캡처 이미지)의 SHA-256 16진 문자열."""
    return hashlib.sha256(data).hexdigest()


def sha256_text(text: str) -> str:
    """텍스트의 SHA-256. 인코딩을 UTF-8로 고정해 결정론적으로."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# ─────────────────────────────────────────────────────────────
# 봉인 결과
# ─────────────────────────────────────────────────────────────
@dataclass
class SealResult:
    image_hash: str
    text_hash: str
    seal_digest: str
    sealed_at: datetime


def _canonical(image_hash: str, text_hash: str,
               captured_at: datetime | None, author_id_raw: str,
               source_hint: str) -> str:
    """
    봉인 대상 필드를 결정론적 문자열로 직렬화한다.
    sort_keys + ensure_ascii=False 로 순서·인코딩에 흔들리지 않게 고정.
    (같은 입력 → 항상 같은 문자열 → 항상 같은 해시)
    """
    payload = {
        "image_hash": image_hash,
        "text_hash": text_hash,
        "captured_at": captured_at.isoformat() if captured_at else None,
        "author_id_raw": author_id_raw,
        "source_hint": source_hint,
    }
    return json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def compute_seal(image_bytes: bytes, text: str,
                 captured_at: datetime | None = None,
                 author_id_raw: str = "",
                 source_hint: str = "") -> SealResult:
    """이미지·텍스트·메타데이터로 봉인값 일습을 계산한다. (레코드를 건드리지 않는 순수 함수)"""
    image_hash = sha256_bytes(image_bytes)
    text_hash = sha256_text(text)
    seal_digest = sha256_text(
        _canonical(image_hash, text_hash, captured_at, author_id_raw, source_hint)
    )
    return SealResult(image_hash, text_hash, seal_digest, datetime.now())


def seal_record(record: EvidenceRecord, image_bytes: bytes) -> EvidenceRecord:
    """
    레코드를 봉인한다. record.text 와 함께 넘어온 이미지 바이트로 해시를 계산해
    image_hash / text_hash / seal_digest / sealed_at 을 채운 뒤 그대로 돌려준다.
    (원문 text 는 그대로 둔다 — 봉인은 '지우기'가 아니라 '고정')
    """
    res = compute_seal(
        image_bytes, record.text,
        captured_at=record.captured_at,
        author_id_raw=record.author_id_raw,
        source_hint=record.source_hint,
    )
    record.image_hash = res.image_hash
    record.text_hash = res.text_hash
    record.seal_digest = res.seal_digest
    record.sealed_at = res.sealed_at
    return record


# ─────────────────────────────────────────────────────────────
# 검증 — 봉인이 의미 있으려면 '나중에 안 바뀜을 확인'할 수 있어야 한다
# ─────────────────────────────────────────────────────────────
@dataclass
class VerifyResult:
    ok: bool                 # 전체 무결성 통과 여부
    image_ok: bool
    text_ok: bool
    digest_ok: bool
    detail: str = ""

    def __bool__(self) -> bool:
        return self.ok


def verify_record(record: EvidenceRecord, image_bytes: bytes) -> VerifyResult:
    """
    봉인된 레코드가 그 뒤로 안 바뀌었는지 재계산해 대조한다.
    이미지·텍스트·묶음 해시를 각각 확인해, 어느 조각이 바뀌었는지까지 짚어준다.
    """
    recomputed = compute_seal(
        image_bytes, record.text,
        captured_at=record.captured_at,
        author_id_raw=record.author_id_raw,
        source_hint=record.source_hint,
    )
    image_ok = (recomputed.image_hash == record.image_hash)
    text_ok = (recomputed.text_hash == record.text_hash)
    digest_ok = (recomputed.seal_digest == record.seal_digest)
    ok = image_ok and text_ok and digest_ok

    if ok:
        detail = "무결성 통과 — 봉인 후 변경 없음."
    else:
        broken = []
        if not image_ok:
            broken.append("이미지")
        if not text_ok:
            broken.append("텍스트")
        if not digest_ok and image_ok and text_ok:
            broken.append("메타데이터(시점·작성자표기·출처)")
        detail = f"무결성 실패 — 변경 감지: {', '.join(broken) or '알 수 없음'}."
    return VerifyResult(ok, image_ok, text_ok, digest_ok, detail)


# ─────────────────────────────────────────────────────────────
# 더미로 봉인·검증·변조 탐지 확인 (실제 증거 아님)
# ─────────────────────────────────────────────────────────────
if __name__ == "__main__":
    from datetime import datetime as dt

    fake_image = b"\x89PNG...(dummy capture bytes)..."
    rec = EvidenceRecord(
        text="야 너 진짜 병신 같다 꺼져",
        author_id_raw="user_1234",
        source_hint="OO커뮤니티 자유게시판",
        captured_at=dt(2026, 6, 20, 14, 30),
    )

    seal_record(rec, fake_image)
    print("봉인 완료")
    print("  image_hash :", rec.image_hash[:16], "…")
    print("  text_hash  :", rec.text_hash[:16], "…")
    print("  seal_digest:", rec.seal_digest[:16], "…")
    print("  표지(cover):", rec.cover())

    print("\n[검증 1] 그대로 재검증:")
    print("  ", verify_record(rec, fake_image).detail)

    print("\n[검증 2] 텍스트를 몰래 한 글자 바꾼 경우:")
    tampered = EvidenceRecord(
        text="야 너 진짜 천사 같다 꺼져",   # '병신' → '천사'
        author_id_raw=rec.author_id_raw, source_hint=rec.source_hint,
        captured_at=rec.captured_at,
        image_hash=rec.image_hash, text_hash=rec.text_hash,
        seal_digest=rec.seal_digest, sealed_at=rec.sealed_at,
    )
    print("  ", verify_record(tampered, fake_image).detail)

    print("\n[검증 3] 캡처 날짜만 몰래 바꾼 경우:")
    tampered2 = EvidenceRecord(
        text=rec.text, author_id_raw=rec.author_id_raw, source_hint=rec.source_hint,
        captured_at=dt(2026, 1, 1, 0, 0),   # 날짜 조작
        image_hash=rec.image_hash, text_hash=rec.text_hash,
        seal_digest=rec.seal_digest, sealed_at=rec.sealed_at,
    )
    print("  ", verify_record(tampered2, fake_image).detail)
