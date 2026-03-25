import typer

from ..common import REPO_ROOT, run_step

network_app = typer.Typer(no_args_is_help=True)


@network_app.command("install")
def network_install() -> None:
    """Install ZeroTier, if it isn't already installed."""
    run_step(
        "ZeroTier install (make install)",
        ["make", "install"],
        REPO_ROOT / "infra",
    )


@network_app.command("create")
def network_create() -> None:
    """Create network."""
    run_step(
        "Create ZeroTier network (make create-network)",
        ["make", "create-network"],
        REPO_ROOT / "infra",
    )


@network_app.command("add")
def network_add(member_id: str = typer.Argument(..., help="Member ID")) -> None:
    """Authorize a member."""
    run_step(
        f"Authorize ZeroTier member {member_id}",
        ["make", "add-node", f"NODE_ID={member_id}"],
        REPO_ROOT / "infra",
    )


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
    """Get network peers."""
    run_step(
        "Get ZeroTier peers (make get-peers)",
        ["make", "get-peers"],
        REPO_ROOT / "infra",
    )
