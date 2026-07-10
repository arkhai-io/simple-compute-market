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

import json
import sqlite3
import subprocess
import time
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Optional

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich import box

from storefront_client import (
    StorefrontClientError,
    SyncStorefrontClient,
)
from registry_client import (
    ListingRequest,
    SyncRegistryClient,
    UpdateListingRequest,
)
from core_storefront.publication_command import (
    StorefrontPublicationCommandCallbacks,
    StorefrontPublicationCommandConfig,
    run_storefront_publication_command,
)
from core_storefront.publication_sources import PublicationSource
from core_storefront.publication_runner import (
    PublicationCommandResult,
    PublicationCycleResult,
    PublicationSourceSelection,
)

from .cli_common import REPO_ROOT, resolve_storefront_url, _resolve_db_path
from .publication_wiring import (
    BareMetalPublicationSourceCallbacks,
    VmPublicationSourceCallbacks,
    build_bare_metal_publication_source_kwargs,
    build_bare_metal_storefront_publication_selection,
    build_storefront_publication_selection,
    build_vm_publication_source_kwargs,
)
from domains.vms.listings.reconciler import (
    available_compute_slices,
    load_derived_listing_for_slice,
    mark_derived_listings_closed,
    open_listing_resource_keys,
    record_derived_listing,
    reopen_local_derived_listing,
    stale_open_listing_ids,
)
from arkhai_vms.storefront_adapter import (
    vm_candidate_skip_keys,
    vm_offer_resource_for_listing,
)


def _normalize_max_duration_seconds(value: Any) -> int | None:
    """Return a positive lease-duration ceiling, or None for unlimited."""
    if value is None:
        return None
    if isinstance(value, str) and not value.strip():
        return None
    seconds = int(value)
    return seconds if seconds > 0 else None


def _import_csv(csv_path: str, db: Optional[str]) -> None:
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
        sys.executable, str(script),
        "--csv", str(Path(csv_path).resolve()),
    ]
    if db:
        cmd.extend(["--db-path", str(Path(db).resolve())])
    subprocess.run(cmd, cwd=str(package_root), check=True)


def _capacity_snapshot_sync() -> list[dict[str, Any]] | None:
    """Aggregated site capacity snapshot, fetched synchronously for CLI flows."""
    import httpx

    from market_storefront.services.capacity_client import _capacity_settings

    try:
        sites, admin_key, _ = _capacity_settings()
    except Exception:
        return None
    headers = {"X-Admin-Key": admin_key} if admin_key else {}
    resources: list[dict[str, Any]] = []
    answered = False
    home_site = next(iter(sites))
    for site_name, url in sites.items():
        try:
            with httpx.Client(timeout=10) as http:
                resp = http.get(
                    f"{url}/api/v1/capacity/snapshot", headers=headers,
                )
                resp.raise_for_status()
                rows = resp.json().get("resources") or []
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


def _member_availability_sync() -> dict[tuple[str | None, str], int] | None:
    """Aggregated site availability, fetched synchronously for CLI flows.

    Keyed ``(site, resource_id)`` like ``member_availability_view``;
    ``None`` when no authority answers — publishing then assumes
    members are fully available and the reserve path corrects it.
    """
    snapshot = _capacity_snapshot_sync()
    if snapshot is None:
        return None
    view: dict[tuple[str | None, str], int] = {}
    home_site = next(
        (str(row.get("site")) for row in snapshot if row.get("home_site")),
        None,
    )
    for row in snapshot:
        resource_id = row.get("resource_id")
        available = row.get("available_units")
        if not resource_id or available is None:
            continue
        site = str(row.get("site")) if row.get("site") else None
        available = max(int(available), 0)
        if site is not None and site == home_site:
            view[(None, str(resource_id))] = available
        view[(site, str(resource_id))] = available
    return view


def _available_resources(db_path: str) -> list[dict]:
    return available_compute_slices(
        db_path, member_availability=_member_availability_sync(),
    )


def _open_listing_resource_keys(db_path: str) -> set[str]:
    return open_listing_resource_keys(db_path)


