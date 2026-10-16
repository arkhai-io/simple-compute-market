"""Release-model plan shapes: the listing marking and each plan's service terms.

The release conditions a listing advertises are the Alkahest mechanism's own
derivation, tested in ``kit/alkahest/tests/unit/test_release_conditions.py``.
"""

from __future__ import annotations

from unittest.mock import patch

from market_alkahest.alkahest import (
    get_erc20_splitter,
    get_recipient_arbiter,
    get_trusted_oracle_arbiter,
)

WALLET = "0x" + "ab" * 20
ESCROW = "0x" + "11" * 20
TOKEN = "0x" + "aa" * 20
SPLITTER = "0x" + "44" * 20


def _settings(*, interruptible: bool = False):
    return {"settlement": {"alkahest": {"interruptible": interruptible}}}


def test_interruptible_listing_resource_is_marked():
    from market_storefront.services.publication_terms import (
        listing_resource_for_candidate,
    )

    resource = {
        "offering_mode": "vm",
        "pool_id": "pool-a",
        "resource_id": "machine-a",
        "listing_shape": {"gpu": {"count": 1, "model": "A100"}},
        "sla": "best_effort",
        "region": "iad",
        "capacity_backing": "backed",
    }
    with patch(
        "market_storefront.utils.config.settings",
        _settings(interruptible=True),
    ):
        listing_resource = listing_resource_for_candidate(resource)
    assert listing_resource["interruptible"] is True
    assert listing_resource["settlement_model"] == "splitter_refund"


def _artifacts(demands, heartbeat_interval=60, chain_config_paths=None):
    from arkhai_vms_settlement.proposals import (
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
    # The listing advertises the condition the proposal selects.
    return accepted_escrow_artifacts_from_proposal(
        proposal=proposal,
        listing={"demands": demands},
        agreed_amount=5_000_000,
        duration_seconds=3600,
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
