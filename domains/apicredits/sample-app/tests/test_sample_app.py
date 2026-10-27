"""The sample app is gated by the family gate end to end.

Drives the real FastAPI app with a MockTransport-scripted credits
service behind the gate, so the wiring — middleware order, excluded
paths, the 402 body — is exercised, not just the gate in isolation.
"""

from __future__ import annotations

import base64
import json

import httpx
import pytest
from market_identity import Ed25519Signer

from arkhai_api_gate import GateConfig, PurchasePointer, TokenGate, TokensClient
from arkhai_api_gate.signing import SigningConfigurationError
from apicredits_sample_app.app import AUTHORITY_LABEL, create_app


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
        authority_label=AUTHORITY_LABEL,
        purchase=PurchasePointer(service_name="weather", listing_id="lst-1"),
    )
    gate = TokenGate(config, TokensClient(service_url=config.service_url, http=http))
    return gate, http


async def test_health_open_metered_endpoint_gated_and_drains_to_402():
    gate, http = _scripted_gate(balance=2)
    app = create_app(GateConfig(service_url="http://svc", authority_label=AUTHORITY_LABEL), gate=gate)

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


# Development seeds; never used on any network.
GATED_APP_SEED = b"sample-app-gated-app-seed-32byte"
AUTHORITY = Ed25519Signer(b"sample-app-authority-seed-32byte")


def _compose_environment(monkeypatch, tmp_path, *, credential: str) -> None:
    """The variables and mounted files the compose file gives the sample app."""

    admin_key = tmp_path / "api-credits-admin-key"
    admin_key.write_text("development-admin-key", encoding="utf-8")
    identity = tmp_path / "credential"
    identity.write_text(credential, encoding="utf-8")
    principals = [AUTHORITY.identity.model_dump(mode="json")]
    for name, value in {
        "SERVICE_URL": "http://credits-service:8082",
        "ADMIN_KEY_FILE": str(admin_key),
        "IDENTITY_CREDENTIAL_FILE": str(identity),
        "AUTHORITY_PRINCIPALS": json.dumps(principals),
        "AMOUNT_PER_REQUEST": "1",
        "VERIFY_TTL_SECONDS": "3",
        "PURCHASE_SERVICE_NAME": "weather-api",
        "PURCHASE_STOREFRONT_URL": "http://credits-storefront:8000",
        "PURCHASE_REGISTRY_URL": "http://api-credits-registry:8080",
    }.items():
        monkeypatch.setenv(f"APICREDITS_MIDDLEWARE_{name}", value)


async def test_the_app_configures_its_signed_gate_from_its_deployment_environment(monkeypatch, tmp_path):
    seed = base64.urlsafe_b64encode(GATED_APP_SEED).rstrip(b"=").decode()
    _compose_environment(monkeypatch, tmp_path, credential=seed + "\n")

    app = create_app()
    config = next(m.kwargs["config"] for m in app.user_middleware if "config" in m.kwargs)

    assert config.service_url == "http://credits-service:8082"
    assert config.authority_label == AUTHORITY_LABEL
    assert config.admin_key == "development-admin-key"
    assert config.verify_ttl_seconds == 3.0
    assert config.purchase.service_name == "weather-api"
    assert config.purchase.registry_url == "http://api-credits-registry:8080"
    assert config.build_signing().principal_identifier == Ed25519Signer(GATED_APP_SEED).identity.identifier
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://app") as c:
        assert (await c.get("/health")).json() == {"status": "ok"}


async def test_an_unusable_mounted_credential_stops_the_app_before_it_serves(monkeypatch, tmp_path):
    _compose_environment(monkeypatch, tmp_path, credential="not-a-credential")

    app = create_app()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://app") as c:
        with pytest.raises(SigningConfigurationError):
            await c.get("/health")
