"""Typed clients for the bare-metal end-to-end lane.

Every client reaches its service the way its real caller does: the storefront's
administrator steps publication, the site's administrator declares pools, the
storefront's own principal declares capacity (the site binds its seller role to
that principal), and a buyer reads the registry. Each response is verified
against the principal the lane pins for that service.

The lane provides every setting under ``bare_metal_lane`` in
``config/config-docker.yml``, so a missing one fails the scenario rather than
skipping it: a skip is how bare-metal publication once went unexercised.
"""

from __future__ import annotations

from typing import Any

import pytest
from market_identity import Identity, TrustedIdentitySet, create_signer
from market_site_client import SiteCapacityAdminClient
from registry_client import SyncRegistryClient
from storefront_client import SyncStorefrontClient
from vm_provisioning_operator import SyncProvisioningClient

from src.settings import settings


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
    """The site's administrator, which declares and changes resource pools."""
    client = SyncProvisioningClient(
        lane_setting("site_url"),
        _signer("site_admin"),
        _pinned("site_authority"),
    )
    yield client
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