def _stale_open_listing_ids(db_path: str) -> list[str]:
    availability = _member_availability_sync()
    if availability is None:
        # No authority answered — closing on ignorance over-closes.
        return []
    return stale_open_listing_ids(db_path, member_availability=availability)


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
    wallet_address: str,
    private_key: Optional[str],
) -> dict:
    """POST /listings/create and return the response as a dict.

    Returns a dict (not the typed StorefrontListingCreateResponse) for
    backward compat with `_publish_round`'s callers, which inspect
    ``resp["listing_id"]`` and ``resp["status"]`` directly.
    """
    with SyncStorefrontClient(agent_url, private_key=private_key) as client:
        try:
            resp = client.create_listing(
                agent_wallet_address=wallet_address,
                offer=offer,
                accepted_escrows=accepted_escrows,
                demands=demands,
                max_duration_seconds=max_duration_seconds,
            )
        except StorefrontClientError as exc:
            typer.secho(f"Storefront error: {exc}", err=True, fg=typer.colors.RED)
            raise typer.Exit(code=1)
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
    private_key: Optional[str],
) -> dict:
    from .utils.config import settings

    if not settings.enable_registry_discovery:
        return {"status": "disabled", "listing_id": listing_id}
    if not private_key:
        raise RuntimeError("wallet.private_key is required to publish to registry")

    urls = list(settings.registry.urls) if settings.registry.urls else ["http://localhost:8080"]
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
        private_key=private_key,
    )
    for url in urls:
        try:
            with SyncRegistryClient(
                url,
                timeout=settings.registry.discovery_timeout,
                api_key=_registry_auth_token(url),
            ) as client:
                client.publish_listing(request, private_key)
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
    private_key: Optional[str],
) -> dict | None:
    derived = load_derived_listing_for_slice(
        db_path,
        pool_id=str(resource["pool_id"]) if resource.get("pool_id") else None,
        resource_id=str(resource["resource_id"]) if resource.get("resource_id") else None,
        gpu_count=int(resource["gpu_count"]),
    )
    if not derived or not derived.get("listing_id"):
        return None
    listing_id = str(derived["listing_id"])
    if derived.get("listing_status") == "open":
        return None

    reopen_local_derived_listing(
        db_path,
        listing_id=listing_id,
        pool_id=str(resource["pool_id"]) if resource.get("pool_id") else None,
        resource_id=str(resource["resource_id"]) if resource.get("resource_id") else None,
        gpu_count=int(resource["gpu_count"]),
        offer_resource=offer,
        accepted_escrows=accepted_escrows,
        demands=demands,
        max_duration_seconds=max_duration_seconds,
        seller=base_url,
    )
    return _publish_existing_listing_to_registries(
        listing_id=listing_id,
        offer=offer,
        accepted_escrows=accepted_escrows,
        demands=demands,
        max_duration_seconds=max_duration_seconds,
        storefront_url=base_url,
        private_key=private_key,
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
    private_key: Optional[str],
) -> dict:
    """POST /api/v1/listings/{listing_id}/close; return the response as a dict."""
    with SyncStorefrontClient(agent_url, private_key=private_key) as client:
        try:
            resp = client.close_listing(order_id)
        except StorefrontClientError as exc:
            typer.secho(f"Storefront error: {exc}", err=True, fg=typer.colors.RED)
            raise typer.Exit(code=1)
    return {
        "status": resp.status,
        "root_agent_response": resp.root_agent_response,
        **resp.extra,
    }


def _close_stale_derived_listings(
    *,
    db_path: str,
    base_url: str,
    private_key: Optional[str],
) -> list[str]:
    closed_listing_ids: list[str] = []
    for listing_id in _stale_open_listing_ids(db_path):
        resp = _close_order(base_url, listing_id, private_key)
        if str(resp.get("status", "?")) in ("closed", "skipped", "queued"):
            closed_listing_ids.append(listing_id)
    mark_derived_listings_closed(db_path, closed_listing_ids)
    return closed_listing_ids


def _vm_candidate_skip_keys(candidate: dict[str, Any]) -> set[str]:
    return vm_candidate_skip_keys(candidate)


def _record_published_vm_listing(
    db_path: str,
    candidate: dict[str, Any],
    listing_id: str,
) -> None:
    record_derived_listing(
        db_path,
        listing_id=listing_id,
        pool_id=str(candidate["pool_id"]) if candidate.get("pool_id") else None,
        resource_id=str(candidate["resource_id"]) if candidate.get("resource_id") else None,
        gpu_count=int(candidate["gpu_count"]),
    )


