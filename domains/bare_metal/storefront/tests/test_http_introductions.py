"""End-to-end introduction reveal on the bare-metal storefront surface."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from typing import Any

import pytest
from market_contact_exchange import MECHANISM as CONTACT_MECHANISM
from market_contact_exchange import (
    IntroductionAdminClient,
    IntroductionSellerClient,
    format_introduction_timestamp,
)
from core_storefront.publication_runner import NoSettlementOption
from market_core.schemas import derive_settlement_option_id
from market_identity import (
    Eip191Signer,
    TrustedIdentitySet,
)
from market_settlement_runtime import SettlementPublicationClause, derive_obligation_ref

from arkhai_bare_metal_storefront.domain_runtime import get_market_domain_contract
from arkhai_bare_metal_storefront.runtime import BareMetalStorefrontRuntime
from arkhai_bare_metal_storefront.server import (
    build_bare_metal_storefront_app,
    build_bare_metal_storefront_registry,
)
from arkhai_bare_metal_storefront.settlement_composition import (
    BareMetalStorefrontSettlementComposition,
)
from arkhai_bare_metal_storefront.site_clients import BareMetalSiteBinding
from arkhai_bare_metal_storefront.sqlite_client import SQLiteClient
from arkhai_bare_metal.fixtures.listing import LISTING_HARDWARE
from arkhai_bare_metal_buyer.fulfillment import BareMetalFulfillmentTransport
from core_buyer.introductions import IntroductionPayloadsDeleted, IntroductionTransport
from dataclasses import replace
from buyer_commands import BuyerCommands
from loopback import serving
from held_loops import held_loop_controller
from market_resource_pools_contracts.backing import UNBACKED
from source_sites import SourceSite, SourceSites, listing_source_projection, source_projections
from storefront_client import StorefrontClient, StorefrontClientError
from test_http_system import _REGISTRY_TRUST, _RecordedRegistries
from test_publication_cycle import REGISTRY_URL

BUYER_SIGNER = Eip191Signer(bytes.fromhex("22" * 32))
SELLER_SIGNER = Eip191Signer(bytes.fromhex("11" * 32))
ADMIN_SIGNER = Eip191Signer(bytes.fromhex("33" * 32))
OUTSIDER_SIGNER = Eip191Signer(bytes.fromhex("44" * 32))

_SELLER_CONTACT = {"telegram": "@capacity_broker"}
_BUYER_CONTACT = {"email": "buyer@example.com"}


def _contact_option() -> dict[str, Any]:
    params = {
        "profile": "default",
        "channel": "telegram",
        "terms": "Net-30, prose contract on request.",
        "claimant_principal": SELLER_SIGNER.identity.model_dump(mode="json"),
    }
    return {
        "option_id": derive_settlement_option_id(
            mechanism=CONTACT_MECHANISM,
            asset="introduction",
            rates=[],
            params=params,
        ),
        "mechanism": CONTACT_MECHANISM,
        "asset": "introduction",
        "rates": [],
        "params": params,
    }


def _runtime(
    path: str,
    *,
    contact: dict[str, Any] | None = None,
    deliver: Any = None,
    contact_enabled: bool = True,
) -> BareMetalStorefrontRuntime:
    domain = get_market_domain_contract()
    return BareMetalStorefrontRuntime(
        db=SQLiteClient(path, domain=domain),
        domain=domain,
        seller_principal=SELLER_SIGNER.identity,
        admin_principals=TrustedIdentitySet(identities=(ADMIN_SIGNER.identity,)),
        storefront_url="http://seller:8000",
        # The one site the introduction listing is published from: the single
        # contact form is that site's contact and resolves for no other.
        site_bindings=(
            BareMetalSiteBinding(
                site_id="site-a",
                service_peer="site-a-peer",
                authority_url="http://site-a",
            ),
        ),
        # Openings recheck each listing against the projection held for the
        # site that published it, which startup loads.
        capacity_client=SourceSites(),
        site_projections=source_projections(),
        loop_controller_factory=held_loop_controller,
        marketplace_signer=SELLER_SIGNER,
        settlement_composition=(
            BareMetalStorefrontSettlementComposition.from_raw_config(
                {
                    "priority": [CONTACT_MECHANISM] if contact_enabled else [],
                    "contact": {
                        "enabled": contact_enabled,
                        "contact_payload": dict(_SELLER_CONTACT),
                        "profiles": {
                            "default": {
                                "channel": "telegram",
                                "terms": "Net-30, prose contract on request.",
                            }
                        },
                        **(contact or {}),
                    },
                },
                # As the composition root supplies it: the seller a contact
                # option names as the introduction's claimant.
                resources={"claimant_principal": SELLER_SIGNER.identity},
            )
        ),
        introduction_delivery=deliver,
    )


def _app(runtime: BareMetalStorefrontRuntime):
    return build_bare_metal_storefront_app(
        registry=build_bare_metal_storefront_registry(domain=runtime.domain),
        runtime=runtime,
    )


async def _insert_contact_listing(runtime: BareMetalStorefrontRuntime) -> dict:
    option = _contact_option()
    await runtime.db.upsert_bare_metal_listing(
        listing_id="intro-listing",
        status="open",
        created_at="2026-01-01T00:00:00Z",
        updated_at="2026-01-01T00:00:00Z",
        seller_principal=runtime.seller_principal,
        storefront_url=runtime.storefront_url,
        site_id="site-a",
        pool_id="pool-a",
        physical_resource_id="resource-1",
        listing={
            "capacity_backing": "backed",
            **LISTING_HARDWARE,
            "kind": "bare_metal.v2",
            "host_id": "machine-1",
            "physical_host_id": "physical-host-1",
            "access_methods": ["ssh"],
        },
        accepted_escrows=[],
        settlement_options=[option],
    )
    return option


def _opening(option: dict) -> dict:
    return {
        "listing_id": "intro-listing",
        "buyer_principal": BUYER_SIGNER.identity.model_dump(mode="json"),
        "buyer_agent_url": "https://buyer.example",
        "provision_terms": {
            "kind": "bare_metal.v2",
            "version": 1,
            "payload": {"duration_seconds": 3600, "access_method": "none"},
        },
        "proposal": {
            "settlement_selection": {
                "mechanism": CONTACT_MECHANISM,
                "option_id": option["option_id"],
                "expiration_unix": 1_900_000_000,
            },
            "fields": {},
        },
    }


def _introductions(base_url: str, signer=BUYER_SIGNER) -> IntroductionTransport:
    """The production buyer's introduction client, pointed at ``base_url``."""
    return IntroductionTransport(
        seller_url=base_url,
        principal=signer.identity,
        signer=signer,
        resolve_seller_principals=lambda: TrustedIdentitySet(
            identities=(SELLER_SIGNER.identity,)
        ),
    )


