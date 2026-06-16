"""KeysService: issuance idempotency, ownership re-check, consume/verify."""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from core_site.db import Base as SiteBase
from core_site.ledger import CapacityLedgerService
from db.models import Base
from services.keys_service import IssuanceError, KeysService, derive_key_id

BUYER = {"buyer_scheme": "wallet", "buyer_id": "0xAbCd000000000000000000000000000000000001"}
OTHER = {"buyer_scheme": "wallet", "buyer_id": "0x9999000000000000000000000000000000000002"}


@pytest.fixture
def ledger_and_service() -> tuple[CapacityLedgerService, KeysService]:
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    SiteBase.metadata.create_all(bind=engine)
    session_factory = sessionmaker(bind=engine)
    ledger = CapacityLedgerService(session_factory)
    ledger.register_resource(
        resource_id="svc-quota", total_units=1000, resource_type="api_tokens",
    )
    return ledger, KeysService(session_factory=session_factory, capacity_ledger=ledger)


@pytest.fixture
def ledger(ledger_and_service) -> CapacityLedgerService:
    return ledger_and_service[0]


@pytest.fixture
def service(ledger_and_service) -> KeysService:
    return ledger_and_service[1]


def test_issue_new_key_grants_and_commits_quota(service, ledger):
    result = service.issue(
        escrow_uid="0xe1", quantity=100, key_mode="new", **BUYER,
    )
    assert result["already_issued"] is False
    assert result["balance"] == 100
    # Self-describing secret: middlewares derive the key id from it.
    assert result["secret"].startswith(result["key_id"] + ".")
    assert result["key_id"] == derive_key_id("0xe1")

    # New keys auto-bind owner = purchasing wallet.
    key = service.get_key(result["key_id"])
    assert (key["owner_scheme"], key["owner_id"]) == ("wallet", BUYER["buyer_id"])

    # Quota consumed and committed open-ended (credits don't expire).
    assert ledger.snapshot()[0]["available_units"] == 900
    allocation = ledger.get_allocation(result["allocation_id"])
    assert allocation["state"] == "leased"
    assert allocation["lease_end_utc"] is None


def test_issue_is_idempotent_on_escrow_uid(service, ledger):
    first = service.issue(escrow_uid="0xe2", quantity=50, key_mode="new", **BUYER)
    again = service.issue(escrow_uid="0xe2", quantity=50, key_mode="new", **BUYER)
    assert again["already_issued"] is True
    assert again["balance"] == 50                       # no double grant
    assert ledger.snapshot()[0]["available_units"] == 950  # no double quota

    # Unused key: the retry rotates the secret so a lost response can't
    # strand the buyer. Old secret dies, new one verifies.
    assert again["secret"] is not None and again["secret"] != first["secret"]
    key_id = first["key_id"]
    assert service.verify(key_id=key_id, secret=first["secret"])["valid"] is False
    assert service.verify(key_id=key_id, secret=again["secret"])["valid"] is True

    # Once the key has consumed, the buyer evidently holds the secret:
    # no rotation, nothing returned.
    service.consume(key_id=key_id, amount=1)
    third = service.issue(escrow_uid="0xe2", quantity=50, key_mode="new", **BUYER)
    assert third["secret"] is None
    assert service.verify(key_id=key_id, secret=again["secret"])["valid"] is True


def test_existing_key_top_up_rechecks_ownership(service):
    new = service.issue(escrow_uid="0xe3", quantity=10, key_mode="new", **BUYER)
    key_id = new["key_id"]

    # Same wallet, different case: admitted (addresses compare lowered).
    topped = service.issue(
        escrow_uid="0xe4", quantity=5, key_mode="existing", key_id=key_id,
        buyer_scheme="wallet", buyer_id=BUYER["buyer_id"].upper().replace("0X", "0x"),
    )
    assert topped["balance"] == 15
    assert topped["secret"] is None  # top-ups never carry a secret

    with pytest.raises(IssuanceError) as exc:
        service.issue(
            escrow_uid="0xe5", quantity=5, key_mode="existing", key_id=key_id, **OTHER,
        )
    assert exc.value.reason == "key_not_owned"

    with pytest.raises(IssuanceError) as exc:
        service.issue(
            escrow_uid="0xe6", quantity=5, key_mode="existing", key_id="ak_missing", **BUYER,
        )
    assert exc.value.reason == "key_not_found"

    service.revoke(key_id)
    with pytest.raises(IssuanceError) as exc:
        service.issue(
            escrow_uid="0xe7", quantity=5, key_mode="existing", key_id=key_id, **BUYER,
        )
    assert exc.value.reason == "key_revoked"


def test_unowned_key_accepts_open_top_up(service):
    # No buyer identity bound at creation = no ownership guard on the key.
    new = service.issue(escrow_uid="0xe8", quantity=10, key_mode="new")
    key = service.get_key(new["key_id"])
    assert key["owner_scheme"] is None

    topped = service.issue(
        escrow_uid="0xe9", quantity=10, key_mode="existing", key_id=new["key_id"], **OTHER,
    )
    assert topped["balance"] == 20


