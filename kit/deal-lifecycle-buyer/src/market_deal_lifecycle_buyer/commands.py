"""Reusable evidence commands with a composition-owned store and fresh deal reader."""

import asyncio
from collections.abc import Callable
from dataclasses import asdict
import json
import time

import typer

from market_deal_lifecycle.terms import LifecycleTerms
from market_deal_lifecycle_buyer.export import export_case
from market_deal_lifecycle_buyer.retention import DealReader, prune_command
from market_deal_lifecycle_buyer.store import FileEvidenceStore


def create_evidence_command_group(
    store_factory: Callable[[], FileEvidenceStore],
    reader: DealReader,
    *,
    terms_from_agreement: Callable[[bytes], LifecycleTerms | dict | None],
    clock: Callable[[], int] = lambda: int(time.time()),
) -> typer.Typer:
    app = typer.Typer(help="Keep and export the buyer's signed deal evidence.")

    @app.command("prune")
    def prune() -> None:
        """Read every deal, then prune only evidence beyond every retention boundary."""
        report = asyncio.run(prune_command(store_factory(), reader, now=clock()))
        typer.echo(json.dumps(asdict(report), sort_keys=True))

    @app.command("export")
    def export(
        negotiation_id: str,
        claim: str = typer.Option(..., "--claim"),
        requested_outcome: str = typer.Option(..., "--requested-outcome"),
        commitment_ref: str | None = typer.Option(None, "--commitment-ref"),
    ) -> None:
        """Export one case as JSON; evidence and Agreement bodies remain base64 bytes."""
        try:
            requested = json.loads(requested_outcome)
            if not isinstance(requested, dict):
                raise ValueError("requested outcome must be a JSON object")
            case = asyncio.run(export_case(store_factory(), negotiation_id, claim=claim,
                                           requested_outcome=requested, commitment_ref=commitment_ref,
                                           terms_from_agreement=terms_from_agreement))
        except ValueError as exc:
            raise typer.BadParameter(str(exc)) from exc
        typer.echo(case.model_dump_json())

    return app
