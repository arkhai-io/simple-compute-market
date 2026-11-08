"""VM fulfillment results, provisioning-job previews and lease termination.

The order of a VM deal's delivery is the compute family's delivery path's
(``market_storefront.delivery_ports``); this module holds the VM reading of a
fulfillment result and the provisioning calls outside that order.
"""

from __future__ import annotations

import logging
from typing import Any

from compute_provisioning_contracts import (
    ACCESS_DELIVERY_KIND,
    ACCESS_DELIVERY_SCHEMA_VERSION,
    AccessDelivery,
    LeaseView,
)
from arkhai_vms import VmConnectionDetails
from market_core import VersionedEnvelope

from market_storefront.services.capacity_client import (
    AggregateFulfillmentClient,
    build_capacity_client,
)
from market_storefront.services.vm_job_spec_service import (
    build_provisioning_job_spec as _vm_build_provisioning_job_spec,
)

logger = logging.getLogger(__name__)

#: The VM domain's market identity in schedule and begin-fulfillment calls.
VM_MARKET = "vms"


def fulfillment_result_connection(envelope: VersionedEnvelope) -> dict[str, Any]:
    """An active fulfillment's delivery, as the deal's connection details.

    The details are ``VmConnectionDetails``: the delivered SSH endpoint, when
    access became ready, and the provisioned resources. The credentials the
    delivery carries, by role and with only their delivered fields, come
    alongside under ``authentication``; they are never part of the connection
    details, and nothing stores them.
    """
    payload: dict[str, Any] = envelope.payload or {}
    domain = payload.get("domain_result") or {}
    if (
        domain.get("kind") != ACCESS_DELIVERY_KIND
        or domain.get("schema_version") != ACCESS_DELIVERY_SCHEMA_VERSION
    ):
        raise RuntimeError(
            f"physical fulfillment returned an unsupported delivery {domain.get('kind')!r}"
        )
    delivery = AccessDelivery.model_validate(domain.get("payload") or {})
    endpoint = next(
        (endpoint for endpoint in delivery.endpoints if endpoint.protocol == "ssh"), None
    )
    if endpoint is None:
        raise RuntimeError("physical fulfillment delivered no SSH endpoint")
    details: dict[str, Any] = VmConnectionDetails(
        host=endpoint.host,
        port=endpoint.port,
        user=endpoint.user,
        ready_at=delivery.ready_at,
        provisioned_resource_ids=tuple(
            str(resource.get("provisioned_resource_id"))
            for resource in payload.get("provisioned_resources", [])
        ),
    ).model_dump(mode="json", exclude_none=True)
    authentication = {
        credential.role: {"password": credential.password, "key_type": credential.key_type}
        for credential in delivery.credentials
        if credential.role in ("root", "tenant")
    }
    if authentication:
        details["authentication"] = authentication
    return details


async def _build_provisioning_job_spec(
    *,
    order_dict: dict | None,
    ssh_public_key: str,
    duration_seconds: int,
    sqlite_client: Any,
) -> dict | None:
    db = sqlite_client
    return await _vm_build_provisioning_job_spec(
        order_dict=order_dict,
        ssh_public_key=ssh_public_key,
        duration_seconds=duration_seconds,
        capacity=build_capacity_client(lambda: db),
    )


async def terminate_vm_lease(
    fulfillment_client: AggregateFulfillmentClient,
    *,
    capacity_reservation_id: str,
    site_id: str,
    reason: str | None = None,
) -> LeaseView:
    """Ask the site holding a reservation to begin tearing down its leased VM early.

    ``fulfillment_client`` is the storefront's per-site fulfillment client
    (``build_fulfillment_client``) and ``site_id`` the site the deal's records
    bind the reservation to, as every record-bound fulfillment call names it:
    the request goes to that site alone, and its answer is verified against that
    site's own service peer. The site submits the same release its lease
    watchdog's expiry sweep submits (`POST
    /api/v1/contract/leases/{capacity_reservation_id}/terminate`), but
    immediately. Capacity is held until the site confirms teardown; this call
    only requests that teardown begin and returns the lease as the site then
    records it.

    End service uses this port for due final requests. Recording the intended
    end and proving capacity return remain separate observations.
    """
    return await fulfillment_client.terminate_lease(
        capacity_reservation_id, site_id=site_id, reason=reason
    )