def _reopen_vm_listing_if_present(
    db_path: str,
    base_url: str,
    candidate: dict[str, Any],
    offer: dict[str, Any],
    accepted_escrows: list[dict],
    demands: list[dict],
    max_duration_seconds: int | None,
    private_key: Optional[str],
) -> dict | None:
    return _reopen_derived_listing_if_present(
        db_path=db_path,
        base_url=base_url,
        resource=candidate,
        offer=offer,
        accepted_escrows=accepted_escrows,
        demands=demands,
        max_duration_seconds=max_duration_seconds,
        private_key=private_key,
    )


def _vm_publication_source_callbacks() -> VmPublicationSourceCallbacks:
    return VmPublicationSourceCallbacks(
        open_keys=_open_listing_resource_keys,
        close_stale=lambda db_path, base_url, private_key: (
            _close_stale_derived_listings(
                db_path=db_path,
                base_url=base_url,
                private_key=private_key,
            )
        ),
        available_candidates=_available_resources,
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
    source_names: tuple[str, ...] = ("vms",),
) -> PublicationSourceSelection:
    """Storefront publication source selection.

    The legacy VM CLI still defaults to VM slice publication only. Passing
    selected source names lets the core composition helper build bare-metal or
    combined source selections without making the VM adapter own bare-metal
    semantics.
    """
    return build_storefront_publication_selection(
        source_names=source_names,
        vm_callbacks=_vm_publication_source_callbacks(),
        bare_metal_callbacks=_bare_metal_publication_source_callbacks(),
    )


def _bare_metal_publication_source_selection() -> PublicationSourceSelection:
    """Bare-metal-only publication selection for future composition roots."""
    return build_bare_metal_storefront_publication_selection(
        _bare_metal_publication_source_callbacks(),
    )


def _publication_adapters() -> tuple[PublicationSource, ...]:
    return _publication_source_selection().build_sources()


def _close_stale_publication_listings(
    *,
    db_path: str,
    base_url: str,
    private_key: Optional[str],
) -> dict[str, list[str]]:
    return _publication_source_selection().close_stale(
        db_path=db_path,
        base_url=base_url,
        private_key=private_key,
    )


def _open_publication_keys(db_path: str) -> set[str]:
    return _publication_source_selection().open_keys(db_path)


def _resolve_pricing(
    res: dict,
    *,
    default_min_price: Optional[str],
    default_token_address: Optional[str],
) -> tuple[Optional[str], Optional[str]]:
    """Pick the (min_price, token_address) for a resource: row > defaults > None.

    Returns (min_price, token_address). Both fall through to defaults
    when the row column is empty; ``"0"`` for min_price is honored as a
    real value (free offering) and does not trigger the fallback.

    The ``token`` column on the row must be a 0x ERC-20 address — symbol
    shorthand was removed in favour of chain-resolved metadata. The
    address itself is the canonical token identity; symbols are derived
    via ``market_alkahest.token.resolve_token``.
    """
    row_min_price = res.get("min_price")
    if row_min_price is None or row_min_price == "":
        min_price = default_min_price
    else:
        min_price = row_min_price
    token_address = (res.get("token") or default_token_address) or None
    return min_price, token_address


