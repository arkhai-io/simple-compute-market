"""Storefront test configuration.

The negotiation policy catalogue is composed once during lifespan startup and
held on the container. Tests that exercise negotiation behaviour do not run the
lifespan, so this populates the container the way startup does — one place rather
than in every suite that reaches a negotiation path.

Composition itself is covered by the policy-kit and role-composition suites, and
`tests/unit/test_policy_catalogue_lifecycle.py` covers the case this fixture
deliberately papers over: reaching negotiation with an unresolved catalogue.
"""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _resolved_policy_catalogue():
    from market_storefront import container
    from market_storefront.utils.sync_negotiation import compose_policy_catalogue

    previous = container.resolved_policy_catalogue
    container.resolved_policy_catalogue = compose_policy_catalogue()
    try:
        yield container.resolved_policy_catalogue
    finally:
        container.resolved_policy_catalogue = previous
