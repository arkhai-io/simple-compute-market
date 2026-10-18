from __future__ import annotations

import re
from dataclasses import replace
from types import SimpleNamespace
from importlib.metadata import entry_points

import httpx
import pytest
from fastapi import APIRouter
from storefront_client import StorefrontClient
from market_alkahest import ReleaseModelError
from market_core import DomainCapability
from core_storefront.domain_plugins import STOREFRONT_CONTRIBUTION_GROUP
from core_storefront.domain_registry import StorefrontDomainRegistryError
from core_storefront.identity_authority import (
    SERVICE_PEER_AUTHORITY,
    StorefrontIdentityAuthority,
)

from market_identity import Eip191Signer, TrustedIdentitySet
from settlement_compositions import alkahest_composition
from arkhai_bare_metal_storefront.alkahest_lifecycle import BareMetalAlkahestLifecycle
from arkhai_bare_metal_storefront.settlement_stages import DeclinedServicing
from arkhai_bare_metal_storefront.runtime import BareMetalStorefrontRuntime
from arkhai_bare_metal_storefront.sqlite_client import SQLiteClient
import arkhai_bare_metal_storefront.server as server_module
from arkhai_bare_metal_storefront.contribution import (
    BARE_METAL_STOREFRONT_CONTRIBUTION,
)
from arkhai_bare_metal_storefront.domain_runtime import get_market_domain_contract
from arkhai_bare_metal_storefront.fulfillment_service import fulfill_bare_metal
from arkhai_bare_metal_storefront.config import IDENTITY_CREDENTIAL_ENV
from arkhai_bare_metal_storefront.runtime import build_runtime_from_configuration
from arkhai_bare_metal_storefront.server import (
    build_bare_metal_storefront_app,
    build_bare_metal_storefront_registry,
)
from arkhai_bare_metal_storefront.settlement_composition import (
    BareMetalStorefrontSettlementComposition,
)
from arkhai_bare_metal_storefront.startup_refusal import BareMetalStartupError
from storefront_configuration import (
    ADMIN,
    CONTACT_SECTION,
    REGISTRY_URL,
    SELLER,
    SELLER_CREDENTIAL,
    SITE,
    SITE_ID,
    publishable_configuration,
    write_configuration,
)


COMPOSITION_SIGNER = Eip191Signer(bytes.fromhex("66" * 32))
# A second site authority's development key; never used on any public network.
OTHER_SITE = Eip191Signer(bytes.fromhex("77" * 32))


def _registry(domain=None):
    return build_bare_metal_storefront_registry(
        domain=domain or get_market_domain_contract()
    )


def test_app_injects_validated_bare_metal_contract_and_router() -> None:
    router = APIRouter()

    @router.get("/healthz")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    app = build_bare_metal_storefront_app(
        registry=_registry(),
        routers=(router,),
        root_path="/bare-metal",
    )

    assert app.title == "Arkhai Bare-Metal Storefront"
    assert app.root_path == "/bare-metal"
    assert app.state.storefront_binding.offering_mode == "bare_metal"
    assert "/healthz" in {route.path for route in app.routes}


def test_app_rejects_inconsistent_domain_before_startup() -> None:
    invalid = replace(
        get_market_domain_contract(),
        fulfillment=None,
    )

    with pytest.raises(
        StorefrontDomainRegistryError,
        match="provides no implementation",
    ):
        build_bare_metal_storefront_app(registry=_registry(invalid))


