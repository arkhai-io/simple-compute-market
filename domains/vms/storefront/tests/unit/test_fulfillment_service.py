"""VM's reading of a fulfillment result, the relay its requests never name, and
early lease termination at the reservation's own site."""

from __future__ import annotations

import inspect
from typing import Any

import pytest
from arkhai_vms import VmConnectionDetails
from market_core import VersionedEnvelope

from market_storefront import delivery_ports
from market_storefront.services import fulfillment_service
from market_storefront.services.capacity_client import AggregateFulfillmentClient
from tests.fulfillment_fixtures import vm_fulfillment_result


class TestFulfillmentResultConnection:
    def test_the_delivery_becomes_the_deals_connection_details(self):
        envelope = vm_fulfillment_result(
            provisioned_resource_id="res-1",
            credentials=(
                {"role": "root", "password": "root-pw", "key_type": None},
                {"role": "tenant", "password": "tenant-pw", "key_type": "generated"},
            ),
        )

        result = fulfillment_service.fulfillment_result_connection(envelope)

        auth = result.pop("authentication")
        assert VmConnectionDetails.model_validate(result) == VmConnectionDetails(
            host="203.0.113.10",
            port=2222,
            user="tenant1",
            ready_at="2030-01-01T00:00:01+00:00",
            provisioned_resource_ids=("res-1",),
        )
        assert auth == {
            "root": {"password": "root-pw", "key_type": None},
            "tenant": {"password": "tenant-pw", "key_type": "generated"},
        }

    def test_a_result_without_the_access_delivery_is_refused(self):
        envelope = VersionedEnvelope(
            kind="fulfillment.result.v1",
            schema_version=1,
            payload={"provisioned_resources": [], "domain_result": None},
        )

        with pytest.raises(RuntimeError, match="unsupported delivery"):
            fulfillment_service.fulfillment_result_connection(envelope)

    def test_an_unknown_credential_role_is_not_kept(self):
        envelope = vm_fulfillment_result(
            credentials=({"role": "admin", "password": "x"},),
        )

        assert "authentication" not in fulfillment_service.fulfillment_result_connection(envelope)


class TestTheStorefrontSelectsNoRelay:
    """The storefront names no relay when it builds a fulfillment request.

    Which relay a host dials is recorded on the relay its pool references. A
    storefront naming one per request would make a fleet-wide fact depend on a
    caller's configuration, and would let two requests against one host
    disagree about how that host is reached. The buyer's address and port come
    back in the fulfillment result.
    """

    def test_no_builder_remains_to_be_called(self):
        assert not hasattr(fulfillment_service, "_connectivity_settings_from_storefront_config")

    def test_no_request_builder_reads_relay_settings(self):
        """Asserted against the source rather than by driving it, because the
        point is that no code path exists to reach — a behavioural test can
        only show that the paths exercised did not."""
        for module in (fulfillment_service, delivery_ports):
            source = inspect.getsource(module)
            body = "\n".join(
                line for line in source.splitlines() if not line.lstrip().startswith("#")
            )
            for key in ("frp_server_addr", "frp_domain", "frp_dashboard_password"):
                assert key not in body, f"{module.__name__} still reads {key}"


@pytest.mark.asyncio
async def test_terminate_vm_lease_asks_only_the_reservations_site():
    """The early-termination plumbing: the request reaches the reservation's
    recorded site and no other, with the reason passed through, and the site's
    lease view comes back."""
    calls: list[tuple[str, str, Any]] = []

    class Site:
        def __init__(self, name):
            self.name = name

        async def terminate_lease(self, capacity_reservation_id, termination):
            calls.append((self.name, capacity_reservation_id, termination))
            return {"capacity_reservation_id": capacity_reservation_id, "site": self.name}

    aggregate = AggregateFulfillmentClient(
        {"site-a": Site("site-a"), "site-b": Site("site-b")},
        # Another site cached for the reservation is not consulted.
        reservation_sites={"reservation-1": "site-a"},
    )

    lease = await fulfillment_service.terminate_vm_lease(
        aggregate,
        capacity_reservation_id="reservation-1",
        site_id="site-b",
        reason="buyer requested early termination",
    )

    assert lease == {"capacity_reservation_id": "reservation-1", "site": "site-b"}
    ((site, reservation, termination),) = calls
    assert (site, reservation) == ("site-b", "reservation-1")
    assert termination.reason == "buyer requested early termination"
