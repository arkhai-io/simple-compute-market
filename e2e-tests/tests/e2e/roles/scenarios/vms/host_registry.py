"""Shared capacity setup for the VM scenarios: pools, executor hosts, declarations.

Three separate records must exist before a VM deal can be negotiated, and they live
in three different stores:

- A **resource pool** in the provisioning service groups executors and carries the
  `listing_mode` policy tag deciding whether the storefront publishes one listing
  per member (`specific_resource`) or one aggregated listing per pool (`fungible`).
- An **executor host** is how the provisioner reaches a machine. It carries pool
  membership, and no sellable capacity any claim consults.
- A **capacity declaration** in the site ledger is what `probe` and `reserve` match
  against. `register_resource` is the only thing that creates one, and nothing
  derives one from a host.

That last point has cost two debugging loops. The host-derived fallback in the
provisioner's inventory provider populates the *resource-pool projection*, which is
what listing derivation reads — so a scenario registering only a host can publish
listings it cannot sell against. Every claim path (`has_matching_inventory_guard`'s
snapshot, `probe`, `reserve`) reads capacity buckets, and with no declaration they
see an empty list. The refusal then surfaces as `no_matching_inventory`, several
stages downstream of the missing setup.

One declaration per executor, and one executor per scenario. A second declaration on
one machine sells the same hardware twice, which the provisioner's inventory loader
refuses outright — and a shared executor is what previously let one scenario's GPU
count break another's reservation. A fungible pool is therefore several executors
with one declaration each, never several declarations on one.

A declaration's own id stays the commercial resource id the scenario's listing
advertises, not the executor's alias: `compute_capacity_claim_from_order` pins the
listing's `offer_resource.resource_id` into the claim, so the declaration must carry
that id to be matched at all. The `vm_host` attribute carries the executor
correlation instead.

Registration goes through the admin APIs rather than a mounted inventory file:
`inventory_path` is docker-compose-specific while the canonical Helm deployment
supplies inventory as an inline secret, and a mount is shared state no scenario
declares.
"""

from __future__ import annotations

from typing import Any

from vm_provisioning_operator import PoolCreate, PoolUpdate
from vm_provisioning_operator.client import ProvisioningError
from vm_provisioning_operator.models import HostCreate, HostUpdate

#: GPUs per executor host. Must cover the largest single slice any scenario
#: reserves — 4, in the dynamic-listings cases. A fungible pool's advertised total
#: is this times its member count, but one reservation is still bounded by one
#: member: slice listings are published up to the per-member ceiling, not the pool
#: sum, because admission matches a single bucket.
E2E_HOST_GPU_COUNT = 4

#: One executor per scenario. Sharing `kvm1` across all of them is what coupled the
#: scenarios to each other, and is incompatible with one declaration per executor.
E2E_BUY_HOST = "kvm-buy"
E2E_DEAL_HOST = "kvm-deal"
E2E_DEAL_CLI_HOST = "kvm-deal-cli"
E2E_MULTI_REGISTRY_HOST = "kvm-multi"
E2E_NON_ERC20_HOST = "kvm-non-erc20"
E2E_DYNAMIC_HOST = "kvm-dynamic"
E2E_FUNGIBLE_HOSTS = ("kvm-fungible-a", "kvm-fungible-b")

#: One pool per scenario, for the same reason as one executor per scenario: a
#: pool's `listing_mode` is resolved per pool, and its structural default flips to
#: `fungible` above one member. Sharing the system `default` pool would let adding a
#: scenario silently change how another scenario's listings are published.
#: The pool the provisioning service seeds from its own active configuration. Read
#: for its provider configuration, never used to hold a scenario's capacity.
SYSTEM_DEFAULT_POOL_ID = "default"

E2E_BUY_POOL_ID = "compute-e2e-buy-pool"
E2E_DEAL_POOL_ID = "compute-e2e-deal-pool"
E2E_DEAL_CLI_POOL_ID = "compute-e2e-deal-cli-pool"
E2E_MULTI_REGISTRY_POOL_ID = "compute-e2e-multi-pool"
E2E_NON_ERC20_POOL_ID = "compute-e2e-non-erc20-pool"


def register_e2e_pool(
    provisioning_client: Any,
    *,
    pool_id: str,
    listing_mode: str,
    label: str | None = None,
) -> Any:
    """Create the resource pool, idempotently, and return the pool row.

    `listing_mode` is a pool policy tag the storefront's publication resolves. It is
    passed explicitly rather than defaulted because the structural fallback —
    `specific_resource` at exactly one member — is only accidentally right for a
    pool about to gain a second member.

    The provider configuration is inherited from the system `default` pool rather
    than written here. An Ansible pool must carry a `playbook_path`, and its correct
    value is deployment-specific — `/dev/null` under the mock profile, a container
    path under docker, another under Helm. Copying the default pool's configuration
    keeps a scenario's pools provisioning exactly the way that deployment already
    provisions, and means a scenario never encodes a path belonging to one profile.
    """
    # Narrow on purpose: a 404 means "not created yet", which is the point of the
    # lookup. A transport or auth failure means the service is unreachable, and
    # creating on top of that would report success over an error.
    try:
        existing = provisioning_client.get_pool(pool_id)
    except ProvisioningError:
        existing = None

    if existing is not None:
        # Reconcile rather than accept, the same way the host helper does: a pool
        # surviving an earlier run may carry a different mode, and the mode decides
        # how this scenario's listings are published.
        if (existing.policy_tags or {}).get("listing_mode") != listing_mode:
            provisioning_client.patch_pool(pool_id, PoolUpdate(
                policy_tags={**(existing.policy_tags or {}), "listing_mode": listing_mode},
            ))
            return provisioning_client.get_pool(pool_id)
        return existing

    provisioning_client.create_pool(PoolCreate(
        id=pool_id,
        label=label or pool_id,
        provider="ansible",
        policy_tags={"listing_mode": listing_mode},
        provider_config=_default_pool_provider_config(provisioning_client),
    ))
    return provisioning_client.get_pool(pool_id)