def test_runnable_http_contract_includes_fulfillment_claims() -> None:
    app = build_bare_metal_storefront_app(registry=_registry())
    paths = set(app.openapi()["paths"])

    assert {
        "/api/v1/listings",
        "/api/v1/listings/{listing_id}",
        "/api/v1/negotiate/new",
        "/api/v1/negotiate/{negotiation_id}",
        "/api/v1/settle/{escrow_uid}",
        "/api/v1/settle/{escrow_uid}/status",
        "/api/v1/fulfillments/{negotiation_id}/status",
        "/api/v1/fulfillments/{negotiation_id}/result",
        "/api/v1/fulfillments/{negotiation_id}/teardown",
        "/api/v1/admin/pause",
        "/api/v1/admin/resume",
        "/api/v1/system/status",
        "/health",
    } <= paths
    # Settlement starts fulfillment; no buyer request begins it.
    assert "/api/v1/fulfillments/begin" not in paths
    assert DomainCapability.FULFILLMENT in (
        get_market_domain_contract().declared_capabilities
    )
    settle_schema = app.openapi()["components"]["schemas"]["BareMetalSettleRequest"]
    assert set(settle_schema["properties"]) == {
        "negotiation_id",
        "buyer_principal",
        "buyer_evm_address",
    }


def test_registry_injects_exact_contract_binding_without_publication_source() -> None:
    contract = get_market_domain_contract()
    registry = _registry(contract)
    registration = registry.resolve_mode("bare_metal")

    app = build_bare_metal_storefront_app(registry=registry)

    assert registration.contract is contract
    assert registry.resolve(registration.binding) is contract
    assert app.state.storefront_binding == registration.binding
    assert app.state.market_domains == registry.projection()
    assert not hasattr(app.state, "publication_source")


@pytest.mark.asyncio
async def test_lifespan_exposes_exact_bare_metal_runtime_without_global_lookup(
    monkeypatch,
) -> None:
    domain = get_market_domain_contract()
    runtime = SimpleNamespace(domain=domain)
    started = []

    async def start(selected):
        started.append(selected)

    monkeypatch.setattr(server_module, "_start_runtime", start)
    app = build_bare_metal_storefront_app(
        registry=_registry(domain),
        runtime=runtime,
    )

    async with app.router.lifespan_context(app):
        assert app.state.storefront_container is runtime
        assert app.state.storefront_container.domain is domain
    assert app.state.storefront_container is None
    assert started == [runtime]


def test_installed_contribution_exposes_complete_bare_metal_contract() -> None:
    contribution = BARE_METAL_STOREFRONT_CONTRIBUTION
    matching = [
        entry_point
        for entry_point in entry_points(group=STOREFRONT_CONTRIBUTION_GROUP)
        if entry_point.name == "bare_metal"
    ]
    contract = contribution.build_contract()

    assert len(matching) == 1
    assert matching[0].load() is contribution
    assert contribution.contribution_id == "bare_metal"
    assert contract is get_market_domain_contract()
    assert contract.publication is not None
    assert contract.storefront is not None
    assert contract.settlement is not None
    assert contract.fulfillment is not None
    assert contract.fulfillment.fulfill is fulfill_bare_metal


def _direct_runtime(tmp_path, **overrides):
    domain = get_market_domain_contract()
    values = dict(
        db=SQLiteClient(str(tmp_path / "storefront.db"), domain=domain),
        domain=domain,
        seller_principal=COMPOSITION_SIGNER.identity,
        admin_principals=TrustedIdentitySet(identities=(COMPOSITION_SIGNER.identity,)),
        storefront_url="http://seller:8000",
        marketplace_signer=COMPOSITION_SIGNER,
    )
    values.update(overrides)
    return BareMetalStorefrontRuntime(**values)


async def test_a_runtime_without_a_settlement_composition_has_no_settlement(
    tmp_path,
) -> None:
    runtime = _direct_runtime(
        tmp_path, seller_evm_address="0x" + "33" * 20
    )

    assert runtime.settlement_worker is None
    assert "settlement-servicing" not in runtime.loops.step_routes()
    with pytest.raises(RuntimeError, match="no bare-metal settlement mechanism is configured"):
        runtime.settlement_service()
    health = await runtime.health()
    assert health["checks"]["commercial_settlement"] == "unavailable"


