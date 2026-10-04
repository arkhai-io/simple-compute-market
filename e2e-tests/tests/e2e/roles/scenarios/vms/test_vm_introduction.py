"""Settlement by introduction on the VM lane, from discovery to the seller's inbox.

The site's operator declares two VM pools at an asking rate: one capacity-backed
and one unbacked. A storefront pool override offers the unbacked pool by
introduction alone. One rate-bounded buyer query returns both pools' listings,
so unbacked supply is comparable on price with backed supply, and leaves out the
lane's default listing, which publishes no rate. The buyer then negotiates the
unbacked listing's introduction and reveals it through the production ``market``
CLI, which delivers the seller's contact to the buyer's own file sink; the
storefront delivers the buyer's contact to the seller by SMTP, read back from
the lane's Mailpit.

The storefront's timer loops are held for the module and publication is stepped,
so the cycle the scenario observes is the one it ran.
"""

from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
import pytest
from e2e_harness.settings import settings
from market_identity import IdentityScheme
from market_pool_overrides import SyncPoolOverrideClient
from registry_client.query import compile_resource_query
from vm_provisioning_operator import PoolCreate, PoolUpdate

from tests.e2e.roles.buyer_cli import _toml_quote, create_profiled_buyer_cli
from tests.e2e.roles.helpers.domain_deal import require_state
from tests.e2e.roles.scenarios.vms.conftest import (
    advance_storefront,
    capacity_site_id,
    pause_storefront,
)
from tests.e2e.roles.scenarios.vms.host_registry import (
    declare_e2e_capacity,
    provision_e2e_executor,
    refresh_storefront_projections,
)

pytestmark = [
    pytest.mark.e2e_vm_introduction,
    pytest.mark.usefixtures("held_loops"),
]

VM = "vm"
CONTACT_MECHANISM = "contact-exchange.v1"
PUBLICATION = "publication"
REGION = "us-west"
GPU_MODEL = "H100"
SHAPE = {"gpu": {"count": 1, "model": GPU_MODEL}}
RATE_QUERY = "asking_rate_asset=usd asking_rate_period=hour"
BACKED_RATE = "3.00"
UNBACKED_RATE = "2.50"
RATE_BOUND = "3.00"
# Development fixtures on a reserved domain, never to be used on a public network.
BUYER_CONTACT_EMAIL = "buyer@vm-e2e.invalid"
SELLER_CONTACT_EMAIL = "bob-sales@seller.invalid"
MAIL_DEADLINE_SECONDS = 30.0


@dataclass
class IntroductionState:
    run: str = ""
    backed_pool: str = ""
    unbacked_pool: str = ""
    backed_listing: str = ""
    unbacked_listing: str = ""
    disclosure: dict[str, Any] | None = None
    run_id: str = ""
    obligation_ref: str = ""
    revealed: bool = False


@pytest.fixture(scope="module")
def state() -> IntroductionState:
    return IntroductionState(run=uuid.uuid4().hex[:8])


@pytest.fixture(scope="module")
def held_loops(storefront_admin_client):
    """Hold the storefront's timer loops for this module and resume afterwards."""
    assert pause_storefront(storefront_admin_client)
    yield
    storefront_admin_client.admin_resume_lifecycle_loops()


@pytest.fixture(scope="module")
def mailpit_url() -> str:
    url = str(settings.get("MAILPIT.API_URL", "") or "").rstrip("/")
    if not url:
        pytest.fail("MAILPIT.API_URL is not configured for this lane")
    return url


@pytest.fixture(scope="module")
def introduction_buyer(buyer_cli_binary: Path, tmp_path_factory):
    """A VM buyer whose own sink is a file this scenario reads back."""
    credential = str(getattr(settings.BUYER, "MARKETPLACE_CREDENTIAL", None) or "")
    if not credential:
        pytest.fail("BUYER.MARKETPLACE_CREDENTIAL is not configured for this lane")
    base = tmp_path_factory.mktemp("vm_introduction_buyer")
    delivered = base / "delivered.jsonl"
    registry_url = str(settings.REGISTRY.API_URL).rstrip("/")
    buyer = create_profiled_buyer_cli(
        binary=buyer_cli_binary,
        base=base,
        domain_identity="vms.compute",
        marketplace_scheme=IdentityScheme.EIP191,
        marketplace_credential=credential,
        registries=(registry_url,),
        registry_authorities={
            registry_url: {
                "authority": str(settings.REGISTRY.get("authority_id", "") or ""),
                "identities": [
                    {
                        "scheme": "eip191",
                        "identifier": str(settings.REGISTRY.get("identifier", "") or ""),
                    }
                ],
            }
        },
        toml_sections=(
            "[Delivery]",
            'enabled = ["file"]',
            "",
            "[Delivery.file]",
            f"path = {_toml_quote(str(delivered))}",
            "",
        ),
        credential_variable="ARKHAI_E2E_BUYER_MARKETPLACE_CREDENTIAL",
    )
    return buyer, delivered


