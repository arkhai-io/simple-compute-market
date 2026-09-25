"""The publication command's composition boundary.

The command hands the cycle the exact per-site clients the runtime composed and
the one configured registry; it fails closed before constructing a cycle when
no trusted site clients exist.
"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from core_storefront.multi_registry_client import MultiRegistryClient
from market_identity import Eip191Signer, TrustedIdentitySet

from arkhai_bare_metal_storefront.domain_runtime import get_market_domain_contract
from arkhai_bare_metal_storefront.publication_cli import run_publication_once
from arkhai_bare_metal_storefront.runtime import BareMetalStorefrontRuntime
from arkhai_bare_metal_storefront.site_clients import BareMetalSiteBinding
from arkhai_bare_metal_storefront.sqlite_client import SQLiteClient

# Development keys; never used on any public network.
SELLER = Eip191Signer(bytes.fromhex("11" * 32))
AUTHORITY = Eip191Signer(bytes.fromhex("44" * 32))
REGISTRY = Eip191Signer(bytes.fromhex("55" * 32))

ENVIRON = {
    "BARE_METAL_STOREFRONT_REGISTRY_URL": "https://registry.example",
    "BARE_METAL_STOREFRONT_REGISTRY_AUTHORITY": "registry.example",
    "BARE_METAL_STOREFRONT_REGISTRY_PRINCIPALS": json.dumps(
        [REGISTRY.identity.model_dump(mode="json")]
    ),
    "BARE_METAL_STOREFRONT_PUBLICATION_CLAUSES": "[]",
    "BARE_METAL_STOREFRONT_FUNDING_DEADLINES": "{}",
    "BARE_METAL_STOREFRONT_DEMANDS": "[]",
    "BARE_METAL_STOREFRONT_OPTION_EXPIRES_AT": "2026-08-17T04:00:00Z",
    "BARE_METAL_STOREFRONT_FULFILLMENT_DEADLINE": "2026-08-17T03:30:00Z",
    "BARE_METAL_STOREFRONT_MAX_DURATION_SECONDS": "3600",
}


def _runtime(tmp_path, *, capacity_client: Any) -> BareMetalStorefrontRuntime:
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
                authority_principal=AUTHORITY.identity,
                authority_url=f"http://{site_id}:8000",
            )
            for site_id in ("site-a", "site-b")
        ),
        capacity_client=capacity_client,
    )


class RecordingCycle:
    def __init__(self, **kwargs: Any) -> None:
        self.kwargs = kwargs
        constructed.append(self)

    async def run(self) -> dict[str, Any]:
        return {"actions": [], "counts": {}}


constructed: list[RecordingCycle] = []


def test_the_command_hands_the_cycle_each_sites_own_client(tmp_path):
    constructed.clear()
    per_site = {"site-a": object(), "site-b": object()}
    capacity_client = MagicMock()
    capacity_client.site.side_effect = per_site.__getitem__
    runtime = _runtime(tmp_path, capacity_client=capacity_client)

    report = run_publication_once(
        runtime=runtime, environ=ENVIRON, cycle_factory=RecordingCycle
    )

    assert report == {"actions": [], "counts": {}}
    (cycle,) = constructed
    site_clients = cycle.kwargs["site_clients"]
    assert set(site_clients) == set(per_site)
    for site_id, client in per_site.items():
        assert site_clients[site_id] is client
    assert cycle.kwargs["sqlite_client"] is runtime.db
    assert cycle.kwargs["seller_principal"] == SELLER.identity
    assert cycle.kwargs["registry_url"] == "https://registry.example"
    # The aggregate client's snapshot swallows an unreachable site; publication
    # never reads it.
    capacity_client.snapshot.assert_not_called()


def test_the_registry_transport_is_the_one_configured_registry(tmp_path):
    """The runtime opens and closes the transport per operation, so the command
    owns no transport; it hands over a factory for exactly the configured
    registry, pinned to its configured authority."""
    constructed.clear()
    capacity_client = MagicMock()
    run_publication_once(
        runtime=_runtime(tmp_path, capacity_client=capacity_client),
        environ=ENVIRON,
        cycle_factory=RecordingCycle,
    )

    client = constructed[0].kwargs["registry_client_factory"]()

    assert isinstance(client, MultiRegistryClient)
    assert client.urls == ["https://registry.example"]


def test_the_command_fails_closed_without_trusted_site_clients(tmp_path):
    constructed.clear()

    with pytest.raises(RuntimeError, match="trusted site capacity clients"):
        run_publication_once(
            runtime=_runtime(tmp_path, capacity_client=None),
            environ=ENVIRON,
            cycle_factory=RecordingCycle,
        )

    assert constructed == []


def test_publication_needs_every_registry_setting(tmp_path):
    constructed.clear()
    environ = dict(ENVIRON)
    del environ["BARE_METAL_STOREFRONT_REGISTRY_AUTHORITY"]

    with pytest.raises(RuntimeError, match="REGISTRY_AUTHORITY"):
        run_publication_once(
            runtime=_runtime(tmp_path, capacity_client=MagicMock()),
            environ=environ,
            cycle_factory=RecordingCycle,
        )

    assert constructed == []
