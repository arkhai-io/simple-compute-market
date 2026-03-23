from __future__ import annotations

import importlib.util
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
SCRIPT_PATH = ROOT / "scripts/run_human_seller_publish.py"


def _load_script_module():
    spec = importlib.util.spec_from_file_location("run_human_seller_publish", SCRIPT_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _write_env(path: Path, values: dict[str, str]) -> None:
    path.write_text(
        "".join(f"{key}={value}\n" for key, value in values.items()),
        encoding="utf-8",
    )


def test_publish_human_seller_offer_uses_live_portfolio_and_shared_artifact(
    tmp_path: Path,
    monkeypatch,
) -> None:
    module = _load_script_module()
    env_path = tmp_path / "seller.env"
    _write_env(
        env_path,
        {
            "AGENT_URL": "http://127.0.0.1:28002/",
            "AGENT_AUTH_URL": "http://10.243.0.68:8000/",
            "AGENT_PRIV_KEY": "0xseller",
        },
    )

    portfolio_calls: list[str] = []
    create_calls: list[dict[str, object]] = []
    monkeypatch.setattr(
        module,
        "fetch_portfolio",
        lambda seller_agent_url: portfolio_calls.append(seller_agent_url)
        or [
            {
                "resource_id": "compute-ww1-001",
                "gpu_model": "RTX 5080",
                "quantity": 1,
                "sla": 90.0,
                "region": "California, US",
            }
        ],
    )
    monkeypatch.setattr(
        module,
        "create_order",
        lambda *, request_url, auth_url, private_key, payload: create_calls.append(
            {
                "request_url": request_url,
                "auth_url": auth_url,
                "private_key": private_key,
                "payload": payload,
            }
        )
        or {"status": "open", "order_id": "seller-order-1", "event_id": "event-1"},
    )

    result = module.publish_human_seller_offer(
        env_path=env_path,
        resource_id="compute-ww1-001",
        gpu_model=None,
        region=None,
        quantity=1,
        token="WETH",
        amount="0.0001",
        duration_hours=1,
    )

    assert portfolio_calls == ["http://127.0.0.1:28002/"]
    assert create_calls == [
        {
            "request_url": "http://127.0.0.1:28002/",
            "auth_url": "http://10.243.0.68:8000/",
            "private_key": "0xseller",
            "payload": {
                "offer": {
                    "gpu_model": "RTX 5080",
                    "quantity": 1,
                    "sla": 90.0,
                    "region": "California, US",
                },
                "demand": {"token": "WETH", "amount": "0.0001"},
                "duration_hours": 1,
            },
        }
    ]
    assert result["seller_order_id"] == "seller-order-1"
    assert result["order_id"] == "seller-order-1"
    assert result["status"] == "open"
    assert result["artifact"]["role"] == "seller"
    assert result["artifact"]["correlation"]["order_id"] == "seller-order-1"
    assert result["artifact"]["details"]["selected_resource"]["resource_id"] == "compute-ww1-001"
    assert Path(result["artifact_path"]).exists()


def test_select_resource_filters_live_portfolio() -> None:
    module = _load_script_module()
    resources = [
        {
            "resource_id": "compute-ww1-001",
            "gpu_model": "RTX 5080",
            "quantity": 1,
            "sla": 90.0,
            "region": "California, US",
        },
        {
            "resource_id": "compute-btc1-001",
            "gpu_model": "H200",
            "quantity": 1,
            "sla": 99.0,
            "region": "Texas, US",
        },
    ]

    selected = module.select_resource(
        resources=resources,
        resource_id=None,
        gpu_model="RTX 5080",
        region=None,
        quantity=1,
    )

    assert selected["resource_id"] == "compute-ww1-001"


def test_build_seller_artifact_uses_shared_contract() -> None:
    module = _load_script_module()

    artifact = module.build_seller_artifact(
        request_url="http://127.0.0.1:28002/",
        auth_url="http://10.243.0.68:8000/",
        response={"status": "open", "order_id": "seller-order-1"},
        selected_resource={
            "resource_id": "compute-ww1-001",
            "gpu_model": "RTX 5080",
            "quantity": 1,
            "sla": 90.0,
            "region": "California, US",
        },
        payload={
            "offer": {
                "gpu_model": "RTX 5080",
                "quantity": 1,
                "sla": 90.0,
                "region": "California, US",
            },
            "demand": {"token": "WETH", "amount": "0.0001"},
            "duration_hours": 1,
        },
    )

    assert artifact["role"] == "seller"
    assert artifact["action"] == "publish"
    assert artifact["correlation"]["order_id"] == "seller-order-1"
    assert artifact["details"]["selected_resource"]["resource_id"] == "compute-ww1-001"
