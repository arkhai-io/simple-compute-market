"""Integration tests for the Negotiate controller.

Uses ``StorefrontClient.negotiate_new()`` and ``negotiate_continue()``
via ``httpx.ASGITransport`` with canonical Ed25519 buyer authentication,
pinned seller trust, and signed seller responses.
"""

from __future__ import annotations


import asyncio
from datetime import datetime, timedelta
import sqlite3

import httpx
import pytest
import pytest_asyncio
from fastapi import FastAPI
from market_alkahest.alkahest import encode_recipient_demand, get_recipient_arbiter
from market_alkahest.dev_chain import anvil_address_book_path
from market_identity import Ed25519Signer, TrustedIdentitySet
from market_policy.negotiation_middleware import (
    NegotiationDecision,
    their_last_proposal,
)
from market_policy.seller_round import SellerRoundResult
from market_core.schemas import RateValue, SettlementOption, derive_settlement_option_id
from storefront_client import StorefrontClient, StorefrontClientError
from market_capacity_publication import RESOURCE_POOL, publication_binding

import market_storefront.container as _container
# The server module completes the controllers' import cycle; the admin
# controller, imported first, would be partially initialized.
import market_storefront.server  # noqa: F401  (import order, see above)
from market_storefront import lifecycle, lifecycle_steps
from market_storefront.controllers.admin_controller import router as admin_router
from market_storefront.utils.config import site_projection_poll_interval
import market_storefront.middleware.admin_identity as _admin_identity
from market_storefront.controllers.negotiations_controller import (
    router as negotiations_router,
)
from market_storefront.publication_binding import prepare_vm_listing_binding
from market_storefront.controllers.negotiate_controller import (
    router as negotiate_router,
)
from market_storefront.domain_runtime import (
    build_vm_storefront_domain,
    build_vm_storefront_registry,
)
from market_storefront.middleware.seller_auth import listing_lifecycle_middleware
from tests._settings_overrides import settings_overrides
from tests.fake_site import FakeProjectionSite, site_projection_state

_BUYER_SIGNER = Ed25519Signer(b"\x21" * 32)
_SELLER_SIGNER = Ed25519Signer(b"\x22" * 32)
_EXPECTED_PUBLISHERS = TrustedIdentitySet(identities=(_SELLER_SIGNER.identity,))
_TOKEN = "0x0000000000000000000000000000000000000001"
_RECIPIENT = "0x" + "33" * 20
#: The escrow contract seeded listings accept unless a test names another.
_ESCROW = "0x" + "11" * 20


def _recipient_condition(recipient: str) -> dict:
    """The recipient release condition on the anvil chain paying ``recipient``."""
    return {
        "chain_name": "anvil",
        "arbiter": get_recipient_arbiter(
            "anvil", config_path=str(anvil_address_book_path())
        ),
        "demand_data": {"recipient": recipient},
    }


#: The release condition a seeded listing authorizes: the recipient arbiter
#: paying the seller wallet the fixture configures. A buyer naming a pinned
#: escrow selects it, as the buyer builds its proposal from the listing.
_AUTHORIZED = [_recipient_condition(_RECIPIENT)]

#: An opening's escrow carrier for a seeded listing: its escrow, token, and
#: release condition, so the round's guards pass and a refusal under test is
#: that test's own.
_PINNED = {"token": _TOKEN, "escrow_address": _ESCROW, "demands": _AUTHORIZED}


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


@pytest_asyncio.fixture
async def db(tmp_path):
    from market_storefront.utils.sqlite_client import SQLiteClient

    return SQLiteClient(
        db_path=str(tmp_path / "negotiate_test.db"),
        registry=build_vm_storefront_registry(build_vm_storefront_domain()),
    )


# The site-test projection the storefront reads each listing's own source from.
# Seeding a listing declares its source here, as the site would.
_SITE_POOLS: list[dict] = []
# The site-test site serving ``_SITE_POOLS``, for tests that make it fail.
_PROJECTION_SITES: list[FakeProjectionSite] = []
# The fixture's recorded site requests, for tests asserting no site call.
_SITE_REQUESTS: list[list[str]] = []
# The fixture's application, for tests that also drive it as an administrator.
_APPS: list[FastAPI] = []
# Builds the fixture's negotiation runtime with other seller-round hooks.
_RUNTIME_BUILDERS: list = []
# A deterministic development key for these tests only; never used on any network.
_ADMIN_SIGNER = Ed25519Signer(b"\x31" * 32)


def _declare_source(
    listing_id: str,
    *,
    gpu_model: str,
    available_gpu_count: int,
    capacity_backing: str = "backed",
) -> None:
    _SITE_POOLS.append({
        "pool_id": f"pool-{listing_id}",
        "pool_metadata": {
            "enabled": True,
            "policy_tags": {
                "deliverable_modes": [] if capacity_backing == "unbacked" else ["vm"],
                "advertisable_modes": ["vm"],
                "capacity_backing": capacity_backing,
                "region": "California, US",
            },
        },
        "resources": [{
            "physical_resource_id": f"res-{listing_id}", "resource_type": "compute.gpu",
            "enabled": True,
            "capacity": {"gpu_count": 8},
            "available": {"gpu_count": available_gpu_count},
            # A claim matches region against the declaration itself.
            "attributes": {"gpu_model": gpu_model, "region": "California, US"},
        }],
    })


