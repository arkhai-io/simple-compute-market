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
  payments authority's revision identifier. A scenario missing one is a
  blocked skip naming it, so its observation is unproven rather than made with
  no provenance.

A value that is not a positive whole number of seconds, or terms no deal can
hold, fail the scenario naming the setting.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import timedelta
from typing import Any, Callable

import pytest

from e2e_harness.settings import settings
from tests.e2e.roles.helpers.compute_deal_stages import DURATION_HOURS
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
    """The public-safe provenance a live run's evidence is labelled with."""

    source_revision: str
    target_alias: str
    payments_revision: str


def live_provenance(*, setting: Callable[[str], Any] = _setting) -> Provenance:
    """The run's provenance, or a blocked skip naming every setting it lacks."""
    values = {name: _live_setting(name, setting) for name in PROVENANCE}
    missing = [f"{SECTION}.{name}" for name, value in values.items() if value is None]
    if missing:
        pytest.skip(f"blocked: live evidence is labelled with its provenance, and the run "
                    f"states no {', '.join(missing)}")
    return Provenance(source_revision=str(values["SOURCE_REVISION"]),
                      target_alias=str(values["TARGET_ALIAS"]),
                      payments_revision=str(values["PAYMENTS_REVISION"]))


__all__ = [
    "LISTING_MAXIMUM_SECONDS",
    "LiveSettings",
    "POLL_INTERVAL",
    "Provenance",
    "live_provenance",
    "live_settings",
]