async def _negotiate_contact(base_url: str, option: dict) -> dict:
    """Open a negotiation for the contact listing through the buyer's typed client."""
    opening = _opening(option)
    async with StorefrontClient(
        base_url,
        signer=BUYER_SIGNER,
        caller_role="buyer",
        expected_publishers=TrustedIdentitySet(identities=(SELLER_SIGNER.identity,)),
    ) as storefront:
        return await storefront.negotiate_new(
            listing_id=opening["listing_id"],
            initial_amount=None,
            provision_terms=opening["provision_terms"],
            proposal_fields=opening["proposal"]["fields"],
            settlement_selection=opening["proposal"]["settlement_selection"],
            selection_only=True,
            buyer_agent_url=opening["buyer_agent_url"],
        )


async def _accept_typed(base_url: str, option: dict) -> tuple[str, str]:
    """Accept the contact listing through the buyer's typed client."""
    payload = await _negotiate_contact(base_url, option)
    assert payload["action"] == "accept"
    negotiation_id = payload["negotiation_id"]
    plan = payload["settlement_plan"]
    obligation_ref = derive_obligation_ref(
        negotiation_id, 0, plan["obligations"][0]
    )
    return negotiation_id, obligation_ref


async def _accept_and_start(base_url: str, option: dict) -> tuple[str, str, dict]:
    """Accept the contact listing and reveal, through the buyer's typed clients."""
    negotiation_id, obligation_ref = await _accept_typed(base_url, option)
    started = _introductions(base_url).start(
        negotiation_id=negotiation_id,
        obligation_ref=obligation_ref,
        contact_payload=dict(_BUYER_CONTACT),
    )
    return negotiation_id, obligation_ref, started


