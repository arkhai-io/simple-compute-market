"""The VM storefront app as its publication loop runs, for integration tests.

The app is built from the routers under test with the container wired the way the
composition root wires it, and it is driven only through the canonical
``StorefrontClient``. Settlement is configured for real — ``[Settlement]`` and
``[pricing].settlements`` — so each publication cycle compiles its clauses through
the request path a deployed storefront runs. The external boundaries are replaced
where this codebase wraps them: the capacity site is the in-memory fake the other
storefront suites use, the site projection is supplied as the projection poller
would hold it, and the settlement composition is a double standing where the
mechanism clients would.

The settings select both compute domains, as a combined storefront does, so every
cycle rebuilds the two-registration registry a deployed loop builds.
"""

from __future__ import annotations

import contextlib
from copy import deepcopy
from collections.abc import AsyncIterator, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from unittest.mock import patch

import httpx
from core_storefront import multi_registry_client
from core_storefront.site_projections import (
    ProjectionCache,
    ProjectionIdentity,
    ProjectionState,
)
from fastapi import FastAPI
from market_config.config_loader import ChainConfig
from market_site_client.fixtures.resource_pools import (
    build_projected_resource,
    build_resource_pool_row,
)
import market_policy.negotiation_thread as thread_store
from market_identity import Ed25519Signer, TrustedIdentitySet
from market_policy.identity import Identity as PolicyIdentity
from storefront_client.client import StorefrontClient

import market_storefront.container as container
from market_storefront.middleware import admin_identity

# The server module completes the controllers' import cycle, as the admin API
# tests rely on; importing a controller first leaves it partially initialized.
import market_storefront.server  # noqa: F401  (import order, see above)
import market_storefront.negotiation_runtime as negotiation_runtime
from market_storefront.controllers.admin_controller import router as admin_router
from market_storefront.controllers.listings_controller import (
    admin_router as listings_admin_router,
)
from market_storefront.controllers.listings_controller import router as listings_router
from market_storefront.controllers.negotiate_controller import router as negotiate_router
from market_storefront.controllers.system_controller import router as system_router
from market_storefront.middleware.seller_auth import listing_lifecycle_middleware
from market_storefront.services import site_projection_cache
from market_storefront.services.listing_service import ListingService
from market_storefront.services.system_service import SystemService
from market_storefront.settlement_composition import (
    build_storefront_settlement_registry,
)
from market_storefront.utils import config as storefront_config
from market_storefront.utils.sqlite_client import SQLiteClient
from tests._settings_overrides import settings_overrides
from tests.fake_site import TEST_MARKETPLACE_SIGNER, FakeSite, capacity_runtime_over

SITE = "site-a"

# Development signers and addresses; none is ever used on a public network.
ADMIN_SIGNER = Ed25519Signer(b"\x71" * 32)
BUYER_SIGNER = Ed25519Signer(b"\x72" * 32)
REGISTRY_SIGNER = Ed25519Signer(b"\x73" * 32)
_ADMINISTRATORS = TrustedIdentitySet(identities=(ADMIN_SIGNER.identity,))
_PUBLISHERS = TrustedIdentitySet(identities=(TEST_MARKETPLACE_SIGNER.identity,))
_WALLET = "0x" + "33" * 20
_TOKEN = "0x" + "22" * 20
_ESCROW_ADDRESS = "0x" + "11" * 20

STOREFRONT_DOMAINS = [
    {
        "contribution": "vms",
        "offering_mode": "vm",
        "domain_identity": "compute.v1",
        "contract_version": "1.0",
    },
    {
        "contribution": "bare_metal",
        "offering_mode": "bare_metal",
        "domain_identity": "bare_metal.v1",
        "contract_version": "1.0",
    },
]
SETTLEMENT = {
    "schema_version": 1,
    "priority": ["alkahest.v1"],
    "alkahest": {"enabled": True},
}


def settlement_clause(rate: str = "100") -> dict[str, Any]:
    """One Alkahest publication clause, as `[pricing].settlements` holds it.

    The rate is integral so the composition double can carry it into an escrow
    rate, which is in base units, without the token-decimal conversion the real
    Alkahest composition performs.
    """
    return {
        "mechanism": "alkahest.v1",
        "asset": _TOKEN,
        "rate": rate,
        "per": "hour",
        "mechanism_input": {
            "chain": "anvil",
            "escrow_kind": "erc20_escrow_obligation_default",
        },
    }


