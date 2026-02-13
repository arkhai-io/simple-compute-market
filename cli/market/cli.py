from __future__ import annotations

from pathlib import Path
import os
import subprocess
from importlib.metadata import version, PackageNotFoundError

import typer
import json
import textwrap
import urllib.parse
import urllib.request
import urllib.error

import yaml
import click
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich import box

app = typer.Typer(no_args_is_help=True)
order_app = typer.Typer(no_args_is_help=True)
network_app = typer.Typer(no_args_is_help=True)
registry_app = typer.Typer(no_args_is_help=True)
dev_app = typer.Typer(no_args_is_help=True)
config_app = typer.Typer(no_args_is_help=True)

REPO_ROOT = Path(__file__).resolve().parents[2]


def run_step(
    label: str,
    cmd: list[str],
    cwd: Path,
    extra_env: dict[str, str] | None = None,
) -> None:
    typer.echo(f"==> {label} at {cwd}")
    env = os.environ.copy()
    venv_path = cwd / ".venv"
    venv_bin = venv_path / "bin"
    if venv_bin.exists():
        env["VIRTUAL_ENV"] = str(venv_path)
        env["PATH"] = f"{venv_bin}{os.pathsep}{env.get('PATH', '')}"
    if extra_env:
        env.update(extra_env)
    subprocess.run(cmd, cwd=cwd, check=True, env=env)



def version_callback(value: bool) -> None:
    """Show version and exit."""
    if value:
        try:
            __version__ = version("market-cli")
        except PackageNotFoundError:
            __version__ = "unknown (not installed)"
        typer.echo(f"Market CLI version {__version__}")
        raise typer.Exit()

@app.callback()
def main(
    version_flag: bool = typer.Option(
        None,
        "--version",
        "-v",
        callback=version_callback,
        is_eager=True,
        help="Show version and exit.",
    ),
) -> None:
    """Market CLI - Unified interface for Arkhai market operations."""
    pass

@app.command()
def install(
    with_zerotier: bool = typer.Option(
        False,
        "--with-zerotier",
        help="Install ZeroTier (runs 'make install' in infra, requires sudo).",
    ),
) -> None:
    """Install dependencies for Agent and Registry.\nWith the --with-zerotier flag, also installs ZeroTier."""
    steps: list[tuple[str, list[str], Path]] = [
        (
            "Agent dependencies (uv sync)",
            ["make", "install"],
            REPO_ROOT / "agent",
        ),
        (
            "Registry dependencies (uv sync)",
            ["make", "install"],
            REPO_ROOT / "erc-8004-registry-py",
        ),
        (
            "Contracts dependencies (npm install)",
            ["npm", "install"],
            REPO_ROOT / "erc-8004-contracts",
        ),
    ]

    if with_zerotier:
        steps.append(
            (
                "ZeroTier install (requires sudo)",
                ["make", "install"],
                REPO_ROOT / "infra",
            )
        )

    for label, cmd, cwd in steps:
        run_step(label, cmd, cwd)

    typer.echo("Done.")

