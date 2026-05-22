from __future__ import annotations

import json

import typer

from service.config_loader import (
    get_dotted,
    load_user_config,
    set_dotted,
    user_config_dir,
    user_config_file,
    write_user_config,
)


config_app = typer.Typer(no_args_is_help=True)


@config_app.command("path")
def config_path() -> None:
    """Print the path of the user config.toml (whether or not it exists)."""
    p = user_config_file()
    typer.echo(str(p))
    if not p.exists():
        typer.secho(
            "(not present — run `market config init-user` to scaffold it)",
            fg=typer.colors.YELLOW,
        )


@config_app.command("show")
def config_show(
    raw: bool = typer.Option(
        False, "--raw",
        help="Print the TOML file verbatim instead of the loaded mapping.",
    ),
) -> None:
    """Show the current user config."""
    p = user_config_file()
    if not p.exists():
        typer.secho(f"No user config at {p}.", fg=typer.colors.YELLOW)
        raise typer.Exit(1)
    if raw:
        typer.echo(p.read_text())
        return
    cfg = load_user_config(p)
    typer.echo(json.dumps(cfg, indent=2, sort_keys=True))


@config_app.command("set")
def config_set(
    key: str = typer.Argument(..., help="Dotted config key, e.g. 'chain.rpc_url'."),
    value: str = typer.Argument(..., help="Value to assign (coerced to int/float/bool when possible)."),
) -> None:
    """Set a single value in the user config.toml.

    Values are coerced: 'true' / 'false' → bool, integer-looking strings → int,
    float-looking strings → float, otherwise left as strings. Use quotes around
    strings that look numeric if you want to keep them as text.
    """
    coerced: object = value
    low = value.strip().lower()
    if low in ("true", "false"):
        coerced = (low == "true")
    else:
        try:
            coerced = int(value)
        except ValueError:
            try:
                coerced = float(value)
            except ValueError:
                coerced = value

    path = user_config_file()
    doc = load_user_config(path)
    set_dotted(doc, key, coerced)
    written = write_user_config(doc, path)
    typer.echo(f"Set {key} = {coerced!r} in {written}")


@config_app.command("get")
def config_get(
    key: str = typer.Argument(..., help="Dotted config key, e.g. 'chain.rpc_url'."),
) -> None:
    """Print the value of a single config key from the user config.toml."""
    doc = load_user_config()
    val = get_dotted(doc, key)
    if val is None:
        typer.secho(
            f"Key {key!r} not set in {user_config_file()}.",
            fg=typer.colors.YELLOW,
        )
        raise typer.Exit(1)
    if isinstance(val, (dict, list)):
        typer.echo(json.dumps(val, indent=2, sort_keys=True))
    else:
        typer.echo(str(val))


_INIT_USER_TEMPLATE = """\
# arkhai user config — see `market config path` for this file's location.
# Every key here is optional and the resolver falls back to built-in
# defaults when a key is missing. Buyers only need [wallet], [chain],
# and [registry]; seller-only keys are commented out below.

# ---------------------------------------------------------------------------
# Shared (buyer + seller read these)
# ---------------------------------------------------------------------------

[wallet]
# address = "0x0000000000000000000000000000000000000000"
# private_key = "0x..."
# ssh_public_key = "ssh-ed25519 AAAA... user@host"

[chain]
# name = "ethereum_sepolia"                    # ethereum_sepolia | base_sepolia | anvil
# rpc_url = "https://sepolia.base.org"
# alkahest_address_config_path = "/path/to/alkahest.json"  # required for anvil

[registry]
# url = "http://localhost:8080"
# identity_registry_address = "0x..."          # ERC-8004 IdentityRegistry. Auto-defaults from chain.name
                                                # to the canonical CREATE2 vanity address; set only for
                                                # non-canonical deployments.

# ---------------------------------------------------------------------------
# Buyer-only (read by `market buy` / `market negotiate` / `market settle`)
# ---------------------------------------------------------------------------

# [buyer]
# default_token_address = "0x..."              # 0x ERC-20 address used when --token-contract is omitted.
                                                # Decimals + symbol are resolved on chain via [chain].rpc_url.

# [buyer.aggregation]
# policy = "best_price"                        # across-seller match policy: best_price (default) |
                                                # fastest_agreed | cheapest_first | registry_order |
                                                # random_shuffle | priceless_last | any custom name registered
                                                # via market_buyer.aggregation.register_aggregation_policy,
                                                # or a folder name under
                                                # $XDG_CONFIG_HOME/arkhai/aggregation_policies/.
# extra_policy_paths = []                      # additional directories to scan for file-based policies.
                                                # Each immediate subdirectory is treated as a policy named
                                                # after the folder; the subdir must contain a policy.py
                                                # exposing `factory(cfg) -> AggregationPolicy`.
# best_price_timeout = 30.0                    # optional wall-clock cap (seconds) for the `best_price`
                                                # policy. When set, candidates still negotiating at the
                                                # deadline are cancelled and the lowest agreed price among
                                                # those that completed wins. Unset = wait for all.

# ---------------------------------------------------------------------------
# Seller-only — uncomment the [seller] sections only on a host that runs
# `market-storefront serve`. The `market` CLI ignores them.
# ---------------------------------------------------------------------------

# [seller]
# agent_id = "alice"                           # must be a valid Python identifier
# port = 8000
# base_url = "http://alice:8000"
# db_path = "/var/lib/arkhai/agent.db"
# log_file_path = "/var/log/arkhai/agent.log"
# zerotier_network = ""

# [seller.provisioning]
# service_url = "http://localhost:8085"

# [seller.negotiation]
# policy_mode = "bisection"                    # "bisection" (default; no ML deps) | "rl" (requires torch)
"""


@config_app.command("init-user")
def config_init_user(
    overwrite: bool = typer.Option(
        False, "--overwrite",
        help="Replace an existing config.toml instead of refusing.",
    ),
) -> None:
    """Scaffold the user config.toml with placeholders for every known key.

    Writes only the commented-out skeleton so nothing breaks on first
    load. Fill in the values you need; the resolver treats missing keys
    as 'fall back to default', so a partial file is fine.
    """
    path = user_config_file()
    if path.exists() and not overwrite:
        typer.secho(
            f"{path} already exists. Pass --overwrite to replace it.",
            err=True, fg=typer.colors.RED,
        )
        raise typer.Exit(1)

    user_config_dir().mkdir(parents=True, exist_ok=True)
    path.write_text(_INIT_USER_TEMPLATE)
    typer.echo(f"Wrote {path}")
    typer.echo("Edit it, or use `market config set <key> <value>` to populate.")
