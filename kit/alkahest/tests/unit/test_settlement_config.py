from __future__ import annotations

from copy import deepcopy

import pytest
from market_alkahest import (
    ALKAHEST_CONFIG_KEY,
    ALKAHEST_MECHANISM_ID,
    AlkahestConditionalEscrowClient,
    AlkahestSettlementConfig,
    create_alkahest_registration,
)
from market_alkahest.settlement_config import alkahest_preflight
from pydantic import ValidationError


@pytest.mark.parametrize(
    "payload",
    [
        {"enabled": False, "wallet": {"private_key": "secret"}},
        {"enabled": False, "chains": {}},
        {"enabled": False, "trusted_oracle_addresses": ["0x" + "11" * 20]},
        {"enabled": False, "oracle_gated": True, "trusted_oracle_addresses": ["bad"]},
    ],
)
def test_alkahest_config_rejects_foreign_or_invalid_fields(payload: dict) -> None:
    with pytest.raises(ValidationError):
        AlkahestSettlementConfig.model_validate(payload)


@pytest.mark.asyncio
async def test_disabled_alkahest_preflight_does_not_touch_injected_resources() -> None:
    calls: list[str | None] = []
    resources = {"get_client": lambda chain: calls.append(chain)}

    status = await alkahest_preflight(AlkahestSettlementConfig(), resources, "seller")

    assert status.mechanism == ALKAHEST_MECHANISM_ID
    assert status.enabled is False
    assert status.ready is False
    assert status.blockers == ()
    assert calls == []


@pytest.mark.asyncio
async def test_enabled_alkahest_reports_sanitized_prerequisite_blockers() -> None:
    status = await alkahest_preflight(
        AlkahestSettlementConfig(enabled=True),
        {},
        "buyer",
    )

    assert status.ready is False
    assert {blocker.code for blocker in status.blockers} == {
        "alkahest.wallet_missing",
        "alkahest.chain_missing",
    }
    projection = status.model_dump_json()
    assert "private_key" not in projection
    assert "rpc_url" not in projection


@pytest.mark.asyncio
async def test_ready_alkahest_preflight_is_observational_and_public_only() -> None:
    def forbid_client_access(_chain):
        raise AssertionError("preflight must not call a transaction client")

    resources = {
        "wallet": {"address": "0x" + "11" * 20, "private_key": "never-report"},
        "chains": {
            "ethereum_sepolia": {
                "rpc_url": "https://private-rpc.example/key",
                "chain_id": 11155111,
            }
        },
        "chain_name": "ethereum_sepolia",
        "observed_chain_id": 11155111,
        "deployed_contracts": {"escrow": True, "arbiter": True},
        "get_client": forbid_client_access,
        "settlement_state": {"unchanged": True},
    }
    before = deepcopy(resources)

    status = await alkahest_preflight(
        AlkahestSettlementConfig(enabled=True),
        resources,
        "seller",
    )

    assert status.ready is True
    assert resources == before
    projection = status.model_dump_json()
    assert "never-report" not in projection
    assert "private-rpc" not in projection
    assert status.public_details == {
        "oracle_gated": False,
        "interruptible": False,
        "chain": "ethereum_sepolia",
    }


@pytest.mark.asyncio
async def test_alkahest_preflight_admits_all_listing_chains_without_default() -> None:
    resources = {
        "wallet": {"address": "0x" + "11" * 20},
        "chains": {
            "chain-a": {"rpc_url": "https://a.example", "chain_id": 1},
            "chain-b": {"rpc_url": "https://b.example", "chain_id": 2},
        },
        "accepted_escrows": [
            {"chain_name": "chain-b"},
            {"chain_name": "chain-a"},
            {"chain_name": "chain-b"},
        ],
        "observed_chain_id": {"chain-a": 1, "chain-b": 2},
    }

    status = await alkahest_preflight(
        AlkahestSettlementConfig(enabled=True),
        resources,
        "seller",
    )

    assert status.ready is True
    assert "chain" not in status.public_details


def test_alkahest_registration_has_exact_contract_and_factory() -> None:
    registration = create_alkahest_registration()
    assert registration.mechanism_id == ALKAHEST_MECHANISM_ID
    assert registration.config_key == ALKAHEST_CONFIG_KEY
    assert registration.roles == frozenset({"buyer", "seller"})

    clients = {"ethereum_sepolia": object()}
    client = registration.client_factory(
        AlkahestSettlementConfig(enabled=False),
        {"clients": clients, "chains": {"ethereum_sepolia": {}}, "chain_name": "ethereum_sepolia"},
        "buyer",
    )
    assert type(client) is AlkahestConditionalEscrowClient


@pytest.mark.asyncio
async def test_alkahest_option_builder_emits_canonical_buyer_choice() -> None:
    config = AlkahestSettlementConfig(enabled=True)
    resources = {
        "wallet": {"address": "0x" + "11" * 20},
        "chains": {"ethereum_sepolia": {"rpc_url": "https://rpc.example"}},
    }
    readiness = await alkahest_preflight(config, resources, "seller")
    registration = create_alkahest_registration()
    escrow = {
        "chain_name": "ethereum_sepolia",
        "escrow_address": "0x" + "22" * 20,
        "literal_fields": {"token": "0x" + "33" * 20},
        "rates": [{"field": "amount", "per": "hour", "value": "125"}],
    }

    publication = registration.option_builder(
        config,
        readiness,
        {"accepted_escrows": [escrow]},
        "seller",
    )

    assert publication["accepted_escrows"] == [escrow]
    option = publication["settlement_options"][0]
    assert option["mechanism"] == ALKAHEST_MECHANISM_ID
    assert len(option["option_id"]) == 64
    assert option["params"]["accepted_escrow"] == escrow
    assert registration.buyer_compatibility(
        config,
        option,
        {"chains": {"ethereum_sepolia"}},
    )
