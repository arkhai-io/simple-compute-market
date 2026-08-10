"""Shared setup for the executor host every VM scenario negotiates against.

The site authority builds its capacity projection by iterating host rows: one
projected resource per registered host, with each capacity resource's attributes
correlated onto it. With no hosts registered the projection is empty, so every
inventory match fails and the storefront refuses each negotiation with
`no_matching_inventory` — several layers from the cause.

Scenarios call this from a numbered stage. Registration used to happen in an
autouse module fixture, where it was setup no scenario named and nobody looked
for — a host registered with one GPU made every scenario reserving more fail as
though no inventory matched. A numbered stage names its own dependency, reports
in the scenario log, and fails at setup rather than several stages downstream.

A mounted inventory file was also considered and rejected: `inventory_path` is
docker-compose-specific, while the canonical Helm deployment supplies inventory as
an inline `inventory_ini` secret, so a scenario built around a mount would
exercise a path production does not use.
"""

from __future__ import annotations

from typing import Any

from vm_provisioning_operator.client import ProvisioningError
from vm_provisioning_operator.models import HostCreate, HostUpdate

#: The alias every VM scenario's seed CSV carries in `attribute.vm_host`.
E2E_HOST_NAME = "kvm1"

#: Must cover the largest slice any scenario reserves — 4, in the fungible
#: dynamic-listings case.
E2E_HOST_GPU_COUNT = 4


def register_e2e_host(
    provisioning_client: Any,
    *,
    name: str = E2E_HOST_NAME,
    gpu_count: int = E2E_HOST_GPU_COUNT,
) -> Any:
    """Register the executor host, idempotently, and return the host row.

    `ssh_key_type='path'` stores the value verbatim, so no key material is
    needed: nothing in these scenarios SSHes anywhere — provisioning runs in mock
    mode — and the host exists to carry capacity, not to be reached.
    """
    # Narrow on purpose: a 404 means "not registered yet" and is the whole point
    # of the lookup, while a transport or auth failure means the registry is
    # unreachable. Catching both would register on top of an error and report
    # success.
    try:
        existing = provisioning_client.get_host(name)
    except ProvisioningError:
        existing = None

    if existing is None:
        provisioning_client.register_host(HostCreate(
            name=name,
            kvm_host="127.0.0.1",
            ssh_user="e2e",
            gpu_count=gpu_count,
            ssh_key_type="path",
            ssh_key_value="/dev/null",
        ))
    elif (existing.gpu_count or 0) < gpu_count:
        # Reconcile rather than accept what is there. Scenarios share a stack, so
        # a host registered by an earlier one may carry less capacity than this
        # one reserves; the contract here is that the host exists *with the
        # capacity the scenario needs*. A host that merely exists is what made a
        # capacity shortfall read as an inventory mismatch.
        provisioning_client.update_host(name, HostUpdate(gpu_count=gpu_count))

    host = provisioning_client.get_host(name)
    assert host is not None, f"host {name!r} absent after registration"
    return host


def register_e2e_capacity(
    site_admin_client: Any,
    *,
    resource_id: str = E2E_HOST_NAME,
    gpu_count: int = E2E_HOST_GPU_COUNT,
    attributes: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Register sellable capacity for the executor host in the site ledger.

    The ledger is a different store from the host registry, and from the
    host-derived projection. `probe` and `reserve` match against
    `CapacityBucket` rows, and `register_resource` is the only thing that creates
    one — so a scenario that reserves capacity must put a resource here, however
    many hosts are registered.

    `attributes` carry the commercial fields a claim matches by equality. They are
    passed in rather than defaulted because each scenario declares its own in the
    resource CSV it seeds, and a default here would silently disagree with one of
    them.
    """
    return site_admin_client.register_resource(
        resource_id,
        total_units=gpu_count,
        resource_type="compute.gpu",
        attributes=attributes or {},
        capacity={"gpu_count": gpu_count},
    )


def refresh_storefront_projections(storefront_client: Any) -> dict[str, Any]:
    """Make the storefront pull site projections now, and prove it landed.

    Projections are pull-synchronized on a poller interval. Waiting one out is a
    sleep, and a sleep is slow when it passes and flaky when it does not — so the
    storefront exposes an admin refresh and this asserts on its answer.

    A site reporting `not_loaded`, `unavailable`, or `invalid` has not confirmed
    its projection. That is explicitly not the same as an authoritative empty, and
    treating it as one is how an inventory failure becomes a negotiation failure
    three layers away.
    """
    result = storefront_client.admin_refresh_site_projections()
    sites = result.get("sites") or {}
    assert sites, "storefront reported no capacity sites after a projection refresh"

    unconfirmed = {
        f"{site}/{family}": view.get("state")
        for site, families in sites.items()
        for family, view in families.items()
        if view.get("state") not in {"loaded", "fresh", "ok"}
    }
    assert not unconfirmed, (
        "site projections did not confirm after refresh: "
        f"{unconfirmed}. An unconfirmed projection is not an empty one — "
        "inventory matching downstream cannot tell the difference."
    )
    return sites
