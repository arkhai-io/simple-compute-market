"""Canonical options through signed review/finalization and durable recipient intents."""
from __future__ import annotations

import sqlite3
import uuid

import pytest
from market_contact_exchange.delivery_client import ContactDeliveryClient, REVIEW_ROUTE
from market_contact_exchange.delivery_contract import IntroductionFinalize, IntroductionReview
from market_contact_exchange.delivery_runtime import ContactDeliveryWorker
from market_contact_exchange import IntroductionAdminClient
from market_contact_exchange.fixtures.delivery import DELIVERY_CONFIG, POLICY
from market_core.schemas import derive_settlement_option_id
from market_settlement_runtime import SettlementPublicationClause
from market_identity import TrustedIdentitySet
from storefront_client import StorefrontClient, StorefrontClientError
from test_http_introductions import (
    BUYER_SIGNER, OUTSIDER_SIGNER, SELLER_SIGNER,
    _accept_typed, _admin, _app, _insert_contact_listing, _introductions, _negotiate_contact, _runtime,
)
from loopback import serving


def client(base_url, signer=BUYER_SIGNER, role="buyer"):
    return StorefrontClient(base_url, signer=signer, caller_role=role,
        expected_publishers=TrustedIdentitySet(identities=(SELLER_SIGNER.identity,)))


