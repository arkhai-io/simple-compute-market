"""The domain's command group.

Listing, buy, negotiate, settle, delivered credentials, and settlement readiness.
"""

from __future__ import annotations

import asyncio
import json
import os
import tempfile
from pathlib import Path
from typing import Any, NoReturn

import typer
from core_buyer.run_log import RunLogError, read_run, runs_dir
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from arkhai_api_buying import buy, common, negotiate, settle
from arkhai_api_buying.credentials import CredentialStoreError, checked_run_id
from arkhai_api_buying.listing import listing_app
from arkhai_api_buying.settlement_composition import BuyerSettlementComposition


def _settlement_app(settlement: BuyerSettlementComposition) -> typer.Typer:
    def status(
        as_json: bool = typer.Option(False, "--json", help="Emit sanitized JSON."),
    ) -> None:
        config, statuses = asyncio.run(settlement.readiness())
        if as_json:
            typer.echo(
                json.dumps(
                    {
                        "schema_version": config.schema_version,
                        "priority": list(config.priority),
                        "mechanisms": [status.safe_projection() for status in statuses],
                    },
                    separators=(",", ":"),
                    sort_keys=True,
                )
            )
        else:
            for status in statuses:
                state = (
                    "ready"
                    if status.ready
                    else "disabled"
                    if not status.enabled
                    else "unready"
                )
                typer.echo(f"{status.mechanism}: {state}")
                for blocker in status.blockers:
                    typer.echo(f"  {blocker.code}: {blocker.message}")
        if not any(status.ready for status in statuses):
            raise typer.Exit(1)

    app = typer.Typer(
        no_args_is_help=True,
        help="Shared settlement profile and readiness commands.",
    )
    app.command("status")(status)
    for registration in settlement.registry().registrations:
        if registration.command_group is not None:
            app.add_typer(registration.command_group, name=registration.config_key)
    return app


def _refuse(message: str) -> NoReturn:
    typer.secho(message, err=True, fg=typer.colors.RED)
    raise typer.Exit(1)


def _without_torn_tail(data: bytes) -> bytes | None:
    """``data`` without its last record when that record is torn, else ``None``.

    A torn record is a last line with no terminating newline, or a last line
    that does not parse. Only the last is ever dropped, so a malformed record
    anywhere else is still refused by the reader.
    """
    if not data.endswith(b"\n"):
        return data[: data.rfind(b"\n") + 1]
    body = data.rstrip(b"\n")
    head, _, last = body.rpartition(b"\n")
    try:
        json.loads(last)
    except ValueError:
        return head + b"\n" if head else b""
    return None


def _scrubbed(prefix: bytes) -> bytes:
    """``prefix`` with any legacy run-log secret removed, so a working copy never holds it."""
    lines = []
    for line in prefix.splitlines():
        try:
            record = json.loads(line)
        except ValueError:
            record = None
        credentials = record.get("credentials") if isinstance(record, dict) else None
        if isinstance(credentials, dict) and "secret" in credentials:
            record["credentials"] = {k: v for k, v in credentials.items() if k != "secret"}
            line = json.dumps(record, separators=(",", ":")).encode()
        lines.append(line)
    return b"".join(line + b"\n" for line in lines)


def _read_delivery_run(run_id: str) -> list[dict[str, Any]]:
    """The run's events, read by its recovery identity, tolerating one torn final record.

    A key can be saved and its ``credentials_delivered`` append torn by a
    failing disk. The torn record is dropped and the rest is still validated
    by the core reader, against a private copy, with its ownership checked.
    """
    try:
        identity = common.resolve_recovery_buyer_identity(run_id)
        return read_run(run_id, signer=identity.signer)
    except RunLogError:
        path = runs_dir() / f"{checked_run_id(run_id)}.jsonl"
        data = path.read_bytes() if path.is_file() else b""
        prefix = _without_torn_tail(data)
        if not prefix:
            raise
    with tempfile.TemporaryDirectory() as directory:
        copy = Path(directory) / path.name
        copy.write_bytes(_scrubbed(prefix))
        os.chmod(copy, 0o600)
        identity = common.resolve_recovery_buyer_identity_in(run_id, Path(directory))
        read_run(run_id, signer=identity.signer, directory=Path(directory))
    return [json.loads(line) for line in prefix.splitlines() if line.strip()]


