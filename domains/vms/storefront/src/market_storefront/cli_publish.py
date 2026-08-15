"""Top-level `market-storefront publish` command.

The seller's counterpart to `market buy`. Wraps the seller's start-of-day
flow behind a single command:

  1. (optional) Import a CSV of compute resources into the agent DB.
  2. Read the DB for `state='available'` compute rows.
  3. POST /listings/create on the agent, once per resource, offering the
     compute and demanding the configured token amount.
  4. Print a table of published orders.

`--watch` extends (3) into a loop: periodically re-scan the DB and
publish orders for resources that are `available` and don't already
have an open order. Runs until Ctrl-C. Safe because the resource poller
force-frees stale leases after the configured grace window.

Assumes the seller agent is already running (mirror of `market buy`).
"""

from __future__ import annotations
import asyncio

import json
import logging
import sqlite3
import subprocess
import time
from datetime import datetime
from pathlib import Path
from typing import Annotated, Any

import typer
from arkhai_vms.storefront_adapter import (
    vm_candidate_skip_keys,
    vm_offer_resource_for_listing,
)
from core_storefront.publication_command import (
    StorefrontPublicationCommandCallbacks,
    StorefrontPublicationCommandConfig,
    run_storefront_publication_command,
)
from core_storefront.publication_runner import (
    PublicationCommandResult,
    PublicationSourceSelection,
)
from core_storefront.publication_sources import PublicationSource
from domains.vms.listings.pricing_resolution import GpuPricingFields
from domains.vms.listings.reconciler import (
    PoolHintResolutionSettings,
    available_compute_slices,
    load_derived_listing_for_slice,
    mark_derived_listings_closed,
    open_listing_resource_keys,
    reopen_local_derived_listing,
    stale_open_listing_ids,
)
from market_identity import TrustedIdentitySet
from market_settlement_runtime import (
    SettlementPublicationClause,
    compile_settlement_publication_clause,
)
from registry_client import (
    ListingRequest,
    SyncRegistryClient,
    UpdateListingRequest,
)
from rich import box
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from storefront_client import (
    StorefrontClientError,
    SyncStorefrontClient,
)

from .publication_binding import record_vm_listing_binding
from .cli_common import _resolve_db_path, resolve_storefront_url
from .publication_wiring import (
    BareMetalPublicationSourceCallbacks,
    VmPublicationSourceCallbacks,
    build_bare_metal_publication_source_kwargs,
    build_bare_metal_storefront_publication_selection,
    build_storefront_publication_selection,
    build_vm_publication_source_kwargs,
)

# ``utils.config`` initializes process-global Dynaconf state from the operator
# TOML. Command helpers import it only when executing so importing this module
# for help, pure payload construction, or tests does not read operator config.

logger = logging.getLogger(__name__)


def _normalize_max_duration_seconds(value: Any) -> int | None:
    """Return a positive lease-duration ceiling, or None for unlimited."""
    if value is None:
        return None
    if isinstance(value, str) and not value.strip():
        return None
    seconds = int(value)
    return seconds if seconds > 0 else None


def _import_csv(csv_path: str, db: str | None) -> None:
    """Invoke the existing import_resources_csv.py script directly.

    Uses ``sys.executable`` (the python running this CLI) and locates
    the script relative to this package — works in both dev checkouts
    (``domains/vms/storefront/scripts/...``) and the container runtime
    (``/app/scripts/...``).
    """
    import sys

    package_root = Path(__file__).resolve().parents[2]
    script = package_root / "scripts" / "import_resources_csv.py"
    if not script.exists():
        raise typer.BadParameter(
            f"import_resources_csv.py not found at {script}. "
            "This shouldn't happen with a normal install — file a bug."
        )
    cmd = [
        sys.executable,
        str(script),
        "--csv",
        str(Path(csv_path).resolve()),
    ]
    if db:
        cmd.extend(["--db-path", str(Path(db).resolve())])
    subprocess.run(cmd, cwd=str(package_root), check=True)


def _site_topology_sync() -> tuple[str | None, int]:
    """(home_site, configured_site_count) as of right now, for CLI flows.

    Computed directly from configuration (no network call needed for
    just the site names/count) -- fresh on every call, never cached,
    since the count is load-bearing for whether an unmapped listing's
    site may be defaulted or must be left ambiguous.
    """
    from market_storefront.services.capacity_client import _capacity_settings

    try:
        sites, _ = _capacity_settings()
    except Exception:
        return None, 0
    return next(iter(sites), None), len(sites)


def _capacity_snapshot_sync() -> list[dict[str, Any]] | None:
    """Aggregated site capacity snapshot, fetched synchronously for CLI flows."""
    import asyncio

    from market_site_client import SiteCapacityClient

    from market_storefront.services.capacity_client import _capacity_settings
    from market_storefront.utils.config import (
        get_provisioning_authorities,
        resolve_marketplace_signer,
    )

    try:
        sites, _ = _capacity_settings()
        signer = resolve_marketplace_signer()
        expected_authorities = get_provisioning_authorities()
    except Exception:
        return None
    resources: list[dict[str, Any]] = []
    answered = False
    home_site = next(iter(sites))
    for site_name, url in sites.items():
        try:
            rows = asyncio.run(
                SiteCapacityClient(
                    url,
                    signer,
                    expected_authorities,
                    timeout=10,
                ).snapshot()
            )
        except Exception as exc:
            typer.echo(
                f"[capacity] site {site_name!r} snapshot failed: {exc}",
                err=True,
            )
            continue
        answered = True
        for row in rows:
            item = dict(row)
            item.setdefault("site", site_name)
            if site_name == home_site:
                item.setdefault("home_site", True)
            resources.append(item)
    return resources if answered else None


