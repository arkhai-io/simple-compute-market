"""Top-level `market provide` command.

The seller's counterpart to `market buy`. Wraps the seller's start-of-day
flow behind a single command:

  1. (optional) Import a CSV of compute resources into the agent DB.
  2. Read the DB for `state='available'` compute rows.
  3. POST /orders/create on the agent, once per resource, offering the
     compute and demanding the configured token amount.
  4. Print a table of published orders.

`--watch` extends (3) into a loop: periodically re-scan the DB and
publish orders for resources that are `available` and don't already
have an open order. Runs until Ctrl-C. Safe because the resource poller
force-frees stale leases after the configured grace window.

Assumes the seller agent is already running (mirror of `market buy`).
"""

from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich import box

from storefront_client import (
    StorefrontClientError,
    SyncStorefrontClient,
)

from .cli_common import REPO_ROOT, read_env_value, resolve_agent_url, _resolve_db_path


def _import_csv(csv_path: str, env: Optional[str], db: Optional[str]) -> None:
    """Invoke the existing import_resources_csv.py script directly.

    Uses `storefront/.venv/bin/python` rather than `uv run` — the
    latter fails cleanly from outside the storefront project, and the
    storefront venv is a stable dependency of the provider-side
    deployment anyway.
    """
    script = REPO_ROOT / "storefront" / "scripts" / "import_resources_csv.py"
    python = REPO_ROOT / "storefront" / ".venv" / "bin" / "python"
    if not python.exists():
        raise typer.BadParameter(
            f"Storefront venv not found at {python}. "
            "Run `cd storefront && uv sync` first."
        )
    cmd = [
        str(python), str(script),
        "--csv", str(Path(csv_path).resolve()),
    ]
    if db:
        cmd.extend(["--db-path", str(Path(db).resolve())])
    if env:
        cmd.extend(["--env-file", str(Path(env).resolve())])
    subprocess.run(cmd, cwd=str(REPO_ROOT), check=True)


def _available_resources(db_path: str) -> list[dict]:
    """Read all `state='available'` compute resources from the agent DB."""
    conn = sqlite3.connect(f"file:{db_path}?mode=ro&nolock=1", uri=True, timeout=5)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            """SELECT resource_id, resource_subtype, unit, value, state, attributes
               FROM resources
               WHERE resource_type = 'compute.gpu' AND state = 'available'
               ORDER BY resource_id""",
        ).fetchall()
    finally:
        conn.close()

    out = []
    for row in rows:
        try:
            attrs = json.loads(row["attributes"] or "{}")
        except json.JSONDecodeError:
            attrs = {}
        out.append({
            "resource_id": row["resource_id"],
            "gpu_model": attrs.get("gpu_model"),
            "quantity": int(row["value"]) if row["value"] is not None else 1,
            "sla": attrs.get("sla", 0.0),
            "region": attrs.get("region"),
        })
    return out


def _open_order_resource_ids(db_path: str) -> set[str]:
    """Return the set of resource_ids that currently have an open sell order.

    Used in `--watch` mode to avoid re-publishing a resource that's already
    offered on the market. Inspects the offer_resource JSON for each open
    order and extracts its `resource_id` field.
    """
    conn = sqlite3.connect(f"file:{db_path}?mode=ro&nolock=1", uri=True, timeout=5)
    try:
        rows = conn.execute(
            "SELECT offer_resource FROM orders WHERE status = 'open'",
        ).fetchall()
    finally:
        conn.close()

    covered: set[str] = set()
    for (raw,) in rows:
        if not raw:
            continue
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            continue
        rid = parsed.get("resource_id") if isinstance(parsed, dict) else None
        if rid:
            covered.add(rid)
    return covered


