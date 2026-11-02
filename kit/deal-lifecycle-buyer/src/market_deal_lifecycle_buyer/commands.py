"""Reusable evidence commands with a composition-owned store and fresh deal reader."""

import asyncio
from collections.abc import Callable
from dataclasses import asdict
import json
import time

import typer

from market_deal_lifecycle_buyer.retention import DealReader, prune_command
from market_deal_lifecycle_buyer.store import FileEvidenceStore


def create_evidence_command_group(
    store_factory: Callable[[], FileEvidenceStore],
    reader: DealReader,
    *,
    clock: Callable[[], int] = lambda: int(time.time()),
) -> typer.Typer:
    app = typer.Typer(help="Keep and export the buyer's signed deal evidence.")

    @app.command("prune")
    def prune() -> None:
        """Read every deal, then prune only evidence beyond every retention boundary."""
        report = asyncio.run(prune_command(store_factory(), reader, now=clock()))
        typer.echo(json.dumps(asdict(report), sort_keys=True))

    return app
