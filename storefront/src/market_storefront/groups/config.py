"""`market-storefront config` — inspect or edit the user storefront.toml.

Mirrors the buyer-side `market config` surface: path / show / get /
set / init-user. Operates on `$XDG_CONFIG_HOME/arkhai/storefront.toml`
(distinct from the buyer's `config.toml`), so a host that runs both
buyer and seller keeps its two roles' state separate.
"""

from __future__ import annotations

import json

import typer

from service.config_loader import (
    get_dotted,
    load_storefront_config,
    load_user_config,
    set_dotted,
    storefront_config_file,
    user_config_dir,
    write_user_config,
)


config_app = typer.Typer(no_args_is_help=True)


@config_app.command("path")
def config_path() -> None:
    """Print the path of the storefront's user storefront.toml."""
    p = storefront_config_file()
    typer.echo(str(p))
    if not p.exists():
        typer.secho(
            "(not present — run `market-storefront config init-user` to scaffold it)",
            fg=typer.colors.YELLOW,
        )


@config_app.command("show")
def config_show(
    raw: bool = typer.Option(
        False, "--raw",
        help="Print the TOML file verbatim instead of the loaded mapping.",
    ),
) -> None:
    """Show the current storefront config."""
    p = storefront_config_file()
    if not p.exists():
        typer.secho(f"No storefront config at {p}.", fg=typer.colors.YELLOW)
        raise typer.Exit(1)
    if raw:
        typer.echo(p.read_text())
        return
    cfg = load_storefront_config()
    typer.echo(json.dumps(cfg, indent=2, sort_keys=True))


@config_app.command("set")
def config_set(
    key: str = typer.Argument(..., help="Dotted config key, e.g. 'seller.port'."),
    value: str = typer.Argument(..., help="Value to assign (coerced to int/float/bool when possible)."),
) -> None:
    """Set a single value in the storefront's storefront.toml.

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

    path = storefront_config_file()
    doc = load_user_config(path)
    set_dotted(doc, key, coerced)
    written = write_user_config(doc, path)
    typer.echo(f"Set {key} = {coerced!r} in {written}")


@config_app.command("get")
def config_get(
    key: str = typer.Argument(..., help="Dotted config key, e.g. 'seller.port'."),
) -> None:
    """Print the value of a single config key from the storefront's storefront.toml."""
    doc = load_storefront_config()
    val = get_dotted(doc, key)
    if val is None:
        typer.secho(
            f"Key {key!r} not set in {storefront_config_file()}.",
            fg=typer.colors.YELLOW,
        )
        raise typer.Exit(1)
    if isinstance(val, (dict, list)):
        typer.echo(json.dumps(val, indent=2, sort_keys=True))
    else:
        typer.echo(str(val))


_INIT_USER_TEMPLATE = """\
# arkhai seller config — see `market-storefront config path` for this
# file's location. Every key is optional; the resolver falls back to
# built-in defaults when a key is missing.

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
# identity_registry_address = "0x..."          # ERC-8004 registry contract

# ---------------------------------------------------------------------------
# Seller — required to run `market-storefront serve`.
# ---------------------------------------------------------------------------

[seller]
# agent_id = "alice"                           # must be a valid Python identifier
# agent_name = "Alice"                         # display name (any string)
# port = 8000
# base_url = "http://alice:8000"               # what peers dial; auto-resolved with ZeroTier if set
# db_path = "/var/lib/arkhai/agent.db"
# log_level = "INFO"                           # DEBUG | INFO | WARNING | ERROR
# log_file_path = "/var/log/arkhai/agent.log"
# onchain_agent_id = ""                        # populated by `market-storefront register`
# default_vm_host = "ww1"                      # KVM host name from ansible inventory
# zerotier_network = ""
# enable_registry_discovery = true
# max_discovery_agents = 10
# enable_order_retry = true
# order_retry_interval = 300
# resource_check_interval = 300
# resource_lease_grace_seconds = 1800
# negotiation_timeout_seconds = 1800
# negotiation_watchdog_interval = 60

[seller.provisioning]
# service_url = "http://localhost:8085"
# timeout = 3600
# poll_interval = 15
# preflight_timeout = 30                        # how long startup waits for /health to come up
# fail_on_unreachable = true                    # set false in dev when service comes up later
# frp_server_addr = ""
# frp_domain = ""
# frp_dashboard_password = ""

[seller.negotiation]
# policy_mode = "bisection"                    # "bisection" (default; no ML deps) | "rl" (requires torch)
# seller_model_path = "domain/compute/agent/app/policy/models/arkhai_negotiator_seller.pt"
# buyer_model_path  = "domain/compute/agent/app/policy/models/arkhai_negotiator_buyer.pt"

[seller.pricing]
# default_min_price = "1000000"                # raw token base units (per-hour rate); fallback for blank min_price.
                                                # Also the negotiation floor for hidden-reserve listings.
# default_token_address = "0x..."              # 0x ERC-20 address used when CSV row has no token column;
                                                # also the demand-side token for the resource-imbalance policy
# default_max_duration_seconds = 86400         # advertised lease ceiling; 0/unset = unlimited
# publish_priceless = false                    # publish rows without a min_price as demand.amount=null
                                                # (hidden reserve; buyer proposes; seller negotiates against
                                                # default_min_price as the floor). Per-row min_price="0"
                                                # publishes as demand.amount=0 (free / public-test offering),
                                                # distinct from hidden reserve.
"""


@config_app.command("init-user")
def config_init_user(
    overwrite: bool = typer.Option(
        False, "--overwrite",
        help="Replace an existing storefront.toml instead of refusing.",
    ),
) -> None:
    """Scaffold the storefront's storefront.toml with placeholders for every known key.

    Writes only the commented-out skeleton so nothing breaks on first
    load. Fill in the values you need; the resolver treats missing keys
    as 'fall back to default', so a partial file is fine.
    """
    path = storefront_config_file()
    if path.exists() and not overwrite:
        typer.secho(
            f"{path} already exists. Pass --overwrite to replace it.",
            err=True, fg=typer.colors.RED,
        )
        raise typer.Exit(1)

    user_config_dir().mkdir(parents=True, exist_ok=True)
    path.write_text(_INIT_USER_TEMPLATE)
    typer.echo(f"Wrote {path}")
    typer.echo("Edit it, or use `market-storefront config set <key> <value>` to populate.")