async def _seller_read(base_url: str, obligation_ref: str) -> dict:
    """Re-read one introduction as its seller, through the seller's typed client."""
    async with StorefrontClient(
        base_url,
        signer=SELLER_SIGNER,
        caller_role="seller",
        expected_publishers=TrustedIdentitySet(identities=(SELLER_SIGNER.identity,)),
    ) as seller:
        reveal = await IntroductionSellerClient(seller).read_introduction(obligation_ref)
    return reveal.model_dump(exclude_none=True)


async def test_contact_options_publish_through_the_composition() -> None:
    composition = BareMetalStorefrontSettlementComposition.from_raw_config(
        {
            "priority": [CONTACT_MECHANISM],
            "contact": {
                "enabled": True,
                "contact_payload": dict(_SELLER_CONTACT),
                "profiles": {
                    "default": {
                        "channel": "telegram",
                        "terms": "Net-30, prose contract on request.",
                    }
                },
            },
        },
        resources={
            "claimant_principal": SELLER_SIGNER.identity,
        },
    )
    payload = await composition.publication_payload(
        candidate={"host_id": "machine-1", "site_id": "default"},
        clauses=[
            SettlementPublicationClause(
                mechanism=CONTACT_MECHANISM,
                asset="introduction",
                mechanism_input={"profile": "default"},
            )
        ],
    )
    assert payload.accepted_escrows == ()
    (option,) = payload.settlement_options
    assert option["mechanism"] == CONTACT_MECHANISM
    assert option["rates"] == []
    assert "@capacity_broker" not in str(payload.settlement_options)


async def test_introduction_start_reveals_and_completes(tmp_path) -> None:
    runtime = _runtime(str(tmp_path / "storefront.db"))
    option = await _insert_contact_listing(runtime)
    app = _app(runtime)
    with serving(app) as base_url:
        negotiation_id, obligation_ref, projection = await _accept_and_start(
            base_url, option
        )
        read = _introductions(base_url).read(obligation_ref=obligation_ref)
        seller_read = await _seller_read(base_url, obligation_ref)
    assert projection["revealed"] is True
    assert projection["counterparty_contact"] == _SELLER_CONTACT
    assert projection["introduction"]["channel"] == "telegram"
    assert read["counterparty_contact"] == _SELLER_CONTACT
    assert seller_read["counterparty_contact"] == _BUYER_CONTACT
    status = await runtime.settlement_runtime.get_status(negotiation_id)
    assert status.status == "complete"
    # Spec scenario "An introduction is revealed": the reveal is the
    # contact-exchange kit's record, and the deal's settlement record stays as
    # acceptance wrote it, with no settlement evidence.
    record = await runtime.db.load_bare_metal_settlement_record(
        negotiation_id=negotiation_id
    )
    assert (record["status"], record["settlement_ref"]) == ("accepted", None)
    assert (
        await runtime.db.load_bare_metal_fulfillment_lifecycle(
            negotiation_id=negotiation_id
        )
        is None
    )


async def test_introduction_survives_a_storefront_restart(tmp_path) -> None:
    path = str(tmp_path / "storefront.db")
    runtime = _runtime(path)
    option = await _insert_contact_listing(runtime)
    with serving(_app(runtime)) as base_url:
        _, obligation_ref, _ = await _accept_and_start(base_url, option)

    with serving(_app(_runtime(path))) as base_url:
        read = _introductions(base_url).read(obligation_ref=obligation_ref)
    assert read["counterparty_contact"] == _SELLER_CONTACT


