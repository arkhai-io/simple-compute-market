"""Whole reviewed text through signed HTTP, frozen SQLite and fake SMTP.

All contacts, routes and credentials are deterministic disposable fixtures.
They must never be used on a public network.
"""

import asyncio
import base64
import binascii
import copy
import html
import json
import sqlite3
import threading
import time
import urllib.request
import uuid
from concurrent.futures import ThreadPoolExecutor
from email.parser import BytesParser
from email.policy import default
from typing import Any
from urllib.parse import unquote

import httpx
import pytest
from arkhai_bare_metal import BareMetalProvisionTerms
from arkhai_bare_metal_storefront import delivery
from arkhai_bare_metal_storefront.contact_context import (
    context_digest,
    listing_binding_digest,
    validate_accepted_contact_context,
)
from core_buyer.negotiation_client import load_buyer_chain, negotiate_with_seller
from market_contact_exchange.delivery_contract import ContactDeliveryConfig, ContactText
from market_contact_exchange.fixtures.delivery import POLICY
from market_core.schemas import (
    SettlementPlan,
    SettlementSelection,
    derive_settlement_option_id,
)
from market_identity import TrustedIdentitySet
from market_settlement_runtime import derive_obligation_ref
from test_contact_context import DECLARATION as DECLARATION_FIXTURE
from test_contact_context import admitted
from test_contact_delivery_publication import (
    configure,
    document,
    prepare_contact_offers,
    store,
)
from test_contact_only_runtime import (
    BUYER,
    CONFIG,
    OUTSIDER,
    SELLER,
    _server,
    _signed_headers,
    _transport,
)
from test_contact_only_runtime import environment as environment
from test_http_contact_delivery import counts, finalize_body
from test_http_contact_delivery import delivery_environment as delivery_environment

SELLER_TEXT = "  SELLER-TEXT-CANARY 😀 e\u0301\n{{ untouched }} <b>plain</b> ${inert}  "
BUYER_TEXT = "  BUYER-TEXT-CANARY 世界\nContact: buyer-shared@example.invalid\nBcc: inert@example.invalid  "
BUYER_ROUTE = "buyer-route-only@example.invalid"
SELLER_ROUTE = "seller-route@example.invalid"
ACCEPTED_TERMS = {"duration_seconds": 3600, "access_method": "none"}
DECLARATION: dict[str, Any] = copy.deepcopy(DECLARATION_FIXTURE)


@pytest.fixture
def source_environment(delivery_environment, monkeypatch):
    config: dict[str, Any] = copy.deepcopy(CONFIG)
    config["contact"]["contact_payload"] = ContactText(text=SELLER_TEXT).model_dump()
    config["contact"]["profiles"]["default"].update(
        delivery_policy=POLICY,
        context_contract="accepted-listing.v1",
    )
    monkeypatch.setenv("BARE_METAL_STOREFRONT_SETTLEMENT", json.dumps(config))
    return delivery_environment


def accepted_plan_validator(option, binding, declaration, terms):
    """Retain caller expectations before negotiation, independently of its reply."""
    source = json.loads(binding.source_envelope_json)
    context = {
        "schema_version": 1,
        "discovery_schema": "vms.compute",
        "negotiation_schema": "bare_metal.v1",
        "declaration": copy.deepcopy(declaration),
        "accepted_terms": copy.deepcopy(terms),
        "option_id": option["option_id"],
        "publication_intent_digest": context_digest(source["publication_intent"]),
        "source_envelope_digest": context_digest(source),
        "listing_binding_digest": listing_binding_digest(binding),
    }
    params = copy.deepcopy(option["params"])
    package = {
        key: params[key]
        for key in (
            "profile",
            "channel",
            "terms",
            "delivery_policy",
            "context_contract",
        )
    }
    package.update(
        option_id=option["option_id"],
        listing_id=declaration["listing_id"],
        accepted_context=context,
    )
    params.update(
        payer_principal=BUYER.identity.model_dump(mode="json"),
        accepted_context_digest=context_digest(context),
    )

    def validate(plan):
        # Core checks parties, count, amount, asset, mechanism and expiry first.
        # This callback owns the remaining exact correspondence, not just hashes.
        obligation = plan.obligations[0]
        if (
            obligation.params != params
            or obligation.conditions != []
            or plan.service_terms != {"contact-exchange.v1": package}
        ):
            raise ValueError("accepted contact differs from retained selection")

    return validate


