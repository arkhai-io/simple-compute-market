"""Replay the installed publication through the shared payments authority fixture."""

from __future__ import annotations

import hashlib

from market_identity import Ed25519Signer
from market_arkhai_payments.canonical import agreement_hash, jcs_bytes
from market_arkhai_payments.contracts import get_contract
from market_arkhai_payments.fixtures.authority import PaymentsAuthority, snapshot_message
from market_arkhai_payments.models import (
    ApprovalRequest, DealAttachment, Mandate, SignedReceipt, StoredDealAttachment,
    SignedTransactionSnapshot,
)
from market_arkhai_payments.receipts import transaction_id, verify_receipt_signature


def _authority(mandate, signed, signer, clock):
    receipt = signed["receipt"]
    engine = PaymentsAuthority(signer=signer, clock=lambda: clock[0],
                               ledger=receipt["ledger"], livemode=receipt["livemode"])
    for part in receipt["parts"]:
        engine.fund(mandate["from"], part["asset"], int(part["gross"]))
    actual = engine.approve(mandate, account=mandate["from"])
    assert actual.model_dump(mode="json", by_alias=True, exclude_none=True) == signed
    return engine


def _differences(actual, expected, path=""):
    if actual == expected:
        return []
    if isinstance(actual, dict) and isinstance(expected, dict):
        return [difference for key in actual.keys() | expected.keys()
                for difference in _differences(
                    actual.get(key, "<absent>"), expected.get(key, "<absent>"), f"{path}/{key}")]
    if isinstance(actual, list) and isinstance(expected, list) and len(actual) == len(expected):
        return [difference for index, (a, e) in enumerate(zip(actual, expected))
                for difference in _differences(a, e, f"{path}/{index}")]
    return [f"{path}: actual={actual!r}, expected={expected!r}"]


def _snapshot(engine, transaction, vector):
    expected = SignedTransactionSnapshot.model_validate(vector["signed"])
    body = expected.snapshot.model_dump(mode="json", by_alias=True, exclude_none=True)
    assert snapshot_message(body).hex() == vector["message"]
    actual = engine.snapshot(transaction)
    actual_wire = actual.model_dump(mode="json", by_alias=True, exclude_none=True)
    assert actual_wire == vector["signed"], "\n".join(_differences(actual_wire, vector["signed"]))


def main() -> int:
    contract = get_contract()
    vectors = contract.vectors()
    # Published, deterministic development key, never for a public network.
    signer = Ed25519Signer(bytes.fromhex(vectors["keys"]["service"]))
    for vector in vectors["mandates"]:
        mandate = Mandate.model_validate(vector["mandate"])
        assert transaction_id(mandate) == vector["id"]

    signed = SignedReceipt.model_validate(vectors["receipt"]["signed"])
    trusted = signed.receipt.issuer.model_dump(mode="json", by_alias=True)
    assert verify_receipt_signature(signed, trusted)

    for vector in vectors["attachments"]:
        DealAttachment.model_validate(vector["request"])
        stored = StoredDealAttachment.model_validate(vector["stored"])
        canonical = jcs_bytes(stored.content.root)
        assert hashlib.sha256(canonical).hexdigest() == stored.sha256.root
        assert len(canonical) == stored.size

    for vector in vectors["approvals"]:
        request = ApprovalRequest.model_validate(vector["request"])
        assert transaction_id(request.mandate) == vector["id"]
        assert request.attachments is not None
        assert agreement_hash(request.attachments[0].content.root) == request.mandate.deal.root.root

    for vector in vectors["snapshots"]:
        snapshot = vector["signed"]["snapshot"]
        clock = [snapshot["receipt"]["receipt"]["approvedAt"]]
        engine = _authority(vector["mandate"], snapshot["receipt"], signer, clock)
        for event in snapshot["events"]:
            clock[0] = event["receivedAt"]
            if "account" in event:
                request_body = {k: event[k] for k in ("account", "requestId", "event")}
                assert engine.submit(snapshot["transaction"], request_body) == event
            else:
                engine.advance(snapshot["transaction"], refill=False)
        clock[0] = snapshot["observedAt"]
        _snapshot(engine, snapshot["transaction"], vector)

    steps = 0
    for scenario in vectors["scenarios"]:
        clock = [scenario["approvedAt"]]
        engine = _authority(scenario["mandate"], scenario["receipt"], signer, clock)
        transaction = scenario["receipt"]["receipt"]["transaction"]
        for step in scenario["steps"]:
            clock[0] = step["at"]
            if "request" in step:
                assert engine.submit(transaction, step["request"]) == step["expectedEvent"]
            _snapshot(engine, transaction, step["snapshot"])
            steps += 1

    print("ok: published mandates, receipt, attachments, approvals,",
          len(vectors["snapshots"]), "snapshots and", steps, "scenario steps")
    print("contract:", contract.metadata)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