@pytest.mark.parametrize("revealed_before_disable", [False, True])
async def test_accepted_introduction_survives_contact_disable(
    tmp_path, revealed_before_disable: bool
) -> None:
    path = str(tmp_path / "storefront.db")
    runtime = _runtime(path)
    option = await _insert_contact_listing(runtime)
    with serving(_app(runtime)) as base_url:
        negotiation_id, obligation_ref = await _accept_typed(base_url, option)
        if revealed_before_disable:
            _introductions(base_url).start(
                negotiation_id=negotiation_id,
                obligation_ref=obligation_ref,
                contact_payload=dict(_BUYER_CONTACT),
            )

    restarted = _runtime(path, contact_enabled=False)
    # A disabled contact section publishes no new option: configuration rules
    # it out, so a candidate naming only it is refused.
    with pytest.raises(NoSettlementOption) as refused:
        await restarted.settlement_composition.publication_payload(
            candidate={"host_id": "machine-1", "site_id": "site-a"},
            clauses=[
                SettlementPublicationClause(
                    mechanism=CONTACT_MECHANISM,
                    asset="introduction",
                    mechanism_input={"profile": "default"},
                )
            ],
        )
    assert refused.value.mechanisms == (CONTACT_MECHANISM,)
    assert refused.value.ruled_out_by_configuration is True
    app = _app(restarted)
    with serving(app) as base_url:
        buyer = _introductions(base_url)
        if revealed_before_disable:
            read = buyer.read(obligation_ref=obligation_ref)
            assert read["counterparty_contact"] == _SELLER_CONTACT

        revealed = buyer.start(
            negotiation_id=negotiation_id,
            obligation_ref=obligation_ref,
            contact_payload=dict(_BUYER_CONTACT),
        )
        assert revealed["counterparty_contact"] == _SELLER_CONTACT
        assert (
            buyer.start(
                negotiation_id=negotiation_id,
                obligation_ref=obligation_ref,
                contact_payload=dict(_BUYER_CONTACT),
            )
            == revealed
        )
        assert buyer.read(obligation_ref=obligation_ref) == revealed

        # Fresh contact work stays refused while the mechanism is disabled.
        with pytest.raises(StorefrontClientError) as refused:
            await _negotiate_contact(base_url, option)
        assert refused.value.status_code == 400

        # The seller re-reads the same persisted reveal after disablement.
        seller_read = await _seller_read(base_url, obligation_ref)
    assert seller_read["counterparty_contact"] == _BUYER_CONTACT
    assert seller_read["obligation_ref"] == obligation_ref

    status = await restarted.settlement_runtime.get_status(negotiation_id)
    assert status.status == "complete"
    record = await restarted.db.load_bare_metal_settlement_record(
        negotiation_id=negotiation_id
    )
    assert (record["status"], record["settlement_ref"]) == ("accepted", None)


async def test_reveal_refusals(tmp_path) -> None:
    runtime = _runtime(str(tmp_path / "storefront.db"))
    option = await _insert_contact_listing(runtime)
    with serving(_app(runtime)) as base_url:
        with pytest.raises(RuntimeError, match="404"):
            _introductions(base_url).read(obligation_ref="ee" * 32)

        _, obligation_ref, _ = await _accept_and_start(base_url, option)
        with pytest.raises(RuntimeError, match="403"):
            _introductions(base_url, OUTSIDER_SIGNER).read(obligation_ref=obligation_ref)


# -- a deal settled by introduction has no settlement or fulfillment -----------


def _fulfillment(base_url: str, signer=BUYER_SIGNER) -> BareMetalFulfillmentTransport:
    """The production bare-metal buyer's fulfillment transport."""
    return BareMetalFulfillmentTransport(
        seller_url=base_url,
        principal=signer.identity,
        signer=signer,
        resolve_seller_principals=lambda: TrustedIdentitySet(
            identities=(SELLER_SIGNER.identity,)
        ),
    )