def _site_pool_projection_sync() -> dict[str, list[dict[str, Any]]] | None:
    """Resource-pool projection per site, fetched synchronously for CLI
    flows -- the CLI has no long-running poller (unlike the storefront
    server's ``site_projection_cache``), so it fetches its own fresh copy
    once per invocation rather than reading a cache that was never
    populated in this process. No caching by design: the CLI isn't meant
    to operate at the storefront server's scale.
    """
    import asyncio

    from market_site_client import SiteCapacityClient

    from market_storefront.services.capacity_client import _capacity_settings
    from market_storefront.utils.config import (
        get_provisioning_authorities,
        resolve_marketplace_signer,
    )

    try:
        sites, _ = _capacity_settings()
        signer = resolve_marketplace_signer()
        expected_authorities = get_provisioning_authorities()
    except Exception:
        return None
    projection: dict[str, list[dict[str, Any]]] = {}
    for site_name, url in sites.items():
        try:
            payload = asyncio.run(
                SiteCapacityClient(
                    url,
                    signer,
                    expected_authorities,
                    timeout=10,
                ).resource_pool_projection()
            )
            rows = payload.get("resource_pools") or []
        except Exception as exc:
            typer.echo(
                f"[capacity] site {site_name!r} projection fetch failed: {exc}",
                err=True,
            )
            continue
        projection[site_name] = rows
    return projection or None


def _site_capacity_buckets_sync() -> dict[str, list[dict[str, Any]]] | None:
    """Grouped capacity-bucket projection per site, fetched synchronously
    for CLI flows -- same no-caching rationale as ``_site_pool_projection_sync``
    (above), used only to source a fungible pool's per-member availability
    ceiling (``reconciler._projected_pool_rows``); an unusable/absent
    fetch here falls back to that function's own resource-list computation
    rather than failing the publish round.
    """
    import asyncio

    from market_site_client import SiteCapacityClient

    from market_storefront.services.capacity_client import _capacity_settings
    from market_storefront.utils.config import (
        get_provisioning_authorities,
        resolve_marketplace_signer,
    )

    try:
        sites, _ = _capacity_settings()
        signer = resolve_marketplace_signer()
        expected_authorities = get_provisioning_authorities()
    except Exception:
        return None
    buckets: dict[str, list[dict[str, Any]]] = {}
    for site_name, url in sites.items():
        try:
            payload = asyncio.run(
                SiteCapacityClient(
                    url,
                    signer,
                    expected_authorities,
                    timeout=10,
                ).capacity_bucket_projection()
            )
            rows = payload.get("capacity_buckets") or []
        except Exception as exc:
            typer.echo(
                f"[capacity] site {site_name!r} capacity-bucket fetch failed: {exc}",
                err=True,
            )
            continue
        buckets[site_name] = rows
    return buckets or None


def _member_availability_sync() -> dict[tuple[str, str], int]:
    """Fetch exact site/resource availability for CLI publication."""
    snapshot = _capacity_snapshot_sync()
    if snapshot is None:
        return {}
    view: dict[tuple[str, str], int] = {}
    for row in snapshot:
        resource_id = row.get("resource_id")
        site = row.get("site")
        available = row.get("available_units")
        if (
            not isinstance(site, str)
            or not site.strip()
            or not isinstance(resource_id, str)
            or not resource_id.strip()
            or available is None
        ):
            continue
        view[(site, resource_id)] = max(int(available), 0)
    return view


def _pool_hint_resolution_settings(
    command_settlements: tuple[SettlementPublicationClause, ...] | None = None,
) -> Any:
    """Build pool-hint policy with whole-list settlement precedence."""
    from market_storefront.utils.config import (
        settings,
        settlement_publication_defaults,
    )

    pricing = getattr(settings, "pricing", None)
    selected_settlements = (
        command_settlements
        if command_settlements is not None
        else settlement_publication_defaults()
    )
    command_settlement_values = (
        [
            clause.model_dump(mode="json", exclude_defaults=True)
            for clause in command_settlements
        ]
        if command_settlements is not None
        else None
    )
    flat_default = GpuPricingFields(
        min_price=(getattr(pricing, "default_min_price", "") or None),
        token=(getattr(pricing, "default_token_address", "") or None),
        max_duration_seconds=(
            getattr(pricing, "default_max_duration_seconds", 0) or None
        ),
        accepted_escrows=None,
        settlements=[
            clause.model_dump(mode="json", exclude_defaults=True)
            for clause in selected_settlements
        ],
    )

    defaults_by_model: dict[str, GpuPricingFields] = {}
    gpu_defaults = getattr(getattr(pricing, "defaults", None), "gpu", None)
    if gpu_defaults:
        for model, fields in dict(gpu_defaults).items():
            fields = fields or {}
            defaults_by_model[str(model)] = GpuPricingFields(
                min_price=fields.get("min_price"),
                token=fields.get("token"),
                max_duration_seconds=fields.get("max_duration_seconds"),
                accepted_escrows=fields.get("accepted_escrows"),
                settlements=(
                    command_settlement_values
                    if command_settlement_values is not None
                    else fields.get("settlements")
                ),
            )

    return PoolHintResolutionSettings(
        accept_pool_declared_sla=bool(
            getattr(pricing, "accept_pool_declared_sla", False),
        ),
        default_sla=float(getattr(pricing, "default_sla", 0.0) or 0.0),
        gpu_pricing_defaults_by_model=defaults_by_model,
        gpu_pricing_flat_default=flat_default,
    )


