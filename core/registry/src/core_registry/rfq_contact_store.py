"""Storage operations for encrypted RFQ contact payloads."""

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import delete, select, tuple_, update
from sqlalchemy.orm import Session

from core_registry.db.models import RfqContactPayload, RfqIntroduction, RfqRequest, RfqResponse
from core_registry.rfq_contact_crypto import (
    BUYER_CONTACT,
    PENDING_CONTACT,
    ContactBinding,
    ContactPurpose,
    EncryptedContact,
    RfqContactKeys,
    RfqContactUnavailable,
)


def contact_binding(
    authority: str,
    request: RfqRequest,
    response: RfqResponse,
    purpose: ContactPurpose,
    expires_at: datetime,
    *,
    introduction_id: str | None = None,
) -> ContactBinding:
    if purpose == BUYER_CONTACT:
        namespace, subject = request.buyer_namespace, request.buyer_subject
    else:
        namespace, subject = response.respondent_namespace, response.respondent_subject
    return ContactBinding(
        registry=authority, rfq_id=request.rfq_id, record_id=introduction_id or response.response_id,
        party_namespace=namespace, party_subject=subject, purpose=purpose, expires_at=expires_at,
    )


def store_contact(
    db: Session,
    keys: RfqContactKeys,
    response_id: str,
    contact: dict[str, str],
    binding: ContactBinding,
) -> None:
    encrypted = keys.encrypt(contact, binding)
    db.add(RfqContactPayload(
        response_id=response_id,
        purpose=binding.purpose,
        expires_at=binding.expires_at,
        format_version=encrypted.format_version,
        key_id=encrypted.key_id,
        nonce=encrypted.nonce,
        ciphertext=encrypted.ciphertext,
    ))


def open_contact(
    db: Session, keys: RfqContactKeys, response_id: str, binding: ContactBinding,
) -> dict[str, str]:
    row = db.get(RfqContactPayload, (response_id, binding.purpose))
    if row is None or row.expires_at != binding.expires_at:
        raise RfqContactUnavailable("RFQ contact is unavailable")
    return keys.decrypt(
        EncryptedContact(row.format_version, row.key_id, row.nonce, row.ciphertext), binding,
    )


def end_pending_responses(db: Session, rfq_id: str, state: str) -> None:
    current_pending = (RfqResponse.rfq_id == rfq_id, RfqResponse.state == "pending")
    pending_ids = select(RfqResponse.response_id).where(*current_pending)
    db.execute(delete(RfqContactPayload).where(
        RfqContactPayload.response_id.in_(pending_ids), RfqContactPayload.purpose == PENDING_CONTACT,
    ))
    db.execute(update(RfqResponse).where(
        *current_pending,
    ).values(state=state, version=RfqResponse.version + 1))


@dataclass(frozen=True)
class ContactSweep:
    removed: int
    oldest_overdue_seconds: float


def sweep_contact_batch(db: Session, now: datetime, batch_size: int = 100) -> ContactSweep:
    if batch_size <= 0:
        raise ValueError("an RFQ contact sweep requires a positive batch size")
    due = db.execute(select(
        RfqContactPayload.response_id, RfqContactPayload.purpose, RfqContactPayload.expires_at,
    ).where(RfqContactPayload.expires_at <= now).order_by(
        RfqContactPayload.expires_at, RfqContactPayload.response_id, RfqContactPayload.purpose,
    ).limit(batch_size).with_for_update()).all()
    if not due:
        return ContactSweep(0, 0)
    removed = db.execute(delete(RfqContactPayload).where(
        tuple_(RfqContactPayload.response_id, RfqContactPayload.purpose).in_(
            [(response_id, purpose) for response_id, purpose, _ in due]
        ),
    )).rowcount
    return ContactSweep(removed, (now - due[0].expires_at).total_seconds())


def redact_restored_contacts(db: Session, now: datetime) -> int:
    """Remove uncertain payloads and end their remaining eligibility atomically."""
    removed = db.execute(delete(RfqContactPayload)).rowcount
    db.execute(update(RfqIntroduction).where(
        RfqIntroduction.ended_at.is_(None),
    ).values(ended_at=now, version=RfqIntroduction.version + 1))
    db.execute(update(RfqResponse).where(
        RfqResponse.state == "pending",
    ).values(state="expired", version=RfqResponse.version + 1))
    return removed


def require_retained_keys(db: Session, keys: RfqContactKeys) -> None:
    retained = set(db.scalars(select(RfqContactPayload.key_id).distinct()))
    if retained - keys.keys.keys():
        raise RfqContactUnavailable("a retained RFQ contact key is unavailable")


def rotate_contact_batch(
    db: Session, authority: str, keys: RfqContactKeys, batch_size: int = 100,
) -> int:
    if batch_size <= 0:
        raise ValueError("RFQ contact rotation requires a positive batch size")
    rows = db.execute(select(
        RfqContactPayload, RfqResponse, RfqRequest, RfqIntroduction.introduction_id,
    ).join(RfqResponse, RfqResponse.response_id == RfqContactPayload.response_id)
    .join(RfqRequest, RfqRequest.rfq_id == RfqResponse.rfq_id)
    .outerjoin(RfqIntroduction, RfqIntroduction.response_id == RfqResponse.response_id)
    .where(RfqContactPayload.key_id != keys.current)
    .order_by(RfqContactPayload.expires_at, RfqContactPayload.response_id, RfqContactPayload.purpose)
    .limit(batch_size).with_for_update(of=RfqContactPayload)).all()
    for row, response, request, introduction_id in rows:
        binding = contact_binding(
            authority, request, response, row.purpose, row.expires_at,
            introduction_id=introduction_id if row.purpose != PENDING_CONTACT else None,
        )
        contact = keys.decrypt(
            EncryptedContact(row.format_version, row.key_id, row.nonce, row.ciphertext), binding,
        )
        encrypted = keys.encrypt(contact, binding)
        row.format_version = encrypted.format_version
        row.key_id = encrypted.key_id
        row.nonce = encrypted.nonce
        row.ciphertext = encrypted.ciphertext
    return len(rows)