async def test_an_alkahest_only_runtime_composes_the_worker_and_its_step(
    tmp_path,
) -> None:
    chain_clients = {"anvil": object()}
    runtime = _direct_runtime(
        tmp_path,
        seller_evm_address="0x" + "33" * 20,
        settlement_composition=alkahest_composition(
            COMPOSITION_SIGNER,
            wallet="0x" + "33" * 20,
            chain_clients=chain_clients,
        ),
    )

    assert runtime.settlement_worker is not None
    assert "settlement-servicing" in runtime.loops.step_routes()
    service = runtime.settlement_service()
    assert service.chain_clients == chain_clients
    health = await runtime.health()
    assert health["checks"]["commercial_settlement"] == "ok"


async def test_each_entry_composes_its_own_obligation_servicing(tmp_path) -> None:
    runtime = _direct_runtime(
        tmp_path,
        seller_evm_address="0x" + "33" * 20,
        settlement_composition=alkahest_composition(
            COMPOSITION_SIGNER,
            wallet="0x" + "33" * 20,
            chain_clients={"anvil": object()},
        ),
    )

    # Alkahest delivers through its lifecycle; contact exchange's reveal binds
    # its own obligation, so its entry declines; payments has no obligations.
    assert isinstance(
        runtime.obligation_servicing["alkahest.v1"], BareMetalAlkahestLifecycle
    )
    assert isinstance(
        runtime.obligation_servicing["contact-exchange.v1"], DeclinedServicing
    )
    assert "arkhai.payments.v1" not in runtime.obligation_servicing


async def test_a_root_that_enables_no_payment_reports_settlement_unconfigured(
    tmp_path,
) -> None:
    # The Alkahest section stays configured, for the deals accepted under it,
    # while nothing is enabled for new ones.
    runtime = _direct_runtime(
        tmp_path,
        seller_evm_address="0x" + "33" * 20,
        settlement_composition=alkahest_composition(
            COMPOSITION_SIGNER,
            wallet="0x" + "33" * 20,
            chain_clients={"anvil": object()},
            enabled=False,
        ),
        fulfillment_client=object(),
    )

    health = await runtime.health()

    assert health["checks"]["commercial_settlement"] == "unconfigured"
    # A deliberate choice is reported, not counted as a degradation.
    assert health["status"] == "ok"
    assert runtime.settlement_worker is not None


async def test_startup_refuses_a_release_model_bare_metal_cannot_deliver(
    tmp_path,
) -> None:
    def interruptible_runtime() -> BareMetalStorefrontRuntime:
        return _direct_runtime(
            tmp_path,
            seller_evm_address="0x" + "33" * 20,
            settlement_composition=alkahest_composition(
                COMPOSITION_SIGNER,
                wallet="0x" + "33" * 20,
                chain_clients={"anvil": object()},
                section={"interruptible": True},
            ),
        )

    app = build_bare_metal_storefront_app(
        registry=_registry(), runtime_factory=interruptible_runtime
    )

    with pytest.raises(ReleaseModelError, match="'interruptible' release model"):
        async with app.router.lifespan_context(app):
            pass
    # Refused while composing its services: no storefront was ever installed.
    assert getattr(app.state, "storefront_container", None) is None


async def test_an_oracle_gated_section_composes(tmp_path) -> None:
    runtime = _direct_runtime(
        tmp_path,
        seller_evm_address="0x" + "33" * 20,
        settlement_composition=alkahest_composition(
            COMPOSITION_SIGNER,
            wallet="0x" + "33" * 20,
            chain_clients={"anvil": object()},
            section={
                "oracle_gated": True,
                "trusted_oracle_addresses": ["0x" + "cd" * 20],
            },
        ),
    )

    assert runtime.settlement_worker is not None


# -- composed from the configuration files -------------------------------------
#
# The server composes its runtime only from its configuration files, so the
# tests above, which construct a runtime directly, cannot see a defect there.
# Each case below writes the files under a temporary XDG_CONFIG_HOME, as a
# deployment mounts them; every value is a development fixture.


