"""HTTP surface: auth gate, issuance→consume→top-up flow, quota mount.

Environment overrides land before ``main`` (and therefore ``config``)
is imported: an in-memory DB and a configured admin key.
"""

from __future__ import annotations

import asyncio
import os

import httpx

os.environ["APICREDITS_DATABASE_URL"] = "sqlite:///:memory:"
os.environ["APICREDITS_STOREFRONT_ADMIN_KEY"] = "test-admin-key"

import pytest
from fastapi.testclient import TestClient

import main  # noqa: E402  (env must be set first)
from market_identity import Identity
from domains.apicredits.settlement.credits_client import (
    CreditIssuanceRequest,
    CreditKeyTarget,
    CreditsServiceClient,
    CreditsServiceError,
)

AUTH = {"X-Admin-Key": "test-admin-key"}
BUYER_1 = "0xabcdef0000000000000000000000000000000001"
BUYER_2 = "0xabcdef0000000000000000000000000000000002"
MALLORY = "0x9999000000000000000000000000000000000003"


def _request(
    negotiation_id: str,
    *,
    owner_identifier: str,
    quantity: int,
    key: dict[str, str],
    capacity_reservation_id: str | None = None,
) -> CreditIssuanceRequest:
    return CreditIssuanceRequest.create(
        negotiation_id=negotiation_id,
        owner=Identity(scheme="eip191", identifier=owner_identifier),
        service="test-api",
        resource_id="svc-quota",
        quantity=quantity,
        key=CreditKeyTarget.model_validate(key),
        capacity_reservation_id=capacity_reservation_id,
    )


@pytest.fixture
def credits(client):
    return CreditsServiceClient(
        "http://testserver",
        "test-admin-key",
        transport=httpx.ASGITransport(app=main.app),
    )


@pytest.fixture(scope="module")
def client():
    with TestClient(main.app) as c:
        yield c


def test_health_open_but_api_gated(client):
    assert client.get("/health").status_code == 200
    assert client.get("/api/v1/keys").status_code == 401
    assert (
        client.get("/api/v1/keys", headers={"X-Admin-Key": "wrong"}).status_code == 401
    )
    assert client.get("/api/v1/keys", headers=AUTH).status_code == 200

    # Rejection paths: the typed client cannot construct legacy or tampered bodies.
    payload = _request(
        "neg-rejected", quantity=1, key={"mode": "new"}, owner_identifier=BUYER_1
    ).model_dump(mode="json")
    legacy = {**payload, "obligation_ref": "esc-old", "mechanism": "alkahest.v1"}
    del legacy["negotiation_id"]
    assert client.post("/api/v1/issuance", json=legacy, headers=AUTH).status_code == 422
    tampered = {**payload, "quantity": 2}
    assert client.post("/api/v1/issuance", json=tampered, headers=AUTH).status_code == 422
    assert client.post("/api/v1/issuance", json=payload).status_code == 401


