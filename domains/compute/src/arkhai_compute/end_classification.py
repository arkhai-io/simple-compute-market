"""Interpret site ends from retained compute command and Agreement evidence.

The caller supplies journal facts; this module owns no storage, authority client
or delivery effects. A site cause alone never establishes financial entitlement.
"""

from collections.abc import Callable, Iterable, Iterator, Mapping
from dataclasses import dataclass
from typing import Any, Protocol, TypeVar


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


class EndRequest(Protocol):
    source_ref: str
    source: str
    ended_at: int


class PhysicalCommand(Protocol):
    intent_ref: str
    kind: str
    payload: dict


class ClassifiedEvidence(Protocol):
    kind: str
    evidence_refs: list[str]


RequestT = TypeVar("RequestT", bound=EndRequest)
ActorT = TypeVar("ActorT")


def site_classification(
    event: SiteEnd, *, seller: Any, term_end: int, available: bool,
    intents: Iterable[PhysicalCommand], requests: Iterable[EndRequest],
    classifications: Mapping[str, ClassifiedEvidence | None], termination_ref: str,
) -> SiteClassification:
    """Correlate supplied immutable journal facts without owning their storage."""
    requests = tuple(requests)
    commands = []
    for intent in intents:
        if intent.kind not in {"terminate", "truncate"}:
            continue
        for request in requests:
            classification = classifications.get(request.source_ref)
            if request.ended_at == intent.payload["at"] and classification is not None:
                commands.append(CommandEnd(
                    intent.intent_ref, intent.kind, intent.payload["at"], request.source_ref,
                    classification.kind, classification.evidence_refs,
                ))
    return classify_site_end(
        event, seller=seller, term_end=term_end, available=available,
        commands=commands, termination_ref=termination_ref,
    )


def resolve_site_corrections(
    requests: Iterable[RequestT], *, classifications: Mapping[str, ClassifiedEvidence | None],
    report_for: Callable[[str], SiteEnd], classify: Callable[[SiteEnd], SiteClassification],
) -> Iterator[tuple[RequestT, SiteClassification]]:
    """Select resolvable pending site statements; callers own codec and atomic writes."""
    for request in requests:
        if request.source != "lease_ended" or classifications.get(request.source_ref) is not None:
            continue
        result = classify(report_for(request.source_ref))
        if result.kind is not None:
            yield request, result


def payment_actor(
    value: str, *, payer_account: str | None, payee_account: str | None,
    buyer: ActorT, seller: ActorT, authority_account: str | None, authority: ActorT | None,
) -> ActorT:
    """Match accepted opaque accounts, never parse one as a marketplace identity."""
    if payer_account is not None and value == payer_account:
        return buyer
    if value == "terms" or payee_account is not None and value == payee_account:
        return seller
    if authority_account is not None and value == authority_account and authority is not None:
        return authority
    raise ValueError("unrecognized payment actor")


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
