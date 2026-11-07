"""Immutable site lease-end evidence, independent of payment and teardown state."""

import base64
from typing import Annotated, Literal

from market_identity import (
    Identity, SignatureProof, Signer, TrustedIdentitySet, canonical_json,
    frame_fields, get_identity_verifier,
)
from pydantic import Base64Bytes, BaseModel, ConfigDict, Field, model_validator

Instant = Annotated[int, Field(strict=True, ge=0)]
Reference = Annotated[str, Field(min_length=1)]


class LeaseEndedEvent(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    version: Literal[1] = 1
    kind: Literal["lease_ended"] = "lease_ended"
    event_id: Reference
    capacity_reservation_id: Reference
    site_id: Reference
    effective_at: Instant
    cause: Reference
    source_state: Reference
    reason: str | None = None
    caller: Identity | None = None
    claimed_deadline: Instant | None = None
    deadline_phase: str | None = None

    @model_validator(mode="after")
    def deadline_has_phase(self):
        if (self.claimed_deadline is None) != (self.deadline_phase is None):
            raise ValueError("a deadline and its phase must be reported together")
        return self


class SignedLeaseEndedReport(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    payload: Base64Bytes
    signer: Identity
    proof: SignatureProof


def _message(payload: bytes) -> bytes:
    return frame_fields(("arkhai.site.lease-ended.v1", payload.decode("utf-8")))


def sign_lease_end(event: LeaseEndedEvent, signer: Signer) -> SignedLeaseEndedReport:
    payload = canonical_json(event)
    return SignedLeaseEndedReport(
        payload=base64.b64encode(payload), signer=signer.identity,
        proof=SignatureProof.from_bytes(signer.identity.scheme, signer.sign(_message(payload))),
    )


def verify_lease_end(
    report: SignedLeaseEndedReport, *, capacity_reservation_id: str,
    site_id: str, expected_sites: TrustedIdentitySet,
) -> LeaseEndedEvent:
    """Verify original stored bytes and configured site/reservation binding."""
    if (
        not expected_sites.allows(report.signer) or report.proof.scheme != report.signer.scheme
        or not get_identity_verifier(report.signer.scheme).verify_signature(
            report.signer, _message(report.payload), report.proof.to_bytes(),
        )
    ):
        raise ValueError("lease-ended report site proof failed")
    event = LeaseEndedEvent.model_validate_json(report.payload)
    if event.capacity_reservation_id != capacity_reservation_id or event.site_id != site_id:
        raise ValueError("lease-ended report names another reservation or site")
    return event


LEASE_ENDED_CALLBACK = {
    "method": "POST",
    "path": "/api/v1/capacity/reservations/{capacity_reservation_id}/lease-ended",
    "operation": "lease_ended",
    "roles": ("service",),
}
