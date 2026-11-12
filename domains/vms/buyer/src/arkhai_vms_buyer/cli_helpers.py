"""Shared CLI helpers used by ``market buy`` and ``market negotiate``.

Lives next to the per-command modules in ``groups/`` rather than at the
package root so callers don't see it as part of the public API.
"""

from __future__ import annotations
import json

from typing import Any, Optional

from rich.console import Console
from core_buyer import format_buyer_explanation
import typer


def resolve_prices_from_matches(
    *,
    matches: list[dict],
    console: Console,
    params: dict | None = None,
    interactive: bool = False,
) -> tuple[Optional[int], Optional[int]]:
    """Fill missing prices via the configured buyer policy's derivation.

    Thin dispatch carrying only the canonical hook arguments — the
    policy's own values travel inside ``params`` (its namespace), so
    this dispatcher knows no policy's vocabulary. A policy with no
    derivation hook passes its explicit values through.
    """
    from .policy_surface import configured_buyer_policy

    params = dict(params or {})
    policy = configured_buyer_policy()
    if policy.derive_prices is None:
        return params.get("initial_price"), params.get("max_price")
    return policy.derive_prices(
        params=params,
        matches=matches,
        console=console,
        interactive=interactive,
    )


def requested_duration_seconds(
    *, duration_hours: float | None, duration_seconds: int | None,
) -> int | None:
    """The one lease duration a buyer names, in seconds, from either spelling.

    Naming it twice is refused rather than letting one spelling silently win,
    and an explicit duration must be positive; omitting it is resolved after
    selection, where a reserved option requires one and a recurring one does not.
    """
    if duration_hours is not None and duration_seconds is not None:
        typer.secho(
            "Pass --duration-seconds or --duration-hours, not both.",
            err=True, fg=typer.colors.RED,
        )
        raise typer.Exit(2)
    if duration_seconds is not None:
        if duration_seconds <= 0:
            typer.secho(
                "--duration-seconds must be positive when supplied.",
                err=True, fg=typer.colors.RED,
            )
            raise typer.Exit(2)
        return duration_seconds
    if duration_hours is not None:
        if duration_hours <= 0:
            typer.secho(
                "--duration-hours must be positive when supplied.",
                err=True, fg=typer.colors.RED,
            )
            raise typer.Exit(2)
        return round(duration_hours * 3600)
    return None


def emit_lifecycle_disclosure(rows, *, title: str) -> None:
    """Keep public terms visible even when interactive confirmation is disabled."""
    typer.echo(title, err=True)
    for name, value in rows:
        typer.echo(f"  {name}: {value}", err=True)


def emit_buyer_explanation(payload: dict[str, Any]) -> None:
    """Print human evidence followed by one stable machine-readable JSON line."""

    for line in format_buyer_explanation(payload):
        typer.echo(line)
    typer.echo("Explanation JSON:")
    typer.echo(json.dumps(payload, sort_keys=True, separators=(",", ":")))
