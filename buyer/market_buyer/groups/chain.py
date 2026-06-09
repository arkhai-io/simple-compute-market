"""`market chain` — operator-facing config sanity checks.

Subcommands:
  check  — issue eth_getCode against each contract address the buyer
           is configured to interact with, naming any that don't
           resolve to bytecode on the configured RPC.

Surfaces TOML typos, wrong-chain-vs-RPC mismatches, and stale post-
redeploy addresses before the operator wastes time on a transaction.
"""
from __future__ import annotations

import asyncio
from typing import Optional

import typer
from rich.console import Console
from rich.table import Table

chain_app = typer.Typer(no_args_is_help=True)


@chain_app.command("check")
def chain_check(
    chain_name: Optional[str] = typer.Option(
        None, "--chain",
        help="Only probe one chain by name. When omitted, probes every "
             "configured [chains.<name>] entry.",
    ),
) -> None:
    """Probe configured contract addresses for deployed bytecode.

    Iterates the buyer's ``[chains.<name>]`` tables (filtered by
    ``--chain`` if given), issuing one ``eth_getCode`` per address the
    buyer will interact with at runtime. Reports which addresses have
    bytecode and which don't.

    Exits 0 on full match, 4 if any address has no bytecode.
    """
    from ..common import buyer_chains

    chains = buyer_chains()
    if not chains:
        typer.secho(
            "No [chains.<name>] tables configured in buyer.toml.",
            err=True, fg=typer.colors.RED,
        )
        raise typer.Exit(2)

    if chain_name is not None:
        if chain_name not in chains:
            typer.secho(
                f"Chain {chain_name!r} not configured. Available: {sorted(chains)}",
                err=True, fg=typer.colors.RED,
            )
            raise typer.Exit(2)
        targets = {chain_name: chains[chain_name]}
    else:
        targets = chains

    from market_alkahest.alkahest import resolve_alkahest_address_config
    from market_alkahest.chain_probe import probe_addresses_sync

    console = Console()
    all_results: dict[str, dict[str, bool]] = {}
    for name, chain in targets.items():
        addresses: dict[str, str] = {}
        try:
            cfg = resolve_alkahest_address_config(
                name, config_path=chain.alkahest_address_config_path,
            )
        except Exception as exc:
            typer.secho(
                f"chain={name!r} could not resolve alkahest config: {exc}",
                err=True, fg=typer.colors.YELLOW,
            )
            cfg = None

        if cfg is not None:
            for path, label in (
                (("arbiters_addresses", "recipient_arbiter"), "alkahest.recipient_arbiter"),
                (("arbiters_addresses", "eas"), "alkahest.eas"),
                (("erc20_addresses", "escrow_obligation_nontierable"),
                 "alkahest.erc20_escrow_obligation"),
            ):
                obj: object | None = cfg
                for attr in path:
                    obj = getattr(obj, attr, None)
                    if obj is None:
                        break
                if isinstance(obj, str) and obj.strip():
                    addresses[label] = obj

        if not addresses:
            typer.secho(
                f"chain={name!r}: no contract addresses to probe.",
                err=True, fg=typer.colors.YELLOW,
            )
            continue

        typer.echo(f"Probing {len(addresses)} address(es) on {chain.rpc_url} (chain={name})…")
        results = probe_addresses_sync(chain.rpc_url, addresses)
        all_results[name] = results

        table = Table(show_header=True, title=name)
        table.add_column("Label", overflow="fold")
        table.add_column("Address", overflow="fold")
        table.add_column("Has bytecode", justify="center")
        for label, addr in addresses.items():
            ok = results.get(label, False)
            table.add_row(label, addr, "✓" if ok else "✗")
        console.print(table)

    if any(not all(r.values()) for r in all_results.values()):
        raise typer.Exit(4)