def _site_projections():
    """The storefront's projection state over the site-test site serving
    ``_SITE_POOLS``, holding nothing until polled."""
    _SITE_POOLS.clear()
    site = FakeProjectionSite(resource_pools=_SITE_POOLS)
    _PROJECTION_SITES[:] = [site]
    return site_projection_state({"site-test": site})


def _unheld_site_projections():
    """A state over a site-test site that has never answered, as a storefront
    restarted while its site cannot be reached holds it."""
    site = FakeProjectionSite(resource_pools=[])
    site.failing = True
    return site_projection_state({"site-test": site})


async def _upsert_bound_listing(
    db,
    listing_id: str,
    *,
    demand_amount: int | None = 5000,
    max_duration_seconds: int | None = 7200,
    gpu_model: str = "H200",
    declared_gpu_model: str = "H200",
    available_gpu_count: int = 8,
    capacity_backing: str = "backed",
    escrow_address: str = "0x" + "11" * 20,
    literal_fields: dict | None = None,
    demands: list[dict] | None = _AUTHORIZED,
    extra_rates: tuple[dict, ...] = (),
    unpriced_escrow_address: str | None = None,
) -> None:
    """Seed an open bound listing with one priced Alkahest option, and with a
    second, unpriced one on ``unpriced_escrow_address`` when it is given."""
    _declare_source(
        listing_id,
        gpu_model=declared_gpu_model,
        available_gpu_count=available_gpu_count,
        capacity_backing=capacity_backing,
    )
    # The poller's cycle: the storefront now holds the source just declared.
    await _container.site_projections().poll_once()
    pool_id = f"pool-{listing_id}"
    # Bound as publication binds it: the listing's shape and the resource it
    # publishes, so every reader finds the listing's key in its binding.
    binding = prepare_vm_listing_binding(
        listing_id=listing_id,
        candidate={
            "site_id": "site-test",
            "pool_id": pool_id,
            "resource_id": f"res-{listing_id}",
            "capacity_backing": capacity_backing,
            "listing_shape": {"gpu": {"count": 1, "model": gpu_model}},
        },
    )
    entry = {
        "chain_name": "anvil", "escrow_address": escrow_address,
        "literal_fields": {"token": _TOKEN} if literal_fields is None else dict(literal_fields),
        "rates": ([] if demand_amount is None else [
            {"field": "amount", "per": "hour", "value": str(demand_amount)}
        ]) + list(extra_rates),
    }
    entries = [entry]
    if unpriced_escrow_address is not None:
        entries.append({
            "chain_name": "anvil", "escrow_address": unpriced_escrow_address,
            "literal_fields": {"token": _TOKEN}, "rates": [],
        })
    options = []
    for each in entries:
        body = {"mechanism": "alkahest.v1", "asset": _TOKEN,
                "rates": [RateValue.model_validate(rate) for rate in each["rates"]],
                "params": {"accepted_escrow": each}}
        options.append(
            SettlementOption(option_id=derive_settlement_option_id(**body), **body)
        )
    await db.upsert_listing_with_binding(
        binding=binding,
        settlement_options=[option.model_dump(mode="json") for option in options],
        status="open",
        created_at=datetime.now().isoformat(),
        updated_at=datetime.now().isoformat(),
        listing_resource={
            "resource_id": f"res-{listing_id}",
            "gpu_model": gpu_model,
            "gpu_count": 1,
            "sla": 99.9,
            "region": "California, US",
            "offering_mode": "vm",
        },
        accepted_escrows=[
            {
                "chain_name": "anvil",
                "escrow_address": escrow_address,
                "literal_fields": (
                    {"token": _TOKEN}
                    if literal_fields is None
                    else dict(literal_fields)
                ),
                "rates": (
                    []
                    if demand_amount is None
                    else [
                        {"field": "amount", "per": "hour", "value": str(demand_amount)}
                    ]
                ),
            },
            *(dict(each) for each in entries[1:]),
        ],
        fulfillment_resource=None,
        max_duration_seconds=max_duration_seconds,
        storefront_url="http://seller:8001",
        seller_principal=_SELLER_SIGNER.identity,
        demands=demands,
    )


async def _selection(db, listing_id, index: int = 0):
    listing = await db.load_listing(listing_id=listing_id)
    return {"mechanism": "alkahest.v1",
            "option_id": listing["settlement_options"][index]["option_id"],
            "expiration_unix": 1_800_000_000}


async def _seed_listing(
    db,
    listing_id: str,
    demand_amount: int | None = 5000,
    max_duration_seconds: int | None = 7200,
) -> None:
    await _upsert_bound_listing(
        db,
        listing_id,
        demand_amount=demand_amount,
        max_duration_seconds=max_duration_seconds,
    )


