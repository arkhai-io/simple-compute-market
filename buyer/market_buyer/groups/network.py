"""`market network` — operator-side ZeroTier membership.

Per-operator actions only: `join` a network and inspect its `peers`.
Network-owner actions (`install` / `create` / `add` <member>) live in
`market-infra` because they're run once per market by the trust
authority, not per-agent.

Mirror of `market-storefront network`. Buyers and sellers each manage
their own membership; the surface is identical.
"""

from __future__ import annotations

import typer

from ..common import REPO_ROOT, run_step


network_app = typer.Typer(no_args_is_help=True)


@network_app.command("join")
def network_join(
    network_id: str = typer.Argument(..., help="ZeroTier network ID to join."),
) -> None:
    """Join a ZeroTier network."""
    run_step(
        f"Join ZeroTier network {network_id}",
        ["make", "join", f"NETWORK_ID={network_id}"],
        REPO_ROOT / "infra",
    )


@network_app.command("get-peers")
def network_get_peers() -> None:
    """List peers visible on the joined network."""
    run_step(
        "Get ZeroTier peers (make get-peers)",
        ["make", "get-peers"],
        REPO_ROOT / "infra",
    )
