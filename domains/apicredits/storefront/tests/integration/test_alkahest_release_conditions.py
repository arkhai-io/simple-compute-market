"""The release conditions an API-credit listing advertises for Alkahest.

The real app and lifespan compose the storefront from configuration: its signer
from a development credential supplied as the Secret boundary supplies it, its
settlement composition, wallet, and chains, and the listing service the route
reaches. Three seams stand in for what lies beyond the storefront: the quota
site's capacity runtime, which the listing service resolves through
``build_capacity_runtime``; the startup tasks, which preflight the credits
service and start the timer loops; and the chain probe's JSON-RPC transport,
the boundary to the chain, supplied through the app's composition seams and
answering as a deployed chain does. The anvil
chain's address book is the development chain's. Every address and key here is
a deterministic development value, never used on a public network.
"""

from __future__ import annotations

import asyncio
import base64
import threading
from contextlib import asynccontextmanager, contextmanager
from copy import deepcopy
from unittest.mock import patch

import httpx
import pytest
from market_alkahest import ReleaseModelError
from market_alkahest.alkahest import get_recipient_arbiter
from market_alkahest.dev_chain import anvil_address_book_path
from market_config.config_loader import ChainConfig
from market_identity import Ed25519Signer, TrustedIdentitySet
from storefront_client import StorefrontClient
from storefront_client.client import StorefrontClientError

import apicredits_storefront.container as container
import apicredits_storefront.server as server
from apicredits_storefront.domain_runtime import get_market_domain_contract
from apicredits_storefront.listing_publication import ApiCreditListingClient
from apicredits_storefront.services import capacity_client as capacity_module
from apicredits_storefront.utils import config as storefront_config
from apicredits_storefront.utils import sqlite_client as sqlite_module
from tests.integration.test_publish_reconcile import _QuotaRuntime

SEED = b"\x22" * 32
SELLER_SIGNER = Ed25519Signer(SEED)
ADMIN_SIGNER = Ed25519Signer(b"\x44" * 32)
# Anvil's first published development account, a key and the address it signs
# as, so the seller wallet names one account; never used on a public network.
SELLER_WALLET = "0xf39fd6e51aad88f6f4ce6ab8827279cfffb92266"
SELLER_WALLET_KEY = "0xac0974bec39a17e36ba4a6b4d238ff944bacb478cbed5efcae784d7bf4f2ff80"
ORACLE = "0x" + "cd" * 20
ESCROW = {
    "chain_name": "anvil",
    "escrow_address": "0x" + "11" * 20,
    "literal_fields": {"token": "0x" + "01" * 20},
    "rates": [{"field": "amount", "per": "token", "value": "100"}],
}
ANVIL = ChainConfig(
    name="anvil",
    rpc_url="http://anvil.test",
    chain_id=31337,
    alkahest_address_config_path=str(anvil_address_book_path()),
)
ALKAHEST_CLAUSE = {
    "mechanism": "alkahest.v1",
    "asset": "0x" + "01" * 20,
    "rate": "100",
    "per": "token",
    "mechanism_input": {
        "chain": "anvil",
        "escrow_kind": "erc20_escrow_obligation_default",
    },
}


def _deployed_chain(rpc_url, method, params, timeout):
    """The chain's JSON-RPC endpoint, answering as the deployed dev chain."""
    return hex(31337) if method == "eth_chainId" else "0x6080"


@contextmanager
def _replaced(**roots):
    """Replace whole settings roots: an override would merge into the test
    configuration's own tables."""
    settings = storefront_config.settings
    saved = {name: deepcopy(settings.get(name)) for name in roots}
    try:
        for name, value in roots.items():
            settings.unset(name, force=True)
            settings.set(name, value)
        yield
    finally:
        for name, value in saved.items():
            settings.unset(name, force=True)
            if value is not None:
                settings.set(name, value)


def _settlement(*, enabled: bool = True, **alkahest) -> dict:
    return {
        "schema_version": 1,
        "priority": ["alkahest.v1"] if enabled else [],
        "alkahest": {"enabled": enabled, **alkahest},
    }