def accepted_text(url, runtime):
    option = asyncio.run(admitted(runtime))
    binding = asyncio.run(
        runtime.db.load_listing_binding(listing_id=DECLARATION["listing_id"])
    )
    validate = accepted_plan_validator(option, binding, DECLARATION, ACCEPTED_TERMS)
    return negotiate_text(url, option, validate)


def negotiate_text(url, option, validate):
    agreed = negotiate_with_seller(
        seller_url=url,
        principal=BUYER.identity,
        signer=BUYER,
        listing_id=DECLARATION["listing_id"],
        resolve_seller_principals=lambda: TrustedIdentitySet(
            identities=(SELLER.identity,)
        ),
        initial_price=None,
        max_price=None,
        unit_count=1,
        policy_params={"_selected_settlement_option": option},
        provision_terms=BareMetalProvisionTerms(payload=copy.deepcopy(ACCEPTED_TERMS)),
        settlement_selection=SettlementSelection(
            mechanism="contact-exchange.v1",
            option_id=option["option_id"],
            expiration_unix=int(time.time()) + 3600,
        ),
        chain=load_buyer_chain(policy_mode="listed_price"),
        validate_advertised_plan=validate,
    )
    assert agreed.status == "agreed"
    assert agreed.negotiation_id is not None and agreed.settlement_plan is not None
    ref = derive_obligation_ref(
        agreed.negotiation_id,
        0,
        agreed.settlement_plan.obligations[0].model_dump(mode="json"),
    )
    return {
        "schema_version": 2,
        "negotiation_id": agreed.negotiation_id,
        "obligation_ref": ref,
        "finalization_id": str(uuid.uuid4()),
        "contact_payload": ContactText(text=BUYER_TEXT).model_dump(),
        "delivery_route": {"kind": "email", "address": BUYER_ROUTE},
    }


def decoded_strings(value):
    """Inspect nested carriers and recursively decoded JSON/URL/HTML/base64 text."""
    pending, seen = [value], set()
    while pending:
        item = pending.pop()
        if isinstance(item, dict):
            pending.extend(item.keys())
            pending.extend(item.values())
        elif isinstance(item, (list, tuple)):
            pending.extend(item)
        elif isinstance(item, bytes):
            pending.append(item.decode("utf-8", errors="replace"))
        elif isinstance(item, str) and item not in seen:
            seen.add(item)
            yield item
            pending.extend((unquote(item), html.unescape(item)))
            try:
                pending.append(json.loads(item))
            except (ValueError, RecursionError):
                pass
            try:
                pending.append(
                    base64.b64decode(item, altchars=b"-_", validate=True).decode(
                        "utf-8"
                    )
                )
            except (ValueError, UnicodeError, binascii.Error):
                pass


def assert_private_absent(value, *canaries):
    for text in decoded_strings(value):
        for canary in canaries:
            assert canary not in text


def frozen_row(runtime):
    with sqlite3.connect(runtime.db.db_path) as conn:
        return conn.execute("SELECT * FROM contact_introductions").fetchone()


def withdraw_listing(runtime):
    # The accepted plan must not depend on a mutable discovery projection.
    # Direct setup models withdrawal/corruption without a real registry publication.
    with sqlite3.connect(runtime.db.db_path) as conn:
        conn.execute(
            "UPDATE listings SET status='withdrawn',offer_resource='{}',settlement_options='[]'"
        )


def change_settings(runtime):
    contact = runtime.settlement_composition.config.mechanism_config("contact")
    contact.contact_payload["text"] = "FUTURE-SELLER-TEXT-CANARY"
    profile = contact.profiles["default"]
    contact.profiles["default"] = profile.model_copy(
        update={
            "terms": "Future public terms",
            "channel": "Future channel",
        }
    )
    config = runtime.contact_delivery_config.model_dump(mode="json")
    config["seller_route"]["address"] = "future-seller-route@example.invalid"
    config["smtp"]["password"] = "FUTURE-SMTP-CANARY"
    object.__setattr__(
        runtime, "contact_delivery_config", ContactDeliveryConfig.model_validate(config)
    )


