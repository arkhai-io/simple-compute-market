"""Heartbeat-gated plan shape: published demands + plan service terms."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

from market_alkahest.alkahest import (
    get_erc20_splitter,
    get_recipient_arbiter,
    get_trusted_oracle_arbiter,
)

WALLET = "0x" + "ab" * 20
ORACLE = "0x" + "cd" * 20
ESCROW = "0x" + "11" * 20
TOKEN = "0x" + "aa" * 20
SPLITTER = "0x" + "44" * 20

CHAINS = {
    "base_sepolia": SimpleNamespace(
        name="base_sepolia", alkahest_address_config_path=None
    ),
}


def _settings(**overrides):
    base = {
        "oracle_gated_listings": False,
        "trusted_oracle_address": "",
        "interruptible_listings": False,
        "interruptible_oracle_address": "",
    }
    base.update(overrides)
    return SimpleNamespace(**base)


def _chains(config_path):
    return {
        "base_sepolia": SimpleNamespace(
            name="base_sepolia", alkahest_address_config_path=str(config_path)
        )
    }


def test_default_posture_publishes_recipient_demands():
    from market_storefront.cli_publish import _demands_for_chains

    with patch("market_storefront.utils.config.settings", _settings()):
        demands = _demands_for_chains(CHAINS, {"base_sepolia"}, WALLET)
    assert len(demands) == 1
    assert demands[0]["arbiter"] == get_recipient_arbiter("base_sepolia").lower()
    assert demands[0]["demand_data"] == {"recipient": WALLET.lower()}


def test_gated_posture_publishes_third_party_oracle_demands():
    from market_storefront.cli_publish import _demands_for_chains

    with patch(
        "market_storefront.utils.config.settings",
        _settings(oracle_gated_listings=True, trusted_oracle_address=ORACLE),
    ):
        demands = _demands_for_chains(CHAINS, {"base_sepolia"}, WALLET)
    assert demands[0]["arbiter"] == get_trusted_oracle_arbiter("base_sepolia").lower()
    assert demands[0]["demand_data"] == {"oracle": ORACLE.lower(), "data": "0x"}


def test_gated_posture_requires_an_oracle():
    import pytest

    from market_storefront.cli_publish import _demands_for_chains

    with patch(
        "market_storefront.utils.config.settings",
        _settings(oracle_gated_listings=True),
    ):
        with pytest.raises(ValueError, match="trusted_oracle_address"):
            _demands_for_chains(CHAINS, {"base_sepolia"}, WALLET)


def test_gated_posture_rejects_self_oracle():
    """The party collecting cannot also be the party deciding collection."""
    import pytest

    from market_storefront.cli_publish import _demands_for_chains

    with patch(
        "market_storefront.utils.config.settings",
        _settings(oracle_gated_listings=True, trusted_oracle_address=WALLET),
    ):
        with pytest.raises(ValueError, match="self-oracle|gates nothing"):
            _demands_for_chains(CHAINS, {"base_sepolia"}, WALLET)


def test_interruptible_posture_publishes_splitter_demands(tmp_path):
    import json

    from market_alkahest.alkahest import _load_override_config_cached
    from market_storefront.cli_publish import _demands_for_chains

    override = {"arbiters_addresses": {"erc20_splitter": SPLITTER}}
    path = tmp_path / "alkahest_override.json"
    path.write_text(json.dumps(override), encoding="utf-8")
    _load_override_config_cached.cache_clear()
    with patch(
        "market_storefront.utils.config.settings",
        _settings(interruptible_listings=True),
    ):
        demands = _demands_for_chains(_chains(path), {"base_sepolia"}, WALLET)
    assert demands[0]["arbiter"] == get_erc20_splitter(
        "base_sepolia", config_path=str(path)
    ).lower()
    assert demands[0]["demand_data"] == {"oracle": WALLET.lower(), "data": "0x"}


def test_interruptible_posture_allows_explicit_refund_authority(tmp_path):
    import json

    from market_alkahest.alkahest import _load_override_config_cached
    from market_storefront.cli_publish import _demands_for_chains

    override = {"arbiters_addresses": {"erc20_splitter": SPLITTER}}
    path = tmp_path / "alkahest_override.json"
    path.write_text(json.dumps(override), encoding="utf-8")
    _load_override_config_cached.cache_clear()
    with patch(
        "market_storefront.utils.config.settings",
        _settings(
            interruptible_listings=True,
            interruptible_oracle_address=ORACLE,
        ),
    ):
        demands = _demands_for_chains(_chains(path), {"base_sepolia"}, WALLET)
    assert demands[0]["demand_data"] == {"oracle": ORACLE.lower(), "data": "0x"}


def test_interruptible_and_oracle_gated_are_mutually_exclusive():
    import pytest

    from market_storefront.cli_publish import _demands_for_chains

    with patch(
        "market_storefront.utils.config.settings",
        _settings(
            oracle_gated_listings=True,
            trusted_oracle_address=ORACLE,
            interruptible_listings=True,
        ),
    ):
        with pytest.raises(ValueError, match="mutually exclusive"):
            _demands_for_chains(CHAINS, {"base_sepolia"}, WALLET)


def test_interruptible_offer_resource_is_marked():
    from market_storefront.cli_publish import _offer_resource_for_listing

    resource = {
        "pool_id": "pool-a",
        "resource_id": "machine-a",
        "gpu_model": "A100",
        "gpu_count": 1,
        "sla": "best_effort",
        "region": "iad",
    }
    with patch(
        "market_storefront.utils.config.settings",
        _settings(interruptible_listings=True),
    ):
        offer = _offer_resource_for_listing(resource)
    assert offer["interruptible"] is True
    assert offer["settlement_model"] == "splitter_refund"


def _artifacts(demands, heartbeat_interval=60, chain_config_paths=None):
    from domains.vms.settlement.proposals import (
        accepted_escrow_artifacts_from_proposal,
    )

    proposal = {
        "chain_name": "base_sepolia",
        "escrow_address": ESCROW,
        "fields": {"token": TOKEN},
        "literal_fields": {"token": TOKEN},
        "rates": [],
        "demands": demands,
        "expiration_unix": 1_800_000_000,
    }
    return accepted_escrow_artifacts_from_proposal(
        proposal=proposal,
        agreed_amount=5_000_000,
        duration_seconds=3600,
        seller_wallet_address=WALLET,
        chain_config_paths=chain_config_paths,
        heartbeat_interval_seconds=heartbeat_interval,
    )


def test_oracle_gated_plan_carries_heartbeat_service_terms():
    demands = [{
        "chain_name": "base_sepolia",
        "arbiter": get_trusted_oracle_arbiter("base_sepolia"),
        "demand_data": {"oracle": WALLET.lower(), "data": "0x"},
    }]
    out = _artifacts(demands)
    plan = out["settlement_plan"]
    assert plan["service_terms"]["heartbeat"] == {
        "schema": "vms.heartbeat.v1",
        "interval_seconds": 60,
    }
    # The materialized demand routes through the trusted-oracle codec.
    ob = plan["obligations"][0]
    assert ob["params"]["obligation_data"]["arbiter"] == (
        get_trusted_oracle_arbiter("base_sepolia")
    )


def test_recipient_gated_plan_has_no_heartbeat_terms():
    demands = [{
        "chain_name": "base_sepolia",
        "arbiter": get_recipient_arbiter("base_sepolia"),
        "demand_data": {"recipient": WALLET.lower()},
    }]
    out = _artifacts(demands)
    assert out["settlement_plan"]["service_terms"] == {}


def test_splitter_plan_carries_interruptible_service_terms(tmp_path):
    import json

    from market_alkahest.alkahest import _load_override_config_cached

    override = {
        "arbiters_addresses": {"erc20_splitter": SPLITTER},
        "erc20_addresses": {
            "escrow_obligation_default": ESCROW,
        },
    }
    path = tmp_path / "alkahest_override.json"
    path.write_text(json.dumps(override), encoding="utf-8")
    _load_override_config_cached.cache_clear()
    demands = [{
        "chain_name": "base_sepolia",
        "arbiter": get_erc20_splitter("base_sepolia", config_path=str(path)),
        "demand_data": {"oracle": WALLET.lower(), "data": "0x"},
    }]
    out = _artifacts(
        demands,
        chain_config_paths={"base_sepolia": str(path)},
    )
    plan = out["settlement_plan"]
    assert plan["service_terms"]["interruptible"] == {
        "schema": "vms.interruptible.v1",
        "refund_authority": "seller_declared",
    }
    assert plan["obligations"][0]["params"]["obligation_data"]["arbiter"] == (
        SPLITTER
    )
