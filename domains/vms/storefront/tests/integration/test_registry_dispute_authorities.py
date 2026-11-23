"""A VM storefront reads again, at publication, a registry it could not read.

The real ``VmSettlementComposition`` runs over the publication harness, and its
dispute policy reads its registries' descriptors as the storefront's startup
does, through the registry client factory startup hands it. The registries are
the harness's double of that client, whose descriptor reads fail until a test
gives a registry its descriptor. Publication and settlement status are
driven through the served storefront and its typed client.

Every account, key and address here is a deterministic development value; none
may be used on a public network.
"""

from __future__ import annotations

import contextlib
import json
from collections.abc import AsyncIterator, Sequence
from pathlib import Path
from unittest.mock import patch

import pytest
from market_core import RegistryDescriptor
from market_deal_lifecycle.configuration import DisputeConfig, DisputeEntry
from market_storefront_kit.dispute_configuration import RegistryDisputePolicy

import market_storefront.container as container
from market_storefront.domain_runtime import build_vm_storefront_domain
from market_storefront.services.publication_service import _make_registry_client
from market_storefront.settlement_composition import (
    VmSettlementComposition,
    build_storefront_settlement_registry,
)
from market_storefront.utils import config as storefront_config
from tests._settings_overrides import replaced_setting
from tests.publication_app import (
    REGISTRY_SIGNER,
    REGISTRY_URLS,
    SELLER_WALLET,
    SETTLEMENT,
    PublicationApp,
    pool,
    publication_app,
)
from tests.recurring_world import DISPUTE_ENTRY, MECHANISM, PAYMENTS_SERVICE, payment_clause

pytestmark = pytest.mark.asyncio

_ROOT = {
    "schema_version": 1,
    "priority": ["alkahest.v1", MECHANISM],
    "alkahest": {**SETTLEMENT["alkahest"], "release_models": ["recipient"]},
    "arkhai_payments": {
        "enabled": True,
        "service_url": "http://127.0.0.1:9",
        "service_identity": PAYMENTS_SERVICE.identity.model_dump(mode="json"),
        "fee_bps": 250,
        "development_auth": True,
    },
}
_POOL = "bounded"


def _descriptor(url: str) -> RegistryDescriptor:
    """``url``'s descriptor, as its client returns it once verified,
    recommending the payments dispute authority."""
    return RegistryDescriptor.model_validate({
        "access": {"posture": "public"},
        "authority": {
            "name": f"registry-{REGISTRY_URLS.index(url)}",
            "principals": [REGISTRY_SIGNER.identity.model_dump(mode="json")],
        },
        "baseUrl": url,
        "displayName": "Test Registry",
        "operatorIdentity": "Test Operator",
        "schema": {"id": "compute.market", "version": "1"},
        "recommendedDisputeAuthorities": [DISPUTE_ENTRY.model_dump(mode="json")],
    })


def _token_cache(path: Path) -> str:
    """The token cache payments readiness reads the development chain's asset from."""
    tokens = path / "cache" / "arkhai" / "tokens"
    tokens.mkdir(parents=True, exist_ok=True)
    token = "0x" + "22" * 20
    (tokens / "31337.json").write_text(json.dumps({
        token: {"symbol": "USDC", "contract_address": token, "decimals": 6, "chain_id": 31337},
    }))
    return str(path / "cache")


