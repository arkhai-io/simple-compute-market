"""`market service` heartbeat emission: signature format + loop behavior."""

from __future__ import annotations

from unittest.mock import patch

from market_identity import Ed25519Signer, TrustedIdentitySet

from domains.vms.buyer import service_cli

SIGNER = Ed25519Signer(b"\x31" * 32)
SELLER = Ed25519Signer(b"\x32" * 32).identity
DEAL_REF = "deal-123"


def test_heartbeat_uses_v2_body_bound_principals_and_refreshes_response_trust():
    captured = {}
    refreshes = 0

    def resolve_seller_principals():
        nonlocal refreshes
        refreshes += 1
        return TrustedIdentitySet(identities=(SELLER,))

    def fake_signed_json(url, body, **kwargs):
        captured.update(url=url, body=body, kwargs=kwargs)
        kwargs["resolve_response_principals"]()
        return {"heartbeat_count": 1, "next_expected_by_unix": 60}

    with patch(
        "core_buyer.orchestration._signed_json",
        side_effect=fake_signed_json,
    ):
        ack = service_cli.send_heartbeat(
            seller_url="http://seller:8001/",
            deal_ref=DEAL_REF,
            principal=SIGNER.identity,
            signer=SIGNER,
            seller_principal=SELLER,
            resolve_seller_principals=resolve_seller_principals,
        )

    assert ack["heartbeat_count"] == 1
    assert captured["url"] == f"http://seller:8001/api/v1/deals/{DEAL_REF}/heartbeat"
    assert captured["body"]["buyer_principal"] == SIGNER.identity.model_dump(
        mode="json"
    )
    assert captured["body"]["seller_principal"] == SELLER.model_dump(mode="json")
    assert captured["body"]["payload"] == {
        "schema": "vms.heartbeat.v1",
        "status": "healthy",
    }
    assert captured["kwargs"]["operation"] == "deal_heartbeat"
    assert captured["kwargs"]["resource"] == DEAL_REF
    assert refreshes == 1


def test_expiration_extraction_prefers_settlement_plan():
    class Deal:
        settlement_plan = {
            "obligations": [
                {"mechanism": "alkahest.v1", "expiration_unix": 1_900_000_000},
            ],
        }

    assert service_cli._deal_expiration_unix(Deal()) == 1_900_000_000.0

    class NoPlan:
        settlement_plan = None

    assert service_cli._deal_expiration_unix(NoPlan()) is None


def test_cadence_prefers_plan_service_terms():
    class Deal:
        settlement_plan = {
            "obligations": [],
            "service_terms": {"heartbeat": {"interval_seconds": 45}},
        }

    assert service_cli._plan_heartbeat_interval(Deal()) == 45.0

    class Bare:
        settlement_plan = {"obligations": []}

    assert service_cli._plan_heartbeat_interval(Bare()) is None