def drain(worker):
    async def run():
        await worker.tick()
        await asyncio.gather(*worker._sends)

    asyncio.run(run())


def test_review_store_render_parity_survives_withdrawal_settings_and_restart(
    source_environment,
    monkeypatch,
    caplog,
):
    sent, workers = source_environment
    rendered = []
    smtp = delivery.send_bounded_smtp

    def record_render(config, address, text, *args, **kwargs):
        rendered.append((address, text))
        return smtp(config, address, text, *args, **kwargs)

    monkeypatch.setattr(delivery, "send_bounded_smtp", record_render)
    with _server(monkeypatch) as (url, runtime):
        body = accepted_text(url, runtime)
        buyer = _transport(url, BUYER)
        review = buyer.review(body=body)
        package = review["introduction"]
        assert package["accepted_context"]["declaration"] == DECLARATION
        assert counts(runtime) == (0, 0) and sent == []
        assert_private_absent(
            review, SELLER_TEXT, BUYER_TEXT, SELLER_ROUTE, BUYER_ROUTE
        )
        # Withdrawal after acceptance but before capture must not invalidate facts.
        withdraw_listing(runtime)
        request = finalize_body(body, review)
        projection = buyer.finalize(body=request)
        assert projection["introduction"] == package
        assert projection["counterparty_contact"] == {"text": SELLER_TEXT}
        row = frozen_row(runtime)
        assert counts(runtime) == (1, 2) and sent == []
        change_settings(runtime)
        assert buyer.finalize(body=request) == projection
        assert frozen_row(runtime) == row
    with _server(monkeypatch) as (url, runtime):
        change_settings(runtime)
        buyer, seller = _transport(url, BUYER), _transport(url, SELLER)
        assert buyer.finalize(body=request) == projection
        seller_view = seller.read(obligation_ref=body["obligation_ref"])
        assert seller_view["counterparty_contact"] == body["contact_payload"]
        assert seller_view["introduction"] == package
        assert_private_absent(projection, BUYER_TEXT, BUYER_ROUTE, SELLER_ROUTE)
        assert_private_absent(seller_view, SELLER_TEXT, BUYER_ROUTE, SELLER_ROUTE)
        for method in ("read", "delivery_read"):
            with pytest.raises(RuntimeError, match="403"):
                getattr(_transport(url, OUTSIDER), method)(
                    obligation_ref=body["obligation_ref"]
                )
        with pytest.raises(RuntimeError, match="403"):
            seller.finalization_read(
                obligation_ref=body["obligation_ref"],
                finalization_id=body["finalization_id"],
            )
        drain(workers[-1])
        assert len(sent) == len(rendered) == 2
        by_route = dict(rendered)
        assert set(by_route) == {BUYER_ROUTE, SELLER_ROUTE}
        assert by_route[BUYER_ROUTE].endswith(
            "Counterparty contact:\n  text: " + SELLER_TEXT
        )
        assert by_route[SELLER_ROUTE].endswith(
            "Counterparty contact:\n  text: " + BUYER_TEXT
        )
        for text in by_route.values():
            assert f"listing_id: {DECLARATION['listing_id']}" in text
            for key, value in DECLARATION["machine_details"].items():
                assert f"{key}: {value}" in text
            assert "duration_seconds: 3600" in text and "access_method: none" in text
            assert f"terms: {package['terms']}" in text
            assert_private_absent(
                text,
                SELLER_ROUTE,
                BUYER_ROUTE,
                "FUTURE-SELLER",
                "FUTURE-SMTP",
                "Future public terms",
            )
        for address, raw in sent:
            message = BytesParser(policy=default).parsebytes(raw)
            assert (
                message.get_content_type() == "text/plain"
                and not message.is_multipart()
            )
            assert message["To"] == address and message["Bcc"] is None
            # SMTP canonicalizes line endings; compare the decoded body separately
            # from the exact pre-MIME scalar rendering pinned above.
            assert (
                message.get_content().replace("\r\n", "\n") == by_route[address] + "\n"
            )
            other_text = BUYER_TEXT if address == BUYER_ROUTE else SELLER_TEXT
            assert_private_absent(message.get_content(), other_text)
        for client in (buyer, seller):
            status = client.delivery_read(obligation_ref=body["obligation_ref"])
            assert status["status"] == "accepted"
            assert_private_absent(
                status, SELLER_TEXT, BUYER_TEXT, SELLER_ROUTE, BUYER_ROUTE
            )
        assert frozen_row(runtime) == row and counts(runtime) == (1, 2)
        with sqlite3.connect(runtime.db.db_path) as conn:
            assert (
                conn.execute(
                    "SELECT count(*) FROM contact_delivery_intents WHERE route IS NOT NULL"
                ).fetchone()[0]
                == 0
            )
        drain(workers[-1])
        assert len(sent) == 2
    assert_private_absent(
        caplog.text,
        "SELLER-TEXT-CANARY",
        "BUYER-TEXT-CANARY",
        SELLER_ROUTE,
        BUYER_ROUTE,
        "FUTURE-SMTP-CANARY",
    )


