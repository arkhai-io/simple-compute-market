"""The buyer's introduction commands, owned by the mechanism.

Starting an introduction from an accepted run, re-reading it, and re-delivering
it are the same in every domain, so they live here once and every domain buyer
mounts them, as a mechanism's buyer commands are mounted under
``settlement <mechanism>``. What differs by domain -- how a recorded run is
reloaded under that domain's configuration and registry trust, the transport,
the run log, and the buyer's own sinks -- arrives through the context the
domain supplies, so this kit depends on no buyer role package.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any, Protocol

import typer
from market_core.schemas import SettlementPlan
from market_settlement_runtime import derive_obligation_ref

from .settlement_config import MECHANISM


class StartIntroduction(Protocol):
    def __call__(
        self,
        *,
        negotiation_id: str,
        obligation_ref: str,
        contact_payload: Mapping[str, str],
    ) -> Mapping[str, Any]: ...


class ReadIntroduction(Protocol):
    def __call__(self, *, obligation_ref: str) -> Mapping[str, Any]: ...


@dataclass(frozen=True)
class RecoveredIntroductionRun:
    """One accepted run, reloaded by the domain buyer for an introduction command.

    ``deliver`` is the buyer's own delivery bound to this deal, or None when
    the command was not asked to deliver. ``record`` appends one event to the
    run's log.
    """

    negotiation_id: str
    settlement_plan: Mapping[str, Any] | None
    start: StartIntroduction
    read: ReadIntroduction
    record: Callable[..., None]
    deliver: Callable[[Mapping[str, Any]], None] | None = None


class IntroductionCommandContext(Protocol):
    """What a domain buyer supplies to the mechanism's introduction commands."""

    #: The exception the domain's transport raises when the storefront has
    #: deleted the introduction's payloads. It carries ``obligation_ref``,
    #: ``payloads_deleted_at``, and ``outcome()``.
    deleted_error: type[Exception]

    def recover(
        self, run_id: str, config: str | None, *, deliver: bool
    ) -> RecoveredIntroductionRun:
        """Reload ``run_id``; with ``deliver``, build the buyer's sinks first.

        Sinks are built before anything is revealed: a misconfigured sink is
        the operator's own mistake and should surface before anything
        irreversible happens.
        """
        ...


def parse_contact(entries: list[str]) -> dict[str, str]:
    """Read ``key=value`` contact entries, refusing anything else."""

    payload: dict[str, str] = {}
    for entry in entries:
        key, separator, value = entry.partition("=")
        if not separator or not key.strip() or not value.strip():
            raise typer.BadParameter("contact entries must be key=value pairs")
        payload[key.strip()] = value.strip()
    return payload


def introduction_obligation_ref(run: RecoveredIntroductionRun) -> str:
    """The accepted run's one introduction obligation, re-derived."""

    if run.settlement_plan is None:
        raise typer.BadParameter("accepted run has no settlement plan")
    plan = SettlementPlan.model_validate(run.settlement_plan)
    if len(plan.obligations) != 1 or plan.obligations[0].mechanism != MECHANISM:
        raise typer.BadParameter("accepted run is not an introduction deal")
    return derive_obligation_ref(
        run.negotiation_id,
        0,
        plan.obligations[0].model_dump(mode="json"),
    )


def _echo(value: Any) -> None:
    typer.echo(json.dumps(value, ensure_ascii=True, sort_keys=True, default=str))


def _report_deleted(run: RecoveredIntroductionRun, deleted: Any) -> None:
    """Report that the storefront deleted this introduction's contact payloads.

    An outcome, not a failure: the deal stands, but the storefront holds
    neither party's contact any more, so there is nothing to print as a reveal
    and nothing to deliver. Copies this buyer already delivered are untouched.
    """

    run.record(
        "introduction_payloads_deleted",
        obligation_ref=deleted.obligation_ref,
        payloads_deleted_at=deleted.payloads_deleted_at,
    )
    _echo(deleted.outcome())


def create_contact_command_group(
    context_factory: Callable[[], IntroductionCommandContext],
) -> typer.Typer:
    """Build ``introduce`` and ``introduction`` over a domain buyer's context."""

    group = typer.Typer(
        no_args_is_help=True,
        help="Introduction-only settlement: exchange contacts after an accepted deal.",
    )

    @group.command("introduce")
    def introduce(
        run_id: str = typer.Option(...),
        contact: list[str] = typer.Option(
            ...,
            "--contact",
            help="Your contact payload as key=value entries (repeatable).",
        ),
        config: str | None = typer.Option(None, "--config"),
    ) -> None:
        """Start the introduction: supply your contact, receive the seller's."""

        context = context_factory()
        payload = parse_contact(contact)
        run = context.recover(run_id, config, deliver=True)
        obligation_ref = introduction_obligation_ref(run)
        try:
            projection = run.start(
                negotiation_id=run.negotiation_id,
                obligation_ref=obligation_ref,
                contact_payload=payload,
            )
        except context.deleted_error as deleted:
            _report_deleted(run, deleted)
            return
        run.record("introduction_revealed", obligation_ref=obligation_ref)
        _echo(dict(projection))
        # After the answer is printed: delivery is never fatal, since the
        # reveal is durable and re-readable.
        if run.deliver is not None:
            run.deliver(projection)

    @group.command("introduction")
    def read_introduction(
        run_id: str = typer.Option(...),
        deliver: bool = typer.Option(
            False,
            "--deliver",
            help="Send the introduction to your configured sinks again.",
        ),
        config: str | None = typer.Option(None, "--config"),
    ) -> None:
        """Re-read the revealed introduction; the reveal is durable."""

        context = context_factory()
        run = context.recover(run_id, config, deliver=deliver)
        obligation_ref = introduction_obligation_ref(run)
        try:
            projection = run.read(obligation_ref=obligation_ref)
        except context.deleted_error as deleted:
            _report_deleted(run, deleted)
            return
        _echo(dict(projection))
        if run.deliver is not None:
            run.deliver(projection)

    return group


__all__ = [
    "IntroductionCommandContext",
    "ReadIntroduction",
    "RecoveredIntroductionRun",
    "StartIntroduction",
    "create_contact_command_group",
    "introduction_obligation_ref",
    "parse_contact",
]