def _available_resources(
    db_path: str,
    command_settlements: tuple[SettlementPublicationClause, ...] | None = None,
) -> list[dict]:
    home_site, _ = _site_topology_sync()
    if home_site is None:
        return []
    projection = _site_pool_projection_if_enabled()
    return available_compute_slices(
        db_path,
        home_site=home_site,
        member_availability=_member_availability_sync(),
        site_pool_projection=projection,
        site_capacity_buckets=(
            _site_capacity_buckets_sync() if projection is not None else None
        ),
        hint_resolution=_pool_hint_resolution_settings(command_settlements),
    )


def _site_pool_projection_if_enabled() -> dict[str, list[dict[str, Any]]] | None:
    """Same opt-in gate as the storefront server's own reconciliation
    subscriber (``capacity_client._reconcile_listings``) -- the CLI is
    also a caller of `available_compute_slices` and must not diverge
    from the server's parity-verification gate on its own.
    """
    from .utils.config import settings

    if not bool(
        getattr(
            getattr(settings, "capacity", None),
            "use_site_projection_for_listings",
            False,
        )
    ):
        return None
    return _site_pool_projection_sync()


def _open_listing_resource_keys(db_path: str) -> set[str]:
    home_site, configured_site_count = _site_topology_sync()
    if home_site is None:
        return set()
    return open_listing_resource_keys(
        db_path,
        home_site=home_site,
        configured_site_count=configured_site_count,
    )


def _stale_open_listing_ids(db_path: str) -> list[str]:
    home_site, configured_site_count = _site_topology_sync()
    if home_site is None:
        return []
    availability = _member_availability_sync()
    projection = _site_pool_projection_if_enabled()
    return stale_open_listing_ids(
        db_path,
        home_site=home_site,
        configured_site_count=configured_site_count,
        member_availability=availability,
        site_pool_projection=projection,
        site_capacity_buckets=(
            _site_capacity_buckets_sync() if projection is not None else None
        ),
    )


def _open_order_resource_ids(db_path: str) -> set[str]:
    """Return the set of resource_ids that currently have an open sell order.

    Used in `--watch` mode to avoid re-publishing a resource that's already
    offered on the market. Inspects the offer_resource JSON for each open
    order and extracts its `resource_id` field.
    """
    conn = sqlite3.connect(f"file:{db_path}?mode=ro&nolock=1", uri=True, timeout=5)
    try:
        rows = conn.execute(
            "SELECT offer_resource FROM listings WHERE status = 'open'",
        ).fetchall()
    finally:
        conn.close()

    covered: set[str] = set()
    for (raw,) in rows:
        if not raw:
            continue
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            continue
        rid = parsed.get("resource_id") if isinstance(parsed, dict) else None
        if rid:
            covered.add(rid)
    return covered


def _publish_offer(
    agent_url: str,
    offer: dict,
    accepted_escrows: list[dict],
    demands: list[dict],
    max_duration_seconds: int | None,
    *,
    settlements: list[dict[str, Any]] | None = None,
) -> dict:
    """POST /listings/create and return the callback response mapping."""
    from .utils.config import resolve_marketplace_signer

    signer = resolve_marketplace_signer()
    with SyncStorefrontClient(
        agent_url,
        signer=signer,
        caller_role="seller",
        expected_publishers=TrustedIdentitySet(identities=(signer.identity,)),
    ) as client:
        try:
            resp = client.create_listing(
                offer=offer,
                accepted_escrows=accepted_escrows,
                settlements=settlements,
                demands=demands,
                max_duration_seconds=max_duration_seconds,
            )
        except StorefrontClientError as exc:
            typer.secho(f"Storefront error: {exc}", err=True, fg=typer.colors.RED)
            raise typer.Exit(code=1) from exc
    return {
        "status": resp.status,
        "listing_id": resp.listing_id,
        "root_agent_response": resp.root_agent_response,
        **resp.extra,
    }


def _registry_auth_token(registry_url: str) -> str | None:
    from .utils.config import settings

    auth = getattr(settings.registry, "auth", None) or {}
    if isinstance(auth, dict):
        token = auth.get(registry_url) or auth.get(registry_url.rstrip("/"))
        return str(token) if token else None
    try:
        token = auth.get(registry_url) or auth.get(registry_url.rstrip("/"))
        return str(token) if token else None
    except Exception:
        return None


def _publish_existing_listing_to_registries(
    *,
    listing_id: str,
    offer: dict,
    accepted_escrows: list[dict],
    demands: list[dict],
    max_duration_seconds: int | None,
    storefront_url: str,
) -> dict:
    from market_config.registry_url import normalize_registry_url

    from .utils.config import (
        get_registry_authorities,
        resolve_marketplace_signer,
        settings,
    )

    signer = resolve_marketplace_signer()
    if not settings.enable_registry_discovery:
        return {"status": "disabled", "listing_id": listing_id}

    urls = list(settings.registry.urls)
    authorities = get_registry_authorities()
    errors: list[str] = []
    any_ok = False
    request = ListingRequest(
        listing_id=listing_id,
        offer=offer,
        accepted_escrows=accepted_escrows,
        demands=demands,
        max_duration_seconds=max_duration_seconds,
        storefront_url=storefront_url,
    )
    update = UpdateListingRequest(
        updates={
            "status": "open",
            "offer_resource": offer,
            "accepted_escrows": accepted_escrows,
            "demands": demands,
            "max_duration_seconds": max_duration_seconds,
        },
    )
    for url in urls:
        try:
            with SyncRegistryClient(
                url,
                timeout=settings.registry.discovery_timeout,
                api_key=_registry_auth_token(url),
                signer=signer,
                caller_role="seller",
                expected_registries=authorities[normalize_registry_url(url)].principals,
                registry_authority=authorities[normalize_registry_url(url)].authority,
            ) as client:
                client.publish_listing(request)
                client.update_listing(listing_id, update)
            any_ok = True
        except Exception as exc:
            errors.append(f"{url}: {exc}")
    if any_ok:
        return {"status": "published", "listing_id": listing_id}
    return {
        "status": "error",
        "listing_id": listing_id,
        "message": "; ".join(errors) or "registry publish failed",
    }