@pytest.mark.parametrize(
    "drift",
    [
        "buyer_text",
        "buyer_route",
        "seller_text",
        "seller_route",
        "profile_missing",
        "policy_removed",
    ],
)
def test_http_review_refuses_changed_disclosure_or_unavailable_config(
    source_environment, monkeypatch, drift
):
    sent, _ = source_environment
    with _server(monkeypatch) as (url, runtime):
        body = accepted_text(url, runtime)
        buyer = _transport(url, BUYER)
        request = finalize_body(body, buyer.review(body=body))
        contact = runtime.settlement_composition.config.mechanism_config("contact")
        if drift == "buyer_text":
            request["contact_payload"] = {"text": BUYER_TEXT + " "}
        elif drift == "buyer_route":
            request["delivery_route"] = {
                "kind": "email",
                "address": "changed@example.invalid",
            }
        elif drift == "seller_text":
            contact.contact_payload["text"] = SELLER_TEXT + " "
        elif drift == "seller_route":
            changed = runtime.contact_delivery_config.model_dump(mode="json")
            changed["seller_route"]["address"] = "changed@example.invalid"
            object.__setattr__(
                runtime,
                "contact_delivery_config",
                ContactDeliveryConfig.model_validate(changed),
            )
        elif drift == "profile_missing":
            contact.profiles.clear()
        else:
            contact.profiles["default"] = contact.profiles["default"].model_copy(
                update={"delivery_policy": None}
            )
        with pytest.raises(
            RuntimeError,
            match="503" if drift in {"profile_missing", "policy_removed"} else "409",
        ):
            buyer.finalize(body=request)
        assert counts(runtime) == (0, 0) and sent == []


def test_public_config_and_smtp_rotation_do_not_replace_reviewed_accepted_terms(
    source_environment, monkeypatch
):
    with _server(monkeypatch) as (url, runtime):
        body = accepted_text(url, runtime)
        buyer = _transport(url, BUYER)
        review = buyer.review(body=body)
        contact = runtime.settlement_composition.config.mechanism_config("contact")
        profile = contact.profiles["default"]
        contact.profiles["default"] = profile.model_copy(
            update={"terms": "New terms", "channel": "New channel"}
        )
        changed = runtime.contact_delivery_config.model_dump(mode="json")
        changed["smtp"]["password"] = "ROTATED-SMTP-CANARY"
        object.__setattr__(
            runtime,
            "contact_delivery_config",
            ContactDeliveryConfig.model_validate(changed),
        )
        projection = buyer.finalize(body=finalize_body(body, review))
        assert projection["introduction"] == review["introduction"]
        assert counts(runtime) == (1, 2)


