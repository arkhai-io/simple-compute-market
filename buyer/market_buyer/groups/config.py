from __future__ import annotations

from pathlib import Path

import click
import typer
import yaml

from ..common import REPO_ROOT

config_app = typer.Typer(no_args_is_help=True)


def _init_env_file(
    component: str,
    env_dir: Path,
    overwrite: bool,
) -> None:
    """Create or overwrite a component .env file with safety checks.

    Rules:
    - If `.env` exists and `overwrite` is False, raise an error.
    - If `.env.local` or any other file containing `.env` exists, warn but still write `.env`.
    - Always write a `.env` file in `env_dir` when allowed.
    """
    env_path = env_dir / ".env"
    env_local_path = env_dir / ".env.local"

    if env_path.exists() and not overwrite:
        raise typer.BadParameter(
            f"{component}: {env_path} already exists. Use --overwrite to replace it."
        )

    has_env_local = env_local_path.exists()
    other_envs = []
    for candidate in env_dir.iterdir():
        name = candidate.name
        if ".env" not in name:
            continue
        if name in {".env", ".env.local", ".env.sample"}:
            continue
        other_envs.append(name)

    env_dir.mkdir(parents=True, exist_ok=True)
    env_path.write_text("", encoding="utf-8")

    if has_env_local or other_envs:
        suffix = ""
        if other_envs:
            suffix = f" (also found: {', '.join(sorted(other_envs))})"
        typer.secho(
            f"Warning: {component} has other env files present. Wrote {env_path}.{suffix}",
            fg=typer.colors.YELLOW,
        )
    else:
        typer.echo(f"Wrote {env_path}")


