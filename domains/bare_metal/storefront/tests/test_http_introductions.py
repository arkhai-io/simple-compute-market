"""End-to-end introduction reveal on the bare-metal storefront surface."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone
from typing import Any

import pytest
from market_contact_exchange import MECHANISM as CONTACT_MECHANISM
from market_contact_exchange import (
    IntroductionAdminClient,
    IntroductionSellerClient,
    format_introduction_timestamp,
)
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
from core_buyer.introductions import IntroductionPayloadsDeleted, IntroductionTransport
from loopback import serving
from source_sites import SourceSites
from storefront_client import StorefrontClient, StorefrontClientError

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
                authority_principal=SELLER_SIGNER.identity,
                authority_url="http://site-a",
            ),
        ),
        # Openings recheck each listing against the site that published it.
        capacity_client=SourceSites(),
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
                }
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
    evidence = await runtime.settlement_service().verified_evidence(
        negotiation_id=negotiation_id, buyer_principal=BUYER_SIGNER.identity
    )
    assert evidence.settlement_ref == obligation_ref
    assert evidence.evidence["delivery"] is None
    assert evidence.evidence["source"] == {"obligation_ref": obligation_ref}
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
    publication = await restarted.settlement_composition.publication_payload(
        candidate={"host_id": "machine-1", "site_id": "site-a"},
        clauses=[
            SettlementPublicationClause(
                mechanism=CONTACT_MECHANISM,
                asset="introduction",
                mechanism_input={"profile": "default"},
            )
        ],
    )
    assert publication.settlement_options == ()
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
    evidence = await restarted.settlement_service().verified_evidence(
        negotiation_id=negotiation_id, buyer_principal=BUYER_SIGNER.identity
    )
    assert evidence.settlement_ref == obligation_ref
    assert evidence.evidence["source"] == {"obligation_ref": obligation_ref}


async def test_reveal_refusals(tmp_path) -> None:
    runtime = _runtime(str(tmp_path / "storefront.db"))
    option = await _insert_contact_listing(runtime)
    with serving(_app(runtime)) as base_url:
        with pytest.raises(RuntimeError, match="404"):
            _introductions(base_url).read(obligation_ref="ee" * 32)

        _, obligation_ref, _ = await _accept_and_start(base_url, option)
        with pytest.raises(RuntimeError, match="403"):
            _introductions(base_url, OUTSIDER_SIGNER).read(obligation_ref=obligation_ref)



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
