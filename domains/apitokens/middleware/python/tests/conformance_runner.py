"""Reference harness that replays ``conformance/session.json``.

Drives the real ``TokenGate`` + ``TokensClient`` against an
``httpx.MockTransport`` scripted from the fixture, so the test exercises
request shaping and response parsing — not a stub. The TS and Rust
harnesses mirror this structure at the HTTP layer (see
``conformance/README.md``).
"""

from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path
from typing import Any

import httpx

from apitokens_middleware.client import TokensClient
from apitokens_middleware.config import GateConfig, PurchasePointer
from apitokens_middleware.gate import TokenGate

CONFORMANCE_DIR = Path(__file__).resolve().parents[2] / "conformance"


def load_session(name: str = "session.json") -> dict[str, Any]:
    return json.loads((CONFORMANCE_DIR / name).read_text(encoding="utf-8"))


class _ScriptedService:
    """Replays scripted verify/consume responses and counts calls per key."""

    def __init__(self, service: dict[str, Any]) -> None:
        self._verify = service.get("verify", {})
        self._consume = service.get("consume", {})
        self._cursor: dict[tuple[str, str], int] = defaultdict(int)
        self.verify_calls: dict[str, int] = defaultdict(int)
        self.consume_calls: dict[str, int] = defaultdict(int)

    def _next(self, kind: str, key_id: str, script: dict[str, Any]) -> dict[str, Any]:
        entries = script.get(key_id) or [{}]
        idx = min(self._cursor[(kind, key_id)], len(entries) - 1)
        self._cursor[(kind, key_id)] += 1
        return entries[idx]

    def handle(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        parts = path.strip("/").split("/")
        # /api/v1/keys/{key_id}/verify | /consume ; /api/v1/keys/consume-batch
        if path.endswith("/verify"):
            key_id = parts[-2]
            self.verify_calls[key_id] += 1
            body = self._next("verify", key_id, self._verify)
            return httpx.Response(200, json=body)
        if path.endswith("/consume"):
            key_id = parts[-2]
            self.consume_calls[key_id] += 1
            entry = self._next("consume", key_id, self._consume)
            return httpx.Response(entry.get("status", 200), json=entry.get("body", {}))
        raise AssertionError(f"unexpected request to {path}")


def _config_from(fixture: dict[str, Any]) -> GateConfig:
    cfg = fixture["config"]
    p = cfg.get("purchase", {})
    return GateConfig(
        service_url="http://tokens-service",
        admin_key="conformance-admin-key",
        amount_per_request=cfg.get("amount_per_request", 1),
        verify_ttl_seconds=cfg.get("verify_ttl_seconds", 30),
        low_balance_threshold=cfg.get("low_balance_threshold", 0),
        flush_interval_seconds=cfg.get("flush_interval_seconds", 0),
        purchase=PurchasePointer(
            service_name=p.get("service_name"),
            listing_id=p.get("listing_id"),
            storefront_url=p.get("storefront_url"),
            registry_url=p.get("registry_url"),
        ),
    )


async def run_session(fixture: dict[str, Any]) -> None:
    service = _ScriptedService(fixture["service"])
    transport = httpx.MockTransport(service.handle)
    config = _config_from(fixture)
    async with httpx.AsyncClient(transport=transport) as http:
        client = TokensClient(
            service_url=config.service_url, admin_key=config.admin_key, http=http,
        )
        gate = TokenGate(config, client)

        for step in fixture["steps"]:
            before_v = sum(service.verify_calls.values())
            before_c = sum(service.consume_calls.values())
            decision = await gate.authorize(step["authorization"])
            made_v = sum(service.verify_calls.values()) - before_v
            made_c = sum(service.consume_calls.values()) - before_c

            exp = step["expect"]
            name = step["name"]
            assert decision.allowed == exp["allowed"], (
                f"[{name}] allowed: got {decision.allowed}, want {exp['allowed']}"
            )
            assert decision.status == exp["status"], (
                f"[{name}] status: got {decision.status}, want {exp['status']}"
            )
            if "error" in exp:
                got_error = (decision.body or {}).get("error")
                assert got_error == exp["error"], (
                    f"[{name}] error: got {got_error!r}, want {exp['error']!r}"
                )
            if "purchase" in exp:
                has_purchase = "purchase" in (decision.body or {})
                assert has_purchase == exp["purchase"], (
                    f"[{name}] purchase pointer: got {has_purchase}, want {exp['purchase']}"
                )
            assert made_v == step["verify_calls"], (
                f"[{name}] verify calls: got {made_v}, want {step['verify_calls']}"
            )
            assert made_c == step["consume_calls"], (
                f"[{name}] consume calls: got {made_c}, want {step['consume_calls']}"
            )
