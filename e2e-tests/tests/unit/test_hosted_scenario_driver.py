from __future__ import annotations

from dataclasses import replace

import pytest

from tests.e2e.roles.scenarios.vms.hosted.control import SanitizedEffect, stable_operation_ref
from tests.e2e.roles.scenarios.vms.hosted.driver import (
    BuyerAction,
    CompositionSnapshot,
    FulfillmentSnapshot,
    FundingResult,
    HostedScenarioDriver,
    ListingSnapshot,
    MaterializationSnapshot,
    NegotiationSnapshot,
    RuntimeSnapshot,
    TerminalSnapshot,
)
from tests.e2e.roles.scenarios.vms.hosted.state import DealState


class Marketplace:
    condition_decision = "satisfied"

    def verify_composition(self):
        return CompositionSnapshot(
            authority_ready=True,
            simulator_ready=True,
            control_protocol="arkhai.hosted-settlement-e2e-control.v1",
            production_manifest_digest="sha256:production",
            e2e_manifest_digest="sha256:e2e",
        )

    def verify_runtime(self):
        return RuntimeSnapshot(wallet_free=True, runtime_ready=True, account_ready=True)

    def create_and_publish_listing(self):
        return ListingSnapshot("listing_ref", "publication_ref")

    def discover_listing(self, listing_id):
        return listing_id

    def negotiate(self, registry_listing_id):
        return NegotiationSnapshot(
            "negotiation_ref",
            {
                "mechanism": "fiat.stripe.v1",
                "amount": 2000,
                "currency": "usd",
            },
            "fiat.stripe.v1",
        )

    def materialize(self, negotiation_id):
        return MaterializationSnapshot(
            obligation_ref="obligation_ref",
            settlement_ref="settlement_ref",
            operation_ref=stable_operation_ref("materialize", "obligation_ref"),
            action=BuyerAction(
                kind="redirect",
                expires_at_unix=2000,
                url="http://simulator/checkout/checkout_ref",
            ),
            amount=2000,
            currency="usd",
            destination_fixture="fixture-account",
            transfer_group="settlement_ref",
            source_relation="source-charge",
        )

    def complete_vm_fulfillment(self, settlement_ref):
        return FulfillmentSnapshot(
            capacity_reservation_ref="capacity_ref",
            fulfillment_ref="fulfillment_ref",
            condition_anchor="condition_anchor",
            condition_decision=self.condition_decision,
        )

    def wait_terminal(self, settlement_ref):
        return TerminalSnapshot(
            operation_ref=stable_operation_ref("collect", settlement_ref),
            marketplace_status="collected",
            authority_status="collected",
            effect_kind="transfer",
        )

    def reclaim(self, settlement_ref):
        return TerminalSnapshot(
            operation_ref=stable_operation_ref("reclaim", settlement_ref),
            marketplace_status="reclaimed",
            authority_status="reclaimed",
            effect_kind="refund",
        )


class Funding:
    action = None

    def fund(self, action, *, operation_ref):
        self.action = action
        return FundingResult(funded=True)


class Effects:
    def inspect_effects(self, *, operation_ref, request_id):
        kind = "refund" if operation_ref.startswith("reclaim_") else "transfer"
        return (
            SanitizedEffect(
                operation_ref=operation_ref,
                resource_ref="settlement_ref",
                kind=kind,
                state="paid" if kind == "transfer" else "succeeded",
                amount=2000,
                currency="usd",
                destination_fixture=("fixture-account" if kind == "transfer" else None),
                transfer_group=("settlement_ref" if kind == "transfer" else None),
                source_relation="source-charge",
                attempts=2,
            ),
        )


class Clock:
    advanced = None

    def advance_clock(self, *, request_id, seconds=None, now_unix=None):
        self.advanced = (seconds, now_unix)


def _driver(marketplace=None):
    market = marketplace or Marketplace()
    funding = Funding()
    clock = Clock()
    return (
        HostedScenarioDriver(
            marketplace=market,
            funding=funding,
            effects=Effects(),
            clock=clock,
        ),
        funding,
        clock,
    )


def test_collection_exercises_public_surfaces_and_reports_only_sanitized_identity() -> None:
    driver, funding, _clock = _driver()
    state = DealState()
    report = driver.run_collection(state)
    assert report.mechanism == "fiat.stripe.v1"
    assert report.operation_ref == stable_operation_ref("collect", "settlement_ref")
    assert report.amount == 2000
    assert report.destination_fixture == "fixture-account"
    assert report.source_relation == "source-charge"
    assert funding.action is not None
    assert "checkout" not in report.__dict__
    assert "url" not in report.__dict__
    assert "provider" not in report.__dict__
    assert funding.action.url not in tuple(state.__dict__.values())


def test_reclaim_advances_only_controlled_clock_and_has_no_transfer() -> None:
    marketplace = Marketplace()
    marketplace.condition_decision = "unsatisfied"
    driver, _funding, clock = _driver(marketplace)
    report = driver.run_expiry_reclaim(DealState(), advance_seconds=3601)
    assert clock.advanced == (3601, None)
    assert report.effect_kind == "refund"


def test_collection_rejects_false_condition() -> None:
    marketplace = Marketplace()
    marketplace.condition_decision = "unsatisfied"
    driver, _funding, _clock = _driver(marketplace)
    with pytest.raises(AssertionError, match="collection cannot proceed"):
        driver.run_collection(DealState())


def test_runtime_must_prove_wallet_chain_rpc_eas_absence() -> None:
    class NotWalletFree(Marketplace):
        def verify_runtime(self):
            return RuntimeSnapshot(wallet_free=False, runtime_ready=True, account_ready=True)

    driver, _funding, _clock = _driver(NotWalletFree())
    with pytest.raises(AssertionError, match="wallet/chain"):
        driver.run_collection(DealState())


def test_effect_mismatch_is_attributed_to_sanitized_inspection_boundary() -> None:
    class WrongEffects(Effects):
        def inspect_effects(self, *, operation_ref, request_id):
            value = super().inspect_effects(
                operation_ref=operation_ref,
                request_id=request_id,
            )[0]
            return (replace(value, amount=1999),)

    driver = HostedScenarioDriver(
        marketplace=Marketplace(),
        funding=Funding(),
        effects=WrongEffects(),
        clock=Clock(),
    )
    with pytest.raises(AssertionError, match="wrong amount"):
        driver.run_collection(DealState())
