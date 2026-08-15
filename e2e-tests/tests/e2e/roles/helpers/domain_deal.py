"""Domain-neutral state and evidence helpers for complete market deals."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Iterable

import pytest


class DealStage(str, Enum):
    """Observable stages every deployable market domain must prove."""

    DISCOVERY = "discovery"
    NEGOTIATION = "negotiation"
    SETTLEMENT = "settlement"
    DELIVERY = "delivery"
    TEARDOWN = "teardown"


_STAGE_ORDER = tuple(DealStage)


@dataclass
class DomainDealState:
    """Schema-opaque state shared by VM, API-credit, and bare-metal scenarios.

    Stable market identities live in named fields. Domain results remain opaque in
    ``delivery`` and ``teardown`` so shared test machinery never guesses a VM host,
    API key, Physical Resource, site, executor, or provider object.
    """

    domain_identity: str
    listing_id: str | None = None
    negotiation_id: str | None = None
    settlement_id: str | None = None
    fulfillment_ref: str | None = None
    delivery: Any | None = None
    teardown: Any | None = None
    _completed: list[DealStage] = field(default_factory=list)

    def complete(self, stage: DealStage, **bindings: Any) -> None:
        """Record one stage in order without interpreting domain payloads."""

        expected = _STAGE_ORDER[len(self._completed)] if len(self._completed) < len(
            _STAGE_ORDER
        ) else None
        if stage is not expected:
            raise AssertionError(
                f"{self.domain_identity} deal stage {stage.value!r} arrived while "
                f"{getattr(expected, 'value', None)!r} was expected"
            )
        for name, value in bindings.items():
            if not hasattr(self, name):
                raise AttributeError(f"DomainDealState has no binding {name!r}")
            current = getattr(self, name)
            if current is not None and current != value:
                raise AssertionError(
                    f"{self.domain_identity} deal changed {name} from "
                    f"{current!r} to {value!r}"
                )
            setattr(self, name, value)
        self._completed.append(stage)

    def assert_complete(self) -> None:
        """Require discovery through domain-defined teardown evidence."""

        if tuple(self._completed) != _STAGE_ORDER:
            missing = [stage.value for stage in _STAGE_ORDER if stage not in self._completed]
            raise AssertionError(
                f"{self.domain_identity} deal is incomplete; missing stages={missing}"
            )


def require_state(state: object, *fields: str) -> None:
    """Skip a dependent scenario stage when an earlier state field is absent."""

    for name in fields:
        value = getattr(state, name, None)
        if not value:
            pytest.skip(
                f"Prerequisite not satisfied: {type(state).__name__}.{name} is "
                f"{value!r}. An earlier stage likely failed."
            )


def ordered_event_groups(
    events: Iterable[dict[str, Any]],
    *event_groups: tuple[str, ...],
) -> list[dict[str, Any]]:
    """Return one event from each ordered public-mechanism boundary group."""

    remaining = iter(events)
    matched: list[dict[str, Any]] = []
    for expected in event_groups:
        if not expected:
            raise ValueError("event group cannot be empty")
        for event in remaining:
            if event.get("event") in expected:
                matched.append(event)
                break
        else:
            seen = [event.get("event") for event in matched]
            raise AssertionError(
                f"run did not emit one of {expected!r} after ordered events {seen!r}"
            )
    return matched


def ordered_events(
    events: Iterable[dict[str, Any]],
    *event_names: str,
) -> list[dict[str, Any]]:
    """Return named run events in order, failing on an absent lifecycle boundary."""

    return ordered_event_groups(events, *((name,) for name in event_names))


def assert_market_run_succeeded(run: Any, *, command: str) -> None:
    """Report a bounded, secret-safe CLI failure without domain assumptions."""

    if run.returncode == 0:
        return
    event_names = [event.get("event", "?") for event in run.read_events()]
    raise AssertionError(
        f"{command} failed rc={run.returncode}; run events={event_names!r}. "
        "Inspect the role-scoped process output directly; it may contain a "
        "transient domain credential and is not copied into test evidence."
    )
