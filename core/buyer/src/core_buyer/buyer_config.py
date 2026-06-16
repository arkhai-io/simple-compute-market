"""Schema-invariant buyer config resolution.

Wallet, chain, negotiation-policy, and storefront-URL resolution from
the buyer's TOML (via ``market_config``) with CLI overrides taking
precedence. Moved verbatim from the VM buyer's ``common`` module when
the API-tokens domain became the second schema plugin; domain packages
keep what interprets their own vocabulary (the VM SSH key resolver,
repo paths) and re-export these.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import typer

if TYPE_CHECKING:
    from market_config.config_loader import ChainConfig


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
