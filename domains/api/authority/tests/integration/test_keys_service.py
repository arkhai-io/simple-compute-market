"""KeysService: issuance idempotency, ownership re-check, consume/verify."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from arkhai_api.issuance import KeyDisposition, accepted_terms_digest, fulfillment_id, issuance_request
from arkhai_api_authority import IssuanceError, KeysService, derive_key_id, initialize, migrate_database
from market_identity import Identity, IdentityScheme
from market_resource_pools import ResourcePoolFacts
from market_site.ledger import CapacityLedgerService, UndeclaredOfferingModeError

from tests.integration.profiles import CHAIN, CONFIG, LABEL, PROFILE, config_for

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
    accepted_terms: dict | None = None,
    request_charge: int | None = None,
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
        **_terms(accepted_terms, request_charge),
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
        accepted_terms=request.accepted_terms,
        terms_digest=request.terms_digest,
        request_charge=request.request_charge,
    )


def _terms(accepted_terms: dict | None, request_charge: int | None) -> dict:
    if accepted_terms is None:
        return {}
    return {
        "accepted_terms": accepted_terms,
        "terms_digest": accepted_terms_digest(accepted_terms),
        "request_charge": request_charge,
    }


def _composed(config=CONFIG) -> tuple[CapacityLedgerService, KeysService, object]:
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    migrate_database(engine, CHAIN)
    initialize(engine, config.profile)
    session_factory = sessionmaker(bind=engine)
    ledger = CapacityLedgerService(session_factory, pool_facts=ResourcePoolFacts())
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


# Accepted terms and key scope

TERMS = {"attestation": None, "rate_card": {"asset": "USD/6", "request_credits": 1}}
REPRICED = {"attestation": None, "rate_card": {"asset": "USD/6", "request_credits": 10}}


def _pinned_key(service, negotiation_id="0xp1", **overrides):
    fields = {"accepted_terms": TERMS, "request_charge": 1, **overrides}
    return _issue(service, negotiation_id=negotiation_id, quantity=10, key_mode="new", **BUYER, **fields)


def _secret_of(result) -> str:
    return result["secret"]


def test_a_pinned_issuance_stores_its_terms_and_its_result_carries_none(service):
    pinned = _pinned_key(service)
    unpinned = _issue(service, negotiation_id="0xu1", quantity=10, key_mode="new", **BUYER)

    assert set(pinned) == set(unpinned)
    assert not {"accepted_terms", "terms_digest", "request_charge"} & set(pinned)
    grant = service.list_grants(pinned["key_id"])[0]
    assert (grant["accepted_terms"], grant["terms_digest"], grant["request_charge"]) == (
        TERMS, accepted_terms_digest(TERMS), 1,
    )
    assert "accepted_terms" not in service.list_grants(unpinned["key_id"])[0]


def test_verify_returns_a_pinned_keys_terms_and_nothing_for_an_unpinned_key(service):
    pinned = _pinned_key(service)
    unpinned = _issue(service, negotiation_id="0xu1", quantity=10, key_mode="new", **BUYER)

    verified = service.verify(key_id=pinned["key_id"], secret=_secret_of(pinned))
    assert verified == {
        "valid": True, "status": "active", "balance": 10,
        "accepted_terms": TERMS, "terms_digest": accepted_terms_digest(TERMS), "request_charge": 1,
    }
    assert service.verify(key_id=unpinned["key_id"], secret=_secret_of(unpinned)) == {
        "valid": True, "status": "active", "balance": 10,
    }


def test_a_terms_digest_that_does_not_match_its_payload_is_refused(service, ledger):
    with pytest.raises(IssuanceError) as exc:
        service.issue(
            fulfillment_id=fulfillment_id(LABEL, "0xbad"), negotiation_id="0xbad",
            owner_scheme=BUYER["buyer_scheme"], owner_id=BUYER["buyer_id"],
            service="test-service", resource_id="svc-quota", quantity=1, key_mode="new",
            request_digest="sha256:" + "0" * 64, accepted_terms=TERMS,
            terms_digest="sha256:" + "1" * 64, request_charge=1,
        )
    assert exc.value.reason == "terms_digest_mismatch"
    assert ledger.snapshot()[0]["available_units"] == 1000


@pytest.mark.parametrize(
    "changed",
    [
        {"issuance_service": "other-service"},
        {"resource_id": "other-quota"},
        {"accepted_terms": REPRICED, "request_charge": 10},
        {"accepted_terms": None, "request_charge": None},
    ],
    ids=["service", "resource", "terms", "unpinned"],
)
def test_a_top_up_outside_the_first_grants_scope_is_refused_and_changes_nothing(service, ledger, changed):
    key = _pinned_key(service)
    fields = {"accepted_terms": TERMS, "request_charge": 1, **changed}

    with pytest.raises(IssuanceError) as exc:
        _issue(service, negotiation_id="0xp2", quantity=5, key_mode="existing", key_id=key["key_id"], **BUYER, **fields)

    assert exc.value.reason == "key_out_of_scope"
    assert len(service.list_grants(key["key_id"])) == 1
    assert service.get_key(key["key_id"])["balance"] == 10
    assert ledger.snapshot()[0]["available_units"] == 990


def test_a_top_up_inside_the_scope_is_granted(service):
    key = _pinned_key(service)
    topped = _issue(service, negotiation_id="0xp2", quantity=5, key_mode="existing", key_id=key["key_id"], **BUYER, accepted_terms=TERMS, request_charge=1)
    assert topped["balance"] == 15


def test_an_unpinned_key_admits_only_unpinned_top_ups(service):
    key = _issue(service, negotiation_id="0xu1", quantity=10, key_mode="new", **BUYER)
    assert _issue(service, negotiation_id="0xu2", quantity=5, key_mode="existing", key_id=key["key_id"], **BUYER)["balance"] == 15
    with pytest.raises(IssuanceError) as exc:
        _issue(service, negotiation_id="0xu3", quantity=5, key_mode="existing", key_id=key["key_id"], **BUYER, accepted_terms=TERMS, request_charge=1)
    assert exc.value.reason == "key_out_of_scope"


def test_a_replay_with_other_terms_conflicts(service):
    _pinned_key(service)
    with pytest.raises(IssuanceError) as exc:
        _pinned_key(service, accepted_terms=REPRICED, request_charge=10)
    assert exc.value.reason == "fulfillment_conflict"
    assert _pinned_key(service)["already_issued"] is True


@pytest.mark.parametrize(
    "scope",
    [{"service": "other-service"}, {"resource_id": "other-quota"}, {"service": "other-service", "resource_id": "svc-quota"}],
)
def test_verify_and_consume_outside_the_keys_scope_refuse_uncharged(service, scope):
    key = _pinned_key(service)

    assert service.verify(key_id=key["key_id"], secret=_secret_of(key), **scope) == {
        "valid": False, "status": "key_out_of_scope", "balance": 0,
    }
    assert service.consume(key_id=key["key_id"], amount=1, **scope) == {
        "ok": False, "reason": "key_out_of_scope", "balance": 0,
    }
    assert service.get_key(key["key_id"])["balance"] == 10
    assert service.list_usage(key["key_id"]) == []


def test_a_batched_consume_is_scoped_per_item(service):
    key = _pinned_key(service)
    inside = {"service": "test-service", "resource_id": "svc-quota"}

    results = service.consume_batch(
        [
            {"key_id": key["key_id"], "amount": 1, "idempotency_key": "b1", "service": "other-service"},
            {"key_id": key["key_id"], "amount": 1, "idempotency_key": "b2", **inside},
            {"key_id": key["key_id"], "amount": 1, "idempotency_key": "b3", "resource_id": "other-quota"},
            {"key_id": key["key_id"], "amount": 1, "idempotency_key": "b4"},
        ]
    )

    assert results == [
        {"ok": False, "reason": "key_out_of_scope", "balance": 0},
        {"ok": True, "consumed": 1, "balance": 9},
        {"ok": False, "reason": "key_out_of_scope", "balance": 0},
        {"ok": True, "consumed": 1, "balance": 8},
    ]
    assert len(service.list_usage(key["key_id"])) == 2


def test_verify_and_consume_inside_or_without_a_scope_admit_and_charge(service):
    key = _pinned_key(service)
    scope = {"service": "test-service", "resource_id": "svc-quota"}

    assert service.verify(key_id=key["key_id"], secret=_secret_of(key), **scope)["valid"] is True
    assert service.consume(key_id=key["key_id"], amount=1, **scope) == {"ok": True, "consumed": 1, "balance": 9}
    assert service.consume(key_id=key["key_id"], amount=1) == {"ok": True, "consumed": 1, "balance": 8}
    assert service.verify(key_id=key["key_id"], secret="wrong", **scope) == {
        "valid": False, "status": "active", "balance": 8,
    }


# A pinned key's charge


def test_a_pinned_key_charged_another_amount_is_refused_carrying_its_unchanged_balance(service):
    key = _pinned_key(service)

    assert service.consume(key_id=key["key_id"], amount=2) == {
        "ok": False, "reason": "charge_mismatch", "balance": 10,
    }
    assert service.get_key(key["key_id"])["balance"] == 10
    assert service.list_usage(key["key_id"]) == []


def test_a_mismatch_beyond_the_balance_is_a_mismatch_not_insufficient_credits(service):
    key = _pinned_key(service)

    assert service.consume(key_id=key["key_id"], amount=11) == {
        "ok": False, "reason": "charge_mismatch", "balance": 10,
    }


def test_a_key_refusal_precedes_a_mismatch(service):
    key = _pinned_key(service)

    assert service.consume(key_id=key["key_id"], amount=2, service="other-service") == {
        "ok": False, "reason": "key_out_of_scope", "balance": 0,
    }
    service.revoke(key["key_id"])
    assert service.consume(key_id=key["key_id"], amount=2) == {
        "ok": False, "reason": "key_revoked", "balance": 10,
    }


def test_a_request_repeated_at_another_amount_is_a_mismatch_not_a_duplicate(service):
    key = _pinned_key(service)
    assert service.consume(key_id=key["key_id"], amount=1, idempotency_key="r1")["ok"] is True

    assert service.consume(key_id=key["key_id"], amount=2, idempotency_key="r1") == {
        "ok": False, "reason": "charge_mismatch", "balance": 9,
    }
    assert service.consume(key_id=key["key_id"], amount=1, idempotency_key="r1") == {
        "ok": True, "consumed": 0, "duplicate": True, "balance": 9,
    }


def test_a_batch_refuses_its_mismatched_item_in_place_and_applies_the_others(service):
    key = _pinned_key(service)

    results = service.consume_batch(
        [
            {"key_id": key["key_id"], "amount": 1, "idempotency_key": "b1"},
            {"key_id": key["key_id"], "amount": 3, "idempotency_key": "b2"},
            {"key_id": key["key_id"], "amount": 1, "idempotency_key": "b3"},
        ]
    )

    assert results == [
        {"ok": True, "consumed": 1, "balance": 9},
        {"ok": False, "reason": "charge_mismatch", "balance": 9},
        {"ok": True, "consumed": 1, "balance": 8},
    ]
    assert len(service.list_usage(key["key_id"])) == 2


def test_an_unpinned_key_is_charged_the_amount_sent(service):
    key = _issue(service, negotiation_id="0xu1", quantity=10, key_mode="new", **BUYER)

    assert service.consume(key_id=key["key_id"], amount=3) == {"ok": True, "consumed": 3, "balance": 7}
    assert service.consume(key_id=key["key_id"], amount=1) == {"ok": True, "consumed": 1, "balance": 6}