def _scale_template_entries(
    entries: list[dict[str, Any]],
    chains: dict[str, Any],
) -> list[dict[str, Any]]:
    """Scale template-materialized rate values to base units, in place.

    The CSV importer stores ``accepted_escrows`` entries with rate values
    as the raw human strings from the slot assignments (``"0.5"`` for
    half a USDC). At publish time we look up token decimals against the
    entry's chain and scale to a uint256-safe decimal-digit string.

    Raises ``ValueError`` (per entry) with a row-actionable message when
    the entry references an unknown chain or a token whose metadata
    can't be resolved on that chain.
    """
    from market_alkahest.token import resolve_token, TokenResolutionError

    scaled: list[dict[str, Any]] = []
    for raw_entry in entries:
        entry = dict(raw_entry)
        chain_name = entry.get("chain_name")
        if not chain_name or chain_name not in chains:
            raise ValueError(
                f"accepted_escrows entry references unknown chain "
                f"{chain_name!r}; configured: {sorted(chains)}"
            )
        chain = chains[chain_name]
        literal_fields = dict(entry.get("literal_fields") or {})
        token_address = literal_fields.get("token")
        if not isinstance(token_address, str) or not token_address:
            raise ValueError(
                f"accepted_escrows entry on chain {chain_name!r} is "
                f"missing literal_fields.token; cannot scale rates"
            )
        try:
            token_meta = resolve_token(
                token_address,
                rpc_url=chain.rpc_url,
                chain_id=chain.chain_id,
            )
        except TokenResolutionError as exc:
            raise ValueError(
                f"accepted_escrows: token {token_address} unresolvable on "
                f"chain {chain_name!r}: {exc}"
            ) from exc
        literal_fields["token"] = token_meta.contract_address.lower()
        decimals = token_meta.decimals

        new_rates: list[dict[str, Any]] = []
        for rate in entry.get("rates") or []:
            raw_value = rate.get("value")
            if raw_value is None or raw_value == "":
                raise ValueError(
                    f"accepted_escrows entry on chain {chain_name!r} "
                    f"has a rate with no value (field={rate.get('field')!r})"
                )
            try:
                human = Decimal(str(raw_value))
            except (InvalidOperation, ValueError, TypeError) as exc:
                raise ValueError(
                    f"accepted_escrows rate value {raw_value!r} on chain "
                    f"{chain_name!r} is not numeric"
                ) from exc
            base_units = human * (Decimal(10) ** decimals)
            if base_units != base_units.to_integral_value():
                raise ValueError(
                    f"accepted_escrows rate value {raw_value!r} on chain "
                    f"{chain_name!r} has more decimals than the token's "
                    f"{decimals}"
                )
            if base_units < 0:
                raise ValueError(
                    f"accepted_escrows rate value {raw_value!r} on chain "
                    f"{chain_name!r} is negative"
                )
            new_rates.append({
                "field": rate.get("field"),
                "per": rate.get("per"),
                "value": str(int(base_units)),
            })

        scaled.append({
            "chain_name": chain_name,
            "escrow_address": str(entry.get("escrow_address") or "").lower(),
            "literal_fields": literal_fields,
            "rates": new_rates,
        })
    return scaled


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
        demands.append({
            "chain_name": chain.name,
            "arbiter": arbiter.lower(),
            "demand_data": {"recipient": recipient_address.lower()},
        })
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
        demands.append({
            "chain_name": chain.name,
            "arbiter": arbiter.lower(),
            "demand_data": {"oracle": oracle_address.lower(), "data": "0x"},
        })
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
        demands.append({
            "chain_name": chain.name,
            "arbiter": arbiter.lower(),
            "demand_data": {"oracle": oracle_address.lower(), "data": "0x"},
        })
    return demands


def _demands_for_chains(
    chains: dict[str, Any],
    chain_names: set[str],
    wallet_address: str,
) -> list[dict[str, Any]]:
    """Published demand set per the seller's settlement posture."""
    from market_storefront.utils.config import settings

    interruptible = bool(getattr(settings, "interruptible_listings", False))
    if getattr(settings, "oracle_gated_listings", False):
        if interruptible:
            raise ValueError(
                "oracle_gated_listings and interruptible_listings are mutually "
                "exclusive settlement postures"
            )
        oracle = str(getattr(settings, "trusted_oracle_address", "") or "")
        if not oracle:
            raise ValueError(
                "oracle_gated_listings requires trusted_oracle_address — a "
                "third party both sides trust. The seller's own wallet is "
                "not a valid oracle: the party collecting cannot also be "
                "the party deciding collection."
            )
        if oracle.lower() == wallet_address.lower():
            raise ValueError(
                "trusted_oracle_address equals this storefront's wallet; "
                "a self-oracle gates nothing — name a third party."
            )
        return _heartbeat_oracle_demands_for_chains(chains, chain_names, oracle)
    if interruptible:
        oracle = str(getattr(settings, "interruptible_oracle_address", "") or "")
        return _splitter_demands_for_chains(
            chains, chain_names, oracle or wallet_address,
        )
    return _recipient_demands_for_chains(chains, chain_names, wallet_address)