ALKAHEST_SECTION = {
    "enabled": True,
    "address_config_path": "/app/alkahest_anvil_addresses.json",
    "oracle_gated": False,
    "trusted_oracle_addresses": [],
    "interruptible": False,
    "interruptible_oracle_addresses": [],
}
WALLET_ADDRESS = "0x" + "33" * 20
WALLET_KEY = "0x" + "55" * 32
CHAINS = {"anvil": {"rpc_url": "http://anvil.test:8545"}}


class ChainClients:
    """Stands in for the Alkahest chain clients, the boundary to the chain."""

    def __init__(self) -> None:
        self.policies: list = []
        self.built = {"anvil": object()}

    def __call__(self, policy, **_kwargs):
        self.policies.append(policy)
        return self.built


def _alkahest(document: dict, *, enabled: bool = True) -> dict:
    settlement = document["Settlement"]
    settlement["alkahest"] = {**ALKAHEST_SECTION, "enabled": enabled}
    if enabled:
        settlement["priority"] = ["alkahest.v1", "contact-exchange.v1"]
    return document


def _configured_runtime(monkeypatch, tmp_path, document=None, *, secrets=None, **kwargs):
    write_configuration(
        monkeypatch,
        tmp_path,
        publishable_configuration(tmp_path / "storefront.db") if document is None else document,
        secrets=secrets,
    )
    kwargs.setdefault("credential", SELLER_CREDENTIAL)
    return build_runtime_from_configuration(**kwargs)


def test_the_runtime_takes_its_principal_and_administrators_from_configuration(
    monkeypatch, tmp_path
):
    runtime = _configured_runtime(monkeypatch, tmp_path)

    assert runtime.seller_principal == SELLER.identity
    assert runtime.marketplace_signer.identity == SELLER.identity
    assert runtime.admin_principals.identities == (ADMIN.identity,)
    assert runtime.storefront_url == "http://seller:8000"
    assert [binding.site_id for binding in runtime.site_bindings] == [SITE_ID]
    assert runtime.pool_override_service() is not None


def test_startup_seeds_each_sites_service_peer_into_durable_identity_state(
    monkeypatch, tmp_path
):
    """Composition: the root's builder over real SQLite. The site is bound to its
    peer, not a principal, and the peer's principal is what durable state, and
    so the trust its responses and callbacks verify against, now holds."""
    runtime = _configured_runtime(monkeypatch, tmp_path)

    assert runtime.site_bindings[0].service_peer == "site_a_authority"
    assert runtime.service_peer_trust.site_trusted_set(SITE_ID).identities == (
        SITE.identity,
    )
    durable = StorefrontIdentityAuthority(runtime.db.db_path).status(
        authority=SERVICE_PEER_AUTHORITY, subject="site_a_authority"
    )
    assert durable.primary == SITE.identity
    assert durable.role == "service"


def test_configuration_that_no_longer_covers_a_seeded_peer_is_refused(
    monkeypatch, tmp_path
):
    """Composition: a peer already seeded owns its principals, so configuration
    naming another primary for it refuses startup rather than overwrite them
    (spec "Startup configuration is stale during rotation")."""
    _configured_runtime(monkeypatch, tmp_path)
    document = publishable_configuration(tmp_path / "storefront.db")
    document["Identity"]["service_peers"]["site_a_authority"]["principals"] = [
        OTHER_SITE.identity.model_dump(mode="json")
    ]

    with pytest.raises(RuntimeError, match="service peers cannot be seeded"):
        _configured_runtime(monkeypatch, tmp_path, document)


def test_a_credential_that_does_not_own_the_identity_is_refused(monkeypatch, tmp_path):
    with pytest.raises(RuntimeError, match="Identity.principal"):
        _configured_runtime(monkeypatch, tmp_path, credential="0x" + "22" * 32)


def test_the_credential_is_read_from_its_own_environment_variable(monkeypatch, tmp_path):
    monkeypatch.setenv(IDENTITY_CREDENTIAL_ENV, SELLER_CREDENTIAL)
    write_configuration(
        monkeypatch, tmp_path, publishable_configuration(tmp_path / "storefront.db")
    )

    assert build_runtime_from_configuration().seller_principal == SELLER.identity


