from __future__ import annotations

from dataclasses import dataclass, fields
from typing import Any


class HostedStagePrerequisiteError(RuntimeError):
    """A staged protected scenario was invoked before its public inputs existed."""


@dataclass
class DealState:
    """Public marketplace/authority state for one protected Stripe test scenario."""

    authority_ready: bool = False
    production_manifest_digest: str | None = None
    wallet_free: bool = False
    runtime_ready: bool = False
    account_ready: bool = False
    listing_id: str | None = None
    publication_ref: str | None = None
    registry_listing_id: str | None = None
    negotiation_id: str | None = None
    accepted_terms_hash: str | None = None
    accepted_mechanism: str | None = None
    obligation_ref: str | None = None
    settlement_ref: str | None = None
    materialize_operation_ref: str | None = None
    buyer_action_kind: str | None = None
    buyer_action_expires_at_unix: int | None = None
    amount: int | None = None
    currency: str | None = None
    destination_account_ref: str | None = None
    transfer_group: str | None = None
    source_relation: str | None = None
    funded: bool = False
    capacity_reservation_ref: str | None = None
    fulfillment_ref: str | None = None
    condition_anchor: str | None = None
    portable_condition_projected: bool = False
    condition_decision: str | None = None
    effect_operation_ref: str | None = None
    marketplace_status: str | None = None
    authority_status: str | None = None
    effect_kind: str | None = None
    effect_count: int | None = None


def state_fields() -> tuple[str, ...]:
    return tuple(item.name for item in fields(DealState))


def require_state(deal_state: DealState, *required: str) -> None:
    """Require exact declared fields without converting failure to a skip."""

    known = frozenset(state_fields())
    unknown = tuple(name for name in required if name not in known)
    if unknown:
        raise AttributeError("unknown hosted DealState field(s): " + ", ".join(sorted(unknown)))
    missing: list[str] = []
    for name in required:
        value: Any = getattr(deal_state, name)
        if value is None or value is False or value == "" or value == () or value == []:
            missing.append(name)
    if missing:
        rendered = ", ".join(f"DealState.{name}={getattr(deal_state, name)!r}" for name in missing)
        raise HostedStagePrerequisiteError(
            f"hosted scenario prerequisite not satisfied: {rendered}"
        )
