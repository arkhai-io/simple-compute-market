"""Top-level `market buy` command.

Wraps the full buyer pipeline behind a single synchronous CLI call:
  1. POST /orders/create with {offer: token, demand: compute}
  2. Poll DB-derived stage until closed / post_settlement / failure / timeout
  3. Print credentials

By default, `market buy` is self-contained: if no agent is reachable at
the target URL, it spawns one transiently (docker container) and tears
it down on exit. Pass `--no-spawn-agent` to use an externally-managed
agent instead.
"""

from __future__ import annotations

import atexit
import contextlib
import json
import os
import shutil
import signal
import sqlite3
import subprocess
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path
from typing import Callable, Optional

import typer
from rich.console import Console
from rich.live import Live
from rich.panel import Panel
from rich.table import Table

from ..common import read_env_value, resolve_agent_url
from .logs import _derive_stage, _resolve_db_path
from .order import (
    _get_auth_headers,
    _normalize_registry_url,
    _post_json,
    _print_credentials_table,
    _resolve_db_path as _order_resolve_db_path,
)


TERMINAL_STAGES = {"closed"}
READY_STAGES = {"post_settlement", "closed"}


DEFAULT_SPAWN_IMAGE = "arkhai:core"
DEFAULT_SPAWN_NETWORK_CANDIDATES = (
    "simple-market-service_market-network",
    "market-network",
)


def _agent_reachable(base_url: str, timeout_s: float = 3.0) -> bool:
    url = base_url.rstrip("/") + "/.well-known/agent.json"
    try:
        with urllib.request.urlopen(url, timeout=timeout_s) as resp:
            return resp.status == 200
    except (urllib.error.URLError, ConnectionError, TimeoutError, OSError):
        return False


def _docker_cmd() -> Optional[str]:
    """Return the preferred OCI runtime binary, or None if none is on PATH."""
    for candidate in ("docker", "podman"):
        if shutil.which(candidate):
            return candidate
    return None


def _pick_network(runtime: str) -> Optional[str]:
    """Return the first candidate docker network that exists locally, or None."""
    try:
        out = subprocess.run(
            [runtime, "network", "ls", "--format", "{{.Name}}"],
            capture_output=True, text=True, timeout=5,
        )
    except Exception:
        return None
    if out.returncode != 0:
        return None
    existing = set(out.stdout.split())
    for name in DEFAULT_SPAWN_NETWORK_CANDIDATES:
        if name in existing:
            return name
    return None


def _spawn_agent_container(
    *,
    env_path: Path,
    port: int,
    image: str,
    network: Optional[str],
    agent_data_dir: Optional[Path],
    console: Console,
) -> tuple[str, Callable[[], None]]:
    """Launch an agent container and return (container_name, cleanup_fn).

    `agent_data_dir` is the host path to mount at the container-internal
    data directory so the CLI can read the same SQLite DB the agent writes.
    """
    runtime = _docker_cmd()
    if not runtime:
        raise typer.BadParameter(
            "No container runtime found (docker or podman). "
            "Install one, run the agent externally, or pass --no-spawn-agent."
        )

    name = f"market-buy-ephemeral-{uuid.uuid4().hex[:8]}"
    cmd = [
        runtime, "run", "--rm", "-d",
        "--name", name,
        "--platform", "linux/amd64",
        "--env-file", str(env_path.resolve()),
        "-p", f"{port}:{port}",
    ]
    if network:
        cmd.extend(["--network", network])
    if agent_data_dir:
        # Mount the host DB dir into the container so host-side polling sees
        # the agent's writes. Path layout matches docker-compose.yml.
        host = str(agent_data_dir.resolve())
        container_rel = "/app/core/agent/app/data/buy-agent"
        cmd.extend(["-v", f"{host}:{container_rel}"])
    cmd.append(image)

    console.print(f"[dim]spawning agent:[/dim] {' '.join(cmd)}")
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    if result.returncode != 0:
        raise typer.BadParameter(
            f"Failed to launch agent container: {result.stderr.strip() or result.stdout.strip()}"
        )

    def _cleanup():
        with contextlib.suppress(Exception):
            subprocess.run(
                [runtime, "stop", "-t", "5", name],
                capture_output=True, text=True, timeout=15,
            )

    atexit.register(_cleanup)
    for sig in (signal.SIGINT, signal.SIGTERM):
        prev = signal.getsignal(sig)
        def _handler(signum, frame, _prev=prev):
            _cleanup()
            if callable(_prev):
                _prev(signum, frame)
            raise SystemExit(130)
        signal.signal(sig, _handler)

    return name, _cleanup