@pytest.fixture
def storefront(tmp_path, monkeypatch):
    """The configuration a seller's storefront starts from, and its database path."""
    db_path = tmp_path / "credits-storefront.db"
    monkeypatch.setenv(
        "ARKHAI_IDENTITY_CREDENTIAL", base64.urlsafe_b64encode(SEED).rstrip(b"=").decode()
    )
    # The process's database client is created by the first startup; each test
    # starts from none and leaves none behind.
    monkeypatch.setattr(sqlite_module, "_sqlite_client", None)

    async def no_startup_tasks(*, domain):
        return None

    monkeypatch.setattr(server, "_startup_tasks", no_startup_tasks)
    monkeypatch.setattr(
        capacity_module,
        "build_capacity_runtime",
        lambda factory: _QuotaRuntime({"svc-quota": 42}),
    )
    identity = SELLER_SIGNER.identity
    with _replaced(
        identity={
            "scheme": identity.scheme.value,
            "identifier": identity.identifier,
            "admin_principals": {
                "identities": [ADMIN_SIGNER.identity.model_dump(mode="json")]
            },
        },
        wallet={"address": SELLER_WALLET, "private_key": SELLER_WALLET_KEY},
        db_path=str(db_path),
        # A quota site the startup refusal can read; its runtime is the test's.
        capacity={
            "placement": "fill_first",
            "sites": {
                "quota-site": {
                    "url": "http://quota-site.invalid:8082",
                    "expected_authorities": {
                        "identities": [ADMIN_SIGNER.identity.model_dump(mode="json")]
                    },
                }
            },
        },
    ), patch.dict(storefront_config.CHAINS, {"anvil": ANVIL}, clear=True):
        yield db_path


def _app(seams=None):
    # The chain probe's JSON-RPC transport is the composition's seam to the
    # chain; the SDK, which the probe builds its clients with, builds them over
    # the HTTP rpc_url without calling it.
    return server.build_api_credits_storefront_app(
        registry=server.build_api_credits_storefront_registry(
            domain=get_market_domain_contract()
        ),
        seams=seams or server.ApiCreditCompositionSeams(alkahest_json_rpc=_deployed_chain),
    )


@asynccontextmanager
async def _started(settlement: dict, *, probed: bool = True, seams=None):
    """The started storefront under ``settlement``, its chain probed once
    unless ``probed`` is false."""
    app = _app(seams)
    with _replaced(settlement=settlement):
        async with app.router.lifespan_context(app):
            probe = container.resolved_alkahest_chain_probe
            if probe is not None and probed:
                await probe.step()
            transport = httpx.ASGITransport(app=app)
            async with StorefrontClient(
                "http://seller",
                signer=SELLER_SIGNER,
                caller_role="seller",
                expected_publishers=TrustedIdentitySet(identities=(SELLER_SIGNER.identity,)),
                transport=transport,
            ) as seller, StorefrontClient(
                "http://seller", transport=transport
            ) as public, StorefrontClient(
                "http://seller",
                signer=ADMIN_SIGNER,
                caller_role="admin",
                expected_publishers=TrustedIdentitySet(identities=(SELLER_SIGNER.identity,)),
                transport=transport,
            ) as admin:
                yield ApiCreditListingClient(seller, seller=SELLER_SIGNER.identity), public, admin


def _supplied_escrows() -> dict:
    return {
        "resource_id": "svc-quota",
        "service_name": "Acme Inference",
        "accepted_escrows": [dict(ESCROW)],
    }


async def test_a_contradictory_release_model_refuses_startup(storefront):
    app = _app()
    with _replaced(
        settlement=_settlement(
            oracle_gated=True, trusted_oracle_addresses=[ORACLE], interruptible=True
        )
    ):
        with pytest.raises(ReleaseModelError, match="mutually exclusive"):
            async with app.router.lifespan_context(app):
                pass

    # Refused before the storefront opened its database.
    assert sqlite_module._sqlite_client is None
    assert not storefront.exists()


async def test_a_published_listing_advertises_the_recipient_arbiter_paying_the_seller(
    storefront,
):
    async with _started(_settlement()) as (listings, public, _admin):
        created = await listings.publish_from_quota(_supplied_escrows())
        listing = await public.get_listing(created.listing_id)

    assert created.status == "created"
    assert listing.extra["demands"] == [
        {
            "chain_name": "anvil",
            "arbiter": get_recipient_arbiter(
                "anvil", config_path=str(anvil_address_book_path())
            ).lower(),
            "demand_data": {"recipient": SELLER_WALLET.lower()},
        }
    ]


async def test_a_seller_stating_only_a_key_publishes_the_keys_account_as_recipient(
    storefront,
):
    with _replaced(wallet={"private_key": SELLER_WALLET_KEY}):
        async with _started(_settlement()) as (listings, public, _admin):
            created = await listings.publish_from_quota(_supplied_escrows())
            listing = await public.get_listing(created.listing_id)

    assert created.status == "created"
    assert [demand["demand_data"] for demand in listing.extra["demands"]] == [
        {"recipient": SELLER_WALLET.lower()}
    ]


