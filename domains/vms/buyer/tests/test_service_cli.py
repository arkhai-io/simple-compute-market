"""`market service` heartbeat emission: signature format + loop behavior."""

from __future__ import annotations

from unittest.mock import patch

from eth_account import Account
from eth_account.messages import encode_defunct

from domains.vms.buyer import service_cli

BUYER_KEY = "0xac0974bec39a17e36ba4a6b4d238ff944bacb478cbed5efcae784d7bf4f2ff80"
BUYER_ADDR = Account.from_key(BUYER_KEY).address
ESCROW = "0x" + "ab" * 32


def test_heartbeat_signature_matches_seller_canonical_format():
    """The signed message must be deal_heartbeat:<uid>:<ts> — the exact
    string core_storefront.auth reconstructs on the seller side."""
    captured = {}

    def fake_post(url, body, *, signature, timestamp, **kw):
        captured.update(url=url, body=body, signature=signature, timestamp=timestamp)
        return {"heartbeat_count": 1, "next_expected_by_unix": timestamp + 60}

    with patch("domains.vms.buyer.buyer_client._post", side_effect=fake_post):
        ack = service_cli.send_heartbeat(
            seller_url="http://seller:8001/",
            escrow_uid=ESCROW,
            buyer_address=BUYER_ADDR,
            buyer_private_key=BUYER_KEY,
        )

    assert ack["heartbeat_count"] == 1
    assert captured["url"] == f"http://seller:8001/api/v1/deals/{ESCROW}/heartbeat"
    assert captured["body"]["buyer_address"] == BUYER_ADDR
    assert captured["body"]["payload"] == {
        "schema": "vms.heartbeat.v1", "status": "healthy",
    }

    message = f"deal_heartbeat:{ESCROW}:{captured['timestamp']}"
    recovered = Account.recover_message(
        encode_defunct(text=message), signature=captured["signature"]
    )
    assert recovered == BUYER_ADDR


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