def _wait_for_agent(base_url: str, timeout_s: float, console: Console) -> bool:
    """Poll agent readiness. Returns True if reachable before the deadline."""
    deadline = time.time() + timeout_s
    console.print(f"[dim]waiting for agent at {base_url}...[/dim]", end="")
    while time.time() < deadline:
        if _agent_reachable(base_url, timeout_s=1.5):
            console.print(" [green]ready[/green]")
            return True
        time.sleep(1.0)
    console.print(" [red]timeout[/red]")
    return False


def _build_resources(
    gpu: Optional[str],
    quantity: int,
    sla: Optional[float],
    region: Optional[str],
    max_price: str,
    token: str,
    demand_json: Optional[str],
    offer_json: Optional[str],
) -> tuple[dict, dict]:
    """Build (offer, demand) resource dicts for the /orders/create payload.

    Buyer semantics: offer = token (what they pay), demand = compute (what they want).
    """
    if demand_json:
        demand = json.loads(demand_json)
    else:
        if not gpu:
            raise typer.BadParameter("--gpu is required (or pass --demand-json)")
        demand = {"gpu_model": gpu, "quantity": quantity}
        if sla is not None:
            demand["sla"] = sla
        if region:
            demand["region"] = region

    if offer_json:
        offer = json.loads(offer_json)
    else:
        offer = {"token": token, "amount": max_price}

    return offer, demand


def _find_order_negotiation(conn: sqlite3.Connection, order_id: str) -> Optional[str]:
    """Return the negotiation_id associated with a local order, if one exists yet."""
    row = conn.execute(
        """SELECT negotiation_id FROM negotiation_threads
           WHERE our_order_id = ? OR their_order_id = ?
           ORDER BY created_at DESC LIMIT 1""",
        (order_id, order_id),
    ).fetchone()
    return row[0] if row else None


def _resolve_recover_order_id(db_path: str, identifier: str) -> Optional[str]:
    """Map an order_id OR escrow_uid to the buyer's local order_id.

    Returns None if no match found. Accepts either:
      - a UUID (treated as an order_id), or
      - a 0x-prefixed hex string (treated as an escrow_uid).
    """
    conn = sqlite3.connect(f"file:{db_path}?mode=ro&nolock=1", uri=True, timeout=5)
    try:
        # Try direct order_id match first.
        row = conn.execute(
            "SELECT order_id FROM orders WHERE order_id = ? LIMIT 1",
            (identifier,),
        ).fetchone()
        if row:
            return row[0]
        # Try escrow_uid (the column exists on orders).
        row = conn.execute(
            "SELECT order_id FROM orders WHERE escrow_uid = ? LIMIT 1",
            (identifier,),
        ).fetchone()
        return row[0] if row else None
    finally:
        conn.close()


def _load_order_state(db_path: str, order_id: str) -> dict:
    """Return the current {status, escrow_uid, taker_attestation} for an order."""
    conn = sqlite3.connect(f"file:{db_path}?mode=ro&nolock=1", uri=True, timeout=5)
    try:
        row = conn.execute(
            "SELECT status, escrow_uid, taker_attestation FROM orders WHERE order_id = ?",
            (order_id,),
        ).fetchone()
    finally:
        conn.close()
    if not row:
        return {}
    return {
        "status": row[0],
        "escrow_uid": row[1],
        "taker_attestation": row[2],
    }


