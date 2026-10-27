"""KeysService: issuance idempotency, ownership re-check, consume/verify."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from arkhai_api.issuance import KeyDisposition, fulfillment_id, issuance_request
from arkhai_api_authority import IssuanceError, KeysService, derive_key_id, initialize, run_migrations
from market_identity import Identity, IdentityScheme
from market_site.ledger import CapacityLedgerService, UndeclaredOfferingModeError

from tests.integration.profiles import CONFIG, LABEL, PROFILE, config_for

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
    negotiation_id: str,
    quantity: int,
    key_mode: str,
    key_id: str | None = None,
    buyer_scheme: str | None = None,
    buyer_id: str | None = None,
    capacity_reservation_id: str | None = None,
    issuance_service: str = "test-service",
    resource_id: str = "svc-quota",
) -> dict:
    if buyer_scheme is None or buyer_id is None:
        raise ValueError("canonical owner is required")
    owner = Identity(scheme=IdentityScheme(buyer_scheme), identifier=buyer_id)
    request = issuance_request(
        LABEL,
        negotiation_id=negotiation_id,
        owner=owner,
        service=issuance_service,
        resource_id=resource_id,
        quantity=quantity,
        key=KeyDisposition(mode=key_mode, key_id=key_id),
    )
    return service.issue(
        fulfillment_id=request.fulfillment_id,
        negotiation_id=negotiation_id,
        owner_scheme=owner.scheme.value,
        owner_id=owner.identifier,
        service=issuance_service,
        resource_id=resource_id,
        quantity=quantity,
        key_mode=key_mode,
        key_id=key_id,
        request_digest=request.request_digest,
        capacity_reservation_id=capacity_reservation_id,
    )


def _composed(config=CONFIG) -> tuple[CapacityLedgerService, KeysService, object]:
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    run_migrations(engine)
    initialize(engine, config.profile)
    session_factory = sessionmaker(bind=engine)
    ledger = CapacityLedgerService(session_factory)
    ledger.register_resource(
        resource_id="svc-quota",
        total_units=1000,
        resource_type="example.units",
        pool_id=config.profile.pool_id,
    )
    return (
        ledger,
        KeysService(session_factory=session_factory, capacity_ledger=ledger, config=config),
        engine,
    )


@pytest.fixture
def ledger_and_service() -> tuple[CapacityLedgerService, KeysService, object]:
    return _composed()


@pytest.fixture
def ledger(ledger_and_service) -> CapacityLedgerService:
    return ledger_and_service[0]


@pytest.fixture
def service(ledger_and_service) -> KeysService:
    return ledger_and_service[1]


def test_issue_new_key_grants_and_commits_quota(service, ledger):
    result = _issue(
        service,
        negotiation_id="0xe1",
        quantity=100,
        key_mode="new",
        **BUYER,
    )
    assert result["already_issued"] is False
    assert result["balance"] == 100
    # Self-describing secret: middlewares derive the key id from it.
    assert result["secret"].startswith(result["key_id"] + ".")
    assert result["key_id"] == derive_key_id(CONFIG.key_prefix, fulfillment_id(LABEL, "0xe1"))

    # New keys auto-bind to the purchasing marketplace principal.
    key = service.get_key(result["key_id"])
    assert (key["owner_scheme"], key["owner_id"]) == ("eip191", BUYER["buyer_id"])

    # Quota consumed and committed open-ended (credits don't expire).
    assert ledger.snapshot()[0]["available_units"] == 900
    reservation = ledger.get_reservation(result["capacity_reservation_id"])
    assert reservation["state"] == "leased"
    assert reservation["lease_end_utc"] is None


def test_issue_is_idempotent_on_negotiation_id(service, ledger):
    first = _issue(service, negotiation_id="0xe2", quantity=50, key_mode="new", **BUYER)
    again = _issue(service, negotiation_id="0xe2", quantity=50, key_mode="new", **BUYER)
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
    third = _issue(service, negotiation_id="0xe2", quantity=50, key_mode="new", **BUYER)
    assert third["secret"] is None
    assert service.verify(key_id=key_id, secret=again["secret"])["valid"] is True


@pytest.mark.parametrize(
    "changed",
    [
        {"quantity": 21},
        {"buyer_id": OTHER["buyer_id"]},
        {"issuance_service": "different-service"},
        {"resource_id": "different-quota"},
        {"key_mode": "existing", "key_id": "another-key"},
    ],
)
def test_changed_fulfillment_reuse_conflicts_before_mutation(service, ledger, changed):
    first = _issue(
        service,
        negotiation_id="0xchanged",
        quantity=20,
        key_mode="new",
        **BUYER,
    )
    replay = {
        "negotiation_id": "0xchanged",
        "quantity": 20,
        "key_mode": "new",
        **BUYER,
        **changed,
    }
    with pytest.raises(IssuanceError) as caught:
        _issue(service, **replay)
    assert caught.value.reason == "fulfillment_conflict"
    assert service.get_key(first["key_id"])["balance"] == 20
    assert ledger.snapshot()[0]["available_units"] == 980


def test_concurrent_exact_retry_commits_one_grant(service, ledger):
    def issue_once() -> dict:
        return _issue(
            service,
            negotiation_id="0xconcurrent",
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
    new = _issue(service, negotiation_id="0xe3", quantity=10, key_mode="new", **BUYER)
    key_id = new["key_id"]

    # The same EIP-191 address is normalized before exact-principal comparison.
    topped = _issue(
        service,
        negotiation_id="0xe4",
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
            negotiation_id="0xe5",
            quantity=5,
            key_mode="existing",
            key_id=key_id,
            **OTHER,
        )
    assert exc.value.reason == "key_not_owned"

    with pytest.raises(IssuanceError) as exc:
        _issue(
            service,
            negotiation_id="0xe5-ed25519",
            quantity=5,
            key_mode="existing",
            key_id=key_id,
            **ED25519_BUYER,
        )
    assert exc.value.reason == "key_not_owned"

    with pytest.raises(IssuanceError) as exc:
        _issue(
            service,
            negotiation_id="0xe6",
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
            negotiation_id="0xe7",
            quantity=5,
            key_mode="existing",
            key_id=key_id,
            **BUYER,
        )
    assert exc.value.reason == "key_revoked"


def test_issue_requires_a_complete_canonical_owner(service):
    with pytest.raises(ValueError, match="canonical owner"):
        _issue(service, negotiation_id="0xe8", quantity=10, key_mode="new")


def test_issue_commits_negotiation_hold_instead_of_reserving(service, ledger):
    hold = ledger.reserve(
        claim={"offering_mode": PROFILE.offering_mode, "units": 200},
        deal_ref={"negotiation_id": "0xheld"},
        ttl_seconds=900,
    )
    result = _issue(
        service,
        negotiation_id="0xheld",
        quantity=200,
        key_mode="new",
        capacity_reservation_id=hold["capacity_reservation_id"],
        **BUYER,
    )
    assert result["capacity_reservation_id"] == hold["capacity_reservation_id"]
    # The hold was committed, not duplicated by a fresh reserve.
    assert ledger.snapshot()[0]["available_units"] == 800
    assert ledger.get_reservation(hold["capacity_reservation_id"])["state"] == "leased"


def test_quota_hold_is_bound_to_purchase(service, ledger):
    hold = ledger.reserve(
        claim={"offering_mode": PROFILE.offering_mode, "units": 1},
        deal_ref={"negotiation_id": "neg-other"},
        ttl_seconds=900,
    )
    with pytest.raises(IssuanceError) as caught:
        _issue(
            service,
            negotiation_id="neg-purchase",
            quantity=200,
            key_mode="new",
            capacity_reservation_id=hold["capacity_reservation_id"],
            **BUYER,
        )
    assert caught.value.reason == "fulfillment_conflict"
    assert service.get_key(
        derive_key_id(CONFIG.key_prefix, fulfillment_id(LABEL, "neg-purchase"))
    ) is None
    assert ledger.snapshot()[0]["available_units"] == 999


def test_expired_hold_replaced_and_replay_does_not_commit_twice(service, ledger):
    hold = ledger.reserve(
        claim={"offering_mode": PROFILE.offering_mode, "units": 200},
        deal_ref={"negotiation_id": "neg-expired"},
        ttl_seconds=-1,
    )
    issued = _issue(
        service,
        negotiation_id="neg-expired",
        quantity=200,
        key_mode="new",
        capacity_reservation_id=hold["capacity_reservation_id"],
        **BUYER,
    )
    assert issued["capacity_reservation_id"] != hold["capacity_reservation_id"]
    assert ledger.get_reservation(hold["capacity_reservation_id"])["state"] == "released"
    replay = _issue(
        service,
        negotiation_id="neg-expired",
        quantity=200,
        key_mode="new",
        capacity_reservation_id="missing-replacement-hint",
        **BUYER,
    )
    assert replay["request_digest"] == issued["request_digest"]
    assert replay["already_issued"] and replay["balance"] == 200
    assert ledger.snapshot()[0]["available_units"] == 800


def test_issue_quota_exhausted_persists_nothing(service, ledger):
    with pytest.raises(IssuanceError) as exc:
        _issue(service, negotiation_id="0xbig", quantity=2000, key_mode="new", **BUYER)
    assert exc.value.reason == "quota_exhausted"
    missing_key_id = derive_key_id(CONFIG.key_prefix, fulfillment_id(LABEL, "0xbig"))
    assert service.get_key(missing_key_id) is None
    assert service.list_grants(missing_key_id) == []
    assert ledger.snapshot()[0]["available_units"] == 1000


def test_consume_decrements_with_402_and_idempotency(service):
    new = _issue(service, negotiation_id="0xc1", quantity=3, key_mode="new", **BUYER)
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
    a = _issue(service, negotiation_id="0xb1", quantity=5, key_mode="new", **BUYER)
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


def test_a_top_up_onto_a_revoked_key_is_refused_without_a_grant(service, ledger):
    new = _issue(service, negotiation_id="0xr1", quantity=4, key_mode="new", **BUYER)
    service.revoke(new["key_id"])
    before = ledger.snapshot()[0]["available_units"]

    with pytest.raises(IssuanceError) as refused:
        _issue(service, negotiation_id="0xr2", quantity=2, key_mode="existing", key_id=new["key_id"], **BUYER)

    assert refused.value.reason == "key_revoked"
    assert service.get_key(new["key_id"])["balance"] == 4
    assert len(service.list_grants(new["key_id"])) == 1
    assert ledger.snapshot()[0]["available_units"] == before


def test_verify_checks_secret_and_status(service):
    new = _issue(service, negotiation_id="0xv1", quantity=1, key_mode="new", **BUYER)
    key_id, secret = new["key_id"], new["secret"]

    assert service.verify(key_id=key_id, secret=secret)["valid"] is True
    assert service.verify(key_id=key_id, secret="wrong")["valid"] is False
    assert service.verify(key_id="ak_missing", secret=secret)["valid"] is False

    service.revoke(key_id)
    after = service.verify(key_id=key_id, secret=secret)
    assert after["valid"] is False and after["status"] == "revoked"


def test_adjust_records_grant_and_refuses_negative_balance(service):
    new = _issue(service, negotiation_id="0xa1", quantity=10, key_mode="new", **BUYER)
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
    assert grants[0]["negotiation_id"] == "0xa1" and grants[1]["negotiation_id"] is None


def test_usage_log_pages_by_event_id(service):
    new = _issue(service, negotiation_id="0xu1", quantity=10, key_mode="new", **BUYER)
    for i in range(4):
        service.consume(key_id=new["key_id"], amount=1, idempotency_key=f"r{i}")
    events = service.list_usage(new["key_id"])
    assert len(events) == 4
    page = service.list_usage(new["key_id"], after_id=events[1]["id"], limit=2)
    assert [e["idempotency_key"] for e in page] == ["r2", "r3"]


# The profile replaces every offering-mode literal.


def _issue_under(config, service, negotiation_id, *, capacity_reservation_id=None):
    owner = Identity(scheme=IdentityScheme("eip191"), identifier=BUYER["buyer_id"])
    request = issuance_request(
        config.label, negotiation_id=negotiation_id, owner=owner, service="svc",
        resource_id="svc-quota", quantity=5, key=KeyDisposition(mode="new"),
    )
    return service.issue(
        fulfillment_id=request.fulfillment_id, negotiation_id=negotiation_id,
        owner_scheme=owner.scheme.value, owner_id=owner.identifier, service="svc",
        resource_id="svc-quota", quantity=5, key_mode="new", key_id=None,
        request_digest=request.request_digest, capacity_reservation_id=capacity_reservation_id,
    )


def test_a_reservation_under_the_profiles_mode_is_committed_and_another_mode_refused():
    config = config_for("inference")
    ledger, service, _ = _composed(config)

    hold = ledger.reserve(
        claim={"offering_mode": "inference", "units": 5},
        deal_ref={"negotiation_id": "neg-own-mode"},
        ttl_seconds=900,
    )
    issued = _issue_under(config, service, "neg-own-mode", capacity_reservation_id=hold["capacity_reservation_id"])
    assert issued["capacity_reservation_id"] == hold["capacity_reservation_id"]
    assert ledger.get_reservation(hold["capacity_reservation_id"])["state"] == "leased"

    # The seeded pool declares only the profile's mode, so the other mode is refused at admission.
    with pytest.raises(UndeclaredOfferingModeError):
        ledger.reserve(
            claim={"offering_mode": "api_credits", "units": 5},
            deal_ref={"negotiation_id": "neg-other-mode"},
            ttl_seconds=900,
        )


def test_a_hold_under_another_mode_conflicts_with_the_purchase():
    config = config_for("inference")
    ledger, service, _ = _composed(config)
    hold = ledger.reserve(
        claim={"offering_mode": "inference", "units": 5},
        deal_ref={"negotiation_id": "neg-other"},
        ttl_seconds=900,
    )
    with pytest.raises(IssuanceError) as refused:
        _issue_under(config, service, "neg-purchase", capacity_reservation_id=hold["capacity_reservation_id"])
    assert refused.value.reason == "fulfillment_conflict"


def test_a_fresh_reservation_claims_the_profiles_mode_and_the_result_carries_its_label():
    config = config_for("inference")
    ledger, service, _ = _composed(config)
    issued = _issue_under(config, service, "neg-fresh")
    reservation = ledger.get_reservation(issued["capacity_reservation_id"])
    assert reservation["offering_mode"] == "inference"
    assert issued["schema"] == config.label.issuance_result_schema
    assert issued["key_id"].startswith(f"{config.key_prefix}_")