def _offer_resource_for_listing(res: dict[str, Any]) -> dict[str, Any]:
    from market_storefront.utils.config import settings

    return vm_offer_resource_for_listing(
        res,
        interruptible=bool(getattr(settings, "interruptible_listings", False)),
    )


def _default_alkahest_payload(
    *,
    resource: dict[str, Any],
    default_min_price: Optional[str],
    default_token_address: Optional[str],
    default_max_duration_seconds: int | None,
    wallet_address: str,
    publish_priceless: bool,
) -> tuple[list[dict], list[dict], int | None] | str:
    template_entries = resource.get("accepted_escrows")
    if template_entries:
        from .utils.config import CHAINS
        if not CHAINS:
            return "no [chains.<name>] tables configured"
        try:
            accepted_escrows = _scale_template_entries(template_entries, CHAINS)
        except ValueError as exc:
            return str(exc)
        chain_names = {
            str(e.get("chain_name"))
            for e in accepted_escrows
            if isinstance(e, dict) and e.get("chain_name")
        }
        try:
            demands = _demands_for_chains(CHAINS, chain_names, wallet_address)
        except Exception as exc:
            return f"listing demands: {exc}"
        raw_max_duration_seconds = (
            resource.get("max_duration_seconds")
            if resource.get("max_duration_seconds") is not None
            else default_max_duration_seconds
        )
        max_duration_seconds = _normalize_max_duration_seconds(
            raw_max_duration_seconds
        )
        return accepted_escrows, demands, max_duration_seconds

    min_price, token_address = _resolve_pricing(
        resource,
        default_min_price=default_min_price,
        default_token_address=default_token_address,
    )
    if not token_address:
        return (
            "no token (set the CSV `token` column to a 0x ERC-20 address, "
            "or [seller.pricing].default_token_address in config.toml)"
        )
    if not token_address.startswith("0x") or len(token_address) != 42:
        return (
            f"invalid token {token_address!r} — must be a 0x ERC-20 address "
            f"(symbol shorthand is no longer supported)"
        )
    from market_alkahest.token import resolve_token, TokenResolutionError
    from .utils.config import CHAINS
    if not CHAINS:
        return "no [chains.<name>] tables configured"
    token_meta = None
    token_resolve_errors: list[str] = []
    for chain in CHAINS.values():
        try:
            token_meta = resolve_token(
                token_address, rpc_url=chain.rpc_url, chain_id=chain.chain_id,
            )
            break
        except TokenResolutionError as exc:
            token_resolve_errors.append(f"{chain.name}: {exc}")
            continue
    if token_meta is None:
        return (
            f"chain resolve failed for {token_address}: "
            + "; ".join(token_resolve_errors)
        )
    token_address = token_meta.contract_address.lower()
    token_decimals = token_meta.decimals

    if min_price is None:
        if not publish_priceless:
            return (
                "no min_price (set per-row in CSV or [seller.pricing].default_min_price, "
                "or set [seller.pricing].publish_priceless=true to advertise as hidden-reserve)"
            )
        advertised_amount: Any = None
    else:
        try:
            human = Decimal(str(min_price))
        except (InvalidOperation, ValueError, TypeError):
            return f"unparseable min_price={min_price!r}; expected numeric string"
        scaled = human * (Decimal(10) ** token_decimals)
        if scaled != scaled.to_integral_value():
            return (
                f"min_price={min_price!r} has more decimals than the "
                f"token's {token_decimals}"
            )
        if scaled < 0:
            return f"min_price={min_price!r} is negative"
        advertised_amount = str(int(scaled))

    raw_max_duration_seconds = (
        resource.get("max_duration_seconds")
        if resource.get("max_duration_seconds") is not None
        else default_max_duration_seconds
    )
    max_duration_seconds = _normalize_max_duration_seconds(
        raw_max_duration_seconds
    )
    from market_alkahest.alkahest import get_erc20_escrow_obligation_default
    accepted_escrows: list[dict] = []
    per_chain_errors: list[str] = []
    for chain in CHAINS.values():
        try:
            escrow_address = get_erc20_escrow_obligation_default(
                chain.name,
                config_path=chain.alkahest_address_config_path,
            )
        except Exception as exc:
            per_chain_errors.append(f"{chain.name}: {exc}")
            continue
        accepted_escrows.append({
            "chain_name": chain.name,
            "escrow_address": escrow_address.lower(),
            "literal_fields": {"token": token_address},
            "rates": [{
                "field": "amount",
                "per": "hour",
                "value": advertised_amount,
            }] if advertised_amount is not None else [],
        })
    if not accepted_escrows:
        return (
            "alkahest config could not resolve ERC20 escrow address on any "
            f"configured chain: {'; '.join(per_chain_errors)}"
        )
    chain_names = {
        str(e.get("chain_name"))
        for e in accepted_escrows
        if isinstance(e, dict) and e.get("chain_name")
    }
    try:
        demands = _demands_for_chains(CHAINS, chain_names, wallet_address)
    except Exception as exc:
        return f"listing demands: {exc}"
    return accepted_escrows, demands, max_duration_seconds


