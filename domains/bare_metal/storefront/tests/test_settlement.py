from __future__ import annotations

import pytest

from arkhai_bare_metal_storefront import settlement
from arkhai_bare_metal_storefront.settlement import (
    BareMetalSettlementPlanError,
    build_bare_metal_settlement_plan,
)
from market_core.schemas import SettlementPlan


PROPOSAL = {
    "chain_name": "base",
    "escrow_address": "0x1111111111111111111111111111111111111111",
    "fields": {"amount": "100"},
}


def _artifacts():
    proposal = dict(PROPOSAL)
    return {
        "proposal": proposal,
        "accepted_escrow_proposal": proposal,
        "settlement_plan": {
            "obligations": [
                {
                    "payer": "buyer",
                    "claimant": "seller",
                    "amount": "100",
                    "asset": "0x2222222222222222222222222222222222222222",
                    "expiration_unix": 2_000_000_000,
                    "mechanism": "alkahest.v1",
                    "params": {"chain_name": "base"},
                },
            ],
            "service_terms": {},
        },
        "accepted_escrow_terms": [],
    }


def test_plan_builder_forwards_agreed_inputs_and_validates_plan(monkeypatch) -> None:
    calls = []

    def fake_builder(**kwargs):
        calls.append(kwargs)
        return _artifacts()

    monkeypatch.setattr(
        settlement,
        "accepted_escrow_artifacts_from_proposal",
        fake_builder,
    )

    result = build_bare_metal_settlement_plan(
        proposal=PROPOSAL,
        agreed_amount=100,
        duration_seconds=3600,
        seller_wallet_address="0xseller",
        chain_config_paths={"base": "/config/base.json"},
    )

    plan = SettlementPlan.model_validate(result["settlement_plan"])
    assert plan.obligations[0].mechanism == "alkahest.v1"
    assert plan.obligations[0].amount == 100
    assert plan.service_terms == {}
    assert calls == [
        {
            "proposal": PROPOSAL,
            "agreed_amount": 100,
            "duration_seconds": 3600,
            "uses_scalar_amount": True,
            "seller_wallet_address": "0xseller",
            "chain_config_paths": {"base": "/config/base.json"},
            "heartbeat_interval_seconds": None,
        },
    ]


def test_plan_builder_is_deterministic(monkeypatch) -> None:
    monkeypatch.setattr(
        settlement,
        "accepted_escrow_artifacts_from_proposal",
        lambda **_kwargs: _artifacts(),
    )

    first = build_bare_metal_settlement_plan(
        proposal=PROPOSAL,
        agreed_amount=100,
        duration_seconds=3600,
    )
    second = build_bare_metal_settlement_plan(
        proposal=PROPOSAL,
        agreed_amount=100,
        duration_seconds=3600,
    )

    assert first == second


def test_plan_builder_returns_empty_without_proposal() -> None:
    assert (
        build_bare_metal_settlement_plan(
            proposal=None,
            agreed_amount=0,
            duration_seconds=3600,
        )
        == {}
    )


def test_plan_builder_rejects_invalid_duration_before_materialization(
    monkeypatch,
) -> None:
    def fail_if_called(**_kwargs):
        raise AssertionError("mechanism builder must not run")

    monkeypatch.setattr(
        settlement,
        "accepted_escrow_artifacts_from_proposal",
        fail_if_called,
    )

    with pytest.raises(BareMetalSettlementPlanError, match="positive"):
        build_bare_metal_settlement_plan(
            proposal=PROPOSAL,
            agreed_amount=100,
            duration_seconds=0,
        )


@pytest.mark.parametrize(
    "artifacts",
    [
        {"accepted_escrow_terms_error": "unknown mechanism"},
        {"proposal": PROPOSAL},
        {"settlement_plan": {"obligations": [{"mechanism": "alkahest.v1"}]}},
    ],
)
def test_plan_builder_fails_closed_on_invalid_materialization(
    monkeypatch,
    artifacts,
) -> None:
    monkeypatch.setattr(
        settlement,
        "accepted_escrow_artifacts_from_proposal",
        lambda **_kwargs: artifacts,
    )

    with pytest.raises(BareMetalSettlementPlanError):
        build_bare_metal_settlement_plan(
            proposal=PROPOSAL,
            agreed_amount=100,
            duration_seconds=3600,
        )
