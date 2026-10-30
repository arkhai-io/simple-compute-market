"""Shared capacity setup for the VM scenarios: pools, executor hosts, declarations.

It also holds which GPUs a VM resource carries (`resource_gpus`), the one rule
a scenario's listing shape and its claims on that supply both follow.

Three separate records must exist before a VM deal can be negotiated, and they live
in three different stores:

- A **resource pool** in the provisioning service groups executors and carries the
  `listing_mode` policy tag deciding whether the storefront publishes one listing
  per member (`specific_resource`) or one aggregated listing per pool (`fungible`).
- An **executor host** is how the provisioner reaches a machine. It carries pool
  membership, and nothing about the machine's hardware or sellable capacity.
- A **capacity declaration** in the site ledger is what `probe` and `reserve` match
  against. `register_resource` is the only thing that creates one, and nothing
  derives one from a host.

The resource-pool projection listing derivation reads is built from declarations
alone, and every claim path (`has_matching_inventory_guard`'s snapshot, `probe`,
`reserve`) reads capacity buckets, so a scenario registering only a host publishes
and claims nothing. A missing declaration surfaces as `no_matching_inventory`,
several stages downstream of the missing setup.

One declaration per executor, and one executor per scenario. A second declaration on
one machine sells the same hardware twice, which the provisioner's inventory loader
refuses outright — and on a shared executor one scenario's declaration would change
what another can reserve. A fungible pool is therefore several executors with one
declaration each, never several declarations on one.

A declaration's own id stays the commercial resource id the scenario's listing
advertises, not the executor's alias: `compute_capacity_claim_from_order` pins the
listing's `offer_resource.resource_id` into the claim, so the declaration must carry
that id to be matched at all. The declaration's `host_id` field names the host it
is delivered through instead.

Registration goes through the admin APIs rather than a mounted inventory file:
`inventory_path` is docker-compose-specific while the canonical Helm deployment
supplies inventory as an inline secret, and a mount is shared state no scenario
declares.
"""

from __future__ import annotations

import asyncio
from typing import Any

from market_resource_pools_contracts.backing import BACKED
from market_resource_pools_contracts.hints import (
    ADVERTISABLE_MODES_POLICY_TAG,
    CAPACITY_BACKING_POLICY_TAG,
    DELIVERABLE_MODES_POLICY_TAG,
)
from market_resource_pools_contracts import PoolCreate, PoolUpdate
from compute_provisioning_client import ComputeProvisioningError
from market_resource_pools_client import SyncResourcePoolClient
from compute_provisioning_contracts import ConnectionSubmission, HostCreate, HostUpdate

#: One executor per scenario, so no scenario's declaration changes what another can
#: reserve, as one declaration per executor requires.
E2E_BUY_HOST = "kvm-buy"
E2E_DEAL_HOST = "kvm-deal"
E2E_DEAL_CLI_HOST = "kvm-deal-cli"
E2E_MULTI_REGISTRY_HOST = "kvm-multi"
E2E_NON_ERC20_HOST = "kvm-non-erc20"
E2E_DYNAMIC_HOST = "kvm-dynamic"
E2E_FUNGIBLE_HOSTS = ("kvm-fungible-a", "kvm-fungible-b")
E2E_LISTING_SHAPES_HOST = "kvm-shapes"
E2E_LISTING_SHAPES_CPU_HOST = "kvm-shapes-cpu"

#: One pool per scenario, for the same reason as one executor per scenario: a
#: pool's `listing_mode` is resolved per pool, and its structural default flips to
#: `fungible` above one member. Sharing one pool would let adding a scenario
#: silently change how another scenario's listings are published.
E2E_BUY_POOL_ID = "compute-e2e-buy-pool"
E2E_DEAL_POOL_ID = "compute-e2e-deal-pool"
E2E_DEAL_CLI_POOL_ID = "compute-e2e-deal-cli-pool"
E2E_MULTI_REGISTRY_POOL_ID = "compute-e2e-multi-pool"
E2E_NON_ERC20_POOL_ID = "compute-e2e-non-erc20-pool"
E2E_LISTING_SHAPES_POOL_ID = "compute-e2e-listing-shapes-pool"
E2E_LISTING_SHAPES_CPU_POOL_ID = "compute-e2e-listing-shapes-cpu-pool"