def test_every_interval_and_term_is_read_from_configuration(monkeypatch, tmp_path):
    document = publishable_configuration(tmp_path / "storefront.db")
    document.update(
        negotiation_timeout_seconds=900,
        negotiation_watchdog_interval=45,
        settlement_servicing_interval_seconds=12,
        payment_reconciliation_interval=8,
        pricing={
            "default_max_duration_seconds": 7200,
            "settlements": [
                {
                    "mechanism": "alkahest.v1",
                    "asset": "0x" + "9f" * 20,
                    "rate": "10",
                    "per": "hour",
                    "mechanism_input": {
                        "chain": "anvil",
                        "escrow_kind": "erc20_escrow_obligation_default",
                    },
                }
            ],
        },
        negotiation={"policies": ["escrow_shape_guard", "bisection"]},
    )

    runtime = _configured_runtime(monkeypatch, tmp_path, document)

    assert runtime.negotiation_watchdog.timeout_seconds == 900
    assert runtime.negotiation_watchdog.interval_seconds == 45
    assert runtime.negotiation_watchdog.terminal_state == "abandoned"
    assert runtime.settlement_servicing_interval_seconds == 12
    assert runtime.payment_reconciliation_interval_seconds == 8
    assert runtime.default_max_duration_seconds == 7200
    assert [clause.mechanism for clause in runtime.publication_clauses] == ["alkahest.v1"]
    assert runtime.negotiation_policies == ["escrow_shape_guard", "bisection"]


def test_the_seller_chain_defaults_when_none_is_configured(monkeypatch, tmp_path):
    assert _configured_runtime(monkeypatch, tmp_path).negotiation_policies is None


def test_an_unknown_seller_policy_is_refused_at_composition(monkeypatch, tmp_path):
    document = publishable_configuration(tmp_path / "storefront.db")
    document["negotiation"] = {"policies": ["no_such_policy"]}

    with pytest.raises(KeyError, match="no_such_policy"):
        _configured_runtime(monkeypatch, tmp_path, document)


def test_publication_reaches_every_configured_registry(monkeypatch, tmp_path):
    document = publishable_configuration(tmp_path / "storefront.db")
    second = "http://registry-b.test:8080"
    document["registry"]["urls"].append(second)
    document["registry"]["authorities"][second] = {
        "authority": "registry-b",
        "principals": [SITE.identity.model_dump(mode="json")],
    }

    configured = _configured_runtime(monkeypatch, tmp_path, document).registry_configuration

    assert configured.urls == (REGISTRY_URL, second)
    assert configured.authorities[second].authority == "registry-b"
    client = configured.client_factory(SELLER)()
    assert client.urls == [REGISTRY_URL, second]


def test_publication_clauses_that_do_not_compile_are_refused_at_startup(
    monkeypatch, tmp_path
):
    document = publishable_configuration(tmp_path / "storefront.db")
    document["pricing"] = {"settlements": [{"mechanism": "alkahest.v1"}]}

    with pytest.raises(RuntimeError, match=r"\[pricing\].settlements"):
        _configured_runtime(monkeypatch, tmp_path, document)


@pytest.mark.parametrize("enabled", [True, False])
def test_a_configured_alkahest_section_composes_its_client_and_worker(
    monkeypatch, tmp_path, enabled
):
    document = _alkahest(publishable_configuration(tmp_path / "storefront.db"), enabled=enabled)
    document["Wallet"] = {"address": WALLET_ADDRESS}
    document["Chains"] = {
        "anvil": {**CHAINS["anvil"], "alkahest_address_config_path": "addresses.json"}
    }
    chain_clients = ChainClients()

    runtime = _configured_runtime(
        monkeypatch,
        tmp_path,
        document,
        secrets=f'[Wallet]\nprivate_key = "{WALLET_KEY}"\n',
        build_chain_clients=chain_clients,
    )

    assert "alkahest.v1" in runtime.settlement_clients
    assert runtime.settlement_composition.resources["clients"] == chain_clients.built
    assert runtime.chain_config_paths == {"anvil": "addresses.json"}
    (policy,) = chain_clients.policies
    assert policy.chains[0].rpc_url == "http://anvil.test:8545"
    # The wallet key reaches the chain clients from the overlay, nowhere else.
    assert policy.private_key == WALLET_KEY
    assert WALLET_KEY not in repr(runtime)
    assert runtime.settlement_worker is not None
    assert "settlement-servicing" in runtime.loops.step_routes()


