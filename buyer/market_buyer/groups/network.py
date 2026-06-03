"""`market network` — ZeroTier overlay membership.

`join` a network and inspect its `peers`. Network-owner actions
(`install` / `create` / `add` <member>) are Make targets in
`scripts/zerotier/`, run by whoever stands up the overlay.

Mirror of `market-storefront network`. Buyers and sellers each manage
their own membership; the surface is identical.
"""

from __future__ import annotations

import typer

from ..common import REPO_ROOT, run_step


network_app = typer.Typer(no_args_is_help=True)


@network_app.command("join")
def network_join(
    network_id: str = typer.Argument(
        None,
        help="ZeroTier network ID. Defaults to seller.zerotier_network from config.toml.",
    ),
) -> None:
    """Join a ZeroTier network."""
    from ..common import resolve_config_value
    network_id = network_id or resolve_config_value(
        toml_path="seller.zerotier_network",
    )
    if not network_id:
        typer.secho(
            "No network_id provided and seller.zerotier_network is not set in config.toml. "
            "Pass the network ID explicitly or run "
            "`market config set seller.zerotier_network <id>` first.",
            err=True, fg=typer.colors.RED,
        )
        raise typer.Exit(2)
    run_step(
        f"Join ZeroTier network {network_id}",
        ["make", "join", f"NETWORK_ID={network_id}"],
        REPO_ROOT / "scripts" / "zerotier",
    )


@network_app.command("get-peers")
def network_get_peers() -> None:
    """List peers visible on the joined network."""
    run_step(
        "Get ZeroTier peers (make get-peers)",
        ["make", "get-peers"],
        REPO_ROOT / "scripts" / "zerotier",
    )