def _publish_offer(
    agent_url: str,
    offer: dict,
    demand: dict,
    duration_hours: int,
    wallet_address: str,
    private_key: Optional[str],
) -> dict:
    """POST /orders/create and return the response as a dict.

    Returns a dict (not the typed StorefrontOrderCreateResponse) for
    backward compat with `_publish_round`'s callers, which inspect
    `resp["order_id"]` and `resp["status"]` directly.
    """
    with SyncStorefrontClient(agent_url, private_key=private_key) as client:
        try:
            resp = client.create_order(
                agent_wallet_address=wallet_address,
                offer=offer,
                demand=demand,
                duration_hours=duration_hours,
            )
        except StorefrontClientError as exc:
            typer.secho(f"Storefront error: {exc}", err=True, fg=typer.colors.RED)
            raise typer.Exit(code=1)
    return {
        "status": resp.status,
        "order_id": resp.order_id,
        "event_id": resp.event_id,
        "root_agent_response": resp.root_agent_response,
        "order_request": resp.order_request,
        **resp.extra,
    }


def _open_order_ids(db_path: str) -> list[str]:
    """Return every status='open' order_id from the agent DB."""
    conn = sqlite3.connect(f"file:{db_path}?mode=ro&nolock=1", uri=True, timeout=5)
    try:
        rows = conn.execute(
            "SELECT order_id FROM orders WHERE status = 'open' ORDER BY created_at",
        ).fetchall()
    finally:
        conn.close()
    return [r[0] for r in rows if r[0]]


def _close_order(
    agent_url: str,
    order_id: str,
    private_key: Optional[str],
) -> dict:
    """POST /orders/close on the storefront; returns the response as a dict."""
    with SyncStorefrontClient(agent_url, private_key=private_key) as client:
        try:
            resp = client.close_order(order_id)
        except StorefrontClientError as exc:
            typer.secho(f"Storefront error: {exc}", err=True, fg=typer.colors.RED)
            raise typer.Exit(code=1)
    return {
        "status": resp.status,
        "event_id": resp.event_id,
        "root_agent_response": resp.root_agent_response,
        "order_request": resp.order_request,
        **resp.extra,
    }


def _publish_round(
    *,
    db_path: str,
    base_url: str,
    demand: dict,
    duration_hours: int,
    wallet_address: str,
    private_key: Optional[str],
    skip_ids: set[str] | None = None,
) -> tuple[list[dict], list[tuple[dict, str]], list[dict]]:
    """Publish one order for every available resource not in `skip_ids`.

    Returns (published, failed, skipped) — each a list of dicts keyed on
    the resource.
    """
    resources = _available_resources(db_path)
    skip_ids = skip_ids or set()

    published: list[dict] = []
    failed: list[tuple[dict, str]] = []
    skipped: list[dict] = []

    for res in resources:
        if res["resource_id"] in skip_ids:
            skipped.append(res)
            continue
        # Explicit resource_id pins this order to a specific DB row, so
        # multiple identical-spec resources each get a distinct order in
        # `--watch` mode.
        offer = {
            "resource_id": res["resource_id"],
            "gpu_model": res["gpu_model"],
            "quantity": res["quantity"],
            "sla": res["sla"],
            "region": res["region"],
        }
        try:
            resp = _publish_offer(
                base_url, offer, demand, duration_hours, wallet_address, private_key,
            )
            published.append({"resource": res, "response": resp})
        except typer.Exit:
            failed.append((res, "HTTP error (see above)"))
        except Exception as exc:
            failed.append((res, str(exc)))

    return published, failed, skipped


def _print_publish_table(console: Console, published: list[dict], failed: list[tuple[dict, str]]) -> None:
    summary = Table(title="Published offers", box=box.SIMPLE_HEAVY, expand=True)
    summary.add_column("Resource", style="bold")
    summary.add_column("GPU")
    summary.add_column("Region")
    summary.add_column("Order ID", overflow="fold")
    summary.add_column("Status")
    for entry in published:
        res = entry["resource"]
        resp = entry["response"]
        summary.add_row(
            res["resource_id"],
            f"{res['gpu_model']} x{res['quantity']}",
            res["region"] or "-",
            str(resp.get("order_id", "-")),
            str(resp.get("status", "-")),
        )
    for res, reason in failed:
        summary.add_row(
            res["resource_id"],
            f"{res['gpu_model']} x{res['quantity']}",
            res["region"] or "-",
            "-",
            f"[red]failed: {reason}[/red]",
        )
    console.print(summary)