@contextlib.asynccontextmanager
async def _storefront(
    tmp_path: Path, *, local_entries: Sequence[DisputeEntry] = ()
) -> AsyncIterator[PublicationApp]:
    """A payments storefront using its registries' recommendations, whose
    startup read has run while every registry's descriptor read fails.

    ``local_entries`` are its ``[[Dispute]]`` entries; with none, it relies on
    registry recommendations alone.
    """

    def composition(_fulfillment) -> VmSettlementComposition:
        registry = build_storefront_settlement_registry()
        return VmSettlementComposition(
            domain=build_vm_storefront_domain(),
            repository=None,
            runtime=None,
            coordinator=None,
            worker=None,
            local_principal=PAYMENTS_SERVICE.identity,
            mechanism_clients={},
            evidence_clients={},
            configuration_registry=registry,
            settlement_config=registry.resolve(_ROOT, role="seller"),
            mechanism_resources={
                "wallet": SELLER_WALLET,
                "chains": dict(storefront_config.CHAINS),
                "clients": {"anvil": object()},
            },
            disputes=RegistryDisputePolicy(DisputeConfig(
                entries=list(local_entries), use_registry_dispute_authorities=True,
            )),
            delivery_deadline_for_pool=lambda _site, _pool: 1200,
        )

    with patch.dict("os.environ", {"XDG_CACHE_HOME": _token_cache(tmp_path)}), \
            replaced_setting("pricing.defaults", {}):
        async with publication_app(
            tmp_path,
            settlement_configuration=_ROOT,
            settlement_composition_factory=composition,
        ) as world:
            # Installed as the composition root installs it, where status and
            # the publication cycle read it.
            previous = container.resolved_settlement_composition
            container.resolved_settlement_composition = world.composition
            try:
                await world.composition.disputes.refresh(_make_registry_client)
                world.set_settlement_clauses([payment_clause()])
                world.pools.append(pool(_POOL, backing="backed", capacity_bounds={"vm": {
                    "max_duration_seconds": 7200,
                    "available_until_utc": "2035-01-01T00:00:00Z",
                }}))
                yield world
            finally:
                container.resolved_settlement_composition = previous


async def _publish(world: PublicationApp) -> dict:
    await world.client.admin_run_lifecycle_cycle("site-projections")
    return await world.client.admin_run_lifecycle_cycle("publication")


async def _payment_options(world: PublicationApp) -> list[dict]:
    page = await world.client.list_listings(status="open", limit=200)
    return [
        option
        for listing in page.listings
        for option in (listing.extra.get("settlement_options") or [])
        if option["settlement"]["schema"] == MECHANISM
    ]


async def _payments_status(world: PublicationApp) -> dict:
    status = await world.client.get_system_status()
    (payments,) = [item for item in status.settlement if item["mechanism"] == MECHANISM]
    return payments


async def test_a_storefront_that_started_before_its_registry_publishes_once_it_answers(tmp_path):
    """Spec scenarios "A storefront starts before its registry" and "A registry
    is still unread"."""
    async with _storefront(tmp_path) as world:
        await _publish(world)
        unread_listings = (await world.client.list_listings(status="open", limit=200)).listings
        unread_options = await _payment_options(world)
        unread_status = await _payments_status(world)
        startup_reads = list(world.registries.descriptor_reads)

        for url in REGISTRY_URLS:
            world.registries.descriptors[url] = _descriptor(url)
        await _publish(world)
        read_options = await _payment_options(world)
        read_status = await _payments_status(world)
        await _publish(world)

    # Startup read both registries and could read neither, and the first cycle
    # read both again: the pool's one clause, a payments clause, composes no
    # option, so no listing opens.
    assert startup_reads == [list(REGISTRY_URLS), list(REGISTRY_URLS)]
    assert unread_listings == [] and unread_options == []
    assert unread_status["ready"] is True and unread_status["blockers"] == []
    assert [entry["registry"] for entry in
            unread_status["public_details"]["dispute_authorities_unread"]] == list(REGISTRY_URLS)
    # The first cycle after the registries answer reads them and publishes the
    # option their authority allows, with no restart.
    assert len(read_options) == 1
    assert read_options[0]["lifecycle"]["adjudication"]["dispute"]["account"] == DISPUTE_ENTRY.account
    assert read_status["ready"] is True
    assert "dispute_authorities_unread" not in read_status["public_details"]
    # "A registry was read": once read, a registry is not read again.
    assert world.registries.descriptor_reads == [*startup_reads, list(REGISTRY_URLS)]


async def test_a_storefront_with_local_authorities_publishes_while_its_registry_is_unread(
    tmp_path,
):
    """Spec scenario "A storefront with local authorities whose registry is
    unread"."""
    async with _storefront(tmp_path, local_entries=[DISPUTE_ENTRY]) as world:
        await _publish(world)
        options = await _payment_options(world)
        payments = await _payments_status(world)

    assert len(options) == 1
    assert payments["ready"] is True and payments["blockers"] == []
    assert [entry["registry"] for entry in
            payments["public_details"]["dispute_authorities_unread"]] == list(REGISTRY_URLS)
