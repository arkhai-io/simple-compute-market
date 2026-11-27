"""The stage's composition-time contributions and its refusals, over injected collaborators."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from arkhai_api_selling.issuance import SettlementRefusal
from arkhai_api_selling.settlement_composition import build_settlement_registry
from market_alkahest import ALKAHEST_MECHANISM_ID, RECIPIENT_RELEASE, ReleaseModelError
from market_core import SettlementStageTable

from arkhai_api_selling_alkahest.stage import AlkahestSellerStage
from tests.bundles import EXAMPLE, SELLER


def _stage(**collaborators) -> AlkahestSellerStage:
    defaults = {
        "fulfils_through_capacity": True,
        "release_models": frozenset({RECIPIENT_RELEASE}),
        "chains": lambda: {"anvil": SimpleNamespace(rpc_url="http://anvil.test")},
        "address_books": lambda: {"anvil": "/books/anvil.json"},
        "seller_wallet": lambda: "",
        "seller_wallet_key": lambda: "",
        "chain_probe": lambda: None,
        "composition": lambda: None,
        "sqlite_client": lambda: None,
        "backfill_escrows": AsyncMock(return_value=0),
        "stage_event": lambda *a, **k: None,
    }
    return AlkahestSellerStage(EXAMPLE, **{**defaults, **collaborators})


def _composition(clients=None):
    return SimpleNamespace(
        runtime=object(), local_principal=SELLER.identity,
        mechanism_resources={"clients": clients or {}},
    )


@pytest.mark.parametrize("enabled", [True, False])
def test_a_section_offering_a_release_model_the_stage_cannot_deliver_is_refused(enabled):
    """Enabled or not, since the section still services the deals accepted under it."""
    stage = _stage()
    registry = build_settlement_registry(SettlementStageTable({ALKAHEST_MECHANISM_ID: stage}))
    config = registry.resolve(
        {
            "schema_version": 1,
            "priority": [ALKAHEST_MECHANISM_ID] if enabled else [],
            "alkahest": {
                "enabled": enabled,
                "release_models": ["interruptible"],
                "interruptible_oracle_addresses": ["0x" + "cd" * 20],
            },
        },
        role="seller",
    )

    with pytest.raises(ReleaseModelError, match="cannot deliver"):
        stage.validate_configuration(config)


def test_a_deliverable_release_model_is_accepted():
    stage = _stage()
    registry = build_settlement_registry(SettlementStageTable({ALKAHEST_MECHANISM_ID: stage}))
    config = registry.resolve(
        {"schema_version": 1, "priority": [], "alkahest": {"enabled": False, "release_models": ["recipient"]}},
        role="seller",
    )

    stage.validate_configuration(config)
    assert stage.composition_resources()["deliverable_release_models"] == frozenset(
        {RECIPIENT_RELEASE}
    )


def test_health_names_the_chains_the_composition_holds_clients_for():
    composition = _composition({"base": object(), "anvil": object()})

    assert _stage().health_checks() == {"alkahest": "unconfigured"}
    assert _stage(composition=lambda: composition).health_checks() == {"alkahest": "anvil,base"}


async def test_the_startup_step_backfills_escrows_over_the_composed_runtime():
    backfill = AsyncMock(return_value=2)
    db = object()
    composition = _composition()
    stage = _stage(backfill_escrows=backfill, composition=lambda: composition, sqlite_client=lambda: db)

    (step,) = stage.startup_steps()
    await step()

    backfill.assert_awaited_once_with(
        sqlite_client=db, settlement_runtime=composition.runtime, local_principal=SELLER.identity
    )
    assert stage.contributed_loops() == ()


async def test_the_startup_step_waits_for_a_composition():
    backfill = AsyncMock()

    await _stage(backfill_escrows=backfill).backfill_escrow_records()

    backfill.assert_not_awaited()


def test_the_servicing_client_is_built_over_the_chains_address_books():
    built = {}
    stage = _stage(escrow_client=lambda **resources: built.update(resources) or "client")
    get_client = object()

    assert stage.client({
        "get_client": get_client, "default_chain": "anvil",
        "chains": {"anvil": SimpleNamespace(rpc_url="http://anvil.test")},
    }) == "client"
    assert built == {
        "get_client": get_client, "default_chain": "anvil",
        "chain_config_paths": {"anvil": "/books/anvil.json"},
    }
    assert stage.servicing(object()) is None


async def test_a_stage_without_seller_refunds_refuses_the_route_and_skips_the_action():
    stage = _stage()

    with pytest.raises(SettlementRefusal) as refused:
        await stage.refund(db=None, composition=None, negotiation_id="neg-escrow")
    assert refused.value.status_code == 409
    skipped = await stage.refund_before_delivery(db=None, composition=None, negotiation_id="neg-escrow")
    assert skipped == {"action": "refund", "status": "skipped", "reason": "refund_not_supported"}