def _submit_refund(
    agent_url: str,
    order_id: str,
    buyer_address: str,
    amount: Optional[str],
    token: Optional[str],
    private_key: Optional[str],
) -> dict:
    """POST /orders/refund; returns the storefront's response as a dict."""
    with SyncStorefrontClient(agent_url, private_key=private_key) as client:
        try:
            resp = client.refund_order(
                order_id=order_id,
                buyer_address=buyer_address,
                amount=amount,
                token=token,
            )
        except StorefrontClientError as exc:
            typer.secho(f"Storefront error: {exc}", err=True, fg=typer.colors.RED)
            raise typer.Exit(code=1)
    return {
        "status": resp.status,
        "order_id": resp.order_id,
        "refund_tx": resp.refund_tx,
        **resp.extra,
    }


def _submit_claim(
    agent_url: str,
    order_id: str,
    fulfillment_uid: Optional[str],
    private_key: Optional[str],
) -> dict:
    """POST /orders/claim; returns the storefront's response as a dict."""
    with SyncStorefrontClient(agent_url, private_key=private_key) as client:
        try:
            resp = client.claim_order(order_id=order_id, fulfillment_uid=fulfillment_uid)
        except StorefrontClientError as exc:
            typer.secho(f"Storefront error: {exc}", err=True, fg=typer.colors.RED)
            raise typer.Exit(code=1)
    return {
        "status": resp.status,
        "order_id": resp.order_id,
        "fulfillment_uid": resp.fulfillment_uid,
        "claim_tx": resp.claim_tx,
        **resp.extra,
    }


