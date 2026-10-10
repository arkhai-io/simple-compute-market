"""Typed clients for the bare-metal end-to-end lane.

Every client reaches its service the way its real caller does: the storefront's
administrator steps publication, the site's administrator declares pools, the
storefront's own principal declares capacity (the site binds its seller role to
that principal), and a buyer reads the registry. Each response is verified
against the principal the lane pins for that service.

The lane provides every setting under ``bare_metal_lane`` in
``config/config-docker.yml``, so a missing one fails the scenario rather than
skipping it: a skip is how bare-metal publication once went unexercised.

The mock-provisioned deal (``test_bare_metal_mock_deal.py``) runs the canonical
compute deal's shared stages, which request the fixtures every compute domain's
conftest provides under one set of names (see ``helpers/compute_deal_stages.py``),
and bare metal's ``deal_driver``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

import pytest
from arkhai_bare_metal_buyer.fulfillment import BareMetalFulfillmentTransport
from market_identity import Identity, TrustedIdentitySet, create_signer
from market_site_client import SiteCapacityAdminClient
from registry_client import SyncRegistryClient
from storefront_client import SyncStorefrontClient
from compute_provisioning_client import SyncComputeProvisioningClient
from market_resource_pools_client import SyncResourcePoolClient

from e2e_harness.provisioning_test_client import ProvisioningTestClient
from e2e_harness.settings import settings
from tests.e2e.roles.helpers.compute_deal import SiteCapacity, convergence_paused
from tests.e2e.roles.helpers.compute_deal_stages import ComputeDealState
from tests.e2e.roles.scenarios.bare_metal.compute_deal_driver import (
    BareMetalComputeDealDriver,
)


def lane_setting(name: str) -> str:
    """One bare-metal lane setting, failing the scenario when it is absent."""
    value = settings.get("BARE_METAL_LANE", {}).get(name)
    if not value:
        pytest.fail(f"bare-metal lane setting BARE_METAL_LANE.{name} is not configured")
    return str(value)


def _signer(role: str) -> Any:
    return create_signer(lane_setting(f"{role}_scheme"), lane_setting(f"{role}_credential"))


def _pinned(role: str) -> TrustedIdentitySet:
    return TrustedIdentitySet(
        identities=(
            Identity(
                scheme=lane_setting(f"{role}_scheme"),
                identifier=lane_setting(f"{role}_identifier"),
            ),
        )
    )


@pytest.fixture(scope="module")
def bare_metal_storefront_admin():
    """The storefront's administrator: publication steps and system reads."""
    client = SyncStorefrontClient(
        lane_setting("storefront_url"),
        _signer("storefront_admin"),
        caller_role="admin",
        expected_publishers=_pinned("storefront"),
    )
    yield client
    client.close()


@pytest.fixture(scope="module")
def bare_metal_storefront_public():
    """Unauthenticated reads a buyer makes of the storefront."""
    client = SyncStorefrontClient(lane_setting("storefront_url"))
    yield client
    client.close()


@pytest.fixture(scope="module")
def bare_metal_registry():
    """Buyer-role registry reads: discovery, as a buyer performs it."""
    client = SyncRegistryClient(
        lane_setting("registry_url"),
        signer=_signer("buyer"),
        caller_role="buyer",
        expected_registries=_pinned("registry"),
        registry_authority=lane_setting("registry_authority_id"),
    )
    yield client
    client.close()


@pytest.fixture(scope="module")
def bare_metal_site_operator():
    """The site's administrator, which declares and changes resource pools.

    Pool administration is the resource-pool authority's typed client over the
    provisioning service's family client, signed as that service's admin.
    """
    client = SyncComputeProvisioningClient(
        lane_setting("site_url"),
        _signer("site_admin"),
        "admin",
        _pinned("site_authority"),
    )
    yield SyncResourcePoolClient(client)
    client.close()


@pytest.fixture(scope="module")
def bare_metal_site_capacity() -> SiteCapacityAdminClient:
    """Capacity declarations, signed as the storefront the site serves.

    Declaring sellable capacity is a seller's act, and the site binds its
    seller role to the one storefront principal it is configured to serve.
    """
    return SiteCapacityAdminClient(
        lane_setting("site_url"),
        create_signer(
            lane_setting("storefront_scheme"), lane_setting("storefront_credential")
        ),
        _pinned("site_authority"),
    )


# ---------------------------------------------------------------------------
# The canonical compute deal's fixtures, under the names its shared stages use
# ---------------------------------------------------------------------------


