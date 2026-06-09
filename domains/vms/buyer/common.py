from __future__ import annotations

from pathlib import Path
import os
import subprocess

import typer

REPO_ROOT = Path(__file__).resolve().parents[3]
STOREFRONT_ROOT = REPO_ROOT / "domains" / "vms" / "storefront"


def resolve_config_value(
    *,
    override: str | None = None,
    toml_path: str | None = None,
    default: str = "",
) -> str:
    """Lookup a scalar config value: CLI override > config.toml > default.

    The TOML file location is whatever ``market_config.config_loader.load_user_config``
    resolves to (XDG default, or the override set by ``--config``).
    """
    if override:
        return override
    if toml_path:
        from market_config.config_loader import get_dotted, load_user_config
        v = get_dotted(load_user_config(), toml_path)
        if v not in (None, ""):
            return str(v)
    return default


def resolve_negotiation_config() -> tuple[object | None, str | None]:
    """Resolve negotiation policy config without flattening TOML lists."""
    from market_config.config_loader import get_dotted, load_user_config

    cfg = load_user_config()
    raw_policies = get_dotted(cfg, "negotiation.policies")
    policies: object | None = None
    if isinstance(raw_policies, list):
        policies = [str(p).strip() for p in raw_policies if str(p).strip()]
    elif isinstance(raw_policies, str) and raw_policies.strip():
        policies = [p.strip() for p in raw_policies.split(",") if p.strip()]
    elif hasattr(raw_policies, "items") or isinstance(raw_policies, dict):
        policies = raw_policies

    raw_policy_mode = get_dotted(cfg, "negotiation.policy_mode")
    policy_mode = str(raw_policy_mode).strip() if raw_policy_mode else None
    return policies, policy_mode


def resolve_buyer_wallet(
    *,
    override_addr: str | None = None,
    override_pk: str | None = None,
) -> tuple[str, str]:
    """Resolve ``(wallet.address, wallet.private_key)`` with derivation.

    Both default to the user config when overrides aren't given. If the
    address is empty but the private key is set, the address is derived
    from the key — addresses are a deterministic function of the key, so
    there's no reason to require both in config. If both are set and
    disagree, a warning is emitted but the configured address is kept
    (lets a user delegate signing for an alternate address while
    surfacing the mismatch loudly).
    """
    addr = resolve_config_value(override=override_addr, toml_path="wallet.address")
    pk = resolve_config_value(override=override_pk, toml_path="wallet.private_key")
    if pk:
        from market_config.config_loader import derive_wallet_address
        derived = derive_wallet_address(pk)
        if derived:
            if not addr:
                addr = derived
            elif addr.lower() != derived.lower():
                typer.secho(
                    f"warning: wallet.address ({addr}) does not match address "
                    f"derived from wallet.private_key ({derived}); using the "
                    f"configured address.",
                    err=True, fg=typer.colors.YELLOW,
                )
    return addr, pk


def buyer_chains() -> dict[str, "ChainConfig"]:
    """Return the buyer's configured ``[chains.<name>]`` tables.

    Thin wrapper around :func:`market_config.config_loader.chains_from_config`
    so the buyer codebase has one place for config-loader access.
    Empty dict when no chains are configured — callers decide whether
    that's fatal (most operations are; ``config show`` isn't).
    """
    from market_config.config_loader import chains_from_config, ChainConfig  # noqa: F401
    return chains_from_config()


def select_chain_for_listing(
    listing: dict | None,
    *,
    override: str | None = None,
    yes: bool = False,
) -> "ChainConfig":
    """Pick a configured chain to use for this listing's escrow.

    Intersection rules:
      - ``override`` must match a name in ``buyer_chains()`` (raises otherwise).
      - When the listing carries ``accepted_escrows``, the chosen chain
        must also appear in the listing's chain_name set. The override is
        validated against this intersection; the interactive default is
        the first intersection member.
      - When ``yes=True`` and no override is given, picks the first
        intersection member silently (or raises if the intersection is
        empty / multiple).

    Returns the selected :class:`ChainConfig`. Raises :class:`typer.Exit`
    on unrecoverable failure.
    """
    chains = buyer_chains()
    if not chains:
        typer.secho(
            "No [chains.<name>] tables configured in buyer.toml. Run "
            "`market config init-user` to scaffold one.",
            err=True, fg=typer.colors.RED,
        )
        raise typer.Exit(2)

    listing_chain_names: set[str] = set()
    if listing is not None:
        for entry in listing.get("accepted_escrows") or []:
            if isinstance(entry, dict):
                name = entry.get("chain_name")
                if isinstance(name, str) and name:
                    listing_chain_names.add(name)

    candidates: list[str]
    if listing_chain_names:
        candidates = [n for n in chains if n in listing_chain_names]
        if not candidates:
            typer.secho(
                f"None of the buyer's configured chains ({sorted(chains)}) match "
                f"the listing's accepted chains ({sorted(listing_chain_names)}).",
                err=True, fg=typer.colors.RED,
            )
            raise typer.Exit(2)
    else:
        candidates = list(chains)

    if override:
        if override not in chains:
            typer.secho(
                f"--chain {override!r} is not in [chains.<name>] config. "
                f"Available: {sorted(chains)}.",
                err=True, fg=typer.colors.RED,
            )
            raise typer.Exit(2)
        if listing_chain_names and override not in listing_chain_names:
            typer.secho(
                f"--chain {override!r} is not accepted by this listing "
                f"({sorted(listing_chain_names)}).",
                err=True, fg=typer.colors.RED,
            )
            raise typer.Exit(2)
        return chains[override]

    if len(candidates) == 1:
        return chains[candidates[0]]

    if yes:
        typer.secho(
            f"Multiple matching chains ({candidates}); pass --chain to pick one "
            "when running with --yes.",
            err=True, fg=typer.colors.RED,
        )
        raise typer.Exit(2)

    # Interactive prompt — default to first match.
    default_idx = 0
    typer.echo("Pick a chain to settle this deal on:")
    for i, n in enumerate(candidates):
        marker = " (default)" if i == default_idx else ""
        typer.echo(f"  [{i}] {n}{marker}")
    raw = typer.prompt(
        "Select", default=str(default_idx), show_default=True,
    )
    try:
        idx = int(raw)
    except ValueError:
        typer.secho(f"Not a number: {raw!r}", err=True, fg=typer.colors.RED)
        raise typer.Exit(2)
    if idx < 0 or idx >= len(candidates):
        typer.secho(f"Out of range: {idx}", err=True, fg=typer.colors.RED)
        raise typer.Exit(2)
    return chains[candidates[idx]]


