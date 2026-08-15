"""API-credits buyer-plugin common helpers.

Generic identity, wallet, and negotiation values come from core. Concrete
chain selection, registry binding, and API-credit flags remain domain-owned.
"""

from __future__ import annotations

import typer
from collections.abc import Callable
from typing import Any, TYPE_CHECKING

from core_buyer.orchestrator import fetch_listing_dict
from core_buyer.run_log import read_run
from market_identity import Signer, TrustedIdentitySet


from core_buyer.buyer_config import (  # noqa: F401 — re-exports
    resolve_buyer_wallet,
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

if TYPE_CHECKING:
    from market_config.config_loader import ChainConfig


#: The registry schema understood by the API-credit buyer domain. Discovery
#: verbs resolve registries through
#: `resolve_indexer_urls_for_schema(APICREDITS_SCHEMA_ID, …)` so registries
#: declaring a different schema are skipped. The API-credit registry's
#: filter-spec.yaml declares the same id.
APICREDITS_SCHEMA_ID = "api_credits"


def buyer_chains() -> dict[str, "ChainConfig"]:
    """Return the API-credit buyer's configured chain tables."""
    from market_config.config_loader import chains_from_config

    return chains_from_config()


def select_chain_for_listing(
    listing: dict | None,
    *,
    override: str | None = None,
    yes: bool = False,
) -> "ChainConfig":
    """Select a configured chain accepted by the API-credit listing."""
    chains = buyer_chains()
    if not chains:
        typer.secho(
            "No [chains.<name>] tables configured in buyer.toml. Run "
            "`market config init-user` to scaffold one.",
            err=True,
            fg=typer.colors.RED,
        )
        raise typer.Exit(2)

    listing_chain_names: set[str] = set()
    if listing is not None:
        for entry in listing.get("accepted_escrows") or []:
            if isinstance(entry, dict):
                name = entry.get("chain_name")
                if isinstance(name, str) and name:
                    listing_chain_names.add(name)

    if listing_chain_names:
        candidates = [name for name in chains if name in listing_chain_names]
        if not candidates:
            typer.secho(
                f"None of the buyer's configured chains ({sorted(chains)}) match "
                f"the listing's accepted chains ({sorted(listing_chain_names)}).",
                err=True,
                fg=typer.colors.RED,
            )
            raise typer.Exit(2)
    else:
        candidates = list(chains)

    if override:
        if override not in chains:
            typer.secho(
                f"--chain {override!r} is not in [chains.<name>] config. "
                f"Available: {sorted(chains)}.",
                err=True,
                fg=typer.colors.RED,
            )
            raise typer.Exit(2)
        if listing_chain_names and override not in listing_chain_names:
            typer.secho(
                f"--chain {override!r} is not accepted by this listing "
                f"({sorted(listing_chain_names)}).",
                err=True,
                fg=typer.colors.RED,
            )
            raise typer.Exit(2)
        return chains[override]

    if len(candidates) == 1:
        return chains[candidates[0]]
    if yes:
        typer.secho(
            f"Multiple matching chains ({candidates}); pass --chain to pick one "
            "when running with --yes.",
            err=True,
            fg=typer.colors.RED,
        )
        raise typer.Exit(2)

    typer.echo("Pick a chain to settle this deal on:")
    for index, name in enumerate(candidates):
        marker = " (default)" if index == 0 else ""
        typer.echo(f"  [{index}] {name}{marker}")
    raw = typer.prompt("Select", default="0", show_default=True)
    try:
        index = int(raw)
    except ValueError:
        typer.secho(f"Not a number: {raw!r}", err=True, fg=typer.colors.RED)
        raise typer.Exit(2)
    if index < 0 or index >= len(candidates):
        typer.secho(f"Out of range: {index}", err=True, fg=typer.colors.RED)
        raise typer.Exit(2)
    return chains[candidates[index]]


def chain_by_name(name: str) -> "ChainConfig":
    """Resolve a configured API-credit settlement chain by name."""
    chains = buyer_chains()
    chain = chains.get(name)
    if chain is None:
        typer.secho(
            f"Chain {name!r} not configured. Available: {sorted(chains)}.",
            err=True,
            fg=typer.colors.RED,
        )
        raise typer.Exit(2)
    return chain


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
            return TrustedIdentitySet.model_validate(value)
        except (TypeError, ValueError) as exc:
            raise RuntimeError(
                "publisher refresh returned invalid principal trust",
            ) from exc

    return refresh




def resolve_key_disposition(
    *,
    new_key: bool,
    key_id: str | None,
) -> tuple[str, str | None]:
    """``(key_mode, key_id)`` from the ``--new-key`` / ``--key-id`` flags.

    Mutually exclusive; with neither given the default is a fresh key
    (auto-bound to the purchasing wallet by the v1 seller default).
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