class SettlementCompositionDouble:
    """The settlement composition at the mechanism boundary.

    Clauses compile against the real configuration registry and settlement
    configuration. Artifact construction, which the real composition delegates to
    mechanism clients, yields one accepted escrow per Alkahest clause.
    ``mechanism_fulfillment`` is the per-test declaration of which mechanisms VM
    fulfils through capacity.
    """

    def __init__(self, mechanism_fulfillment: Mapping[str, bool]) -> None:
        self.configuration_registry = build_storefront_settlement_registry()
        self.settlement_config = self.configuration_registry.resolve(
            storefront_config.settlement_config_mapping(), role="seller"
        )
        self.mechanism_fulfillment = dict(mechanism_fulfillment)

    async def publication_artifacts(self, resources, clauses=None):
        accepted = [
            {
                "chain_name": str(clause.mechanism_input["chain"]),
                "escrow_address": _ESCROW_ADDRESS,
                "literal_fields": {"token": clause.asset},
                "rates": [
                    {"field": "amount", "per": clause.per, "value": clause.rate}
                ],
            }
            for clause in clauses or ()
            if clause.mechanism == "alkahest.v1"
        ]
        return accepted, [], ()


REGISTRY_URLS = ("http://registry-a.test", "http://registry-b.test")


class RecordingRegistries:
    """The storefront's registry client, recording what each registry is sent.

    Stands where ``MultiRegistryClient`` wraps the independently operated
    registries, so publication runs its real fan-out and result recording and
    every registry answers success. ``sent`` holds, in order,
    ``(operation, registry_url, listing_id, request)`` with each request as the
    JSON the client would serialize.
    """

    def __init__(self) -> None:
        self.urls = REGISTRY_URLS
        self.sent: list[tuple[str, str, str, dict[str, Any]]] = []
        # (operation, registry_url) pairs that fail until removed; an update's
        # operation is the status it sets.
        self.failing: set[tuple[str, str]] = set()

    def __call__(self, *_args: Any, **_kwargs: Any) -> "RecordingRegistries":
        return self

    async def __aenter__(self) -> "RecordingRegistries":
        return self

    async def __aexit__(self, *_exc: Any) -> bool:
        return False

    @staticmethod
    def _json(request: Any) -> dict[str, Any]:
        return request.to_dict()

    def _result(self, operation: str, url: str) -> dict[str, Any]:
        if (operation, url) in self.failing:
            return {"registry_url": url, "success": False, "error": "unreachable"}
        return {"registry_url": url, "success": True, "response": {"ok": True}}

    async def publish_listing_per_registry(self, *, payloads):
        results = []
        for url, request in payloads.items():
            body = self._json(request)
            self.sent.append(("publish", url, str(body.get("listing_id")), body))
            results.append(self._result("publish", url))
        return results

    async def update_listing_per_registry(self, *, listing_id, payloads):
        results = []
        for url, request in payloads.items():
            body = self._json(request)
            self.sent.append(("update", url, listing_id, body))
            results.append(self._result(str(body.get("status")), url))
        return results

    def to(self, operation: str, listing_id: str) -> list[tuple[str, dict[str, Any]]]:
        """``(registry_url, request)`` for one operation on one listing."""
        return [
            (url, body)
            for sent, url, listing, body in self.sent
            if sent == operation and listing == listing_id
        ]


def pool(
    pool_id: str,
    *,
    backing: str,
    gpu_model: str = "H100",
    gpu_count: int = 1,
    enabled: bool = True,
    capacity: dict[str, int] | None = None,
    available: dict[str, int] | None = None,
    **tags: Any,
) -> dict[str, Any]:
    """One projected fungible pool with a single member.

    ``capacity`` declares every dimension of the member; without it the member
    declares ``gpu_count`` only. ``available`` defaults to the capacity.

    Built by the site client's contract fixture, the shape the provisioning
    service's own tests validate its projection against.
    """
    policy_tags = {"listing_cardinality_mode": "fungible", "region": "us-east", **tags}
    return build_resource_pool_row(
        pool_id,
        capacity_backing=backing,
        enabled=enabled,
        policy_tags=policy_tags,
        resources=[
            build_projected_resource(
                f"{pool_id}-res",
                capacity=capacity if capacity is not None else {"gpu_count": gpu_count},
                available=available,
                # A claim matches region against the declaration itself, so the
                # member declares the region its pool advertises.
                attributes={"gpu_model": gpu_model, "region": policy_tags["region"]},
            )
        ],
    )