UNSETTLEABLE = {
    "interruptible": (
        {"interruptible": True, "interruptible_oracle_addresses": [ORACLE]},
        "alkahest.release_model_undeliverable",
    ),
    "no-oracle": ({"oracle_gated": True}, "alkahest.oracle_policy_invalid"),
}


@pytest.mark.parametrize("case", sorted(UNSETTLEABLE))
async def test_an_unsettleable_section_starts_and_its_status_names_the_blocker(
    storefront, case
):
    """Spec scenario "An Alkahest section that cannot settle makes Alkahest
    unready": the storefront starts, and the administrator's status reports
    Alkahest unready with the configuration blocker."""
    section, blocker = UNSETTLEABLE[case]
    async with _started(_settlement(**section)) as (_listings, _public, admin):
        status = await admin.get_system_status()

    (alkahest,) = [item for item in status.settlement if item["mechanism"] == "alkahest.v1"]
    assert alkahest["ready"] is False
    assert (blocker, "configuration") in {(b["code"], b["kind"]) for b in alkahest["blockers"]}


@pytest.mark.parametrize("case", sorted(UNSETTLEABLE))
async def test_supplied_escrows_publish_no_alkahest_option_while_it_is_unready(
    storefront, case
):
    """Spec scenario "An API-credit listing request supplies its escrows":
    with Alkahest unready no condition is derived for them and no Alkahest
    option publishes, so a listing whose only option they were is refused."""
    section, blocker = UNSETTLEABLE[case]
    async with _started(_settlement(**section)) as (listings, _public, _admin):
        with pytest.raises(StorefrontClientError, match=blocker) as refused:
            await listings.publish_from_quota(_supplied_escrows())

    assert refused.value.status_code == 400


@pytest.mark.parametrize("case", sorted(UNSETTLEABLE))
async def test_alkahest_clauses_compile_no_option_while_it_is_unready(storefront, case):
    """The clause path: the composition the route uses compiles no Alkahest
    escrow and derives no condition while Alkahest is unready, and its
    readiness names the configuration blocker."""
    section, blocker = UNSETTLEABLE[case]
    async with _started(_settlement(**section)):
        composition = container.resolved_settlement_composition
        escrows, options, readiness = await composition.publication_artifacts(
            {
                "claimant_principal": SELLER_SIGNER.identity,
                "resource_id": "svc-quota",
                "service": "Acme Inference",
            },
            [dict(ALKAHEST_CLAUSE)],
        )
        assert (escrows, options) == ([], [])
        assert blocker in {b.code for status in readiness for b in status.blockers}
        assert composition.release_conditions([dict(ESCROW)], readiness=readiness) == []


def _clause_request(mechanism: str = "alkahest.v1") -> dict:
    return {
        "resource_id": "svc-quota",
        "service_name": "Acme Inference",
        "settlement_clauses": [{**ALKAHEST_CLAUSE, "mechanism": mechanism}],
    }


@pytest.mark.parametrize("mechanism", ["alkahest.v1", "alkahest"])
async def test_a_clause_create_before_the_chain_is_reached_answers_503(
    storefront, mechanism
):
    """A clause may name its mechanism by ID or by configuration key."""
    async with _started(_settlement(), probed=False) as (listings, _public, _admin):
        with pytest.raises(StorefrontClientError) as refused:
            await listings.publish_from_quota(_clause_request(mechanism))

    assert refused.value.status_code == 503
    assert "alkahest.v1 (chain anvil)" in str(refused.value)


@pytest.mark.parametrize("case", sorted(UNSETTLEABLE))
async def test_a_create_unready_for_configuration_before_the_chain_is_reached_answers_400(
    storefront, case
):
    """Not retryable: the configuration blocker stands whatever the chain answers."""
    section, blocker = UNSETTLEABLE[case]
    async with _started(_settlement(**section), probed=False) as (listings, _p, _a):
        with pytest.raises(StorefrontClientError, match=blocker) as refused:
            await listings.publish_from_quota(_supplied_escrows())

    assert refused.value.status_code == 400


@pytest.mark.parametrize("case", sorted(UNSETTLEABLE))
async def test_a_clause_create_while_alkahest_is_unready_for_configuration_answers_400(
    storefront, case
):
    section, blocker = UNSETTLEABLE[case]
    async with _started(_settlement(**section)) as (listings, _public, _admin):
        with pytest.raises(StorefrontClientError, match=blocker) as refused:
            await listings.publish_from_quota(_clause_request())

    assert refused.value.status_code == 400


