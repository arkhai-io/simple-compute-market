from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Literal, Protocol

from .control import SanitizedEffect, stable_operation_ref
from .state import DealState, require_state, state_fields

MECHANISM = "fiat.stripe.v1"


@dataclass(frozen=True)
class StageContract:
    name: str
    requires: tuple[str, ...]
    produces: tuple[str, ...]


STAGE_CONTRACTS = (
    StageContract(
        "composition",
        (),
        (
            "authority_ready",
            "simulator_ready",
            "control_protocol",
            "production_manifest_digest",
            "e2e_manifest_digest",
        ),
    ),
    StageContract(
        "runtime",
        (
            "authority_ready",
            "simulator_ready",
            "control_protocol",
            "production_manifest_digest",
            "e2e_manifest_digest",
        ),
        ("wallet_free", "runtime_ready", "account_ready"),
    ),
    StageContract(
        "listing",
        ("wallet_free", "runtime_ready", "account_ready"),
        ("listing_id", "publication_ref"),
    ),
    StageContract(
        "discovery",
        ("listing_id", "publication_ref"),
        ("registry_listing_id",),
    ),
    StageContract(
        "negotiation",
        ("registry_listing_id",),
        ("negotiation_id", "accepted_terms_hash", "accepted_mechanism"),
    ),
    StageContract(
        "materialization",
        ("negotiation_id", "accepted_terms_hash", "accepted_mechanism", "account_ready"),
        (
            "obligation_ref",
            "settlement_ref",
            "materialize_operation_ref",
            "buyer_action_kind",
            "buyer_action_expires_at_unix",
            "amount",
            "currency",
            "destination_fixture",
            "transfer_group",
            "source_relation",
        ),
    ),
    StageContract(
        "funding",
        (
            "settlement_ref",
            "materialize_operation_ref",
            "buyer_action_kind",
            "buyer_action_expires_at_unix",
        ),
        ("funded",),
    ),
    StageContract(
        "fulfillment",
        ("listing_id", "settlement_ref", "funded"),
        (
            "capacity_reservation_ref",
            "fulfillment_ref",
            "condition_anchor",
            "portable_condition_projected",
            "condition_decision",
        ),
    ),
    StageContract(
        "terminal",
        (
            "settlement_ref",
            "funded",
            "fulfillment_ref",
            "condition_anchor",
            "portable_condition_projected",
            "condition_decision",
            "amount",
            "currency",
            "destination_fixture",
            "transfer_group",
            "source_relation",
        ),
        (
            "effect_operation_ref",
            "marketplace_status",
            "authority_status",
            "effect_kind",
            "effect_count",
        ),
    ),
    StageContract("report", state_fields(), ()),
)


@dataclass(frozen=True)
class CompositionSnapshot:
    authority_ready: bool
    simulator_ready: bool
    control_protocol: str
    production_manifest_digest: str
    e2e_manifest_digest: str


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
    url: str = field(repr=False)


@dataclass(frozen=True)
class MaterializationSnapshot:
    obligation_ref: str
    settlement_ref: str
    operation_ref: str
    action: BuyerAction
    amount: int
    currency: str
    destination_fixture: str
    transfer_group: str
    source_relation: str


@dataclass(frozen=True)
class FundingResult:
    funded: bool


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


@dataclass(frozen=True)
class HostedEvidenceReport:
    evidence: Literal["simulated", "external"]
    production_manifest_digest: str
    e2e_manifest_digest: str
    listing_id: str
    negotiation_id: str
    obligation_ref: str
    settlement_ref: str
    operation_ref: str
    mechanism: str
    marketplace_status: str
    authority_status: str
    effect_kind: str
    amount: int
    currency: str
    destination_fixture: str
    transfer_group: str
    source_relation: str


class MarketplacePort(Protocol):
    def verify_composition(self) -> CompositionSnapshot: ...

    def verify_runtime(self) -> RuntimeSnapshot: ...

    def create_and_publish_listing(self) -> ListingSnapshot: ...

    def discover_listing(self, listing_id: str) -> str: ...

    def negotiate(self, registry_listing_id: str) -> NegotiationSnapshot: ...

    def materialize(self, negotiation_id: str) -> MaterializationSnapshot: ...

    def complete_vm_fulfillment(self, settlement_ref: str) -> FulfillmentSnapshot: ...

    def wait_terminal(self, settlement_ref: str) -> TerminalSnapshot: ...

    def reclaim(self, settlement_ref: str) -> TerminalSnapshot: ...


class ControlledClock(Protocol):
    def advance_clock(
        self,
        *,
        request_id: str,
        seconds: int | None = None,
        now_unix: int | None = None,
    ) -> object: ...


class FundingDriver(Protocol):
    def fund(self, action: BuyerAction, *, operation_ref: str) -> FundingResult: ...


