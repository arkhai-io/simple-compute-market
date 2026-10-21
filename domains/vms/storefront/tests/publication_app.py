"""The VM storefront app as its publication loop runs, for integration tests.

The app is built from the routers under test with the container wired the way the
composition root wires it, and it is driven only through the canonical
``StorefrontClient``. Settlement is configured for real — ``[Settlement]`` and
``[pricing].settlements`` — so each publication cycle compiles its clauses through
the request path a deployed storefront runs. The external boundaries are replaced
where this codebase wraps them: the capacity site is the in-memory fake the other
storefront suites use, the storefront's projection state is built over fake sites
serving the harness's pool lists, and the settlement composition is a double
standing where the mechanism clients would.

The settings select both compute domains, as a combined storefront does, so every
cycle rebuilds the two-registration registry a deployed loop builds.
"""

from __future__ import annotations

import contextlib
from types import SimpleNamespace
from copy import deepcopy
from collections.abc import AsyncIterator, Collection, Iterator, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from unittest.mock import patch

import httpx
from core_storefront import multi_registry_client
from fastapi import FastAPI
from market_config.config_loader import ChainConfig
from market_capacity_publication.capacity_remote import reset_site_event_cursors
from market_site_client.fixtures.resource_pools import (
    build_projected_resource,
    build_resource_pool_row,
)
import market_policy.negotiation_thread as thread_store
from market_contact_exchange import MECHANISM as CONTACT_MECHANISM
from market_contact_exchange import ContactExchangeClient
from market_core.schemas import RateValue, derive_settlement_option_id
from core_storefront.service_peers import ServicePeerTrust
from market_identity import Ed25519Signer, TrustedIdentitySet
from market_policy.identity import Identity as PolicyIdentity
from market_settlement_runtime import (
    MechanismReadiness,
    SettlementRuntime,
    SettlementSQLiteRepository,
)
from storefront_client.client import StorefrontClient

from market_alkahest.dev_chain import anvil_address_book_path
import market_storefront.container as container
from market_storefront.middleware import admin_identity

# The server module completes the controllers' import cycle, as the admin API
# tests rely on; importing a controller first leaves it partially initialized.
import market_storefront.server  # noqa: F401  (import order, see above)
from market_storefront.server import build_pool_override_service
from market_storefront.services.publication_terms import (
    parse_configured_admissibility_default,
)
import market_storefront.negotiation_runtime as negotiation_runtime
from market_storefront.contact_exchange import build_vm_contact_exchange
from market_storefront.controllers.admin_controller import router as admin_router
from market_storefront.controllers.introductions_controller import (
    router as introductions_router,
)
from market_storefront.controllers.listings_controller import (
    admin_router as listings_admin_router,
)
from market_storefront.controllers.listings_controller import router as listings_router
from market_storefront.controllers.negotiate_controller import router as negotiate_router
from market_storefront.controllers.system_controller import router as system_router
from market_storefront.middleware.seller_auth import listing_lifecycle_middleware
from market_storefront.middleware.service_peer_auth import (
    service_peer_callback_middleware,
)
from market_storefront.services.listing_service import ListingService
from market_storefront.services.publication_loop import wake_publication_loop
from market_storefront.services.system_service import SystemService
from market_storefront.settlement_composition import (
    build_storefront_settlement_registry,
)
from market_storefront.utils import config as storefront_config
from market_storefront.utils.sqlite_client import SQLiteClient
from tests._settings_overrides import replaced_setting, settings_overrides
from tests.fake_site import (
    TEST_MARKETPLACE_SIGNER,
    FakeProjectionSite,
    FakeSite,
    capacity_runtime_over_sites,
    site_projection_state,
)

SITE = "site-a"
#: The second configured site, composed only when a test asks for it.
SITE_B = "site-b"

