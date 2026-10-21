"""The release conditions an API-credit listing advertises for Alkahest.

The real app and lifespan compose the storefront from configuration: its signer
from a development credential supplied as the Secret boundary supplies it, its
settlement composition, wallet, and chains, and the listing service the route
reaches. Three seams stand in for what lies beyond the storefront: the quota
site's capacity runtime, which the listing service resolves through
``build_capacity_runtime``; the startup tasks, which preflight the credits
service and start the timer loops; and the chain probe's JSON-RPC transport,
the boundary to the chain, which answers as a deployed chain does. The anvil
chain's address book is the development chain's. Every address and key here is
a deterministic development value, never used on a public network.
"""

from __future__ import annotations

import base64
from contextlib import asynccontextmanager, contextmanager
from copy import deepcopy
from unittest.mock import patch

import httpx
import pytest
from market_alkahest import AlkahestChainProbe, ProbedChain, ReleaseModelError
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
SELLER_WALLET = "0x" + "33" * 20
# A deterministic development key; never used on a public network.
SELLER_WALLET_KEY = "0x" + "55" * 32
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
    probe_for = server._build_alkahest_chain_probe

    def probe_over_the_deployed_chain(section, clients):
        built = probe_for(section, clients)
        return AlkahestChainProbe(
            [ProbedChain.from_config(name, chain) for name, chain in storefront_config.CHAINS.items()],
            clients=built.clients,
            json_rpc=_deployed_chain,
        )

    monkeypatch.setattr(server, "_build_alkahest_chain_probe", probe_over_the_deployed_chain)
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


def _app():
    return server.build_api_credits_storefront_app(
        registry=server.build_api_credits_storefront_registry(
            domain=get_market_domain_contract()
        )
    )


@asynccontextmanager
async def _started(settlement: dict):
    """The started storefront under ``settlement``, its chain probed once."""
    app = _app()
    with _replaced(settlement=settlement):
        async with app.router.lifespan_context(app):
            probe = container.resolved_alkahest_chain_probe
            if probe is not None:
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
    escrow and derives no condition while Alkahest is unready."""
    section, _blocker = UNSETTLEABLE[case]
    async with _started(_settlement(**section)):
        composition = container.resolved_settlement_composition
        with pytest.raises(RuntimeError, match="no enabled settlement mechanism is ready"):
            await composition.publication_artifacts(
                {
                    "claimant_principal": SELLER_SIGNER.identity,
                    "resource_id": "svc-quota",
                    "service": "Acme Inference",
                },
                [dict(ALKAHEST_CLAUSE)],
            )
        readiness = await composition.readiness()
        assert composition.release_conditions([dict(ESCROW)], readiness=readiness) == []