class EffectInspector(Protocol):
    def inspect_effects(
        self, *, operation_ref: str, request_id: str
    ) -> tuple[SanitizedEffect, ...]: ...


class HostedScenarioDriver:
    """Provider-neutral staged VM lifecycle over public marketplace ports."""

    def __init__(
        self,
        *,
        marketplace: MarketplacePort,
        funding: FundingDriver,
        effects: EffectInspector,
        clock: ControlledClock | None = None,
    ) -> None:
        self.marketplace = marketplace
        self.funding = funding
        self.effects = effects
        self.clock = clock

    def verify_composition(self, state: DealState) -> None:
        snapshot = self.marketplace.verify_composition()
        if not snapshot.authority_ready or not snapshot.simulator_ready:
            raise AssertionError("hosted authority/simulator composition is not ready")
        if snapshot.control_protocol != "arkhai.hosted-settlement-e2e-control.v1":
            raise AssertionError("hosted private control protocol does not match the release")
        state.authority_ready = snapshot.authority_ready
        state.simulator_ready = snapshot.simulator_ready
        state.control_protocol = snapshot.control_protocol
        state.production_manifest_digest = snapshot.production_manifest_digest
        state.e2e_manifest_digest = snapshot.e2e_manifest_digest

    def verify_runtime(self, state: DealState) -> None:
        require_state(state, *STAGE_CONTRACTS[1].requires)
        snapshot = self.marketplace.verify_runtime()
        if not snapshot.wallet_free:
            raise AssertionError("default hosted runtime constructed wallet/chain infrastructure")
        if not snapshot.runtime_ready or not snapshot.account_ready:
            raise AssertionError("hosted settlement runtime/account is not ready")
        state.wallet_free = True
        state.runtime_ready = True
        state.account_ready = True

    def publish_listing(self, state: DealState) -> None:
        require_state(state, *STAGE_CONTRACTS[2].requires)
        snapshot = self.marketplace.create_and_publish_listing()
        state.listing_id = snapshot.listing_id
        state.publication_ref = snapshot.publication_ref

    def discover(self, state: DealState) -> None:
        require_state(state, *STAGE_CONTRACTS[3].requires)
        registry_listing_id = self.marketplace.discover_listing(state.listing_id or "")
        if registry_listing_id != state.listing_id:
            raise AssertionError("registry discovery returned the wrong hosted listing")
        state.registry_listing_id = registry_listing_id

    def negotiate(self, state: DealState) -> None:
        require_state(state, *STAGE_CONTRACTS[4].requires)
        snapshot = self.marketplace.negotiate(state.registry_listing_id or "")
        if snapshot.accepted_mechanism != MECHANISM:
            raise AssertionError("negotiation did not pin fiat.stripe.v1")
        terms = json.dumps(snapshot.accepted_terms, separators=(",", ":"), sort_keys=True)
        state.negotiation_id = snapshot.negotiation_id
        state.accepted_terms_hash = hashlib.sha256(terms.encode()).hexdigest()
        state.accepted_mechanism = snapshot.accepted_mechanism

    def materialize(self, state: DealState) -> BuyerAction:
        require_state(state, *STAGE_CONTRACTS[5].requires)
        snapshot = self.marketplace.materialize(state.negotiation_id or "")
        if snapshot.action.kind != "redirect":
            raise AssertionError("hosted materialization returned a non-redirect action")
        if snapshot.amount <= 0 or len(snapshot.currency) != 3:
            raise AssertionError("hosted materialization returned invalid financial terms")
        state.obligation_ref = snapshot.obligation_ref
        state.settlement_ref = snapshot.settlement_ref
        state.materialize_operation_ref = snapshot.operation_ref
        state.buyer_action_kind = snapshot.action.kind
        state.buyer_action_expires_at_unix = snapshot.action.expires_at_unix
        state.amount = snapshot.amount
        state.currency = snapshot.currency
        state.destination_fixture = snapshot.destination_fixture
        state.transfer_group = snapshot.transfer_group
        state.source_relation = snapshot.source_relation
        return snapshot.action

    def fund(self, state: DealState, action: BuyerAction) -> None:
        require_state(state, *STAGE_CONTRACTS[6].requires)
        result = self.funding.fund(action, operation_ref=state.materialize_operation_ref or "")
        if not result.funded:
            raise AssertionError("hosted Checkout did not become authoritatively funded")
        state.funded = True

    def fulfill(self, state: DealState) -> None:
        require_state(state, *STAGE_CONTRACTS[7].requires)
        snapshot = self.marketplace.complete_vm_fulfillment(state.settlement_ref or "")
        if snapshot.condition_decision not in {"satisfied", "unsatisfied"}:
            raise AssertionError("portable condition projection returned an invalid decision")
        state.capacity_reservation_ref = snapshot.capacity_reservation_ref
        state.fulfillment_ref = snapshot.fulfillment_ref
        state.condition_anchor = snapshot.condition_anchor
        state.portable_condition_projected = True
        state.condition_decision = snapshot.condition_decision

    def observe_terminal(
        self, state: DealState, *, reclaim: bool = False
    ) -> tuple[SanitizedEffect, ...]:
        require_state(state, *STAGE_CONTRACTS[8].requires)
        snapshot = (
            self.marketplace.reclaim(state.settlement_ref or "")
            if reclaim
            else self.marketplace.wait_terminal(state.settlement_ref or "")
        )
        expected_kind = "refund" if reclaim else "transfer"
        expected_status = "reclaimed" if reclaim else "collected"
        if snapshot.effect_kind != expected_kind:
            raise AssertionError("authority reached the wrong terminal provider effect")
        if (
            snapshot.marketplace_status != expected_status
            or snapshot.authority_status != expected_status
        ):
            raise AssertionError("marketplace and authority terminal states did not converge")
        effects = self.effects.inspect_effects(
            operation_ref=snapshot.operation_ref,
            request_id=stable_operation_ref(
                f"request-inspect-{expected_kind}", snapshot.operation_ref
            ),
        )
        matching = tuple(effect for effect in effects if effect.kind == expected_kind)
        if len(matching) != 1:
            raise AssertionError(f"expected exactly one {expected_kind} effect")
        effect = matching[0]
        expected = {
            "amount": state.amount,
            "currency": state.currency,
            "destination_fixture": state.destination_fixture if not reclaim else None,
            "transfer_group": state.transfer_group if not reclaim else None,
            "source_relation": state.source_relation,
        }
        for name, value in expected.items():
            if value is not None and getattr(effect, name) != value:
                raise AssertionError(f"sanitized {expected_kind} effect has wrong {name}")
        other_kind = "transfer" if reclaim else "refund"
        if any(item.kind == other_kind for item in effects):
            raise AssertionError(f"terminal {expected_kind} operation also created a {other_kind}")
        state.effect_operation_ref = snapshot.operation_ref
        state.marketplace_status = snapshot.marketplace_status
        state.authority_status = snapshot.authority_status
        state.effect_kind = snapshot.effect_kind
        state.effect_count = 1
        return matching

    def run_collection(self, state: DealState) -> HostedEvidenceReport:
        self.verify_composition(state)
        self.verify_runtime(state)
        self.publish_listing(state)
        self.discover(state)
        self.negotiate(state)
        action = self.materialize(state)
        self.fund(state, action)
        self.fulfill(state)
        if state.condition_decision != "satisfied":
            raise AssertionError("collection cannot proceed with an unsatisfied condition")
        self.observe_terminal(state)
        return self.terminal_report(state)

    def run_expiry_reclaim(self, state: DealState, *, advance_seconds: int) -> HostedEvidenceReport:
        if self.clock is None:
            raise RuntimeError("expiry reclaim requires the simulator controlled clock")
        self.verify_composition(state)
        self.verify_runtime(state)
        self.publish_listing(state)
        self.discover(state)
        self.negotiate(state)
        action = self.materialize(state)
        self.fund(state, action)
        self.fulfill(state)
        if state.condition_decision != "unsatisfied":
            raise AssertionError("expiry reclaim requires a projected false condition")
        self.clock.advance_clock(
            seconds=advance_seconds,
            request_id=stable_operation_ref("request-advance-reclaim", state.settlement_ref or ""),
        )
        self.observe_terminal(state, reclaim=True)
        return self.terminal_report(state)

    def terminal_report(
        self,
        state: DealState,
        *,
        evidence: Literal["simulated", "external"] = "simulated",
    ) -> HostedEvidenceReport:
        require_state(state, *STAGE_CONTRACTS[-1].requires)
        return HostedEvidenceReport(
            evidence=evidence,
            production_manifest_digest=state.production_manifest_digest or "",
            e2e_manifest_digest=state.e2e_manifest_digest or "",
            listing_id=state.listing_id or "",
            negotiation_id=state.negotiation_id or "",
            obligation_ref=state.obligation_ref or "",
            settlement_ref=state.settlement_ref or "",
            operation_ref=state.effect_operation_ref or "",
            mechanism=state.accepted_mechanism or "",
            marketplace_status=state.marketplace_status or "",
            authority_status=state.authority_status or "",
            effect_kind=state.effect_kind or "",
            amount=state.amount or 0,
            currency=state.currency or "",
            destination_fixture=state.destination_fixture or "",
            transfer_group=state.transfer_group or "",
            source_relation=state.source_relation or "",
        )
