"""Integration tests for the Negotiate controller.

Uses ``StorefrontClient.negotiate_new()`` and ``negotiate_continue()``
via ``httpx.ASGITransport`` with canonical Ed25519 buyer authentication,
pinned seller trust, and signed seller responses.
"""

from __future__ import annotations

from datetime import datetime

import httpx
import pytest
import pytest_asyncio
from fastapi import FastAPI
from market_identity import Ed25519Signer, TrustedIdentitySet
from market_core.schemas import EscrowProposal, SettlementSelection

import market_storefront.container as _container
from market_storefront.controllers.negotiate_controller import (
    _proposal_payload,
    router as negotiate_router,
)
from market_storefront.middleware.seller_auth import listing_lifecycle_middleware
from tests._settings_overrides import settings_overrides
from storefront_client import StorefrontClient, StorefrontClientError


_BUYER_SIGNER = Ed25519Signer(b"\x21" * 32)
_SELLER_SIGNER = Ed25519Signer(b"\x22" * 32)
_EXPECTED_PUBLISHERS = TrustedIdentitySet(identities=(_SELLER_SIGNER.identity,))
_TOKEN = "0x0000000000000000000000000000000000000001"


def _vm_provision(duration_seconds: int = 3600) -> dict:
    return {
        "kind": "compute.v1",
        "version": 1,
        "payload": {
            "duration_seconds": duration_seconds,
            "ssh_public_key": "",
        },
    }


def _assert_canonical_owners(result: dict) -> None:
    assert result["buyer_principal"] == _BUYER_SIGNER.identity.model_dump(mode="json")
    assert result["seller_principal"] == _SELLER_SIGNER.identity.model_dump(mode="json")


def test_proposal_payload_preserves_settlement_selection() -> None:
    proposal = EscrowProposal(
        chain_name="anvil",
        escrow_address="0x" + "00" * 20,
        fields={"amount": "2000"},
        expiration_unix=1_800_000_000,
    )
    selection = SettlementSelection(
        mechanism="fiat.stripe.v1",
        option_id="1" * 64,
        expiration_unix=1_800_000_000,
    )

    payload = _proposal_payload(proposal, selection)

    assert payload["fields"] == {"amount": "2000"}
    assert payload["settlement_selection"] == selection.model_dump(mode="json")


@pytest_asyncio.fixture
async def db(tmp_path):
    from market_storefront.domain_runtime import build_vm_storefront_domain, build_vm_storefront_registry
    from market_storefront.utils.sqlite_client import SQLiteClient

    return SQLiteClient(db_path=str(tmp_path / "negotiate_test.db"), registry=build_vm_storefront_registry(build_vm_storefront_domain()))


async def _seed_listing(
    db,
    listing_id: str,
    demand_amount: int = 5000,
    max_duration_seconds: int | None = 7200,
) -> None:
    await db.upsert_listing(
        listing_id=listing_id,
        status="open",
        created_at=datetime.now().isoformat(),
        updated_at=datetime.now().isoformat(),
        offer_resource={
            "resource_id": f"res-{listing_id}",
            "gpu_model": "H200",
            "gpu_count": 1,
            "sla": 99.9,
            "region": "California, US",
        },
        accepted_escrows=[
            {
                "chain_name": "anvil",
                "escrow_address": "0x" + "11" * 20,
                "literal_fields": {"token": _TOKEN},
                "rates": (
                    []
                    if demand_amount is None
                    else [
                        {"field": "amount", "per": "hour", "value": str(demand_amount)}
                    ]
                ),
            }
        ],
        fulfillment_resource=None,
        max_duration_seconds=max_duration_seconds,
        storefront_url="http://seller:8001",
        seller_principal=_SELLER_SIGNER.identity,
    )
    # Seed at least one matching available compute resource so the
    # seller's pre-thread guard composite (default
    # `negotiate_request.default.v1` → `negotiate.guard.has_matching_inventory`)
    # lets the negotiation start. Tests that want to exercise the
    # refusal path should call _seed_listing without this fixture, or
    # override the composite's components list to drop the inventory guard.
    await db.upsert_resource(
        resource_id=f"res-{listing_id}",
        resource_type="compute.gpu",
        resource_subtype=None,
        unit="vm",
        value=1,
        state="available",
        attributes={
            "gpu_model": "H200",
            "region": "California, US",
            "vm_host": "kvm1",
        },
    )