# Development signers and addresses; none is ever used on a public network.
ADMIN_SIGNER = Ed25519Signer(b"\x71" * 32)
BUYER_SIGNER = Ed25519Signer(b"\x72" * 32)
REGISTRY_SIGNER = Ed25519Signer(b"\x73" * 32)
#: The provisioning service's signer, for fulfillment-event callbacks.
SERVICE_SIGNER = Ed25519Signer(b"\x74" * 32)
_ADMINISTRATORS = TrustedIdentitySet(identities=(ADMIN_SIGNER.identity,))
_PUBLISHERS = TrustedIdentitySet(identities=(TEST_MARKETPLACE_SIGNER.identity,))
#: The storefront's configured seller wallet; a development value, never used
#: on a public network.
SELLER_WALLET = "0x" + "33" * 20
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


#: The seller contacts a contact-exchange app reveals, one per configured site.
#: Development values on a reserved domain.
SITE_CONTACTS = {
    "site-a": {"email": "sales@site-a.invalid"},
    "site-b": {"email": "sales@site-b.invalid"},
}


def contact_settlement(origins: Mapping[str, Mapping[str, str]]) -> dict[str, Any]:
    """``[Settlement]`` composing contact exchange beside Alkahest, keyed by site."""
    return {
        **SETTLEMENT,
        "priority": ["alkahest.v1", CONTACT_MECHANISM],
        "contact": {
            "enabled": True,
            "origins": {
                site: {"contact_payload": dict(contact)} for site, contact in origins.items()
            },
            "profiles": {
                "default": {"channel": "email", "terms": "Quoted per engagement."}
            },
        },
    }


