"""API-credit storefront test configuration.

The negotiation policy catalogue is composed once during lifespan startup and
held on the container. Tests that exercise negotiation behaviour do not run the
lifespan, so this populates the container the way startup does.
"""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _resolved_policy_catalogue():
    from apicredits_storefront import container
    from apicredits_storefront.utils.sync_negotiation import (
        compose_policy_catalogue,
    )

    previous = container.resolved_policy_catalogue
    container.resolved_policy_catalogue = compose_policy_catalogue()
    try:
        yield container.resolved_policy_catalogue
    finally:
        container.resolved_policy_catalogue = previous