@order_app.command("create")
def order_create(
    offer: str = typer.Option(
        ...,
        "--offer",
        "-o",
        help="Offer resource JSON. Example: '{\"gpu_model\":\"H200\",\"quantity\":1,\"sla\":99.9,\"region\":\"California, US\"}'",

    ),
    demand: str = typer.Option(
        ...,
        "--demand",
        "-d",
        help="Demand resource JSON. Example: '{\"token\":\"MOCK\",\"amount\":9.0}'",
    ),
    agent_url: str | None = typer.Option(
        None,
        "--agent-url",
        "-a",
        help="Agent base URL (env: AGENT_URL or BASE_URL_OVERRIDE).",
    ),
    duration_hours: int | None = typer.Option(
        None,
        "--duration-hours",
        "-t",
        help="Order duration in hours (default: 1).",
    ),
) -> None:
    """Create a new order via the Agent endpoint."""
    base_url = agent_url or os.getenv("AGENT_URL") or os.getenv("BASE_URL_OVERRIDE") or "http://localhost:8000"
    base_url = _normalize_registry_url(base_url)
    duration = duration_hours if duration_hours is not None else 1
    if duration < 1:
        raise typer.BadParameter("duration-hours must be >= 1")

    try:
        offer_data = json.loads(offer)
        demand_data = json.loads(demand)
    except json.JSONDecodeError as exc:
        raise typer.BadParameter(f"Invalid JSON: {exc}") from exc

    if not isinstance(offer_data, dict) or not isinstance(demand_data, dict):
        raise typer.BadParameter("Offer and demand must be JSON objects")

    payload = {
        "offer": offer_data,
        "demand": demand_data,
        "duration_hours": duration,
    }
    url = f"{base_url}/orders/create"
    response = _post_json(url, payload)

    console = Console()
    table = Table.grid(padding=(0, 2))
    table.add_column(style="bold", no_wrap=True)
    table.add_column()
    table.add_row("Status", str(response.get("status", "-")))
    if "event_id" in response:
        table.add_row("Event ID", str(response.get("event_id")))
    if "order_id" in response:
        table.add_row("Order ID", str(response.get("order_id")))
    if "root_agent_response" in response:
        table.add_row("Agent", str(response.get("root_agent_response")))
    order_request = response.get("order_request")
    if isinstance(order_request, dict):
        offer_req = order_request.get("offer")
        demand_req = order_request.get("demand")
        if offer_req is not None:
            table.add_row("Offer", _format_resource(offer_req))
        if demand_req is not None:
            table.add_row("Demand", _format_resource(demand_req))
        if "duration_hours" in order_request:
            table.add_row("Duration (h)", str(order_request.get("duration_hours")))

    console.print(Panel(table, title="Order Create", border_style="green"))


@order_app.command("close")
def order_close(
    order_id: str = typer.Argument(
        ...,
        help="Order ID to close.",
    ),
    agent_url: str | None = typer.Option(
        None,
        "--agent-url",
        "-a",
        help="Agent base URL (env: AGENT_URL or BASE_URL_OVERRIDE).",
    ),
) -> None:
    """Close an order via the Agent endpoint."""
    base_url = agent_url or os.getenv("AGENT_URL") or os.getenv("BASE_URL_OVERRIDE") or "http://localhost:8000"
    base_url = _normalize_registry_url(base_url)
    if not order_id.strip():
        raise typer.BadParameter("order-id must be a non-empty string")

    payload = {"order_id": order_id}
    url = f"{base_url}/orders/close"
    response = _post_json(url, payload)

    console = Console()
    table = Table.grid(padding=(0, 2))
    table.add_column(style="bold", no_wrap=True)
    table.add_column()
    table.add_row("Status", str(response.get("status", "-")))
    table.add_row("Order ID", order_id)
    if "event_id" in response:
        table.add_row("Event ID", str(response.get("event_id")))
    if "root_agent_response" in response:
        table.add_row("Agent", str(response.get("root_agent_response")))

    console.print(Panel(table, title="Order Close", border_style="green"))


@order_app.command("history")
def order_history(
    env: str | None = typer.Option(
        None,
        "--env",
        "-e",
        help="Path to env file (default: agent/.env).",
    ),
) -> None:
    """Show order history from local SQLite."""
    env_path = Path(env) if env else REPO_ROOT / "agent" / ".env"
    db_path = _read_env_value(env_path, "AGENT_DB_PATH")
    if not db_path:
        typer.secho(f"AGENT_DB_PATH not found in {env_path}", err=True, fg=typer.colors.RED)
        raise typer.Exit(code=1)
    if not Path(db_path).exists():
        typer.secho(f"No local order database found at {db_path}", err=True, fg=typer.colors.RED)
        raise typer.Exit(code=1)

    try:
        import sqlite3

        conn = sqlite3.connect(db_path)
        try:
            cur = conn.cursor()
            cur.execute(
                """
                SELECT order_id, status, created_at, updated_at,
                       offer_resource, demand_resource, fulfillment_resource
                FROM orders
                ORDER BY created_at DESC
                """
            )
            rows = cur.fetchall()
        finally:
            conn.close()
    except Exception as exc:
        typer.secho(f"Failed to read local orders: {exc}", err=True, fg=typer.colors.RED)
        raise typer.Exit(code=1)

    if not rows:
        typer.echo("No local orders found.")
        return

    console = Console()
    table = Table(title="Order History", box=box.SIMPLE_HEAVY, expand=True)
    table.add_column("Order ID", style="bold", overflow="fold")
    table.add_column("Status")
    table.add_column("Offer")
    table.add_column("Demand")
    table.add_column("Fulfillment")
    table.add_column("Created", justify="right")
    table.add_column("Updated", justify="right")

    for row in rows:
        (
            order_id,
            status,
            created_at,
            updated_at,
            offer_resource,
            demand_resource,
            fulfillment_resource,
        ) = row
        offer_parsed = _parse_db_resource(offer_resource)
        demand_parsed = _parse_db_resource(demand_resource)
        fulfillment_parsed = _parse_db_resource(fulfillment_resource)

        offer_display = _format_resource(offer_parsed) if offer_parsed is not None else "-"
        demand_display = _format_resource(demand_parsed) if demand_parsed is not None else "-"
        fulfillment_display = _format_resource_full(fulfillment_parsed)

        table.add_row(
            str(order_id or "-"),
            str(status or "-"),
            offer_display if "\n" in offer_display else _shorten(offer_display, 120),
            demand_display if "\n" in demand_display else _shorten(demand_display, 120),
            fulfillment_display,
            _short_ts(created_at),
            _short_ts(updated_at),
        )

    console.print(table)


