"""HTTP surface: auth gate, issuance→consume→top-up flow, quota mount.

Environment overrides land before ``main`` (and therefore ``config``)
is imported: an in-memory DB and a configured admin key.
"""

from __future__ import annotations

import os

os.environ["APITOKENS_DATABASE_URL"] = "sqlite:///:memory:"
os.environ["APITOKENS_STOREFRONT_ADMIN_KEY"] = "test-admin-key"

import pytest
from fastapi.testclient import TestClient

import main  # noqa: E402  (env must be set first)

AUTH = {"X-Admin-Key": "test-admin-key"}


@pytest.fixture(scope="module")
def client():
    with TestClient(main.app) as c:
        yield c


def test_health_open_but_api_gated(client):
    assert client.get("/health").status_code == 200
    assert client.get("/api/v1/keys").status_code == 401
    assert client.get("/api/v1/keys", headers={"X-Admin-Key": "wrong"}).status_code == 401
    assert client.get("/api/v1/keys", headers=AUTH).status_code == 200


def test_full_deal_flow(client):
    # Seller quota: the resource a listing derives from.
    r = client.put(
        "/api/v1/capacity/resources/svc-quota",
        json={"total_units": 1000, "resource_type": "api_tokens"},
        headers=AUTH,
    )
    assert r.status_code == 200

    # Issuance (new key) — the settlement fulfillment call.
    r = client.post(
        "/api/v1/issuance",
        json={
            "escrow_uid": "0xdeal1",
            "quantity": 3,
            "key": {"mode": "new"},
            "buyer": {"scheme": "wallet", "id": "0xBuyer1"},
        },
        headers=AUTH,
    )
    assert r.status_code == 200, r.text
    issued = r.json()
    key_id, secret = issued["key_id"], issued["secret"]
    assert secret and issued["balance"] == 3

    # Quota committed.
    snapshot = client.get("/api/v1/capacity/snapshot", headers=AUTH).json()
    assert snapshot["resources"][0]["available_units"] == 997

    # Middleware verify + consume to exhaustion.
    r = client.post(
        f"/api/v1/keys/{key_id}/verify", json={"secret": secret}, headers=AUTH,
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
        f"/api/v1/keys/{key_id}/consume", json={"amount": 1}, headers=AUTH,
    )
    assert r.status_code == 402
    assert r.json() == {"error": "insufficient_credits", "balance": 0}

    # The re-purchase loop: a second deal tops up the existing key.
    r = client.post(
        "/api/v1/issuance",
        json={
            "escrow_uid": "0xdeal2",
            "quantity": 2,
            "key": {"mode": "existing", "key_id": key_id},
            "buyer": {"scheme": "wallet", "id": "0xbuyer1"},  # case-insensitive
        },
        headers=AUTH,
    )
    assert r.status_code == 200, r.text
    assert r.json()["balance"] == 2 and r.json()["secret"] is None

    r = client.post(
        f"/api/v1/keys/{key_id}/consume", json={"amount": 1}, headers=AUTH,
    )
    assert r.status_code == 200 and r.json()["balance"] == 1

    # A stranger cannot top up the wallet-bound key.
    r = client.post(
        "/api/v1/issuance",
        json={
            "escrow_uid": "0xdeal3",
            "quantity": 1,
            "key": {"mode": "existing", "key_id": key_id},
            "buyer": {"scheme": "wallet", "id": "0xMallory"},
        },
        headers=AUTH,
    )
    assert r.status_code == 403
    assert r.json()["error"] == "key_not_owned"

    # Guard lookup: ownership claim, no secrets anywhere.
    r = client.get(f"/api/v1/keys/{key_id}", headers=AUTH)
    detail = r.json()
    assert detail["owner_scheme"] == "wallet"
    assert "secret" not in detail and "secret_hash" not in detail


def test_batch_consume_and_admin_surface(client):
    r = client.post(
        "/api/v1/issuance",
        json={
            "escrow_uid": "0xdeal4",
            "quantity": 5,
            "key": {"mode": "new"},
            "buyer": {"scheme": "wallet", "id": "0xBuyer2"},
        },
        headers=AUTH,
    )
    key_id = r.json()["key_id"]

    r = client.post(
        "/api/v1/keys/consume-batch",
        json={"items": [
            {"key_id": key_id, "amount": 2, "idempotency_key": "b1"},
            {"key_id": key_id, "amount": 2, "idempotency_key": "b1"},  # duplicate
            {"key_id": "ak_missing", "amount": 1},
        ]},
        headers=AUTH,
    )
    assert r.status_code == 200
    results = r.json()["results"]
    assert results[0]["ok"] is True and results[0]["balance"] == 3
    assert results[1]["duplicate"] is True
    assert results[2]["ok"] is False

    r = client.post(
        f"/api/v1/keys/{key_id}/adjust",
        json={"delta": 10, "reason": "goodwill"}, headers=AUTH,
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