def _reopen_derived_listing_if_present(
    *,
    db_path: str,
    base_url: str,
    resource: dict,
    offer: dict,
    accepted_escrows: list[dict],
    demands: list[dict],
    max_duration_seconds: int | None,
) -> dict | None:
    derived = load_derived_listing_for_slice(
        db_path,
        site_id=str(resource["site_id"]),
        pool_id=str(resource["pool_id"]) if resource.get("pool_id") else None,
        resource_id=str(resource["resource_id"])
        if resource.get("resource_id")
        else None,
        gpu_count=int(resource["gpu_count"]),
    )
    if not derived or not derived.get("listing_id"):
        return None
    listing_id = str(derived["listing_id"])
    if derived.get("listing_status") == "open":
        return None

    from .utils.config import resolve_marketplace_signer

    signer = resolve_marketplace_signer()
    reopen_local_derived_listing(
        db_path,
        listing_id=listing_id,
        site_id=str(resource["site_id"]),
        pool_id=str(resource["pool_id"]) if resource.get("pool_id") else None,
        resource_id=str(resource["resource_id"])
        if resource.get("resource_id")
        else None,
        gpu_count=int(resource["gpu_count"]),
        offer_resource=offer,
        accepted_escrows=accepted_escrows,
        demands=demands,
        max_duration_seconds=max_duration_seconds,
        storefront_url=base_url,
        seller_principal=signer.identity,
    )
    return _publish_existing_listing_to_registries(
        listing_id=listing_id,
        offer=offer,
        accepted_escrows=accepted_escrows,
        demands=demands,
        max_duration_seconds=max_duration_seconds,
        storefront_url=base_url,
    )


def _open_listing_ids(db_path: str) -> list[str]:
    """Return every status='open' listing_id from the agent DB."""
    conn = sqlite3.connect(f"file:{db_path}?mode=ro&nolock=1", uri=True, timeout=5)
    try:
        rows = conn.execute(
            "SELECT listing_id FROM listings WHERE status = 'open' ORDER BY created_at",
        ).fetchall()
    finally:
        conn.close()
    return [r[0] for r in rows if r[0]]


def _close_order(
    agent_url: str,
    order_id: str,
) -> dict:
    """POST /api/v1/listings/{listing_id}/close; return the response as a dict."""
    from .utils.config import resolve_marketplace_signer

    signer = resolve_marketplace_signer()
    with SyncStorefrontClient(
        agent_url,
        signer=signer,
        caller_role="seller",
        expected_publishers=TrustedIdentitySet(identities=(signer.identity,)),
    ) as client:
        try:
            resp = client.close_listing(order_id)
        except StorefrontClientError as exc:
            typer.secho(f"Storefront error: {exc}", err=True, fg=typer.colors.RED)
            raise typer.Exit(code=1) from exc
    return {
        "status": resp.status,
        "root_agent_response": resp.root_agent_response,
        **resp.extra,
    }


def _close_stale_derived_listings(
    *,
    db_path: str,
    base_url: str,
) -> list[str]:
    home_site, configured_site_count = _site_topology_sync()
    closed_listing_ids: list[str] = []
    for listing_id in _stale_open_listing_ids(db_path):
        resp = _close_order(base_url, listing_id)
        if str(resp.get("status", "?")) in ("closed", "skipped", "queued"):
            closed_listing_ids.append(listing_id)
    if home_site is not None:
        mark_derived_listings_closed(
            db_path,
            closed_listing_ids,
            home_site=home_site,
            configured_site_count=configured_site_count,
        )
    return closed_listing_ids


def _vm_candidate_skip_keys(candidate: dict[str, Any]) -> set[str]:
    return vm_candidate_skip_keys(candidate)


def _record_published_vm_listing(
    db_path: str,
    candidate: dict[str, Any],
    listing_id: str,
) -> None:
    asyncio.run(
        record_vm_listing_binding(
            db_path=db_path,
            listing_id=listing_id,
            candidate=candidate,
        )
    )


def _reopen_vm_listing_if_present(
    db_path: str,
    base_url: str,
    candidate: dict[str, Any],
    offer: dict[str, Any],
    accepted_escrows: list[dict],
    demands: list[dict],
    max_duration_seconds: int | None,
) -> dict | None:
    return _reopen_derived_listing_if_present(
        db_path=db_path,
        base_url=base_url,
        resource=candidate,
        offer=offer,
        accepted_escrows=accepted_escrows,
        demands=demands,
        max_duration_seconds=max_duration_seconds,
    )


def _vm_publication_source_callbacks(
    command_settlements: tuple[SettlementPublicationClause, ...] | None = None,
) -> VmPublicationSourceCallbacks:
    return VmPublicationSourceCallbacks(
        open_keys=_open_listing_resource_keys,
        close_stale=lambda db_path, base_url: _close_stale_derived_listings(
            db_path=db_path,
            base_url=base_url,
        ),
        available_candidates=lambda db_path: _available_resources(
            db_path,
            command_settlements,
        ),
        offer_resource=_offer_resource_for_listing,
        record_published=_record_published_vm_listing,
        reopen_existing=_reopen_vm_listing_if_present,
    )


def _bare_metal_publication_source_callbacks() -> BareMetalPublicationSourceCallbacks:
    return BareMetalPublicationSourceCallbacks(
        capacity_snapshot=_capacity_snapshot_sync,
        close_listing=_close_order,
        publish_existing_listing=_publish_existing_listing_to_registries,
    )