@pytest.mark.parametrize("enabled", [True, False])
@pytest.mark.parametrize("missing", ["[Wallet].address", "[Chains]", "[Wallet].private_key"])
def test_a_configured_alkahest_section_requires_every_input(
    monkeypatch, tmp_path, enabled, missing
):
    document = _alkahest(publishable_configuration(tmp_path / "storefront.db"), enabled=enabled)
    if missing != "[Wallet].address":
        document["Wallet"] = {"address": WALLET_ADDRESS}
    if missing != "[Chains]":
        document["Chains"] = CHAINS
    secrets = None if missing == "[Wallet].private_key" else f'[Wallet]\nprivate_key = "{WALLET_KEY}"\n'

    with pytest.raises(RuntimeError, match=re.escape(missing)):
        _configured_runtime(
            monkeypatch, tmp_path, document, secrets=secrets, build_chain_clients=ChainClients()
        )


@pytest.mark.parametrize("stale", ["[Wallet].address", "[Chains]", "[Wallet].private_key"])
def test_alkahest_inputs_without_a_section_are_refused(monkeypatch, tmp_path, stale):
    document = publishable_configuration(tmp_path / "storefront.db")
    secrets = None
    if stale == "[Wallet].address":
        document["Wallet"] = {"address": WALLET_ADDRESS}
    elif stale == "[Chains]":
        document["Chains"] = CHAINS
    else:
        secrets = f'[Wallet]\nprivate_key = "{WALLET_KEY}"\n'

    with pytest.raises(RuntimeError, match="no Alkahest section"):
        _configured_runtime(monkeypatch, tmp_path, document, secrets=secrets)


@pytest.mark.parametrize("enabled", [True, False])
def test_a_release_model_bare_metal_cannot_deliver_is_refused_by_name(
    monkeypatch, tmp_path, enabled
):
    document = _alkahest(publishable_configuration(tmp_path / "storefront.db"), enabled=enabled)
    document["Settlement"]["alkahest"]["interruptible"] = True
    document["Wallet"] = {"address": WALLET_ADDRESS}
    document["Chains"] = CHAINS

    with pytest.raises(RuntimeError, match="'interruptible' release model"):
        _configured_runtime(
            monkeypatch,
            tmp_path,
            document,
            secrets=f'[Wallet]\nprivate_key = "{WALLET_KEY}"\n',
            build_chain_clients=ChainClients(),
        )


def test_a_disabled_section_is_still_configured():
    # Disabled sections still own recovery for their accepted obligations.
    root = {
        "schema_version": 1,
        "priority": ["contact-exchange.v1"],
        "contact": CONTACT_SECTION,
        "alkahest": {**ALKAHEST_SECTION, "enabled": False},
    }

    composition = BareMetalStorefrontSettlementComposition.from_raw_config(root)

    assert composition.enabled_mechanisms == ("contact-exchange.v1",)
    assert composition.configures("alkahest.v1")
    assert composition.configures("contact-exchange.v1")


def test_a_contact_only_root_composes_its_obligation_worker(monkeypatch, tmp_path):
    runtime = _configured_runtime(monkeypatch, tmp_path)

    # Contact exchange declines its obligations; nothing services Alkahest.
    assert set(runtime.obligation_servicing) == {"contact-exchange.v1"}
    assert runtime.settlement_worker is not None


def _without_registry(document: dict) -> dict:
    document["registry"] = {"urls": []}
    return document


def _unpinned_registry(document: dict) -> dict:
    document["registry"]["authorities"] = {}
    return document