@pytest.mark.parametrize("seller_unknown", [False, True])
async def test_explicit_contact_uses_native_option_and_both_owned_routes(tmp_path, seller_unknown):
    path = str(tmp_path / "contacts.db")
    contact = {"delivery": DELIVERY_CONFIG, "profiles": {
        "default": {"channel": "email", "terms": "Introduction only; USD 0.80 per hour asking rate, no reservation.", "delivery_policy": POLICY}}}
    runtime = _runtime(path, contact=contact)
    payload = await runtime.settlement_composition.publication_payload(
        candidate={"site_id": "site-a"}, clauses=[SettlementPublicationClause(
            mechanism="contact-exchange.v1", asset="introduction", mechanism_input={"profile": "default"})])
    option, = payload.settlement_options
    assert set(option) == {"option_id", "settlement"}
    assert option["option_id"] == derive_settlement_option_id(settlement=option["settlement"])
    assert option["settlement"]["delivery_policy"] == POLICY
    assert payload.accepted_escrows == ()
    assert "price" not in option and "rates" not in option
    await _insert_contact_listing(runtime, option=option)
    with serving(_app(runtime)) as base_url:
        negotiation, ref = await _accept_typed(base_url, option)
        with pytest.raises(RuntimeError, match="409"):
            _introductions(base_url).start(negotiation_id=negotiation, obligation_ref=ref, contact_payload={"name": "Buyer"})
        request = IntroductionReview(schema_version=2, negotiation_id=negotiation, obligation_ref=ref,
            finalization_id=str(uuid.uuid4()), contact_payload={"text": "Buyer approved whole text"},
            delivery_route={"kind": "email", "address": "buyer-owned@example.invalid"})
        # Rejection path: the typed review model cannot construct an unknown private field.
        async with client(base_url) as transport:
            with pytest.raises(StorefrontClientError) as malformed:
                await transport.authenticated_request("POST", REVIEW_ROUTE, role="buyer",
                    operation="introduction_review", resource=ref,
                    body={**request.model_dump(mode="json"), "private_canary": "DO-NOT-ECHO-PRIVATE-INPUT"})
            assert malformed.value.status_code == 422
            assert "DO-NOT-ECHO-PRIVATE-INPUT" not in str(malformed.value)
        async with client(base_url, OUTSIDER_SIGNER) as outsider:
            with pytest.raises(StorefrontClientError) as denied:
                await ContactDeliveryClient(outsider).review(request)
            assert denied.value.status_code == 403
        async with client(base_url) as transport:
            delivery = ContactDeliveryClient(transport)
            review_request_id = str(uuid.uuid4())
            review = await delivery.review(request, request_id=review_request_id)
            with pytest.raises(StorefrontClientError) as repeated_review:
                await delivery.review(request, request_id=review_request_id)
            assert repeated_review.value.status_code == 409
            assert review["delivery_policy"] == POLICY
            assert review["introduction"] == {
                "option_id": option["option_id"], "listing_id": "intro-listing",
                "profile": "default", "channel": "email", "terms": option["settlement"]["terms"],
                "delivery_policy": POLICY,
            }
            finalize = IntroductionFinalize(**request.model_dump(), review_token=review["review_token"], consent="exchange-contacts-and-deliver.v1")
            finalize_request_id = str(uuid.uuid4())
            result = await delivery.finalize(finalize, request_id=finalize_request_id)
            assert result["finalization"]["status"] == "committed"
            assert result["counterparty_contact"] == {"telegram": "@capacity_broker"}
            assert (await delivery.read_finalization(ref, request.finalization_id))["status"] == "committed"
            assert (await delivery.finalize(finalize, request_id=finalize_request_id))["finalization"]["status"] == "committed"
            assert (await delivery.read_delivery(ref))["status"] == "pending"
            sent = []
            async def send(record, role, route, intent, attempt, deadline):
                sent.append((role, route["address"], record))
                return ("needs_review", "acceptance_unknown") if seller_unknown and role == "seller" else ("accepted", None)
            worker = ContactDeliveryWorker(transaction=runtime.contact_exchange.store.transaction,
                prepare=runtime.contact_exchange.prepare_delivery, complete=runtime.contact_exchange.complete_delivery, send=send)
            await worker.tick()
            await worker.tick()
            assert len(sent) == 2
            assert {(role, address) for role, address, _ in sent} == {
                ("buyer", "buyer-owned@example.invalid"), ("seller", "seller-route@example.invalid")}
            assert (await delivery.read_delivery(ref))["status"] == "accepted"
        async with client(base_url, SELLER_SIGNER, "seller") as seller:
            assert (await ContactDeliveryClient(seller).read_delivery(ref, role="seller"))["status"] == ("needs_review" if seller_unknown else "accepted")
        with sqlite3.connect(path) as conn:
            assert conn.execute("SELECT COUNT(*) FROM contact_finalizations WHERE status='committed'").fetchone()[0] == 1
            assert conn.execute("SELECT COUNT(*) FROM contact_delivery_intents").fetchone()[0] == 2
            assert conn.execute("SELECT COUNT(*) FROM contact_delivery_intents WHERE route IS NOT NULL").fetchone()[0] == 0
            retained = "\n".join(row[0] or "" for row in conn.execute("SELECT response_body FROM auth_replay_reservations"))
            assert all(value not in retained for value in (
                review["review_token"], "@capacity_broker", "Buyer approved whole text",
                "buyer-owned@example.invalid", "seller-route@example.invalid"))

    disabled = _runtime(path, contact=contact, contact_enabled=False)
    assert disabled.contact_delivery_worker is not None
    with serving(_app(disabled)) as base_url:
        async with client(base_url) as transport:
            delivery = ContactDeliveryClient(transport)
            assert (await delivery.read_finalization(ref, request.finalization_id))["status"] == "committed"
            assert (await delivery.finalize(finalize))["finalization"]["status"] == "committed"
            assert (await delivery.read_delivery(ref))["status"] == "accepted"
        async with client(base_url, SELLER_SIGNER, "seller") as seller:
            assert (await ContactDeliveryClient(seller).read_delivery(ref, role="seller"))["status"] == ("needs_review" if seller_unknown else "accepted")