@pytest_asyncio.fixture
async def client(db, monkeypatch):
    import market_policy.negotiation_thread as _nt_module
    from market_config.config_loader import ChainConfig
    from market_policy.identity import Identity

    import market_storefront.negotiation_runtime as _negotiation_runtime

    _nt_module._thread_store = None
    _nt_module.get_thread_store(
        sqlite_client=db,
        identity=Identity(agent_url="http://test-seller:8001"),
    )

    _container.resolved_sqlite_client = db
    _container.resolved_domain_registry = db.domain_registry
    _container.resolved_marketplace_signer = _SELLER_SIGNER
    monkeypatch.setattr(
        _admin_identity,
        "get_administrator_configs",
        lambda: {"operator": TrustedIdentitySet(identities=(_ADMIN_SIGNER.identity,))},
    )
    _admin_identity.initialize_administrator_identities(db.db_path)
    app = FastAPI()
    app.include_router(negotiate_router)
    app.include_router(negotiations_router)
    # The lifecycle routes, for tests that hold the loops and step them.
    app.include_router(admin_router)
    app.middleware("http")(listing_lifecycle_middleware)
    app.middleware("http")(_admin_identity.administrator_identity_middleware)
    _APPS[:] = [app]

    # The injected seller-round and acceptance-hold collaborator runs against
    # an in-memory site ledger with the same exact durable site binding.
    from tests.fake_site import FakeSite, capacity_runtime_over

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
    address_config_path = anvil_address_book_path()
    monkeypatch.setattr(
        _negotiation_runtime,
        "CHAINS",
        {
            "anvil": ChainConfig(
                name="anvil",
                rpc_url="http://anvil.test",
                chain_id=31337,
                alkahest_address_config_path=str(address_config_path),
            )
        },
    )

    site_requests: list[str] = []
    original_handle = fake_site._handle

    def _recording_handle(request):
        site_requests.append(f"{request.method} {request.url.path}")
        return original_handle(request)

    fake_site._handle = _recording_handle
    _SITE_REQUESTS[:] = []
    _SITE_REQUESTS.append(site_requests)
    capacity_runtime = capacity_runtime_over(fake_site, site_name="site-test")

    async def capacity_binding_for_listing(repository, listing_id):
        assert repository is db
        listing_binding = await repository.load_listing_binding(listing_id=listing_id)
        assert listing_binding is not None
        return publication_binding(
            capacity_backing=listing_binding.capacity_backing,
            site_id=listing_binding.site_id,
            offering_mode=listing_binding.binding.offering_mode,
            source_id=str(listing_binding.pool_id),
        )

    monkeypatch.setattr(
        "market_storefront.negotiation_runtime.capacity_binding_for_listing",
        capacity_binding_for_listing,
    )
    registration = db.domain_registry.resolve_mode("vm")
    site_projections = _site_projections()
    monkeypatch.setattr(_container, "resolved_site_projections", site_projections)

    def build_runtime(*, projections=site_projections, **hooks):
        return _negotiation_runtime.build_vm_negotiation_runtime(
            registration.contract,
            registry=db.domain_registry,
            binding=registration.binding,
            capacity_runtime=capacity_runtime,
            site_projections=projections,
            **hooks,
        )

    _RUNTIME_BUILDERS[:] = [build_runtime]
    _container.resolved_negotiation_runtime = build_runtime()
    transport = httpx.ASGITransport(app=app)
    with settings_overrides(
        **{
            "wallet.address": _RECIPIENT,
        }
    ):
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
    _container.resolved_negotiation_runtime = None
    _container.resolved_marketplace_signer = None


