"""Pick an ``accepted_escrows`` entry from a VM listing."""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Optional

import typer
from rich.console import Console
from rich.table import Table

logger = logging.getLogger(__name__)


def _entry_token(entry: dict[str, Any]) -> Optional[str]:
    from market_alkahest.schemas import accepted_token_address

    value = accepted_token_address(entry)
    return value.lower() if isinstance(value, str) and value.startswith("0x") else None


def _filter_entries(
    accepted: list[dict[str, Any]],
    *,
    chain_name: str,
    token_contract_filter: Optional[str],
    compatible: Optional[Any] = None,
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    token_filter = token_contract_filter.lower() if token_contract_filter else None
    for entry in accepted:
        if not isinstance(entry, dict):
            continue
        if entry.get("chain_name") != chain_name:
            continue
        if token_filter is not None and _entry_token(entry) != token_filter:
            continue
        if compatible is not None and not compatible(entry):
            continue
        out.append(entry)
    return out


def _balance(
    *,
    rpc_url: str,
    wallet_address: str,
    token_address: str,
) -> int:
    """Return token balance, or 0 when lookup fails."""
    try:
        from market_alkahest.token import get_wallet_token_balance
    except Exception:
        return 0
    try:
        return asyncio.run(get_wallet_token_balance(
            wallet_address=wallet_address,
            token_address=token_address,
            rpc_url=rpc_url,
        ))
    except Exception as exc:
        logger.debug("balanceOf(%s) failed: %s", token_address, exc)
        return 0


def select_escrow_entry(
    listing: dict[str, Any],
    *,
    chain_name: str,
    token_contract_filter: Optional[str],
    assume_yes: bool,
    rpc_url: str,
    buyer_address: str,
    console: Optional[Console] = None,
    compatible: Optional[Any] = None,
) -> Optional[dict[str, Any]]:
    """Return one accepted escrow entry to negotiate against.

    ``compatible`` is the configured buyer policy's format predicate
    (ARCHITECTURE.md, "Buyer negotiation policy surface"): entries the policy cannot
    negotiate are never offered, so an incompatible-only listing yields
    None ("no compatible escrow format") instead of a tuple the
    strategy would mangle.
    """
    accepted = listing.get("accepted_escrows") or []
    if isinstance(accepted, str):
        import json

        try:
            accepted = json.loads(accepted)
        except (ValueError, TypeError):
            accepted = []
    if not isinstance(accepted, list) or not accepted:
        return None

    candidates = _filter_entries(
        accepted,
        chain_name=chain_name,
        token_contract_filter=token_contract_filter,
        compatible=compatible,
    )
    if not candidates:
        return None

    if len(candidates) == 1:
        return candidates[0]

    if assume_yes:
        for entry in candidates:
            token = _entry_token(entry)
            if not token:
                continue
            balance = _balance(
                rpc_url=rpc_url,
                wallet_address=buyer_address,
                token_address=token,
            )
            if balance > 0:
                return entry
        return candidates[0]

    console = console or Console()
    table = Table(title="Accepted escrows", show_header=True)
    table.add_column("#", justify="right", style="dim")
    table.add_column("Escrow contract", overflow="fold")
    table.add_column("Token", overflow="fold")
    table.add_column("Price/hr", justify="right")
    from market_alkahest.schemas import primary_rate_value

    for i, entry in enumerate(candidates, start=1):
        token = _entry_token(entry) or "-"
        rate = primary_rate_value(entry)
        table.add_row(
            str(i),
            str(entry.get("escrow_address", "-")),
            token,
            "-" if rate is None else str(rate),
        )
    console.print(table)
    try:
        idx = typer.prompt(
            "Which entry to use?",
            default=1,
            type=int,
        )
    except typer.Abort:
        raise typer.Exit(2)
    if idx < 1 or idx > len(candidates):
        typer.secho(
            f"Invalid selection {idx}; expected 1..{len(candidates)}.",
            err=True,
            fg=typer.colors.RED,
        )
        raise typer.Exit(2)
    return candidates[idx - 1]
