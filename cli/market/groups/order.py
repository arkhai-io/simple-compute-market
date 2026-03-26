from __future__ import annotations

from pathlib import Path
import os
import json
import textwrap
import time
import urllib.parse
import urllib.request
import urllib.error

import typer
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich import box

from ..common import REPO_ROOT

order_app = typer.Typer(no_args_is_help=True)


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
    env: str | None = typer.Option(
        None,
        "--env",
        "-e",
        help="Path to env file used to read BASE_URL_OVERRIDE.",
    ),
    duration_hours: int | None = typer.Option(
        None,
        "--duration-hours",
        "-t",
        help="Order duration in hours (default: 1).",
    ),
) -> None:
    """Create a new order via the Agent endpoint."""
    env_path = Path(env) if env else None
    env_base_url = _read_env_value(env_path, "BASE_URL_OVERRIDE") if env_path else None
    base_url = agent_url or env_base_url or os.getenv("AGENT_URL") or os.getenv("BASE_URL_OVERRIDE") or "http://localhost:8000"
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

    private_key = (
        (_read_env_value(env_path, "AGENT_PRIV_KEY") if env_path else None)
        or os.getenv("AGENT_PRIV_KEY")
    )
    wallet_address = (
        (_read_env_value(env_path, "AGENT_WALLET_ADDRESS") if env_path else None)
        or os.getenv("AGENT_WALLET_ADDRESS")
        or ""
    )
    payload = {
        "offer": offer_data,
        "demand": demand_data,
        "duration_hours": duration,
    }
    url = f"{base_url}/orders/create"
    response = _post_json(url, payload, _get_auth_headers("create_order", wallet_address, private_key))

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
    env: str | None = typer.Option(
        None,
        "--env",
        "-e",
        help="Path to env file used to read BASE_URL_OVERRIDE and AGENT_PRIV_KEY.",
    ),
) -> None:
    """Close an order via the Agent endpoint."""
    env_path = Path(env) if env else None
    env_base_url = _read_env_value(env_path, "BASE_URL_OVERRIDE") if env_path else None
    base_url = agent_url or env_base_url or os.getenv("AGENT_URL") or os.getenv("BASE_URL_OVERRIDE") or "http://localhost:8000"
    base_url = _normalize_registry_url(base_url)
    if not order_id.strip():
        raise typer.BadParameter("order-id must be a non-empty string")

    private_key = (
        (_read_env_value(env_path, "AGENT_PRIV_KEY") if env_path else None)
        or os.getenv("AGENT_PRIV_KEY")
    )
    payload = {"order_id": order_id}
    url = f"{base_url}/orders/close"
    response = _post_json(url, payload, _get_auth_headers("close_order", order_id, private_key))

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
        help="Path to env file (default: core/agent/.env).",
    ),
) -> None:
    """Show order history from local SQLite."""
    env_path = Path(env) if env else REPO_ROOT / "core" / "agent" / ".env"
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
    table.add_column("Fulfillment", overflow="fold")
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
    env: str | None = typer.Option(
        None,
        "--env",
        "-e",
        help="Path to env file used to read BASE_URL_OVERRIDE and AGENT_PRIV_KEY.",
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

    env_path = Path(env) if env else None
    env_base_url = _read_env_value(env_path, "BASE_URL_OVERRIDE") if env_path else None
    base_agent_url = agent_url or env_base_url or os.getenv("AGENT_URL") or os.getenv("BASE_URL_OVERRIDE") or "http://localhost:8000"
    base_agent_url = _normalize_registry_url(base_agent_url)
    private_key = (
        (_read_env_value(env_path, "AGENT_PRIV_KEY") if env_path else None)
        or os.getenv("AGENT_PRIV_KEY")
    )
    create_url = f"{base_agent_url}/orders/create"
    response = _post_json(create_url, payload, _get_auth_headers("create_order", base_agent_url, private_key))

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


def _get_auth_headers(operation: str, resource_id: str, private_key: str | None) -> dict[str, str]:
    """Build X-Signature / X-Timestamp headers for a CLI→agent request.

    Returns an empty dict if no private_key is provided or if eth_account is
    not installed (request is sent unsigned; the agent will reject it if it
    requires auth).
    """
    if not private_key:
        return {}
    try:
        from eth_account import Account
        from eth_account.messages import encode_defunct
    except ImportError:
        return {}
    ts = int(time.time())
    message = f"{operation}:{resource_id}:{ts}"
    msg_hash = encode_defunct(text=message)
    sig = Account.sign_message(msg_hash, private_key).signature.hex()
    return {"X-Signature": sig, "X-Timestamp": str(ts)}


def _get_cli_http_timeout() -> float:
    raw = os.getenv("MARKET_CLI_HTTP_TIMEOUT", "120")
    default_value = 120.0
    try:
        timeout = float(raw)
    except ValueError:
        return default_value
    if timeout <= 0:
        return default_value
    return timeout


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


def _post_json(url: str, payload: dict, extra_headers: dict[str, str] | None = None) -> dict:
    try:
        data = json.dumps(payload).encode("utf-8")
        headers = {"Accept": "application/json", "Content-Type": "application/json"}
        if extra_headers:
            headers.update(extra_headers)
        request = urllib.request.Request(
            url,
            data=data,
            headers=headers,
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=_get_cli_http_timeout()) as response:
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
    env: str | None = typer.Option(
        None,
        "--env",
        "-e",
        help="Path to env file (reads AGENT_DB_PATH for local DB queries).",
    ),
    db: str | None = typer.Option(
        None,
        "--db",
        help="Explicit path to the agent SQLite DB.",
    ),
    negotiation: bool = typer.Option(
        False,
        "--negotiation",
        "-n",
        help="Show negotiation message history for this order.",
    ),
    credentials: bool = typer.Option(
        False,
        "--credentials",
        "-c",
        help="Show credentials associated with this order.",
    ),
    show_password: bool = typer.Option(
        False,
        "--show-password",
        "-p",
        help="Reveal credential passwords in plain text (implies --credentials).",
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

    if show_password:
        credentials = True

    if not (negotiation or credentials):
        return

    db_path = _resolve_db_path(db, env)
    if not db_path:
        typer.secho(
            "Local DB not found. Pass --db <path> or --env <envfile> with AGENT_DB_PATH set.",
            err=True,
            fg=typer.colors.YELLOW,
        )
        return

    import sqlite3

    if negotiation:
        _print_negotiation_table(console, db_path, order_id)

    if credentials:
        _print_credentials_table(console, db_path, order_id, show_password=show_password)


def _resolve_db_path(db: str | None, env: str | None) -> str | None:
    """Return the SQLite DB path from explicit arg, env file, or env var."""
    if db:
        return db
    env_path = Path(env) if env else REPO_ROOT / "core" / "agent" / ".env"
    value = _read_env_value(env_path, "AGENT_DB_PATH")
    if value and Path(value).exists():
        return value
    # Fallback: check env var directly
    from_env = os.getenv("AGENT_DB_PATH")
    if from_env and Path(from_env).exists():
        return from_env
    return None


def _negotiation_price_decimals(db_path: str, order_id: str) -> int:
    """Return the token decimals for an order by reading its token resource from SQLite."""
    try:
        import sqlite3

        conn = sqlite3.connect(db_path)
        try:
            cur = conn.cursor()
            cur.execute(
                "SELECT offer_resource, demand_resource FROM orders WHERE order_id = ?",
                (order_id,),
            )
            row = cur.fetchone()
        finally:
            conn.close()
        if not row:
            return 0
        for raw in row:
            try:
                resource = json.loads(raw) if isinstance(raw, str) else raw
                token = resource.get("token") if isinstance(resource, dict) else None
                if isinstance(token, dict) and "decimals" in token:
                    return int(token["decimals"])
            except Exception:
                continue
    except Exception:
        pass
    return 0


def _fmt_price(price: int | None, decimals: int) -> str:
    if price is None:
        return "-"
    if decimals == 0:
        return str(price)
    from decimal import Decimal
    return str((Decimal(price) / Decimal(10) ** decimals).normalize())


def _print_negotiation_table(console: Console, db_path: str, order_id: str) -> None:
    """Query negotiation_messages for this order and print as a table."""
    try:
        import sqlite3

        conn = sqlite3.connect(db_path)
        try:
            cur = conn.cursor()
            # negotiation_id is sorted(order_a, order_b) joined by '_'.
            # UUIDs don't contain '_', so LIKE matching is unambiguous.
            cur.execute(
                """
                SELECT negotiation_id, round, sender, our_price, their_price,
                       proposed_price, action_taken, message_type, timestamp
                FROM negotiation_messages
                WHERE negotiation_id LIKE ? OR negotiation_id LIKE ?
                ORDER BY negotiation_id, round ASC
                """,
                (f"{order_id}_%", f"%_{order_id}"),
            )
            rows = cur.fetchall()
        finally:
            conn.close()
    except Exception as exc:
        typer.secho(f"Failed to read negotiation history: {exc}", err=True, fg=typer.colors.RED)
        return

    if not rows:
        console.print("\n[dim]No negotiation history found for this order.[/dim]")
        return

    decimals = _negotiation_price_decimals(db_path, order_id)

    table = Table(title="Negotiation History", box=box.SIMPLE_HEAVY, expand=True)
    table.add_column("Round", justify="right", style="bold", no_wrap=True)
    table.add_column("Sender", overflow="fold")
    table.add_column("Our Price", justify="right")
    table.add_column("Their Price", justify="right")
    table.add_column("Proposed", justify="right")
    table.add_column("Action")
    table.add_column("Type")
    table.add_column("Timestamp", justify="right")

    prev_neg_id = None
    for neg_id, rnd, sender, our_price, their_price, proposed, action, msg_type, ts in rows:
        if prev_neg_id and neg_id != prev_neg_id:
            table.add_section()
        prev_neg_id = neg_id
        # Shorten sender URL to last component (agent hostname or port)
        sender_short = sender.rstrip("/").rsplit("/", 1)[-1] if "/" in sender else sender
        table.add_row(
            str(rnd),
            sender_short,
            _fmt_price(our_price, decimals),
            _fmt_price(their_price, decimals),
            _fmt_price(proposed, decimals),
            str(action or "-"),
            str(msg_type or "-"),
            _short_ts(ts),
        )

    console.print(table)


def _print_credentials_table(console: Console, db_path: str, order_id: str, *, show_password: bool = False) -> None:
    """Query credentials for this order and print as a table."""
    try:
        import sqlite3

        conn = sqlite3.connect(db_path)
        try:
            cur = conn.cursor()
            cur.execute(
                """
                SELECT role, granted_to, password, ssh_commands, ssh_key_path_host, key_type
                FROM credentials
                WHERE order_id = ?
                ORDER BY role
                """,
                (order_id,),
            )
            rows = cur.fetchall()
        finally:
            conn.close()
    except Exception as exc:
        typer.secho(f"Failed to read credentials: {exc}", err=True, fg=typer.colors.RED)
        return

    if not rows:
        console.print("\n[dim]No credentials found for this order.[/dim]")
        return

    table = Table(title="Credentials", box=box.SIMPLE_HEAVY, expand=True)
    table.add_column("Role", style="bold", no_wrap=True)
    table.add_column("Granted To", no_wrap=True)
    table.add_column("Password")
    table.add_column("SSH Commands", overflow="fold")
    table.add_column("Key Path", overflow="fold")
    table.add_column("Key Type", no_wrap=True)

    for role, granted_to, password, ssh_commands, ssh_key_path_host, key_type in rows:
        # Parse ssh_commands JSON if present, show as newline-separated values
        ssh_display = "-"
        if ssh_commands:
            try:
                cmds = json.loads(ssh_commands)
                if isinstance(cmds, dict):
                    ssh_display = "\n".join(f"{k}: {v}" for k, v in cmds.items())
                else:
                    ssh_display = str(cmds)
            except Exception:
                ssh_display = ssh_commands

        table.add_row(
            str(role or "-"),
            str(granted_to or "-"),
            (str(password) if show_password else "••••••••") if password else "-",
            ssh_display,
            str(ssh_key_path_host or "-"),
            str(key_type or "-"),
        )

    console.print(table)