@pytest.mark.parametrize("corruption", ["machine", "terms", "option"])
def test_http_refuses_forged_persisted_accepted_context(
    source_environment, monkeypatch, corruption
):
    sent, _ = source_environment
    with _server(monkeypatch) as (url, runtime):
        body = accepted_text(url, runtime)
        buyer = _transport(url, BUYER)
        request = finalize_body(body, buyer.review(body=body))
        # No public API rewrites an accepted plan; model corrupt storage directly.
        with sqlite3.connect(runtime.db.db_path) as conn:
            plan = json.loads(
                conn.execute(
                    "SELECT settlement_plan FROM negotiation_threads WHERE negotiation_id=?",
                    (body["negotiation_id"],),
                ).fetchone()[0]
            )
            context = plan["service_terms"]["contact-exchange.v1"]["accepted_context"]
            if corruption == "machine":
                context["declaration"]["machine_details"]["gpu_count"] = 99
            elif corruption == "terms":
                context["accepted_terms"]["duration_seconds"] = 7200
            else:
                context["option_id"] = "f" * 64
            conn.execute(
                "UPDATE negotiation_threads SET settlement_plan=? WHERE negotiation_id=?",
                (json.dumps(plan), body["negotiation_id"]),
            )
        with pytest.raises(RuntimeError, match="404"):
            buyer.finalize(body=request)
        assert counts(runtime) == (0, 0) and sent == []


@pytest.mark.parametrize("invalid", [0, 1, 3, True, 2.0, "2", None, "context"])
def test_http_strict_version_and_caller_context_refusal(
    source_environment, monkeypatch, invalid
):
    with _server(monkeypatch) as (url, runtime):
        body = accepted_text(url, runtime)
        if invalid == "context":
            body["accepted_context"] = {"text": "FORGED-CONTEXT-CANARY"}
        else:
            body["schema_version"] = invalid
        # Rejection-only raw HTTP probes malformed carriers before client parsing.
        response = httpx.post(
            f"{url}/api/v1/introductions/reviews",
            json=body,
            headers=_signed_headers(
                BUYER,
                "introduction_review",
                body["obligation_ref"],
                method="POST",
                body=body,
            ),
            trust_env=False,
        )
        assert response.status_code == 422
        assert response.headers["cache-control"] == "no-store"
        assert_private_absent(
            response.json(),
            BUYER_TEXT,
            SELLER_TEXT,
            BUYER_ROUTE,
            SELLER_ROUTE,
            "FORGED-CONTEXT-CANARY",
        )
        assert counts(runtime) == (0, 0)


@pytest.mark.parametrize("delayed", ["review", "finalize", "cancel"])
def test_http_cancel_fences_deterministically_ordered_requests(
    source_environment, monkeypatch, delayed
):
    sent, _ = source_environment
    entered, release = threading.Event(), threading.Event()
    with _server(monkeypatch) as (url, runtime):
        body = accepted_text(url, runtime)
        buyer = _transport(url, BUYER)
        cancel = {
            "schema_version": 2,
            "obligation_ref": body["obligation_ref"],
            "finalization_id": body["finalization_id"],
            "consent": "fence-unresolved-finalization.v1",
        }
        request = (
            body
            if delayed == "review"
            else finalize_body(body, buyer.review(body=body))
        )
        transaction = runtime.db.contact_transaction
        held = False

        async def hold_first_capture(callback):
            nonlocal held
            if not held:
                held = True
                entered.set()
                assert await asyncio.to_thread(release.wait, 5)
            return await transaction(callback)

        # Hold an authenticated request before its SQLite transaction. The second
        # request wins deterministically, then the delayed one observes its fence.
        monkeypatch.setattr(runtime.db, "contact_transaction", hold_first_capture)
        first_method = {
            "review": buyer.review,
            "finalize": buyer.finalize,
            "cancel": buyer.cancel_finalization,
        }[delayed]
        with ThreadPoolExecutor(1) as pool:
            first = pool.submit(
                first_method, body=cancel if delayed == "cancel" else request
            )
            try:
                assert entered.wait(5)
                assert counts(runtime) == (0, 0) and sent == []
                if delayed == "cancel":
                    projection = buyer.finalize(body=request)
                    assert counts(runtime) == (1, 2)
                else:
                    assert (
                        buyer.cancel_finalization(body=cancel)["status"] == "cancelled"
                    )
                    assert counts(runtime) == (0, 0)
            finally:
                release.set()
            if delayed == "cancel":
                assert first.result()["status"] == "committed"
                row = frozen_row(runtime)
                assert buyer.finalize(body=request) == projection
                assert frozen_row(runtime) == row
            else:
                with pytest.raises(RuntimeError, match="409"):
                    first.result()
                with pytest.raises(RuntimeError, match="409"):
                    buyer.review(body=body)
        status = buyer.finalization_read(
            obligation_ref=body["obligation_ref"],
            finalization_id=body["finalization_id"],
        )
        assert status["status"] == ("committed" if delayed == "cancel" else "cancelled")
        assert counts(runtime) == ((1, 2) if delayed == "cancel" else (0, 0))
        assert sent == []


