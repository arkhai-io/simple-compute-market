"""HTTP surface: auth gate, issuance→consume→top-up flow, quota mount.

Environment overrides land before ``main`` (and therefore ``config``)
is imported: an in-memory DB and a configured admin key.
"""

from __future__ import annotations

import os

os.environ["APICREDITS_DATABASE_URL"] = "sqlite:///:memory:"
os.environ["APICREDITS_STOREFRONT_ADMIN_KEY"] = "test-admin-key"

import pytest
from fastapi.testclient import TestClient

import main  # noqa: E402  (env must be set first)
from market_identity import Identity
from models.keys_model import (
    KeyDisposition,
    derive_credit_fulfillment_id,
    issuance_request_digest,
)

AUTH = {"X-Admin-Key": "test-admin-key"}
BUYER_1 = "0xabcdef0000000000000000000000000000000001"
BUYER_2 = "0xabcdef0000000000000000000000000000000002"
MALLORY = "0x9999000000000000000000000000000000000003"


def _issuance_payload(
    obligation_ref: str,
    *,
    owner_identifier: str,
    quantity: int,
    key: dict[str, str],
) -> dict[str, object]:
    owner = Identity(scheme="eip191", identifier=owner_identifier)
    disposition = KeyDisposition.model_validate(key)
    fulfillment_id = derive_credit_fulfillment_id(obligation_ref)
    request_digest = issuance_request_digest(
        fulfillment_id=fulfillment_id,
        obligation_ref=obligation_ref,
        mechanism="alkahest.v1",
        owner=owner,
        service="test-api",
        resource_id="svc-quota",
        quantity=quantity,
        key=disposition,
    )
    return {
        "fulfillment_id": fulfillment_id,
        "obligation_ref": obligation_ref,
        "mechanism": "alkahest.v1",
        "owner": owner.model_dump(mode="json"),
        "service": "test-api",
        "resource_id": "svc-quota",
        "quantity": quantity,
        "key": disposition.model_dump(mode="json"),
        "request_digest": request_digest,
    }


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


def test_full_deal_flow(client):
    # Seller quota: the resource a listing derives from.
    r = client.put(
        "/api/v1/capacity/resources/svc-quota",
        json={"total_units": 1000, "resource_type": "api_credits"},
        headers=AUTH,
    )
    assert r.status_code == 200

    # Issuance (new key) — the settlement fulfillment call.
    r = client.post(
        "/api/v1/issuance",
        json=_issuance_payload(
            "0xdeal1",
            quantity=3,
            key={"mode": "new"},
            owner_identifier=BUYER_1.upper().replace("0X", "0x"),
        ),
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

    # The re-purchase loop: a second deal tops up the existing key.
    r = client.post(
        "/api/v1/issuance",
        json=_issuance_payload(
            "0xdeal2",
            quantity=2,
            key={"mode": "existing", "key_id": key_id},
            owner_identifier=BUYER_1,
        ),
        headers=AUTH,
    )
    assert r.status_code == 200, r.text
    assert r.json()["balance"] == 2 and r.json()["secret"] is None

    r = client.post(
        f"/api/v1/keys/{key_id}/consume",
        json={"amount": 1},
        headers=AUTH,
    )
    assert r.status_code == 200 and r.json()["balance"] == 1

    # A stranger cannot top up the principal-bound key.
    r = client.post(
        "/api/v1/issuance",
        json=_issuance_payload(
            "0xdeal3",
            quantity=1,
            key={"mode": "existing", "key_id": key_id},
            owner_identifier=MALLORY,
        ),
        headers=AUTH,
    )
    assert r.status_code == 403
    assert r.json()["error"] == "key_not_owned"

    # Guard lookup: ownership claim, no secrets anywhere.
    r = client.get(f"/api/v1/keys/{key_id}", headers=AUTH)
    detail = r.json()
    assert detail["owner_scheme"] == "eip191"
    assert "secret" not in detail and "secret_hash" not in detail


def test_batch_consume_and_admin_surface(client):
    r = client.post(
        "/api/v1/issuance",
        json=_issuance_payload(
            "0xdeal4",
            quantity=5,
            key={"mode": "new"},
            owner_identifier=BUYER_2,
        ),
        headers=AUTH,
    )
    key_id = r.json()["key_id"]

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
