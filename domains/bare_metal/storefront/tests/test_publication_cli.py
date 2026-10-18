"""The publication command's composition boundary.

The command hands the cycle the runtime's one held projection state, loaded
with one poll first, and every configured registry; it fails closed before
constructing a cycle when no projection state exists. It composes the runtime
from the storefront's configuration files, as the server does.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from core_storefront.multi_registry_client import (
    MultiRegistryClient,
    RegistryAuthorityTrust,
)
from market_identity import Eip191Signer, TrustedIdentitySet

from arkhai_bare_metal_storefront.config import IDENTITY_CREDENTIAL_ENV
from arkhai_bare_metal_storefront.domain_runtime import get_market_domain_contract
from arkhai_bare_metal_storefront.publication_cli import run_publication_once
from arkhai_bare_metal_storefront.publication_service import (
    BareMetalRegistryConfiguration,
)
from arkhai_bare_metal_storefront.runtime import (
    BareMetalStorefrontRuntime,
    build_runtime_from_configuration,
)
from arkhai_bare_metal_storefront.site_clients import BareMetalSiteBinding
from arkhai_bare_metal_storefront.sqlite_client import SQLiteClient
from signed_sites import SignedSite, SignedSites
from storefront_configuration import (
    REGISTRY_URL,
    SELLER_CREDENTIAL,
    SITE,
    SITE_ID,
    publishable_configuration,
    write_configuration,
)
from test_publication_cycle import Site, member, pool, projections_over

# Development keys; never used on any public network.
SELLER = Eip191Signer(bytes.fromhex("11" * 32))
REGISTRY = Eip191Signer(bytes.fromhex("55" * 32))

_TRUST = RegistryAuthorityTrust(
    authority="registry.example",
    principals=TrustedIdentitySet(identities=(REGISTRY.identity,)),
)
REGISTRIES = BareMetalRegistryConfiguration(
    authorities={
        "https://registry.example": _TRUST,
        "https://registry-b.example": _TRUST,
    }
)


def _sites() -> dict[str, Site]:
    return {
        site_id: Site(pool("pool-1", member("r1", "pool-1")))
        for site_id in ("site-a", "site-b")
    }


def _runtime(
    tmp_path,
    *,
    sites: dict[str, Site] | None,
    registry_configuration: BareMetalRegistryConfiguration | None = REGISTRIES,
) -> BareMetalStorefrontRuntime:
    domain = get_market_domain_contract()
    composition = MagicMock()
    composition.runtime_clients.return_value = {}
    composition.publication_payload = AsyncMock()
    return BareMetalStorefrontRuntime(
        db=SQLiteClient(str(tmp_path / "storefront.db"), domain=domain),
        domain=domain,
        seller_principal=SELLER.identity,
        admin_principals=TrustedIdentitySet(identities=(SELLER.identity,)),
        storefront_url="https://seller.example",
        marketplace_signer=SELLER,
        settlement_composition=composition,
        site_bindings=tuple(
            BareMetalSiteBinding(
                site_id=site_id,
                service_peer=f"{site_id}-peer",
                authority_url=f"http://{site_id}:8000",
            )
            for site_id in ("site-a", "site-b")
        ),
        site_projections=projections_over(sites) if sites is not None else None,
        registry_configuration=registry_configuration,
        default_max_duration_seconds=3600,
    )


class RecordingCycle:
    def __init__(self, **kwargs: Any) -> None:
        self.kwargs = kwargs
        self.held_when_run: dict[str, Any] | None = None
        constructed.append(self)

    async def run(self) -> dict[str, Any]:
        self.held_when_run = self.kwargs["site_projections"].status()
        return {"actions": [], "counts": {}}


constructed: list[RecordingCycle] = []


def test_the_command_hands_the_cycle_the_held_projections_after_one_poll(tmp_path):
    constructed.clear()
    runtime = _runtime(tmp_path, sites=_sites())

    report = run_publication_once(runtime=runtime, cycle_factory=RecordingCycle)

    assert report == {"actions": [], "counts": {}}
    (cycle,) = constructed
    assert cycle.kwargs["site_projections"] is runtime.site_projections
    assert cycle.kwargs["site_ids"] == ["site-a", "site-b"]
    # The command's own process loaded the state before its cycle ran.
    assert {
        site_id: {family: status.state for family, status in families.items()}
        for site_id, families in cycle.held_when_run.items()
    } == {
        site_id: {"resource_pool": "loaded", "capacity_bucket": "loaded"}
        for site_id in ("site-a", "site-b")
    }
    assert cycle.kwargs["sqlite_client"] is runtime.db
    assert cycle.kwargs["seller_principal"] == SELLER.identity
    assert cycle.kwargs["registry_urls"] == (
        "https://registry.example",
        "https://registry-b.example",
    )
    assert cycle.kwargs["default_max_duration_seconds"] == 3600


def test_the_registry_transport_is_every_configured_registry(tmp_path):
    """The runtime opens and closes the transport per operation, so the command
    owns no transport; it hands over a factory for exactly the configured
    registries, each pinned to its configured authority."""
    constructed.clear()
    run_publication_once(
        runtime=_runtime(tmp_path, sites=_sites()),
        cycle_factory=RecordingCycle,
    )

    client = constructed[0].kwargs["registry_client_factory"]()

    assert isinstance(client, MultiRegistryClient)
    assert client.urls == ["https://registry.example", "https://registry-b.example"]


def test_the_command_fails_closed_without_held_projections(tmp_path):
    constructed.clear()

    with pytest.raises(RuntimeError, match="site projection state is unavailable"):
        run_publication_once(
            runtime=_runtime(tmp_path, sites=None),
            cycle_factory=RecordingCycle,
        )

    assert constructed == []


def test_publication_needs_a_configured_registry(tmp_path):
    constructed.clear()

    with pytest.raises(RuntimeError, match="no registry is configured"):
        run_publication_once(
            runtime=_runtime(tmp_path, sites=_sites(), registry_configuration=None),
            cycle_factory=RecordingCycle,
        )

    assert constructed == []


def test_the_command_composes_the_storefront_from_its_configuration_files(
    monkeypatch, tmp_path
):
    constructed.clear()
    write_configuration(
        monkeypatch, tmp_path, publishable_configuration(tmp_path / "storefront.db")
    )
    monkeypatch.setenv(IDENTITY_CREDENTIAL_ENV, SELLER_CREDENTIAL)
    # Composed as the command composes it, with only the site's transport
    # replaced, so its first poll reaches the site double.
    runtime = build_runtime_from_configuration(
        site_clients=SignedSites({"site-a.test": SignedSite(SITE)}).factories()
    )

    run_publication_once(runtime=runtime, cycle_factory=RecordingCycle)

    (cycle,) = constructed
    assert cycle.kwargs["site_ids"] == [SITE_ID]
    assert cycle.held_when_run[SITE_ID]["resource_pool"].state == "loaded"
    assert cycle.kwargs["registry_urls"] == (REGISTRY_URL,)
    assert cycle.kwargs["storefront_url"] == "http://seller:8000"
