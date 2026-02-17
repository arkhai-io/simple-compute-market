from __future__ import annotations

import json
import os
import urllib.parse
import urllib.request
import urllib.error

import typer
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich import box

from market.helpers import (
    _fetch_json,
    _format_resource,
    _resolve_agent_url,
    _short_ts,
    _shorten,
)

agent_app = typer.Typer(no_args_is_help=True)

_STATUS_STYLES = {
    "active": "yellow", "success": "green", "failure": "red",
    "timeout": "dim red", "superseded": "dim",
}
_ACTION_STYLES = {
    "ACCEPT_OFFER": "green", "REJECT_OFFER": "red", "COUNTER_OFFER": "yellow",
    "EXIT_NEGOTIATION": "dim red", "MAKE_OFFER": "cyan",
}


def _styled(value: str | None, styles: dict[str, str]) -> str:
    if value is None:
        return "-"
    style = styles.get(value)
    return f"[{style}]{value}[/{style}]" if style else value


def _d(value) -> str:
    """Display a value, substituting '-' for None."""
    return str(value) if value is not None else "-"


def _format_json(raw) -> str | None:
    if raw is None:
        return None
    try:
        return json.dumps(raw if isinstance(raw, dict) else json.loads(raw), indent=2)
    except Exception:
        return str(raw)


def _detail_grid(rows: list[tuple[str, str]]) -> Table:
    grid = Table.grid(padding=(0, 2))
    grid.add_column(style="bold", no_wrap=True)
    grid.add_column()
    for label, value in rows:
        grid.add_row(label, value)
    return grid


# ---------------------------------------------------------------------------
# API-based commands (require running agent)
# ---------------------------------------------------------------------------

@agent_app.command("orders")
def agent_orders(
    status: str | None = typer.Option(
        None, "--status", help="Filter by status (open, matched, fulfilled, etc.).",
    ),
    limit: int = typer.Option(50, "--limit", "-l", help="Maximum orders to fetch."),
    agent_url: str | None = typer.Option(
        None, "--agent-url", "-a", help="Agent base URL (env: AGENT_URL or BASE_URL_OVERRIDE).",
    ),
) -> None:
    """List orders from the running agent API."""
    base_url = _resolve_agent_url(agent_url)
    params: dict[str, str] = {}
    if status:
        params["status"] = status
    if limit:
        params["limit"] = str(limit)
    qs = urllib.parse.urlencode(params)
    data = _fetch_json(f"{base_url}/orders" + (f"?{qs}" if qs else ""))
    orders = data.get("orders", [])

    console = Console()
    if not orders:
        console.print("[dim]No orders found.[/dim]")
        return

    table = Table(title="Agent Orders", box=box.SIMPLE_HEAVY, expand=True)
    table.add_column("Order ID", style="bold", overflow="fold")
    table.add_column("Status")
    table.add_column("Escrow UID")
    table.add_column("Updated", justify="right")
    for o in orders:
        table.add_row(
            _d(o.get("order_id")), _d(o.get("status")),
            _d(o.get("escrow_uid")), _short_ts(o.get("updated_at")),
        )
    console.print(table)
    console.print(f"Total: {data.get('total', len(orders))}")


def _fetch_json_with_headers(url: str, headers: dict[str, str] | None = None) -> dict | None:
    """Fetch JSON from a URL with optional custom headers. Returns None on failure."""
    try:
        req_headers = {"Accept": "application/json"}
        if headers:
            req_headers.update(headers)
        request = urllib.request.Request(url, headers=req_headers)
        with urllib.request.urlopen(request, timeout=10) as response:
            return json.loads(response.read().decode("utf-8"))
    except Exception:
        return None


def _build_agent_id_erc8004() -> str | None:
    """Build ERC-8004 agent ID from env vars: eip155:{chain_id}:{registry}:{agent_id}."""
    chain_id = os.getenv("CHAIN_ID")
    registry = os.getenv("IDENTITY_REGISTRY_ADDRESS")
    onchain_id = os.getenv("ONCHAIN_AGENT_ID")
    if chain_id and registry and onchain_id:
        return f"eip155:{chain_id}:{registry}:{onchain_id}"
    return None