def _projection_caches(pools: list[dict[str, Any]]):
    resource_pools = ProjectionCache(client=None)
    resource_pools._value = pools
    resource_pools._state = ProjectionState.loaded
    resource_pools._identity = ProjectionIdentity(revision=1, digest="publication")
    return site_projection_cache.SiteProjectionCaches(
        resource_pools=resource_pools,
        capacity_buckets=ProjectionCache(client=None),
    )


@contextlib.contextmanager
def _replaced_setting(key: str, value: Any):
    settings = storefront_config.settings
    original = deepcopy(settings.get(key))
    settings.set(key, deepcopy(value), merge=False)
    try:
        yield
    finally:
        if original is None:
            settings.unset(key, force=True)
        else:
            settings.set(key, original, merge=False)


@dataclass
class PublicationApp:
    client: StorefrontClient
    seller: StorefrontClient
    db: SQLiteClient
    pools: list[dict[str, Any]]
    composition: SettlementCompositionDouble
    site: FakeSite
    buyer: StorefrontClient | None = None
    registries: RecordingRegistries | None = None

    def set_settlement_clauses(self, clauses: list[dict[str, Any]]) -> None:
        """Replace `[pricing].settlements`, the storefront-wide durable terms."""
        storefront_config.settings.set(
            "pricing.settlements", deepcopy(clauses), merge=False
        )