def _load_env_schema(schema_path: Path) -> dict:
    if not schema_path.exists():
        raise typer.BadParameter(f"Schema not found: {schema_path}")
    try:
        return yaml.safe_load(schema_path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        raise typer.BadParameter(f"Invalid schema YAML at {schema_path}: {exc}") from exc


def _prompt_for_value(key: str, spec: dict) -> tuple[str | None, str]:
    description = spec.get("description")
    required = bool(spec.get("required", False))
    default = spec.get("default", None)
    secret = bool(spec.get("secret", False))

    if description:
        typer.echo(f"{key}: {description}")

    hints: list[str] = ["ESC to skip"]
    if required:
        hints.append("required")
    if secret:
        hints.append("hidden input")
    hint_text = ", ".join(hints)
    default_suffix = f" [default: {default}]" if default is not None else ""
    prompt_text = f"{key}{default_suffix} ({hint_text}): "
    value, skipped = _read_line(prompt_text, secret=secret)
    if skipped:
        return None, "skipped"

    if value is None or value.strip() == "":
        if default is not None:
            return str(default), "default"
        # If required with no default, allow skip via empty input.
        if required:
            return None, "skipped-empty-required"
        return None, "empty"

    return value, "value"


def _write_env_tmp(
    env_dir: Path,
    values: list[tuple[str, str | None]],
) -> Path:
    env_dir.mkdir(parents=True, exist_ok=True)
    tmp_path = env_dir / ".env.tmp"
    lines: list[str] = []
    for key, value in values:
        if value is None:
            continue
        lines.append(f"{key}={value}")
    tmp_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return tmp_path


def _load_env_tmp(tmp_path: Path) -> list[tuple[str, str]]:
    if not tmp_path.exists():
        return []
    lines = tmp_path.read_text(encoding="utf-8").splitlines()
    values: list[tuple[str, str]] = []
    for line in lines:
        if not line or line.strip().startswith("#"):
            continue
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if not key:
            continue
        values.append((key, value))
    return values


def _read_line(prompt_text: str, *, secret: bool) -> tuple[str | None, bool]:
    typer.echo(prompt_text, nl=False)
    buf: list[str] = []
    while True:
        ch = click.getchar()
        if ch in ("\r", "\n"):
            break
        if ch == "\x1b":
            typer.echo()
            return None, True
        if ch in ("\b", "\x7f"):
            if buf:
                buf.pop()
                # Erase last character on the terminal.
                typer.echo("\b \b", nl=False)
            continue
        buf.append(ch)
        typer.echo("*" if secret else ch, nl=False)
    typer.echo()
    return "".join(buf), False


@config_app.command("init")
def config_init(
    component: str | None = typer.Argument(
        None,
        help="Component env to initialize (agent, provisioning, registry, zerotier).",
    ),
    overwrite: bool = typer.Option(
        False,
        "--overwrite",
        help="Overwrite existing .env.",
    ),
) -> None:
    """Initialize a component .env file."""
    if component is None:
        typer.secho(
            "Missing COMPONENT. Valid targets: agent, provisioning, registry, zerotier.\n"
            "Usage example: 'market config init agent' to create core/agent/.env",
            fg=typer.colors.RED,
        )
        raise typer.Exit(code=1)

    component_key = component.strip().lower()
    if component_key == "agent":
        target_dir = REPO_ROOT / "core" / "agent"
        schema_path = REPO_ROOT / "cli" / "config" / "agent.schema.yaml"
    elif component_key == "provisioning":
        target_dir = REPO_ROOT / "async-provisioning-service"
        schema_path = REPO_ROOT / "cli" / "config" / "provisioning.schema.yaml"
    elif component_key == "registry":
        target_dir = REPO_ROOT / "erc-8004-registry-py"
        schema_path = REPO_ROOT / "cli" / "config" / "registry.schema.yaml"
    elif component_key == "zerotier":
        target_dir = REPO_ROOT / "infra" / "zerotier"
        schema_path = REPO_ROOT / "cli" / "config" / "zerotier.schema.yaml"
    else:
        raise typer.BadParameter(
            "component must be one of: agent, provisioning, registry, zerotier"
        )

    env_path = target_dir / ".env"
    env_local_path = target_dir / ".env.local"
    if env_path.exists() and not overwrite:
        raise typer.BadParameter(
            f"{component_key}: {env_path} already exists. Use --overwrite to replace it."
        )

    has_env_local = env_local_path.exists()
    other_envs = []
    if target_dir.exists():
        for candidate in target_dir.iterdir():
            name = candidate.name
            if ".env" not in name:
                continue
            if name in {".env", ".env.local", ".env.sample"}:
                continue
            other_envs.append(name)

    schema = _load_env_schema(schema_path)
    fields = schema.get("fields", {})
    if not isinstance(fields, dict) or not fields:
        raise typer.BadParameter(f"No fields found in schema: {schema_path}")

    tmp_path = target_dir / ".env.tmp"
    values: list[tuple[str, str | None]] = []
    resumed_values: dict[str, str] = {}
    if tmp_path.exists():
        if typer.confirm(f"Found {tmp_path}. Resume from it?", default=True):
            resumed_values = dict(_load_env_tmp(tmp_path))
        else:
            tmp_path.unlink()

    for key, spec in fields.items():
        if not isinstance(spec, dict):
            raise typer.BadParameter(f"Invalid field spec for {key} in {schema_path}")
        is_secret = bool(spec.get("secret", False))
        try:
            if spec.get("generated", False):
                value = None
                status = "generated"
            elif key in resumed_values:
                value = resumed_values[key]
                status = "resumed"
            else:
                value, status = _prompt_for_value(key, spec)
        except typer.BadParameter:
            raise
        values.append((key, value))

        # Persist interim progress to a temp file
        _write_env_tmp(target_dir, values)

        if status == "resumed":
            display_value = "[hidden]" if is_secret else value
            typer.secho(f"{key}: {display_value}", fg=typer.colors.CYAN)
        elif status == "default":
            if is_secret:
                typer.secho(
                    f"{key}: used default value [hidden]",
                    fg=typer.colors.GREEN,
                )
            else:
                typer.secho(f"{key}: used default value {value}", fg=typer.colors.GREEN)
        elif status == "skipped":
            typer.secho(f"{key}: skipped", fg=typer.colors.YELLOW)
        elif status == "skipped-empty-required":
            typer.secho(f"{key}: skipped (required field)", fg=typer.colors.YELLOW)
        elif status == "empty":
            typer.secho(f"{key}: empty", fg=typer.colors.YELLOW)
        elif status == "generated":
            continue
        else:
            if is_secret:
                typer.secho(f"{key}: set to [hidden]", fg=typer.colors.GREEN)
            else:
                typer.secho(f"{key}: set to {value}", fg=typer.colors.GREEN)

    provided = {key: value for key, value in values if value is not None}
    missing_required = []
    for key, spec in fields.items():
        if not isinstance(spec, dict):
            continue
        if spec.get("generated", False):
            continue
        if not spec.get("required", False):
            continue
        if key not in provided or str(provided.get(key)).strip() == "":
            missing_required.append(key)

    if missing_required:
        typer.secho(
            "Missing required fields; leaving .env.tmp in place: "
            + ", ".join(missing_required),
            fg=typer.colors.RED,
        )
        typer.secho(
            "Run config init again to complete the missing fields and write the .env file.",
            fg=typer.colors.RED,
        )
        return

    if tmp_path.exists():
        tmp_path.replace(env_path)
        typer.echo(f"Wrote {env_path} from {tmp_path}")
    else:
        _write_env_tmp(target_dir, values).replace(env_path)
        typer.echo(f"Wrote {env_path}")

    if has_env_local or other_envs:
        suffix = ""
        if other_envs:
            suffix = f" (also found: {', '.join(sorted(other_envs))})"
        typer.secho(
            f"Warning: {component_key} has other env files present. Wrote {env_path}.{suffix}",
            fg=typer.colors.YELLOW,
        )


@config_app.command("path")
def config_path() -> None:
    """Print the path of the user config.toml (whether or not it exists)."""
    from ..config_loader import user_config_file
    p = user_config_file()
    typer.echo(str(p))
    if not p.exists():
        typer.secho("(not present — run `market config init-user` to scaffold it)",
                    fg=typer.colors.YELLOW)


@config_app.command("show")
def config_show(
    raw: bool = typer.Option(
        False, "--raw",
        help="Print the TOML file verbatim instead of the loaded mapping.",
    ),
) -> None:
    """Show the current user config."""
    from ..config_loader import load_user_config, user_config_file
    p = user_config_file()
    if not p.exists():
        typer.secho(f"No user config at {p}.", fg=typer.colors.YELLOW)
        raise typer.Exit(1)
    if raw:
        typer.echo(p.read_text())
        return
    cfg = load_user_config(p)
    import json
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
    from ..config_loader import load_user_config, set_dotted, user_config_file, write_user_config

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
    from ..config_loader import get_dotted, load_user_config, user_config_file
    doc = load_user_config()
    val = get_dotted(doc, key)
    if val is None:
        typer.secho(
            f"Key {key!r} not set in {user_config_file()}.",
            fg=typer.colors.YELLOW,
        )
        raise typer.Exit(1)
    if isinstance(val, (dict, list)):
        import json
        typer.echo(json.dumps(val, indent=2, sort_keys=True))
    else:
        typer.echo(str(val))


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
    as 'fall back to env / default' so a partial file is fine.
    """
    from ..config_loader import user_config_file, user_config_dir

    path = user_config_file()
    if path.exists() and not overwrite:
        typer.secho(
            f"{path} already exists. Pass --overwrite to replace it.",
            err=True, fg=typer.colors.RED,
        )
        raise typer.Exit(1)

    template = """\
# arkhai user config — see `market config path` for this file's location.
# Every key here is optional: if a key is missing, the resolver falls
# back to the matching env var, then to built-in defaults.
# Precedence: CLI flag > env var > this file > default.

# ---------------------------------------------------------------------------
# Shared (buyer + seller read these)
# ---------------------------------------------------------------------------

[wallet]
# address = "0x0000000000000000000000000000000000000000"
# private_key = "0x..."                        # prefer env AGENT_PRIV_KEY
# ssh_public_key = "ssh-ed25519 AAAA... user@host"

[chain]
# name = "ethereum_sepolia"                    # ethereum_sepolia | base_sepolia | anvil
# rpc_url = "https://sepolia.base.org"
# alkahest_address_config_path = "/path/to/alkahest.json"  # required for anvil

[registry]
# url = "http://localhost:8080"
# identity_registry_address = "0x..."          # ERC-8004 registry contract

# ---------------------------------------------------------------------------
# Seller-only (ignored if you're only running a buyer CLI)
# Every value below is optional; defaults apply when absent.
# ---------------------------------------------------------------------------

# [seller]
# agent_id = "alice"                           # must be a valid Python identifier
# agent_name = "Alice"                         # display name (any string)
# port = 8000
# base_url = "http://alice:8000"               # what peers dial; auto-resolved with ZeroTier if set
# db_path = "/var/lib/arkhai/agent.db"
# log_level = "INFO"                           # DEBUG | INFO | WARNING | ERROR
# log_file_path = "/var/log/arkhai/agent.log"
# token_registry_path = "/etc/arkhai/tokens.json"
# onchain_agent_id = ""                        # set by `market install --seller` + `market register`
# default_vm_host = "ww1"                      # KVM host name from ansible inventory
# zerotier_network = ""
# enable_registry_discovery = true
# max_discovery_agents = 10
# enable_order_retry = true
# order_retry_interval = 300
# resource_check_interval = 300
# resource_lease_grace_seconds = 1800
# negotiation_timeout_seconds = 1800           # mark stale threads terminal after this
# negotiation_watchdog_interval = 60
# event_validation_mode = "warn"
# enable_event_queue = false

# [seller.provisioning]
# service_url = "http://localhost:8085"
# timeout = 3600
# poll_interval = 15
# frp_server_addr = ""
# frp_domain = ""
# frp_dashboard_password = ""

# [seller.redis]
# enable = false
# url = "redis://localhost:6379"
# channels = "events:*"

# [seller.negotiation]
# policy_mode = ""                              # "" (default → rl) | "bisection" | "rl"
# seller_model_path = "domain/compute/agent/app/policy/models/arkhai_negotiator_seller.pt"
# buyer_model_path  = "domain/compute/agent/app/policy/models/arkhai_negotiator_buyer.pt"
"""
    user_config_dir().mkdir(parents=True, exist_ok=True)
    path.write_text(template)
    typer.echo(f"Wrote {path}")
    typer.echo("Edit it, or use `market config set <key> <value>` to populate.")