@agent_app.command("order")
def agent_order(
    order_id: str = typer.Argument(..., help="Order ID to look up."),
    agent_url: str | None = typer.Option(
        None, "--agent-url", "-a", help="Agent base URL (env: AGENT_URL or BASE_URL_OVERRIDE).",
    ),
    provisioning_url: str | None = typer.Option(
        None, "--provisioning-url",
        help="Provisioning service URL (env: PROVISIONING_SERVICE_URL, default: http://localhost:8081).",
    ),
    agent_id: str | None = typer.Option(
        None, "--agent-id",
        help="ERC-8004 agent ID for provisioning queries (env: auto-built from CHAIN_ID, IDENTITY_REGISTRY_ADDRESS, ONCHAIN_AGENT_ID).",
    ),
) -> None:
    """Show a single order with attestations, negotiation summary, and provisioned VM credentials."""
    base_url = _resolve_agent_url(agent_url)
    data = _fetch_json(f"{base_url}/orders/{order_id}")
    console = Console()

    # --- Panel 1: Order Detail ---
    detail_rows = [
        ("Order ID", _d(data.get("order_id"))),
        ("Status", _d(data.get("status"))),
        ("Maker", _d(data.get("order_maker"))),
        ("Taker", _d(data.get("order_taker"))),
        ("Offer", _format_resource(data.get("offer_resource", {}))),
        ("Demand", _format_resource(data.get("demand_resource", {}))),
        ("Duration (h)", _d(data.get("duration_hours"))),
        ("Escrow UID", _d(data.get("escrow_uid"))),
        ("Created", _short_ts(data.get("created_at"))),
        ("Updated", _short_ts(data.get("updated_at"))),
    ]
    console.print(Panel(_detail_grid(detail_rows), title="Order Detail", border_style="blue"))

    # --- Panel 2: Attestations ---
    attestation_rows = [
        ("Escrow UID", _d(data.get("escrow_uid"))),
        ("Maker Attestation", _d(data.get("maker_attestation"))),
        ("Taker Attestation", _d(data.get("taker_attestation"))),
    ]
    console.print(Panel(_detail_grid(attestation_rows), title="Attestations", border_style="green"))

    # --- Panel 3: Negotiation Summary ---
    try:
        negotiations_data = _fetch_json(f"{base_url}/negotiations?order_id={order_id}")
        negotiations = negotiations_data.get("negotiations", [])
        if negotiations:
            neg = negotiations[0]  # Most relevant thread for this order
            neg_id = neg.get("negotiation_id")
            # Fetch full detail for the thread
            thread_data = _fetch_json(f"{base_url}/negotiations/{neg_id}")

            messages = thread_data.get("messages", [])
            prices: list[str] = []
            for m in messages:
                price_val = m.get("proposed_price") or m.get("our_price") or m.get("their_price")
                if price_val is not None:
                    prices.append(f"R{m.get('round', '?')}: {price_val}")

            agreed = thread_data.get("agreed_price")
            if prices:
                if agreed is not None:
                    prices.append(f"Agreed: {agreed}")
                progression = " → ".join(prices)
            elif agreed is not None:
                progression = str(agreed) + " (instant match)"
            else:
                progression = "-"

            neg_rows = [
                ("Negotiation ID", _d(neg_id)),
                ("Terminal State", _d(thread_data.get("terminal_state"))),
                ("Rounds", _d(thread_data.get("round_count") if "round_count" in thread_data else len(messages))),
                ("Agreed Price", _d(thread_data.get("agreed_price"))),
                ("Strategy", _d(thread_data.get("our_strategy"))),
                ("Initial Price", _d(thread_data.get("our_initial_price"))),
                ("Price Progression", progression),
            ]
            console.print(Panel(_detail_grid(neg_rows), title="Negotiation Summary", border_style="cyan"))
        else:
            console.print("[dim]No negotiation threads found for this order.[/dim]")
    except Exception:
        console.print("[dim]Could not fetch negotiation data.[/dim]")

    # --- Panel 4: Provisioned VM Credentials ---
    prov_url = provisioning_url or os.getenv("PROVISIONING_SERVICE_URL") or "http://localhost:8081"
    prov_url = prov_url.rstrip("/")
    erc_agent_id = agent_id or _build_agent_id_erc8004()

    if erc_agent_id:
        prov_data = _fetch_json_with_headers(
            f"{prov_url}/provisioned",
            headers={"X-Agent-ID": erc_agent_id},
        )
        if prov_data and isinstance(prov_data, dict):
            vms = prov_data.get("vms", prov_data.get("machines", []))
            if isinstance(vms, list):
                matched = [
                    vm for vm in vms
                    if vm.get("seller_order_id") == order_id or vm.get("buyer_order_id") == order_id
                ]
                if matched:
                    vm = matched[0]
                    cred_rows = [
                        ("VM ID", _d(vm.get("id"))),
                        ("VM Name", _d(vm.get("vm_name"))),
                        ("State", _d(vm.get("vm_state"))),
                        ("Host", _d(vm.get("vm_host"))),
                        ("Internal IP", _d(vm.get("vm_ip_internal"))),
                        ("SSH Port", _d(vm.get("external_ssh_port"))),
                        ("FRP Domain", _d(vm.get("frp_domain"))),
                        ("Escrow UID", _d(vm.get("escrow_uid"))),
                    ]
                    # Seller credentials (root)
                    if vm.get("root_password") or vm.get("root_ssh_commands"):
                        cred_rows.append(("Root Password", _d(vm.get("root_password"))))
                        if vm.get("root_ssh_commands"):
                            cmds = vm["root_ssh_commands"]
                            if isinstance(cmds, dict):
                                for label, cmd in cmds.items():
                                    cred_rows.append((f"SSH ({label})", str(cmd)))
                            elif isinstance(cmds, list):
                                for cmd in cmds:
                                    cred_rows.append(("SSH Command", str(cmd)))
                    # Buyer credentials (tenant)
                    if vm.get("tenant_user") or vm.get("tenant_ssh_commands"):
                        cred_rows.append(("Tenant User", _d(vm.get("tenant_user"))))
                        cred_rows.append(("Tenant Password", _d(vm.get("tenant_password"))))
                        if vm.get("tenant_ssh_commands"):
                            cmds = vm["tenant_ssh_commands"]
                            if isinstance(cmds, dict):
                                for label, cmd in cmds.items():
                                    cred_rows.append((f"SSH ({label})", str(cmd)))
                            elif isinstance(cmds, list):
                                for cmd in cmds:
                                    cred_rows.append(("SSH Command", str(cmd)))
                    # Filter out rows where the value is "-"
                    cred_rows = [(k, v) for k, v in cred_rows if v != "-"]
                    if cred_rows:
                        console.print(Panel(_detail_grid(cred_rows), title="Provisioned VM Credentials", border_style="magenta"))
                    else:
                        console.print("[dim]VM found but no credential details available.[/dim]")
                else:
                    console.print("[dim]No provisioned VM found for this order.[/dim]")
            else:
                console.print("[dim]No provisioned VMs available.[/dim]")
        else:
            console.print("[dim]Provisioning service not reachable or no data returned.[/dim]")
    else:
        console.print("[dim]No agent ID available for provisioning queries (set CHAIN_ID, IDENTITY_REGISTRY_ADDRESS, ONCHAIN_AGENT_ID or use --agent-id).[/dim]")