def _buyer_storefront(base_url: str) -> StorefrontClient:
    return StorefrontClient(
        base_url,
        signer=BUYER_SIGNER,
        caller_role="buyer",
        expected_publishers=TrustedIdentitySet(identities=(SELLER_SIGNER.identity,)),
    )


_FULFILLMENT_READS = ("status", "access", "result", "teardown")


async def _settlement_and_fulfillment_answers(base_url: str, negotiation_id: str) -> dict:
    """What settle, settle status, and each fulfillment route answer the deal's
    buyer, and what fulfillment status answers another principal."""
    answers: dict[str, Any] = {}
    async with _buyer_storefront(base_url) as buyer:
        for name, call in (
            ("settle", buyer.settle_agreement(negotiation_id)),
            ("settle_status", buyer.get_settle_status(negotiation_id)),
        ):
            try:
                answers[name] = await call
            except StorefrontClientError as exc:
                answers[name] = exc
    for name in _FULFILLMENT_READS:
        try:
            answers[name] = getattr(_fulfillment(base_url), name)(negotiation_id)
        except RuntimeError as exc:
            answers[name] = exc
    try:
        answers["outsider"] = _fulfillment(base_url, OUTSIDER_SIGNER).status(negotiation_id)
    except RuntimeError as exc:
        answers["outsider"] = exc
    return answers


def _assert_settled_by_introduction(answers: dict) -> None:
    """Spec scenarios "A buyer settles an introduction deal", "A buyer asks for
    an introduction deal's fulfillment", and "Another buyer asks about an
    introduction deal"."""
    for name in ("settle", "settle_status"):
        refused = answers[name]
        assert isinstance(refused, StorefrontClientError), (name, refused)
        assert refused.status_code == 409
        assert "completes by introduction, not settlement" in str(refused)
    for name in _FULFILLMENT_READS:
        refused = answers[name]
        assert isinstance(refused, RuntimeError), (name, refused)
        assert "HTTP 404" in str(refused) and "has no fulfillment" in str(refused), refused
    # Refused by the buyer authorization every deal's routes run before the
    # stage is resolved, so the answer names nothing of the mechanism. The
    # status is matched with its prefix: the message also names the loopback
    # URL, whose port may contain any three digits.
    outsider = answers["outsider"]
    assert isinstance(outsider, RuntimeError), outsider
    assert "HTTP 403" in str(outsider), outsider
    assert "HTTP 404" not in str(outsider) and "introduction" not in str(outsider)


async def test_an_introduction_deal_answers_settle_and_fulfillment_from_its_stage(
    tmp_path,
) -> None:
    runtime = _runtime(str(tmp_path / "storefront.db"))
    option = await _insert_contact_listing(runtime)
    with serving(_app(runtime)) as base_url:
        negotiation_id, _, _ = await _accept_and_start(base_url, option)
        answers = await _settlement_and_fulfillment_answers(base_url, negotiation_id)

    _assert_settled_by_introduction(answers)
    record = await runtime.db.load_bare_metal_settlement_record(
        negotiation_id=negotiation_id
    )
    assert (record["status"], record["settlement_ref"]) == ("accepted", None)


class _ContextCountingClient(SQLiteClient):
    """The storefront's persistence, counting fulfillment-context loads."""

    context_loads = 0

    async def load_bare_metal_fulfillment_context(self, *, negotiation_id: str):
        type(self).context_loads += 1
        return await super().load_bare_metal_fulfillment_context(
            negotiation_id=negotiation_id
        )


