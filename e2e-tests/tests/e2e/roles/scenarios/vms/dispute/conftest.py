"""Fixtures every VM dispute scenario takes; each module supplies its own driver."""

from __future__ import annotations

import pytest

from tests.e2e.roles.helpers.mediation import MediationTarget, configured_mediation
from tests.e2e.roles.helpers.payments import configured_payments
from tests.e2e.roles.scenarios.vms.dispute.stages import DisputeState
from tests.e2e.roles.scenarios.vms.lifecycle_deal import TypedLifecycleBuyer


@pytest.fixture(scope="module")
def payments_config():
    """The lane's payments target: a blocked skip when none is configured."""
    return configured_payments()


@pytest.fixture(scope="module")
def mediation_target() -> MediationTarget:
    """The lane's mediation target: a blocked skip when none is configured, a
    failure when the lane's own is not ready."""
    return configured_mediation()


@pytest.fixture(scope="module")
def dispute(tmp_path_factory) -> DisputeState:
    return DisputeState(buyer_store=tmp_path_factory.mktemp("dispute_buyer_evidence"))


@pytest.fixture(scope="module")
def vm_lifecycle_buyer(storefront_client, storefront_admin_client, registry_client,
                       deal_driver, buyer_config, seller_wallet, site_capacity):
    """The buyer's lifecycle reads, for the release stage of ``lifecycle_deal.py``."""
    return TypedLifecycleBuyer(storefront_client, storefront_admin_client, registry_client,
                               deal_driver, buyer_config, seller_wallet, site_capacity)