def _alkahest_payload_for_candidate(
    *,
    pricing_resource: dict[str, Any],
    default_min_price: Optional[str],
    default_token_address: Optional[str],
    default_max_duration_seconds: int | None,
    wallet_address: str,
    publish_priceless: bool,
) -> tuple[list[dict], list[dict], int | None] | str:
    return _default_alkahest_payload(
        resource=pricing_resource,
        default_min_price=default_min_price,
        default_token_address=default_token_address,
        default_max_duration_seconds=default_max_duration_seconds,
        wallet_address=wallet_address,
        publish_priceless=publish_priceless,
    )


def _publish_command_round(
    *,
    db_path: str,
    base_url: str,
    wallet_address: str,
    private_key: Optional[str],
    default_min_price: Optional[str],
    default_token_address: Optional[str],
    default_max_duration_seconds: int | None,
    rpc_url: str,
    chain_id: int,
    publish_priceless: bool = False,
    skip_ids: set[str] | None = None,
    close_stale: bool = False,
    skip_open: bool = False,
) -> PublicationCommandResult:
    """Publish one listing for every priced available resource slice.

    Pricing is per-row: ``resources.min_price`` / ``resources.token`` win
    over the [seller.pricing] defaults. Tristate publish behaviour:

      * Row ``min_price > 0``  → publish with a single amount/hour rate
        (public price).
      * Row ``min_price = "0"`` → publish with the rate value ``"0"``
        (free / public-test offering; explicit per-row, defaults don't
        override).
      * Row ``min_price`` unset and no default → controlled by
        ``publish_priceless``:
          - True  → publish with ``rates = []`` (hidden reserve;
            buyer proposes; seller's strategy uses
            ``[seller.pricing].default_min_price`` as the negotiation floor).
          - False → skip the row, surfaced in ``failed``.

    Returns (published, failed, skipped) — each a list of dicts keyed on
    the resource.
    """
    def build_payload(
        adapter: PublicationSource,
        candidate: dict[str, Any],
        offer: dict[str, Any],
    ) -> tuple[list[dict], list[dict], int | None] | str:
        return _alkahest_payload_for_candidate(
            pricing_resource=adapter.pricing_resource(candidate, offer),
            default_min_price=default_min_price,
            default_token_address=default_token_address,
            default_max_duration_seconds=default_max_duration_seconds,
            wallet_address=wallet_address,
            publish_priceless=publish_priceless,
        )

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
                wallet_address,
                private_key,
            )
        except typer.Exit as exc:
            raise RuntimeError("HTTP error (see above)") from exc

    return run_storefront_publication_command(
        _publication_source_selection(),
        config=StorefrontPublicationCommandConfig(
            db_path=db_path,
            base_url=base_url,
            private_key=private_key,
            close_stale=close_stale,
            skip_open=skip_open,
        ),
        callbacks=StorefrontPublicationCommandCallbacks(
            build_payload=build_payload,
            publish_offer=publish_offer,
        ),
        skip_ids=skip_ids,
    )


def _publish_round(
    **kwargs: Any,
) -> tuple[list[dict], list[tuple[dict, str]], list[dict]]:
    """Compatibility wrapper returning the legacy publish-round tuple."""
    result = _publish_command_round(**kwargs)
    return result.published, result.failed, result.skipped