@agent_app.command("threads")
def agent_threads(
    status: str | None = typer.Option(
        None, "--status", "-s",
        help="Filter by status (active, success, failure, timeout, superseded).",
    ),
    order_id: str | None = typer.Option(
        None, "--order-id", "-o", help="Filter by order ID (matches our or their order).",
    ),
    limit: int = typer.Option(50, "--limit", "-l", help="Maximum threads to show."),
    agent_url: str | None = typer.Option(
        None, "--agent-url", help="Agent base URL (env: AGENT_URL or BASE_URL_OVERRIDE).",
    ),
) -> None:
    """List negotiation threads from the running agent API."""
    base_url = _resolve_agent_url(agent_url)
    params: dict[str, str] = {}
    if status:
        params["status"] = status
    if order_id:
        params["order_id"] = order_id
    if limit:
        params["limit"] = str(limit)
    qs = urllib.parse.urlencode(params)
    data = _fetch_json(f"{base_url}/negotiations" + (f"?{qs}" if qs else ""))
    negotiations = data.get("negotiations", [])

    if not negotiations:
        Console().print("[dim]No negotiation threads found.[/dim]")
        return

    console = Console()
    table = Table(title="Negotiation Threads", box=box.SIMPLE_HEAVY, expand=True)
    table.add_column("Negotiation ID", style="bold", overflow="fold")
    table.add_column("Status")
    table.add_column("Terminal State")
    table.add_column("Our Order", overflow="fold")
    table.add_column("Their Order", overflow="fold")
    table.add_column("Rounds", justify="right")
    table.add_column("Updated", justify="right")

    for n in negotiations:
        table.add_row(
            _d(n.get("negotiation_id")),
            _styled(n.get("status"), _STATUS_STYLES),
            _d(n.get("terminal_state")),
            _shorten(_d(n.get("our_order_id")), 32),
            _shorten(_d(n.get("their_order_id")), 32),
            _d(n.get("round_count")),
            _short_ts(n.get("updated_at")),
        )
    console.print(table)


