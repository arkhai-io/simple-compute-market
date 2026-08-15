from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Literal, Protocol

MECHANISM = "fiat.stripe.v1"


@dataclass(frozen=True)
class CompositionSnapshot:
    authority_ready: bool
    production_manifest_digest: str


@dataclass(frozen=True)
class RuntimeSnapshot:
    wallet_free: bool
    runtime_ready: bool
    account_ready: bool


@dataclass(frozen=True)
class ListingSnapshot:
    listing_id: str
    publication_ref: str


@dataclass(frozen=True)
class NegotiationSnapshot:
    negotiation_id: str
    accepted_terms: dict[str, object]
    accepted_mechanism: str


@dataclass(frozen=True)
class BuyerAction:
    kind: str
    expires_at_unix: int
    url: str | None = field(default=None, repr=False)


@dataclass(frozen=True)
class MaterializationSnapshot:
    obligation_ref: str
    settlement_ref: str
    operation_ref: str
    action: BuyerAction | None
    amount: int
    currency: str
    expiration_unix: int
    destination_account_ref: str
    transfer_group: str
    source_relation: str
    accepted_negotiation_id: str
    accepted_funding_profile: str
    accepted_condition_hash: str
    funding_authorization_bound: bool


@dataclass(frozen=True)
class FulfillmentSnapshot:
    capacity_reservation_ref: str
    fulfillment_ref: str
    condition_anchor: str
    condition_decision: Literal["satisfied", "unsatisfied"]


@dataclass(frozen=True)
class TerminalSnapshot:
    operation_ref: str
    marketplace_status: str
    authority_status: str
    effect_kind: Literal["transfer", "refund"]


class MarketplacePort(Protocol):
    def verify_composition(self) -> CompositionSnapshot: ...

    def verify_runtime(self) -> RuntimeSnapshot: ...

    def ensure_payer_profile_fixture(
        self,
        funding_profile: str,
        interaction: str,
    ) -> dict[str, object]: ...

    def complete_payer_setup(self) -> dict[str, object]: ...


    def create_and_publish_listing(self) -> ListingSnapshot: ...

    def discover_listing(self, listing_id: str) -> str: ...

    def negotiate(self, registry_listing_id: str) -> NegotiationSnapshot: ...

    def materialize(self, negotiation_id: str) -> MaterializationSnapshot: ...

    def observe_pending_funding(self, settlement_ref: str) -> dict[str, object]: ...


    def wait_funded(self, settlement_ref: str) -> bool: ...

    def complete_vm_fulfillment(self, settlement_ref: str) -> FulfillmentSnapshot: ...

    def wait_terminal(self, settlement_ref: str) -> TerminalSnapshot: ...

    def reclaim(self, settlement_ref: str) -> TerminalSnapshot: ...


def stable_operation_ref(prefix: str, *parts: str) -> str:
    """Derive one durable marketplace operation identity from accepted resources."""

    if not prefix or not parts or any(not part for part in parts):
        raise ValueError("stable operation references require a prefix and non-empty parts")
    digest = hashlib.sha256("\x00".join(parts).encode()).hexdigest()
    return f"{prefix}_{digest[:40]}"
