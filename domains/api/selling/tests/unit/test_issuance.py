"""Issuance from verified evidence, under a neutral domain's bundle."""

from __future__ import annotations

import json

import pytest
from arkhai_api.issuance import IssuanceRequest, fulfillment_id, issuance_result_model
from arkhai_api_client import AuthorityError
from market_core import SettlementEvidence

from arkhai_api_selling.issuance import (
    MissingQuotaResource,
    connection_payload,
    delivery,
    fulfill,
    fulfill_from_hold,
    issuance_subject,
    persist_delivery,
    prepare_issuance_request,
    settlement_evidence,
)
from tests.bundles import BUYER, CLAIMANT, EXAMPLE, accepted_agreement, with_extension

IssuanceResult = issuance_result_model(EXAMPLE.label)
LISTING = {"product": "alpha", "quota": "quota-a", "url": "https://alpha.example"}


def _evidence(
    reference: str = "neg-1",
    *,
    quantity: int = 3,
    status: str = "verified",
    listing: dict | None = None,
    kind: str = EXAMPLE.settlement_evidence_kind,
) -> SettlementEvidence:
    return SettlementEvidence(
        reference, "opaque.future.v1", reference, status,
        {"kind": kind, "schema_version": 1, "agreement_digest": "a" * 64,
         "source": {"verified_source": "fixture"},
         "delivery": {"owner": BUYER.model_dump(mode="json"),
                      "listing_resource": dict(LISTING if listing is None else listing),
                      "quantity": quantity, "key_mode": "new", "key_id": None,
                      "listing_id": "L-1"}},
    )


def _result(request: IssuanceRequest, *, secret: str | None = "ak_new.s3cret") -> IssuanceResult:
    return IssuanceResult(
        fulfillment_id=request.fulfillment_id,
        grant_id=request.fulfillment_id,
        negotiation_id=request.negotiation_id,
        owner=request.owner,
        service=request.service,
        resource_id=request.resource_id,
        quantity=request.quantity,
        key_mode=request.key.mode,
        key_id=request.key.key_id or "ak_new",
        balance=request.quantity,
        request_digest=request.request_digest,
        committed_at_unix=1_790_000_000,
        capacity_reservation_id=request.capacity_reservation_id,
        already_issued=False,
        secret=secret,
    )


class _Authority:
    def __init__(self, issue=None):
        self.requests: list[IssuanceRequest] = []
        self._issue = issue

    async def submit_issuance(self, request):
        self.requests.append(request)
        if self._issue is not None:
            return await self._issue(request)
        return _result(request)


def _events():
    recorded = []

    def stage_event(stage, event, **fields):
        recorded.append((stage, event, fields))

    return recorded, stage_event


# The projection and its refusals


def test_the_subject_is_the_bundles_projection_of_the_listing():
    subject = issuance_subject(EXAMPLE, LISTING)
    assert (subject.service, subject.resource_id, subject.endpoint) == (
        "alpha", "quota-a", "https://alpha.example",
    )


@pytest.mark.parametrize(
    ("listing", "missing"),
    [({"product": "alpha"}, "quota resource"), ({"product": " ", "quota": "q"}, "service")],
)
def test_a_listing_naming_no_quota_resource_or_service_is_refused_by_name(listing, missing):
    with pytest.raises(MissingQuotaResource, match=f"listing 'L-9' names no {missing}"):
        issuance_subject(EXAMPLE, listing, listing_id="L-9")


def test_delivery_reads_only_the_bundles_envelope_and_requires_verification():
    assert delivery(EXAMPLE, _evidence()).quantity == 3
    with pytest.raises(ValueError, match="unsupported"):
        delivery(EXAMPLE, _evidence(kind="other.settlement-evidence.v1"))
    with pytest.raises(ValueError, match="verified"):
        delivery(EXAMPLE, _evidence(status="pending"))
    assert delivery(EXAMPLE, _evidence(status="pending"), require_verified=False)
    with pytest.raises(ValueError, match="a service and a quota resource"):
        delivery(EXAMPLE, _evidence(listing={"product": "alpha"}))


# The accepted listing


