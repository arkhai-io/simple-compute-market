"""CLI commands for inspecting the storefront's stage events.

    market-storefront logs                          # all stage events, newest first
    market-storefront logs --negotiation <id>       # events for one negotiation
    market-storefront logs --stage settlement       # events for one stage
    market-storefront logs --last 5                 # last 5 events

    market-storefront status <negotiation_id>       # derive current stage from DB state

Reads the storefront's local SQLite ``stage_events`` table (written
by the storefront runtime via market_storefront.utils.stage_log).
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.text import Text

from .cli_common import DEFAULT_AGENT_ENV, container_db_to_host, read_env_value

logs_app = typer.Typer(no_args_is_help=True)
console = Console()


def _resolve_db_path(db: str | None, env: str | None) -> str | None:
    """Return the SQLite DB path from explicit ``--db`` or the explicit
    ``--env`` file. Process env is not consulted."""
    if db:
        return db
    env_path = Path(env) if env else DEFAULT_AGENT_ENV
    db_path_from_env = read_env_value(env_path, "AGENT_DB_PATH")
    if db_path_from_env:
        agent_mode = read_env_value(env_path, "AGENT_MODE", default="host")
        resolved = str(container_db_to_host(db_path_from_env)) if agent_mode == "container" else db_path_from_env
        if Path(resolved).exists():
            return resolved
    return None


# ---------------------------------------------------------------------------
# market logs
# ---------------------------------------------------------------------------


@logs_app.command("show")
def logs_show(
    negotiation: Optional[str] = typer.Option(None, "--negotiation", "-n", help="Filter by negotiation ID (or prefix)"),
    stage: Optional[str] = typer.Option(None, "--stage", "-s", help="Filter by stage (discovery, negotiation, settlement, provision, post_settlement)"),
    last: int = typer.Option(50, "--last", "-l", help="Show last N events"),
    db: Optional[str] = typer.Option(None, "--db", help="Agent SQLite DB path"),
    env: Optional[str] = typer.Option(None, "-e", "--env", help="Agent env file"),
    raw: bool = typer.Option(False, "--raw", help="Print raw JSON per line"),
):
    """Show stage-boundary events from the agent's local log."""
    db_path = _resolve_db_path(db, env)
    if not db_path:
        console.print("[red]Could not find agent DB. Use --db or --env to specify.[/red]")
        raise typer.Exit(1)

    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=5)
    conn.row_factory = sqlite3.Row
    try:
        cur = conn.cursor()

        where_clauses = []
        params: list = []
        if negotiation:
            where_clauses.append("(negotiation_id = ? OR negotiation_id LIKE ?)")
            params.extend([negotiation, f"%{negotiation}%"])
        if stage:
            where_clauses.append("stage = ?")
            params.append(stage)

        where = f"WHERE {' AND '.join(where_clauses)}" if where_clauses else ""
        query = f"SELECT ts, stage, event, negotiation_id, order_id, escrow_uid, data FROM stage_events {where} ORDER BY id DESC LIMIT ?"
        params.append(last)

        rows = cur.execute(query, params).fetchall()
    except sqlite3.OperationalError as e:
        if "no such table" in str(e):
            console.print("[yellow]No stage_events table yet — agent has not emitted any stage events.[/yellow]")
            raise typer.Exit(0)
        raise
    finally:
        conn.close()

    if not rows:
        console.print("[dim]No matching stage events found.[/dim]")
        raise typer.Exit(0)

    # Reverse so oldest-first (we fetched DESC for LIMIT, display ASC)
    rows = list(reversed(rows))

    if raw:
        for row in rows:
            typer.echo(row["data"])
        return

    table = Table(title=f"Stage Events ({len(rows)})", show_lines=False)
    table.add_column("Time", style="dim", no_wrap=True, max_width=19)
    table.add_column("Stage", style="bold")
    table.add_column("Event")
    table.add_column("Negotiation", max_width=12)
    table.add_column("Details", max_width=60)

    stage_colors = {
        "discovery": "blue",
        "negotiation": "yellow",
        "settlement": "green",
        "provision": "cyan",
        "post_settlement": "magenta",
    }

    for row in rows:
        data = json.loads(row["data"])
        # Build a concise detail string from the interesting fields
        skip_keys = {"ts", "stage", "event", "negotiation_id", "order_id", "escrow_uid"}
        details = {k: v for k, v in data.items() if k not in skip_keys and v is not None}
        detail_str = ", ".join(f"{k}={v}" for k, v in details.items())
        if len(detail_str) > 60:
            detail_str = detail_str[:57] + "..."

        color = stage_colors.get(row["stage"], "white")
        neg_id = (row["negotiation_id"] or "")[:12]

        table.add_row(
            row["ts"][:19],
            f"[{color}]{row['stage']}[/{color}]",
            row["event"],
            neg_id,
            detail_str,
        )

    console.print(table)


# ---------------------------------------------------------------------------
# market status <negotiation_id>
# ---------------------------------------------------------------------------


