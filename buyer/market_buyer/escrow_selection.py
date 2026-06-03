"""Pick an ``accepted_escrows`` entry from a listing.

The seller advertises one or more escrow shapes it accepts on a given
listing — each entry carries ``(chain_name, escrow_address,
literal_fields, rates)``. The buyer's job is to pick one of those
entries to negotiate against. Token, escrow contract, and chain all
come from the picked entry — the buyer never imposes its own escrow
shape on the seller.

Selection rules (see ``select_escrow_entry``):
  * Filter entries by the buyer's configured ``chain_name`` (the buyer
    only has one chain's RPC + addresses).
  * Optionally filter by ``--token-contract`` (when the buyer wants to
    spend only one specific ERC-20).
  * If 0 entries remain: raise — the listing isn't compatible.
  * If 1: return it.
  * If >1:
      - interactive (no ``--yes``): prompt with a table.
      - ``--yes``: on-chain ``balanceOf`` per token; pick the first
        entry the buyer has any of. Falls back to the first entry on
        a clean zero across the board.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any, Optional

import typer
from rich.console import Console
from rich.table import Table

logger = logging.getLogger(__name__)


def _entry_token(entry: dict[str, Any]) -> Optional[str]:
    from service.schemas import accepted_token_address

    v = accepted_token_address(entry)
    return v.lower() if isinstance(v, str) and v.startswith("0x") else None


def _filter_entries(
    accepted: list[dict[str, Any]],
    *,
    chain_name: str,
    token_contract_filter: Optional[str],
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    tcf = token_contract_filter.lower() if token_contract_filter else None
    for e in accepted:
        if not isinstance(e, dict):
            continue
        if e.get("chain_name") != chain_name:
            continue
        if tcf is not None and _entry_token(e) != tcf:
            continue
        out.append(e)
    return out


def _balance(
    *,
    rpc_url: str,
    wallet_address: str,
    token_address: str,
) -> int:
    """Sync wrapper around the async ``get_wallet_token_balance``.

    Returns 0 on any failure (RPC error, unknown token, no web3). The
    intent of the auto-pick path is "use this if we have some" — a
    failed lookup just means "try the next one."
    """
    try:
        from service.clients.token import get_wallet_token_balance
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
) -> Optional[dict[str, Any]]:
    """Return one accepted_escrows entry to negotiate against.

    Returns ``None`` when the listing has no entry compatible with the
    buyer's chain (+ optional token filter) — callers in single-listing
    flows treat that as a hard error; callers iterating over a candidate
    pool just skip the listing.

    Raises ``typer.Exit(2)`` only when the user aborts an interactive
    prompt — that's a real user-driven cancel, not a filter miss.
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
    )
    if not candidates:
        return None

    if len(candidates) == 1:
        return candidates[0]

    if assume_yes:
        # Pick the first entry where the buyer has any balance. Falls
        # back to candidates[0] when every balance comes up zero.
        for entry in candidates:
            token = _entry_token(entry)
            if not token:
                continue
            bal = _balance(
                rpc_url=rpc_url,
                wallet_address=buyer_address,
                token_address=token,
            )
            if bal > 0:
                return entry
        return candidates[0]

    # Interactive: render a table and ask which entry to use.
    console = console or Console()
    table = Table(title="Accepted escrows", show_header=True)
    table.add_column("#", justify="right", style="dim")
    table.add_column("Escrow contract", overflow="fold")
    table.add_column("Token", overflow="fold")
    table.add_column("Price/hr", justify="right")
    from service.schemas import primary_rate_value

    for i, e in enumerate(candidates, start=1):
        token = _entry_token(e) or "-"
        rate = primary_rate_value(e)
        table.add_row(
            str(i),
            str(e.get("escrow_address", "-")),
            token,
            "-" if rate is None else str(rate),
        )
    console.print(table)
    try:
        idx = typer.prompt(
            "Which entry to use?",
            default=1, type=int,
        )
    except typer.Abort:
        raise typer.Exit(2)
    if idx < 1 or idx > len(candidates):
        typer.secho(
            f"Invalid selection {idx}; expected 1..{len(candidates)}.",
            err=True, fg=typer.colors.RED,
        )
        raise typer.Exit(2)
    return candidates[idx - 1]
