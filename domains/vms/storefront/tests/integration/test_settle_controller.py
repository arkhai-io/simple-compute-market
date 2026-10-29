"""Integration tests for AdminSettleController.

Tests for POST /api/v1/admin/settle/{escrow_uid}/verify
and  POST /api/v1/admin/settle/{escrow_uid}/evaluate.

Both endpoints are dry-run (no DB writes). The verify endpoint reads the
escrow through the storefront's Alkahest client, the boundary to the chain,
which these tests replace with one answering as the SDK decodes an ERC-20
escrow on the development chain. The evaluate endpoint only needs SQLite
(inventory lookup) and is testable fully in-process.

Test structure mirrors test_listings_api.py — FastAPI in-process transport,
real SQLiteClient (tmp_path), real AdminSettleController wired via container.
"""
from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace
from typing import AsyncIterator

import httpx
import pytest
import pytest_asyncio
from fastapi import FastAPI
from market_alkahest.alkahest import (
    encode_recipient_demand,
    get_erc20_escrow_obligation_default,
    get_recipient_arbiter,
)
from market_alkahest.dev_chain import anvil_address_book_path
from market_alkahest.plans import materialize_settlement_plan_from_proposal
from market_core.schemas import (
    Agreement,
    EscrowProposal,
    SettlementOption,
    derive_settlement_option_id,
)
from market_identity import Ed25519Signer, Identity, TrustedIdentitySet

import market_storefront.container as _container
from market_storefront.controllers.settle_controller import admin_settle_router
from market_storefront.middleware.admin_identity import (
    administrator_identity_middleware,
    initialize_administrator_identities,
)
from market_storefront.domain_runtime import build_vm_storefront_domain, build_vm_storefront_registry
from market_storefront.utils.sqlite_client import SQLiteClient
from storefront_client.client import StorefrontClient, StorefrontClientError
from market_storefront.publication_binding import prepare_vm_listing_binding
from market_storefront.utils import config as storefront_config
from tests._settings_overrides import settings_overrides
from tests.fake_site import FakeSite, site_capacity

_TEST_SELLER_PRINCIPAL = Identity(
    scheme="eip191",
    identifier="0x2222222222222222222222222222222222222222",
)

_BUYER_PRINCIPAL = Ed25519Signer(b"\x53" * 32).identity

ADMIN_SIGNER = Ed25519Signer(b"\x51" * 32)
STOREFRONT_SIGNER = Ed25519Signer(b"\x52" * 32)
ADMINISTRATORS = TrustedIdentitySet(identities=(ADMIN_SIGNER.identity,))
STOREFRONT_AUTHORITIES = TrustedIdentitySet(
    identities=(STOREFRONT_SIGNER.identity,)
)


@pytest_asyncio.fixture
async def db(tmp_path):
    db_path = tmp_path / "settle_test.db"
    return SQLiteClient(
        db_path=str(db_path),
        registry=build_vm_storefront_registry(build_vm_storefront_domain()),
    )


async def _seed_listing(
    db: SQLiteClient,
    listing_id: str,
    *,
    resource_id: str | None = None,
    demands: list[dict] | None = None,
) -> None:
    """Seed a minimal compute listing into SQLite, or rewrite it in place."""
    now = datetime.now().isoformat()
    resource_id = resource_id or f"res-{listing_id}"
    await db.upsert_listing_with_binding(
        binding=prepare_vm_listing_binding(
            listing_id=listing_id,
            candidate={
                "capacity_backing": "backed",
                "site_id": "site-test",
                "pool_id": resource_id,
                "listing_shape": {"gpu": {"count": 1, "model": "H200"}},
            },
        ),
        status="open",
        created_at=now,
        updated_at=now,
        paused=False,
        listing_resource={
            "resource_id": resource_id,
            "gpu_model": "H200",
            "gpu_count": 1,
            "sla": 99.0,
            "region": "California, US",
            "offering_mode": "vm",
        },
        accepted_escrows=[{
            "chain_name": "anvil",
            "escrow_address": "0x" + "11" * 20,
            "literal_fields": {"token": "0x0000000000000000000000000000000000000001"},
            "rates": [{"field": "amount", "per": "hour", "value": "5000"}],
        }],
        demands=demands or [],
        fulfillment_resource=None,
        max_duration_seconds=3600,
        storefront_url="http://seller:8001",
        seller_principal=_TEST_SELLER_PRINCIPAL,
    )


