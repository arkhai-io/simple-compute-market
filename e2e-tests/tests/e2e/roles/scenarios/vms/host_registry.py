"""Shared setup for the executor host every VM scenario negotiates against.

The site authority builds its capacity projection by iterating host rows: one
projected resource per registered host, with each capacity resource's attributes
correlated onto it. With no hosts registered the projection is empty, so every
inventory match fails and the storefront refuses each negotiation with
`no_matching_inventory` — several layers from the cause.

Scenarios call this from a numbered stage rather than relying on a mounted
inventory file. Three reasons. A file is seeded at container start, so a failure
surfaces at the first negotiation instead of at setup. A file is also
docker-compose-specific: the canonical Helm deployment supplies inventory as an
inline `inventory_ini` secret, so a scenario built around a mount exercises a path
production does not use. And a file is shared state no scenario declares —
registering through the same admin API an operator would use makes the dependency
visible in the test that has it.
"""

from __future__ import annotations

from typing import Any

from vm_provisioning_operator.client import ProvisioningError
from vm_provisioning_operator.models import HostCreate

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

    host = provisioning_client.get_host(name)
    assert host is not None, f"host {name!r} absent after registration"
    return host


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
