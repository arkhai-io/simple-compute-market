"""Evidence storage is keyed before commitment and preserves exact signed bytes."""

from typing import Protocol

from market_deal_lifecycle_contracts.models import EvidenceItem, Instant, Reference, WireModel


class CommitmentAttempt(WireModel):
    commitment_ref: Reference
    superseded: bool = False


class EvidenceRecord(WireModel):
    negotiation_id: Reference
    commitments: list[CommitmentAttempt]
    items: list[EvidenceItem]
    acceptance_expires_at: Instant | None = None


class EvidenceStore(Protocol):
    async def put(self, negotiation_id: str, item: EvidenceItem) -> None:
        """Idempotent by evidence ID; refuse changed bytes, retain insertion order."""
        ...

    async def record_commitment(self, negotiation_id: str, attempt: CommitmentAttempt) -> None:
        """At most one live commitment; keep superseded attempts with their own references."""
        ...

    async def read(self, negotiation_id: str) -> EvidenceRecord: ...
    async def negotiations(self) -> tuple[str, ...]: ...
    async def delete(self, negotiation_id: str) -> None:
        """Only after the owning role has established its complete retention boundary."""
        ...