async def test_an_unbacked_listing_published_by_the_storefront_reaches_an_introduction(
    tmp_path,
) -> None:
    """Spec scenarios "An unbacked pool advertises bare metal", "An unbacked
    bare-metal listing is accepted", and "An unbacked introduction deal's
    fulfillment is requested", through the app: its own publication cycle
    publishes the unbacked pool's machine with no delivery term and only the
    introduction option; the buyer accepts and reveals it, the seller's contact
    reaching the buyer; and every settlement and fulfillment route answers from
    the stage, without loading a fulfillment context for a binding that names
    no host. No fulfillment authority is composed, so a route that reached the
    fulfillment service would fail rather than answer."""
    site = SourceSite(listing_source_projection(backing=UNBACKED))
    registries = _RecordedRegistries(authorities={REGISTRY_URL: _REGISTRY_TRUST})
    path = str(tmp_path / "storefront.db")
    _ContextCountingClient.context_loads = 0
    runtime = replace(
        _runtime(path),
        db=_ContextCountingClient(path, domain=get_market_domain_contract()),
        capacity_client=SourceSites(site),
        site_projections=source_projections(site),
        registry_configuration=registries,
        publication_clauses=(
            SettlementPublicationClause(
                mechanism=CONTACT_MECHANISM,
                asset="introduction",
                mechanism_input={"profile": "default"},
            ),
        ),
        default_max_duration_seconds=3600,
    )
    app = _app(runtime)
    with serving(app) as base_url:
        async with _admin(base_url) as admin:
            report = await admin.admin_run_lifecycle_cycle("publication")
        # What the registry was sent is what a buyer discovers.
        ((operation, _url, listing_id, sent),) = registries.recording.sent
        published = sent["listing_resource"]
        (option,) = [dict(item) for item in sent["settlement_options"]]
        async with _buyer_storefront(base_url) as buyer:
            accepted = await buyer.negotiate_new(
                listing_id=listing_id,
                initial_amount=None,
                provision_terms=_opening(option)["provision_terms"],
                proposal_fields={},
                settlement_selection=_opening(option)["proposal"]["settlement_selection"],
                selection_only=True,
                buyer_agent_url="https://buyer.example",
            )
        negotiation_id = accepted["negotiation_id"]
        obligation_ref = derive_obligation_ref(
            negotiation_id, 0, accepted["settlement_plan"]["obligations"][0]
        )
        revealed = _introductions(base_url).start(
            negotiation_id=negotiation_id,
            obligation_ref=obligation_ref,
            contact_payload=dict(_BUYER_CONTACT),
        )
        answers = await _settlement_and_fulfillment_answers(base_url, negotiation_id)

    assert [item["action"] for item in report["actions"]] == ["publish"]
    assert operation == "publish"
    assert published["capacity_backing"] == "unbacked"
    for term in ("host_id", "physical_host_id", "access_methods"):
        assert term not in published
    assert option["mechanism"] == CONTACT_MECHANISM
    assert accepted["action"] == "accept"
    assert revealed["counterparty_contact"] == _SELLER_CONTACT
    _assert_settled_by_introduction(answers)
    assert _ContextCountingClient.context_loads == 0
    assert runtime.capacity_client.reservation_sites == {}