@order_app.command("match")
def order_match(
    order_id: str = typer.Argument(
        ...,
        help="Order ID to match (flip offer/demand).",
    ),
    registry_url: str = typer.Option(
        None,
        "--registry-url",
        "-r",
        help="Registry Indexer base URL (env: INDEXER_URL or REGISTRY_URL).",
    ),
    agent_url: str | None = typer.Option(
        None,
        "--agent-url",
        "-a",
        help="Agent base URL (env: AGENT_URL or BASE_URL_OVERRIDE).",
    ),
    duration_hours: int | None = typer.Option(
        None,
        "--duration-hours",
        "-t",
        help="Order duration in hours (default: from target order or 1).",
    ),
) -> None:
    """Match an existing order by flipping offer/demand and creating a new order."""
    if not order_id.strip():
        raise typer.BadParameter("order-id must be a non-empty string")

    base_registry_url = registry_url or os.getenv("INDEXER_URL") or os.getenv("REGISTRY_URL") or "http://localhost:8080"
    base_registry_url = _normalize_registry_url(base_registry_url)
    target_url = f"{base_registry_url}/orders/{order_id}"
    target_payload = _fetch_json(target_url)
    target_order = target_payload.get("order") if isinstance(target_payload, dict) and "order" in target_payload else target_payload
    if not isinstance(target_order, dict):
        raise typer.BadParameter("Registry response did not include an order object")

    offer_resource = _normalize_registry_resource(target_order.get("demand_resource"))
    demand_resource = _normalize_registry_resource(target_order.get("offer_resource"))
    if not isinstance(offer_resource, dict) or not isinstance(demand_resource, dict):
        raise typer.BadParameter("Target order is missing offer/demand resources")

    duration = duration_hours if duration_hours is not None else target_order.get("duration_hours", 1)
    if not isinstance(duration, int):
        try:
            duration = int(str(duration))
        except (TypeError, ValueError):
            raise typer.BadParameter("duration-hours must be an integer")
    if duration < 1:
        raise typer.BadParameter("duration-hours must be >= 1")

    payload = {
        "offer": offer_resource,
        "demand": demand_resource,
        "duration_hours": duration,
    }

    base_agent_url = agent_url or os.getenv("AGENT_URL") or os.getenv("BASE_URL_OVERRIDE") or "http://localhost:8000"
    base_agent_url = _normalize_registry_url(base_agent_url)
    create_url = f"{base_agent_url}/orders/create"
    response = _post_json(create_url, payload)

    console = Console()
    table = Table.grid(padding=(0, 2))
    table.add_column(style="bold", no_wrap=True)
    table.add_column()
    table.add_row("Status", str(response.get("status", "-")))
    if "event_id" in response:
        table.add_row("Event ID", str(response.get("event_id")))
    if "order_id" in response:
        table.add_row("Order ID", str(response.get("order_id")))
    if "root_agent_response" in response:
        table.add_row("Agent", str(response.get("root_agent_response")))

    console.print(Panel(table, title="Order Match", border_style="green"))


