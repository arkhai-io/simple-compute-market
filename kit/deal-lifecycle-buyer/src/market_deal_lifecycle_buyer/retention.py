"""Pruning requires a fresh, complete observation of every retention boundary."""

from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field

from market_deal_lifecycle.terms import Adjudication

from market_deal_lifecycle_buyer.store import FileEvidenceStore


@dataclass(frozen=True)
class RetentionObservation:
    adjudication: Adjudication | None = None
    has_adapter: bool = False
    committed: bool | None = None
    acceptance_expires_at: int | None = None
    delivery_ended_at: int | None = None
    physical_recovered_at: int | None = None
    # Completeness means the reader enumerated all parts/cases, not just a page.
    parts_complete: bool = False
    cases_complete: bool = False
    payouts: Mapping[str, int | None] = field(default_factory=dict)
    case_closes: Mapping[str, int | None] = field(default_factory=dict)

    def boundary(self, *, known_commitments: bool) -> int | None:
        if self.adjudication is None or not self.has_adapter:
            return None
        window = self.adjudication.dispute_window_seconds
        if self.committed is False and not known_commitments:
            if self.acceptance_expires_at is None:
                return None
            instants = [self.acceptance_expires_at]
        elif self.committed is True:
            if (self.delivery_ended_at is None or self.physical_recovered_at is None
                    or not self.parts_complete or not self.cases_complete or not self.payouts
                    or any(at is None for at in self.payouts.values())
                    or any(at is None for at in self.case_closes.values())):
                return None
            instants = [self.delivery_ended_at, self.physical_recovered_at,
                        *(at for at in self.payouts.values() if at is not None),
                        *(at for at in self.case_closes.values() if at is not None)]
        else:
            return None
        if any(type(at) is not int or at < 0 for at in instants):
            return None
        return max(instants) + window


DealReader = Callable[[str], Awaitable[RetentionObservation]]


@dataclass(frozen=True)
class PruneReport:
    deleted: tuple[str, ...]
    kept: Mapping[str, str]


async def prune_command(store: FileEvidenceStore, reader: DealReader, *, now: int) -> PruneReport:
    """Read every deal first; unavailable or incomplete authority views keep evidence."""
    deleted = []
    kept = {}
    for negotiation_id in await store.negotiations():
        record = await store.read(negotiation_id)
        try:
            observed = await reader(negotiation_id)
        except Exception:
            kept[negotiation_id] = "read_unavailable"
            continue
        boundary = observed.boundary(known_commitments=bool(record.commitments))
        if boundary is None:
            kept[negotiation_id] = "retention_unresolved"
        elif now < boundary:
            kept[negotiation_id] = "within_window"
        elif await store.delete_if_unchanged(record):
            deleted.append(negotiation_id)
        else:
            kept[negotiation_id] = "evidence_changed"
    return PruneReport(tuple(deleted), kept)