def _default_pool_provider_config(provisioning_client: Any) -> dict[str, Any]:
    """The system default pool's provider configuration.

    The default pool is seeded from the provisioning service's own active
    configuration, so it is the one place a scenario can read a valid
    `playbook_path` for whatever profile the stack is running under.
    """
    default_pool = provisioning_client.get_pool(SYSTEM_DEFAULT_POOL_ID)
    config = dict(getattr(default_pool, "provider_config", None) or {})
    assert config.get("playbook_path"), (
        f"the {SYSTEM_DEFAULT_POOL_ID!r} pool reports no playbook_path "
        f"({config!r}); an Ansible pool cannot be created without one, and this "
        "scenario has no profile-independent value to substitute"
    )
    return config


def register_e2e_host(
    provisioning_client: Any,
    *,
    name: str,
    pool_id: str,
    gpu_count: int = E2E_HOST_GPU_COUNT,
) -> Any:
    """Register one executor host into `pool_id`, idempotently.

    `ssh_key_type='path'` stores the value verbatim, so no key material is needed:
    nothing here SSHes anywhere — provisioning runs in mock mode — and the host
    exists to be an executor identity, not to be reached.

    Reconciles rather than accepting what is there. A host may survive an earlier
    run against the same stack with a different GPU count or pool, and the contract
    is that it exists *with what this scenario needs*.
    """
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
            pool_id=pool_id,
        ))
    elif (existing.gpu_count or 0) < gpu_count or existing.pool_id != pool_id:
        provisioning_client.update_host(
            name, HostUpdate(gpu_count=gpu_count, pool_id=pool_id),
        )

    host = provisioning_client.get_host(name)
    assert host is not None, f"host {name!r} absent after registration"
    assert host.pool_id == pool_id, (
        f"host {name!r} is in pool {host.pool_id!r}, not {pool_id!r} — another "
        "scenario may be sharing this executor"
    )
    return host


def declare_e2e_capacity(
    site_admin_client: Any,
    *,
    resource_id: str,
    vm_host: str,
    attributes: dict[str, Any],
    pool_id: str,
    gpu_count: int = E2E_HOST_GPU_COUNT,
) -> dict[str, Any]:
    """Declare one executor's sellable capacity in the site ledger.

    `pool_id` is passed as the field, never inside `attributes`. The field is what
    admission and both projections read; an attribute of the same name is read by
    nothing.

    `attributes` carry the categorical fields a claim matches by equality —
    `gpu_model` and `region` above all. They are passed in rather than defaulted
    because each scenario declares its own in the listing it publishes, and a
    default here would silently disagree with one of them. A declaration missing
    either reproduces the `no_matching_inventory` refusal this helper prevents.
    """
    return site_admin_client.register_resource(
        resource_id,
        total_units=gpu_count,
        resource_type="compute.gpu",
        pool_id=pool_id,
        capacity={"gpu_count": gpu_count},
        attributes={**attributes, "vm_host": vm_host},
    )


def provision_e2e_executor(
    provisioning_client: Any,
    site_admin_client: Any,
    *,
    host: str,
    resource_id: str,
    attributes: dict[str, Any],
    pool_id: str,
    listing_mode: str = "specific_resource",
    gpu_count: int = E2E_HOST_GPU_COUNT,
) -> Any:
    """Pool, executor host, and its one capacity declaration, in dependency order.

    The pool must exist before a host can join it, and the host before a
    declaration correlates to it. Most scenarios want exactly this sequence once,
    so they call this rather than the three helpers individually.
    """
    register_e2e_pool(
        provisioning_client, pool_id=pool_id, listing_mode=listing_mode,
    )
    host_row = register_e2e_host(
        provisioning_client, name=host, pool_id=pool_id, gpu_count=gpu_count,
    )
    declare_e2e_capacity(
        site_admin_client,
        resource_id=resource_id,
        vm_host=host,
        attributes=attributes,
        pool_id=pool_id,
        gpu_count=gpu_count,
    )
    return host_row


def refresh_storefront_projections(storefront_client: Any) -> dict[str, Any]:
    """Make the storefront pull site projections now, and prove it landed.

    Projections are pull-synchronized on a poller interval. Waiting one out is a
    sleep, and a sleep is slow when it passes and flaky when it does not — so the
    storefront exposes an admin refresh and this asserts on its answer.

    A site reporting `not_loaded`, `unavailable`, or `invalid` has not confirmed its
    projection. That is explicitly not the same as an authoritative empty, and
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
