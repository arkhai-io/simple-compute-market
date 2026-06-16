"""VM buyer-plugin common helpers.

The schema-invariant config resolution (wallet, chains, negotiation
policy, storefront URL) moved to ``core_buyer.buyer_config`` when the
API-tokens domain became the second schema plugin; it is re-exported
here because every CLI module resolves it through ``.common``. This
module keeps what is VM vocabulary: the SSH-key resolver, repo paths
for operator scripts, and the schema id.
"""

from __future__ import annotations

from pathlib import Path
import os
import subprocess

import typer

# Schema-invariant config + registry-discovery resolution lives in the
# core buyer role; re-exported here because every CLI module resolves
# it through `.common`.
from core_buyer.buyer_config import (  # noqa: F401
    buyer_chains,
    chain_by_name,
    resolve_config_value,
    resolve_negotiation_config,
    resolve_buyer_wallet,
    resolve_storefront_url,
    select_chain_for_listing,
)
from core_buyer.registry_config import (  # noqa: F401
    resolve_discovery_timeout,
    resolve_indexer_auth,
    resolve_indexer_urls,
    resolve_indexer_urls_for_schema,
)

REPO_ROOT = Path(__file__).resolve().parents[3]
STOREFRONT_ROOT = REPO_ROOT / "domains" / "vms" / "storefront"

#: The registry schema this plugin implements (mirrors the
#: BuyerSchemaPlugin declaration in `.cli`). Discovery verbs resolve
#: registries through `resolve_indexer_urls_for_schema(VMS_SCHEMA_ID, …)`
#: so registries declaring a different schema are skipped.
VMS_SCHEMA_ID = "vms.compute"


def resolve_ssh_public_key(*, override: str | None = None) -> str:
    """Resolve the buyer's SSH public key for provisioning.

    Precedence: explicit override > ``wallet.ssh_public_key`` from config.toml
    > the first standard public-key file found in ``~/.ssh/``. Returns an
    empty string if no source has one — the caller decides whether that's
    fatal (settle requires it; reclaim/refund don't).

    The ~/.ssh fallback covers the most common case where the user has an
    ed25519/rsa keypair but never added it to config.toml. Order matches
    OpenSSH's identity-file default search order.
    """
    explicit = resolve_config_value(override=override, toml_path="wallet.ssh_public_key")
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
