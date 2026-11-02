"""Interpret site ends from retained compute command and Agreement evidence.

The caller supplies journal facts; this module owns no storage, authority client
or delivery effects. A site cause alone never establishes financial entitlement.
"""

from dataclasses import dataclass
from typing import Any, Protocol


class SiteEnd(Protocol):
    event_id: str
    effective_at: int
    reason: str | None
    caller: Any
    cause: str
    source_state: str
    deadline_phase: str | None
    claimed_deadline: int | None


@dataclass(frozen=True)
class CommandEnd:
    command_ref: str
    kind: str
    at: int
    source_ref: str
    classification: str | None
    evidence_refs: list[str]


@dataclass(frozen=True)
class SiteClassification:
    kind: str | None
    evidence_refs: list[str]
    controlling_source_ref: str | None = None


def classify_site_end(
    event: SiteEnd, *, seller: Any, term_end: int, available: bool,
    commands: list[CommandEnd], termination_ref: str,
) -> SiteClassification:
    """Correlate exact commands, preserving unresolved and independent sources."""
    ref = "site-event:" + event.event_id
    for command in commands:
        commanded = (
            command.kind == "terminate" and event.reason == command.command_ref
            and (event.caller == seller or (
                event.caller is None and event.cause == "release"
                and event.source_state in {"reserved", "leased"} and not available
            )) and command.at <= event.effective_at
        ) or (
            command.kind == "truncate" and event.deadline_phase == "lease"
            and event.claimed_deadline == event.effective_at == command.at
        )
        if commanded:
            # An echo is the same end even when its controlling source is a
            # failure. Do not file the financial consequence a second time.
            return SiteClassification(
                command.classification, [ref, command.source_ref, *command.evidence_refs],
                command.source_ref,
            )
    if event.deadline_phase == "lease" and event.claimed_deadline == event.effective_at == term_end:
        return SiteClassification("terms", [ref])
    if (event.deadline_phase == "reservation" and event.claimed_deadline == event.effective_at
            and not available):
        return SiteClassification("provisioning_failure", [ref])
    if event.reason == termination_ref:
        return SiteClassification(None, [ref])
    if event.cause in {"termination", "force_release"}:
        return SiteClassification("unentitled_withdrawal", [ref])
    # Release/teardown failures can precede the authority end that caused them.
    return SiteClassification(None, [ref])