def _publication_source_kwargs() -> dict[str, Any]:
    return build_vm_publication_source_kwargs(_vm_publication_source_callbacks())


def _bare_metal_publication_source_kwargs() -> dict[str, Any]:
    """Infrastructure callbacks for the bare-metal publication adapter."""
    return build_bare_metal_publication_source_kwargs(
        _bare_metal_publication_source_callbacks(),
    )


def _publication_source_selection(
    command_settlements: tuple[SettlementPublicationClause, ...] | None = None,
) -> PublicationSourceSelection:
    """Build all sources from the configured frozen contribution registry."""
    from market_storefront.utils.config import storefront_domain_registry

    return build_storefront_publication_selection(
        registry=storefront_domain_registry(),
        vm_callbacks=_vm_publication_source_callbacks(command_settlements),
        bare_metal_callbacks=_bare_metal_publication_source_callbacks(),
    )


def _bare_metal_publication_source_selection() -> PublicationSourceSelection:
    """Build the explicitly configured bare-metal-only registry selection."""
    from market_storefront.utils.config import storefront_domain_registry

    return build_bare_metal_storefront_publication_selection(
        storefront_domain_registry(),
        _bare_metal_publication_source_callbacks(),
    )


def _publication_adapters() -> tuple[PublicationSource, ...]:
    return _publication_source_selection().build_sources()


def _open_publication_keys(db_path: str) -> set[str]:
    return _publication_source_selection().open_keys(db_path)


def _recipient_demands_for_chains(
    chains: dict[str, Any],
    chain_names: set[str],
    recipient_address: str,
) -> list[dict[str, Any]]:
    from market_alkahest.alkahest import get_recipient_arbiter

    demands: list[dict[str, Any]] = []
    for name in sorted(chain_names):
        chain = chains.get(name)
        if chain is None:
            continue
        arbiter = get_recipient_arbiter(
            chain.name,
            config_path=chain.alkahest_address_config_path,
        )
        demands.append(
            {
                "chain_name": chain.name,
                "arbiter": arbiter.lower(),
                "demand_data": {"recipient": recipient_address.lower()},
            }
        )
    return demands


def _heartbeat_oracle_demands_for_chains(
    chains: dict[str, Any],
    chain_names: set[str],
    oracle_address: str,
) -> list[dict[str, Any]]:
    """Oracle-gated plan shape: TrustedOracleArbiter demands.

    Collection through these listings waits for the named third-party
    oracle to ``arbitrate()`` true. First instantiation of lifecycle
    work item I.5: the oracle is assumed to arbitrate true at end of
    lease unless a dispute is raised (manual for now; the buyer's
    signed heartbeats and the seller's persisted evidence inform
    dispute handling). A plan shape, not a code path: only the
    advertised demand changes; negotiation, materialization, and the
    claims engine all flow through the same codec registry.
    """
    from market_alkahest.alkahest import get_trusted_oracle_arbiter

    demands: list[dict[str, Any]] = []
    for name in sorted(chain_names):
        chain = chains.get(name)
        if chain is None:
            continue
        arbiter = get_trusted_oracle_arbiter(
            chain.name,
            config_path=chain.alkahest_address_config_path,
        )
        demands.append(
            {
                "chain_name": chain.name,
                "arbiter": arbiter.lower(),
                "demand_data": {"oracle": oracle_address.lower(), "data": "0x"},
            }
        )
    return demands


def _splitter_demands_for_chains(
    chains: dict[str, Any],
    chain_names: set[str],
    oracle_address: str,
) -> list[dict[str, Any]]:
    """Interruptible plan shape: splitter demands.

    The splitter demand identifies who may declare the eventual refund
    split. For the current VM spot MVP that can be the seller wallet;
    the split itself is applied later on-chain when an interruption
    occurs.
    """
    from market_alkahest.alkahest import get_erc20_splitter

    demands: list[dict[str, Any]] = []
    for name in sorted(chain_names):
        chain = chains.get(name)
        if chain is None:
            continue
        arbiter = get_erc20_splitter(
            chain.name,
            config_path=chain.alkahest_address_config_path,
        )
        demands.append(
            {
                "chain_name": chain.name,
                "arbiter": arbiter.lower(),
                "demand_data": {"oracle": oracle_address.lower(), "data": "0x"},
            }
        )
    return demands


def _demands_for_chains(
    chains: dict[str, Any],
    chain_names: set[str],
    wallet_address: str,
) -> list[dict[str, Any]]:
    """Published demand set per the seller's settlement posture."""
    from market_storefront.utils.config import settlement_config_mapping

    alkahest = settlement_config_mapping().get("alkahest", {})
    if not isinstance(alkahest, dict):
        alkahest = {}
    interruptible = bool(alkahest.get("interruptible", False))
    if alkahest.get("oracle_gated", False):
        if interruptible:
            raise ValueError(
                "Settlement.alkahest oracle and interruptible policies "
                "are mutually exclusive"
            )
        trusted = alkahest.get("trusted_oracle_addresses", [])
        oracle = str(trusted[0] if isinstance(trusted, list) and trusted else "")
        if not oracle:
            raise ValueError(
                "Settlement.alkahest.oracle_gated requires a trusted oracle"
            )
        if oracle.lower() == wallet_address.lower():
            raise ValueError(
                "Settlement.alkahest trusted oracle equals the storefront wallet"
            )
        return _heartbeat_oracle_demands_for_chains(chains, chain_names, oracle)
    if interruptible:
        trusted = alkahest.get("interruptible_oracle_addresses", [])
        oracle = str(trusted[0] if isinstance(trusted, list) and trusted else "")
        return _splitter_demands_for_chains(
            chains,
            chain_names,
            oracle or wallet_address,
        )
    return _recipient_demands_for_chains(chains, chain_names, wallet_address)


