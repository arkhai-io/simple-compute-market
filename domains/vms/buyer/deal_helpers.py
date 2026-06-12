"""VM shim over the core deal-recovery helpers.

Run-log scraping and chain-settings resolution moved to
``core_buyer.deal_helpers`` when the API-tokens domain became the
second schema plugin. This module keeps the VM instantiation:
SSH-key resolution (and its missing-key guard) wraps the core
resolver, since the key is the VM domain's provisioning payload.
"""

from __future__ import annotations

from typing import Optional, TYPE_CHECKING

import typer

from core_buyer.deal_helpers import (  # noqa: F401 — re-exports
    ChainSettings,
    DealContext,
    NegotiationResumePoint,
    is_negotiation_complete,
    load_deal_context,
    load_negotiation_resume_point,
    open_run_log,
)
from core_buyer.deal_helpers import (
    resolve_chain_settings as _core_resolve_chain_settings,
)

if TYPE_CHECKING:
    from market_config.config_loader import ChainConfig


def resolve_chain_settings(
    *,
    buyer_address: Optional[str],
    buyer_private_key: Optional[str],
    ssh_public_key: Optional[str],
    chain: "ChainConfig",
    token_contract: Optional[str],
    token_decimals: Optional[int],
    require_ssh: bool = True,
) -> ChainSettings:
    """Resolve wallet/SSH/token credentials around a pre-selected ChainConfig.

    VM instantiation of the core resolver: resolves the SSH public key
    (override > config.toml > ~/.ssh) and enforces its presence for
    commands that submit settlement. ``require_ssh=False`` skips the
    check for commands that don't (e.g. ``market escrow create``).
    """
    from .common import resolve_ssh_public_key

    ssh = resolve_ssh_public_key(override=ssh_public_key)
    if require_ssh and not ssh:
        typer.secho("Missing required config:", err=True, fg=typer.colors.RED)
        typer.secho(
            "  • ssh_public_key — set with: market config set wallet.ssh_public_key <value>",
            err=True, fg=typer.colors.RED,
        )
        typer.secho(
            "Run `market config init-user` to scaffold a config file with the full set of keys.",
            err=True, fg=typer.colors.YELLOW,
        )
        raise typer.Exit(2)

    return _core_resolve_chain_settings(
        buyer_address=buyer_address,
        buyer_private_key=buyer_private_key,
        ssh_public_key=ssh,
        chain=chain,
        token_contract=token_contract,
        token_decimals=token_decimals,
    )