@pytest.mark.parametrize("modern", [False, True])
async def test_private_retries_follow_deletion_and_store_only_metadata(tmp_path, modern):
    from market_contact_exchange import IntroductionAdminClient
    from test_http_introductions import _admin

    path = str(tmp_path / "private.db")
    contact = {"delivery": DELIVERY_CONFIG, "profiles": {"default": {
        "channel": "email", "terms": "Synthetic introduction",
        **({"delivery_policy": POLICY} if modern else {}),
    }}}
    runtime = _runtime(path, contact=contact)
    payload = await runtime.settlement_composition.publication_payload(
        candidate={"site_id": "site-a"}, clauses=[SettlementPublicationClause(
            mechanism="contact-exchange.v1", asset="introduction",
            mechanism_input={"profile": "default"})])
    option, = payload.settlement_options
    await _insert_contact_listing(runtime, option=option)
    with serving(_app(runtime)) as base_url:
        negotiation, ref = await _accept_typed(base_url, option)
        async with client(base_url) as transport:
            body = {"negotiation_id": negotiation, "obligation_ref": ref,
                    "contact_payload": {"name": "synthetic-private-buyer"}}
            token = None
            if modern:
                review_request = IntroductionReview(**body, schema_version=2,
                    finalization_id=str(uuid.uuid4()),
                    delivery_route={"kind": "email", "address": "buyer@example.invalid"})
                delivery = ContactDeliveryClient(transport)
                review = await delivery.review(review_request, request_id="private-review")
                token = review["review_token"]
                with sqlite3.connect(path) as conn:
                    stored = str(conn.execute("SELECT response_body FROM auth_replay_reservations").fetchall())
                assert token not in stored
                with pytest.raises(StorefrontClientError) as retried_review:
                    await delivery.review(review_request, request_id="private-review")
                assert retried_review.value.status_code == 409
                body = IntroductionFinalize(**review_request.model_dump(), review_token=token,
                    consent="exchange-contacts-and-deliver.v1").model_dump(mode="json")

            async def start(payload=body):
                return await transport.authenticated_request("POST", "/api/v1/introductions",
                    role="buyer", operation="introduction_start", resource=ref,
                    body=payload, request_id="private-start")

            async def read():
                return await transport.authenticated_request("GET", f"/api/v1/introductions/{ref}",
                    role="buyer", operation="introduction_read", resource=ref,
                    request_id="private-read")

            first = await start()
            assert (await start())["counterparty_contact"] == first["counterparty_contact"]
            assert (await read())["counterparty_contact"] == first["counterparty_contact"]
            async with client(base_url) as other_transport:
                with pytest.raises(StorefrontClientError) as changed:
                    await other_transport.authenticated_request(
                        "POST", "/api/v1/introductions", role="buyer",
                        operation="introduction_start", resource=ref,
                        body={**body, "contact_payload": {"name": "changed"}},
                        request_id="private-start")
                assert changed.value.status_code == 409
            async with _admin(base_url) as admin:
                await IntroductionAdminClient(admin).delete_introduction_payloads(ref)
            for retry in (start, read):
                with pytest.raises(StorefrontClientError) as deleted:
                    await retry()
                assert deleted.value.status_code == 410
                assert "introduction_payloads_deleted" in str(deleted.value)
                assert "capacity_broker" not in str(deleted.value)
            with sqlite3.connect(path) as conn:
                replay = str(conn.execute("SELECT response_body FROM auth_replay_reservations").fetchall())
                assert "capacity_broker" not in replay
                assert "synthetic-private-buyer" not in replay
                assert token is None or token not in replay
                assert conn.execute("SELECT COUNT(*) FROM contact_introductions").fetchone()[0] == 1
                assert conn.execute("SELECT buyer_contact,seller_contact FROM contact_introductions").fetchone() == ("{}", "{}")


