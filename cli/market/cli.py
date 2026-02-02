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

from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich import box

app = typer.Typer(no_args_is_help=True)
order_app = typer.Typer(no_args_is_help=True)
network_app = typer.Typer(no_args_is_help=True)
registry_app = typer.Typer(no_args_is_help=True)
dev_app = typer.Typer(no_args_is_help=True)

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
        help="Offer resource JSON.",
    ),
    demand: str = typer.Option(
        ...,
        "--d",
        "-d",
        help="Demand resource JSON.",
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


@order_app.command("update")
def order_update() -> None:
    """Update an existing order (stub)."""
    typer.echo("Not implemented: order update")


@order_app.command("cancel")
def order_cancel() -> None:
    """Cancel an order (stub)."""
    typer.echo("Not implemented: order cancel")


@order_app.command("history")
def order_history() -> None:
    """Show order history (stub)."""
    typer.echo("Not implemented: order history")


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


def _short_ts(value: str | None) -> str:
    if not value:
        return "-"
    return value.replace("T", " ")[:19]


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
        typer.secho(f"Failed to create order: {exc}", err=True, fg=typer.colors.RED)
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
    table = Table(title="Open Orders", box=box.SIMPLE_HEAVY)
    table.add_column("Order ID", style="bold")
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
            _shorten(str(order.get("order_id", "-")), 32),
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


@app.command()
def config() -> None:
    """Manage config (stub)."""
    typer.echo("Not implemented: config")


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