def register(app: typer.Typer) -> None:
    """Register the top-level `market provide` command."""

    @app.command("claim")
    def claim(
        order_id: str = typer.Argument(..., help="Local order ID on the provider agent."),
        fulfillment_uid: Optional[str] = typer.Option(
            None, "--fulfillment-uid",
            help="Override the fulfillment_uid from local state. Use this if the seller's "
                 "StringObligation attestation landed on-chain but the agent DB is out of sync.",
        ),
        agent_url: Optional[str] = typer.Option(
            None, "--agent-url", "-a",
            help="Provider agent base URL (env: AGENT_URL, BASE_URL_OVERRIDE).",
        ),
        env: Optional[str] = typer.Option(
            None, "--env", "-e",
            help="Env file (reads BASE_URL_OVERRIDE, AGENT_PRIV_KEY).",
        ),
    ) -> None:
        """Collect an escrow on-chain after fulfillment.

        This is the seller's normal settlement path: once the fulfillment
        attestation is on-chain, calling `market claim <order>` tells the
        agent to run `escrow.collect(escrow_uid, fulfillment_uid)` and
        close the order locally. Useful when the automatic post-fulfillment
        collection path failed or was never triggered (agent restart, RPC
        outage, etc.).
        """
        console = Console()
        env_path = Path(env) if env else None
        base_url = resolve_agent_url(agent_url, env_path, default_port=8001)
        private_key = (
            (read_env_value(env_path, "AGENT_PRIV_KEY") if env_path else None)
            or os.getenv("AGENT_PRIV_KEY")
        )

        header = Table.grid(padding=(0, 2))
        header.add_column(style="bold")
        header.add_column()
        header.add_row("Agent", base_url)
        header.add_row("Order", order_id)
        if fulfillment_uid:
            header.add_row("Fulfillment UID override", fulfillment_uid)
        console.print(Panel(header, title="market claim", border_style="cyan"))

        try:
            resp = _submit_claim(base_url, order_id, fulfillment_uid, private_key)
        except typer.Exit:
            raise  # SyncStorefrontClient already reported the error

        status = str(resp.get("status", "?"))
        if status != "claimed":
            typer.secho(
                f"Claim did not succeed: status={status} detail={resp}",
                err=True, fg=typer.colors.RED,
            )
            raise typer.Exit(7)

        result = Table.grid(padding=(0, 2))
        result.add_column(style="bold")
        result.add_column()
        result.add_row("Status", "claimed (order closed)")
        result.add_row("Escrow UID", str(resp.get("escrow_uid", "-")))
        result.add_row("Fulfillment UID", str(resp.get("fulfillment_uid", "-")))
        result.add_row("Collect result", str(resp.get("collect_result", "-")))
        console.print(Panel(result, title="Claim complete", border_style="green"))

    @app.command("refund")
    def refund(
        order_id: str = typer.Argument(..., help="Local order ID on the provider agent."),
        buyer_address: str = typer.Option(
            ..., "--buyer", "-b",
            help="0x-prefixed wallet address to receive the refund.",
        ),
        amount: Optional[str] = typer.Option(
            None, "--amount", "-n",
            help="Refund amount in human token units. Defaults to the order's "
                 "demanded payment (demand.amount * duration_hours).",
        ),
        token: Optional[str] = typer.Option(
            None, "--token",
            help="Override the refund token symbol. Defaults to the token on the order.",
        ),
        agent_url: Optional[str] = typer.Option(
            None, "--agent-url", "-a",
            help="Provider agent base URL (env: AGENT_URL, BASE_URL_OVERRIDE).",
        ),
        env: Optional[str] = typer.Option(
            None, "--env", "-e",
            help="Env file (reads BASE_URL_OVERRIDE, AGENT_PRIV_KEY).",
        ),
    ) -> None:
        """Refund a deal via direct ERC-20 transfer from the provider wallet.

        This bypasses the escrow contract: the provider pays the buyer out of
        their own balance. Use when provisioning failed or the deal otherwise
        can't settle through the normal escrow release path.
        """
        console = Console()
        env_path = Path(env) if env else None
        base_url = resolve_agent_url(agent_url, env_path, default_port=8001)
        private_key = (
            (read_env_value(env_path, "AGENT_PRIV_KEY") if env_path else None)
            or os.getenv("AGENT_PRIV_KEY")
        )

        header = Table.grid(padding=(0, 2))
        header.add_column(style="bold")
        header.add_column()
        header.add_row("Agent", base_url)
        header.add_row("Order", order_id)
        header.add_row("Buyer", buyer_address)
        if amount:
            header.add_row("Amount", f"{amount} {token or '(order default)'}")
        else:
            header.add_row("Amount", "[dim]default from order[/dim]")
        console.print(Panel(header, title="market refund", border_style="yellow"))

        try:
            resp = _submit_refund(
                base_url, order_id, buyer_address, amount, token, private_key,
            )
        except typer.Exit:
            raise  # SyncStorefrontClient already printed the error

        status = str(resp.get("status", "?"))
        if status != "refunded":
            typer.secho(
                f"Refund did not succeed: status={status} detail={resp}",
                err=True, fg=typer.colors.RED,
            )
            raise typer.Exit(6)

        result = Table.grid(padding=(0, 2))
        result.add_column(style="bold")
        result.add_column()
        result.add_row("Status", "refunded")
        result.add_row("Tx hash", str(resp.get("tx_hash", "-")))
        result.add_row("From", str(resp.get("from_address", "-")))
        result.add_row("To", str(resp.get("to_address", "-")))
        tok = resp.get("token") or {}
        result.add_row(
            "Token",
            f"{tok.get('symbol', '-')} ({tok.get('contract_address', '-')})",
        )
        result.add_row("Amount (raw)", str(resp.get("amount_raw", "-")))
        result.add_row("Block", str(resp.get("block_number", "-")))
        console.print(Panel(result, title="Refund complete", border_style="green"))

    @app.command("provide")
    def provide(
        inventory: Optional[str] = typer.Option(
            None, "--inventory", "-i",
            help="Path to a CSV file describing compute resources to import before publishing.",
        ),
        min_price: Optional[str] = typer.Option(
            None, "--min-price", "-p",
            help="Minimum price per order, in human units of --token. Required unless --abort-all is given.",
        ),
        abort_all: bool = typer.Option(
            False, "--abort-all",
            help="Close every open sell order on this agent instead of publishing. Useful on shutdown.",
        ),
        token: str = typer.Option("MOCK", "--token", help="Payment token symbol."),
        duration_hours: int = typer.Option(
            1, "--duration-hours", "-t",
            help="Lease duration offered per order (hours).",
        ),
        watch: bool = typer.Option(
            False, "--watch", "-w",
            help="Keep running: re-publish orders as resources free up. Ctrl-C to stop.",
        ),
        poll_interval: float = typer.Option(
            30.0, "--poll-interval",
            help="Seconds between scans in --watch mode.",
        ),
        agent_url: Optional[str] = typer.Option(
            None, "--agent-url", "-a",
            help="Seller agent base URL (env: AGENT_URL, BASE_URL_OVERRIDE).",
        ),
        env: Optional[str] = typer.Option(
            None, "--env", "-e",
            help="Env file (reads BASE_URL_OVERRIDE, AGENT_PRIV_KEY, AGENT_WALLET_ADDRESS, AGENT_DB_PATH).",
        ),
        db: Optional[str] = typer.Option(
            None, "--db", help="Explicit seller agent SQLite DB path.",
        ),
    ) -> None:
        """Publish sell orders for every available compute resource on the seller's node."""
        console = Console()
        env_path = Path(env) if env else None

        base_url = resolve_agent_url(agent_url, env_path, default_port=8001)
        private_key = (
            (read_env_value(env_path, "AGENT_PRIV_KEY") if env_path else None)
            or os.getenv("AGENT_PRIV_KEY")
        )
        wallet_address = (
            (read_env_value(env_path, "AGENT_WALLET_ADDRESS") if env_path else None)
            or os.getenv("AGENT_WALLET_ADDRESS")
            or ""
        )
        db_path = _resolve_db_path(db, env)
        if not db_path:
            typer.secho(
                "Could not resolve seller agent DB. Pass --db or --env with AGENT_DB_PATH set.",
                err=True, fg=typer.colors.RED,
            )
            raise typer.Exit(1)

        # Mode: abort-all is mutually exclusive with the publish flags.
        if abort_all:
            if inventory or watch or min_price is not None:
                raise typer.BadParameter(
                    "--abort-all is mutually exclusive with "
                    "--inventory, --min-price, and --watch."
                )
            order_ids = _open_order_ids(db_path)
            if not order_ids:
                console.print("[green]No open sell orders — nothing to abort.[/green]")
                return

            console.print(
                Panel(
                    f"[bold]Aborting {len(order_ids)} open order(s)[/bold]\n"
                    f"Agent: {base_url}",
                    title="market provide --abort-all",
                    border_style="yellow",
                )
            )
            closed_count = 0
            failed: list[tuple[str, str]] = []
            for oid in order_ids:
                try:
                    resp = _close_order(base_url, oid, private_key)
                except typer.Exit:
                    failed.append((oid, "HTTP error (see above)"))
                    continue
                except Exception as exc:
                    failed.append((oid, str(exc)))
                    continue
                status = str(resp.get("status", "?"))
                if status in ("closed", "skipped", "queued"):
                    closed_count += 1
                    console.print(f"  [green]✓[/green] {oid} → {status}")
                else:
                    failed.append((oid, resp.get("message") or status))
                    console.print(f"  [red]✗[/red] {oid} → {status}")

            console.print(
                f"\n[bold]Closed {closed_count}/{len(order_ids)} orders[/bold]"
                + (f" [red]({len(failed)} failed)[/red]" if failed else "")
            )
            if failed:
                raise typer.Exit(5)
            return

        if min_price is None:
            raise typer.BadParameter(
                "--min-price is required (or pass --abort-all to close open orders)."
            )

        if inventory:
            csv_file = Path(inventory)
            if not csv_file.exists():
                raise typer.BadParameter(f"Inventory file not found: {inventory}")
            console.print(f"[bold]Importing inventory:[/bold] {csv_file}")
            try:
                _import_csv(str(csv_file), env, db)
            except subprocess.CalledProcessError as exc:
                typer.secho(f"Inventory import failed: {exc}", err=True, fg=typer.colors.RED)
                raise typer.Exit(2)

        demand = {"token": token, "amount": min_price}

        # ------------------------------------------------------------------
        # One-shot path (original behavior)
        # ------------------------------------------------------------------
        if not watch:
            published, failed, _skipped = _publish_round(
                db_path=db_path, base_url=base_url, demand=demand,
                duration_hours=duration_hours, wallet_address=wallet_address,
                private_key=private_key,
            )
            if not published and not failed:
                console.print(
                    "[yellow]No available compute resources in the agent DB.[/yellow] "
                    "Pass --inventory <csv> or seed the DB first.",
                )
                raise typer.Exit(3)

            _print_publish_table(console, published, failed)
            totals = Table.grid(padding=(0, 2))
            totals.add_column(style="bold")
            totals.add_column()
            totals.add_row("Published", str(len(published)))
            totals.add_row("Failed", str(len(failed)))
            totals.add_row("Agent", base_url)
            totals.add_row("Demand per order", f"{min_price} {token}")
            console.print(Panel(totals, title="Summary", border_style="green" if not failed else "yellow"))

            if failed and not published:
                raise typer.Exit(4)
            return

        # ------------------------------------------------------------------
        # --watch loop
        # ------------------------------------------------------------------
        header = Table.grid(padding=(0, 2))
        header.add_column(style="bold")
        header.add_column()
        header.add_row("Agent", base_url)
        header.add_row("Demand per order", f"{min_price} {token}")
        header.add_row("Poll interval", f"{poll_interval:.0f}s")
        header.add_row("Duration per lease", f"{duration_hours}h")
        console.print(Panel(header, title="market provide --watch", border_style="blue"))
        console.print("[dim]Ctrl-C to stop.[/dim]\n")

        total_published = 0
        total_failed = 0
        cycle = 0
        try:
            while True:
                cycle += 1
                covered = _open_order_resource_ids(db_path)
                published, failed, skipped = _publish_round(
                    db_path=db_path, base_url=base_url, demand=demand,
                    duration_hours=duration_hours, wallet_address=wallet_address,
                    private_key=private_key, skip_ids=covered,
                )
                total_published += len(published)
                total_failed += len(failed)

                ts = datetime.now().strftime("%H:%M:%S")
                if published or failed:
                    console.print(f"[dim]{ts}[/dim] cycle {cycle}: "
                                  f"[green]+{len(published)}[/green] new"
                                  + (f" [red]/{len(failed)} failed[/red]" if failed else "")
                                  + (f" [dim](skipped {len(skipped)} already-open)[/dim]" if skipped else ""))
                    _print_publish_table(console, published, failed)
                else:
                    available_count = len(_available_resources(db_path))
                    console.print(
                        f"[dim]{ts}[/dim] cycle {cycle}: no new orders "
                        f"(available={available_count}, already-open={len(covered)})"
                    )

                time.sleep(poll_interval)
        except KeyboardInterrupt:
            console.print(
                f"\n[yellow]Stopped.[/yellow] "
                f"Total cycles={cycle}, published={total_published}, failed={total_failed}.",
            )