@pytest.fixture
def capacity_site() -> FakeSite:
    return FakeSite(deliverable_modes={"vm"})


@pytest_asyncio.fixture
async def admin_client(
    db,
    capacity_site,
    monkeypatch,
) -> AsyncIterator[tuple[StorefrontClient, SQLiteClient]]:
    """Admin settle controller wired with real v2 identity authentication."""
    monkeypatch.setattr(
        "market_storefront.middleware.admin_identity.get_administrator_configs",
        lambda: {"integration-admin": ADMINISTRATORS},
    )
    initialize_administrator_identities(db.db_path)
    monkeypatch.setattr(_container, "resolved_alkahest_clients", {})
    _container.resolved_sqlite_client = db
    _container.resolved_marketplace_signer = STOREFRONT_SIGNER

    app = FastAPI()
    app.include_router(admin_settle_router)
    app.middleware("http")(administrator_identity_middleware)

    transport = httpx.ASGITransport(app=app)
    async with site_capacity(
        capacity_site,
        site_name="site-test",
        sqlite_client_factory=lambda: db,
    ):
        async with StorefrontClient(
            "http://test",
            signer=ADMIN_SIGNER,
            caller_role="admin",
            expected_publishers=STOREFRONT_AUTHORITIES,
            transport=transport,
        ) as c:
            yield c, db

    _container.resolved_sqlite_client = None
    _container.resolved_marketplace_signer = None


# ---------------------------------------------------------------------------
# POST /api/v1/admin/settle/{escrow_uid}/verify
# ---------------------------------------------------------------------------


# The development chain's address book and deterministic development addresses;
# never used on a public network.
_BOOK = str(anvil_address_book_path())
_SELLER_WALLET = "0x3C44CdDdB6a900fa2b585dd299e03d12FA4293BC"
_TOKEN = "0x" + "01" * 20
_AMOUNT = 5000
_EXPIRATION = 1_900_000_000


def _condition(recipient: str = _SELLER_WALLET) -> dict:
    return {
        "chain_name": "anvil",
        "arbiter": get_recipient_arbiter("anvil", config_path=_BOOK),
        "demand_data": {"recipient": recipient},
    }


def _proposal() -> EscrowProposal:
    return EscrowProposal(
        chain_name="anvil",
        escrow_address=get_erc20_escrow_obligation_default("anvil", config_path=_BOOK),
        fields={"token": _TOKEN, "amount": _AMOUNT},
        literal_fields={"token": _TOKEN},
        demand=_condition(),
        expiration_unix=_EXPIRATION,
    )


async def _accepted_deal(db: SQLiteClient, negotiation_id: str, listing_id: str) -> dict:
    """An accepted Alkahest deal on ``listing_id``, its plan committed as
    acceptance commits it; returns that plan."""
    proposal = _proposal()
    plan = materialize_settlement_plan_from_proposal(
        proposal=proposal,
        listing={"demands": [_condition()]},
        agreed_amount=_AMOUNT,
        duration_seconds=3600,
        addr_config_path=_BOOK,
    ).model_dump(mode="json")
    plan["buyer_principal"] = _BUYER_PRINCIPAL.model_dump(mode="json")
    plan["seller_principal"] = _TEST_SELLER_PRINCIPAL.model_dump(mode="json")
    await db.create_negotiation_thread(
        negotiation_id=negotiation_id,
        our_listing_id=listing_id,
        their_listing_id="",
        our_agent_id="seller-agent",
        their_agent_id="buyer-agent",
        buyer_principal=_BUYER_PRINCIPAL,
        seller_principal=_TEST_SELLER_PRINCIPAL,
        owner_id="seller-agent",
        buyer_escrow_proposal=proposal.model_dump(mode="json"),
    )
    option_body = {
        "mechanism": "alkahest.v1",
        "asset": _TOKEN,
        "rates": [],
        "params": {"accepted_escrow": {"chain_name": "anvil"}},
    }
    agreement = Agreement(
        negotiation_id=negotiation_id,
        listing_id=listing_id,
        listing_hash="0" * 64,
        buyer=_BUYER_PRINCIPAL.model_dump(mode="json"),
        seller=_TEST_SELLER_PRINCIPAL.model_dump(mode="json"),
        settlement=SettlementOption(
            option_id=derive_settlement_option_id(**option_body), **option_body
        ),
        amount=_AMOUNT,
        asset=_TOKEN,
        duration_seconds=3600,
        start_utc="2026-01-01T00:00:00Z",
        accepted_at="2026-01-01T00:00:00Z",
    )
    await db.commit_agreed_terms(
        negotiation_id=negotiation_id,
        agreed_price=_AMOUNT,
        agreed_duration_seconds=3600,
        agreement_bytes=agreement.model_dump_json(exclude_none=True).encode(),
        settlement_data={
            "accepted_escrow_proposal": proposal.model_dump(mode="json")
        },
    )
    await db.commit_settlement_plan(
        negotiation_id=negotiation_id,
        settlement_plan=plan,
        buyer_principal=_BUYER_PRINCIPAL,
        seller_principal=_TEST_SELLER_PRINCIPAL,
    )
    await db.update_negotiation_thread_terminal(
        negotiation_id=negotiation_id, terminal_state="success"
    )
    return plan