def _offer_resource_for_listing(res: dict[str, Any]) -> dict[str, Any]:
    from market_storefront.utils.config import settlement_config_mapping

    alkahest = settlement_config_mapping().get("alkahest", {})
    interruptible = isinstance(alkahest, dict) and bool(
        alkahest.get("interruptible", False)
    )
    offer = vm_offer_resource_for_listing(res, interruptible=interruptible)
    offer["virtualization_type"] = "vm"
    return offer


def _compile_publication_clauses(
    values: list[str] | list[dict[str, Any]],
) -> tuple[SettlementPublicationClause, ...]:
    from market_storefront.settlement_composition import (
        build_storefront_settlement_registry,
    )

    from .utils.config import settlement_config_mapping

    registry = build_storefront_settlement_registry()
    config = registry.resolve(settlement_config_mapping(), role="seller")
    return tuple(
        compile_settlement_publication_clause(
            value,
            registry=registry,
            config=config,
            role="seller",
        )
        for value in values
    )


def _demands_for_publication_clauses(
    clauses: tuple[SettlementPublicationClause, ...],
    *,
    wallet_address: str,
) -> list[dict[str, Any]]:
    chain_names = {
        str(clause.mechanism_input["chain"])
        for clause in clauses
        if clause.mechanism == "alkahest.v1"
        and isinstance(clause.mechanism_input.get("chain"), str)
    }
    if not chain_names:
        return []
    from .utils.config import CHAINS

    unknown = chain_names.difference(CHAINS)
    if unknown:
        raise ValueError(
            f"settlement clause references unknown chain {sorted(unknown)[0]!r}"
        )
    return _demands_for_chains(CHAINS, chain_names, wallet_address)


def _publish_command_round(
    *,
    db_path: str,
    base_url: str,
    wallet_address: str,
    default_max_duration_seconds: int | None,
    command_settlements: tuple[SettlementPublicationClause, ...] | None = None,
    skip_ids: set[str] | None = None,
    close_stale: bool = False,
    skip_open: bool = False,
) -> PublicationCommandResult:
    """Publish one listing per available slice from complete settlement clauses."""

    listing_clauses: dict[int, list[dict[str, Any]]] = {}

    def build_payload(
        adapter: PublicationSource,
        candidate: dict[str, Any],
        offer: dict[str, Any],
    ) -> tuple[list[dict], list[dict], int | None] | str:
        pricing_resource = adapter.pricing_resource(candidate, offer)
        raw_clauses = pricing_resource.get("settlements")
        if raw_clauses is None:
            from .utils.config import settlement_publication_defaults

            defaults = (
                command_settlements
                if command_settlements is not None
                else settlement_publication_defaults()
            )
            raw_clauses = [
                clause.model_dump(mode="json", exclude_defaults=True)
                for clause in defaults
            ]
        if not isinstance(raw_clauses, list) or not raw_clauses:
            return (
                "no settlement clauses (set a resource `settlements` array, "
                "repeat --settlement, or configure [pricing].settlements)"
            )
        try:
            clauses = _compile_publication_clauses(raw_clauses)
            demands = _demands_for_publication_clauses(
                clauses,
                wallet_address=wallet_address,
            )
        except (TypeError, ValueError) as exc:
            return str(exc)
        listing_clauses[id(offer)] = [
            clause.model_dump(mode="json", exclude_defaults=True) for clause in clauses
        ]
        raw_max_duration = (
            pricing_resource.get("max_duration_seconds")
            if pricing_resource.get("max_duration_seconds") is not None
            else default_max_duration_seconds
        )
        return [], demands, _normalize_max_duration_seconds(raw_max_duration)

    def publish_offer(
        offer: dict[str, Any],
        accepted_escrows: list[dict],
        demands: list[dict],
        max_duration_seconds: int | None,
    ) -> dict[str, Any]:
        try:
            return _publish_offer(
                base_url,
                offer,
                accepted_escrows,
                demands,
                max_duration_seconds,
                settlements=listing_clauses.pop(id(offer), None),
            )
        except typer.Exit as exc:
            raise RuntimeError("HTTP error (see above)") from exc

    return run_storefront_publication_command(
        _publication_source_selection(command_settlements=command_settlements),
        config=StorefrontPublicationCommandConfig(
            db_path=db_path,
            base_url=base_url,
            close_stale=close_stale,
            skip_open=skip_open,
        ),
        callbacks=StorefrontPublicationCommandCallbacks(
            build_payload=build_payload,
            publish_offer=publish_offer,
        ),
        skip_ids=skip_ids,
    )