@agent_app.command("thread")
def agent_thread(
    negotiation_id: str = typer.Argument(..., help="Negotiation ID to inspect."),
    agent_url: str | None = typer.Option(
        None, "--agent-url", "-a", help="Agent base URL (env: AGENT_URL or BASE_URL_OVERRIDE).",
    ),
) -> None:
    """Show negotiation thread detail with round-by-round messages."""
    base_url = _resolve_agent_url(agent_url)
    data = _fetch_json(f"{base_url}/negotiations/{negotiation_id}")

    if data.get("error"):
        typer.secho(f"Thread {negotiation_id} not found.", err=True, fg=typer.colors.RED)
        raise typer.Exit(code=1)

    console = Console()
    console.print(Panel(
        _detail_grid([
            ("Negotiation ID", _d(data.get("negotiation_id"))),
            ("Status", _styled(data.get("status"), _STATUS_STYLES)),
            ("Terminal State", _d(data.get("terminal_state"))),
            ("Agreed Price", _d(data.get("agreed_price"))),
            ("Our Order", _d(data.get("our_order_id"))),
            ("Their Order", _d(data.get("their_order_id"))),
            ("Our Agent", _d(data.get("our_agent_id"))),
            ("Their Agent", _d(data.get("their_agent_id"))),
            ("Strategy", _d(data.get("our_strategy"))),
            ("Initial Price", _d(data.get("our_initial_price"))),
            ("Created", _short_ts(data.get("created_at"))),
            ("Updated", _short_ts(data.get("updated_at"))),
        ]),
        title="Thread Detail", border_style="blue",
    ))

    messages = data.get("messages", [])
    if not messages:
        Console().print("[dim]No round messages found for this thread.[/dim]")
        return

    rounds_table = Table(title="Rounds", box=box.SIMPLE_HEAVY, expand=True)
    for col, kw in [
        ("Round", {"justify": "right"}), ("Sender", {"overflow": "fold"}),
        ("Action", {}), ("Our Price", {"justify": "right"}),
        ("Their Price", {"justify": "right"}), ("Proposed", {"justify": "right"}),
        ("Type", {}), ("Timestamp", {"justify": "right"}),
    ]:
        rounds_table.add_column(col, **kw)

    prices: list[str] = []
    for m in messages:
        rnd = m.get("round")
        action = m.get("action_taken")
        our_price = m.get("our_price")
        their_price = m.get("their_price")
        proposed = m.get("proposed_price")
        rounds_table.add_row(
            _d(rnd), _shorten(_d(m.get("sender")), 32), _styled(action, _ACTION_STYLES),
            _d(our_price), _d(their_price), _d(proposed),
            _d(m.get("message_type")), _short_ts(m.get("timestamp")),
        )
        price_val = proposed if proposed is not None else (our_price if our_price is not None else their_price)
        if price_val is not None:
            prices.append(f"R{rnd}: {price_val}")

    console.print(rounds_table)
    if prices:
        console.print(Panel(" → ".join(prices), title="Price Progression", border_style="cyan"))


@agent_app.command("balance")
def agent_balance(
    agent_url: str | None = typer.Option(
        None, "--agent-url", "-a", help="Agent base URL (env: AGENT_URL or BASE_URL_OVERRIDE).",
    ),
    address: str | None = typer.Option(
        None, "--address", help="Wallet address to check (default: agent's own).",
    ),
    token: str | None = typer.Option(
        None, "--token", "-t", help="Additional ERC20 contract address to query.",
    ),
) -> None:
    """Show wallet balances (ETH + ERC20 tokens) via the running agent."""
    base_url = _resolve_agent_url(agent_url)
    params: dict[str, str] = {}
    if address:
        params["address"] = address
    if token:
        params["token"] = token
    qs = urllib.parse.urlencode(params)
    url = f"{base_url}/balance" + (f"?{qs}" if qs else "")

    data = _fetch_json(url)
    console = Console()

    if data.get("error"):
        typer.secho(f"Error: {data['error']}", err=True, fg=typer.colors.RED)
        raise typer.Exit(code=1)

    rows: list[tuple[str, str]] = [
        ("Address", _d(data.get("address"))),
        ("ETH Balance", f"{_d(data.get('eth_balance_human'))} ETH"),
    ]

    tokens = data.get("tokens", [])
    for tk in tokens:
        if tk.get("error"):
            rows.append((f"Token {_shorten(_d(tk.get('address')), 20)}", f"[red]Error: {tk['error']}[/red]"))
            continue
        symbol = tk.get("symbol", "???")
        human = tk.get("balance_human", "0")
        contract = tk.get("address", "")
        rows.append((f"{symbol} Balance", f"{human} {symbol}"))
        rows.append((f"{symbol} Contract", _shorten(contract, 44)))

    console.print(Panel(_detail_grid(rows), title="Wallet Balances", border_style="green"))