@contextlib.asynccontextmanager
async def publication_app(
    tmp_path: Path,
    *,
    mechanism_fulfillment: Mapping[str, bool] | None = None,
    negotiation: bool = False,
    registries: bool = False,
) -> AsyncIterator[PublicationApp]:
    """Run the VM storefront app for publication tests.

    ``mechanism_fulfillment`` defaults to the VM composition's own declaration,
    under which an unbacked listing has no settlement option it may publish.
    ``negotiation`` adds the negotiation route, its runtime, and a buyer client,
    so a listing the loop published can be negotiated in the same app.
    ``registries`` enables registry publication to two registries, recorded by
    ``RecordingRegistries``; otherwise publication records locally only.
    """
    pools: list[dict[str, Any]] = []
    address_config = (
        Path(negotiation_runtime.__file__).resolve().parent
        / "data"
        / "alkahest_anvil_addresses.json"
    )
    chains = {
        "anvil": ChainConfig(
            name="anvil",
            rpc_url="http://anvil.test",
            chain_id=31337,
            alkahest_address_config_path=str(address_config),
        )
    }
    with contextlib.ExitStack() as stack:
        recording = RecordingRegistries() if registries else None
        stack.enter_context(
            settings_overrides(
                enable_registry_discovery=registries,
                **{
                    "capacity.use_site_projection_for_listings": True,
                    "wallet.address": _WALLET,
                },
            )
        )
        # Replaced rather than overridden: an override merges into the test
        # configuration's own values, which would append to its lists.
        stack.enter_context(_replaced_setting("storefront_domains", STOREFRONT_DOMAINS))
        stack.enter_context(_replaced_setting("settlement", SETTLEMENT))
        stack.enter_context(
            _replaced_setting(
                "registry.urls", list(REGISTRY_URLS) if registries else []
            )
        )
        if registries:
            stack.enter_context(
                _replaced_setting(
                    "registry.authorities",
                    {
                        url: {
                            "authority": f"registry-{index}",
                            "principals": [
                                REGISTRY_SIGNER.identity.model_dump(mode="json")
                            ],
                        }
                        for index, url in enumerate(REGISTRY_URLS)
                    },
                )
            )
        stack.enter_context(
            _replaced_setting("pricing.settlements", [settlement_clause()])
        )
        stack.enter_context(patch.dict(storefront_config.CHAINS, chains, clear=True))
        stack.enter_context(patch.object(negotiation_runtime, "CHAINS", chains))
        if recording is not None:
            stack.enter_context(
                patch.object(multi_registry_client, "MultiRegistryClient", recording)
            )
        stack.enter_context(
            patch.dict(
                site_projection_cache._caches,
                {SITE: _projection_caches(pools)},
                clear=True,
            )
        )
        stack.enter_context(
            patch.object(
                admin_identity,
                "get_administrator_configs",
                lambda: {"operator": _ADMINISTRATORS},
            )
        )
        registry = storefront_config.storefront_domain_registry()
        db = SQLiteClient(db_path=str(tmp_path / "storefront.db"), registry=registry)
        composition = SettlementCompositionDouble(
            mechanism_fulfillment
            if mechanism_fulfillment is not None
            else {"alkahest.v1": True, "fiat.stripe.v1": True}
        )
        site = FakeSite(deliverable_modes={"vm"})
        capacity = capacity_runtime_over(
            site,
            site_name=SITE,
            sqlite_client_factory=lambda: db,
        )
        registration = registry.resolve_mode("vm")
        listings = ListingService(
            registry=registry,
            binding=registration.binding,
            domain=registration.contract,
            capacity_runtime=capacity,
            sqlite_client=db,
            marketplace_signer=TEST_MARKETPLACE_SIGNER,
            alkahest_clients={},
            settlement_composition_provider=lambda: composition,
        )
        previous = {
            name: getattr(container, name, None)
            for name in (
                "resolved_sqlite_client",
                "resolved_listing_service",
                "resolved_capacity_runtime",
                "resolved_domain_registry",
                "resolved_marketplace_signer",
                "resolved_system_service",
            )
        }
        container.resolved_sqlite_client = db
        container.resolved_listing_service = listings
        container.resolved_capacity_runtime = capacity
        container.resolved_domain_registry = registry
        container.resolved_marketplace_signer = TEST_MARKETPLACE_SIGNER
        container.resolved_system_service = SystemService(
            sqlite_client=db, marketplace_signer=TEST_MARKETPLACE_SIGNER
        )
        routers: tuple[Any, ...] = ()
        if negotiation:
            previous["resolved_negotiation_runtime"] = getattr(
                container, "resolved_negotiation_runtime", None
            )
            stack.enter_context(
                settings_overrides(
                    **{
                        "provisioning.identity.principals": [
                            BUYER_SIGNER.identity.model_dump(mode="json"),
                            TEST_MARKETPLACE_SIGNER.identity.model_dump(mode="json"),
                        ],
                    }
                )
            )
            thread_store.get_thread_store(
                sqlite_client=db,
                identity=PolicyIdentity(agent_url="http://test-seller:8001"),
            )
            container.resolved_negotiation_runtime = (
                negotiation_runtime.build_vm_negotiation_runtime(
                    registration.contract,
                    registry=registry,
                    binding=registration.binding,
                    capacity_runtime=capacity,
                )
            )
            routers = (negotiate_router,)
        try:
            admin_identity.initialize_administrator_identities(db.db_path)
            app = FastAPI()
            for router in (
                system_router,
                admin_router,
                listings_router,
                listings_admin_router,
                *routers,
            ):
                app.include_router(router)
            app.middleware("http")(listing_lifecycle_middleware)
            app.middleware("http")(admin_identity.administrator_identity_middleware)
            transport = httpx.ASGITransport(app=app)
            async with StorefrontClient(
                "http://test",
                transport=transport,
                signer=ADMIN_SIGNER,
                caller_role="admin",
                expected_publishers=_PUBLISHERS,
            ) as client, StorefrontClient(
                "http://test",
                transport=transport,
                signer=TEST_MARKETPLACE_SIGNER,
                caller_role="seller",
                expected_publishers=_PUBLISHERS,
            ) as seller, StorefrontClient(
                "http://test",
                transport=transport,
                signer=BUYER_SIGNER,
                caller_role="buyer",
                expected_publishers=_PUBLISHERS,
            ) as buyer:
                yield PublicationApp(
                    client,
                    seller,
                    db,
                    pools,
                    composition,
                    site,
                    buyer if negotiation else None,
                    recording,
                )
        finally:
            thread_store._thread_store = None
            for name, value in previous.items():
                setattr(container, name, value)
