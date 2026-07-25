"""Contracts for compiling one durable fulfillment aggregate from a
domain adapter's pre-existing execution record during a schema cutover.

A backfill compiler is a pure function of one already-enumerated candidate:
it performs no I/O, holds no database session, and either returns a
``LegacyFulfillmentBackfillDraft`` or raises
``LegacyBackfillValidationError``. A migration owns everything the compiler
does not: SQL enumeration, whole-population validation-before-commit
ordering, existing-row conflict/equivalence comparison against already
persisted aggregates, and the single atomic write. Keeping compilation pure
lets every candidate shape be covered by fast, direct unit tests instead of
only through a live database engine.

See ``openspec/specs/fulfillment/spec.md#existing-lease-continuity-during-fulfillment-cutover``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol


class LegacyBackfillValidationError(Exception):
    """A historical candidate cannot be safely backfilled into a fulfillment aggregate.

    Raised for problems intrinsic to one candidate's own data (missing or
    conflicting identity, target, or provider configuration). Cross-candidate
    concerns such as duplicate identity or conflicting already-persisted rows
    are the enumerating migration's responsibility, not the compiler's.
    """


@dataclass(frozen=True)
class LegacyFulfillmentBackfillDraft:
    """Durable row content a cutover migration should persist for one candidate.

    Mirrors the settlement/provisioned-resource row shape a migration
    writes, without depending on any ORM or database type — a compiler
    produces this from historical coordinates alone.
    """

    capacity_reservation_id: str
    fulfillment_id: str
    state: str
    settlement_resource_id: str
    pool_id: str
    provider: str
    resource_attributes: dict[str, Any]
    provider_metadata: dict[str, Any]
    teardown_provider_metadata: dict[str, Any] | None
    prepared_teardown_operation: dict[str, Any] | None
    provisioned_resource_ref: str | None


class LegacyFulfillmentBackfillCompiler(Protocol):
    """Structural contract a domain adapter's backfill compiler satisfies.

    Each domain defines its own candidate input shape (its historical
    execution record's fields), so this protocol fixes only the compiler's
    output and error contract, not its parameter list.
    """

    def __call__(self, candidate: Any, *, fulfillment_id: str) -> LegacyFulfillmentBackfillDraft: ...