@agent_app.command("decisions")
def agent_decisions(
    event_type: str | None = typer.Option(
        None, "--event-type", "-t", help="Filter by event type.",
    ),
    action_type: str | None = typer.Option(
        None, "--action-type", "-a", help="Filter by action type.",
    ),
    limit: int = typer.Option(50, "--limit", "-l", help="Maximum decisions to show."),
    agent_url: str | None = typer.Option(
        None, "--agent-url", help="Agent base URL (env: AGENT_URL or BASE_URL_OVERRIDE).",
    ),
) -> None:
    """List agent decisions from the running agent API."""
    base_url = _resolve_agent_url(agent_url)
    params: dict[str, str] = {}
    if event_type:
        params["event_type"] = event_type
    if action_type:
        params["action_type"] = action_type
    if limit:
        params["limit"] = str(limit)
    qs = urllib.parse.urlencode(params)
    data = _fetch_json(f"{base_url}/decisions" + (f"?{qs}" if qs else ""))
    decisions = data.get("decisions", [])

    if not decisions:
        Console().print("[dim]No decisions found.[/dim]")
        return

    console = Console()
    table = Table(title="Agent Decisions", box=box.SIMPLE_HEAVY, expand=True)
    table.add_column("Decision ID", style="bold", overflow="fold")
    table.add_column("Event Type")
    table.add_column("Action")
    table.add_column("Policy Used")
    table.add_column("Outcome")
    table.add_column("Timestamp", justify="right")

    for d in decisions:
        outcome_json = d.get("outcome_json")
        outcome_display = "-"
        if outcome_json:
            try:
                outcome_display = _shorten(json.dumps(
                    outcome_json if isinstance(outcome_json, dict) else json.loads(outcome_json),
                    separators=(",", ":"),
                ), 60)
            except Exception:
                outcome_display = _shorten(str(outcome_json), 60)
        table.add_row(
            _d(d.get("decision_id")), _d(d.get("event_type")),
            _styled(d.get("action_type"), _ACTION_STYLES),
            _d(d.get("policy_used")), outcome_display,
            _short_ts(d.get("timestamp")),
        )
    console.print(table)


@agent_app.command("decision")
def agent_decision(
    decision_id: str = typer.Argument(..., help="Decision ID to inspect."),
    agent_url: str | None = typer.Option(
        None, "--agent-url", "-a", help="Agent base URL (env: AGENT_URL or BASE_URL_OVERRIDE).",
    ),
) -> None:
    """Show decision detail with context and outcome."""
    base_url = _resolve_agent_url(agent_url)
    data = _fetch_json(f"{base_url}/decisions/{decision_id}")

    if data.get("error"):
        typer.secho(f"Decision {decision_id} not found.", err=True, fg=typer.colors.RED)
        raise typer.Exit(code=1)

    console = Console()
    console.print(Panel(
        _detail_grid([
            ("Decision ID", _d(data.get("decision_id"))),
            ("Event ID", _d(data.get("event_id"))),
            ("Event Type", _d(data.get("event_type"))),
            ("Agent ID", _d(data.get("agent_id"))),
            ("Policy Used", _d(data.get("policy_used"))),
            ("Action", _styled(data.get("action_type"), _ACTION_STYLES)),
            ("Timestamp", _short_ts(data.get("timestamp"))),
        ]),
        title="Decision Detail", border_style="blue",
    ))

    context = data.get("context_json")
    ctx_display = _format_json(context)
    if ctx_display:
        console.print(Panel(ctx_display, title="Context", border_style="dim"))

    outcome = data.get("outcome_json")
    if outcome:
        out_display = _format_json(outcome) or "-"
        outcome_ts = data.get("outcome_timestamp")
        if outcome_ts:
            out_display += f"\n\nOutcome timestamp: {_short_ts(outcome_ts)}"
        console.print(Panel(out_display, title="Outcome", border_style="green"))