def _rate(amount: str) -> dict[str, Any]:
    return {"shape": SHAPE, "amount": amount, "asset": "usd", "period": "hour"}


def _found(registry, query: str) -> set[str]:
    """Listings a buyer finds, compiled against the registry's own specification."""
    compiled = compile_resource_query(
        query,
        filter_spec=registry.get_filter_spec(),
        registry_url=str(settings.REGISTRY.API_URL),
    )
    response = registry.list_listings(
        offering_mode=VM, etag=compiled.etag, **compiled.as_params()
    )
    return {listing.id for listing in response.listings}


def _pool_listing(storefront_admin_client, pool_id: str, cycle: dict[str, Any]) -> str:
    """The one open listing published from ``pool_id``.

    A cycle's publish action names its derivation key rather than its pool, so
    the listing is found by the pool its resource records; the cycle is reported
    when it is not there, so a failure says what publication did instead.
    """
    page = storefront_admin_client.list_listings(status="open", limit=200)
    found = []
    for listing in page.listings:
        resource = listing.listing_resource
        if isinstance(resource, str):
            resource = json.loads(resource)
        if (resource or {}).get("pool_id") == pool_id:
            found.append(str(listing.listing_id))
    assert len(found) == 1, f"listings for {pool_id}: {found}; cycle: {cycle}"
    return found[0]


def _json_line(text: str) -> dict[str, Any]:
    """The JSON object a command printed last."""
    for line in reversed(text.strip().splitlines()):
        if line.startswith("{"):
            return json.loads(line)
    raise AssertionError(f"no JSON object in output: {text[-2000:]}")


class TestStage00_DisclosureBeforeCommitment:
    def test_00_readiness_discloses_the_retention_window(
        self, storefront_admin_client, state: IntroductionState
    ):
        """A buyer reads the retention window before handing over a contact."""
        health = storefront_admin_client.get_health()
        disclosure = health.disclosures.get("introduction_retention")
        assert disclosure and disclosure["scope"] == "introduction_record", health
        state.disclosure = disclosure


class TestStage01_BackedAndUnbackedSupply:
    def test_01_both_pools_publish_at_an_asking_rate(
        self,
        provisioning_client,
        site_capacity_admin_client,
        storefront_admin_client,
        state: IntroductionState,
    ):
        state.backed_pool = f"vm-intro-backed-{state.run}"
        state.unbacked_pool = f"vm-intro-unbacked-{state.run}"
        # Backed supply: a pool, an executor host, and its capacity declaration.
        provision_e2e_executor(
            provisioning_client,
            site_capacity_admin_client,
            host=f"{state.backed_pool}-host",
            resource_id=f"{state.backed_pool}-res",
            attributes={"gpu_model": GPU_MODEL, "region": REGION},
            pool_id=state.backed_pool,
            sellable_units=1,
            listing_mode="fungible",
            listing_shapes={VM: [SHAPE]},
            region=REGION,
        )
        backed = provisioning_client.get_pool(state.backed_pool)
        provisioning_client.patch_pool(state.backed_pool, _with_rate(backed, BACKED_RATE))
        # Unbacked supply: declared and advertised, never delivered, so no
        # executor stands behind it.
        provisioning_client.create_pool(
            PoolCreate(
                id=state.unbacked_pool,
                label=state.unbacked_pool,
                provider="ansible",
                policy_tags={
                    "listing_mode": "fungible",
                    "deliverable_modes": [],
                    "advertisable_modes": [VM],
                    "capacity_backing": "unbacked",
                    "region": REGION,
                    "listing_shapes": {VM: [SHAPE]},
                    "asking_rates": {VM: [_rate(UNBACKED_RATE)]},
                },
                provider_config=dict(backed.provider_config or {}),
            )
        )
        declare_e2e_capacity(
            site_capacity_admin_client,
            resource_id=f"{state.unbacked_pool}-res",
            host_id=f"{state.unbacked_pool}-declared",
            attributes={"gpu_model": GPU_MODEL, "region": REGION},
            pool_id=state.unbacked_pool,
            sellable_units=1,
        )
        # The storefront's pollers are held, so it pulls the site's new pools
        # now; an override is checked against the pools it has pulled.
        refresh_storefront_projections(storefront_admin_client)
        # Only the unbacked pool offers introduction; the lane's configured
        # clauses still govern every other listing.
        SyncPoolOverrideClient(storefront_admin_client).put_pool_override(
            {
                "site_id": capacity_site_id(),
                "pool_id": state.unbacked_pool,
                "offering_mode": VM,
                "settlements": [
                    {
                        "mechanism": CONTACT_MECHANISM,
                        "asset": "introduction",
                        "mechanism_input": {"profile": "default"},
                    }
                ],
            }
        )

        cycle = advance_storefront(storefront_admin_client, PUBLICATION)

        state.backed_listing = _pool_listing(storefront_admin_client, state.backed_pool, cycle)
        state.unbacked_listing = _pool_listing(
            storefront_admin_client, state.unbacked_pool, cycle
        )

    def test_02_one_rate_bounded_query_returns_both(
        self, registry_client, state: IntroductionState
    ):
        require_state(state, "unbacked_listing", "backed_listing")
        found = _found(registry_client, f"asking_rate<={RATE_BOUND} {RATE_QUERY}")
        assert {state.backed_listing, state.unbacked_listing} <= found, found
        # A bound below the unbacked rate excludes it and keeps nothing above it.
        cheaper = _found(registry_client, f"asking_rate<=2.49 {RATE_QUERY}")
        assert state.unbacked_listing not in cheaper and state.backed_listing not in cheaper
        # Every listing a rate-bounded query returns publishes a rate.
        for listing_id in found:
            listing = registry_client.get_listing(listing_id)
            assert listing.listing_resource.get("asking_rate"), listing_id

    def test_03_the_unbacked_listing_offers_only_an_introduction(
        self, registry_client, state: IntroductionState
    ):
        require_state(state, "unbacked_listing")
        listing = registry_client.get_listing(state.unbacked_listing)
        mechanisms = {dict(option)["mechanism"] for option in listing.settlement_options}
        assert mechanisms == {CONTACT_MECHANISM}, listing.settlement_options