async def test_a_create_before_the_chain_is_reached_answers_503_until_a_probe_reaches_it(
    storefront,
):
    """Spec scenario "An operator creates a listing before the chain is
    reached": the create is refused as retryable, naming Alkahest, and the same
    request succeeds once a stepped probe reaches the chain."""
    async with _started(_settlement(), probed=False) as (listings, public, admin):
        with pytest.raises(StorefrontClientError, match="alkahest.v1") as refused:
            await listings.publish_from_quota(_supplied_escrows())
        await admin.admin_run_lifecycle_cycle("alkahest-chain-probe")
        created = await listings.publish_from_quota(_supplied_escrows())
        listing = await public.get_listing(created.listing_id)

    assert refused.value.status_code == 503
    assert "alkahest.v1 (chain anvil)" in str(refused.value)
    assert "retry" in str(refused.value)
    assert created.status == "created"
    assert [escrow["chain_name"] for escrow in listing.extra["accepted_escrows"]] == ["anvil"]


SEED_LISTING = {
    "resource_id": "svc-quota",
    "service_name": "Acme Inference",
    "chain": "anvil",
    "token": ESCROW["literal_fields"]["token"],
    "escrow_address": ESCROW["escrow_address"],
    "price_per_token": "100",
}


async def test_the_seed_waits_for_its_chain_and_publishes_once_a_probe_reaches_it(
    storefront,
):
    """Spec scenario "A storefront starts with its chain down": the seed's step
    waits while the chain is unprobed and publishes after a probe reaches it,
    with no restart. Its quota registration, the boundary to the credits
    service, is replaced on the started storefront's seed."""
    registered = []

    async def register(**request):
        registered.append(request)

    with _replaced(seed=dict(SEED_LISTING)):
        async with _started(_settlement(), probed=False) as (_listings, public, admin):
            container.resolved_listing_seed.register_quota = register
            waiting = await admin.admin_run_lifecycle_cycle("listing-seed")
            await admin.admin_run_lifecycle_cycle("alkahest-chain-probe")
            done = await admin.admin_run_lifecycle_cycle("listing-seed")
            listing = await public.get_listing(done["listing_id"])

    assert (waiting["state"], waiting["mechanisms"]) == ("waiting", ["alkahest.v1"])
    assert done["state"] == "done"
    assert [escrow["chain_name"] for escrow in listing.extra["accepted_escrows"]] == ["anvil"]
    # Registered once: the ledger re-asserts a registration it already holds.
    assert [request["resource_id"] for request in registered] == ["svc-quota"]


class _Chains:
    """Each chain's JSON-RPC endpoint and the SDK's construction over it: a
    chain answers once it is in ``answering``, and until then refuses both."""

    def __init__(self, urls: dict[str, str]) -> None:
        self.names_by_url = {url: name for name, url in urls.items()}
        self.answering: set[str] = set()

    def rpc(self, rpc_url, method, params, timeout):
        if self.names_by_url[rpc_url] not in self.answering:
            raise ConnectionRefusedError("connection refused")
        return _deployed_chain(rpc_url, method, params, timeout)

    def constructor(self, _policy):
        def construct(chain_name: str) -> object:
            if chain_name not in self.answering:
                raise ConnectionRefusedError("websocket upgrade refused")
            return f"client:{chain_name}"

        return construct

    def seams(self):
        return server.ApiCreditCompositionSeams(
            alkahest_client_constructor=self.constructor, alkahest_json_rpc=self.rpc
        )


def _alkahest_status(status) -> dict:
    (alkahest,) = [item for item in status.settlement if item["mechanism"] == "alkahest.v1"]
    return alkahest


async def test_the_composition_and_the_loop_share_one_probe_over_one_client_map(storefront):
    """The real composition reads readiness from the probe the registered
    ``alkahest-chain-probe`` loop steps, and holds that probe's own client map:
    a chain whose client cannot be built is unreachable, and once a stepped
    probe builds it the composition holds the client and Alkahest is ready."""
    chains = _Chains({"anvil": ANVIL.rpc_url})
    async with _started(_settlement(), probed=False, seams=chains.seams()) as (
        _listings,
        _public,
        admin,
    ):
        await admin.admin_run_lifecycle_cycle("alkahest-chain-probe")
        refused = _alkahest_status(await admin.get_system_status())
        chains.answering.add("anvil")
        await admin.admin_run_lifecycle_cycle("alkahest-chain-probe")
        reached = _alkahest_status(await admin.get_system_status())
        probe = container.resolved_alkahest_chain_probe
        composition = container.resolved_settlement_composition

    assert [blocker["code"] for blocker in refused["blockers"]] == ["alkahest.chain_unreachable"]
    assert reached["ready"] is True
    assert composition.mechanism_resources["clients"] is probe.clients
    assert probe.clients == {"anvil": "client:anvil"}