def test_full_deal_flow(client, credits):
    # Seller quota: the resource a listing derives from.
    r = client.put(
        "/api/v1/capacity/resources/svc-quota",
        json={"total_units": 1000, "resource_type": "api_credits"},
        headers=AUTH,
    )
    assert r.status_code == 200

    # The operator-authenticated typed client owns issuance wire shapes.
    request = _request(
        "neg-deal1",
        quantity=3,
        key={"mode": "new"},
        owner_identifier=BUYER_1.upper().replace("0X", "0x"),
    )
    issued = asyncio.run(credits.submit_credit_issuance(request))
    key_id, secret = issued.key_id, issued.secret
    assert secret and issued.balance == 3
    assert "secret" not in issued.model_dump(mode="json")

    replay = asyncio.run(credits.submit_credit_issuance(request))
    assert replay.key_id == key_id and replay.already_issued
    assert replay.balance == 3 and replay.secret != secret
    secret = replay.secret
    found = asyncio.run(credits.get_credit_issuance(request.fulfillment_id))
    assert found.key_id == key_id and found.secret is None

    # Quota committed.
    snapshot = client.get("/api/v1/capacity/snapshot", headers=AUTH).json()
    assert snapshot["resources"][0]["available_units"] == 997

    # Middleware verify + consume to exhaustion.
    r = client.post(
        f"/api/v1/keys/{key_id}/verify",
        json={"secret": secret},
        headers=AUTH,
    )
    assert r.json()["valid"] is True

    for i in range(3):
        r = client.post(
            f"/api/v1/keys/{key_id}/consume",
            json={"amount": 1, "idempotency_key": f"req-{i}"},
            headers=AUTH,
        )
        assert r.status_code == 200, r.text
    r = client.post(
        f"/api/v1/keys/{key_id}/consume",
        json={"amount": 1},
        headers=AUTH,
    )
    assert r.status_code == 402
    assert r.json() == {"error": "insufficient_credits", "balance": 0}

    # Consumption suppresses secret rotation on recovery.
    used_replay = asyncio.run(credits.submit_credit_issuance(request))
    assert used_replay.secret is None and used_replay.balance == 3

    topped = asyncio.run(
        credits.submit_credit_issuance(
            _request(
                "neg-deal2",
                quantity=2,
                key={"mode": "existing", "key_id": key_id},
                owner_identifier=BUYER_1,
            )
        )
    )
    assert topped.balance == 2 and topped.secret is None

    r = client.post(
        f"/api/v1/keys/{key_id}/consume",
        json={"amount": 1},
        headers=AUTH,
    )
    assert r.status_code == 200 and r.json()["balance"] == 1

    # A different purchase uses the same authorization, with no mechanism input.
    another = asyncio.run(
        credits.submit_credit_issuance(
            _request(
                "neg-deal-payment",
                quantity=2,
                key={"mode": "existing", "key_id": key_id},
                owner_identifier=BUYER_1,
            )
        )
    )
    assert another.balance == 3 and another.secret is None
    with pytest.raises(CreditsServiceError) as caught:
        asyncio.run(
            credits.submit_credit_issuance(
                _request(
                    "neg-deal3",
                    quantity=1,
                    key={"mode": "existing", "key_id": key_id},
                    owner_identifier=MALLORY,
                )
            )
        )
    assert caught.value.reason == "key_not_owned"
    assert caught.value.status_code == 403

    with pytest.raises(CreditsServiceError) as caught:
        asyncio.run(
            credits.submit_credit_issuance(
                _request(
                    request.negotiation_id,
                    quantity=4,
                    key={"mode": "new"},
                    owner_identifier=BUYER_1,
                )
            )
        )
    assert caught.value.reason == "fulfillment_conflict"
    assert asyncio.run(credits.get_key(key_id))["balance"] == 3
    snapshot = client.get("/api/v1/capacity/snapshot", headers=AUTH).json()
    assert snapshot["resources"][0]["available_units"] == 993
    assert client.get(f"/api/v1/keys/{key_id}/grants", headers=AUTH).json()["total"] == 3

    # Guard lookup: ownership claim, no secrets anywhere.
    r = client.get(f"/api/v1/keys/{key_id}", headers=AUTH)
    detail = r.json()
    assert detail["owner_scheme"] == "eip191"
    assert "secret" not in detail and "secret_hash" not in detail


def test_batch_consume_and_admin_surface(client, credits):
    issued = asyncio.run(
        credits.submit_credit_issuance(
            _request(
                "neg-deal4",
                quantity=5,
                key={"mode": "new"},
                owner_identifier=BUYER_2,
            )
        )
    )
    key_id = issued.key_id

    r = client.post(
        "/api/v1/keys/consume-batch",
        json={
            "items": [
                {"key_id": key_id, "amount": 2, "idempotency_key": "b1"},
                {"key_id": key_id, "amount": 2, "idempotency_key": "b1"},  # duplicate
                {"key_id": "ak_missing", "amount": 1},
            ]
        },
        headers=AUTH,
    )
    assert r.status_code == 200
    results = r.json()["results"]
    assert results[0]["ok"] is True and results[0]["balance"] == 3
    assert results[1]["duplicate"] is True
    assert results[2]["ok"] is False

    r = client.post(
        f"/api/v1/keys/{key_id}/adjust",
        json={"delta": 10, "reason": "goodwill"},
        headers=AUTH,
    )
    assert r.json()["balance"] == 13

    grants = client.get(f"/api/v1/keys/{key_id}/grants", headers=AUTH).json()
    assert grants["total"] == 2

    usage = client.get(f"/api/v1/keys/{key_id}/usage", headers=AUTH).json()
    assert usage["total"] == 1

    r = client.post(f"/api/v1/keys/{key_id}/revoke", headers=AUTH)
    assert r.json()["status"] == "revoked"
    r = client.post(f"/api/v1/keys/{key_id}/consume", json={"amount": 1}, headers=AUTH)
    assert r.status_code == 403 and r.json()["error"] == "key_revoked"
