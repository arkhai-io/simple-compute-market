"""The sample app is gated by the middleware end to end.

Drives the real FastAPI app with a MockTransport-scripted tokens
service behind the gate, so the wiring — middleware order, excluded
paths, the 402 body — is exercised, not just the gate in isolation.
"""

from __future__ import annotations

import httpx

from apitokens_middleware import GateConfig, PurchasePointer, TokenGate, TokensClient
from apitokens_sample_app.app import create_app


def _scripted_gate(balance: int) -> tuple[TokenGate, httpx.AsyncClient]:
    state = {"balance": balance}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/verify"):
            return httpx.Response(200, json={
                "valid": True, "status": "active", "balance": state["balance"]})
        if state["balance"] >= 1:
            state["balance"] -= 1
            return httpx.Response(200, json={
                "ok": True, "consumed": 1, "balance": state["balance"]})
        return httpx.Response(402, json={"error": "insufficient_credits", "balance": 0})

    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    config = GateConfig(
        service_url="http://svc",
        purchase=PurchasePointer(service_name="weather", listing_id="lst-1"),
    )
    gate = TokenGate(config, TokensClient(service_url=config.service_url, http=http))
    return gate, http


async def test_health_open_metered_endpoint_gated_and_drains_to_402():
    gate, http = _scripted_gate(balance=2)
    app = create_app(GateConfig(service_url="http://svc"), gate=gate)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://app",
    ) as c:
        # Health is ungated.
        assert (await c.get("/health")).json() == {"status": "ok"}
        # The metered endpoint needs a token.
        assert (await c.get("/api/forecast")).status_code == 401

        first = await c.get("/api/forecast", headers={"Authorization": "Bearer ak.s"})
        assert first.status_code == 200
        assert first.json()["forecast"] == "sunny"

        assert (await c.get(
            "/api/forecast", headers={"Authorization": "Bearer ak.s"})).status_code == 200

        drained = await c.get("/api/forecast", headers={"Authorization": "Bearer ak.s"})
        assert drained.status_code == 402
        assert drained.json()["purchase"]["service_name"] == "weather"

    await http.aclose()