async def test_startup_does_not_wait_on_a_chain_whose_client_never_finishes_building(
    storefront,
):
    """Spec requirement "A deployment does not wait on a service's
    dependencies": a websocket chain that accepts the connection and never
    upgrades it holds its client's construction for good. Startup constructs no
    client, so the storefront starts and answers its health check, and the
    probe, whose wait on construction the RPC timeout bounds, holds Alkahest
    unready for reachability."""
    never_upgraded = threading.Event()
    constructed_on: list[str] = []

    def constructor(_policy):
        def construct(chain_name: str) -> object:
            constructed_on.append(threading.current_thread().name)
            # Only the probe's own construction thread is held: one anywhere
            # else, as startup's would be, fails at once, so the assertion below
            # names it rather than the test hanging.
            if threading.current_thread().name.startswith("alkahest-client-"):
                never_upgraded.wait()
            raise ConnectionError("websocket closed")

        return construct

    seams = server.ApiCreditCompositionSeams(
        alkahest_client_constructor=constructor, alkahest_json_rpc=_deployed_chain
    )
    try:
        async with _started(
            _settlement(rpc_timeout_seconds=0.2), probed=False, seams=seams
        ) as (_listings, public, admin):
            health = await public.get_health()
            await asyncio.wait_for(
                admin.admin_run_lifecycle_cycle("alkahest-chain-probe"), timeout=5
            )
            status = _alkahest_status(await admin.get_system_status())
    finally:
        never_upgraded.set()

    assert health.checks["database"] == "ok"
    assert constructed_on and all(
        name.startswith("alkahest-client-") for name in constructed_on
    ), constructed_on
    assert status["ready"] is False
    assert [(b["code"], b["kind"]) for b in status["blockers"]] == [
        ("alkahest.chain_unreachable", "reachability")
    ]


async def test_status_reports_a_configured_chain_no_listing_publishes_on(storefront):
    """Status names nothing being published, so a second configured chain that
    does not answer is reported, as servicing a deal accepted on it would need."""
    second = ChainConfig(
        name="base_sepolia",
        rpc_url="http://base.test",
        chain_id=31337,
        alkahest_address_config_path=str(anvil_address_book_path()),
    )
    chains = _Chains({"anvil": ANVIL.rpc_url, "base_sepolia": second.rpc_url})
    chains.answering.add("anvil")
    with patch.dict(storefront_config.CHAINS, {"anvil": ANVIL, "base_sepolia": second}):
        async with _started(_settlement(), seams=chains.seams()) as (_listings, _public, admin):
            status = _alkahest_status(await admin.get_system_status())

    assert [blocker["code"] for blocker in status["blockers"]] == ["alkahest.chain_unreachable"]
    assert status["public_details"]["chain_probe"]["anvil"]["result"] == "reachable"
    assert (
        status["public_details"]["chain_probe"]["base_sepolia"]["result"]
        == "alkahest.chain_unreachable"
    )


async def test_a_restarted_storefront_finds_its_seeded_listing_and_creates_no_second(
    storefront,
):
    """The seed finds the listing its earlier run created in the storefront's
    own database, so a restart neither registers the quota again nor creates a
    second listing."""
    registered = []

    async def register(**request):
        registered.append(request)

    with _replaced(seed=dict(SEED_LISTING)):
        async with _started(_settlement()) as (_listings, _public, admin):
            container.resolved_listing_seed.register_quota = register
            first = await admin.admin_run_lifecycle_cycle("listing-seed")
        async with _started(_settlement()) as (_listings, public, admin):
            container.resolved_listing_seed.register_quota = register
            again = await admin.admin_run_lifecycle_cycle("listing-seed")
            open_listings = await public.list_listings(status="open")

    assert (first["state"], again["state"]) == ("done", "done")
    assert again["listing_id"] == first["listing_id"]
    assert len(registered) == 1
    assert [listing.listing_id for listing in open_listings.listings] == [first["listing_id"]]