def _normalize_registry_url(raw_url: str) -> str:
    return raw_url.rstrip("/")


def _short_contract_address(value: str) -> str:
    if not value:
        return "-"
    if len(value) <= 12:
        return value
    return f"{value[:6]}…{value[-4:]}"


def _format_resource(resource: dict) -> str:
    if not resource:
        return "-"
    if not isinstance(resource, dict):
        return str(resource)
    is_compute = resource.get("type") == "compute" or "gpu_model" in resource
    if is_compute:
        ordered_keys = ("type", "gpu_model", "quantity", "sla", "region")
        lines = [f"{key}={resource[key]}" for key in ordered_keys if key in resource]
        extra_keys = sorted(k for k in resource.keys() if k not in ordered_keys)
        lines.extend(f"{key}={resource[key]}" for key in extra_keys)
        return "\n".join(lines) if lines else json.dumps(resource, separators=(",", ":"), sort_keys=True)

    token_payload = resource.get("token")
    is_token = resource.get("type") == "token" or isinstance(token_payload, dict) or "symbol" in resource
    if is_token:
        token_data = token_payload if isinstance(token_payload, dict) else resource
        symbol = token_data.get("symbol")
        decimals = token_data.get("decimals")
        amount = resource.get("amount", token_data.get("amount"))
        contract = token_data.get("contract_address")
        lines = []
        if symbol is not None:
            lines.append(f"symbol={symbol}")
        if decimals is not None:
            lines.append(f"decimals={decimals}")
        if amount is not None:
            lines.append(f"amount={amount}")
        if contract is not None:
            lines.append(f"contract_address={_short_contract_address(str(contract))}")
        return "\n".join(lines) if lines else json.dumps(resource, separators=(",", ":"), sort_keys=True)

    parts: list[str] = []
    for key in ("type", "region", "gpu_model", "sla", "symbol"):
        if key in resource:
            parts.append(f"{key}={resource[key]}")
    if parts:
        return ", ".join(parts)
    return json.dumps(resource, separators=(",", ":"), sort_keys=True)


def _shorten(text: str, width: int = 36) -> str:
    if not text:
        return "-"
    return textwrap.shorten(text, width=width, placeholder="…")


def _normalize_registry_resource(resource: dict) -> dict:
    """Convert registry token resource amounts to friendly units for create endpoint."""
    if not isinstance(resource, dict):
        return resource
    token = resource.get("token")
    amount = resource.get("amount")
    if isinstance(token, dict) and "decimals" in token and amount is not None:
        try:
            decimals = int(token["decimals"])
        except (TypeError, ValueError):
            return resource
        from decimal import Decimal, InvalidOperation
        try:
            amount_value = Decimal(str(amount))
        except (InvalidOperation, ValueError, TypeError):
            return resource
        human_amount = amount_value / (Decimal(10) ** decimals)
        normalized = dict(resource)
        normalized["amount"] = str(human_amount.normalize())
        return normalized
    return resource


def _short_ts(value: str | None) -> str:
    if not value:
        return "-"
    return value.replace("T", " ")[:19]


def _read_env_value(path: Path, key: str) -> str | None:
    if not path.exists():
        return None
    try:
        for raw_line in path.read_text().splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            if line.startswith("export "):
                line = line[len("export ") :].strip()
            if "=" not in line:
                continue
            name, value = line.split("=", 1)
            if name.strip() != key:
                continue
            value = value.strip()
            if len(value) >= 2 and value[0] == value[-1] and value[0] in ("\"", "'"):
                value = value[1:-1]
            return value
    except Exception:
        return None
    return None


def _parse_db_resource(value: str | None) -> dict | str | None:
    if value is None:
        return None
    if isinstance(value, str):
        try:
            return json.loads(value)
        except Exception:
            return value
    return value


def _format_resource_full(resource: dict | str | None) -> str:
    if resource is None or resource == "":
        return "-"
    if isinstance(resource, str):
        return resource
    try:
        return json.dumps(resource, separators=(",", ":"), sort_keys=True)
    except Exception:
        return str(resource)