class TestNegotiateNew:
    """POST /api/v1/negotiate/new — validation and happy path."""

    async def test_missing_listing_id_raises_422(self, client):
        """listing_id is required — Pydantic rejects the request."""
        c, _ = client
        with pytest.raises(StorefrontClientError):
            await c.negotiate_new(
                listing_id="",
                initial_amount=8000,
                provision_terms=_vm_provision(),
                **_PINNED,
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
                **_PINNED,
            )
        assert "404" in str(exc_info.value)

    async def test_valid_request_starts_negotiation(self, client, db):
        c, db = client
        await _seed_listing(db, "neg-listing-1", demand_amount=5000)
        result = await c.negotiate_new(
            listing_id="neg-listing-1",
            settlement_selection=await _selection(db, "neg-listing-1"),
            initial_amount=5000,
            provision_terms=_vm_provision(),
            token=_TOKEN,
            chain_name="anvil",
            escrow_address="0x" + "11" * 20,
            demands=_AUTHORIZED,
        )
        _assert_canonical_owners(result)
        assert "negotiation_id" in result
        assert result["action"] in ("accept", "counter", "exit")

    async def test_selectionless_proposal_is_not_implicitly_accepted_as_alkahest(self, client, db):
        c, db = client
        await _seed_listing(db, "neg-missing-selection", demand_amount=5000)
        with pytest.raises(StorefrontClientError) as error:
            await c.negotiate_new(
                listing_id="neg-missing-selection", initial_amount=5000,
                provision_terms=_vm_provision(), token=_TOKEN, chain_name="anvil",
                escrow_address="0x" + "11" * 20, demands=_AUTHORIZED,
            )
        assert error.value.status_code == 409
        assert "settlement_mechanism_required" in str(error.value)
        with sqlite3.connect(db.db_path) as conn:
            assert conn.execute("SELECT COUNT(*) FROM negotiation_threads WHERE agreement_bytes IS NOT NULL").fetchone()[0] == 0
            assert conn.execute("SELECT COUNT(*) FROM vm_settlement_evidence").fetchone()[0] == 0

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
            settlement_selection=await _selection(db, "neg-listing-unlimited"),
            initial_amount=5000,
            provision_terms=_vm_provision(),
            token=_TOKEN,
            chain_name="anvil",
            escrow_address="0x" + "11" * 20,
            demands=_AUTHORIZED,
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
            settlement_selection=await _selection(db, "neg-listing-large"),
            initial_amount=large_amount,
            proposal_fields={"amount": str(large_amount)},
            provision_terms=_vm_provision(),
            token=_TOKEN,
            chain_name="anvil",
            escrow_address="0x" + "11" * 20,
            demands=_AUTHORIZED,
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
                **_PINNED,
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
            closed_by="seller",
        )
        with pytest.raises(StorefrontClientError) as exc_info:
            await c.negotiate_new(
                listing_id="neg-listing-closed",
                initial_amount=5000,
                provision_terms=_vm_provision(),
                **_PINNED,
            )
        msg = str(exc_info.value)
        assert "409" in msg
        assert "listing_not_open" in msg

    async def test_listing_its_source_does_not_declare_returns_409(self, client, db):
        """A listing publishing a model its own source does not declare is refused."""
        c, db = client
        await _upsert_bound_listing(
            db,
            "neg-listing-empty",
            gpu_model="B300",
        )
        with pytest.raises(StorefrontClientError) as exc_info:
            await c.negotiate_new(
                listing_id="neg-listing-empty",
                initial_amount=5000,
                provision_terms=_vm_provision(),
                **_PINNED,
            )
        msg = str(exc_info.value)
        assert "409" in msg
        assert "no_matching_declaration" in msg

    async def test_backed_listing_with_nothing_free_returns_409(self, client, db):
        """A listing its source still declares, with nothing free, is refused.

        The declared match passes, so the refusal is the availability reason,
        not the declared-match one.
        """
        c, db = client
        await _upsert_bound_listing(
            db,
            "neg-listing-taken",
            available_gpu_count=0,
        )
        with pytest.raises(StorefrontClientError) as exc_info:
            await c.negotiate_new(
                listing_id="neg-listing-taken",
                initial_amount=5000,
                provision_terms=_vm_provision(),
                **_PINNED,
            )
        msg = str(exc_info.value)
        assert "409" in msg
        assert "no_matching_inventory" in msg

    async def test_priceless_listing_without_fallback_returns_409(self, client, db):
        """A bound amountless listing without a configured floor is refused."""
        c, db = client
        await _upsert_bound_listing(
            db,
            "neg-listing-priceless",
            demand_amount=None,
        )
        # default_min_price is None in the test config — falls through.
        with pytest.raises(StorefrontClientError) as exc_info:
            await c.negotiate_new(
                listing_id="neg-listing-priceless",
                initial_amount=5000,
                provision_terms=_vm_provision(),
                **_PINNED,
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
        await _upsert_bound_listing(
            db,
            "neg-listing-attestation",
            demand_amount=None,
            escrow_address=escrow_address,
            literal_fields=literals,
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
                settlement_selection=await _selection(db, "neg-listing-attestation"),
                initial_amount=None,
                provision_terms=_vm_provision(),
                chain_name="anvil",
                escrow_address=escrow_address,
                proposal_fields={},
                literal_fields=literals,
                rates=[],
                escrow_expiration_unix=1_800_000_000,
                demands=_AUTHORIZED,
            )
        _assert_canonical_owners(result)

        assert result["action"] == "accept"
        assert "amount" not in result["proposal"]["fields"]
        assert result["accepted_escrow_proposal"]["literal_fields"] == literals

        # The plan is the seller's committed copy; no escrow terms ride beside
        # it for a buyer to fund in place of its own derivation.
        assert "accepted_escrow_terms" not in result
        (ob,) = result["settlement_plan"]["obligations"]
        assert ob["mechanism"] == "alkahest.v1"
        assert ob["payer"] == "buyer"
        assert ob["claimant"] == "seller"
        assert ob["expiration_unix"] == 1_800_000_000
        assert ob["params"]["escrow_contract"].lower() == escrow_address.lower()
        assert "amount" not in ob["params"]["obligation_data"]

    async def test_inventory_with_wrong_attributes_is_refused(self, client, db):
        """An available resource with the wrong gpu_model doesn't satisfy
        a listing offering a different gpu_model."""
        c, db = client
        # Seed a listing with the standard helper (which seeds H200).
        await _seed_listing(db, "neg-listing-mismatched")
        # Add a *different* available resource and remove the H200 one
        # by deleting it via state transition isn't easy here, so just
        # seed a wrong-model listing and skip the helper-seeded one.
        await _upsert_bound_listing(
            db,
            "neg-listing-rtx",
            gpu_model="RTX 4090",
        )
        # The H200 resource seeded by _seed_listing doesn't match the
        # RTX 4090 listing_resource; the seller should refuse.
        with pytest.raises(StorefrontClientError) as exc_info:
            await c.negotiate_new(
                listing_id="neg-listing-rtx",
                initial_amount=5000,
                provision_terms=_vm_provision(),
                **_PINNED,
            )
        assert "409" in str(exc_info.value)
        assert "no_matching_declaration" in str(exc_info.value)


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


class TestCounterNamingAnotherOption:
    """An acceptance settles the buyer's opening, so a counter naming another
    option changes neither what is priced nor what is accepted."""

    async def test_a_counter_selecting_an_unpriced_option_is_not_accepted_at_its_amount(
        self, client, db
    ):
        c, db = client
        await _upsert_bound_listing(
            db, "neg-two-options", demand_amount=5000,
            unpriced_escrow_address="0x" + "22" * 20,
        )
        opened = await c.negotiate_new(
            listing_id="neg-two-options",
            settlement_selection=await _selection(db, "neg-two-options"),
            initial_amount=4000,
            provision_terms=_vm_provision(),
            token=_TOKEN,
            chain_name="anvil",
            escrow_address=_ESCROW,
            demands=_AUTHORIZED,
        )
        assert opened["action"] == "counter", opened

        countered = await c.negotiate_continue(
            opened["negotiation_id"],
            action="counter",
            proposal={"fields": {"amount": "1"}},
            settlement_selection=await _selection(db, "neg-two-options", index=1),
        )

        assert countered["action"] != "accept"
        with sqlite3.connect(db.db_path) as conn:
            assert conn.execute(
                "SELECT COUNT(*) FROM negotiation_threads "
                "WHERE agreement_bytes IS NOT NULL OR settlement_plan IS NOT NULL"
            ).fetchone()[0] == 0

    async def test_a_continuation_after_its_option_is_repriced_is_refused_naming_it(
        self, client, db
    ):
        """A publication cycle repricing the opening's option changes its
        identity, so the round is refused by name rather than decided against a
        zero reference."""
        c, db = client
        await _upsert_bound_listing(db, "neg-repriced", demand_amount=5000)
        opened = await c.negotiate_new(
            listing_id="neg-repriced",
            settlement_selection=await _selection(db, "neg-repriced"),
            initial_amount=4000,
            provision_terms=_vm_provision(),
            token=_TOKEN,
            chain_name="anvil",
            escrow_address=_ESCROW,
            demands=_AUTHORIZED,
        )
        assert opened["action"] == "counter", opened
        repriced_entry = {
            "chain_name": "anvil", "escrow_address": _ESCROW,
            "literal_fields": {"token": _TOKEN},
            "rates": [{"field": "amount", "per": "hour", "value": "6000"}],
        }
        body = {"mechanism": "alkahest.v1", "asset": _TOKEN,
                "rates": [RateValue.model_validate(rate) for rate in repriced_entry["rates"]],
                "params": {"accepted_escrow": repriced_entry}}
        repriced = SettlementOption(option_id=derive_settlement_option_id(**body), **body)
        await db.update_listing(
            listing_id="neg-repriced",
            settlement_options=[repriced.model_dump(mode="json")],
            accepted_escrows=[repriced_entry],
        )

        countered = await c.negotiate_continue(
            opened["negotiation_id"],
            action="counter",
            proposal={"fields": {"amount": "4500"}},
        )

        assert countered["action"] == "reject"
        assert countered["reason"].startswith("pinned_option_withdrawn")


class TestUnbackedListingNegotiation:
    async def test_an_unbacked_listing_negotiates_to_acceptance_without_the_site(
        self, client, db
    ):
        """An unbacked listing enters the ordinary negotiation lifecycle.

        The inventory guard checks it against its declaration only, acceptance
        builds its settlement artifacts, and nothing asks the site anything: no
        availability read and no capacity hold, even with holds enabled.
        """
        c, db = client
        escrow_address = "0x" + "44" * 20
        await _upsert_bound_listing(
            db,
            "neg-listing-unbacked",
            demand_amount=None,
            escrow_address=escrow_address,
            capacity_backing="unbacked",
            available_gpu_count=0,
        )
        (site_requests,) = _SITE_REQUESTS
        site_requests.clear()

        with settings_overrides(
            **{
                "negotiation.policies": [
                    "has_matching_inventory_guard",
                    "escrow_shape_guard",
                    "accept_exact_listing",
                ],
                "capacity.hold_ttl_seconds": 900,
            }
        ):
            result = await c.negotiate_new(
                listing_id="neg-listing-unbacked",
                settlement_selection=await _selection(db, "neg-listing-unbacked"),
                initial_amount=None,
                provision_terms=_vm_provision(),
                chain_name="anvil",
                escrow_address=escrow_address,
                proposal_fields={},
                literal_fields={"token": _TOKEN},
                rates=[],
                escrow_expiration_unix=1_800_000_000,
                demands=_AUTHORIZED,
            )

        assert result["action"] == "accept"
        assert result["settlement_plan"]["obligations"]
        assert "accepted_escrow_terms" not in result
        assert site_requests == []
        assert await db.load_capacity_hold(negotiation_id=result["negotiation_id"]) is None

    async def test_an_unbacked_listing_its_declaration_no_longer_supports_is_refused(
        self, client, db
    ):
        c, db = client
        await _upsert_bound_listing(
            db,
            "neg-listing-unbacked-shrunk",
            capacity_backing="unbacked",
            gpu_model="B300",
        )
        (site_requests,) = _SITE_REQUESTS
        site_requests.clear()

        with pytest.raises(StorefrontClientError) as exc_info:
            await c.negotiate_new(
                listing_id="neg-listing-unbacked-shrunk",
                initial_amount=5000,
                provision_terms=_vm_provision(),
                **_PINNED,
            )

        assert "no_matching_declaration" in str(exc_info.value)
        assert site_requests == []


class TestAdministrativeAcceptance:
    """Force-accept, sent through the canonical administrator client, goes
    through the runtime's acceptance, so the domain's hold is attempted and its
    accepted settlement artifacts recorded exactly as after a negotiated
    acceptance."""

    async def test_force_accept_records_the_hold_and_settlement_plan(
        self, client, db
    ):
        c, db = client
        await _seed_listing(db, "neg-listing-force", demand_amount=5000)
        with settings_overrides(**{"capacity.hold_ttl_seconds": 900}):
            opened = await c.negotiate_new(
                listing_id="neg-listing-force",
                settlement_selection=await _selection(db, "neg-listing-force"),
                initial_amount=4500,
                provision_terms=_vm_provision(),
                token=_TOKEN,
                chain_name="anvil",
                escrow_address="0x" + "11" * 20,
                escrow_expiration_unix=1_800_000_000,
                demands=_AUTHORIZED,
            )
            assert opened["action"] == "counter"
            negotiation_id = opened["negotiation_id"]
            (site_requests,) = _SITE_REQUESTS
            site_requests.clear()

            (app,) = _APPS
            async with StorefrontClient(
                "http://test",
                signer=_ADMIN_SIGNER,
                caller_role="admin",
                expected_publishers=_EXPECTED_PUBLISHERS,
                transport=httpx.ASGITransport(app=app),
            ) as admin:
                accepted = await admin.force_accept_negotiation(
                    "neg-listing-force", negotiation_id, amount=5000
                )

        assert accepted.action == "accept"
        assert accepted.amount == 5000
        thread = await db.load_negotiation_thread_row(negotiation_id=negotiation_id)
        plan = thread["settlement_plan"]
        assert plan["obligations"][0]["mechanism"] == "alkahest.v1"
        assert thread["terminal_state"] == "success"
        assert int(thread["agreed_price"]) == 5000
        # The acceptance hold reserves at the listing's site, as it does after
        # a negotiated acceptance.
        assert any("reserv" in request for request in site_requests), site_requests


@pytest_asyncio.fixture
async def held_loops(client):
    """The site-projection poller's timer registered as startup registers it
    and started held, so no poll runs unless an operator steps one; it is
    cancelled and awaited afterwards."""
    await lifecycle.reset_for_tests()
    lifecycle.controller().request_pause(True)
    lifecycle.register_loop(
        lifecycle.SITE_PROJECTION_POLLER,
        route="site-projections",
        step=lifecycle_steps.site_projections_step,
        interval_seconds=site_projection_poll_interval(),
    )
    lifecycle.start_loops()
    yield
    await lifecycle.reset_for_tests()


def _admin_client() -> StorefrontClient:
    (app,) = _APPS
    return StorefrontClient(
        "http://test",
        signer=_ADMIN_SIGNER,
        caller_role="admin",
        expected_publishers=_EXPECTED_PUBLISHERS,
        transport=httpx.ASGITransport(app=app),
    )


class TestSourceConfirmationWindow:
    """A source check confirms a listing only from a projection a poll
    confirmed within the source-confirmation window, so a storefront whose
    loops are held while it trades refuses rather than judging on projections
    nobody polls."""

    async def test_a_round_past_the_window_is_retryable_until_the_projection_is_stepped(
        self, client, db, held_loops
    ):
        """Spec scenario "The loops are held past the confirmation window".

        The runtime measures each check at a clock the test sets: first at an
        instant past the window since the seeding poll, while the held poller
        has polled nothing; then a second after the poll the operator's step
        ran, which the test confirms happened."""
        c, db = client
        await _seed_listing(db, "neg-window")
        state = _container.site_projections()
        (site,) = _PROJECTION_SITES
        seeded = state.view("site-test", RESOURCE_POOL).fetched_at
        now = {"at": seeded + timedelta(seconds=61)}

        (build_runtime,) = _RUNTIME_BUILDERS
        _container.resolved_negotiation_runtime = build_runtime(
            source_confirmation_clock=lambda: now["at"]
        )
        opening = dict(
            listing_id="neg-window",
            settlement_selection=await _selection(db, "neg-window"),
            initial_amount=4000,
            provision_terms=_vm_provision(),
            **_PINNED,
        )
        with settings_overrides(**{"capacity.source_confirmation_seconds": 60}):
            async with _admin_client() as admin:
                held = await admin.admin_pause_lifecycle_loops()
                assert held["loops"][lifecycle.SITE_PROJECTION_POLLER] == "paused"

                with pytest.raises(StorefrontClientError) as refused:
                    await c.negotiate_new(**opening)
                assert refused.value.status_code == 503
                assert "listing_source_unverifiable" in str(refused.value)
                assert state.view("site-test", RESOURCE_POOL).fetched_at == seeded

                calls = len(site.calls)
                await admin.admin_run_lifecycle_cycle("site-projections")
                stepped = state.view("site-test", RESOURCE_POOL).fetched_at
                assert "resource_pool.version" in site.calls[calls:]
                assert stepped > seeded
                now["at"] = stepped + timedelta(seconds=1)
                opened = await c.negotiate_new(**opening)

                still_held = await admin.admin_pause_lifecycle_loops()

        assert opened["action"] == "counter"
        assert still_held["loops"][lifecycle.SITE_PROJECTION_POLLER] == "paused"

    async def test_an_unbacked_listings_stale_site_is_retryable(self, client, db):
        """Spec scenario "An unbacked listing's site is stale": the retained
        generation still declares the listing's source, but its latest poll
        failed, and nothing else backs an unbacked listing."""
        c, db = client
        await _upsert_bound_listing(db, "neg-unbacked-stale", capacity_backing="unbacked")
        (site,) = _PROJECTION_SITES
        site.failing = True
        await _container.site_projections().poll_once()
        (site_requests,) = _SITE_REQUESTS
        site_requests.clear()

        with pytest.raises(StorefrontClientError) as refused:
            await c.negotiate_new(
                listing_id="neg-unbacked-stale",
                settlement_selection=await _selection(db, "neg-unbacked-stale"),
                initial_amount=4000,
                provision_terms=_vm_provision(),
                **_PINNED,
            )

        assert refused.value.status_code == 503
        assert "listing_source_unverifiable" in str(refused.value)
        assert site_requests == []


class TestAcceptanceRechecksTheSource:
    """A buyer's accept rechecks the listing against its source, as a round does.

    The negotiation opens while the source matches, so the seller counters; the
    source then changes, or becomes unreadable, before the buyer accepts.
    """

    async def _open_countered(self, c, db, listing_id: str) -> str:
        await _upsert_bound_listing(db, listing_id)
        opened = await c.negotiate_new(
            listing_id=listing_id,
            settlement_selection=await _selection(db, listing_id),
            initial_amount=4000,
            provision_terms=_vm_provision(),
            **_PINNED,
        )
        assert opened["action"] == "counter"
        return opened["negotiation_id"]

    async def test_an_accept_after_the_source_changed_is_refused(self, client, db):
        c, db = client
        negotiation_id = await self._open_countered(c, db, "neg-recheck-changed")
        (pool,) = [p for p in _SITE_POOLS if p["pool_id"] == "pool-neg-recheck-changed"]
        pool["resources"][0]["attributes"]["gpu_model"] = "B300"

        with pytest.raises(StorefrontClientError) as refused:
            await c.negotiate_continue(negotiation_id, action="accept")

        assert refused.value.status_code == 409
        assert "no_matching_declaration" in str(refused.value)
        thread = await db.load_negotiation_thread_row(negotiation_id=negotiation_id)
        assert thread["terminal_state"] is None
        assert thread["agreed_at"] is None

    async def test_an_accept_whose_source_cannot_be_read_is_retryable(self, client, db):
        c, db = client
        negotiation_id = await self._open_countered(c, db, "neg-recheck-unread")
        # Restarted while the site cannot be reached: nothing is held for it.
        (build_runtime,) = _RUNTIME_BUILDERS
        _container.resolved_negotiation_runtime = build_runtime(
            projections=_unheld_site_projections()
        )

        with pytest.raises(StorefrontClientError) as refused:
            await c.negotiate_continue(negotiation_id, action="accept")

        assert refused.value.status_code == 503
        assert "listing_source_unverifiable" in str(refused.value)

    async def test_a_buyer_exits_whatever_the_source(self, client, db):
        c, db = client
        negotiation_id = await self._open_countered(c, db, "neg-recheck-exit")
        (build_runtime,) = _RUNTIME_BUILDERS
        _container.resolved_negotiation_runtime = build_runtime(
            projections=_unheld_site_projections()
        )

        result = await c.negotiate_continue(negotiation_id, action="exit")

        assert result["action"] == "exit"


#: A recipient other than the seller wallet the listing's condition pays.
_BUYER_RECIPIENT = "0x" + "77" * 20


async def _accept_as_proposed(*, listing, history, **_round):
    """A seller policy that accepts the buyer's proposal as it stands."""
    proposal = their_last_proposal(history)
    return SellerRoundResult(
        our_amount=5000,
        strategy_label="maximize",
        direction="maximize",
        chain_label="accept_as_proposed",
        decision=NegotiationDecision(action="accept", proposal=dict(proposal)),
        intermediate={"uses_scalar_amount": True},
    )


class TestReleaseConditionAuthorization:
    """An accepted plan uses exactly the condition the listing authorizes.

    Each case opens at the listed rate, so the seller would accept at once and
    materialize the plan; the refusal must come before any agreement or plan is
    recorded, whatever seller policies run.
    """

    @staticmethod
    def _without_seller_policy() -> None:
        """Run negotiation with a seller hook that accepts whatever is proposed.

        VM prepends the escrow-shape guard to every configured chain, so a seller
        without it is a seller-round hook of its own.
        """
        (build_runtime,) = _RUNTIME_BUILDERS
        _container.resolved_negotiation_runtime = build_runtime(
            seller_round_hook=_accept_as_proposed
        )

    async def _open(self, c, db, listing_id: str, **proposal):
        return await c.negotiate_new(
            listing_id=listing_id,
            settlement_selection=await _selection(db, listing_id),
            initial_amount=5000,
            provision_terms=_vm_provision(),
            token=_TOKEN,
            chain_name="anvil",
            escrow_expiration_unix=1_800_000_000,
            **proposal,
        )

    @staticmethod
    def _nothing_accepted(db) -> None:
        with sqlite3.connect(db.db_path) as conn:
            assert conn.execute(
                "SELECT COUNT(*) FROM negotiation_threads "
                "WHERE agreement_bytes IS NOT NULL OR settlement_plan IS NOT NULL"
            ).fetchone()[0] == 0

    async def test_a_substituted_recipient_is_refused_without_the_shape_guard(
        self, client, db
    ):
        c, db = client
        await _upsert_bound_listing(
            db, "rc-substituted", demands=[_recipient_condition(_RECIPIENT)]
        )

        with pytest.raises(StorefrontClientError) as refused:
            self._without_seller_policy()
            await self._open(
                c, db, "rc-substituted",
                escrow_address="0x" + "11" * 20,
                demands=[_recipient_condition(_BUYER_RECIPIENT)],
            )

        assert refused.value.status_code == 409
        assert "release_condition" in str(refused.value)
        self._nothing_accepted(db)

    async def test_a_listing_authorizing_no_condition_accepts_none(self, client, db):
        c, db = client
        await _upsert_bound_listing(db, "rc-unauthorized", demands=None)

        with pytest.raises(StorefrontClientError) as refused:
            self._without_seller_policy()
            await self._open(
                c, db, "rc-unauthorized",
                escrow_address="0x" + "11" * 20,
                demands=[_recipient_condition(_BUYER_RECIPIENT)],
            )

        assert refused.value.status_code == 409
        assert "release_condition" in str(refused.value)
        self._nothing_accepted(db)

    @pytest.mark.parametrize(
        "guarded",
        [
            pytest.param(True, id="default chain, with the shape guard"),
            pytest.param(False, id="a seller policy accepting as proposed"),
        ],
    )
    async def test_an_opening_naming_no_escrow_contract_is_refused(
        self, client, db, guarded
    ):
        """With the shape guard the round is refused by name. A seller without
        it accepts at once, and VM's Alkahest stage refuses the acceptance
        through the kit's pinned-escrow check before building any plan, so
        nothing is recorded either way."""
        c, db = client
        await _upsert_bound_listing(
            db, "rc-unpinned", demands=[_recipient_condition(_RECIPIENT)]
        )

        with pytest.raises(StorefrontClientError) as refused:
            if not guarded:
                self._without_seller_policy()
            await self._open(
                c, db, "rc-unpinned",
                escrow_address="0x" + "00" * 20,
                demands=[_recipient_condition(_RECIPIENT)],
            )

        assert refused.value.status_code == 409
        assert "escrow_contract_unpinned" in str(refused.value)
        self._nothing_accepted(db)

    async def _open_selecting_only(self, c, db, listing_id: str):
        """An exact selection with no escrow carrier, as a payments buyer opens."""
        return await c.negotiate_new(
            listing_id=listing_id,
            settlement_selection=await _selection(db, listing_id),
            initial_amount=5000,
            provision_terms=_vm_provision(),
            selection_only=True,
        )

    async def test_an_exact_selection_is_accepted_only_with_its_authorized_plan(
        self, client, db
    ):
        """VM's Alkahest entry builds the escrow from the selected option under
        the listing's condition, so an exact selection is never accepted
        without the plan its settlement is verified against."""
        c, db = client
        authorized = _recipient_condition(_RECIPIENT)
        await _upsert_bound_listing(db, "rc-exact", demands=[authorized])

        result = await self._open_selecting_only(c, db, "rc-exact")

        assert result["action"] == "accept"
        (obligation,) = result["settlement_plan"]["obligations"]
        data = obligation["params"]["obligation_data"]
        assert data["arbiter"].lower() == authorized["arbiter"].lower()
        assert data["demand"] == "0x" + encode_recipient_demand(_RECIPIENT).hex()
        thread = await db.load_negotiation_thread_row(
            negotiation_id=result["negotiation_id"]
        )
        assert thread["settlement_plan"]["obligations"] == [obligation]

    async def test_an_exact_selection_of_a_listing_with_no_demands_is_refused(
        self, client, db
    ):
        c, db = client
        await _upsert_bound_listing(db, "rc-exact-none", demands=None)

        with pytest.raises(StorefrontClientError) as refused:
            await self._open_selecting_only(c, db, "rc-exact-none")

        assert refused.value.status_code == 409
        assert "release_condition_not_advertised" in str(refused.value)
        self._nothing_accepted(db)

    async def test_an_escrow_whose_plan_cannot_be_materialized_is_refused(
        self, client, db
    ):
        """The selected option names a rate the codecs cannot price, so its
        authorized escrow has no plan; the round is refused, not accepted
        without one."""
        c, db = client
        await _upsert_bound_listing(
            db, "rc-unpriceable",
            extra_rates=({"field": "bonus", "per": "fortnight", "value": "1"},),
        )

        with pytest.raises(StorefrontClientError) as refused:
            await self._open_selecting_only(c, db, "rc-unpriceable")

        assert refused.value.status_code == 409
        assert "settlement_plan_unmaterializable" in str(refused.value)
        self._nothing_accepted(db)

    async def test_an_opening_naming_no_condition_is_settled_under_the_listings(
        self, client, db
    ):
        c, db = client
        authorized = _recipient_condition(_RECIPIENT)
        await _upsert_bound_listing(db, "rc-default", demands=[authorized])

        self._without_seller_policy()
        result = await self._open(
            c, db, "rc-default",
            escrow_address="0x" + "11" * 20,
        )

        assert result["action"] == "accept"
        (obligation,) = result["settlement_plan"]["obligations"]
        data = obligation["params"]["obligation_data"]
        assert data["arbiter"].lower() == authorized["arbiter"].lower()
        assert data["demand"] == "0x" + encode_recipient_demand(_RECIPIENT).hex()