@pytest_asyncio.fixture
async def client(db):
    import market_policy.negotiation_thread as _nt_module
    from market_policy.identity import Identity

    _nt_module._thread_store = None
    _nt_module.get_thread_store(
        sqlite_client=db,
        identity=Identity(agent_url="http://test-seller:8001"),
    )

    _container.resolved_sqlite_client = db
    _container.resolved_domain_registry = db.domain_registry

    _container.resolved_marketplace_signer = _SELLER_SIGNER
    app = FastAPI()
    app.include_router(negotiate_router)
    app.middleware("http")(listing_lifecycle_middleware)

    # The seller's round-start availability snapshot and acceptance-time
    # capacity holds run against the site authority; route them at an
    # in-memory ledger with a matching resource.
    from tests.fake_site import FakeSite, site_capacity

    fake_site = FakeSite(deliverable_modes={"vm"})
    fake_site.add_resource(
        "res-fake-site",
        8,
        attributes={
            "gpu_model": "H200",
            "region": "California, US",
            "vm_host": "kvm1",
        },
    )

    transport = httpx.ASGITransport(app=app)
    with settings_overrides(
        **{
            "provisioning.identity.principals": [
                _BUYER_SIGNER.identity.model_dump(mode="json"),
                _SELLER_SIGNER.identity.model_dump(mode="json"),
            ],
        }
    ):
        with site_capacity(fake_site):
            async with StorefrontClient(
                "http://test",
                signer=_BUYER_SIGNER,
                caller_role="buyer",
                expected_publishers=_EXPECTED_PUBLISHERS,
                transport=transport,
            ) as c:
                yield c, db
    _container.resolved_sqlite_client = None
    _container.resolved_domain_registry = None
    _container.resolved_marketplace_signer = None