def run_watch_loop(
    *,
    db_path: str,
    base_url: str,
    wallet_address: str,
    default_max_duration_seconds: int | None,
    poll_interval: float,
    command_settlements: tuple[SettlementPublicationClause, ...] | None = None,
    console: Console | None = None,
    log_silent_cycles: bool = True,
) -> None:
    """Long-running publish loop. Used by `publish --watch` and by `serve`.

    Each cycle skips resources that already have an open listing and
    publishes the rest using resource clauses over command clauses over
    configured defaults. Sleeps ``poll_interval`` seconds between cycles.

    ``log_silent_cycles=False`` quiets cycles where nothing happened —
    useful when this is running as a background task inside `serve`
    where the user is also looking at HTTP request logs.
    """
    out_console = console or Console()
    total_published = 0
    total_failed = 0
    cycle = 0
    try:
        while True:
            cycle += 1
            try:
                result = _publish_command_round(
                    db_path=db_path,
                    base_url=base_url,
                    wallet_address=wallet_address,
                    default_max_duration_seconds=default_max_duration_seconds,
                    command_settlements=command_settlements,
                    close_stale=True,
                    skip_open=True,
                )
            except Exception as exc:
                ts = datetime.now().strftime("%H:%M:%S")
                out_console.print(
                    f"[dim]{ts}[/dim] cycle {cycle}: "
                    f"[red]error: {exc!r}[/red] (continuing after poll interval)"
                )
                time.sleep(poll_interval)
                continue

            total_published += result.published_count
            total_failed += result.failed_count

            ts = datetime.now().strftime("%H:%M:%S")
            if not result.no_new_listings:
                out_console.print(
                    f"[dim]{ts}[/dim] cycle {cycle}: "
                    f"[green]+{result.published_count}[/green] new"
                    + (
                        f" [red]/{result.failed_count} failed[/red]"
                        if result.has_failures
                        else ""
                    )
                    + (
                        f" [dim](skipped {result.skipped_count} already-open)[/dim]"
                        if result.skipped
                        else ""
                    )
                )
                _print_publish_table(out_console, result.published, result.failed)
            elif log_silent_cycles:
                available_count = len(
                    _available_resources(db_path, command_settlements)
                )
                out_console.print(
                    f"[dim]{ts}[/dim] cycle {cycle}: no new orders "
                    f"(available={available_count}, already-open={result.skipped_count})"
                )

            time.sleep(poll_interval)
    except KeyboardInterrupt:
        out_console.print(
            f"\n[yellow]Stopped.[/yellow] "
            f"Total cycles={cycle}, published={total_published}, failed={total_failed}."
        )


def _print_publish_table(
    console: Console, published: list[dict], failed: list[tuple[dict, str]]
) -> None:
    summary = Table(title="Published offers", box=box.SIMPLE_HEAVY, expand=True)
    summary.add_column("Resource", style="bold")
    summary.add_column("GPU")
    summary.add_column("Region")
    summary.add_column("Price/hr x Token")
    summary.add_column("Listing ID", overflow="fold")
    summary.add_column("Status")
    from market_core.schemas import accepted_token_address, primary_rate_value

    for entry in published:
        res = entry["resource"]
        resp = entry["response"]
        first_escrow = (entry["accepted_escrows"] or [{}])[0]
        price = primary_rate_value(first_escrow)
        token = accepted_token_address(first_escrow) or "-"
        offer = (
            res.get("offer_resource")
            if isinstance(res.get("offer_resource"), dict)
            else res
        )
        resource_label = (
            res.get("pool_id") or res.get("resource_id") or res.get("machine_id") or "-"
        )
        gpu_model = offer.get("gpu_model") or offer.get("capabilities", {}).get(
            "gpu_model"
        )
        gpu_count = offer.get("gpu_count")
        gpu_label = (
            f"{gpu_model} x{gpu_count}"
            if gpu_count is not None
            else str(gpu_model or offer.get("kind") or "-")
        )
        summary.add_row(
            str(resource_label),
            gpu_label,
            str(offer.get("region") or offer.get("site", {}).get("region") or "-"),
            f"{price if price is not None else 'hidden'} {token}",
            str(resp.get("listing_id", "-")),
            str(resp.get("status", "-")),
        )
    for res, reason in failed:
        offer = (
            res.get("offer_resource")
            if isinstance(res.get("offer_resource"), dict)
            else res
        )
        resource_label = (
            res.get("pool_id") or res.get("resource_id") or res.get("machine_id") or "-"
        )
        gpu_model = offer.get("gpu_model") or offer.get("capabilities", {}).get(
            "gpu_model"
        )
        gpu_count = offer.get("gpu_count")
        gpu_label = (
            f"{gpu_model} x{gpu_count}"
            if gpu_count is not None
            else str(gpu_model or offer.get("kind") or "-")
        )
        summary.add_row(
            str(resource_label),
            gpu_label,
            str(offer.get("region") or offer.get("site", {}).get("region") or "-"),
            "-",
            "-",
            f"[red]failed: {reason}[/red]",
        )
    console.print(summary)


