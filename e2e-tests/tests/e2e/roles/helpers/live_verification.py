"""What a live verification scenario reads of its run beside the payments target.

A live verification scenario gives a live producer the input its lane twin gave
the producer's double and compares the output through the lane twin's shared
assertion (``producer_assertions.py``), on wall time. Its run states, in the
``LIVE`` section (environment prefix ``ARKHAI_LIVE__``):

- the per-period terms its deal is offered on, since on wall time a period, a
  seller's notice and a term pass only in real time: PERIOD_SECONDS,
  PAYEE_NOTICE_SECONDS and MAXIMUM_TERM_SECONDS, defaulting to the lanes'
  values, a fifteen-minute period, a two-minute notice and an hour's term;
- POLL_BOUND_SECONDS, how long a scenario polls the producer for an output it
  makes on its own schedule once its instant has passed, two minutes unless
  stated;
- the provenance its evidence is labelled with, all public-safe:
  SOURCE_REVISION, the revision of this repository's code the topology runs;
  TARGET_ALIAS, the deployment's alias for the topology; PAYMENTS_REVISION, the
  payments authority's revision identifier; and, for a scenario that files a
  case, MEDIATION_REVISION, the mediation authority's. A scenario missing one
  is a blocked skip naming it, so its observation is unproven rather than made
  with no provenance.

A scenario that files a case polls the dispute authority's record until the
case is closed (``await_case_closed``), bounded like any other output.

A value that is not a positive whole number of seconds fails the scenario
naming the setting, and so do a term past the listing's maximum duration, a
period longer than the term and a notice no shorter than it. The market
refuses the other terms no deal can hold where it publishes the option or
accepts the Agreement, which ``e2e-tests/README.md``'s "Live verification"
states.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from datetime import timedelta
from typing import Any, Callable, Mapping

import pytest

from e2e_harness.settings import settings
from tests.e2e.roles.helpers.compute_deal_stages import DURATION_HOURS
from tests.e2e.roles.helpers.lane_time import PollBoundPassed, poll_until
from tests.e2e.roles.helpers.rate_servicing_stages import SPOT_NOTICE_SECONDS
from tests.e2e.roles.helpers.recurring_purchase_stages import PERIOD_SECONDS, RateTerms

log = logging.getLogger(__name__)

SECTION = "LIVE"
#: How often a scenario repeats a producer's read while it polls.
POLL_INTERVAL = timedelta(seconds=2)
#: The listing a live scenario creates offers the lanes' maximum duration, so
#: no term longer than it can be bought.
LISTING_MAXIMUM_SECONDS = DURATION_HOURS * 3600
DEFAULT_POLL_BOUND_SECONDS = 120
#: The provenance settings, each named in a skip when absent.
PROVENANCE = ("SOURCE_REVISION", "TARGET_ALIAS", "PAYMENTS_REVISION")
#: The provenance setting a scenario filing a case also needs.
MEDIATION_PROVENANCE = "MEDIATION_REVISION"


def _setting(path: str) -> Any:
    return settings.get(path)


def _live_setting(name: str, setting: Callable[[str], Any]) -> Any:
    value = setting(f"{SECTION}.{name}")
    return None if value is None or value == "" else value


def _seconds(name: str, default: int, setting: Callable[[str], Any]) -> int:
    value = _live_setting(name, setting)
    if value is None:
        return default
    # A bool is an int to Python, but no number of seconds.
    if type(value) is int and value > 0:
        return value
    if isinstance(value, str) and value.strip().isdecimal() and int(value.strip()) > 0:
        return int(value.strip())
    pytest.fail(f"{SECTION}.{name} must be a positive whole number of seconds, not {value!r}")


@dataclass(frozen=True)
class LiveSettings:
    """A live run's per-period terms and polling bound."""

    period_seconds: int
    payee_notice_seconds: int
    maximum_term_seconds: int
    poll_bound_seconds: int

    @property
    def rate_terms(self) -> RateTerms:
        return RateTerms(self.period_seconds)

    @property
    def poll_bound(self) -> timedelta:
        return timedelta(seconds=self.poll_bound_seconds)

    @property
    def reach_bound(self) -> timedelta:
        """The longest wait for an instant of the deal: none lies past its
        Agreement's end, at most the term after any stage of it."""
        return timedelta(seconds=self.maximum_term_seconds)


