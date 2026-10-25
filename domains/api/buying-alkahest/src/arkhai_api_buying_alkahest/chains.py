"""The configured chains an Alkahest settlement runs on, and the one a listing's escrows accept."""

from __future__ import annotations

import typer
from market_config.config_loader import ChainConfig, chains_from_config


def buyer_chains() -> dict[str, "ChainConfig"]:
    """Return the buyer's configured chain tables."""
    return chains_from_config()


def select_chain_for_listing(
    listing: dict | None,
    *,
    override: str | None = None,
    yes: bool = False,
    chains: dict[str, "ChainConfig"] | None = None,
) -> "ChainConfig":
    """Select a configured chain the listing accepts, from ``chains`` or else the buyer's configuration."""
    chains = buyer_chains() if chains is None else chains
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