def register(app: typer.Typer) -> None:
    """Register the top-level `market-storefront publish` command."""

    @app.command("publish")
    def provide(
        inventory: str | None = typer.Option(
            None,
            "--inventory",
            "-i",
            help="Path to a CSV resource inventory. Each row may provide a "
            "structured settlements JSON array that replaces command/config defaults.",
        ),
        settlement: Annotated[
            list[str] | None,
            typer.Option(
                "--settlement",
                help="Complete settlement publication clause. Repeat for ordered options; "
                "resource settlements replace this list, which replaces "
                "[pricing].settlements.",
            ),
        ] = None,
        abort_all: bool = typer.Option(
            False,
            "--abort-all",
            help="Close every open sell order on this agent instead of publishing. Useful on shutdown.",
        ),
        max_duration_seconds: int | None = typer.Option(
            None,
            "--max-duration-seconds",
            help="Override the per-listing max lease ceiling (seconds). "
            "Without this, each row uses its CSV column or "
            "[seller.pricing].default_max_duration_seconds (NULL = unlimited).",
        ),
        watch: bool = typer.Option(
            False,
            "--watch",
            "-w",
            help="Keep running: re-publish orders as resources free up. Ctrl-C to stop.",
        ),
        poll_interval: float = typer.Option(
            30.0,
            "--poll-interval",
            help="Seconds between scans in --watch mode.",
        ),
        storefront_url: str | None = typer.Option(
            None,
            "--storefront-url",
            "-a",
            help="Storefront base URL (default: base_url from storefront.toml).",
        ),
        db: str | None = typer.Option(
            None,
            "--db",
            help="Explicit storefront SQLite DB path "
            "(default: db_path from storefront.toml).",
        ),
    ) -> None:
        """Publish sell orders from typed settlement publication clauses.

        Whole-list precedence is resource `settlements`, then repeated
        `--settlement`, then `[pricing].settlements`. `min_price` remains a
        negotiation-policy floor and never constructs a settlement option.
        """
        console = Console()
        from .utils.config import (
            get_evm_wallet_address,
            settings,
            settlement_publication_defaults,
        )

        base_url = resolve_storefront_url(storefront_url, default_port=8001)
        wallet_address = get_evm_wallet_address()
        db_path = _resolve_db_path(db)
        try:
            command_settlements = (
                _compile_publication_clauses(settlement) if settlement else None
            )
            effective_defaults = (
                command_settlements
                if command_settlements is not None
                else settlement_publication_defaults()
            )
        except ValueError as exc:
            raise typer.BadParameter(str(exc), param_hint="--settlement") from exc
        if not db_path:
            typer.secho(
                "Could not resolve storefront DB. Pass --db or set "
                "db_path in storefront.toml.",
                err=True,
                fg=typer.colors.RED,
            )
            raise typer.Exit(1)

        default_max_duration_seconds = (
            max_duration_seconds
            if max_duration_seconds is not None
            else settings.pricing.default_max_duration_seconds
        )
        default_max_duration_seconds = _normalize_max_duration_seconds(
            default_max_duration_seconds
        )

        # Mode: abort-all is mutually exclusive with the publish flags.
        if abort_all:
            if inventory or watch or settlement:
                raise typer.BadParameter(
                    "--abort-all is mutually exclusive with --inventory, --watch, "
                    "and --settlement."
                )
            order_ids = _open_listing_ids(db_path)
            if not order_ids:
                console.print("[green]No open sell orders — nothing to abort.[/green]")
                return

            console.print(
                Panel(
                    f"[bold]Aborting {len(order_ids)} open order(s)[/bold]\n"
                    f"Agent: {base_url}",
                    title="market-storefront publish --abort-all",
                    border_style="yellow",
                )
            )
            closed_count = 0
            failed: list[tuple[str, str]] = []
            for oid in order_ids:
                try:
                    resp = _close_order(base_url, oid)
                except typer.Exit:
                    failed.append((oid, "HTTP error (see above)"))
                    continue
                except Exception as exc:
                    failed.append((oid, str(exc)))
                    continue
                status = str(resp.get("status", "?"))
                if status in ("closed", "skipped", "queued"):
                    closed_count += 1
                    console.print(f"  [green]✓[/green] {oid} → {status}")
                else:
                    failed.append((oid, resp.get("message") or status))
                    console.print(f"  [red]✗[/red] {oid} → {status}")

            console.print(
                f"\n[bold]Closed {closed_count}/{len(order_ids)} orders[/bold]"
                + (f" [red]({len(failed)} failed)[/red]" if failed else "")
            )
            if failed:
                raise typer.Exit(5)
            return

        if inventory:
            csv_file = Path(inventory)
            if not csv_file.exists():
                raise typer.BadParameter(f"Inventory file not found: {inventory}")
            console.print(f"[bold]Importing inventory:[/bold] {csv_file}")
            try:
                _import_csv(str(csv_file), db)
            except subprocess.CalledProcessError as exc:
                typer.secho(
                    f"Inventory import failed: {exc}", err=True, fg=typer.colors.RED
                )
                raise typer.Exit(2) from exc

        # ------------------------------------------------------------------
        # One-shot path
        # ------------------------------------------------------------------
        if not watch:
            result = _publish_command_round(
                db_path=db_path,
                base_url=base_url,
                wallet_address=wallet_address,
                default_max_duration_seconds=default_max_duration_seconds,
                command_settlements=command_settlements,
                skip_ids=_open_publication_keys(db_path),
                close_stale=True,
                skip_open=True,
            )
            if result.no_new_listings:
                console.print(
                    "[yellow]No available compute resources in the agent DB.[/yellow] "
                    "Pass --inventory <csv> or seed the DB first.",
                )
                raise typer.Exit(3)

            _print_publish_table(console, result.published, result.failed)
            totals = Table.grid(padding=(0, 2))
            totals.add_column(style="bold")
            totals.add_column()
            totals.add_row("Published", str(result.published_count))
            totals.add_row("Failed", str(result.failed_count))
            totals.add_row("Agent", base_url)
            totals.add_row("Settlement defaults", str(len(effective_defaults)))
            console.print(
                Panel(
                    totals,
                    title="Summary",
                    border_style="green" if not result.has_failures else "yellow",
                )
            )

            if result.has_failures and not result.has_publications:
                raise typer.Exit(4)
            return

        # ------------------------------------------------------------------
        # --watch loop
        # ------------------------------------------------------------------
        header = Table.grid(padding=(0, 2))
        header.add_column(style="bold")
        header.add_column()
        header.add_row("Agent", base_url)
        header.add_row("Settlement defaults", str(len(effective_defaults)))
        header.add_row("Poll interval", f"{poll_interval:.0f}s")
        header.add_row(
            "Default max duration",
            f"{default_max_duration_seconds}s"
            if default_max_duration_seconds
            else "unlimited",
        )
        console.print(
            Panel(
                header, title="market-storefront publish --watch", border_style="blue"
            )
        )
        console.print("[dim]Ctrl-C to stop.[/dim]\n")

        run_watch_loop(
            db_path=db_path,
            base_url=base_url,
            wallet_address=wallet_address,
            default_max_duration_seconds=default_max_duration_seconds,
            command_settlements=command_settlements,
            poll_interval=poll_interval,
            console=console,
        )
