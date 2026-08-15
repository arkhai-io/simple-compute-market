"""Shared row shape and error type for one-time historical-data cutovers
into the fulfillment aggregate.

A domain adapter's cutover compiler is a pure function of one
already-enumerated candidate: it performs no I/O, holds no database
session, and either returns a ``LegacyFulfillmentBackfillDraft`` or raises
``LegacyBackfillValidationError``. The migration that calls it owns
everything the compiler does not: SQL enumeration, whole-population
validation-before-commit ordering, existing-row conflict/equivalence
comparison against already persisted aggregates, and the single atomic
write.

These two types live here, rather than in the migration or the domain
adapter, because ``LegacyFulfillmentBackfillDraft`` mirrors
``SettlementRecord``/``ProvisionedResource``'s own row shape, which is
defined in this package — not because a domain cutover compiler is a
general-purpose fulfillment extension point. A domain adapter and the
service that runs its migration both already depend on this package for
that reason.

See ``openspec/specs/fulfillment/spec.md#existing-lease-continuity-during-fulfillment-cutover``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


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
    executor_kind: str
    provider: str
    resource_attributes: dict[str, Any]
    provider_metadata: dict[str, Any]
    teardown_provider_metadata: dict[str, Any] | None
    prepared_teardown_operation: dict[str, Any] | None
    provisioned_resource_id: str | None