def test_evidence_records_the_listing_the_agreement_names():
    agreement, raw = accepted_agreement("L-accepted")
    accepted = settlement_evidence(
        EXAMPLE, agreement, raw, reference="ref-1", status="verified",
        source={"verified_source": "fixture"},
        order={"listing_resource": LISTING},
    )

    recorded = delivery(EXAMPLE, accepted)
    assert recorded.listing_id == "L-accepted"
    assert recorded.listing_resource == {**LISTING, "offering_mode": None}
    assert accepted.evidence["kind"] == "example.settlement-evidence.v1"


async def test_issuance_reads_the_listing_recorded_in_the_evidence():
    agreement, raw = accepted_agreement("L-accepted")
    accepted = settlement_evidence(
        EXAMPLE, agreement, raw, reference="ref-1", status="verified",
        source={"verified_source": "fixture"},
        order={"listing_resource": LISTING},
    )
    authority = _Authority()

    await fulfill(EXAMPLE, evidence=accepted, credits_client=authority, stage_event=_events()[1])

    (request,) = authority.requests
    assert (request.service, request.resource_id) == ("alpha", "quota-a")
    assert request.fulfillment_id == fulfillment_id(EXAMPLE.label, "neg-accepted")


def test_the_request_is_built_under_the_bundles_label():
    request = prepare_issuance_request(EXAMPLE, evidence=_evidence(), capacity_reservation_id="hold-1")
    assert request.schema == EXAMPLE.label.issuance_request_schema
    assert request.capacity_reservation_id == "hold-1"


def test_the_connection_payload_carries_the_kind_and_never_the_secret():
    subject = issuance_subject(EXAMPLE, LISTING)
    assert connection_payload(EXAMPLE, subject=subject, key_id="ak_1", quantity=2) == (
        '{"kind": "example.v1", "service_name": "alpha", '
        '"base_url": "https://alpha.example", "key_id": "ak_1", "quantity": 2}'
    )


# Issuance


async def test_issuance_returns_credentials_once_under_the_held_reservation():
    authority = _Authority()
    events, stage_event = _events()

    result = await fulfill(
        EXAMPLE,
        evidence=_evidence("neg-first"),
        credits_client=authority,
        stage_event=stage_event,
        held_reservation={"capacity_reservation_id": "alloc-7", "resource_id": "quota-a"},
    )

    assert result["status"] == "fulfilled"
    assert result["tenant_credentials"] == {
        "key_id": "ak_new", "base_url": "https://alpha.example", "balance": 3,
        "secret": "ak_new.s3cret",
    }
    payload = json.loads(result["connection_details"])
    assert (payload["key_id"], payload["quantity"]) == ("ak_new", 3)
    assert "secret" not in payload
    assert "public_extension" not in result
    assert authority.requests[0].capacity_reservation_id == "alloc-7"
    assert result["fulfillment_uid"] == authority.requests[0].fulfillment_id
    assert [event for _, event, _ in events] == ["credits_issued", "fulfilled"]


async def test_a_refusal_applies_the_failure_policy():
    async def refuse(_request):
        raise AuthorityError("quota_exhausted", "no units", status_code=409)

    events, stage_event = _events()
    policy_calls = []

    async def policy(**kwargs):
        policy_calls.append(kwargs)

    result = await fulfill(
        EXAMPLE,
        evidence=_evidence("neg-refused"),
        credits_client=_Authority(refuse),
        stage_event=stage_event,
        apply_failure_policy=policy,
        held_reservation={"capacity_reservation_id": "alloc-8"},
    )

    assert result["status"] == "error"
    assert "quota_exhausted" in result["message"]
    assert policy_calls[0]["reason"] == "quota_exhausted"
    assert policy_calls[0]["capacity_reservation_id"] == "alloc-8"
    assert policy_calls[0]["resource_id"] == "quota-a"
    assert [event for _, event, _ in events] == ["failed"]