def _fetch_json(url: str) -> dict:
    try:
        request = urllib.request.Request(url, headers={"Accept": "application/json"})
        with urllib.request.urlopen(request, timeout=10) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8") if exc.fp else str(exc)
        typer.secho(f"Registry error ({exc.code}): {detail}", err=True, fg=typer.colors.RED)
        raise typer.Exit(code=1)
    except Exception as exc:
        typer.secho(f"Failed to fetch orders: {exc}", err=True, fg=typer.colors.RED)
        raise typer.Exit(code=1)


def _post_json(url: str, payload: dict) -> dict:
    try:
        data = json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(
            url,
            data=data,
            headers={"Accept": "application/json", "Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=10) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8") if exc.fp else str(exc)
        typer.secho(f"Agent error ({exc.code}): {detail}", err=True, fg=typer.colors.RED)
        raise typer.Exit(code=1)
    except Exception as exc:
        typer.secho(f"Failed to call agent endpoint: {exc}", err=True, fg=typer.colors.RED)
        raise typer.Exit(code=1)


@order_app.command("list")
def order_list(
    registry_url: str = typer.Option(
        None,
        "--registry-url",
        "-r",
        help="Registry Indexer base URL (env: INDEXER_URL or REGISTRY_URL).",
    ),
    order_id: str | None = typer.Option(
        None,
        "--order-id",
        help="Filter by order ID.",
    ),
    limit: int = typer.Option(
        50,
        "--limit",
        "-l",
        help="Maximum orders to fetch (1-200).",
    ),
    offset: int = typer.Option(
        0,
        "--offset",
        "-o",
        help="Pagination offset.",
    ),
) -> None:
    """List open orders from the Registry Indexer."""
    base_url = registry_url or os.getenv("INDEXER_URL") or os.getenv("REGISTRY_URL") or "http://localhost:8080"
    base_url = _normalize_registry_url(base_url)
    if limit < 1 or limit > 200:
        raise typer.BadParameter("limit must be between 1 and 200")
    if offset < 0:
        raise typer.BadParameter("offset must be >= 0")

    query_params: dict[str, str | int] = {"status": "open", "limit": limit, "offset": offset}
    if order_id:
        query_params["order_id"] = order_id
    params = urllib.parse.urlencode(query_params)
    url = f"{base_url}/orders?{params}"

    payload = _fetch_json(url)

    items = payload.get("items", [])
    console = Console()
    table = Table(title="Open Orders", box=box.SIMPLE_HEAVY, expand=True)
    table.add_column("Order ID", style="bold", overflow="fold")
    table.add_column("Agent ID")
    table.add_column("Maker")
    table.add_column("Taker")
    table.add_column("Offer")
    table.add_column("Demand")
    table.add_column("Created", justify="right")

    for order in items:
        offer_display = _format_resource(order.get("offer_resource", {}))
        demand_display = _format_resource(order.get("demand_resource", {}))
        table.add_row(
            str(order.get("order_id", "-")),
            _shorten(str(order.get("agent_id", "-")), 32),
            _shorten(str(order.get("order_maker", "-")), 40),
            _shorten(str(order.get("order_taker", "-")), 40),
            offer_display if "\n" in offer_display else _shorten(offer_display, 120),
            demand_display if "\n" in demand_display else _shorten(demand_display, 120),
            _short_ts(order.get("created_at")),
        )

    if not items:
        console.print("No open orders found.")
        return

    console.print(table)


@order_app.command("show")
def order_show(
    order_id: str = typer.Argument(..., help="Order ID"),
    registry_url: str = typer.Option(
        None,
        "--registry-url",
        "-r",
        help="Registry Indexer base URL (env: INDEXER_URL or REGISTRY_URL).",
    ),
) -> None:
    """Show a single order by ID."""
    base_url = registry_url or os.getenv("INDEXER_URL") or os.getenv("REGISTRY_URL") or "http://localhost:8080"
    base_url = _normalize_registry_url(base_url)
    url = f"{base_url}/orders/{order_id}"
    payload = _fetch_json(url)
    found = payload.get("order", payload)

    console = Console()
    table = Table.grid(padding=(0, 2))
    table.add_column(style="bold", no_wrap=True)
    table.add_column()
    table.add_row("Order ID", str(found.get("order_id", "-")))
    table.add_row("Agent ID", str(found.get("agent_id", "-")))
    table.add_row("Status", str(found.get("status", "-")))
    table.add_row("Maker", str(found.get("order_maker", "-")))
    table.add_row("Taker", str(found.get("order_taker", "-")))
    table.add_row("Duration (h)", str(found.get("duration_hours", "-")))
    table.add_row("Created", _short_ts(found.get("created_at")))
    table.add_row("Updated", _short_ts(found.get("updated_at")))
    table.add_row("Offer", _format_resource(found.get("offer_resource", {})))
    table.add_row("Demand", _format_resource(found.get("demand_resource", {})))

    console.print(Panel(table, title="Market Order", border_style="blue"))


app.add_typer(order_app, name="order", help="Manage orders (see subcommands).")
app.add_typer(
    config_app,
    name="config",
    help="Manage market config (targets: agent, provisioning, registry, zerotier).",
)

@app.command()
def register(
    env: str | None = typer.Option(
        None,
        "--env",
        "-e",
        help="Path to env file passed as ENV_FILE to make register.",
    ),
) -> None:
    """Register agent on-chain (make register)."""
    cmd = ["make", "register"]
    if env:
        cmd.append(f"ENV_FILE={env}")
    run_step(
        "Register agent (make register)",
        cmd,
        REPO_ROOT / "agent",
    )


@app.command()
def start(
    env: str | None = typer.Option(
        None,
        "--env",
        "-e",
        help="Path to env file passed as ENV_FILE to make serve-a2a.",
    ),
) -> None:
    """Start Agent service."""
    cmd = ["make", "serve-a2a"]
    if env:
        cmd.append(f"ENV_FILE={env}")
    run_step(
        "Start agent (make serve-a2a)",
        cmd,
        REPO_ROOT / "agent",
    )


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
            "Usage example: 'market config init agent' to create agent/.env"
            ,
            fg=typer.colors.RED,
        )
        raise typer.Exit(code=1)

    component_key = component.strip().lower()
    if component_key == "agent":
        target_dir = REPO_ROOT / "agent"
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