def resource_gpus(resource: dict[str, Any]) -> tuple[int, str] | None:
    """The GPU count and model a VM resource carries, or ``None`` for none.

    A resource carries GPUs only when it states a positive `gpu_count` and a
    `gpu_model`. A shape that declares no GPUs is sold and claimed without the
    GPU family at all: a zero count or a model alone would publish, and claim,
    a GPU dimension the machine does not have.
    """
    count = resource.get("gpu_count")
    model = resource.get("gpu_model")
    if isinstance(count, int) and count > 0 and model:
        return count, str(model)
    return None


def claim_attributes(resource: dict[str, Any], *, resource_id: str) -> dict[str, Any]:
    """What a claim pinned to `resource_id` requires of a resource of this shape.

    The GPU count is required only of a shape that carries GPUs.
    """
    gpus = resource_gpus(resource)
    return {"resource_id": resource_id, **({"gpu_count": gpus[0]} if gpus else {})}


def _pools(provisioning_client: Any) -> SyncResourcePoolClient:
    """Pool administration over the family client's signing transport."""
    return SyncResourcePoolClient(provisioning_client)


def register_e2e_pool(
    provisioning_client: Any,
    *,
    pool_id: str,
    listing_mode: str,
    deliverable_modes: tuple[str, ...] = ("vm",),
    label: str | None = None,
    listing_shapes: dict[str, list[dict[str, Any]]] | None = None,
    pricing: dict[str, Any] | None = None,
    region: str | None = None,
) -> Any:
    """Create the resource pool, idempotently, and return the pool row.

    `listing_shapes`, when given, is the pool's `listing_shapes` hint: per
    offering mode, the shapes its listings are sold in. Omitted, the pool states
    none and the storefront publishes its default shapes. `pricing`, when given,
    is the pool's `pricing` hint, the durable terms a published listing takes
    ahead of the storefront's configured defaults. `region`, when given, is the
    pool's `region` hint: the region its listings advertise, which a storefront
    takes from the pool rather than from its members, while a reservation matches
    it against each member's declared `region` attribute.

    `listing_mode` is a pool policy tag the storefront's publication resolves. It is
    passed explicitly rather than defaulted because the structural fallback —
    `specific_resource` at exactly one member — is only accidentally right for a
    pool about to gain a second member.

    The pool states no provider configuration. Its playbook is the provisioning
    service's configured `vm_playbook_path`, frozen into each job when the job is
    prepared, and its correct value is deployment-specific — `/dev/null` under the
    mock profile, a container path under docker, another under Helm — so a
    scenario never encodes a path belonging to one profile, and reads no other
    pool to learn one.
    """
    # Narrow on purpose: a 404 means "not created yet", which is the point of the
    # lookup. A transport or auth failure means the service is unreachable, and
    # creating on top of that would report success over an error.
    try:
        existing = _pools(provisioning_client).get_pool(pool_id)
    except ComputeProvisioningError:
        existing = None

    if existing is not None:
        # Reconcile rather than accept, the same way the host helper does: a pool
        # surviving an earlier run may carry a different mode, and the mode decides
        # how this scenario's listings are published.
        tags = dict(existing.policy_tags or {})
        wanted = {
            "listing_mode": listing_mode,
            DELIVERABLE_MODES_POLICY_TAG: list(deliverable_modes),
            **_backed_declarations(deliverable_modes),
            **({"listing_shapes": listing_shapes} if listing_shapes is not None else {}),
            **({"pricing": pricing} if pricing is not None else {}),
            **({"region": region} if region is not None else {}),
        }
        if any(tags.get(k) != v for k, v in wanted.items()):
            _pools(provisioning_client).patch_pool(pool_id, PoolUpdate(
                policy_tags={**tags, **wanted},
            ))
            return _pools(provisioning_client).get_pool(pool_id)
        return existing

    _pools(provisioning_client).create_pool(PoolCreate(
        id=pool_id,
        label=label or pool_id,
        provider="vm.ansible",
        policy_tags={
            "listing_mode": listing_mode,
            # A pool must declare the offering modes it delivers; reservation
            # refuses a claim whose mode no matching pool declares. Stored as a
            # list for stable ordering in exported pool documents, though its
            # semantics are a set.
            DELIVERABLE_MODES_POLICY_TAG: list(deliverable_modes),
            **_backed_declarations(deliverable_modes),
            **({"listing_shapes": listing_shapes} if listing_shapes is not None else {}),
            **({"pricing": pricing} if pricing is not None else {}),
            **({"region": region} if region is not None else {}),
        },
        provider_config={},
    ))
    return _pools(provisioning_client).get_pool(pool_id)


