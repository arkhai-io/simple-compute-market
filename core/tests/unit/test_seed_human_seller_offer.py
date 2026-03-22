from __future__ import annotations

import importlib.util
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
SCRIPT_PATH = ROOT / "scripts/seed_human_seller_offer.py"


def _load_script_module():
    spec = importlib.util.spec_from_file_location("seed_human_seller_offer", SCRIPT_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _write_env(path: Path, values: dict[str, str]) -> None:
    path.write_text(
        "".join(f"{key}={value}\n" for key, value in values.items()),
        encoding="utf-8",
    )


def test_select_resource_prefers_requested_inventory_match() -> None:
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
        resource_id="compute-ww1-001",
        gpu_model=None,
        region=None,
        quantity=1,
    )

    assert selected["gpu_model"] == "RTX 5080"
    assert selected["region"] == "California, US"


def test_seed_human_seller_offer_uses_live_portfolio_resource(tmp_path: Path, monkeypatch) -> None:
    module = _load_script_module()
    sandbox_dir = tmp_path / "sandbox"
    sandbox_dir.mkdir()
    context_path = sandbox_dir / "context.json"
    context_path.write_text(
        json.dumps(
            {
                "sandbox_dir": str(sandbox_dir),
                "seller_agent_url": "http://127.0.0.1:28002/",
            }
        ),
        encoding="utf-8",
    )
    _write_env(
        sandbox_dir / "seller.env",
        {
            "AGENT_AUTH_URL": "http://10.243.0.68:8000/",
            "AGENT_PRIV_KEY": "0xseller",
        },
    )

    monkeypatch.setattr(
        module,
        "fetch_portfolio",
        lambda seller_agent_url: [
            {
                "resource_id": "compute-ww1-001",
                "gpu_model": "RTX 5080",
                "quantity": 1,
                "sla": 90.0,
                "region": "California, US",
            }
        ],
    )

    captured: dict[str, object] = {}

    def _fake_create_order(*, request_url: str, auth_url: str, private_key: str, payload: dict[str, object]):
        captured["request_url"] = request_url
        captured["auth_url"] = auth_url
        captured["private_key"] = private_key
        captured["payload"] = payload
        return {"status": "open", "order_id": "seller-order-1", "event_id": "event-1"}

    monkeypatch.setattr(module, "create_order", _fake_create_order)

    result = module.seed_human_seller_offer(
        context_path=context_path,
        token="WETH",
        amount="0.0001",
        duration_hours=1,
        quantity=1,
    )

    assert captured["request_url"] == "http://127.0.0.1:28002/"
    assert captured["auth_url"] == "http://10.243.0.68:8000/"
    assert captured["private_key"] == "0xseller"
    assert captured["payload"] == {
        "offer": {
            "gpu_model": "RTX 5080",
            "quantity": 1,
            "sla": 90.0,
            "region": "California, US",
        },
        "demand": {"token": "WETH", "amount": "0.0001"},
        "duration_hours": 1,
    }
    assert result["selected_resource"]["resource_id"] == "compute-ww1-001"
    assert result["order_id"] == "seller-order-1"
    assert Path(result["artifact_path"]).exists()