@config_app.command("set")
def config_set(
    attr: str = typer.Argument(..., help="Config attribute to set."),
    value: str = typer.Argument(..., help="Value to assign."),
) -> None:
    """Set a market config value (stub)."""
    typer.echo(f"Not implemented: market config set {attr} {value}")


@config_app.command("get")
def config_get(
    attr: str = typer.Argument(..., help="Config attribute to read."),
) -> None:
    """Get a market config value (stub)."""
    typer.echo(f"Not implemented: market config get {attr}")


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


@network_app.command("get-peers")
def network_get_peers() -> None:
    """Get network peers."""
    run_step(
        "Get ZeroTier peers (make get-peers)",
        ["make", "get-peers"],
        REPO_ROOT / "infra",
    )


app.add_typer(network_app, name="network", help="Manage ZeroTier network, mainly for market admins (see subcommands).")

@registry_app.command("start")
def registry_start() -> None:
    """Start the Registry Indexer server."""
    run_step(
        "Start Registry Indexer (make serve)",
        ["make", "serve"],
        REPO_ROOT / "erc-8004-registry-py",
    )


app.add_typer(registry_app, name="registry", help="As Market Admin, manage the Registry Indexer server.")

@dev_app.command("test-env")
def dev_test_env() -> None:
    """As a Developer, run the Anvil test env."""
    run_step(
        "Start Anvil test env (make test-env)",
        ["make", "test-env"],
        REPO_ROOT / "agent",
    )


@dev_app.command("deploy-registry")
def dev_deploy_registry(
    rpc_url: str = typer.Option(
        ...,
        "--rpc-url",
        "-r",
        help="RPC URL to deploy against (sets ANVIL_RPC_URL).",
    ),
) -> None:
    """As a Developer, deploy the ERC-8004 contracts to the given RPC_URL."""
    run_step(
        f"Deploy ERC-8004 contracts to {rpc_url}",
        ["npm", "run", "deploy:anvil"],
        REPO_ROOT / "erc-8004-contracts",
        {"ANVIL_RPC_URL": rpc_url},
    )


app.add_typer(dev_app, name="dev", help="Developer utilities (local chain and contract deploy).")


if __name__ == "__main__":
    app()