def _backed_declarations(deliverable_modes: tuple[str, ...]) -> dict[str, Any]:
    """The advertisement and backing declarations every pool write requires.

    A scenario pool is ordinary backed supply, so it advertises exactly what it
    delivers: the widest set the backed subset rule accepts.
    """
    return {
        ADVERTISABLE_MODES_POLICY_TAG: list(deliverable_modes),
        CAPACITY_BACKING_POLICY_TAG: BACKED.label,
    }


#: The connection a host is registered with when the scenario reaches it through
#: the mock profile, which connects to nothing. A `key_path` connection names a
#: key file without carrying it, so no key material is needed.
_PLACEHOLDER_CONNECTION = ConnectionSubmission(
    kind="ssh",
    public={"ssh_host": "127.0.0.1", "ssh_user": "e2e", "key_path": "/dev/null"},
)


def _connection_differs(stored: Any, wanted: ConnectionSubmission) -> bool:
    """Whether a stored connection is not the one ``wanted`` describes.

    Compared on the fields ``wanted`` states: a stored connection also carries
    the defaults its kind filled in, which a submission need not repeat.
    """
    if stored.kind != wanted.kind or stored.version != wanted.version:
        return True
    return any(stored.public.get(name) != value for name, value in wanted.public.items())


def register_e2e_host(
    provisioning_client: Any,
    *,
    name: str,
    pool_id: str,
    connection: ConnectionSubmission | None = None,
) -> Any:
    """Register one executor host into `pool_id`, idempotently.

    `connection` is how the provisioning service reaches the host. Omitted, the
    host gets a placeholder that nothing connects to: under the mock profile the
    host exists to be an executor identity, not to be reached.

    Reconciles rather than accepting what is there. A host may survive an earlier
    run against the same stack in a different pool, and the contract is that it
    exists *in the pool this scenario needs*. A host registered with a
    connection has that connection replaced when it differs, so a create is
    never sent to the address an earlier run left behind; without one, an
    existing host's connection is left as it is. What the machine sells is its
    declaration's, never the host's.
    """
    try:
        existing = provisioning_client.get_host(name)
    except ComputeProvisioningError:
        existing = None

    if existing is None:
        provisioning_client.register_host(HostCreate(
            host_id=name,
            connection=connection or _PLACEHOLDER_CONNECTION,
            pool_id=pool_id,
        ))
    else:
        replace = connection is not None and _connection_differs(existing.connection, connection)
        if replace or existing.pool_id != pool_id:
            provisioning_client.update_host(name, HostUpdate(
                pool_id=pool_id,
                **({"connection": connection} if replace else {}),
            ))

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
    host_id: str,
    attributes: dict[str, Any],
    pool_id: str,
    sellable_units: int | None,
    capacity: dict[str, int] | None = None,
) -> dict[str, Any]:
    """Declare one executor's sellable capacity in the site ledger.

    `capacity` declares every dimension; its `gpu_count` must equal
    `sellable_units`. Omitted, the declaration states the GPU count only. A
    machine without GPUs passes `sellable_units=None` and a `capacity` naming no
    `gpu_count`: the site then records no GPU mirror for it, rather than zero.

    `sellable_units` has no default on purpose. It must equal what the scenario's
    own seeded resource declares, because that number decides when a slice listing
    closes: reserve one unit against a four-unit declaration and a 1x listing stays
    open, since three remain. A helper-wide default is exactly the wrong shape for
    a value only the scenario knows.

    `pool_id` is passed as the field, never inside `attributes`. The field is what
    admission and both projections read; an attribute of the same name is read by
    nothing.

    `attributes` carry the categorical fields a claim matches by equality —
    `gpu_model` and `region` above all. They are passed in rather than defaulted
    because each scenario declares its own in the listing it publishes, and a
    default here would silently disagree with one of them. A declaration missing
    either reproduces the `no_matching_inventory` refusal this helper prevents.
    """
    # The capacity-admin client is async-only, so the call is driven here
    # rather than making every caller async: these helpers run from synchronous
    # test stages, and one `asyncio.run` at the boundary keeps that so.
    return asyncio.run(
        site_admin_client.register_resource(
            resource_id,
            total_units=sellable_units,
            resource_type="compute.gpu",
            pool_id=pool_id,
            capacity=_declared_capacity(sellable_units, capacity),
            host_id=host_id, attributes={**attributes},
        )
    )


