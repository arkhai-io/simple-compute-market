"""VM buyer-plugin common helpers.

Generic identity, wallet, negotiation, and storefront values come from the
core buyer. Concrete chain selection and VM SSH-key resolution stay here at
the domain composition boundary.
"""

from __future__ import annotations

from pathlib import Path
import os
import subprocess

from typing import TYPE_CHECKING
import typer

# Generic buyer config remains core-owned; chain selection below is VM-owned.
from core_buyer.buyer_config import (  # noqa: F401
    resolve_buyer_signer,
    resolve_config_value,
    resolve_negotiation_config,
    resolve_identity_config,
    resolve_identity_credential,
    resolve_buyer_wallet,
    resolve_storefront_url,
)
from core_buyer.registry_config import (  # noqa: F401
    resolve_discovery_timeout,
    resolve_indexer_urls,
    resolve_indexer_urls_for_schema,
    resolve_registry_api_keys,
    resolve_registry_authorities,
)

if TYPE_CHECKING:
    from market_config.config_loader import ChainConfig


REPO_ROOT = Path(__file__).resolve().parents[3]
STOREFRONT_ROOT = REPO_ROOT / "domains" / "vms" / "storefront"

#: The registry schema understood by the VM buyer domain. Discovery verbs
#: resolve registries through `resolve_indexer_urls_for_schema(VMS_SCHEMA_ID, …)`
#: so registries declaring a different schema are skipped.
VMS_SCHEMA_ID = "vms.compute"


def buyer_chains() -> dict[str, "ChainConfig"]:
    """Return the VM buyer's configured chain tables."""
    from market_config.config_loader import chains_from_config

    return chains_from_config()


def select_chain_for_listing(
    listing: dict | None,
    *,
    override: str | None = None,
    yes: bool = False,
) -> "ChainConfig":
    """Select a configured chain accepted by the VM listing."""
    chains = buyer_chains()
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
    """Resolve a configured VM settlement chain by name."""
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


def resolve_ssh_public_key(*, override: str | None = None) -> str:
    """Resolve the buyer's SSH public key for provisioning.

    Precedence: explicit override > ``provisioning.ssh_public_key`` from
    config.toml > the first standard public-key file found in ``~/.ssh/``.
    Returns an empty string if no source has one — the caller decides whether
    that is fatal.

    The ~/.ssh fallback covers the most common case where the user has an
    ed25519/rsa keypair but never added it to config.toml. Order matches
    OpenSSH's identity-file default search order.
    """
    explicit = resolve_config_value(
        override=override,
        toml_path="provisioning.ssh_public_key",
    )
    if explicit:
        return explicit
    home_ssh = Path.home() / ".ssh"
    for fname in ("id_ed25519.pub", "id_ecdsa.pub", "id_rsa.pub"):
        p = home_ssh / fname
        if p.is_file():
            try:
                content = p.read_text(encoding="utf-8").strip()
            except OSError:
                continue
            if content:
                return content
    return ""


def resolve_chain_id(rpc_url: str) -> int:
    """Fallback ``eth_chainId`` resolver for code paths that haven't been
    migrated to the multi-chain ChainConfig pattern yet.

    Prefer reading ``chain.chain_id`` directly from a :class:`ChainConfig`
    returned by :func:`select_chain_for_listing` / :func:`chain_by_name`
    — that's the source of truth now and avoids the live RPC hop.
    """
    from web3 import Web3
    from web3.providers import HTTPProvider

    try:
        w3 = Web3(HTTPProvider(rpc_url))
        return int(w3.eth.chain_id)
    except Exception as exc:
        raise RuntimeError(
            f"eth_chainId lookup against {rpc_url!r} failed: {exc}"
        ) from exc


def run_step(
    label: str,
    cmd: list[str],
    cwd: Path,
    extra_env: dict[str, str] | None = None,
) -> None:
    typer.echo(f"==> {label} at {cwd}")
    env = os.environ.copy()
    venv_path = cwd / ".venv"
    # When running storefront-side commands (e.g. registration scripts)
    # the working dir is the storefront package, but uv created the
    # venv at the storefront package root.
    if cwd.resolve() == STOREFRONT_ROOT.resolve():
        storefront_venv = STOREFRONT_ROOT / ".venv"
        if storefront_venv.exists():
            venv_path = storefront_venv
    venv_bin = venv_path / "bin"
    if venv_bin.exists():
        env["VIRTUAL_ENV"] = str(venv_path)
        env["PATH"] = f"{venv_bin}{os.pathsep}{env.get('PATH', '')}"
    if extra_env:
        env.update(extra_env)
    subprocess.run(cmd, cwd=cwd, check=True, env=env)
