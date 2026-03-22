from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from market.cli import app


PRIVATE_KEY = "0x5de4111afa1a4b94908f83103eb1f1706367c2e68ca870fc3fb9a804cdab365a"
OWNER_ADDRESS = "0x3C44CdDdB6a900fa2b585dd299e03d12FA4293BC"


def _recover_signature_address(*, operation: str, resource_id: str, headers: dict[str, str]) -> str:
    eth_account = pytest.importorskip("eth_account")
    messages_mod = pytest.importorskip("eth_account.messages")
    timestamp = headers["X-Timestamp"]
    message = messages_mod.encode_defunct(text=f"{operation}:{resource_id}:{timestamp}")
    return eth_account.Account.recover_message(message, signature=headers["X-Signature"])


def test_order_create_can_sign_with_canonical_auth_url_while_posting_to_tunnel_url(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    env_path = tmp_path / "buyer.env"
    env_path.write_text(
        "\n".join(
            [
                "BASE_URL_OVERRIDE=http://127.0.0.1:28001/",
                "AGENT_AUTH_URL=http://10.243.0.117:8000/",
                f"AGENT_PRIV_KEY={PRIVATE_KEY}",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    observed: dict[str, object] = {}

    def fake_post_json(url: str, payload: dict, extra_headers: dict[str, str] | None = None) -> dict:
        observed["url"] = url
        observed["payload"] = payload
        observed["headers"] = extra_headers or {}
        return {"status": "created", "order_id": "order-123"}

    monkeypatch.setattr("market.groups.order._post_json", fake_post_json)

    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "order",
            "create",
            "--env",
            str(env_path),
            "--offer",
            '{"gpu_model":"H200","quantity":1,"sla":99.9,"region":"California, US"}',
            "--demand",
            '{"token":"WETH","amount":0.0001}',
        ],
    )

    assert result.exit_code == 0, result.output
    assert observed["url"] == "http://127.0.0.1:28001/orders/create"
    assert observed["payload"] == {
        "offer": {"gpu_model": "H200", "quantity": 1, "sla": 99.9, "region": "California, US"},
        "demand": {"token": "WETH", "amount": 0.0001},
        "duration_hours": 1,
    }
    headers = observed["headers"]
    assert isinstance(headers, dict)
    assert _recover_signature_address(
        operation="create_order",
        resource_id="http://10.243.0.117:8000",
        headers=headers,
    ).lower() == OWNER_ADDRESS.lower()


def test_order_match_can_override_auth_url_independently_of_request_url(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    env_path = tmp_path / "buyer.env"
    env_path.write_text(
        "\n".join(
            [
                "BASE_URL_OVERRIDE=http://127.0.0.1:28001/",
                f"AGENT_PRIV_KEY={PRIVATE_KEY}",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    observed: dict[str, object] = {}

    monkeypatch.setattr(
        "market.groups.order._fetch_json",
        lambda url: {
            "order": {
                "order_id": "seller-order-1",
                "offer_resource": {
                    "gpu_model": "H200",
                    "quantity": 1,
                    "sla": 99.9,
                    "region": "California, US",
                },
                "demand_resource": {
                    "token": {
                        "symbol": "WETH",
                        "contract_address": "0x1111111111111111111111111111111111111111",
                        "decimals": 18,
                    },
                    "amount": 100000000000000,
                },
                "duration_hours": 1,
            }
        },
    )

    def fake_post_json(url: str, payload: dict, extra_headers: dict[str, str] | None = None) -> dict:
        observed["url"] = url
        observed["payload"] = payload
        observed["headers"] = extra_headers or {}
        return {"status": "created", "order_id": "buyer-order-1"}

    monkeypatch.setattr("market.groups.order._post_json", fake_post_json)

    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "order",
            "match",
            "seller-order-1",
            "--registry-url",
            "http://127.0.0.1:28080/",
            "--agent-url",
            "http://127.0.0.1:28001/",
            "--auth-agent-url",
            "http://10.243.0.117:8000/",
            "--env",
            str(env_path),
        ],
    )

    assert result.exit_code == 0, result.output
    assert observed["url"] == "http://127.0.0.1:28001/orders/create"
    assert observed["payload"] == {
        "offer": {
            "token": {
                "symbol": "WETH",
                "contract_address": "0x1111111111111111111111111111111111111111",
                "decimals": 18,
            },
            "amount": "0.0001",
        },
        "demand": {
            "gpu_model": "H200",
            "quantity": 1,
            "sla": 99.9,
            "region": "California, US",
        },
        "duration_hours": 1,
    }
    headers = observed["headers"]
    assert isinstance(headers, dict)
    assert _recover_signature_address(
        operation="create_order",
        resource_id="http://10.243.0.117:8000",
        headers=headers,
    ).lower() == OWNER_ADDRESS.lower()