def chain_by_name(name: str) -> "ChainConfig":
    """Look up one chain by name from the buyer's config.

    Raises :class:`typer.Exit` if the name isn't configured — used by
    commands like ``market settle --from <run_id>`` that know which
    chain they're on from a recorded source of truth.
    """
    chains = buyer_chains()
    chain = chains.get(name)
    if chain is None:
        typer.secho(
            f"Chain {name!r} not configured. Available: {sorted(chains)}.",
            err=True, fg=typer.colors.RED,
        )
        raise typer.Exit(2)
    return chain


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


def resolve_indexer_urls(*, override: str | None = None) -> list[str]:
    """Resolve the buyer's configured registry URLs as a list.

    Precedence: CLI override (comma-separated) > ``registry.urls`` (list)
    > ``http://localhost:8080`` default. Mirrors the storefront's
    ``_resolve_indexer_urls`` shape — only the plural list form is
    recognised, so a stray scalar ``registry.url`` falls through to
    the default.

    The override is comma-separated rather than a repeatable typer
    option because every command that takes it already declares a
    single string flag; comma-splitting keeps the change to those
    declarations a one-liner.
    """
    if override:
        parts = [p.strip() for p in override.split(",") if p.strip()]
        if parts:
            return parts
    from market_config.config_loader import get_dotted, load_user_config
    raw = get_dotted(load_user_config(), "registry.urls")
    if isinstance(raw, list) and raw:
        cleaned = [str(u).strip() for u in raw if str(u).strip()]
        if cleaned:
            return cleaned
    return ["http://localhost:8080"]


def resolve_indexer_auth() -> dict[str, str]:
    """Resolve per-registry bearer tokens from the buyer's TOML config.

    Reads ``[registry.auth]``, a flat ``url → token`` table. URLs not
    listed are queried unauthenticated. There is no CLI override —
    credentials are config-only by design (avoids accidental shell-
    history exposure on a multi-user box).
    """
    from market_config.config_loader import get_dotted, load_user_config
    raw = get_dotted(load_user_config(), "registry.auth")
    if not isinstance(raw, dict):
        return {}
    out: dict[str, str] = {}
    for url, token in raw.items():
        if isinstance(url, str) and isinstance(token, str) and url.strip() and token.strip():
            out[url.strip()] = token.strip()
    return out


def resolve_discovery_timeout(*, override: float | None = None) -> float:
    """Resolve the buyer's per-registry discovery deadline (seconds).

    Precedence: CLI override > ``registry.discovery_timeout`` from
    config.toml > ``5.0``. The orchestrator's multi-URL helpers cap
    each per-registry request at this value so a slow registry can't
    extend the wall time of a discovery pass.
    """
    if override is not None and override > 0:
        return float(override)
    from market_config.config_loader import get_dotted, load_user_config
    raw = get_dotted(load_user_config(), "registry.discovery_timeout")
    try:
        v = float(raw)
        if v > 0:
            return v
    except (TypeError, ValueError):
        pass
    return 5.0


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


def resolve_storefront_url(
    agent_url: str | None,
    default_port: int = 8000,
) -> str:
    """Resolve the URL the CLI should dial to reach the agent.

    Precedence: explicit ``agent_url`` > ``seller.base_url`` from
    config.toml > ``http://localhost:{default_port}``.
    """
    if agent_url:
        return agent_url
    from market_config.config_loader import get_dotted, load_user_config
    cfg = load_user_config()
    base_url = get_dotted(cfg, "seller.base_url")
    if isinstance(base_url, str) and base_url:
        return base_url
    return f"http://localhost:{default_port}"


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
