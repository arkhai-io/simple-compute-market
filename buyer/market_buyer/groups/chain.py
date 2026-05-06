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
    rpc_url: Optional[str] = typer.Option(
        None, "--rpc-url",
        help="Override chain.rpc_url from config.toml.",
    ),
    chain_name: Optional[str] = typer.Option(
        None, "--chain-name",
        help="Override chain.name from config.toml.",
    ),
    alkahest_addr_config: Optional[str] = typer.Option(
        None, "--alkahest-addr-config",
        help="Override chain.alkahest_address_config_path from config.toml.",
    ),
) -> None:
    """Probe configured contract addresses for deployed bytecode.

    Reads the buyer's chain config (override flags > config.toml > SDK
    defaults), then issues one eth_getCode per address that the buyer
    will interact with at runtime. Reports which addresses have
    bytecode and which don't.

    Exits 0 on full match, 4 if any address has no bytecode.
    """
    from ..common import resolve_config_value

    rpc = rpc_url or resolve_config_value(toml_path="chain.rpc_url")
    chain = chain_name or resolve_config_value(
        toml_path="chain.name", default="ethereum_sepolia",
    )
    addr_cfg = alkahest_addr_config or resolve_config_value(
        toml_path="chain.alkahest_address_config_path",
    ) or None

    if not rpc:
        typer.secho(
            "chain.rpc_url is not configured. Set it with "
            "`market config set chain.rpc_url <url>` or pass --rpc-url.",
            err=True, fg=typer.colors.RED,
        )
        raise typer.Exit(2)

    from service.clients.alkahest import resolve_alkahest_address_config
    from service.clients.chain_probe import probe_addresses_sync

    addresses: dict[str, str] = {}
    try:
        cfg = resolve_alkahest_address_config(chain, config_path=addr_cfg)
    except Exception as exc:
        typer.secho(
            f"Could not resolve alkahest config for chain={chain!r}: {exc}",
            err=True, fg=typer.colors.RED,
        )
        raise typer.Exit(2)

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

    # ERC-8004 IdentityRegistry — buyer reads it for seller-attestation lookups.
    identity_registry = resolve_config_value(toml_path="registry.identity_registry_address")
    if identity_registry:
        addresses["identity_registry"] = identity_registry

    # Default token contract — buyer transfers it during settle.
    from ..common import resolve_default_token
    try:
        from service.clients.token import TOKEN_REGISTRY
        default_token_meta = TOKEN_REGISTRY.require(resolve_default_token())
        if default_token_meta.contract_address:
            addresses[f"token.{default_token_meta.symbol}"] = default_token_meta.contract_address
    except Exception:
        # Token registry resolution is best-effort here.
        pass

    if not addresses:
        typer.secho(
            "No contract addresses to probe. Configure chain.alkahest_address_config_path "
            "(or pick a SDK-known chain.name) and registry.identity_registry_address.",
            err=True, fg=typer.colors.YELLOW,
        )
        raise typer.Exit(2)

    console = Console()
    typer.echo(f"Probing {len(addresses)} address(es) on {rpc} (chain={chain})…")
    results = probe_addresses_sync(rpc, addresses)

    table = Table(show_header=True)
    table.add_column("Label", overflow="fold")
    table.add_column("Address", overflow="fold")
    table.add_column("Has bytecode", justify="center")
    for label, addr in addresses.items():
        ok = results.get(label, False)
        table.add_row(label, addr, "✓" if ok else "✗")
    console.print(table)

    if not all(results.values()):
        raise typer.Exit(4)
