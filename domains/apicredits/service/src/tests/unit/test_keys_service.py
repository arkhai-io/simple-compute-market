"""KeysService: issuance idempotency, ownership re-check, consume/verify."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from market_identity import Identity, IdentityScheme
from market_resource_pools import DEFAULT_POOL_ID, ResourcePool
from market_resource_pools.db import Base as PoolsBase
from market_site.db import Base as SiteBase
from market_site.ledger import CapacityLedgerService
from db.models import ApiKey, Base, CreditGrant
from models.keys_model import (
    LEGACY_ISSUANCE_RESOURCE_ID,
    LEGACY_ISSUANCE_SERVICE,
    KeyDisposition,
    derive_credit_fulfillment_id,
    issuance_request_digest,
    legacy_issuance_request_digest,
)
from services.keys_service import IssuanceError, KeysService, derive_key_id

BUYER = {
    "buyer_scheme": "eip191",
    "buyer_id": "0xabcd000000000000000000000000000000000001",
}
OTHER = {
    "buyer_scheme": "eip191",
    "buyer_id": "0x9999000000000000000000000000000000000002",
}
ED25519_BUYER = {
    "buyer_scheme": "ed25519",
    "buyer_id": "ERERERERERERERERERERERERERERERERERERERERERE",
}


def _issue(
    service: KeysService,
    *,
    escrow_uid: str,
    quantity: int,
    key_mode: str,
    key_id: str | None = None,
    buyer_scheme: str | None = None,
    buyer_id: str | None = None,
    capacity_reservation_id: str | None = None,
) -> dict:
    if buyer_scheme is None or buyer_id is None:
        raise ValueError("canonical owner is required")
    owner = Identity(scheme=IdentityScheme(buyer_scheme), identifier=buyer_id)
    fulfillment_id = derive_credit_fulfillment_id(escrow_uid)
    key = KeyDisposition(mode=key_mode, key_id=key_id)
    digest = issuance_request_digest(
        fulfillment_id=fulfillment_id,
        obligation_ref=escrow_uid,
        mechanism="alkahest.v1",
        owner=owner,
        service="test-service",
        resource_id="svc-quota",
        quantity=quantity,
        key=key,
    )
    return service.issue(
        fulfillment_id=fulfillment_id,
        obligation_ref=escrow_uid,
        mechanism="alkahest.v1",
        owner_scheme=owner.scheme.value,
        owner_id=owner.identifier,
        service="test-service",
        resource_id="svc-quota",
        quantity=quantity,
        key_mode=key_mode,
        key_id=key_id,
        request_digest=digest,
        capacity_reservation_id=capacity_reservation_id,
    )


def _insert_migrated_legacy_grant(
    engine,
    *,
    escrow_uid: str,
    quantity: int,
    key_mode: str = "existing",
) -> None:
    owner = Identity(
        scheme=IdentityScheme(BUYER["buyer_scheme"]),
        identifier=BUYER["buyer_id"],
    )
    fulfillment_id = derive_credit_fulfillment_id(escrow_uid)
    key_id = (
        derive_key_id(escrow_uid) if key_mode == "new" else f"legacy-key-{escrow_uid}"
    )
    with Session(engine) as db, db.begin():
        db.add(
            ApiKey(
                key_id=key_id,
                secret_hash="legacy-secret-hash",
                owner_scheme=owner.scheme.value,
                owner_id=owner.identifier,
                status="active",
                balance=quantity,
            )
        )
        db.add(
            CreditGrant(
                key_id=key_id,
                fulfillment_id=fulfillment_id,
                obligation_ref=escrow_uid,
                mechanism="alkahest.v1",
                service=LEGACY_ISSUANCE_SERVICE,
                resource_id=LEGACY_ISSUANCE_RESOURCE_ID,
                key_mode=key_mode,
                key_target_id=key_id if key_mode == "existing" else None,
                owner_scheme=owner.scheme.value,
                owner_id=owner.identifier,
                request_digest=legacy_issuance_request_digest(
                    fulfillment_id=fulfillment_id,
                    obligation_ref=escrow_uid,
                    key_id=key_id,
                    key_mode=key_mode,
                    owner=owner,
                    quantity=quantity,
                ),
                escrow_uid=escrow_uid,
                quantity=quantity,
                reason="issuance",
            )
        )


@pytest.fixture
def ledger_and_service() -> tuple[CapacityLedgerService, KeysService, object]:
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    SiteBase.metadata.create_all(bind=engine)
    PoolsBase.metadata.create_all(bind=engine)
    with Session(engine) as db, db.begin():
        db.add(
            ResourcePool(
                id=DEFAULT_POOL_ID,
                label="Default Pool",
                provider="api_credits",
                enabled=True,
                policy_tags={"deliverable_modes": ["api_credits"]},
            )
        )
    session_factory = sessionmaker(bind=engine)
    ledger = CapacityLedgerService(session_factory)
    ledger.register_resource(
        resource_id="svc-quota",
        total_units=1000,
        resource_type="api_credits",
    )
    return (
        ledger,
        KeysService(session_factory=session_factory, capacity_ledger=ledger),
        engine,
    )


@pytest.fixture
def ledger(ledger_and_service) -> CapacityLedgerService:
    return ledger_and_service[0]


@pytest.fixture
def service(ledger_and_service) -> KeysService:
    return ledger_and_service[1]


def test_migrated_legacy_grant_is_adopted_once_for_exact_recovery(
    ledger_and_service,
):
    ledger, service, engine = ledger_and_service
    escrow_uid = "0xlegacy-resume"
    quantity = 7
    _insert_migrated_legacy_grant(
        engine,
        escrow_uid=escrow_uid,
        quantity=quantity,
        key_mode="new",
    )
    key_id = derive_key_id(escrow_uid)

    resumed = _issue(
        service,
        escrow_uid=escrow_uid,
        quantity=quantity,
        key_mode="new",
        key_id=None,
        **BUYER,
    )

    assert resumed["fulfillment_id"] == derive_credit_fulfillment_id(escrow_uid)
    assert resumed["key_id"] == key_id
    assert resumed["already_issued"] is True
    assert resumed["secret"] is not None
    assert (
        service.verify(
            key_id=key_id,
            secret=resumed["secret"],
        )["valid"]
        is True
    )
    assert resumed["balance"] == quantity
    assert ledger.snapshot()[0]["available_units"] == 1000
    with Session(engine) as db:
        grant = db.query(CreditGrant).one()
        owner = Identity(
            scheme=IdentityScheme(BUYER["buyer_scheme"]),
            identifier=BUYER["buyer_id"],
        )
        expected_digest = issuance_request_digest(
            fulfillment_id=derive_credit_fulfillment_id(escrow_uid),
            obligation_ref=escrow_uid,
            mechanism="alkahest.v1",
            owner=owner,
            service="test-service",
            resource_id="svc-quota",
            quantity=quantity,
            key=KeyDisposition(mode="new"),
        )
        assert (grant.service, grant.resource_id, grant.request_digest) == (
            "test-service",
            "svc-quota",
            expected_digest,
        )

    assert (
        _issue(
            service,
            escrow_uid=escrow_uid,
            quantity=quantity,
            key_mode="new",
            key_id=None,
            **BUYER,
        )["already_issued"]
        is True
    )


def test_migrated_legacy_grant_rejects_mismatched_recovery(
    ledger_and_service,
):
    _ledger, service, engine = ledger_and_service
    escrow_uid = "0xlegacy-mismatch"
    _insert_migrated_legacy_grant(engine, escrow_uid=escrow_uid, quantity=7)
    key_id = f"legacy-key-{escrow_uid}"

    with pytest.raises(IssuanceError) as caught:
        _issue(
            service,
            escrow_uid=escrow_uid,
            quantity=8,
            key_mode="existing",
            key_id=key_id,
            **BUYER,
        )

    assert caught.value.reason == "fulfillment_conflict"
    with Session(engine) as db:
        grant = db.query(CreditGrant).one()
        assert (
            grant.service,
            grant.resource_id,
        ) == (
            LEGACY_ISSUANCE_SERVICE,
            LEGACY_ISSUANCE_RESOURCE_ID,
        )


def test_issue_new_key_grants_and_commits_quota(service, ledger):
    result = _issue(
        service,
        escrow_uid="0xe1",
        quantity=100,
        key_mode="new",
        **BUYER,
    )
    assert result["already_issued"] is False
    assert result["balance"] == 100
    # Self-describing secret: middlewares derive the key id from it.
    assert result["secret"].startswith(result["key_id"] + ".")
    assert result["key_id"] == derive_key_id(derive_credit_fulfillment_id("0xe1"))

    # New keys auto-bind to the purchasing marketplace principal.
    key = service.get_key(result["key_id"])
    assert (key["owner_scheme"], key["owner_id"]) == ("eip191", BUYER["buyer_id"])

    # Quota consumed and committed open-ended (credits don't expire).
    assert ledger.snapshot()[0]["available_units"] == 900
    reservation = ledger.get_reservation(result["capacity_reservation_id"])
    assert reservation["state"] == "leased"
    assert reservation["lease_end_utc"] is None


def test_issue_is_idempotent_on_escrow_uid(service, ledger):
    first = _issue(service, escrow_uid="0xe2", quantity=50, key_mode="new", **BUYER)
    again = _issue(service, escrow_uid="0xe2", quantity=50, key_mode="new", **BUYER)
    assert again["already_issued"] is True
    assert again["balance"] == 50  # no double grant
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
    third = _issue(service, escrow_uid="0xe2", quantity=50, key_mode="new", **BUYER)
    assert third["secret"] is None
    assert service.verify(key_id=key_id, secret=again["secret"])["valid"] is True


def test_changed_fulfillment_reuse_conflicts_before_mutation(service, ledger):
    first = _issue(
        service,
        escrow_uid="0xchanged",
        quantity=20,
        key_mode="new",
        **BUYER,
    )
    with pytest.raises(IssuanceError) as caught:
        _issue(
            service,
            escrow_uid="0xchanged",
            quantity=21,
            key_mode="new",
            **BUYER,
        )
    assert caught.value.reason == "fulfillment_conflict"
    assert service.get_key(first["key_id"])["balance"] == 20
    assert ledger.snapshot()[0]["available_units"] == 980


def test_concurrent_exact_retry_commits_one_grant(service, ledger):
    def issue_once() -> dict:
        return _issue(
            service,
            escrow_uid="0xconcurrent",
            quantity=25,
            key_mode="new",
            **BUYER,
        )

    with ThreadPoolExecutor(max_workers=8) as executor:
        results = list(executor.map(lambda _: issue_once(), range(8)))
    assert {result["key_id"] for result in results} == {results[0]["key_id"]}
    assert service.get_key(results[0]["key_id"])["balance"] == 25
    assert ledger.snapshot()[0]["available_units"] == 975


def test_existing_key_top_up_rechecks_ownership(service):
    new = _issue(service, escrow_uid="0xe3", quantity=10, key_mode="new", **BUYER)
    key_id = new["key_id"]

    # The same EIP-191 address is normalized before exact-principal comparison.
    topped = _issue(
        service,
        escrow_uid="0xe4",
        quantity=5,
        key_mode="existing",
        key_id=key_id,
        buyer_scheme="eip191",
        buyer_id=BUYER["buyer_id"].upper().replace("0X", "0x"),
    )
    assert topped["balance"] == 15
    assert topped["secret"] is None  # top-ups never carry a secret

    with pytest.raises(IssuanceError) as exc:
        _issue(
            service,
            escrow_uid="0xe5",
            quantity=5,
            key_mode="existing",
            key_id=key_id,
            **OTHER,
        )
    assert exc.value.reason == "key_not_owned"

    with pytest.raises(IssuanceError) as exc:
        _issue(
            service,
            escrow_uid="0xe5-ed25519",
            quantity=5,
            key_mode="existing",
            key_id=key_id,
            **ED25519_BUYER,
        )
    assert exc.value.reason == "key_not_owned"

    with pytest.raises(IssuanceError) as exc:
        _issue(
            service,
            escrow_uid="0xe6",
            quantity=5,
            key_mode="existing",
            key_id="ak_missing",
            **BUYER,
        )
    assert exc.value.reason == "key_not_found"

    service.revoke(key_id)
    with pytest.raises(IssuanceError) as exc:
        _issue(
            service,
            escrow_uid="0xe7",
            quantity=5,
            key_mode="existing",
            key_id=key_id,
            **BUYER,
        )
    assert exc.value.reason == "key_revoked"


def test_issue_requires_a_complete_canonical_owner(service):
    with pytest.raises(ValueError, match="canonical owner"):
        _issue(service, escrow_uid="0xe8", quantity=10, key_mode="new")


def test_issue_commits_negotiation_hold_instead_of_reserving(service, ledger):
    hold = ledger.reserve(
        claim={"executor_kind": "api_credits", "units": 200},
        deal_ref={"escrow_uid": "0xheld"},
        ttl_seconds=900,
    )
    result = _issue(
        service,
        escrow_uid="0xheld",
        quantity=200,
        key_mode="new",
        capacity_reservation_id=hold["capacity_reservation_id"],
        **BUYER,
    )
    assert result["capacity_reservation_id"] == hold["capacity_reservation_id"]
    # The hold was committed, not duplicated by a fresh reserve.
    assert ledger.snapshot()[0]["available_units"] == 800
    assert ledger.get_reservation(hold["capacity_reservation_id"])["state"] == "leased"


def test_issue_quota_exhausted_persists_nothing(service, ledger):
    with pytest.raises(IssuanceError) as exc:
        _issue(service, escrow_uid="0xbig", quantity=2000, key_mode="new", **BUYER)
    assert exc.value.reason == "quota_exhausted"
    missing_key_id = derive_key_id(derive_credit_fulfillment_id("0xbig"))
    assert service.get_key(missing_key_id) is None
    assert service.list_grants(missing_key_id) == []
    assert ledger.snapshot()[0]["available_units"] == 1000


def test_consume_decrements_with_402_and_idempotency(service):
    new = _issue(service, escrow_uid="0xc1", quantity=3, key_mode="new", **BUYER)
    key_id = new["key_id"]

    assert service.consume(key_id=key_id, amount=2) == {
        "ok": True,
        "consumed": 2,
        "balance": 1,
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
    a = _issue(service, escrow_uid="0xb1", quantity=5, key_mode="new", **BUYER)
    results = service.consume_batch(
        [
            {"key_id": a["key_id"], "amount": 3, "idempotency_key": "r1"},
            {"key_id": "ak_missing", "amount": 1},
            {"key_id": a["key_id"], "amount": 3},  # only 2 left
            {"key_id": a["key_id"], "amount": 2},
        ]
    )
    assert [r["ok"] for r in results] == [True, False, False, True]
    assert results[-1]["balance"] == 0


def test_verify_checks_secret_and_status(service):
    new = _issue(service, escrow_uid="0xv1", quantity=1, key_mode="new", **BUYER)
    key_id, secret = new["key_id"], new["secret"]

    assert service.verify(key_id=key_id, secret=secret)["valid"] is True
    assert service.verify(key_id=key_id, secret="wrong")["valid"] is False
    assert service.verify(key_id="ak_missing", secret=secret)["valid"] is False

    service.revoke(key_id)
    after = service.verify(key_id=key_id, secret=secret)
    assert after["valid"] is False and after["status"] == "revoked"


def test_adjust_records_grant_and_refuses_negative_balance(service):
    new = _issue(service, escrow_uid="0xa1", quantity=10, key_mode="new", **BUYER)
    key_id = new["key_id"]

    adjusted = service.adjust(key_id=key_id, delta=5, reason="goodwill")
    assert adjusted["balance"] == 15

    with pytest.raises(ValueError):
        service.adjust(key_id=key_id, delta=-100)
    assert service.adjust(key_id="ak_missing", delta=1) is None

    grants = service.list_grants(key_id)
    assert [(g["quantity"], g["reason"]) for g in grants] == [
        (10, "issuance"),
        (5, "goodwill"),
    ]
    assert grants[0]["escrow_uid"] == "0xa1" and grants[1]["escrow_uid"] is None


def test_usage_log_pages_by_event_id(service):
    new = _issue(service, escrow_uid="0xu1", quantity=10, key_mode="new", **BUYER)
    for i in range(4):
        service.consume(key_id=new["key_id"], amount=1, idempotency_key=f"r{i}")
    events = service.list_usage(new["key_id"])
    assert len(events) == 4
    page = service.list_usage(new["key_id"], after_id=events[1]["id"], limit=2)
    assert [e["idempotency_key"] for e in page] == ["r2", "r3"]