def _close_order(
    agent_url: str,
    order_id: str,
    private_key: Optional[str],
) -> dict:
    """POST /orders/close and return the full response dict."""
    url = f"{_normalize_registry_url(agent_url)}/orders/close"
    headers = _get_auth_headers("close_order", order_id, private_key)
    return _post_json(url, {"order_id": order_id}, headers)


def _credentials_present(conn: sqlite3.Connection, order_id: str) -> bool:
    try:
        row = conn.execute(
            "SELECT COUNT(*) FROM credentials WHERE order_id = ?",
            (order_id,),
        ).fetchone()
        return bool(row and row[0])
    except sqlite3.OperationalError:
        return False


def _poll_snapshot(db_path: str, order_id: str) -> dict:
    """Single read: returns {stage, detail, negotiation_id, credentials_ready}.

    Opens the DB read-only with nolock=1 so a busy writer on the other side
    (e.g. the agent doing WAL checkpoints) does not surface as a spurious
    'attempt to write a readonly database'. Retries briefly on transient I/O.
    """
    last_err: Exception | None = None
    for _ in range(5):
        try:
            conn = sqlite3.connect(
                f"file:{db_path}?mode=ro&nolock=1", uri=True, timeout=5,
            )
            conn.row_factory = sqlite3.Row
            try:
                nid = _find_order_negotiation(conn, order_id)
                creds_ready = _credentials_present(conn, order_id)
                if not nid:
                    return {
                        "stage": "discovery",
                        "detail": "matching seller",
                        "negotiation_id": None,
                        "credentials_ready": creds_ready,
                    }
                info = _derive_stage(conn, nid)
                info["credentials_ready"] = creds_ready
                info["negotiation_id"] = nid
                return info
            finally:
                conn.close()
        except sqlite3.OperationalError as exc:
            last_err = exc
            time.sleep(0.2)
    # Final attempt failed — surface a snapshot that represents "we can't read".
    return {
        "stage": "unknown",
        "detail": f"db read error: {last_err}",
        "negotiation_id": None,
        "credentials_ready": False,
    }


def _create_buy_order(
    agent_url: str,
    offer: dict,
    demand: dict,
    duration_hours: int,
    wallet_address: str,
    private_key: Optional[str],
) -> str:
    """POST /orders/create and return the new order_id."""
    payload = {"offer": offer, "demand": demand, "duration_hours": duration_hours}
    url = f"{_normalize_registry_url(agent_url)}/orders/create"
    headers = _get_auth_headers("create_order", wallet_address, private_key)
    response = _post_json(url, payload, headers)
    order_id = response.get("order_id")
    if not order_id:
        raise typer.BadParameter(f"Agent did not return order_id: {response}")
    return order_id


def _wait_for_completion(
    db_path: str,
    order_id: str,
    timeout: int,
    poll_interval: float,
    console: Console,
) -> dict:
    """Block until credentials ready / closed / failure / timeout. Returns final snapshot."""
    deadline = time.time() + timeout

    def render(info: dict) -> Panel:
        color = {
            "discovery": "blue",
            "negotiation": "yellow",
            "settlement": "green",
            "provision": "cyan",
            "post_settlement": "magenta",
            "closed": "bold green",
            "unknown": "red",
        }.get(info.get("stage", ""), "white")
        lines = [f"[bold]Order:[/bold] {order_id}"]
        lines.append(f"[bold]Stage:[/bold] [{color}]{info.get('stage', '?')}[/{color}]")
        if info.get("detail"):
            lines.append(f"[bold]Detail:[/bold] {info['detail']}")
        for key in ("negotiation_id", "escrow_uid", "rounds"):
            val = info.get(key)
            if val is not None:
                lines.append(f"[dim]{key}:[/dim] {val}")
        lines.append(f"[dim]timeout in {max(0, int(deadline - time.time()))}s[/dim]")
        return Panel("\n".join(lines), title="[bold]market buy[/bold]", border_style=color)

    with Live(console=console, refresh_per_second=2) as live:
        while True:
            info = _poll_snapshot(db_path, order_id)
            live.update(render(info))

            if info.get("credentials_ready") or info.get("stage") in READY_STAGES:
                return info
            if info.get("terminal_state") in ("failure", "superseded", "abandoned"):
                return info
            if time.time() >= deadline:
                info["_timed_out"] = True
                return info
            time.sleep(poll_interval)


