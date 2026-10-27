"""The configured chains an Alkahest settlement runs on, and the one a listing's escrows accept."""

from __future__ import annotations

import typer
from market_config.config_loader import ChainConfig, chains_from_config


def buyer_chains() -> dict[str, "ChainConfig"]:
    """Return the buyer's configured chain tables."""
    return chains_from_config()


def accepted_chain_names(listing: dict | None) -> set[str]:
    """The chains a listing's accepted escrows name."""
    names: set[str] = set()
    for entry in (listing or {}).get("accepted_escrows") or []:
        if isinstance(entry, dict):
            name = entry.get("chain_name")
            if isinstance(name, str) and name:
                names.add(name)
    return names


def select_chain_for_listing(
    listing: dict | None,
    *,
    yes: bool = False,
    chains: dict[str, "ChainConfig"] | None = None,
) -> "ChainConfig":
    """The configured chain a listing's accepted escrows name; several prompt, or refuse under ``yes``."""
    chains = buyer_chains() if chains is None else chains
    if not chains:
        typer.secho(
            "No [chains.<name>] tables configured in buyer.toml. Run "
            "`market config init-user` to scaffold one.",
            err=True,
            fg=typer.colors.RED,
        )
        raise typer.Exit(2)

    listing_id = (listing or {}).get("listing_id")
    listing_chain_names = accepted_chain_names(listing)
    candidates = [name for name in chains if name in listing_chain_names]
    if not candidates:
        typer.secho(
            f"Listing {listing_id!r} accepts chains {sorted(listing_chain_names)}, none of "
            f"which is among the buyer's configured chains ({sorted(chains)}).",
            err=True,
            fg=typer.colors.RED,
        )
        raise typer.Exit(2)

    if len(candidates) == 1:
        return chains[candidates[0]]
    if yes:
        typer.secho(
            f"Listing {listing_id!r} accepts several configured chains ({candidates}); run without "
            "--yes to pick one, or configure only the chains you settle on.",
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
    """Resolve a configured settlement chain by name."""
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