def run_watch_loop(
    *,
    db_path: str,
    base_url: str,
    wallet_address: str,
    private_key: Optional[str],
    default_min_price: Optional[str],
    default_token_address: Optional[str],
    default_max_duration_seconds: int | None,
    rpc_url: str,
    chain_id: int,
    publish_priceless: bool = False,
    poll_interval: float,
    console: Optional[Console] = None,
    log_silent_cycles: bool = True,
) -> None:
    """Long-running publish loop. Used by `publish --watch` and by `serve`.

    Each cycle: skip resources that already have an open listing, try to
    publish the rest (per-row pricing > config defaults). Sleeps
    ``poll_interval`` seconds between cycles. Exits on KeyboardInterrupt.

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
                    db_path=db_path, base_url=base_url,
                    wallet_address=wallet_address, private_key=private_key,
                    default_min_price=default_min_price,
                    default_token_address=default_token_address,
                    default_max_duration_seconds=default_max_duration_seconds,
                    rpc_url=rpc_url, chain_id=chain_id,
                    publish_priceless=publish_priceless,
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
                    + (f" [red]/{result.failed_count} failed[/red]" if result.has_failures else "")
                    + (f" [dim](skipped {result.skipped_count} already-open)[/dim]" if result.skipped else "")
                )
                _print_publish_table(out_console, result.published, result.failed)
            elif log_silent_cycles:
                available_count = len(_available_resources(db_path))
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


def _print_publish_table(console: Console, published: list[dict], failed: list[tuple[dict, str]]) -> None:
    summary = Table(title="Published offers", box=box.SIMPLE_HEAVY, expand=True)
    summary.add_column("Resource", style="bold")
    summary.add_column("GPU")
    summary.add_column("Region")
    summary.add_column("Price/hr × Token")
    summary.add_column("Listing ID", overflow="fold")
    summary.add_column("Status")
    from market_core.schemas import accepted_token_address, primary_rate_value
    for entry in published:
        res = entry["resource"]
        resp = entry["response"]
        first_escrow = (entry["accepted_escrows"] or [{}])[0]
        price = primary_rate_value(first_escrow)
        token = accepted_token_address(first_escrow) or "-"
        offer = res.get("offer_resource") if isinstance(res.get("offer_resource"), dict) else res
        resource_label = (
            res.get("pool_id")
            or res.get("resource_id")
            or res.get("machine_id")
            or "-"
        )
        gpu_model = offer.get("gpu_model") or offer.get("capabilities", {}).get("gpu_model")
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
        offer = res.get("offer_resource") if isinstance(res.get("offer_resource"), dict) else res
        resource_label = (
            res.get("pool_id")
            or res.get("resource_id")
            or res.get("machine_id")
            or "-"
        )
        gpu_model = offer.get("gpu_model") or offer.get("capabilities", {}).get("gpu_model")
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
        inventory: Optional[str] = typer.Option(
            None, "--inventory", "-i",
            help="Path to a CSV file describing compute resources to import before publishing. "
                 "Each row may set min_price and token columns; otherwise [seller.pricing] defaults apply.",
        ),
        abort_all: bool = typer.Option(
            False, "--abort-all",
            help="Close every open sell order on this agent instead of publishing. Useful on shutdown.",
        ),
        max_duration_seconds: Optional[int] = typer.Option(
            None, "--max-duration-seconds",
            help="Override the per-listing max lease ceiling (seconds). "
                 "Without this, each row uses its CSV column or "
                 "[seller.pricing].default_max_duration_seconds (NULL = unlimited).",
        ),
        watch: bool = typer.Option(
            False, "--watch", "-w",
            help="Keep running: re-publish orders as resources free up. Ctrl-C to stop.",
        ),
        poll_interval: float = typer.Option(
            30.0, "--poll-interval",
            help="Seconds between scans in --watch mode.",
        ),
        storefront_url: Optional[str] = typer.Option(
            None, "--storefront-url", "-a",
            help="Storefront base URL (default: base_url from storefront.toml).",
        ),
        db: Optional[str] = typer.Option(
            None, "--db",
            help="Explicit storefront SQLite DB path "
                 "(default: db_path from storefront.toml).",
        ),
    ) -> None:
        """Publish sell orders for every priced compute resource on the storefront.

        Pricing is per-resource: each row's `min_price` / `token` columns
        win over the [pricing] defaults. Resources without either a
        row-level price or a default are skipped (reported as failed).
        """
        console = Console()
        from .utils.config import settings

        base_url = resolve_storefront_url(storefront_url, default_port=8001)
        private_key = settings.wallet.private_key
        wallet_address = settings.wallet.address or ""
        db_path = _resolve_db_path(db)
        if not db_path:
            typer.secho(
                "Could not resolve storefront DB. Pass --db or set "
                "db_path in storefront.toml.",
                err=True, fg=typer.colors.RED,
            )
            raise typer.Exit(1)

        default_min_price = settings.pricing.default_min_price
        default_token_address = settings.pricing.default_token_address
        default_max_duration_seconds = (
            max_duration_seconds
            if max_duration_seconds is not None
            else settings.pricing.default_max_duration_seconds
        )
        default_max_duration_seconds = _normalize_max_duration_seconds(
            default_max_duration_seconds
        )

        from .utils.config import CHAINS
        if not CHAINS:
            typer.secho(
                "No [chains.<name>] tables configured — required to resolve "
                "ERC-20 token metadata on chain. Add at least one chain "
                "entry to storefront.toml.",
                err=True, fg=typer.colors.RED,
            )
            raise typer.Exit(1)
        # The publish loop iterates CHAINS internally; rpc_url / chain_id
        # are kept on the watch-loop signature for back-compat but use the
        # first configured chain as a generic resolution target. Per-chain
        # token resolution happens inside _publish_round.
        first_chain = next(iter(CHAINS.values()))
        rpc_url = first_chain.rpc_url
        chain_id = first_chain.chain_id

        # Mode: abort-all is mutually exclusive with the publish flags.
        if abort_all:
            if inventory or watch:
                raise typer.BadParameter(
                    "--abort-all is mutually exclusive with --inventory and --watch."
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
                    resp = _close_order(base_url, oid, private_key)
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
                typer.secho(f"Inventory import failed: {exc}", err=True, fg=typer.colors.RED)
                raise typer.Exit(2)

        # ------------------------------------------------------------------
        # One-shot path
        # ------------------------------------------------------------------
        if not watch:
            published, failed, skipped = _publish_round(
                db_path=db_path, base_url=base_url,
                wallet_address=wallet_address, private_key=private_key,
                default_min_price=default_min_price,
                default_token_address=default_token_address,
                default_max_duration_seconds=default_max_duration_seconds,
                rpc_url=rpc_url, chain_id=chain_id,
                publish_priceless=settings.pricing.publish_priceless,
                skip_ids=_open_publication_keys(db_path),
                close_stale=True,
                skip_open=True,
            )
            result = PublicationCommandResult(
                PublicationCycleResult(
                    closed={},
                    published=published,
                    failed=failed,
                    skipped=skipped,
                ),
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
            totals.add_row(
                "Default price",
                f"{default_min_price or '-'} {default_token_address or '(per-row required)'}",
            )
            console.print(Panel(totals, title="Summary", border_style="green" if not result.has_failures else "yellow"))

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
        header.add_row(
            "Default price",
            f"{default_min_price or '-'} {default_token_address or '(per-row required)'}",
        )
        header.add_row("Poll interval", f"{poll_interval:.0f}s")
        header.add_row(
            "Default max duration",
            f"{default_max_duration_seconds}s" if default_max_duration_seconds else "unlimited",
        )
        console.print(Panel(header, title="market-storefront publish --watch", border_style="blue"))
        console.print("[dim]Ctrl-C to stop.[/dim]\n")

        run_watch_loop(
            db_path=db_path, base_url=base_url,
            wallet_address=wallet_address, private_key=private_key,
            default_min_price=default_min_price,
            default_token_address=default_token_address,
            default_max_duration_seconds=default_max_duration_seconds,
            rpc_url=rpc_url, chain_id=chain_id,
            publish_priceless=settings.pricing.publish_priceless,
            poll_interval=poll_interval, console=console,
        )