async def test_the_buyer_commands_reach_an_introduction_over_their_own_run_log(
    tmp_path, monkeypatch
) -> None:
    """The production ``market bare-metal request-introduction`` and ``market
    bare-metal settlement contact introduce`` against the storefront: the first
    holds the seller's accept reply to the advertised option and records a run
    log the second reloads, as a buyer runs them. The buyer's own sink receives
    the seller's contact in an event naming, as its counterparty, the seller
    the accepted Agreement names (introduction-delivery's "The delivered event
    carries the introduction without interpreting it")."""
    runtime = _runtime(str(tmp_path / "storefront.db"))
    option = await _insert_contact_listing(runtime)
    delivered = tmp_path / "delivered.jsonl"
    buyer = BuyerCommands(
        monkeypatch,
        tmp_path,
        signer=BUYER_SIGNER,
        registry_principal=ADMIN_SIGNER.identity,
        delivered=delivered,
    )
    contact = ",".join(f"{key}={value}" for key, value in _BUYER_CONTACT.items())
    with serving(_app(runtime)) as base_url:
        buyer.serve(
            SimpleNamespace(
                listing_id="intro-listing",
                storefront_url=base_url,
                publisher_id="publisher-1",
                publisher_principals=TrustedIdentitySet(identities=(SELLER_SIGNER.identity,)),
                settlement_options=[option],
            )
        )
        request = buyer.run(
            "request-introduction", "intro-listing", "--option-id", option["option_id"]
        )
        introduced = buyer.run(
            "settlement", "contact", "introduce",
            "--run-id", request["run_id"], "--contact", contact,
        )

    assert request["status"] == "agreed"
    assert introduced["counterparty_contact"] == _SELLER_CONTACT
    (event,) = [json.loads(line) for line in delivered.read_text().splitlines()]
    seller = SELLER_SIGNER.identity
    assert request["agreement"]["seller"] == seller.model_dump(mode="json")
    assert (event["role"], event["obligation_ref"], event["contact"]) == (
        "buyer",
        request["obligation_ref"],
        _SELLER_CONTACT,
    )
    assert event["counterparty"] == f"{seller.scheme.value}:{seller.identifier}"



# -- retention ---------------------------------------------------------------

_ONE_DAY = 86_400


def _admin(base_url: str) -> StorefrontClient:
    return StorefrontClient(
        base_url,
        signer=ADMIN_SIGNER,
        caller_role="admin",
        expected_publishers=TrustedIdentitySet(identities=(SELLER_SIGNER.identity,)),
    )


def _backdate_reveal(db_path: str, obligation_ref: str, *, days: int) -> None:
    """Make one revealed introduction ``days`` old.

    Service-internal precondition state no API can express: the reveal time is
    the storefront's clock at insert, and the persistence triggers refuse any
    change to it. The fixture steps around them the way a database owner
    repairing data would, and restores them before the storefront reads again.
    """
    conn = sqlite3.connect(db_path)
    try:
        triggers = conn.execute(
            "SELECT sql FROM sqlite_master WHERE type='trigger' "
            "AND tbl_name='contact_introductions'"
        ).fetchall()
        conn.execute("DROP TRIGGER contact_introductions_redaction_only")
        conn.execute("DROP TRIGGER contact_introductions_keep_unredacted")
        conn.execute(
            "UPDATE contact_introductions SET created_at=? WHERE obligation_ref=?",
            (
                format_introduction_timestamp(
                    datetime.now(timezone.utc) - timedelta(days=days)
                ),
                obligation_ref,
            ),
        )
        for (sql,) in triggers:
            conn.execute(sql)
        conn.commit()
    finally:
        conn.close()


async def test_readiness_discloses_the_window_the_reveal_carries(tmp_path) -> None:
    runtime = _runtime(
        str(tmp_path / "storefront.db"), contact={"retention_seconds": _ONE_DAY}
    )
    option = await _insert_contact_listing(runtime)
    with serving(_app(runtime)) as base_url:
        async with StorefrontClient(base_url) as anonymous:
            readiness = await anonymous.get_health()
        _, obligation_ref, started = await _accept_and_start(base_url, option)
        read = _introductions(base_url).read(obligation_ref=obligation_ref)
    expected = {
        "window_seconds": _ONE_DAY,
        "basis": "current_policy",
        "scope": "introduction_record",
    }
    assert readiness.disclosures == {"introduction_retention": expected}
    assert started["retention"] == expected
    assert read["retention"] == expected


async def test_an_indefinite_window_is_disclosed_explicitly(tmp_path) -> None:
    runtime = _runtime(
        str(tmp_path / "storefront.db"), contact={"retention_seconds": "indefinite"}
    )
    with serving(_app(runtime)) as base_url:
        async with StorefrontClient(base_url) as anonymous:
            readiness = await anonymous.get_health()
    assert readiness.disclosures["introduction_retention"]["window_seconds"] is None