async def test_an_unreachable_authority_stays_retryable_when_the_stage_allows():
    async def unavailable(_request):
        raise RuntimeError("credits service timed out")

    events, stage_event = _events()
    policy_calls = []

    async def policy(**kwargs):
        policy_calls.append(kwargs)

    result = await fulfill(
        EXAMPLE,
        evidence=_evidence(),
        retry_uncertain=True,
        credits_client=_Authority(unavailable),
        stage_event=stage_event,
        apply_failure_policy=policy,
    )

    assert result["status"] == "pending"
    assert not policy_calls
    assert [event for _, event, _ in events] == ["issuance_retryable"]


class _HoldStore:
    def __init__(self):
        self.deleted: list[str] = []

    async def load_capacity_hold(self, *, negotiation_id):
        return {"capacity_reservation_id": "alloc-payment", "payload": {"resource_id": "quota-a"}}

    async def delete_capacity_hold(self, *, negotiation_id):
        self.deleted.append(negotiation_id)


async def test_the_hold_row_stays_until_a_retry_completes():
    store = _HoldStore()
    attempts = []

    async def flaky(request):
        attempts.append(request)
        if len(attempts) == 1:
            raise RuntimeError("timed out")
        return _result(request)

    authority = _Authority(flaky)
    _recorded, stage_event = _events()
    kwargs = dict(evidence=_evidence("neg-payment"), db=store, credits_client=authority,
                  stage_event=stage_event, retry_uncertain=True)

    assert (await fulfill_from_hold(EXAMPLE, **kwargs))["status"] == "pending"
    assert store.deleted == []
    assert (await fulfill_from_hold(EXAMPLE, **kwargs))["status"] == "fulfilled"
    assert [request.capacity_reservation_id for request in attempts] == ["alloc-payment"] * 2
    assert store.deleted == ["neg-payment"]


# The public result


class _ProgressStore:
    db_path = ":memory:"

    def __init__(self):
        self.saved: dict = {}

    async def save_issuance_progress(self, *, negotiation_id, **fields):
        self.saved = fields
        return fields


async def test_a_domain_omitting_every_optional_contribution_delivers_with_the_defaults():
    assert (EXAMPLE.publication_guards, EXAMPLE.acceptance_hook, EXAMPLE.public_result_extension) == ((), None, None)
    result = await fulfill(EXAMPLE, evidence=_evidence(), credits_client=_Authority(_no_secret), stage_event=_events()[1])
    store = _ProgressStore()

    await persist_delivery(EXAMPLE, store, _evidence(), result, public_ref="neg-1")

    assert set(store.saved["public_result"]) == {"key_id", "base_url", "balance", "connection_details"}


async def _no_secret(request):
    return _result(request, secret=None)


async def test_a_public_result_extension_rides_beside_the_connection_payload_and_never_the_secret():
    bundle = with_extension(lambda listing, result: {"materialization": {"product": listing["product"], "grant": result.grant_id}})
    result = await fulfill(bundle, evidence=_evidence(), credits_client=_Authority(_no_secret), stage_event=_events()[1])
    store = _ProgressStore()

    await persist_delivery(bundle, store, _evidence(), result, public_ref="neg-1")

    public = store.saved["public_result"]
    assert public["materialization"]["product"] == "alpha"
    assert "connection_details" in public
    assert "secret" not in json.dumps(public)


@pytest.mark.parametrize("key", ["secret", "tenant_credentials", "key_id"])
async def test_an_extension_naming_a_private_or_existing_field_is_refused(key):
    bundle = with_extension(lambda _listing, _result: {key: "x"})

    result = await fulfill(bundle, evidence=_evidence(), credits_client=_Authority(), stage_event=_events()[1])

    assert result["status"] == "error" and "may not carry" in result["message"]


# The result answers the request