def live_settings(*, setting: Callable[[str], Any] = _setting) -> LiveSettings:
    """The run's ``LIVE`` terms, each defaulting to the lanes' value."""
    read = LiveSettings(
        period_seconds=_seconds("PERIOD_SECONDS", PERIOD_SECONDS, setting),
        payee_notice_seconds=_seconds("PAYEE_NOTICE_SECONDS", SPOT_NOTICE_SECONDS, setting),
        maximum_term_seconds=_seconds("MAXIMUM_TERM_SECONDS", LISTING_MAXIMUM_SECONDS, setting),
        poll_bound_seconds=_seconds("POLL_BOUND_SECONDS", DEFAULT_POLL_BOUND_SECONDS, setting),
    )
    if read.maximum_term_seconds > LISTING_MAXIMUM_SECONDS:
        pytest.fail(f"{SECTION}.MAXIMUM_TERM_SECONDS is {read.maximum_term_seconds}, longer than "
                    f"the {LISTING_MAXIMUM_SECONDS}-second maximum duration the scenario's "
                    "listing offers")
    if read.period_seconds > read.maximum_term_seconds:
        pytest.fail(f"{SECTION}.PERIOD_SECONDS is {read.period_seconds}, longer than the "
                    f"{read.maximum_term_seconds}-second term")
    if read.payee_notice_seconds >= read.maximum_term_seconds:
        pytest.fail(f"{SECTION}.PAYEE_NOTICE_SECONDS is {read.payee_notice_seconds}, no "
                    f"shorter than the {read.maximum_term_seconds}-second term")
    return read


@dataclass(frozen=True)
class Provenance:
    """The public-safe provenance a live run's evidence is labelled with; the
    mediation authority's revision only for a scenario that files a case."""

    source_revision: str
    target_alias: str
    payments_revision: str
    mediation_revision: str | None = None


def live_provenance(*, setting: Callable[[str], Any] = _setting,
                    mediation: bool = False) -> Provenance:
    """The run's provenance, or a blocked skip naming every setting it lacks;
    with ``mediation``, for a scenario whose evidence is also the mediation
    authority's, MEDIATION_REVISION among them."""
    names = PROVENANCE + ((MEDIATION_PROVENANCE,) if mediation else ())
    values = {name: _live_setting(name, setting) for name in names}
    missing = [f"{SECTION}.{name}" for name, value in values.items() if value is None]
    if missing:
        pytest.skip(f"blocked: live evidence is labelled with its provenance, and the run "
                    f"states no {', '.join(missing)}")
    revision = values.get(MEDIATION_PROVENANCE)
    return Provenance(source_revision=str(values["SOURCE_REVISION"]),
                      target_alias=str(values["TARGET_ALIAS"]),
                      payments_revision=str(values["PAYMENTS_REVISION"]),
                      mediation_revision=None if revision is None else str(revision))


def _holds(record: list[Mapping[str, Any]], case_ref: str, kind: str) -> bool:
    return any(entry.get("case_ref") == case_ref and entry.get("kind") == kind
               for entry in record)


def await_case_closed(
    read: Callable[[], list[dict[str, Any]]], *, case_ref: str, bound: timedelta,
    ruling_requirement: str | None = None, interval: timedelta = POLL_INTERVAL,
    clock: Callable[[], float] = time.monotonic, sleep: Callable[[float], Any] = time.sleep,
) -> list[dict[str, Any]]:
    """The Agreement's signed record, read by ``read`` until it holds the case's
    ``closed`` entry; that record.

    The dispute authority rules and closes a case on its own schedule, so the
    record is polled (``lane_time.poll_until``) and, once ``bound`` has passed
    without the case closed, the stage fails naming the case and the last
    record: an authority that documents the ruling and does not make it
    differs from the expectation. Where a ruling is a decision a person makes,
    reaching the scenario only through a policy the topology applies, a
    record holding no ruling of the case once the bound has passed is the
    topology's unmet requirement instead: a blocked skip naming
    ``ruling_requirement``, so the observation is unproven. A ruling made and
    the case still open at the bound fails, as the authority's own, and so
    does any failure of a read itself: only the bound passing is the
    requirement's.
    """
    try:
        return poll_until(read, lambda record: _holds(record, case_ref, "closed"),
                          bound=bound, interval=interval, what=f"case {case_ref} closed",
                          clock=clock, sleep=sleep)
    except PollBoundPassed as passed:
        if ruling_requirement is not None and not _holds(passed.last, case_ref, "ruled"):
            pytest.skip(f"blocked: case {case_ref} was not ruled within {bound}, and "
                        f"{ruling_requirement}")
        raise


__all__ = [
    "LISTING_MAXIMUM_SECONDS",
    "LiveSettings",
    "MEDIATION_PROVENANCE",
    "POLL_INTERVAL",
    "Provenance",
    "await_case_closed",
    "live_provenance",
    "live_settings",
]
