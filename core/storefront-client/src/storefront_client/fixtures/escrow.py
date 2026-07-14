"""Contract fixtures for storefront-client escrow boundary messages.

These fixtures define the canonical shape of the HTTP response bodies that
``SyncStorefrontClient.claim_listing()`` and ``SyncStorefrontClient.refund_listing()``
return, as packaged by ``_submit_claim`` and ``_submit_refund`` in
``market_storefront.groups.escrow``.

Each boundary is represented by a pair of functions:

- ``build_*()``     — constructs a canonical instance for use as a mock
                      return value in consumer tests.
- ``validate_*()``  — asserts that a value produced by real code conforms
                      to the contract.  Called by producer-side tests.

Usage in a consumer test::

    from fixtures.escrow import build_claim_response
    monkeypatch.setattr(escrow_group, "_submit_claim", lambda *a: build_claim_response())

Usage in a producer test (once storefront-client gains unit tests)::

    from fixtures.escrow import validate_claim_response
    response = client.claim_listing(...)
    validate_claim_response(response)
"""

from __future__ import annotations


# ---------------------------------------------------------------------------
# claim
# ---------------------------------------------------------------------------


def build_claim_response(
    *,
    escrow_uid: str = "0xESCROW",
    escrow_kind: str = "ERC20",
    fulfillment_uid: str = "0xFULF",
    collect_result: str = "ok",
) -> dict:
    """Canonical claim response returned by ``_submit_claim``."""
    return {
        "status": "claimed",
        "escrow_uid": escrow_uid,
        "escrow_kind": escrow_kind,
        "fulfillment_uid": fulfillment_uid,
        "collect_result": collect_result,
    }


def validate_claim_response(actual: dict) -> None:
    """Assert that *actual* conforms to the claim response contract."""
    assert actual.get("status") == "claimed", f"Expected status 'claimed', got {actual.get('status')!r}"
    assert "escrow_uid" in actual, "claim response must include 'escrow_uid'"
    assert "escrow_kind" in actual, "claim response must include 'escrow_kind'"
    assert "fulfillment_uid" in actual, "claim response must include 'fulfillment_uid'"
    assert "collect_result" in actual, "claim response must include 'collect_result'"


# ---------------------------------------------------------------------------
# refund
# ---------------------------------------------------------------------------


def build_refund_response(
    *,
    tx_hash: str = "0xTX",
    from_address: str = "0xSELLER",
    to_address: str = "0xBUYER",
    token: str | None = None,
    amount_raw: str = "1000000",
    block_number: int = 42,
) -> dict:
    """Canonical refund response returned by ``_submit_refund``."""
    return {
        "status": "refunded",
        "tx_hash": tx_hash,
        "from_address": from_address,
        "to_address": to_address,
        "token": token,
        "amount_raw": amount_raw,
        "block_number": block_number,
    }


def validate_refund_response(actual: dict) -> None:
    """Assert that *actual* conforms to the refund response contract."""
    assert actual.get("status") == "refunded", f"Expected status 'refunded', got {actual.get('status')!r}"
    assert "tx_hash" in actual, "refund response must include 'tx_hash'"
    assert "from_address" in actual, "refund response must include 'from_address'"
    assert "to_address" in actual, "refund response must include 'to_address'"
    assert "token" in actual, "refund response must include 'token' (may be None)"
    assert "amount_raw" in actual, "refund response must include 'amount_raw'"
    assert "block_number" in actual, "refund response must include 'block_number'"
