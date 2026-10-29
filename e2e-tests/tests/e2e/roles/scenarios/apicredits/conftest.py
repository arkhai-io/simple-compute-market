"""Settings and clients shared by the API-credit lane's scenarios."""

from __future__ import annotations

import pytest
from market_identity import Identity, TrustedIdentitySet, create_signer
from storefront_client import SyncStorefrontClient

from e2e_harness.settings import settings


def lane_setting(name: str) -> str:
    """One API-credit lane setting, failing the scenario when it is absent.

    The lane supplies its own configuration, so a missing value is a broken
    lane, not a scenario to skip: in this lane a skip would leave nothing
    passing and the run green. Only an external authority the lane does not
    supply, such as a payments target, may block a scenario.
    """
    value = str(settings.get(name, "") or "").strip()
    if not value:
        pytest.fail(f"API-credit lane setting {name} is not configured")
    return value


@pytest.fixture(scope="module")
def credits_storefront_admin():
    """The credits storefront's administrator, which steps its loops."""
    client = SyncStorefrontClient(
        lane_setting("API_CREDITS.STOREFRONT_URL"),
        create_signer(
            lane_setting("API_CREDITS.STOREFRONT_ADMIN_SCHEME"),
            lane_setting("API_CREDITS.STOREFRONT_ADMIN_CREDENTIAL"),
        ),
        caller_role="admin",
        expected_publishers=TrustedIdentitySet(
            identities=(
                Identity(
                    scheme=lane_setting("API_CREDITS.STOREFRONT_SCHEME"),
                    identifier=lane_setting("API_CREDITS.STOREFRONT_IDENTIFIER"),
                ),
            )
        ),
    )
    yield client
    client.close()