class TestStage02_Reveal:
    def test_04_the_buyer_cli_negotiates_and_reveals(
        self, introduction_buyer, registry_client, state: IntroductionState
    ):
        require_state(state, "unbacked_listing")
        buyer, delivered = introduction_buyer
        (option,) = [
            dict(option)
            for option in registry_client.get_listing(state.unbacked_listing).settlement_options
        ]

        negotiated = buyer.run(
            [
                "request-introduction",
                state.unbacked_listing,
                "--option-id",
                option["option_id"],
            ],
            timeout=120.0,
        )
        assert negotiated.returncode == 0, negotiated.stdout()[-2000:]
        accepted = _json_line(negotiated.stdout())
        assert accepted.get("status") == "agreed", accepted
        state.run_id = accepted["run_id"]
        state.obligation_ref = accepted["obligation_ref"]

        revealed = buyer.run(
            [
                "settlement",
                "contact",
                "introduce",
                "--run-id",
                state.run_id,
                "--contact",
                f"email={BUYER_CONTACT_EMAIL}",
            ],
            timeout=120.0,
        )
        assert revealed.returncode == 0, revealed.stdout()[-2000:]
        projection = _json_line(revealed.stdout())
        assert projection["revealed"] is True
        assert projection["counterparty_contact"] == {"email": SELLER_CONTACT_EMAIL}
        assert projection["retention"] == state.disclosure
        # The buyer's own sink holds the seller's contact.
        lines = [json.loads(line) for line in delivered.read_text().splitlines() if line]
        assert any(SELLER_CONTACT_EMAIL in json.dumps(line) for line in lines), lines
        state.revealed = True


class TestStage03_SellerDelivery:
    def test_05_the_seller_is_mailed_the_buyers_contact(
        self, mailpit_url: str, state: IntroductionState
    ):
        """Seller-side delivery runs off the request path, so it is awaited, bounded."""
        require_state(state, "revealed")
        deadline = time.monotonic() + MAIL_DEADLINE_SECONDS
        while True:
            listing = httpx.get(f"{mailpit_url}/api/v1/messages", timeout=10).json()
            matching = [
                message
                for message in listing.get("messages") or []
                if state.obligation_ref in str(message.get("Subject", ""))
            ]
            if matching:
                break
            assert time.monotonic() < deadline, listing
            time.sleep(0.5)
        (message,) = matching
        recipients = {entry.get("Address") for entry in message.get("To") or []}
        assert recipients == {SELLER_CONTACT_EMAIL}, message
        body = httpx.get(f"{mailpit_url}/api/v1/message/{message['ID']}", timeout=10).json()
        assert BUYER_CONTACT_EMAIL in str(body.get("Text", "")), body


def _with_rate(pool: Any, amount: str) -> Any:

    tags = dict(pool.policy_tags or {})
    tags["asking_rates"] = {VM: [_rate(amount)]}
    return PoolUpdate(policy_tags=tags)
