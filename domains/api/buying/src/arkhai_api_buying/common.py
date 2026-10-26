"""Helpers every buyer command shares: identity and registry configuration, the run's source binding, and output."""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any, Optional

import typer
from core_buyer.buyer_config import BuyerProfileResolver, ResolvedBuyerIdentity
from core_buyer.orchestrator import fetch_listing_dict
from core_buyer.policy_surface import configured_buyer_policy
from core_buyer.profile_service import BuyerProfileService
from core_buyer.run_log import read_run
from market_identity import Signer, TrustedIdentitySet
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from core_buyer.buyer_config import (  # noqa: F401 — re-exports
    resolve_config_value,
    resolve_fresh_buyer_identity,
    resolve_negotiation_config,
    resolve_recovery_buyer_identity,
)
from core_buyer.registry_config import (  # noqa: F401 — re-exports
    resolve_discovery_timeout,
    resolve_indexer_urls,
    resolve_indexer_urls_for_schema,
    resolve_registry_api_keys,
    resolve_registry_authorities,
)

from arkhai_api_buying.credentials import UNRECORDED_EXIT, UNSAVED_EXIT, Delivery


def make_run_publisher_principals_refresh(
    run_id: str,
    *,
    signer: Signer,
) -> Callable[[str, str, str, str], TrustedIdentitySet]:
    """Build a source-pinned signed refresh for one signer-owned run."""
    events = read_run(run_id, signer=signer)
    if not events:
        raise RuntimeError(f"run {run_id!r} has no signer-owned events")

    def bound_value(name: str, *, url: bool = False) -> str:
        values = {
            (str(event[name]).rstrip("/") if url else str(event[name]))
            for event in events
            if event.get(name) is not None
        }
        if len(values) != 1:
            raise RuntimeError(f"run {run_id!r} has invalid {name} binding")
        return values.pop()

    bound_listing_id = bound_value("listing_id")
    bound_publisher_id = bound_value("publisher_id")
    bound_registry_url = bound_value("source_registry_url", url=True)
    bound_registry_authority = bound_value("source_registry_authority")
    bound_storefront_url = bound_value("seller_url", url=True)

    configured_urls = resolve_indexer_urls()
    registry_authorities = resolve_registry_authorities(configured_urls)
    registry_authority = registry_authorities.get(bound_registry_url)
    if (
        registry_authority is None
        or registry_authority.authority != bound_registry_authority
    ):
        raise RuntimeError("run registry authority binding is no longer configured")
    api_key = resolve_registry_api_keys().get(bound_registry_url)
    timeout = resolve_discovery_timeout()

    def refresh(
        listing_id: str,
        publisher_id: str,
        source_registry_url: str,
        source_registry_authority: str,
    ) -> TrustedIdentitySet:
        if (
            str(listing_id) != bound_listing_id
            or str(publisher_id) != bound_publisher_id
            or source_registry_url.rstrip("/") != bound_registry_url
            or source_registry_authority != bound_registry_authority
        ):
            raise RuntimeError("publisher refresh changed recorded source binding")
        listing = fetch_listing_dict(
            bound_registry_url,
            bound_listing_id,
            timeout=timeout,
            signer=signer,
            registry_authority=registry_authority,
            api_key=api_key,
        )
        if listing is None:
            raise RuntimeError("publisher refresh listing no longer exists")
        if (
            str(listing.get("listing_id")) != bound_listing_id
            or str(listing.get("publisher_id")) != bound_publisher_id
            or str(listing.get("storefront_url") or "").rstrip("/")
            != bound_storefront_url
        ):
            raise RuntimeError("publisher refresh changed listing subject binding")
        value: Any = listing.get("publisher_principals")
        try:
            return TrustedIdentitySet.model_validate_json(json.dumps(value))
        except (TypeError, ValueError) as exc:
            raise RuntimeError(
                "publisher refresh returned invalid principal trust",
            ) from exc

    return refresh


def resolve_recovery_buyer_identity_in(run_id: str, directory: Path) -> ResolvedBuyerIdentity:
    """The run's recorded profile and principal, read from the run log in ``directory``."""
    return BuyerProfileResolver(BuyerProfileService(run_logs_directory=directory)).recovery(run_id)


def resolve_key_disposition(
    *,
    new_key: bool,
    key_id: str | None,
) -> tuple[str, str | None]:
    """``(key_mode, key_id)`` from the ``--new-key`` / ``--key-id`` flags.

    Mutually exclusive; with neither given the default is a fresh key
    (bound to the purchasing principal by the seller).
    """
    if new_key and key_id:
        typer.secho(
            "--new-key and --key-id are mutually exclusive: a deal either "
            "issues a fresh key or tops up an existing one.",
            err=True,
            fg=typer.colors.RED,
        )
        raise typer.Exit(2)
    if key_id:
        return "existing", key_id
    return "new", None


def resolve_prices_from_matches(
    *,
    matches: list[dict],
    console: Console,
    params: dict | None = None,
    interactive: bool = False,
) -> tuple[Optional[int], Optional[int]]:
    """Fill missing prices via the configured buyer policy's derivation.

    Thin dispatch carrying only the canonical hook arguments — the
    policy's own values travel inside ``params`` (its namespace), so
    this dispatcher knows no policy's vocabulary. A policy with no
    derivation hook passes its explicit values through.
    """
    params = dict(params or {})
    policy = configured_buyer_policy()
    if policy.derive_prices is None:
        return params.get("initial_price"), params.get("max_price")
    return policy.derive_prices(
        params=params,
        matches=matches,
        console=console,
        interactive=interactive,
    )


def render_credentials(
    console: Console, delivery: Delivery, *, run_id: str, command_path: str,
) -> None:
    """Show the issued key once, then exit if its secret could not be saved privately."""
    credentials = delivery.credentials
    table = Table.grid(padding=(0, 2))
    table.add_column(style="bold")
    table.add_column()
    for label, key in (
        ("Key ID", "key_id"),
        ("Secret", "secret"),
        ("Base URL", "base_url"),
        ("Balance", "balance"),
    ):
        if credentials.get(key) is not None:
            table.add_row(label, str(credentials[key]))
    if delivery.unsaved:
        title, border = "API key issued — NOT SAVED; copy it now", "red"
    elif delivery.reference:
        title, border = "API key issued — shown once; saved privately", "green"
    else:
        title, border = "API key delivered — no secret returned", "green"
    console.print(Panel(table, title=title, border_style=border))
    if delivery.reference:
        console.print(
            f"[dim]Saved to {delivery.location}. Read it again with "
            f"`{command_path} credentials show --from {run_id}`.[/dim]"
        )
    if delivery.unrecorded:
        typer.secho(
            f"The run log could not record this delivery; the key is saved at {delivery.location}.",
            err=True,
            fg=typer.colors.RED,
        )
        raise typer.Exit(UNRECORDED_EXIT)
    if delivery.unsaved:
        typer.secho(
            "The issued key could not be saved to the private credential store. "
            "Copy the secret above now; the run log does not hold it.",
            err=True,
            fg=typer.colors.RED,
        )
        raise typer.Exit(UNSAVED_EXIT)


def validate_model(model_type, value):
    """Decode a wire dictionary while tolerating an already-decoded model."""
    if isinstance(value, model_type):
        return value
    if hasattr(value, "model_dump"):
        value = value.model_dump()
    return model_type.model_validate(value)
