"""The VM purchase driver's reads of the storefront, against fake clients that
return the typed storefront client's own response types."""

from __future__ import annotations

from unittest.mock import MagicMock

from market_identity import Identity
from storefront_client.models import SettleStatusResponse

from tests.e2e.roles.scenarios.vms.purchase_driver import VmPurchaseDriver

# Placeholder addresses that name no real account; never use them on a network.
BUYER = Identity(scheme="eip191", identifier="0x" + "11" * 20)
SELLER = Identity(scheme="eip191", identifier="0x" + "22" * 20)


def _driver(*, storefront_client, storefront_admin_client) -> VmPurchaseDriver:
    return VmPurchaseDriver(
        provisioning_client=None, storefront_client=storefront_client,
        storefront_admin_client=storefront_admin_client, storefront_service_client=None,
        site_capacity_admin_client=None, site_capacity=None, site_id="site",
        provisioning_test_client=None, buyer_config={"ssh_public_key": "k"},
        purchase_registry=None, seller_account="seller", dispute_window="P7D",
    )


def test_the_purchases_fulfillment_is_the_buyers_settle_status_once_the_job_is_submitted():
    admin = MagicMock()
    storefront = MagicMock()
    storefront.get_settle_status.return_value = SettleStatusResponse(
        status="provisioning", escrow_uid="negotiation-1",
        buyer_principal=BUYER, seller_principal=SELLER,
        fulfillment_id="fulfillment-1", provisioning_job_id="job-1",
    )

    status = _driver(
        storefront_client=storefront, storefront_admin_client=admin,
    ).purchase_fulfillment("negotiation-1")

    admin.wait_for_stage_event.assert_called_once()
    assert admin.wait_for_stage_event.call_args.args == ("provision", "job_submitted")
    assert admin.wait_for_stage_event.call_args.kwargs["negotiation_id"] == "negotiation-1"
    storefront.get_settle_status.assert_called_once_with("negotiation-1")
    assert status["fulfillment_id"] == "fulfillment-1"
    assert status["status"] == "provisioning"
    assert status["buyer_principal"] == BUYER
