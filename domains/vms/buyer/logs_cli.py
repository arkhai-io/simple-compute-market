"""`market logs` — inspect past buy/negotiate runs.

The buyer doesn't have a server or a SQLite DB; each `market buy` /
`market negotiate` invocation appends to a per-run JSONL file under
``$XDG_STATE_HOME/arkhai/buy-runs/`` (see domains.vms.buyer.run_log).

Subcommands:

    market logs                        # list recent runs
    market logs show <run_id>          # full event stream for one run
    market logs tail                   # full event stream for the most recent run
"""

from __future__ import annotations

import json
from typing import Optional

import typer
from rich import box
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from .run_log import list_runs, read_run, runs_dir


logs_app = typer.Typer(no_args_is_help=False, invoke_without_command=True)
console = Console()


def _short(value: str | None, width: int = 12) -> str:
    if not value:
        return "-"
    if len(value) <= width:
        return value
    return value[:width] + "…"


def _short_ts(value: str | None) -> str:
    if not value:
        return "-"
    return value.split(".")[0].replace("T", " ").replace("+00:00", "")


def _print_runs_table(limit: int) -> None:
    runs = list_runs()
    if not runs:
        console.print(f"[dim]No runs found. Run dir: {runs_dir()}[/dim]")
        return

    table = Table(title="Recent runs", box=box.SIMPLE_HEAVY, expand=True)
    table.add_column("Run ID", overflow="fold")
    table.add_column("Started")
    table.add_column("Last event")
    table.add_column("Last seen")
    table.add_column("Status")

    for r in runs[:limit]:
        status = r.last_status or "[dim]in-progress[/dim]"
        table.add_row(
            r.run_id,
            _short_ts(r.started_at),
            r.last_event or "-",
            _short_ts(r.last_event_ts),
            status,
        )
    console.print(table)


@logs_app.callback()
def logs_callback(ctx: typer.Context) -> None:
    """Default action: list recent runs (when invoked with no subcommand)."""
    if ctx.invoked_subcommand is not None:
        return
    _print_runs_table(limit=20)


@logs_app.command("runs")
def runs_list(
    limit: int = typer.Option(20, "--limit", "-l", help="Max runs to show."),
) -> None:
    """List recent runs, newest first."""
    _print_runs_table(limit=limit)


def _negotiation_key(ev: dict) -> str | None:
    """The grouping key for negotiation-scoped events.

    Always ``listing_id`` when present — it's sticky from the
    negotiation_started event through completion, so events stay in
    one group even when negotiation_id is added partway through.
    Returns ``None`` for run-level events (discover, escrow_*,
    run_started, run_ended, settlement_*, etc.).
    """
    if "listing_id" in ev:
        return ev["listing_id"]
    if "negotiation_id" in ev:
        return ev["negotiation_id"]
    return None


def _print_event_line(ev: dict, *, indent: int = 0) -> None:
    ts = _short_ts(ev.get("ts"))
    name = ev.get("event", "?")
    body = {
        k: v for k, v in ev.items()
        if k not in ("ts", "run_id", "event", "listing_id", "negotiation_id")
    }
    prefix = "  " * indent
    if body:
        console.print(
            f"{prefix}[dim]{ts}[/dim]  [bold]{name}[/bold]  "
            f"{json.dumps(body, default=str)}"
        )
    else:
        console.print(f"{prefix}[dim]{ts}[/dim]  [bold]{name}[/bold]")


def _print_run_events(run_id_prefix: str, raw: bool) -> None:
    matched = _resolve_run_id(run_id_prefix)
    if matched is None:
        raise typer.Exit(1)

    events = read_run(matched)
    if not events:
        console.print(f"[yellow]Run {matched} has no events.[/yellow]")
        return

    if raw:
        for ev in events:
            typer.echo(json.dumps(ev))
        return

    header = Table.grid(padding=(0, 2))
    header.add_column(style="bold")
    header.add_column()
    header.add_row("Run ID", matched)
    header.add_row("Events", str(len(events)))
    console.print(Panel(header, title="market logs show", border_style="cyan"))

    # First pass: resolve listing_id → negotiation_id for the
    # heading (the id only shows up after round 0; we want it on the
    # group banner even when the first event in the group doesn't
    # have it yet).
    lid_to_neg_id: dict[str, str] = {}
    for ev in events:
        lid = ev.get("listing_id")
        nid = ev.get("negotiation_id")
        if lid and nid and lid not in lid_to_neg_id:
            lid_to_neg_id[lid] = nid

    # Group consecutive negotiation-scoped events under a single
    # heading per negotiation. Run-level events (no key) print flat.
    current_key: str | None = None
    for ev in events:
        key = _negotiation_key(ev)
        if key is None:
            current_key = None
            _print_event_line(ev)
        else:
            if key != current_key:
                current_key = key
                lid = ev.get("listing_id") or "?"
                nid = lid_to_neg_id.get(lid)
                heading = (
                    f"{nid}  (listing={lid})" if nid
                    else f"listing={lid}"
                )
                console.print(f"[cyan]┌── negotiation: {heading}[/cyan]")
            _print_event_line(ev, indent=1)


@logs_app.command("show")
def logs_show(
    run_id: str = typer.Argument(..., help="Run ID (or unique prefix)."),
    raw: bool = typer.Option(False, "--raw", help="Print raw JSONL lines."),
) -> None:
    """Show every event for a single run."""
    _print_run_events(run_id, raw=raw)


@logs_app.command("tail")
def logs_tail(
    raw: bool = typer.Option(False, "--raw", help="Print raw JSONL lines."),
) -> None:
    """Show the event stream for the most recent run."""
    runs = list_runs()
    if not runs:
        console.print(f"[dim]No runs found. Run dir: {runs_dir()}[/dim]")
        raise typer.Exit(0)
    _print_run_events(runs[0].run_id, raw=raw)


def _resolve_run_id(needle: str) -> Optional[str]:
    """Allow callers to pass a unique prefix instead of the full id."""
    runs = list_runs()
    exact = [r for r in runs if r.run_id == needle]
    if exact:
        return exact[0].run_id
    matches = [r for r in runs if r.run_id.startswith(needle)]
    if not matches:
        console.print(f"[red]No run matches {needle!r}.[/red]")
        return None
    if len(matches) > 1:
        console.print(f"[red]Ambiguous prefix {needle!r}; matches:[/red]")
        for r in matches:
            console.print(f"  {r.run_id}")
        return None
    return matches[0].run_id
