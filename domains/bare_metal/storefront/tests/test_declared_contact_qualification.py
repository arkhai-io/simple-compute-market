"""Installed publication-to-exchange qualification with disposable TEST fixtures.

Only owned loopback services and fake SMTP are used. The deterministic identities,
TEST machines and example.invalid routes must never be used on a public network.
"""

import asyncio
import copy
import json
import sqlite3
import subprocess
import sys
import time
import uuid
from email.parser import BytesParser
from email.policy import default
from pathlib import Path

import pytest
from arkhai_bare_metal import BareMetalProvisionTerms
from arkhai_bare_metal_storefront.contact_context import (
    context_digest,
    validate_accepted_contact_context,
)
from arkhai_bare_metal_storefront.contact_offers import (
    contact_registry,
    load_contact_declarations,
)
from arkhai_bare_metal_storefront.domain_runtime import get_market_domain_contract
from arkhai_bare_metal_storefront.runtime import build_runtime_from_environment
from arkhai_bare_metal_storefront.server import (
    build_bare_metal_storefront_app,
    build_bare_metal_storefront_registry,
)
from core_buyer.negotiation_client import load_buyer_chain, negotiate_with_seller
from market_core.schemas import SettlementPlan, SettlementSelection
from market_settlement_runtime import derive_obligation_ref
from test_contact_publication import BUYER, SELLER, introduction, serve
from test_contact_publication import declaration_environment as declaration_environment
from test_contact_publication import publication_environment as publication_environment
from test_http_contact_delivery import (
    RecordingSMTP,
    counts,
    finalize_body,
    install_smtp_boundary,
)
from test_http_contact_source_exchange import (
    ACCEPTED_TERMS,
    BUYER_ROUTE,
    BUYER_TEXT,
    SELLER_ROUTE,
    SELLER_TEXT,
    accepted_plan_validator,
    assert_private_absent,
    change_settings,
    drain,
    frozen_row,
    withdraw_listing,
)


def recipient_states(runtime):
    with sqlite3.connect(runtime.db.db_path) as conn:
        return conn.execute(
            "SELECT recipient_role,status,attempts,route FROM contact_delivery_intents "
            "ORDER BY recipient_role"
        ).fetchall()