def _delivered_credential(
    settlement: BuyerSettlementComposition, run_id: str,
) -> tuple[dict[str, Any], str]:
    """A run's last delivered credential and where it was read: ``store`` or, for older runs, ``run_log``."""
    try:
        events = _read_delivery_run(run_id)
    except (RunLogError, RuntimeError, ValueError) as exc:
        _refuse(f"Run {run_id!r} cannot be read: {exc}")
    store = settlement.credential_store
    delivered = [event for event in events if event.get("event") == "credentials_delivered"]
    event = delivered[-1] if delivered else {}

    def load(reference: str) -> dict[str, Any] | None:
        try:
            return store.load(reference)
        except CredentialStoreError as exc:
            _refuse(f"Run {run_id!r}'s credential cannot be read: {exc}")

    if event.get("delivery_ref"):
        credentials = load(str(event["delivery_ref"]))
        if credentials is None:
            _refuse(f"The private credential store holds no key for run {run_id!r}.")
        return credentials, "store"
    # A key saved while its run log refused the append is found by run id.
    credentials = load(store.reference(run_id))
    if credentials is not None:
        return credentials, "store"
    legacy = event.get("credentials")
    if isinstance(legacy, dict) and legacy.get("secret"):
        return dict(legacy), "run_log"
    if not delivered:
        _refuse(f"Run {run_id!r} records no delivered credential.")
    _refuse(f"Run {run_id!r}'s delivery returned no secret.")


def _credentials_app(settlement: BuyerSettlementComposition) -> typer.Typer:
    def show(
        run_id: str = typer.Option(
            ..., "--from", "--run", "-r", help="Buyer run-id whose delivered key to show.",
        ),
        as_json: bool = typer.Option(False, "--json", help="Emit the key as one JSON object."),
    ) -> None:
        """Show the API key a run delivered, secret included."""
        credentials, source = _delivered_credential(settlement, run_id)
        if as_json:
            typer.echo(json.dumps(
                {
                    "run_id": run_id,
                    "key_id": credentials.get("key_id"),
                    "secret": credentials.get("secret"),
                    "base_url": credentials.get("base_url"),
                    "balance": credentials.get("balance"),
                    "source": source,
                },
                separators=(",", ":"),
                sort_keys=True,
            ))
            return
        table = Table.grid(padding=(0, 2))
        table.add_column(style="bold")
        table.add_column()
        for label, key in (
            ("Key ID", "key_id"), ("Secret", "secret"), ("Base URL", "base_url"), ("Balance", "balance"),
        ):
            if credentials.get(key) is not None:
                table.add_row(label, str(credentials[key]))
        console = Console()
        console.print(Panel(table, title=f"API key — run {run_id}", border_style="green"))
        if source == "run_log":
            console.print(
                "[yellow]This run was recorded before private credential storage: "
                "its secret is held in the run log.[/yellow]"
            )

    app = typer.Typer(no_args_is_help=True, help="Keys delivered by settled runs.")
    app.command("show")(show)
    return app


def command_group(settlement: BuyerSettlementComposition) -> typer.Typer:
    """The group a buyer plugin registers under its bundle's ``command`` name."""
    group = typer.Typer(no_args_is_help=True)
    group.add_typer(
        listing_app(settlement),
        name="listing",
        help=f"Browse {settlement.contributions.noun} listings (list/show).",
    )
    buy.register(group, settlement=settlement)
    negotiate.register(group, settlement=settlement)
    settle.register(group, settlement=settlement)
    group.add_typer(_credentials_app(settlement), name="credentials")
    group.add_typer(_settlement_app(settlement), name="settlement")
    return group