def test_lost_finalize_http_ack_recovers_exact_capture_after_restart(
    source_environment, monkeypatch
):
    sent, workers = source_environment
    discarded = []
    urlopen = urllib.request.urlopen

    def lose_finalize_ack(request, *args, **kwargs):
        response = urlopen(request, *args, **kwargs)
        if request.method == "POST" and request.full_url.endswith(
            "/api/v1/introductions"
        ):
            # The real server has committed and answered; the caller receives no
            # response body or proof, as with a connection lost before HTTP ACK.
            assert response.status == 200
            response.close()
            discarded.append(True)
            raise ConnectionResetError("injected lost finalization acknowledgement")
        return response

    with _server(monkeypatch) as (url, runtime):
        body = accepted_text(url, runtime)
        buyer = _transport(url, BUYER)
        review = buyer.review(body=body)
        request = finalize_body(body, review)
        with monkeypatch.context() as failure:
            failure.setattr(urllib.request, "urlopen", lose_finalize_ack)
            with pytest.raises(
                RuntimeError, match="injected lost finalization acknowledgement"
            ):
                buyer.finalize(body=request)
        assert discarded == [True] and counts(runtime) == (1, 2) and sent == []
        row = frozen_row(runtime)
    with _server(monkeypatch) as (url, runtime):
        buyer = _transport(url, BUYER)
        status = buyer.finalization_read(
            obligation_ref=body["obligation_ref"],
            finalization_id=body["finalization_id"],
        )
        assert status["status"] == "committed"
        assert_private_absent(
            status, BUYER_TEXT, SELLER_TEXT, BUYER_ROUTE, SELLER_ROUTE
        )
        projection = buyer.finalize(body=request)
        assert projection["introduction"] == review["introduction"]
        assert projection["counterparty_contact"] == {"text": SELLER_TEXT}
        assert frozen_row(runtime) == row and counts(runtime) == (1, 2)
        drain(workers[-1])
        assert len(sent) == 2
        assert buyer.finalize(body=request) == projection
        drain(workers[-1])
        assert len(sent) == 2 and counts(runtime) == (1, 2)
        assert frozen_row(runtime) == row


@pytest.mark.parametrize(
    "substitution",
    [
        "machine",
        "declaration",
        "accepted_terms",
        "option",
        "conditions",
        "publication_digest",
        "source_digest",
        "binding_digest",
    ],
)
def test_caller_callback_refuses_self_consistent_substituted_acceptance(
    source_environment,
    monkeypatch,
    substitution,
):
    with _server(monkeypatch) as (url, runtime):
        option = asyncio.run(admitted(runtime))
        binding = asyncio.run(
            runtime.db.load_listing_binding(listing_id=DECLARATION["listing_id"])
        )
        declaration, terms = copy.deepcopy(DECLARATION), copy.deepcopy(ACCEPTED_TERMS)
        validate = accepted_plan_validator(option, binding, declaration, terms)
        body = negotiate_text(url, option, validate)
        # Subsequent caller-state edits cannot move the retained expectations.
        declaration["machine_details"]["gpu_count"] = 99
        terms["duration_seconds"] = 7200
        with sqlite3.connect(runtime.db.db_path) as conn:
            original = json.loads(
                conn.execute(
                    "SELECT settlement_plan FROM negotiation_threads WHERE negotiation_id=?",
                    (body["negotiation_id"],),
                ).fetchone()[0]
            )
        validate(SettlementPlan.model_validate(original))
        forged = copy.deepcopy(original)
        package = forged["service_terms"]["contact-exchange.v1"]
        obligation = forged["obligations"][0]
        if substitution == "machine":
            package["accepted_context"]["declaration"]["machine_details"][
                "gpu_count"
            ] = 99
        elif substitution == "declaration":
            package["accepted_context"]["declaration"]["declaration_id"] = (
                "other-declaration"
            )
        elif substitution == "accepted_terms":
            package["accepted_context"]["accepted_terms"]["duration_seconds"] = 7200
        elif substitution.endswith("_digest"):
            key = {
                "publication_digest": "publication_intent_digest",
                "source_digest": "source_envelope_digest",
                "binding_digest": "listing_binding_digest",
            }[substitution]
            package["accepted_context"][key] = "f" * 64
        elif substitution == "option":
            altered = copy.deepcopy(option)
            altered["params"]["terms"] = "Substituted commercial terms"
            altered["option_id"] = derive_settlement_option_id(
                **{
                    key: altered[key]
                    for key in ("mechanism", "asset", "rates", "params")
                }
            )
            package["terms"] = altered["params"]["terms"]
            package["option_id"] = package["accepted_context"]["option_id"] = altered[
                "option_id"
            ]
            obligation["params"]["terms"] = altered["params"]["terms"]
        else:
            obligation["conditions"] = [{"kind": "substituted-condition"}]
        obligation["params"]["accepted_context_digest"] = context_digest(
            package["accepted_context"]
        )
        plan = SettlementPlan.model_validate(forged)
        # Internal provenance consistency alone is not caller selection validation.
        validate_accepted_contact_context(plan)
        with pytest.raises(ValueError, match="retained selection"):
            validate(plan)