@pytest.mark.parametrize("prior_state", ["accepted", "reviewed", "unknown"])
async def test_removed_profile_policy_stops_new_delivery_and_preserves_accepted_work(tmp_path, prior_state):
    path = str(tmp_path / "policy-rollback.db")
    profile = {"channel": "email", "terms": "Synthetic introduction"}
    modern = {"delivery": DELIVERY_CONFIG, "profiles": {"default": {**profile, "delivery_policy": POLICY}}}
    legacy = {"delivery": DELIVERY_CONFIG, "profiles": {"default": profile}}
    runtime = _runtime(path, contact=modern)
    clauses = [SettlementPublicationClause(mechanism="contact-exchange.v1", asset="introduction",
                                           mechanism_input={"profile": "default"})]
    payload = await runtime.settlement_composition.publication_payload(candidate={"site_id": "site-a"}, clauses=clauses)
    option, = payload.settlement_options
    await _insert_contact_listing(runtime, option=option)
    calls = []

    async def unknown_send(*args):
        calls.append(args)
        return "needs_review", "acceptance_unknown"

    def worker(current):
        return ContactDeliveryWorker(transaction=current.contact_exchange.store.transaction,
            prepare=current.contact_exchange.prepare_delivery, complete=current.contact_exchange.complete_delivery,
            send=unknown_send)

    with serving(_app(runtime)) as base_url:
        negotiation, ref = await _accept_typed(base_url, option)
        if prior_state != "accepted":
            async with client(base_url) as transport:
                delivery = ContactDeliveryClient(transport)
                review_request = IntroductionReview(schema_version=2, negotiation_id=negotiation,
                    obligation_ref=ref, finalization_id=str(uuid.uuid4()), contact_payload={"name": "Synthetic buyer"},
                    delivery_route={"kind": "email", "address": "buyer@example.invalid"})
                review = await delivery.review(review_request)
                finalization = IntroductionFinalize(**review_request.model_dump(), review_token=review["review_token"],
                    consent="exchange-contacts-and-deliver.v1")
                if prior_state == "unknown":
                    await delivery.finalize(finalization)
            if prior_state == "unknown":
                await worker(runtime).tick()
                assert len(calls) == 2

    restored = _runtime(path, contact=legacy)
    assert restored.contact_delivery_worker is not None
    assert restored.settlement_composition.enabled_mechanisms == ("contact-exchange.v1",)
    with serving(_app(restored)) as base_url:
        # The old signed option remains in durable listing state. A current
        # seller profile no longer authorizes its explicit delivery policy.
        with pytest.raises(StorefrontClientError) as stale:
            await _negotiate_contact(base_url, option)
        assert stale.value.status_code == 409
        async with client(base_url) as transport:
            delivery = ContactDeliveryClient(transport)
            if prior_state == "accepted":
                review_request = IntroductionReview(schema_version=2, negotiation_id=negotiation,
                    obligation_ref=ref, finalization_id=str(uuid.uuid4()), contact_payload={"name": "Synthetic buyer"},
                    delivery_route={"kind": "email", "address": "buyer@example.invalid"})
                review = await delivery.review(review_request)
                finalization = IntroductionFinalize(**review_request.model_dump(), review_token=review["review_token"],
                    consent="exchange-contacts-and-deliver.v1")
            result = await delivery.finalize(finalization)
            assert result["finalization"]["status"] == "committed"
            assert result["introduction"]["delivery_policy"] == POLICY
            assert (await delivery.read_finalization(ref, review_request.finalization_id))["status"] == "committed"
            await worker(restored).tick()
            assert len(calls) == 2
            assert (await delivery.read_delivery(ref))["status"] == "needs_review"
            await worker(restored).tick()
            assert len(calls) == 2
        replacement = await restored.settlement_composition.publication_payload(candidate={"site_id": "site-a"}, clauses=clauses)
        legacy_option, = replacement.settlement_options
        assert "delivery_policy" not in legacy_option["settlement"]
        assert legacy_option["option_id"] != option["option_id"]
        await _insert_contact_listing(restored, option=legacy_option)
        await _accept_typed(base_url, legacy_option)
    with sqlite3.connect(path) as conn:
        assert conn.execute("SELECT COUNT(*) FROM contact_delivery_intents WHERE obligation_ref=? AND status='needs_review' AND route IS NULL", (ref,)).fetchone()[0] == 2