async def test_no_retention_is_disclosed_without_contact_exchange(tmp_path) -> None:
    runtime = _runtime(str(tmp_path / "storefront.db"), contact_enabled=False)
    with serving(_app(runtime)) as base_url:
        async with StorefrontClient(base_url) as anonymous:
            readiness = await anonymous.get_health()
        async with _admin(base_url) as admin:
            with pytest.raises(StorefrontClientError) as refused:
                await IntroductionAdminClient(admin).delete_introduction_payloads(
                    "ab" * 32
                )
    assert readiness.disclosures == {}
    assert refused.value.status_code == 404
    assert "introduction-retention" not in runtime.loops.step_routes()


async def test_operator_deletion_keeps_the_deal_and_stops_every_reveal(tmp_path) -> None:
    deliveries: list[str] = []
    runtime = _runtime(
        str(tmp_path / "storefront.db"),
        deliver=lambda projection, agreement: deliveries.append(
            projection["obligation_ref"]
        ),
    )
    option = await _insert_contact_listing(runtime)
    with serving(_app(runtime)) as base_url:
        negotiation_id, obligation_ref, _ = await _accept_and_start(base_url, option)
        assert deliveries == [obligation_ref]
        async with _admin(base_url) as admin:
            introductions_admin = IntroductionAdminClient(admin)
            deleted = await introductions_admin.delete_introduction_payloads(obligation_ref)
            again = await introductions_admin.delete_introduction_payloads(obligation_ref)
        with pytest.raises(IntroductionPayloadsDeleted) as on_read:
            _introductions(base_url).read(obligation_ref=obligation_ref)
        # A fresh request identity, so not an exact replay of the first start.
        with pytest.raises(IntroductionPayloadsDeleted) as on_start:
            _introductions(base_url).start(
                negotiation_id=negotiation_id,
                obligation_ref=obligation_ref,
                contact_payload=dict(_BUYER_CONTACT),
            )

    assert deleted.obligation_ref == obligation_ref
    assert deleted.redacted is True
    assert again == deleted.model_copy(update={"redacted": False})
    assert on_read.value.payloads_deleted_at == deleted.payloads_deleted_at
    assert on_start.value.outcome()["revealed"] is False
    # Nothing was persisted again and the seller was not told a second time.
    stored = await runtime.contact_exchange.store.load(obligation_ref)
    assert stored is not None and stored.buyer_contact == {}
    assert deliveries == [obligation_ref]
    # The deal remains: its obligation record resolves and correlates.
    assert await runtime.settlement_repository.load_settlement_obligation(
        obligation_ref
    ) is not None
    status = await runtime.settlement_runtime.get_status(negotiation_id)
    assert status.status == "complete"


async def test_held_retention_sweep_deletes_what_it_previewed(
    tmp_path,
) -> None:
    db_path = str(tmp_path / "storefront.db")
    runtime = _runtime(db_path, contact={"retention_seconds": _ONE_DAY})
    option = await _insert_contact_listing(runtime)
    with serving(_app(runtime)) as base_url:
        async with _admin(base_url) as admin:
            held = await admin.admin_pause_lifecycle_loops()
            assert held["loops"]["introduction_retention"] == "paused"
            _, expired_ref, _ = await _accept_and_start(base_url, option)
            _, fresh_ref, _ = await _accept_and_start(base_url, option)
            _backdate_reveal(db_path, expired_ref, days=2)

            preview = await admin.admin_dry_run_lifecycle_cycle(
                "introduction-retention"
            )
            assert preview["eligible"] == [expired_ref]
            assert _introductions(base_url).read(obligation_ref=expired_ref)

            stepped = await admin.admin_run_lifecycle_cycle("introduction-retention")
            assert stepped == {"loop": "introduction_retention", "deleted": 1}
            with pytest.raises(IntroductionPayloadsDeleted):
                _introductions(base_url).read(obligation_ref=expired_ref)
            assert _introductions(base_url).read(obligation_ref=fresh_ref)[
                "counterparty_contact"
            ] == _SELLER_CONTACT
            await admin.admin_resume_lifecycle_loops()