def _derive_stage(
    conn: sqlite3.Connection,
    negotiation_id: str,
) -> dict:
    """Derive the current deal stage from DB state for a negotiation."""
    conn.row_factory = sqlite3.Row

    # 1. Load negotiation thread
    thread = conn.execute(
        "SELECT * FROM negotiation_threads WHERE negotiation_id = ?",
        (negotiation_id,),
    ).fetchone()

    if not thread:
        return {"stage": "unknown", "reason": "no negotiation thread found"}

    result = {
        "negotiation_id": negotiation_id,
        "our_order_id": thread["our_order_id"],
        "their_order_id": thread["their_order_id"],
        "thread_status": thread["status"],
        "terminal_state": thread["terminal_state"],
    }

    # 2. Load our order
    our_order = None
    if thread["our_order_id"]:
        our_order = conn.execute(
            "SELECT * FROM orders WHERE order_id = ?",
            (thread["our_order_id"],),
        ).fetchone()

    if our_order:
        result["order_status"] = our_order["status"]
        result["escrow_uid"] = our_order["escrow_uid"]
        result["maker_attestation"] = our_order["maker_attestation"]
        result["taker_attestation"] = our_order["taker_attestation"]

    # 3. Derive stage
    if not thread["terminal_state"]:
        result["stage"] = "negotiation"
        result["detail"] = "in progress"
        # Count rounds
        rounds = conn.execute(
            "SELECT COUNT(*) FROM negotiation_messages WHERE negotiation_id = ?",
            (negotiation_id,),
        ).fetchone()[0]
        result["rounds"] = rounds
    elif thread["terminal_state"] in ("failure", "superseded", "abandoned"):
        result["stage"] = "negotiation"
        result["detail"] = f"terminated: {thread['terminal_state']}"
    elif thread["terminal_state"] == "success":
        if not our_order:
            result["stage"] = "negotiation"
            result["detail"] = "agreed (no local order found)"
        elif not our_order["escrow_uid"]:
            result["stage"] = "settlement"
            result["detail"] = "awaiting escrow"
        elif our_order["status"] == "closed":
            result["stage"] = "closed"
            result["detail"] = "deal complete"
        elif our_order["taker_attestation"]:
            result["stage"] = "post_settlement"
            result["detail"] = "fulfillment received, awaiting close"
        elif our_order["maker_attestation"]:
            result["stage"] = "provision"
            result["detail"] = "fulfilled, awaiting buyer confirmation"
        else:
            result["stage"] = "settlement"
            result["detail"] = "escrow created, awaiting fulfillment"

    return result


@logs_app.command("status")
def deal_status(
    negotiation_id: str = typer.Argument(help="Negotiation ID (or order ID to search by)"),
    db: Optional[str] = typer.Option(None, "--db", help="Agent SQLite DB path"),
    env: Optional[str] = typer.Option(None, "-e", "--env", help="Agent env file"),
):
    """Show the current stage and state of a deal/negotiation."""
    db_path = _resolve_db_path(db, env)
    if not db_path:
        console.print("[red]Could not find agent DB. Use --db or --env to specify.[/red]")
        raise typer.Exit(1)

    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=5)
    try:
        # If the argument looks like an order_id, find the negotiation
        neg_ids = []
        row = conn.execute(
            "SELECT negotiation_id FROM negotiation_threads WHERE negotiation_id = ?",
            (negotiation_id,),
        ).fetchone()
        if row:
            neg_ids = [negotiation_id]
        else:
            # Search by order_id
            rows = conn.execute(
                """SELECT negotiation_id FROM negotiation_threads
                   WHERE our_order_id = ? OR their_order_id = ?""",
                (negotiation_id, negotiation_id),
            ).fetchall()
            neg_ids = [r[0] for r in rows]

        if not neg_ids:
            console.print(f"[yellow]No negotiation found for '{negotiation_id}'.[/yellow]")
            raise typer.Exit(1)

        for nid in neg_ids:
            info = _derive_stage(conn, nid)

            stage_colors = {
                "negotiation": "yellow",
                "settlement": "green",
                "provision": "cyan",
                "post_settlement": "magenta",
                "closed": "bold green",
                "unknown": "red",
            }
            color = stage_colors.get(info.get("stage", ""), "white")

            panel_lines = []
            panel_lines.append(f"[bold]Stage:[/bold] [{color}]{info.get('stage', '?')}[/{color}]")
            if info.get("detail"):
                panel_lines.append(f"[bold]Detail:[/bold] {info['detail']}")
            for key in ("our_order_id", "their_order_id", "order_status",
                        "escrow_uid", "maker_attestation", "taker_attestation",
                        "rounds", "terminal_state"):
                val = info.get(key)
                if val is not None:
                    panel_lines.append(f"[dim]{key}:[/dim] {val}")

            console.print(Panel(
                "\n".join(panel_lines),
                title=f"[bold]Negotiation {nid[:20]}…[/bold]" if len(nid) > 20 else f"[bold]Negotiation {nid}[/bold]",
                border_style=color,
            ))

            # Show stage events for this deal. Events fire throughout the
            # lifecycle; some land before a negotiation_id exists (discovery)
            # or carry only an order_id (provision/settlement). Join on any
            # identifier that names this deal.
            ids_to_match = [nid]
            for key in ("our_order_id", "their_order_id", "escrow_uid"):
                v = info.get(key)
                if v and v not in ids_to_match:
                    ids_to_match.append(v)
            placeholders = ",".join("?" * len(ids_to_match))
            try:
                events = conn.execute(
                    f"""SELECT ts, stage, event, data FROM stage_events
                        WHERE negotiation_id IN ({placeholders})
                           OR order_id IN ({placeholders})
                           OR escrow_uid IN ({placeholders})
                        ORDER BY id ASC""",
                    ids_to_match * 3,
                ).fetchall()
                if events:
                    console.print(f"\n[bold]Stage events ({len(events)}):[/bold]")
                    for ev in events:
                        data = json.loads(ev[3])
                        skip = {"ts", "stage", "event", "negotiation_id"}
                        details = {k: v for k, v in data.items() if k not in skip and v is not None}
                        detail_str = ", ".join(f"{k}={v}" for k, v in details.items())
                        console.print(f"  {ev[0][:19]}  [{stage_colors.get(ev[1], 'white')}]{ev[1]}.{ev[2]}[/]  {detail_str}")
            except sqlite3.OperationalError:
                pass  # no stage_events table yet

    finally:
        conn.close()