def _no_mechanism(document: dict) -> dict:
    document["Settlement"] = {"schema_version": 1, "priority": []}
    return document


def _no_site(document: dict) -> dict:
    document["capacity"] = {"sites": {}}
    return document


def _site_without_peer(document: dict) -> dict:
    document["Identity"]["service_peers"] = {}
    return document


def _site_with_two_peers(document: dict) -> dict:
    peers = document["Identity"]["service_peers"]
    peers["site_a_second"] = {
        **peers["site_a_authority"],
        "principals": [OTHER_SITE.identity.model_dump(mode="json")],
    }
    return document


@pytest.mark.parametrize(
    ("broken", "named"),
    [
        pytest.param(_without_registry, "no registry to publish to", id="no registry"),
        pytest.param(_unpinned_registry, r"\[registry.authorities\] must pin exactly",
                     id="a registry without its pin"),
        pytest.param(_no_mechanism, "no settlement mechanism is enabled", id="no mechanism"),
        pytest.param(_no_site, "no site to publish from", id="no site"),
        pytest.param(_site_without_peer, "site 'site-a' is bound to no service peer",
                     id="a site with no service peer"),
        pytest.param(_site_with_two_peers, "site 'site-a' is bound to 2 service peers",
                     id="a site with two service peers"),
    ],
)
async def test_a_storefront_that_cannot_publish_refuses_to_start(
    monkeypatch, tmp_path, broken, named
):
    """Application startup: the real app and its lifespan, composing from the
    configuration files. Each refusal names its problem, and nothing durable or
    running exists afterwards: no database file, no installed storefront, so no
    loop. Spec scenarios: "A bare-metal storefront has no registry", "A site has
    no service peer"."""
    database = tmp_path / "storefront.db"
    write_configuration(monkeypatch, tmp_path, broken(publishable_configuration(database)))
    monkeypatch.setenv(IDENTITY_CREDENTIAL_ENV, SELLER_CREDENTIAL)
    app = build_bare_metal_storefront_app(registry=_registry())

    with pytest.raises(BareMetalStartupError, match=named) as refused:
        async with app.router.lifespan_context(app):
            pass

    assert str(refused.value).startswith("the storefront cannot publish: ")
    assert not database.exists()
    assert getattr(app.state, "storefront_container", None) is None


async def test_every_problem_is_named_in_one_refusal(monkeypatch, tmp_path):
    document = _no_site(_no_mechanism(_without_registry(
        publishable_configuration(tmp_path / "storefront.db")
    )))
    write_configuration(monkeypatch, tmp_path, document)

    with pytest.raises(BareMetalStartupError) as refused:
        build_runtime_from_configuration(credential=SELLER_CREDENTIAL)

    message = str(refused.value)
    for problem in ("no registry", "no settlement mechanism", "no site"):
        assert problem in message


async def test_a_storefront_configured_through_files_starts_and_serves(
    monkeypatch, tmp_path
):
    """Application startup through the lifespan, from the files alone, with an
    override through the loader's environment layer applied rather than refused.
    Spec scenario: "An operator overrides a setting on a development cluster"."""
    write_configuration(
        monkeypatch, tmp_path, publishable_configuration(tmp_path / "storefront.db")
    )
    monkeypatch.setenv(IDENTITY_CREDENTIAL_ENV, SELLER_CREDENTIAL)
    monkeypatch.setenv("STOREFRONT_NEGOTIATION_WATCHDOG_INTERVAL", "45")
    app = build_bare_metal_storefront_app(registry=_registry())

    async with app.router.lifespan_context(app):
        runtime = app.state.storefront_container
        async with StorefrontClient(
            "http://seller", transport=httpx.ASGITransport(app=app)
        ) as public:
            health = await public.get_health()

    assert runtime.negotiation_watchdog.interval_seconds == 45
    assert runtime.seller_principal == SELLER.identity
    assert health.status == "ok"
    assert (tmp_path / "storefront.db").exists()