def _chain_answering(*, recipient: str = _SELLER_WALLET, amount: int = _AMOUNT):
    """The Alkahest client for the development chain, its escrow reads answering
    as the SDK decodes an ERC-20 escrow."""
    obligation = SimpleNamespace(
        arbiter=get_recipient_arbiter("anvil", config_path=_BOOK),
        demand=encode_recipient_demand(recipient),
        token=_TOKEN,
        amount=amount,
    )
    attestation = SimpleNamespace(revocation_time=0, expiration_time=_EXPIRATION)

    async def get_obligation(_uid):
        return {"attestation": attestation, "data": obligation}

    default = SimpleNamespace(get_obligation=get_obligation)
    return SimpleNamespace(erc20=SimpleNamespace(escrow=SimpleNamespace(default=default)))


@pytest.fixture
def anvil_book(monkeypatch):
    """The storefront's anvil chain, its book the development address book."""
    monkeypatch.setattr(
        storefront_config, "CHAINS", {"anvil": SimpleNamespace(name="anvil")}
    )
    with settings_overrides(**{"settlement.alkahest.address_books": {"anvil": _BOOK}}):
        yield


class TestVerifySettle:
    """POST /api/v1/admin/settle/{escrow_uid}/verify — escrow chain read dry-run."""

    async def test_unknown_negotiation_returns_404(self, admin_client):
        """No accepted negotiation → 404 before any chain read."""
        c, _ = admin_client
        with pytest.raises(StorefrontClientError) as exc_info:
            await c.verify_settle("some-escrow-uid", negotiation_id="does-not-exist")
        assert "404" in str(exc_info.value)

    async def test_an_escrow_funding_the_committed_plan_is_valid_after_the_listing_changed(
        self, admin_client, anvil_book, monkeypatch
    ):
        """The deal's listing now pays another wallet; the escrow funding the plan
        committed at acceptance still verifies, as settlement verifies it."""
        c, db = admin_client
        await _seed_listing(db, "settle-verify-1", demands=[_condition()])
        await _accepted_deal(db, "neg-verify-1", "settle-verify-1")
        # A development address standing for the seller's changed wallet.
        await _seed_listing(
            db, "settle-verify-1", demands=[_condition("0x" + "44" * 20)]
        )
        monkeypatch.setattr(
            _container, "resolved_alkahest_clients", {"anvil": _chain_answering()}
        )
        valid = await c.verify_settle("0xescrow-1", negotiation_id="neg-verify-1")
        monkeypatch.setattr(
            _container,
            "resolved_alkahest_clients",
            {"anvil": _chain_answering(amount=_AMOUNT - 1)},
        )
        underfunded = await c.verify_settle("0xescrow-1", negotiation_id="neg-verify-1")

        assert valid == {"valid": True, "escrow_uid": "0xescrow-1", "reason": None}
        assert underfunded["valid"] is False
        assert "amount" in underfunded["reason"]

    async def test_a_chain_this_storefront_does_not_configure_is_not_valid(
        self, admin_client, anvil_book
    ):
        c, db = admin_client
        await _seed_listing(db, "settle-verify-uid")
        await _accepted_deal(db, "neg-verify-uid", "settle-verify-uid")

        result = await c.verify_settle("echo-this-uid", negotiation_id="neg-verify-uid")

        assert result["valid"] is False
        assert result["escrow_uid"] == "echo-this-uid"
        assert "not configured" in result["reason"]

    async def test_no_db_writes_on_verify(self, admin_client, anvil_book, monkeypatch):
        """verify_settle must not create any settlement_jobs rows."""
        c, db = admin_client
        await _seed_listing(db, "settle-verify-nowrite")
        await _accepted_deal(db, "neg-verify-nowrite", "settle-verify-nowrite")
        monkeypatch.setattr(_container, "resolved_alkahest_clients", {"anvil": _chain_answering()})
        await c.verify_settle("no-write-uid", negotiation_id="neg-verify-nowrite")
        job = await db.load_escrow(escrow_uid="no-write-uid")
        assert job is None, (
            "verify_settle must not write settlement_jobs rows — it is a dry-run endpoint."
        )