@pytest.mark.parametrize(
    ("field_name", "value"),
    [
        ("fulfillment_id", "example-fulfillment.v1:" + "f" * 64),
        ("negotiation_id", "neg-other"),
        ("owner", CLAIMANT),
        ("service", "beta"),
        ("resource_id", "quota-b"),
        ("quantity", 4),
        ("key_mode", "existing"),
        ("request_digest", "sha256:" + "e" * 64),
        ("grant_id", "example-fulfillment.v1:" + "f" * 64),
    ],
)
async def test_a_result_answering_another_request_delivers_nothing(field_name, value):
    async def other_answer(request):
        changed = {field_name: value}
        if field_name == "fulfillment_id":
            changed["grant_id"] = value
        return _result(request).model_copy(update=changed)

    events, stage_event = _events()
    policy_calls = []

    async def policy(**kwargs):
        policy_calls.append(kwargs)

    result = await fulfill(
        EXAMPLE,
        evidence=_evidence(),
        credits_client=_Authority(other_answer),
        stage_event=stage_event,
        apply_failure_policy=policy,
    )

    assert result["status"] == "error"
    assert field_name in result["message"]
    assert "tenant_credentials" not in result and "issuance" not in result
    assert not policy_calls
    assert [event for _, event, _ in events] == ["failed"]


async def test_a_replaced_hold_still_answers_the_request():
    async def fresh_reservation(request):
        return _result(request).model_copy(update={"capacity_reservation_id": "alloc-fresh"})

    result = await fulfill(
        EXAMPLE,
        evidence=_evidence(),
        credits_client=_Authority(fresh_reservation),
        stage_event=_events()[1],
        held_reservation={"capacity_reservation_id": "alloc-expired"},
    )

    assert result["status"] == "fulfilled"


async def test_an_extension_is_handed_the_result_without_its_secret():
    seen = []
    bundle = with_extension(lambda _listing, issued: seen.append(issued) or {})

    result = await fulfill(bundle, evidence=_evidence(), credits_client=_Authority(), stage_event=_events()[1])

    assert result["tenant_credentials"]["secret"] == "ak_new.s3cret"
    assert seen[0].secret is None


@pytest.mark.parametrize(
    "extension",
    [
        {"materialization": {"token": "ak_new.s3cret"}},
        {"notes": ["see", {"k": "prefix ak_new.s3cret suffix"}]},
        {"materialization": {"ak_new.s3cret": True}},
    ],
)
async def test_an_extension_carrying_the_secret_anywhere_is_refused(extension):
    result = await fulfill(EXAMPLE, evidence=_evidence(), credits_client=_Authority(), stage_event=_events()[1])
    result["public_extension"] = extension

    with pytest.raises(ValueError, match="bearer secret"):
        await persist_delivery(EXAMPLE, _ProgressStore(), _evidence(), result, public_ref="neg-1")


async def test_a_result_naming_another_existing_key_delivers_nothing():
    evidence = _evidence()
    evidence.evidence["delivery"].update(key_mode="existing", key_id="ak_mine")

    async def other_key(request):
        return _result(request, secret=None).model_copy(update={"key_id": "ak_other"})

    result = await fulfill(EXAMPLE, evidence=evidence, credits_client=_Authority(other_key), stage_event=_events()[1])

    assert result["status"] == "error" and "key_id" in result["message"]


async def test_the_hold_row_stays_when_the_grants_state_is_unknown():
    store = _HoldStore()

    async def other_answer(request):
        return _result(request).model_copy(update={"negotiation_id": "neg-other"})

    result = await fulfill_from_hold(
        EXAMPLE, evidence=_evidence(), db=store, credits_client=_Authority(other_answer),
        stage_event=_events()[1],
    )

    assert result["status"] == "error"
    assert store.deleted == []


@pytest.mark.parametrize(
    ("extension", "message"),
    [
        ({"materialization": {"token": "ak_new.s3cret"}}, "bearer secret"),
        ({"blob": b"bytes"}, "plain JSON"),
        ({"key_id": "ak_other"}, "may not carry key_id"),
    ],
)
async def test_an_unsafe_extension_is_refused_before_the_delivery_reaches_its_stage(extension, message):
    events, stage_event = _events()
    bundle = with_extension(lambda _listing, _result: extension)

    result = await fulfill(bundle, evidence=_evidence(), credits_client=_Authority(), stage_event=stage_event)

    assert result["status"] == "error" and message in result["message"]
    assert result["grant_unknown"] is True
    assert "tenant_credentials" not in result and "public_extension" not in result
    assert [event for _, event, _ in events] == ["credits_issued", "failed"]