def contact_clause() -> dict[str, Any]:
    """One contact-exchange publication clause, as a pool override states it."""
    return {
        "mechanism": CONTACT_MECHANISM,
        "asset": "introduction",
        "mechanism_input": {"profile": "default"},
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
    mechanism clients, yields one accepted escrow and its exact option per Alkahest clause; a
    contact-exchange clause, which needs no client, is built by the real
    registry, and so is acceptance. ``mechanism_fulfillment`` is the per-test
    declaration of which mechanisms VM fulfils through capacity, exposed as the
    ``fulfils_through_capacity`` of each seller stage, as the real stage table
    declares it.
    """

    def __init__(self, mechanism_fulfillment: Mapping[str, bool]) -> None:
        self.configuration_registry = build_storefront_settlement_registry()
        self.settlement_config = self.configuration_registry.resolve(
            storefront_config.settlement_config_mapping(), role="seller"
        )
        self.seller_stages = {
            mechanism: SimpleNamespace(fulfils_through_capacity=fulfils)
            for mechanism, fulfils in mechanism_fulfillment.items()
        }

    async def _registry_options(self, resources, clauses) -> list[dict[str, Any]]:
        contact = [clause for clause in clauses or () if clause.mechanism == CONTACT_MECHANISM]
        if not contact or CONTACT_MECHANISM not in self.settlement_config.priority:
            return []
        readiness = {
            status.mechanism: status
            for status in await self.configuration_registry.ordered_readiness(
                self.settlement_config, role="seller"
            )
        }
        status = readiness.get(CONTACT_MECHANISM)
        if status is None or not status.ready:
            return []
        options: list[dict[str, Any]] = []
        for clause in contact:
            built = self.configuration_registry.build_option(
                status,
                self.settlement_config,
                role="seller",
                resources={**resources, "publication_clause": clause},
            )
            options.extend(built["settlement_options"])
        return options

    def accepted_obligation_dispatch(self) -> dict[str, Any]:
        """The real registry dispatch, as the composition root installs it."""
        dispatch: dict[str, Any] = {}
        for mechanism_id in self.settlement_config.priority:
            registration = self.configuration_registry.registration(mechanism_id)
            if registration.accepted_obligation_builder is None:
                continue

            def build(option, context, *, _mechanism_id: str = mechanism_id):
                return self.configuration_registry.build_accepted_obligation(
                    _mechanism_id,
                    option,
                    self.settlement_config,
                    role="seller",
                    context=context,
                )

            dispatch[mechanism_id] = build
        return dispatch

    async def readiness(self):
        """Each mechanism's readiness, evaluated by the real registry.

        Alkahest's preflight reads the chain probe the container holds, as the
        real composition hands it, and the harness's seller wallet and chains.
        """
        resources = {
            "wallet": {"address": SELLER_WALLET},
            "chains": dict(storefront_config.CHAINS),
            "default_chain": "anvil",
        }
        if container.resolved_alkahest_chain_probe is not None:
            resources["chain_probe"] = container.resolved_alkahest_chain_probe
        return await self.configuration_registry.ordered_readiness(
            self.settlement_config, role="seller", resources=resources
        )

    async def publication_artifacts(self, resources, clauses=None):
        options = await self._registry_options(resources, clauses)
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
        # Each accepted escrow is also an exact option, in the shape the
        # Alkahest kit publishes, so a buyer can select it explicitly.
        for escrow in accepted:
            body = {
                "mechanism": "alkahest.v1",
                "asset": escrow["literal_fields"]["token"],
                "rates": [{**rate, "value": str(rate["value"])} for rate in escrow["rates"]],
                "params": {"accepted_escrow": escrow},
            }
            option_id = derive_settlement_option_id(
                **{**body, "rates": [RateValue.model_validate(rate) for rate in body["rates"]]}
            )
            options.append({"option_id": option_id, **body})
        # Release conditions are derived only under a ready Alkahest, so the
        # double reports Alkahest ready wherever it builds Alkahest options, as
        # the real composition's readiness does.
        readiness = (
            (
                MechanismReadiness(
                    mechanism="alkahest.v1", configured=True, enabled=True, ready=True
                ),
            )
            if accepted
            else ()
        )
        return accepted, options, readiness


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


@contextlib.contextmanager
def recorded_registries() -> Iterator[RecordingRegistries]:
    """Configure the two test registries, each pinned to its authority, with
    ``RecordingRegistries`` standing for their client.

    A storefront publishes to every configured registry, so a test that
    publishes, closes, or reopens a listing needs registries to reach.
    """
    recording = RecordingRegistries()
    with contextlib.ExitStack() as stack:
        stack.enter_context(replaced_setting("registry.urls", list(REGISTRY_URLS)))
        stack.enter_context(
            replaced_setting(
                "registry.authorities",
                {
                    url: {
                        "authority": f"registry-{index}",
                        "principals": [REGISTRY_SIGNER.identity.model_dump(mode="json")],
                    }
                    for index, url in enumerate(REGISTRY_URLS)
                },
            )
        )
        stack.enter_context(
            patch.object(multi_registry_client, "MultiRegistryClient", recording)
        )
        yield recording


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


class HarnessProjectionSite(FakeProjectionSite):
    """The harness's pool list as its site serves it to the projection state.

    Tests edit the list in place, and the storefront holds it as of its last
    poll or refresh, as it holds any site's projection. With a ``site``, each
    resource-pool fetch also writes that fake site's live availability into
    every member it holds, so a reservation there reaches the storefront exactly
    when the storefront refreshes the site, and never otherwise. Its
    capacity-bucket family is derived from the same list. ``failing``
    fails every call, as a site mid-outage does.
    """

    def __init__(self, pools: list[dict[str, Any]], site: "FakeSite | None" = None) -> None:
        super().__init__(resource_pools=pools, derive_buckets=True)
        self.site = site

    @property
    def pools(self) -> list[dict[str, Any]]:
        return self.resource_pools

    def _write_availability(self) -> None:
        if self.site is not None and not self.failing:
            for projected in self.pools:
                for member in projected.get("resources") or []:
                    resource_id = member.get("physical_resource_id")
                    if resource_id in self.site.resources:
                        member["available"] = self.site.available_dimensions(resource_id)

    async def resource_pool_projection(self) -> dict[str, Any]:
        self._write_availability()
        return await super().resource_pool_projection()

    async def capacity_bucket_projection(self) -> dict[str, Any]:
        self._write_availability()
        return await super().capacity_bucket_projection()


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
    projection: HarnessProjectionSite | None = None
    site_b: FakeSite | None = None
    pools_b: list[dict[str, Any]] | None = None
    projection_b: HarnessProjectionSite | None = None
    service: StorefrontClient | None = None
    app: FastAPI | None = None
    contact_exchange: Any = None
    site_projections: Any = None
    #: One entry per publication wake the projection state raised.
    wakes: list[None] | None = None

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
    second_site: bool = False,
    contacts: Mapping[str, Mapping[str, str]] | None = None,
    admissibility_default: Mapping[str, Any] | None = None,
    unreachable_sites: Collection[str] = (),
) -> AsyncIterator[PublicationApp]:
    """Run the VM storefront app for publication tests.

    ``mechanism_fulfillment`` defaults to the VM composition's own declaration,
    under which an unbacked listing has no settlement option it may publish.
    ``negotiation`` adds the negotiation route, its runtime, and a buyer client,
    so a listing the loop published can be negotiated in the same app.
    Publication goes to two registries, recorded by ``RecordingRegistries``, as
    a storefront always publishes to every configured registry.
    ``second_site`` configures ``SITE_B`` after ``SITE``, with its own fake site,
    pool list, and projection cache; ``SITE`` stays the home site.
    ``contacts`` composes contact exchange, keyed by site, as the lifespan composes
    it: the real registry builds its options and acceptance, a real settlement
    runtime over the app's database drives its obligation, and the introduction
    routes are mounted. Implies ``negotiation``.
    ``admissibility_default`` is configured as ``[admissibility.defaults.vm]``
    and parsed as the lifespan parses it, so publication, reconciliation, and the
    override write check all judge against it.
    ``unreachable_sites`` fail their projections from the first load, as sites
    a restarting storefront cannot reach; a test clears ``failing`` to bring
    one back. A second app over the same ``tmp_path`` reopens the first's
    database, which is how a test restarts the storefront.
    """
    negotiation = negotiation or contacts is not None
    pools: list[dict[str, Any]] = []
    projection = HarnessProjectionSite(pools)
    pools_b: list[dict[str, Any]] = []
    projection_b = HarnessProjectionSite(pools_b)
    projection.failing = SITE in unreachable_sites
    projection_b.failing = SITE_B in unreachable_sites
    # Each app has a fresh fake site whose events restart at version one, while
    # the capacity-event cursor is process-wide; a cursor left by an earlier app
    # would skip this site's first events.
    reset_site_event_cursors()
    address_config = anvil_address_book_path()
    chains = {
        "anvil": ChainConfig(
            name="anvil",
            rpc_url="http://anvil.test",
            chain_id=31337,
            alkahest_address_config_path=str(address_config),
        )
    }
    with contextlib.ExitStack() as stack:
        recording = stack.enter_context(recorded_registries())
        stack.enter_context(settings_overrides(**{"wallet.address": SELLER_WALLET}))
        # Replaced rather than overridden: an override merges into the test
        # configuration's own values, which would append to its lists.
        stack.enter_context(replaced_setting("storefront_domains", STOREFRONT_DOMAINS))
        stack.enter_context(
            replaced_setting(
                "settlement",
                contact_settlement(contacts) if contacts is not None else SETTLEMENT,
            )
        )

        stack.enter_context(
            replaced_setting("pricing.settlements", [settlement_clause()])
        )
        if admissibility_default is not None:
            # Replaced at its root: unsetting a dotted key leaves the table behind.
            stack.enter_context(
                replaced_setting(
                    "admissibility", {"defaults": {"vm": admissibility_default}}
                )
            )
        stack.enter_context(patch.dict(storefront_config.CHAINS, chains, clear=True))
        stack.enter_context(patch.object(negotiation_runtime, "CHAINS", chains))

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
            else {"alkahest.v1": True, "arkhai.payments.v1": True}
        )
        site = FakeSite(deliverable_modes={"vm"})
        # The site's live answer is the same list the storefront's cache holds,
        # until a test gives the site a different generation.
        site.pool_projection = pools
        projection.site = site
        site_b = FakeSite(deliverable_modes={"vm"}) if second_site else None
        if site_b is not None:
            site_b.pool_projection = pools_b
            projection_b.site = site_b
        capacity = capacity_runtime_over_sites(
            {SITE: site, **({SITE_B: site_b} if site_b is not None else {})},
            sqlite_client_factory=lambda: db,
            # Bound to the projection state built below, as the root binds it.
            site_projections=lambda: site_projections,
        )
        # The storefront's one projection state, over the harness's sites,
        # loaded as startup loads it. Each wake is recorded, then raised as
        # production raises it.
        wakes: list[None] = []

        def wake() -> None:
            wakes.append(None)
            wake_publication_loop()

        site_projections = site_projection_state(
            {SITE: projection, **({SITE_B: projection_b} if second_site else {})},
            on_resource_pool_change=wake,
        )
        await site_projections.poll_once()
        registration = registry.resolve_mode("vm")
        listings = ListingService(
            registry=registry,
            binding=registration.binding,
            domain=registration.contract,
            capacity_runtime=capacity,
            site_projections=site_projections,
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
                "resolved_site_projections",
                "resolved_domain_registry",
                "resolved_marketplace_signer",
                "resolved_system_service",
                "resolved_pool_override_service",
                "resolved_admissibility_default",
                "resolved_contact_exchange",
                "resolved_service_peer_trust",
            )
        }
        container.resolved_sqlite_client = db
        container.resolved_listing_service = listings
        container.resolved_capacity_runtime = capacity
        container.resolved_site_projections = site_projections
        container.resolved_domain_registry = registry
        container.resolved_marketplace_signer = TEST_MARKETPLACE_SIGNER
        container.resolved_system_service = SystemService(
            sqlite_client=db,
            marketplace_signer=TEST_MARKETPLACE_SIGNER,
            site_projections=site_projections,
        )
        container.resolved_admissibility_default = (
            parse_configured_admissibility_default()
        )
        container.resolved_pool_override_service = build_pool_override_service(
            sqlite_client=db,
            capacity_runtime=capacity,
            site_projections=site_projections,
            admissibility_default=container.resolved_admissibility_default,
        )
        routers: tuple[Any, ...] = ()
        if negotiation:
            previous["resolved_negotiation_runtime"] = getattr(
                container, "resolved_negotiation_runtime", None
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
                    site_projections=site_projections,
                    accepted_obligation_dispatch=(
                        composition.accepted_obligation_dispatch()
                        if contacts is not None
                        else None
                    ),
                )
            )
            routers = (negotiate_router,)
        contact_exchange = None
        if contacts is not None:
            repository = SettlementSQLiteRepository(db.db_path, apply_migrations=False)
            composition.repository = repository
            composition.runtime = SettlementRuntime(
                repository, {CONTACT_MECHANISM: ContactExchangeClient()}
            )
            contact_exchange = build_vm_contact_exchange(
                sqlite_client=db,
                settlement_composition=composition,
                known_origins=capacity.site_ids,
                delivery=None,
            )
            container.resolved_contact_exchange = contact_exchange
            routers = (*routers, introductions_router)
        try:
            admin_identity.initialize_administrator_identities(db.db_path)
            # The provisioning service's callbacks authenticate as a service
            # peer trusted for the home site, seeded as the lifespan seeds it.
            service_peer_trust = ServicePeerTrust(
                db.db_path,
                {
                    "provisioning": (
                        "service",
                        SITE,
                        TrustedIdentitySet(identities=(SERVICE_SIGNER.identity,)),
                    )
                },
            )
            service_peer_trust.seed()
            container.resolved_service_peer_trust = service_peer_trust
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
            app.middleware("http")(service_peer_callback_middleware)
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
            ) as buyer, StorefrontClient(
                "http://test",
                transport=transport,
                signer=SERVICE_SIGNER,
                caller_role="service",
                expected_publishers=_PUBLISHERS,
            ) as service:
                yield PublicationApp(
                    client,
                    seller,
                    db,
                    pools,
                    composition,
                    site,
                    buyer if negotiation else None,
                    recording,
                    projection,
                    site_b,
                    pools_b if second_site else None,
                    projection_b if second_site else None,
                    service,
                    app,
                    contact_exchange,
                    site_projections,
                    wakes,
                )
        finally:
            reset_site_event_cursors()
            thread_store._thread_store = None
            for name, value in previous.items():
                setattr(container, name, value)