# ---------------------------------------------------------------------------
# POST /api/v1/admin/settle/{escrow_uid}/evaluate
# ---------------------------------------------------------------------------


class TestEvaluateSettle:
    """POST /api/v1/admin/settle/{escrow_uid}/evaluate — provisioning job spec dry-run."""

    async def test_unknown_listing_returns_404(self, admin_client):
        """Listing not in DB → 404."""
        c, _ = admin_client
        with pytest.raises(StorefrontClientError) as exc_info:
            await c.evaluate_settle(
                "some-escrow-uid",
                listing_id="does-not-exist",
                ssh_public_key="",
                duration_seconds=3600,
            )
        assert "404" in str(exc_info.value)

    async def test_known_listing_no_inventory_returns_would_submit_false(self, admin_client):
        """Known listing but empty inventory → would_submit=False with reason."""
        c, db = admin_client
        await _seed_listing(db, "settle-eval-no-inv")
        result = await c.evaluate_settle(
            "eval-escrow-1",
            listing_id="settle-eval-no-inv",
            ssh_public_key="",
            duration_seconds=3600,
        )
        assert isinstance(result, dict)
        # No inventory registered → no host matches
        assert result.get("would_submit") is False
        assert result.get("escrow_uid") == "eval-escrow-1"
        assert result.get("reason")  # explains no matching host

    async def test_response_contains_escrow_uid(self, admin_client):
        """escrow_uid is always echoed back."""
        c, db = admin_client
        await _seed_listing(db, "settle-eval-echo")
        result = await c.evaluate_settle(
            "echo-escrow-uid",
            listing_id="settle-eval-echo",
        )
        assert result.get("escrow_uid") == "echo-escrow-uid"

    async def test_no_db_writes_on_evaluate(self, admin_client, capacity_site):
        """evaluate_settle must not create settlement_jobs rows or reserve inventory."""
        c, db = admin_client
        await _seed_listing(
            db,
            "settle-eval-nowrite",
            resource_id="r-eval-1",
        )

        capacity_site.add_resource(
            "r-eval-1",
            1,
            attributes={
                "gpu_model": "H200",
                "region": "California, US",
                "host_id": "host1",
            },
        )

        result = await c.evaluate_settle(
            "no-write-eval-uid",
            listing_id="settle-eval-nowrite",
            duration_seconds=3600,
        )
        assert result.get("would_submit") is True

        # Settlement job must not be created
        job = await db.load_escrow(escrow_uid="no-write-eval-uid")
        assert job is None, "evaluate_settle must not write settlement_jobs rows"

        # Evaluation reserves nothing at the site.
        assert capacity_site._available("r-eval-1") == 1

    async def test_with_matching_inventory_returns_would_submit_true(
        self,
        admin_client,
        capacity_site,
    ):
        """Listing + matching site resource → would_submit=True with host_id."""
        c, db = admin_client
        await _seed_listing(
            db,
            "settle-eval-match",
            resource_id="r-eval-match",
        )
        capacity_site.add_resource(
            "r-eval-match",
            1,
            attributes={
                "gpu_model": "H200",
                "region": "California, US",
                "host_id": "host-match",
            },
        )
        result = await c.evaluate_settle(
            "match-escrow-uid",
            listing_id="settle-eval-match",
            ssh_public_key="ssh-ed25519 AAAAC3 test@test",
            duration_seconds=3600,
        )

        assert result.get("would_submit") is True, (
            f"Expected would_submit=True with matching inventory. reason={result.get('reason')!r}"
        )
        assert result.get("host_id") == "host-match"
        assert "vm_target" not in result  # provisioning names the guest