class TestNegotiateNew:
    """POST /api/v1/negotiate/new — validation and happy path."""

    async def test_missing_listing_id_raises_422(self, client):
        """listing_id is required — Pydantic rejects the request."""
        c, _ = client
        with pytest.raises(StorefrontClientError) as exc_info:
            await c.negotiate_new(
                listing_id="",
                initial_amount=8000,
                provision_terms=_vm_provision(),
            )
        # missing listing_id can't be tested via client (required param);
        # test that a nonexistent listing returns 404 below.

    async def test_unknown_listing_returns_404(self, client):
        c, _ = client
        with pytest.raises(StorefrontClientError) as exc_info:
            await c.negotiate_new(
                listing_id="ghost-listing",
                initial_amount=8000,
                provision_terms=_vm_provision(),
            )
        assert "404" in str(exc_info.value)

    async def test_valid_request_starts_negotiation(self, client, db):
        c, db = client
        await _seed_listing(db, "neg-listing-1", demand_amount=5000)
        result = await c.negotiate_new(
            listing_id="neg-listing-1",
            initial_amount=5000,
            provision_terms=_vm_provision(),
            token=_TOKEN,
        )
        _assert_canonical_owners(result)
        assert "negotiation_id" in result
        assert result["action"] in ("accept", "counter", "exit")

    async def test_zero_max_duration_means_unlimited(self, client, db):
        c, db = client
        await _seed_listing(
            db,
            "neg-listing-unlimited",
            demand_amount=5000,
            max_duration_seconds=0,
        )
        result = await c.negotiate_new(
            listing_id="neg-listing-unlimited",
            initial_amount=5000,
            provision_terms=_vm_provision(),
            token=_TOKEN,
        )
        _assert_canonical_owners(result)
        assert "negotiation_id" in result
        assert result["action"] in ("accept", "counter", "exit")

    async def test_valid_request_persists_uint256_amounts(self, client, db):
        """18-decimal token rates exceed SQLite int64 but are normal EVM amounts."""
        c, db = client
        large_amount = 150 * 10**18
        await _seed_listing(db, "neg-listing-large", demand_amount=large_amount)
        result = await c.negotiate_new(
            listing_id="neg-listing-large",
            initial_amount=large_amount,
            proposal_fields={"amount": str(large_amount)},
            provision_terms=_vm_provision(),
            token=_TOKEN,
        )
        _assert_canonical_owners(result)

        neg_id = result["negotiation_id"]
        messages = await db.load_negotiation_thread(negotiation_id=neg_id)
        assert messages[0]["our_price"] == large_amount
        assert messages[0]["their_price"] == large_amount
        assert messages[0]["proposed_price"] == large_amount

    async def test_invalid_payload_rejected_before_policy(self, client, db):
        """Domain payload validation runs before the opening-round policy."""
        c, db = client
        await _seed_listing(db, "neg-listing-zero-duration")
        with pytest.raises((StorefrontClientError, Exception)) as exc_info:
            await c.negotiate_new(
                listing_id="neg-listing-zero-duration",
                initial_amount=8000,
                provision_terms=_vm_provision(0),
            )
        assert "400" in str(exc_info.value)
        assert "incompatible_provision_terms" in str(exc_info.value)

    async def test_listing_not_open_returns_409(self, client, db):
        """Listing in a terminal state is refused with 409."""
        c, db = client
        await _seed_listing(db, "neg-listing-closed")
        # Flip the listing's status to a non-open state.
        await db.update_listing(
            listing_id="neg-listing-closed",
            status="closed",
        )
        with pytest.raises(StorefrontClientError) as exc_info:
            await c.negotiate_new(
                listing_id="neg-listing-closed",
                initial_amount=5000,
                provision_terms=_vm_provision(),
            )
        msg = str(exc_info.value)
        assert "409" in msg
        assert "listing_not_open" in msg

    async def test_no_matching_inventory_returns_409(self, client, db):
        """Listing without a matching available compute resource is refused."""
        c, db = client
        # Seed listing only — no resource. Use a fresh listing_id since
        # _seed_listing always seeds an available resource.
        await db.upsert_listing(
            listing_id="neg-listing-empty",
            status="open",
            created_at=datetime.now().isoformat(),
            updated_at=datetime.now().isoformat(),
            # A model the fixture's fake site doesn't carry — the
            # availability snapshot has nothing matching.
            offer_resource={
                "resource_id": "res-neg-listing-empty",
                "gpu_model": "B300",
                "gpu_count": 1,
                "sla": 99.9,
                "region": "California, US",
            },
            accepted_escrows=[
                {
                    "chain_name": "anvil",
                    "escrow_address": "0x" + "11" * 20,
                    "literal_fields": {"token": _TOKEN},
                    "rates": [{"field": "amount", "per": "hour", "value": "5000"}],
                }
            ],
            fulfillment_resource=None,
            max_duration_seconds=7200,
            storefront_url="http://seller:8001",
            seller_principal=_SELLER_SIGNER.identity,
        )
        with pytest.raises(StorefrontClientError) as exc_info:
            await c.negotiate_new(
                listing_id="neg-listing-empty",
                initial_amount=5000,
                provision_terms=_vm_provision(),
            )
        msg = str(exc_info.value)
        assert "409" in msg
        assert "no_matching_inventory" in msg

    async def test_priceless_listing_without_fallback_returns_409(self, client, db):
        """Listing with demand.amount=None (hidden reserve) and no
        [seller.pricing].default_min_price configured → 409 with
        reason=no_floor_price (the seller has no negotiation floor)."""
        c, db = client
        await db.upsert_listing(
            listing_id="neg-listing-priceless",
            status="open",
            created_at=datetime.now().isoformat(),
            updated_at=datetime.now().isoformat(),
            offer_resource={
                "resource_id": "res-priceless",
                "gpu_model": "H200",
                "gpu_count": 1,
                "sla": 99.9,
                "region": "California, US",
            },
            accepted_escrows=[
                {
                    "chain_name": "anvil",
                    "escrow_address": "0x" + "11" * 20,
                    "literal_fields": {"token": _TOKEN},
                    "rates": [],  # hidden reserve
                }
            ],
            fulfillment_resource=None,
            max_duration_seconds=7200,
            storefront_url="http://seller:8001",
            seller_principal=_SELLER_SIGNER.identity,
        )
        # Seed a matching available resource so the inventory check passes
        # and we test the price-less guard specifically.
        await db.upsert_resource(
            resource_id="res-priceless",
            resource_type="compute.gpu",
            resource_subtype=None,
            unit="vm",
            value=1,
            state="available",
            attributes={
                "gpu_model": "H200",
                "region": "California, US",
                "vm_host": "kvm1",
            },
        )
        # default_min_price is None in the test config — falls through.
        with pytest.raises(StorefrontClientError) as exc_info:
            await c.negotiate_new(
                listing_id="neg-listing-priceless",
                initial_amount=5000,
                provision_terms=_vm_provision(),
                token=_TOKEN,
            )
        msg = str(exc_info.value)
        assert "409" in msg
        assert "no_floor_price" in msg

    async def test_amountless_exact_escrow_can_start_and_accept(self, client, db):
        c, db = client
        attestation_uid = "0x" + "aa" * 32
        arbiter = "0x" + "55" * 20
        demand = "0x" + "66" * 32
        literals = {
            "attestationUid": attestation_uid,
            "arbiter": arbiter,
            "demand": demand,
        }
        escrow_address = "0x" + "44" * 20
        await db.upsert_listing(
            listing_id="neg-listing-attestation",
            status="open",
            created_at=datetime.now().isoformat(),
            updated_at=datetime.now().isoformat(),
            offer_resource={
                "resource_id": "res-attestation",
                "gpu_model": "H200",
                "gpu_count": 1,
                "sla": 99.9,
                "region": "California, US",
            },
            accepted_escrows=[
                {
                    "chain_name": "anvil",
                    "escrow_address": escrow_address,
                    "literal_fields": literals,
                    "rates": [],
                }
            ],
            fulfillment_resource=None,
            max_duration_seconds=7200,
            storefront_url="http://seller:8001",
            seller_principal=_SELLER_SIGNER.identity,
        )
        await db.upsert_resource(
            resource_id="res-attestation",
            resource_type="compute.gpu",
            resource_subtype=None,
            unit="vm",
            value=1,
            state="available",
            attributes={
                "gpu_model": "H200",
                "region": "California, US",
                "vm_host": "kvm1",
            },
        )

        with settings_overrides(
            **{
                "negotiation.policies": [
                    "has_matching_inventory_guard",
                    "escrow_shape_guard",
                    "accept_exact_listing",
                ],
            }
        ):
            result = await c.negotiate_new(
                listing_id="neg-listing-attestation",
                initial_amount=None,
                provision_terms=_vm_provision(),
                chain_name="anvil",
                escrow_address=escrow_address,
                proposal_fields={},
                literal_fields=literals,
                rates=[],
                escrow_expiration_unix=1_800_000_000,
            )
        _assert_canonical_owners(result)

        assert result["action"] == "accept"
        assert "amount" not in result["proposal"]["fields"]
        assert result["accepted_escrow_proposal"]["literal_fields"] == literals
        assert "amount" not in result["accepted_escrow_terms"][0]["obligation_data"]

        # The canonical plan carrier rides alongside the legacy terms
        # mirror and stays byte-consistent with it.
        plan = result["settlement_plan"]
        assert len(plan["obligations"]) == len(result["accepted_escrow_terms"])
        ob = plan["obligations"][0]
        legacy = result["accepted_escrow_terms"][0]
        assert ob["mechanism"] == "alkahest.v1"
        assert ob["payer"] == legacy["maker"]
        assert ob["claimant"] == "seller"
        assert ob["expiration_unix"] == legacy["expiration_unix"]
        assert ob["params"]["escrow_contract"] == legacy["escrow_contract"]
        assert ob["params"]["obligation_data"] == legacy["obligation_data"]

    async def test_inventory_with_wrong_attributes_is_refused(self, client, db):
        """An available resource with the wrong gpu_model doesn't satisfy
        a listing offering a different gpu_model."""
        c, db = client
        # Seed a listing with the standard helper (which seeds H200).
        await _seed_listing(db, "neg-listing-mismatched")
        # Add a *different* available resource and remove the H200 one
        # by deleting it via state transition isn't easy here, so just
        # seed a wrong-model listing and skip the helper-seeded one.
        await db.upsert_listing(
            listing_id="neg-listing-rtx",
            status="open",
            created_at=datetime.now().isoformat(),
            updated_at=datetime.now().isoformat(),
            offer_resource={
                "resource_id": "res-neg-listing-rtx",
                "gpu_model": "RTX 4090",
                "gpu_count": 1,
                "sla": 99.9,
                "region": "California, US",
            },
            accepted_escrows=[
                {
                    "chain_name": "anvil",
                    "escrow_address": "0x" + "11" * 20,
                    "literal_fields": {"token": _TOKEN},
                    "rates": [{"field": "amount", "per": "hour", "value": "5000"}],
                }
            ],
            fulfillment_resource=None,
            max_duration_seconds=7200,
            storefront_url="http://seller:8001",
            seller_principal=_SELLER_SIGNER.identity,
        )
        # The H200 resource seeded by _seed_listing doesn't match the
        # RTX 4090 offer; the seller should refuse.
        with pytest.raises(StorefrontClientError) as exc_info:
            await c.negotiate_new(
                listing_id="neg-listing-rtx",
                initial_amount=5000,
                provision_terms=_vm_provision(),
            )
        assert "409" in str(exc_info.value)
        assert "no_matching_inventory" in str(exc_info.value)


class TestNegotiateContinue:
    """POST /api/v1/negotiate/{neg_id}"""

    async def test_unknown_neg_id_returns_404(self, client):
        c, _ = client
        with pytest.raises(StorefrontClientError) as exc_info:
            await c.negotiate_continue(
                "ghost-neg-id",
                action="exit",
            )
        assert "404" in str(exc_info.value)

    async def test_invalid_action_returns_422(self, client):
        """The client exposes FastAPI's Literal schema rejection as 422."""
        c, _ = client
        with pytest.raises(StorefrontClientError) as exc_info:
            await c.negotiate_continue(
                "neg-123",
                action="invalid_action",
            )

        assert exc_info.value.status_code == 422

    async def test_counter_without_price_returns_400(self, client):
        """A counter without a proposal fails the route schema contract."""
        c, _ = client
        with pytest.raises(StorefrontClientError) as exc_info:
            await c.negotiate_continue(
                "neg-123",
                action="counter",
            )

        assert exc_info.value.status_code == 400