def test_issue_commits_negotiation_hold_instead_of_reserving(service, ledger):
    hold = ledger.reserve(
        claim={"units": 200}, deal_ref={"escrow_uid": "0xheld"}, ttl_seconds=900,
    )
    result = service.issue(
        escrow_uid="0xheld", quantity=200, key_mode="new",
        allocation_id=hold["allocation_id"], **BUYER,
    )
    assert result["allocation_id"] == hold["allocation_id"]
    # The hold was committed, not duplicated by a fresh reserve.
    assert ledger.snapshot()[0]["available_units"] == 800
    assert ledger.get_allocation(hold["allocation_id"])["state"] == "leased"


def test_issue_quota_exhausted_persists_nothing(service, ledger):
    with pytest.raises(IssuanceError) as exc:
        service.issue(escrow_uid="0xbig", quantity=2000, key_mode="new", **BUYER)
    assert exc.value.reason == "quota_exhausted"
    assert service.get_key(derive_key_id("0xbig")) is None
    assert service.list_grants(derive_key_id("0xbig")) == []
    assert ledger.snapshot()[0]["available_units"] == 1000


def test_consume_decrements_with_402_and_idempotency(service):
    new = service.issue(escrow_uid="0xc1", quantity=3, key_mode="new", **BUYER)
    key_id = new["key_id"]

    assert service.consume(key_id=key_id, amount=2) == {
        "ok": True, "consumed": 2, "balance": 1,
    }
    short = service.consume(key_id=key_id, amount=2)
    assert short == {"ok": False, "reason": "insufficient_credits", "balance": 1}

    # Idempotent flushes: the same key applies once.
    first = service.consume(key_id=key_id, amount=1, idempotency_key="req-1")
    assert first["ok"] is True and first["balance"] == 0
    dup = service.consume(key_id=key_id, amount=1, idempotency_key="req-1")
    assert dup == {"ok": True, "consumed": 0, "duplicate": True, "balance": 0}

    assert service.consume(key_id="ak_missing", amount=1)["reason"] == "key_not_found"
    service.revoke(key_id)
    assert service.consume(key_id=key_id, amount=1)["reason"] == "key_revoked"

    with pytest.raises(ValueError):
        service.consume(key_id=key_id, amount=0)


def test_consume_batch_keeps_order_and_isolates_failures(service):
    a = service.issue(escrow_uid="0xb1", quantity=5, key_mode="new", **BUYER)
    results = service.consume_batch([
        {"key_id": a["key_id"], "amount": 3, "idempotency_key": "r1"},
        {"key_id": "ak_missing", "amount": 1},
        {"key_id": a["key_id"], "amount": 3},  # only 2 left
        {"key_id": a["key_id"], "amount": 2},
    ])
    assert [r["ok"] for r in results] == [True, False, False, True]
    assert results[-1]["balance"] == 0


def test_verify_checks_secret_and_status(service):
    new = service.issue(escrow_uid="0xv1", quantity=1, key_mode="new", **BUYER)
    key_id, secret = new["key_id"], new["secret"]

    assert service.verify(key_id=key_id, secret=secret)["valid"] is True
    assert service.verify(key_id=key_id, secret="wrong")["valid"] is False
    assert service.verify(key_id="ak_missing", secret=secret)["valid"] is False

    service.revoke(key_id)
    after = service.verify(key_id=key_id, secret=secret)
    assert after["valid"] is False and after["status"] == "revoked"


def test_adjust_records_grant_and_refuses_negative_balance(service):
    new = service.issue(escrow_uid="0xa1", quantity=10, key_mode="new", **BUYER)
    key_id = new["key_id"]

    adjusted = service.adjust(key_id=key_id, delta=5, reason="goodwill")
    assert adjusted["balance"] == 15

    with pytest.raises(ValueError):
        service.adjust(key_id=key_id, delta=-100)
    assert service.adjust(key_id="ak_missing", delta=1) is None

    grants = service.list_grants(key_id)
    assert [(g["quantity"], g["reason"]) for g in grants] == [
        (10, "issuance"), (5, "goodwill"),
    ]
    assert grants[0]["escrow_uid"] == "0xa1" and grants[1]["escrow_uid"] is None


def test_usage_log_pages_by_event_id(service):
    new = service.issue(escrow_uid="0xu1", quantity=10, key_mode="new", **BUYER)
    for i in range(4):
        service.consume(key_id=new["key_id"], amount=1, idempotency_key=f"r{i}")
    events = service.list_usage(new["key_id"])
    assert len(events) == 4
    page = service.list_usage(new["key_id"], after_id=events[1]["id"], limit=2)
    assert [e["idempotency_key"] for e in page] == ["r2", "r3"]