def test_installed_general_publication_to_frozen_recipient_copies(
    declaration_environment, monkeypatch, caplog
):
    path, config = declaration_environment
    sent, workers = install_smtp_boundary(monkeypatch)
    config["contact"]["contact_payload"] = {"text": SELLER_TEXT}
    monkeypatch.setenv("BARE_METAL_STOREFRONT_SETTLEMENT", json.dumps(config))
    domain = get_market_domain_contract()
    runtimes = []

    def factory():
        runtime = build_runtime_from_environment(domain=domain)
        runtimes.append(runtime)
        return runtime

    def application():
        return build_bare_metal_storefront_app(
            registry=build_bare_metal_storefront_registry(domain=domain),
            runtime_factory=factory,
        )

    def bind_url(url):
        monkeypatch.setenv("BARE_METAL_STOREFRONT_PUBLIC_URL", url)

    with serve(application(), before_start=bind_url):
        runtime = runtimes[-1]
        assert runtime.capacity_client is runtime.fulfillment_client is None
        assert runtime.site_bindings == ()
        with contact_registry(runtime) as registry:
            assert registry.list_listings().listings == []
        command = Path(sys.executable).parent / "bare-metal-storefront"
        published = subprocess.run(
            [str(command), "publish-declarations", "--offers", str(path)],
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert published.returncode == 0, published.stderr
        assert json.loads(published.stdout)["confirmed"] == 6
        declarations = load_contact_declarations(path)
        with contact_registry(runtime) as registry:
            discovered = registry.list_listings().listings
            assert {item.id for item in discovered} == {
                entry.declaration.listing_id for entry in declarations.offers
            }
            assert len(discovered) > 5
            listing = registry.get_listing(
                declarations.offers[0].declaration.listing_id
            )
        assert isinstance(listing.id, str) and isinstance(listing.storefront_url, str)
        # Retain expectations before receiving any seller acceptance.
        declaration = declarations.offers[0].declaration.model_dump(mode="json")
        (option,) = copy.deepcopy(listing.settlement_options)
        assert option["rates"] == [] and listing.accepted_escrows == []
        for field, value in declaration["machine_details"].items():
            assert listing.offer[field] == value
        binding = asyncio.run(runtime.db.load_listing_binding(listing_id=listing.id))
        validate = accepted_plan_validator(option, binding, declaration, ACCEPTED_TERMS)
        outcome = negotiate_with_seller(
            seller_url=listing.storefront_url,
            principal=BUYER.identity,
            signer=BUYER,
            listing_id=listing.id,
            resolve_seller_principals=lambda: listing.publisher_principals,
            initial_price=None,
            max_price=None,
            unit_count=1,
            policy_params={"_selected_settlement_option": option},
            provision_terms=BareMetalProvisionTerms(
                payload=copy.deepcopy(ACCEPTED_TERMS)
            ),
            settlement_selection=SettlementSelection(
                mechanism="contact-exchange.v1",
                option_id=option["option_id"],
                expiration_unix=int(time.time()) + 3600,
            ),
            chain=load_buyer_chain(policy_mode="listed_price"),
            validate_advertised_plan=validate,
        )
        assert outcome.status == "agreed"
        plan = outcome.settlement_plan
        assert plan is not None and outcome.negotiation_id is not None
        assert plan.obligations[0].amount is None
        assert plan.obligations[0].asset == "introduction"
        validate(plan)
        forged = plan.model_dump(mode="json")
        forged_context = forged["service_terms"]["contact-exchange.v1"][
            "accepted_context"
        ]
        forged_context["declaration"]["machine_details"]["gpu_count"] += 1
        forged["obligations"][0]["params"]["accepted_context_digest"] = context_digest(
            forged_context
        )
        substitution = SettlementPlan.model_validate(forged)
        validate_accepted_contact_context(substitution)
        with pytest.raises(ValueError, match="retained selection"):
            validate(substitution)
        ref = derive_obligation_ref(
            outcome.negotiation_id, 0, plan.obligations[0].model_dump(mode="json")
        )
        assert counts(runtime) == (0, 0) and sent == []
        buyer = introduction(listing.storefront_url, BUYER)
        body = {
            "schema_version": 2,
            "negotiation_id": outcome.negotiation_id,
            "obligation_ref": ref,
            "finalization_id": str(uuid.uuid4()),
            "contact_payload": {"text": BUYER_TEXT},
            "delivery_route": {"kind": "email", "address": BUYER_ROUTE},
        }
        review = buyer.review(body=body)
        package = copy.deepcopy(review["introduction"])
        assert package == plan.service_terms["contact-exchange.v1"]
        assert counts(runtime) == (0, 0) and sent == []
        withdraw_listing(runtime)
        request = finalize_body(body, review)
        projection = buyer.finalize(body=request)
        row = frozen_row(runtime)
        assert counts(runtime) == (1, 2) and sent == []
        assert (
            asyncio.run(
                runtime.settlement_runtime.get_status(outcome.negotiation_id)
            ).status
            == "complete"
        )
        assert projection["introduction"] == package
        change_settings(runtime)

    # Restart at durable exchange/settlement completion, before either SMTP attempt.
    refused = []
    rcpt = RecordingSMTP.rcpt

    def temporary_seller_refusal(self, address):
        if address == SELLER_ROUTE and not refused:
            refused.append(True)
            return 450, b"TEST temporary recipient refusal"
        return rcpt(self, address)

    monkeypatch.setattr(RecordingSMTP, "rcpt", temporary_seller_refusal)
    with serve(application(), before_start=bind_url) as url:
        runtime = runtimes[-1]
        change_settings(runtime)
        buyer, seller = introduction(url, BUYER), introduction(url, SELLER)
        assert buyer.finalize(body=request) == projection
        assert buyer.read(obligation_ref=ref)["counterparty_contact"] == {
            "text": SELLER_TEXT
        }
        seller_view = seller.read(obligation_ref=ref)
        assert seller_view["counterparty_contact"] == {"text": BUYER_TEXT}
        assert seller_view["introduction"] == package
        assert frozen_row(runtime) == row and counts(runtime) == (1, 2)
        assert (
            asyncio.run(
                runtime.settlement_runtime.get_status(outcome.negotiation_id)
            ).status
            == "complete"
        )
        worker = workers[-1]
        now = int(time.time())
        worker.wall_clock = lambda: now
        drain(worker)
        states = recipient_states(runtime)
        assert [(role, state, attempts) for role, state, attempts, _ in states] == [
            ("buyer", "accepted", 1),
            ("seller", "retry_wait", 1),
        ]
        assert states[0][3] is None and states[1][3] is not None
        assert [address for address, _ in sent] == [BUYER_ROUTE]
        now += 61
        drain(worker)
        assert recipient_states(runtime) == [
            ("buyer", "accepted", 1, None),
            ("seller", "accepted", 2, None),
        ]
        assert len(sent) == 2 and {address for address, _ in sent} == {
            BUYER_ROUTE,
            SELLER_ROUTE,
        }
        rendered_contexts = []
        for address, raw in sent:
            message = BytesParser(policy=default).parsebytes(raw)
            assert message["To"] == address and message["Bcc"] is None
            assert (
                message.get_content_type() == "text/plain"
                and not message.is_multipart()
            )
            text = message.get_content().replace("\r\n", "\n")
            own, counterparty = (
                (BUYER_TEXT, SELLER_TEXT)
                if address == BUYER_ROUTE
                else (SELLER_TEXT, BUYER_TEXT)
            )
            assert text.endswith(
                "Counterparty contact:\n  text: " + counterparty + "\n"
            )
            assert f"listing_id: {listing.id}" in text
            for key, value in declaration["machine_details"].items():
                assert f"{key}: {value}" in text
            assert "duration_seconds: 3600" in text and "access_method: none" in text
            assert f"terms: {package['terms']}" in text
            assert_private_absent(
                text,
                own,
                BUYER_ROUTE,
                SELLER_ROUTE,
                "FUTURE-SELLER",
                "Future public terms",
            )
            rendered_contexts.append(
                text.split("Agreed introduction:\n", 1)[1].split(
                    "\n\nCounterparty contact:", 1
                )[0]
            )
            pending = [package]
            while pending:
                for key, value in pending.pop().items():
                    if isinstance(value, dict):
                        pending.append(value)
                    else:
                        assert f"{key}: {value}" in rendered_contexts[-1]
        assert rendered_contexts[0] == rendered_contexts[1]
        drain(worker)
        assert len(sent) == 2 and frozen_row(runtime) == row
    with serve(application(), before_start=bind_url):
        runtime = runtimes[-1]
        drain(workers[-1])
        assert len(sent) == 2 and frozen_row(runtime) == row
        assert recipient_states(runtime) == [
            ("buyer", "accepted", 1, None),
            ("seller", "accepted", 2, None),
        ]
    assert_private_absent(
        caplog.text, BUYER_TEXT, SELLER_TEXT, BUYER_ROUTE, SELLER_ROUTE
    )
    print(
        json.dumps(
            {
                "qualification": "local-declared-contact-exchange",
                "published": 6,
                "discovered": sorted(item.id for item in discovered),
                "selected_option": option,
                "accepted_context": package["accepted_context"],
                "acceptance_sends": 0,
                "recipient_copies": 2,
                "recipient_attempts": {"buyer": 1, "seller": 2},
                "terminal_routes": 0,
                "restart_capture_unchanged": True,
                "self_consistent_substitution": "refused",
                "physical_authority": False,
            },
            sort_keys=True,
        )
    )
