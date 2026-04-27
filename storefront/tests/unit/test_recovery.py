"""Unit tests for the pure recovery-flow derivation helpers.

Each `derive_*_params` encodes the validation + status guards for its
endpoint. The endpoint handler's remaining work (alkahest call, DB write,
stage event) is a straight pass-through, so exercising these pure
helpers covers the business logic without bootstrapping the agent.
"""

from __future__ import annotations

import pytest

from market_storefront.utils.recovery import (
    derive_arbitrate_params,
    derive_claim_params,
    derive_reclaim_params,
)


def _order(
    *,
    order_id: str = "ord-1",
    status: str = "accepted",
    escrow_uid: str | None = "0xescrow",
    maker_attestation: str | None = "0xfulfill",
    oracle_address: str | None = "0x" + "0" * 40,
) -> dict:
    return {
        "order_id": order_id,
        "status": status,
        "escrow_uid": escrow_uid,
        "maker_attestation": maker_attestation,
        "oracle_address": oracle_address,
    }


# ---------------------------------------------------------------------------
# derive_claim_params
# ---------------------------------------------------------------------------


def test_claim_happy_path_uses_local_attestation():
    order = _order()
    tag, params = derive_claim_params(order=order, payload={"order_id": "ord-1"})
    assert tag == "ok"
    assert params["escrow_uid"] == "0xescrow"
    assert params["fulfillment_uid"] == "0xfulfill"


def test_claim_missing_order_id_is_value_error():
    with pytest.raises(ValueError, match="order_id"):
        derive_claim_params(order=None, payload={})


def test_claim_order_not_found_returns_404():
    tag, status, body = derive_claim_params(order=None, payload={"order_id": "gone"})
    assert tag == "error"
    assert status == 404


def test_claim_already_closed_returns_409():
    order = _order(status="closed")
    tag, status, body = derive_claim_params(order=order, payload={"order_id": "ord-1"})
    assert tag == "error"
    assert status == 409


def test_claim_without_escrow_uid_returns_400():
    order = _order(escrow_uid=None)
    tag, status, body = derive_claim_params(order=order, payload={"order_id": "ord-1"})
    assert tag == "error"
    assert status == 400
    assert "escrow_uid" in body["error"]


def test_claim_without_attestation_returns_400():
    order = _order(maker_attestation=None)
    tag, status, body = derive_claim_params(order=order, payload={"order_id": "ord-1"})
    assert tag == "error"
    assert status == 400
    assert "maker_attestation" in body["error"] or "fulfillment" in body["error"]


def test_claim_payload_override_wins_over_db():
    order = _order(maker_attestation=None)
    tag, params = derive_claim_params(
        order=order,
        payload={"order_id": "ord-1", "fulfillment_uid": "0xfromclient"},
    )
    assert tag == "ok"
    assert params["fulfillment_uid"] == "0xfromclient"


# ---------------------------------------------------------------------------
# derive_reclaim_params
# ---------------------------------------------------------------------------


def test_reclaim_happy_path():
    order = _order(status="accepted", maker_attestation=None)  # attestation not needed
    tag, params = derive_reclaim_params(order=order, payload={"order_id": "ord-1"})
    assert tag == "ok"
    assert params["escrow_uid"] == "0xescrow"


def test_reclaim_order_not_found_returns_404():
    tag, status, body = derive_reclaim_params(order=None, payload={"order_id": "gone"})
    assert tag == "error"
    assert status == 404


@pytest.mark.parametrize("terminal", ["closed", "reclaimed", "refunded"])
def test_reclaim_terminal_state_returns_409(terminal):
    order = _order(status=terminal)
    tag, status, body = derive_reclaim_params(order=order, payload={"order_id": "ord-1"})
    assert tag == "error"
    assert status == 409
    assert body["status"] == terminal


def test_reclaim_without_escrow_uid_returns_400():
    order = _order(escrow_uid=None)
    tag, status, body = derive_reclaim_params(order=order, payload={"order_id": "ord-1"})
    assert tag == "error"
    assert status == 400
    assert "escrow_uid" in body["error"]


# ---------------------------------------------------------------------------
# derive_arbitrate_params
# ---------------------------------------------------------------------------


def test_arbitrate_happy_path_defaults_to_approve():
    order = _order()
    tag, params = derive_arbitrate_params(order=order, payload={"order_id": "ord-1"})
    assert tag == "ok"
    assert params["decision"] is True
    assert params["fulfillment_uid"] == "0xfulfill"
    assert params["escrow_uid"] == "0xescrow"


def test_arbitrate_decision_false_is_respected():
    order = _order()
    tag, params = derive_arbitrate_params(
        order=order, payload={"order_id": "ord-1", "decision": False}
    )
    assert tag == "ok"
    assert params["decision"] is False


@pytest.mark.parametrize(
    "decision_raw,expected",
    [("true", True), ("yes", True), ("1", True), ("approve", True),
     ("false", False), ("no", False), ("0", False), ("reject", False)],
)
def test_arbitrate_string_decision_is_normalized(decision_raw, expected):
    order = _order()
    tag, params = derive_arbitrate_params(
        order=order, payload={"order_id": "ord-1", "decision": decision_raw}
    )
    assert tag == "ok"
    assert params["decision"] is expected


def test_arbitrate_order_not_found_returns_404():
    tag, status, body = derive_arbitrate_params(order=None, payload={"order_id": "gone"})
    assert tag == "error"
    assert status == 404


def test_arbitrate_without_attestation_and_no_override_returns_400():
    order = _order(maker_attestation=None)
    tag, status, body = derive_arbitrate_params(
        order=order, payload={"order_id": "ord-1"}
    )
    assert tag == "error"
    assert status == 400
    assert "fulfillment" in body["error"].lower() or "maker_attestation" in body["error"]


def test_arbitrate_payload_fulfillment_uid_overrides_db():
    order = _order(maker_attestation=None)
    tag, params = derive_arbitrate_params(
        order=order,
        payload={"order_id": "ord-1", "fulfillment_uid": "0xoverride"},
    )
    assert tag == "ok"
    assert params["fulfillment_uid"] == "0xoverride"