@dataclass
class BareMetalDealState(ComputeDealState):
    """Bare metal's observations layered over the canonical compute deal's state.

    The fields bare metal's own stages hand each other: its publication preview
    and, for the second deal on the freed machine, the reopened listing, the
    second negotiation and escrow, and its two teardown responses.
    """

    domain_identity: str = "bare_metal.v1"
    _publication_previewed: bool = False
    _listing_reopened: bool = False
    second_negotiation_id: Optional[str] = None
    #: The second deal's escrow deadline, pinned at its negotiation.
    _second_escrow_expiration_unix: Optional[int] = None
    second_fulfillment_id: Optional[str] = None
    _second_deal_active: bool = False
    second_teardown: Optional[dict[str, Any]] = None


@pytest.fixture(scope="module")
def deal_state() -> BareMetalDealState:
    return BareMetalDealState()


@pytest.fixture(scope="module")
def storefront_admin_client(bare_metal_storefront_admin):
    return bare_metal_storefront_admin


@pytest.fixture(scope="module")
def storefront_client():
    """Buyer-role storefront client: the buyer settling its own deal."""
    client = SyncStorefrontClient(
        lane_setting("storefront_url"),
        _signer("buyer"),
        caller_role="buyer",
        expected_publishers=_pinned("storefront"),
    )
    yield client
    client.close()


@pytest.fixture(scope="module")
def registry_client(bare_metal_registry):
    return bare_metal_registry


@pytest.fixture(scope="module")
def provisioning_client():
    """The site's family client, signed as its administrator."""
    client = SyncComputeProvisioningClient(
        lane_setting("site_url"),
        _signer("site_admin"),
        "admin",
        _pinned("site_authority"),
    )
    yield client
    client.close()


@pytest.fixture(scope="module")
def provisioning_test_client():
    """The site's ``/test/*`` controls, present in its mock profile."""
    with ProvisioningTestClient(
        lane_setting("site_url"),
        signer=_signer("site_admin"),
        expected_authorities=_pinned("site_authority"),
        timeout=20.0,
    ) as client:
        yield client


@pytest.fixture(scope="module")
def site_capacity() -> SiteCapacity:
    """The site's capacity reads, release, and lease truncation, as its admin."""
    return SiteCapacity(
        lane_setting("site_url"), _signer("site_admin"), _pinned("site_authority")
    )


@pytest.fixture(scope="module")
def buyer_config() -> dict[str, str]:
    """The buyer's wallet, for the on-chain escrow; its key is its signer's."""
    return {
        "private_key": lane_setting("buyer_credential"),
        "wallet_address": lane_setting("buyer_wallet_address"),
        "rpc_url": lane_setting("buyer_rpc_url"),
        "ssh_public_key": "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAITestKeyForE2E test@e2e",
    }


@pytest.fixture(scope="module")
def seller_wallet() -> str:
    return lane_setting("seller_wallet_address")


@pytest.fixture(scope="module")
def buyer_principal():
    return _signer("buyer").identity


@pytest.fixture(scope="module")
def buyer_fulfillment() -> BareMetalFulfillmentTransport:
    """The production bare-metal buyer's own fulfillment transport."""
    signer = _signer("buyer")
    return BareMetalFulfillmentTransport(
        seller_url=lane_setting("storefront_url"),
        principal=signer.identity,
        signer=signer,
        resolve_seller_principals=lambda: _pinned("storefront"),
    )


@pytest.fixture(scope="module")
def deal_driver(
    bare_metal_site_operator,
    bare_metal_site_capacity,
    provisioning_client,
    provisioning_test_client,
    storefront_admin_client,
    buyer_fulfillment,
    site_capacity,
    buyer_config,
) -> BareMetalComputeDealDriver:
    """Bare metal's part of the canonical compute deal's shared stages."""
    return BareMetalComputeDealDriver(
        site_operator=bare_metal_site_operator,
        site_capacity_admin=bare_metal_site_capacity,
        provisioning_client=provisioning_client,
        provisioning_test_client=provisioning_test_client,
        storefront_admin_client=storefront_admin_client,
        fulfillment=buyer_fulfillment,
        site_capacity=site_capacity,
        buyer_config=buyer_config,
        site_id=lane_setting("site_id"),
    )


@pytest.fixture(scope="module")
def convergence_advanced_explicitly(provisioning_client):
    """This module drives fulfillment convergence; the timer does not.

    See `convergence_paused` for why it is opt-in and resumed in the finaliser.
    """
    yield from convergence_paused(provisioning_client)