def test_historical_no_outbound_record_stays_byte_identical_without_jobs(
    delivery_environment,
    monkeypatch,
):
    sent, workers = delivery_environment
    config = configure(monkeypatch, version=1)
    with _server(monkeypatch) as (url, runtime):
        item = asyncio.run(prepare_contact_offers(runtime, document(1)))[0]
        asyncio.run(store(runtime, item))
        option = item.request.settlement_options[0]
        agreed = negotiate_with_seller(
            seller_url=url,
            principal=BUYER.identity,
            signer=BUYER,
            listing_id=item.listing_id,
            resolve_seller_principals=lambda: TrustedIdentitySet(
                identities=(SELLER.identity,)
            ),
            initial_price=None,
            max_price=None,
            unit_count=1,
            policy_params={"_selected_settlement_option": option},
            provision_terms=BareMetalProvisionTerms(
                payload={"duration_seconds": 3600, "access_method": "none"}
            ),
            settlement_selection=SettlementSelection(
                mechanism="contact-exchange.v1",
                option_id=option["option_id"],
                expiration_unix=int(time.time()) + 3600,
            ),
            chain=load_buyer_chain(policy_mode="listed_price"),
        )
        assert agreed.status == "agreed"
        assert agreed.negotiation_id is not None and agreed.settlement_plan is not None
        ref = derive_obligation_ref(
            agreed.negotiation_id,
            0,
            agreed.settlement_plan.obligations[0].model_dump(mode="json"),
        )
        before = agreed.settlement_plan.model_dump(mode="json")
        projection = _transport(url, BUYER).start(
            negotiation_id=agreed.negotiation_id,
            obligation_ref=ref,
            contact_payload={"opaque-old-key": "Historic buyer contact"},
        )
        row = frozen_row(runtime)
        assert "accepted_context" not in projection["introduction"]
        assert counts(runtime) == (1, 0)
    config["contact"]["contact_payload"] = {"text": SELLER_TEXT}
    for profile in config["contact"]["profiles"].values():
        profile.update(delivery_policy=POLICY, context_contract="accepted-listing.v1")
    monkeypatch.setenv("BARE_METAL_STOREFRONT_SETTLEMENT", json.dumps(config))
    with _server(monkeypatch) as (url, runtime):
        assert _transport(url, BUYER).read(obligation_ref=ref) == projection
        assert _transport(url, SELLER).read(obligation_ref=ref)[
            "counterparty_contact"
        ] == {"opaque-old-key": "Historic buyer contact"}
        drain(workers[-1])
        assert frozen_row(runtime) == row and counts(runtime) == (1, 0) and sent == []
        with sqlite3.connect(runtime.db.db_path) as conn:
            stored = json.loads(
                conn.execute(
                    "SELECT settlement_plan FROM negotiation_threads WHERE negotiation_id=?",
                    (agreed.negotiation_id,),
                ).fetchone()[0]
            )
        assert stored == before