def register(app: typer.Typer) -> None:
    """Register the top-level `market buy` command on the given Typer app."""

    @app.command("buy")
    def buy(
        gpu: Optional[str] = typer.Option(None, "--gpu", "-g", help="GPU model, e.g. 'RTX 5080'."),
        quantity: int = typer.Option(1, "--quantity", "-q", help="Number of GPUs."),
        sla: Optional[float] = typer.Option(None, "--sla", help="Minimum SLA percentage."),
        region: Optional[str] = typer.Option(None, "--region", help="Preferred region."),
        max_price: Optional[str] = typer.Option(None, "--max-price", "-p", help="Price ceiling (human units of --token). Required unless --recover is given."),
        token: str = typer.Option("MOCK", "--token", help="Payment token symbol."),
        duration_hours: int = typer.Option(1, "--duration-hours", "-t", help="Lease duration in hours."),
        demand_json: Optional[str] = typer.Option(None, "--demand-json", help="Raw demand resource JSON (overrides --gpu/--quantity/--sla/--region)."),
        offer_json: Optional[str] = typer.Option(None, "--offer-json", help="Raw offer resource JSON (overrides --max-price/--token)."),
        recover: Optional[str] = typer.Option(None, "--recover", help="Resume waiting on an existing order by order_id or escrow_uid, instead of creating a new one."),
        abort: Optional[str] = typer.Option(None, "--abort", help="Cancel an in-flight order by order_id or escrow_uid. Closes the order locally and in the registry."),
        spawn_agent: bool = typer.Option(
            True, "--spawn-agent/--no-spawn-agent",
            help="If no agent is reachable at the target URL, transiently spawn one (container) for the duration of this command and tear it down on exit. On by default so `market buy` feels like a one-shot.",
        ),
        spawn_image: str = typer.Option(
            DEFAULT_SPAWN_IMAGE, "--spawn-image",
            help="Container image to use when --spawn-agent must launch one.",
        ),
        spawn_network: Optional[str] = typer.Option(
            None, "--spawn-network",
            help="Container network for a spawned agent. Defaults to the first local network named 'simple-market-service_market-network' or 'market-network' if present.",
        ),
        spawn_timeout: int = typer.Option(
            30, "--spawn-timeout",
            help="Seconds to wait for a spawned agent to become reachable.",
        ),
        timeout: int = typer.Option(600, "--timeout", help="Total wait budget in seconds."),
        poll_interval: float = typer.Option(2.0, "--poll-interval", help="Seconds between DB polls."),
        agent_url: Optional[str] = typer.Option(None, "--agent-url", "-a", help="Buyer agent base URL (env: AGENT_URL, BASE_URL_OVERRIDE)."),
        env: Optional[str] = typer.Option(None, "--env", "-e", help="Env file (reads BASE_URL_OVERRIDE, AGENT_PRIV_KEY, AGENT_DB_PATH)."),
        db: Optional[str] = typer.Option(None, "--db", help="Explicit buyer agent SQLite DB path."),
        show_password: bool = typer.Option(False, "--show-password", help="Reveal credential passwords when printing."),
    ) -> None:
        """Buy compute with the given constraints — synchronous, one command.

        Modes:

          Create (default): `market buy --gpu X --max-price Y` creates a
          new order, blocks until the deal closes, prints credentials.

          Recover: `market buy --recover <id>` skips order creation and
          resumes polling an existing deal. Useful when a previous
          `market buy` was interrupted (Ctrl-C, crash). `<id>` is either
          the local order_id or the on-chain escrow_uid.

          Abort: `market buy --abort <id>` cancels an in-flight order.
          Closes the order locally and in the registry. Warns (but does
          not roll back) if an on-chain escrow is already posted.
        """
        console = Console()
        env_path = Path(env) if env else None

        # Exactly one mode.
        modes = [m for m in ("recover" if recover else None, "abort" if abort else None) if m]
        if len(modes) > 1:
            raise typer.BadParameter(
                "--recover and --abort are mutually exclusive."
            )
        if (recover or abort) and max_price is not None:
            raise typer.BadParameter(
                "--recover/--abort are mutually exclusive with --max-price."
            )
        if not recover and not abort and max_price is None:
            raise typer.BadParameter(
                "--max-price is required (or pass --recover <id> / --abort <id>)."
            )

        base_url = resolve_agent_url(agent_url, env_path, default_port=8000)
        db_path = _resolve_db_path(db, env) or _order_resolve_db_path(db, env)
        if not db_path:
            typer.secho(
                "Could not resolve buyer agent DB. Pass --db or --env with AGENT_DB_PATH set.",
                err=True,
                fg=typer.colors.RED,
            )
            raise typer.Exit(1)

        # Ensure an agent is reachable. Spawn transiently if not.
        if not _agent_reachable(base_url):
            if not spawn_agent:
                typer.secho(
                    f"No agent reachable at {base_url} and --no-spawn-agent. "
                    f"Start one separately (`market start`) or drop the flag.",
                    err=True, fg=typer.colors.RED,
                )
                raise typer.Exit(1)
            if not env_path:
                raise typer.BadParameter(
                    "--spawn-agent requires --env so the spawned container knows "
                    "its identity, keys, and chain/registry endpoints."
                )
            port_str = read_env_value(env_path, "PORT", default="8000")
            try:
                port = int(port_str)
            except ValueError:
                port = 8000
            runtime = _docker_cmd()
            network = spawn_network or (_pick_network(runtime) if runtime else None)
            console.print(
                Panel(
                    f"[bold]image[/bold]    {spawn_image}\n"
                    f"[bold]port[/bold]     {port}\n"
                    f"[bold]network[/bold]  {network or '(default)'}\n"
                    f"[bold]env[/bold]      {env_path}",
                    title="Spawning transient agent",
                    border_style="cyan",
                )
            )
            _spawn_agent_container(
                env_path=env_path,
                port=port,
                image=spawn_image,
                network=network,
                agent_data_dir=Path(db_path).parent if db_path else None,
                console=console,
            )
            if not _wait_for_agent(base_url, timeout_s=spawn_timeout, console=console):
                typer.secho(
                    f"Spawned agent did not become reachable at {base_url} "
                    f"within {spawn_timeout}s. See container logs for details.",
                    err=True, fg=typer.colors.RED,
                )
                raise typer.Exit(1)

        if abort:
            order_id = _resolve_recover_order_id(db_path, abort)
            if not order_id:
                typer.secho(
                    f"No local order found for id/escrow_uid {abort!r}. "
                    "Check the value or pass a different --db.",
                    err=True, fg=typer.colors.RED,
                )
                raise typer.Exit(1)

            state = _load_order_state(db_path, order_id)
            status = state.get("status") or "?"
            escrow_uid = state.get("escrow_uid")
            taker_attestation = state.get("taker_attestation")

            summary = Table.grid(padding=(0, 2))
            summary.add_column(style="bold")
            summary.add_column()
            summary.add_row("Mode", "abort")
            summary.add_row("Input", abort)
            summary.add_row("Order ID", order_id)
            summary.add_row("Current status", status)
            if escrow_uid:
                summary.add_row("Escrow UID", escrow_uid)
            summary.add_row("Agent", base_url)
            console.print(Panel(summary, title="Buy abort", border_style="yellow"))

            if status == "closed":
                console.print("[green]Already closed — nothing to do.[/green]")
                return

            # Warn when on-chain state makes local close insufficient.
            if escrow_uid and not taker_attestation:
                console.print(
                    "[yellow]Warning:[/yellow] an escrow is posted on-chain for this order "
                    "but the seller has not yet delivered. Closing the local order will "
                    "mark it cancelled in the registry, but the escrow refund is NOT "
                    "automated yet — you may need to reclaim it manually.",
                )
            elif escrow_uid and taker_attestation:
                console.print(
                    "[yellow]Warning:[/yellow] this deal is already fulfilled (taker "
                    "attestation present). Aborting now will not undo the on-chain "
                    "settlement; credentials already in the buyer DB remain valid.",
                )

            private_key = (
                (read_env_value(env_path, "AGENT_PRIV_KEY") if env_path else None)
                or os.getenv("AGENT_PRIV_KEY")
            )
            try:
                resp = _close_order(base_url, order_id, private_key)
            except typer.Exit:
                # _post_json already printed the error and exited.
                raise
            result_status = str(resp.get("status", "?"))
            result_msg = str(resp.get("message") or "")
            color = "green" if result_status in ("closed", "skipped", "queued") else "red"
            console.print(f"[{color}]Close result:[/] {result_status}"
                          + (f" — {result_msg}" if result_msg else ""))
            if result_status in ("closed", "skipped", "queued"):
                return
            raise typer.Exit(5)

        if recover:
            order_id = _resolve_recover_order_id(db_path, recover)
            if not order_id:
                typer.secho(
                    f"No local order found for id/escrow_uid {recover!r}. "
                    "Check the value or pass a different --db.",
                    err=True, fg=typer.colors.RED,
                )
                raise typer.Exit(1)
            summary = Table.grid(padding=(0, 2))
            summary.add_column(style="bold")
            summary.add_column()
            summary.add_row("Mode", "recover")
            summary.add_row("Input", recover)
            summary.add_row("Order ID", order_id)
            summary.add_row("Agent", base_url)
            console.print(Panel(summary, title="Buy recovery", border_style="blue"))
        else:
            private_key = (
                (read_env_value(env_path, "AGENT_PRIV_KEY") if env_path else None)
                or os.getenv("AGENT_PRIV_KEY")
            )
            wallet_address = (
                (read_env_value(env_path, "AGENT_WALLET_ADDRESS") if env_path else None)
                or os.getenv("AGENT_WALLET_ADDRESS")
                or ""
            )
            try:
                offer, demand = _build_resources(
                    gpu, quantity, sla, region, max_price, token, demand_json, offer_json
                )
            except json.JSONDecodeError as exc:
                raise typer.BadParameter(f"Invalid JSON: {exc}") from exc

            summary = Table.grid(padding=(0, 2))
            summary.add_column(style="bold")
            summary.add_column()
            summary.add_row("Agent", base_url)
            summary.add_row("Demand", json.dumps(demand, separators=(",", ":")))
            summary.add_row("Offer", json.dumps(offer, separators=(",", ":")))
            summary.add_row("Duration (h)", str(duration_hours))
            console.print(Panel(summary, title="Buy request", border_style="blue"))

            order_id = _create_buy_order(
                base_url, offer, demand, duration_hours, wallet_address, private_key,
            )
            console.print(f"[green]Order created:[/green] {order_id}")

        final = _wait_for_completion(db_path, order_id, timeout, poll_interval, console)

        if final.get("_timed_out"):
            console.print(f"[red]Timed out after {timeout}s — order is in stage '{final.get('stage')}'.[/red]")
            console.print(f"[dim]Resume with: market buy --recover {order_id}[/dim]")
            raise typer.Exit(2)
        if final.get("terminal_state") in ("failure", "superseded", "abandoned"):
            console.print(f"[red]Negotiation ended without a deal: {final.get('terminal_state')}[/red]")
            raise typer.Exit(3)

        console.print()
        _print_credentials_table(console, db_path, order_id, show_password=show_password)