def _declared_capacity(
    sellable_units: int | None, capacity: dict[str, int] | None
) -> dict[str, int]:
    if sellable_units is None:
        if not capacity or "gpu_count" in capacity:
            raise ValueError(
                "a declaration with no sellable GPU units must state a capacity "
                f"naming no gpu_count, not {capacity!r}"
            )
        return dict(capacity)
    if capacity is None:
        return {"gpu_count": sellable_units}
    if capacity.get("gpu_count") != sellable_units:
        raise ValueError(
            f"capacity gpu_count {capacity.get('gpu_count')!r} must equal "
            f"sellable_units {sellable_units}"
        )
    return dict(capacity)


def provision_e2e_executor(
    provisioning_client: Any,
    site_admin_client: Any,
    *,
    host: str,
    resource_id: str,
    attributes: dict[str, Any],
    pool_id: str,
    sellable_units: int | None,
    listing_mode: str = "specific_resource",
    deliverable_modes: tuple[str, ...] = ("vm",),
    listing_shapes: dict[str, list[dict[str, Any]]] | None = None,
    capacity: dict[str, int] | None = None,
    pricing: dict[str, Any] | None = None,
    region: str | None = None,
    connection: ConnectionSubmission | None = None,
) -> Any:
    """Pool, executor host, and its one capacity declaration, in dependency order.

    `listing_shapes`, `pricing`, `region`, and `capacity` are passed to the pool
    and the declaration; see `register_e2e_pool` and `declare_e2e_capacity`.
    `connection` is the host's; see `register_e2e_host`.

    `sellable_units` is what the declaration offers and must match the scenario's
    seeded resource: declaring more than its listing sells leaves units
    available after the reserve, so a slice listing never closes. `None` declares
    a machine without GPUs; see `declare_e2e_capacity`.

    The pool must exist before a host can join it, and the host before a
    declaration correlates to it. Most scenarios want exactly this sequence once,
    so they call this rather than the three helpers individually.
    """
    register_e2e_pool(
        provisioning_client,
        pool_id=pool_id,
        listing_mode=listing_mode,
        deliverable_modes=deliverable_modes,
        listing_shapes=listing_shapes,
        pricing=pricing,
        region=region,
    )
    host_row = register_e2e_host(
        provisioning_client, name=host, pool_id=pool_id, connection=connection
    )
    declare_e2e_capacity(
        site_admin_client,
        resource_id=resource_id,
        host_id=host,
        attributes=attributes,
        pool_id=pool_id,
        sellable_units=sellable_units,
        capacity=capacity,
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
