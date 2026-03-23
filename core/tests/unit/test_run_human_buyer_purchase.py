from __future__ import annotations

import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
SCRIPT_PATH = ROOT / "scripts/run_human_buyer_purchase.py"


def _load_script_module():
    spec = importlib.util.spec_from_file_location("run_human_buyer_purchase", SCRIPT_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_select_offer_prefers_explicit_order_id() -> None:
    module = _load_script_module()
    offers = [
        {
            "order_id": "order-1",
            "offer_resource": {"gpu_model": "RTX 5080", "region": "California, US"},
            "demand_resource": {
                "token": {"symbol": "WETH", "decimals": 18},
                "amount": 100000000000000,
            },
        },
        {
            "order_id": "order-2",
            "offer_resource": {"gpu_model": "H200", "region": "Texas, US"},
            "demand_resource": {
                "token": {"symbol": "WETH", "decimals": 18},
                "amount": 300000000000000,
            },
        },
    ]

    selected = module.select_offer(
        offers=offers,
        order_id="order-2",
        gpu_model=None,
        region=None,
        max_price=None,
    )

    assert selected["order_id"] == "order-2"


def test_select_offer_filters_and_picks_cheapest_match() -> None:
    module = _load_script_module()
    offers = [
        {
            "order_id": "expensive",
            "offer_resource": {"gpu_model": "RTX 5080", "region": "California, US"},
            "demand_resource": {
                "token": {"symbol": "WETH", "decimals": 18},
                "amount": 200000000000000,
            },
        },
        {
            "order_id": "cheap",
            "offer_resource": {"gpu_model": "RTX 5080", "region": "California, US"},
            "demand_resource": {
                "token": {"symbol": "WETH", "decimals": 18},
                "amount": 100000000000000,
            },
        },
        {
            "order_id": "wrong-region",
            "offer_resource": {"gpu_model": "RTX 5080", "region": "Texas, US"},
            "demand_resource": {
                "token": {"symbol": "WETH", "decimals": 18},
                "amount": 50000000000000,
            },
        },
    ]

    selected = module.select_offer(
        offers=offers,
        order_id=None,
        gpu_model="RTX 5080",
        region="California, US",
        max_price="0.00015",
    )

    assert selected["order_id"] == "cheap"


def test_build_buyer_artifact_uses_shared_role_contract() -> None:
    module = _load_script_module()
    artifact = module.build_buyer_artifact(
        action="purchase",
        status="succeeded",
        request_url="http://127.0.0.1:28001/",
        auth_url="http://10.243.0.117:8000/",
        order_id="buyer-order-1",
        job_id="job-1",
        vm_target="tenant-1",
        details={"selected_seller_order_id": "seller-order-1"},
    )

    assert artifact["role"] == "buyer"
    assert artifact["correlation"]["order_id"] == "buyer-order-1"
    assert artifact["correlation"]["job_id"] == "job-1"
    assert artifact["correlation"]["vm_target"] == "tenant-1"
    assert artifact["details"]["selected_seller_order_id"] == "seller-order-1"
