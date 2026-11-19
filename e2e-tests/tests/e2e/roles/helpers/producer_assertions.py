"""Assertions over an external producer's outputs, each stated once.

A lane row gives the payments double an input — a payer's stop, a balance that
runs out, a payee's notice, a part reaching its end — and reads what the double
emits: the transaction's signed snapshot, whose contract is the payments
service's own. The expectation over that output is one function here, which
every scenario giving the producer that input asserts through, so no two of
them hold the producer to different expectations.

Reading is the caller's, kept apart from the assertion: a lane row steps the
storefront and reads once, since lane time and the double's controls make the
output due. Each assertion takes the snapshot as JSON, as
``model_dump(mode="json", by_alias=True, exclude_none=True)`` gives it, and the
inputs the expectation is derived from: the row's price and period, its parties'
accounts, its notice, and the instants an earlier read recorded.

Each assertion names the fields it compares, in three kinds:

- **exact** — equal to a value the row's own terms fix: a stop's cause and
  partial-period treatment, the account that stopped the part, an amount derived
  from the row's price and a number of periods;
- **by relation** — equal to a value derived from another field of the output or
  from an instant an earlier read recorded: an effective instant equal to the
  authority's receipt of the stop plus the notice, a ``terms`` stop at the funded
  boundary the snapshot reported, a term end at the Agreement's end, the settled
  amount the periods between the part's start and its stop, the refund the rest
  of what was paid;
- **ignored** — every other field: identifiers (the transaction, request ids,
  the ledger), signatures and the snapshot's signing identity, ``observedAt``,
  sequence numbers (an event's is read only to find the event that stopped the
  part), the fee and net amounts, which are the producer's fee policy, holds,
  release instants, extensions and attachments.

A difference fails the assertion, never skips it, naming every differing field
with its expected and actual values.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Mapping


class _Absent:
    """A field the output does not carry."""

    def __repr__(self) -> str:
        return "<absent>"


ABSENT = _Absent()


@dataclass(frozen=True)
class Check:
    """One field of an output and the value expected of it.

    ``relation`` says what the expected value is derived from, for a field
    compared by relation; an exact field has none.
    """

    field: str
    actual: Any
    expected: Any
    relation: str | None = None

    def holds(self) -> bool:
        return self.actual == self.expected

    def describe(self) -> str:
        how = f" ({self.relation})" if self.relation else ""
        return f"{self.field}: expected {self.expected!r}{how}, got {self.actual!r}"


def require(output: str, checks: list[Check]) -> None:
    """Fail naming every check that does not hold, with both values."""
    differences = [check for check in checks if not check.holds()]
    if differences:
        raise AssertionError(
            f"{output} differs from the expectation:\n"
            + "\n".join(f"  {check.describe()}" for check in differences)
        )


def field(data: Any, path: str) -> Any:
    """The value at a dotted path, list indices written as numbers
    (``parts.0.stop.cause``), or ``ABSENT``."""
    value = data
    for key in path.split("."):
        if isinstance(value, Mapping) and key in value:
            value = value[key]
        elif isinstance(value, list) and key.isdigit() and int(key) < len(value):
            value = value[int(key)]
        else:
            return ABSENT
    return value


def amount(value: Any) -> Any:
    """A minor-units amount as an integer; ``ABSENT`` stays absent."""
    return ABSENT if value is ABSENT else int(value)


def event(snapshot: Mapping[str, Any], sequence: Any) -> Mapping[str, Any]:
    """The transaction event with ``sequence``, or an empty mapping."""
    for entry in snapshot.get("events", []):
        if entry.get("sequence") == sequence:
            return entry
    return {}


def _plus(instant: Any, seconds: int) -> Any:
    return ABSENT if instant is ABSENT else int(instant) + seconds


def _periods(started: Any, until: Any, period_seconds: int, *, started_period: bool) -> Any:
    """The periods from ``started`` to ``until``: whole ones, and with
    ``started_period`` the one in progress too."""
    if started is ABSENT or until is ABSENT:
        return ABSENT
    elapsed = max(0, int(until) - int(started))
    return (math.ceil if started_period else math.floor)(elapsed / period_seconds)


def _times(periods: Any, price: int) -> Any:
    return ABSENT if periods is ABSENT else periods * price


def _stopped_part(snapshot: Mapping[str, Any], part: int) -> tuple[str, Mapping[str, Any]]:
    prefix = f"parts.{part}"
    found = field(snapshot, prefix)
    return prefix, found if isinstance(found, Mapping) else {}


def _settlement_checks(snapshot: Mapping[str, Any], prefix: str, *,
                       settled_expected: Any, settled_relation: str | None) -> list[Check]:
    """The money of a stopped part: its settled amount, nothing left reserved,
    what it kept equal to what it settled, and the rest of what was paid
    returned to the payer."""
    gross = amount(field(snapshot, f"{prefix}.gross"))
    settled = amount(field(snapshot, f"{prefix}.stop.settled.gross"))
    reversed_ = amount(field(snapshot, f"{prefix}.reversed"))
    held = amount(field(snapshot, f"{prefix}.held"))
    released = amount(field(snapshot, f"{prefix}.released"))
    kept = ABSENT if ABSENT in (held, released) else held + released
    remainder = ABSENT if ABSENT in (gross, settled, reversed_) else gross - settled - reversed_
    return [
        Check(f"{prefix}.stop.settled.gross", settled, settled_expected, settled_relation),
        Check(f"{prefix}.reserved", amount(field(snapshot, f"{prefix}.reserved")), 0),
        Check(f"{prefix}.held + {prefix}.released", kept, settled,
              f"{prefix}.stop.settled.gross"),
        Check(f"{prefix}.refunded", amount(field(snapshot, f"{prefix}.refunded")), remainder,
              f"{prefix}.gross less the settled and reversed amounts"),
    ]


def _stopper_check(snapshot: Mapping[str, Any], prefix: str, stop: str, *,
                   account: str | None) -> Check:
    """Who stopped the part: the account of the event that stopped it, or, for a
    stop the terms made, the ``terms`` issuer."""
    stopping = event(snapshot, field(snapshot, f"{prefix}.{stop}.sequence"))
    if account is None:
        return Check(f"the issuer of the event stopping {prefix}",
                     stopping.get("issuer", ABSENT), "terms")
    return Check(f"the account of the event stopping {prefix}",
                 stopping.get("account", ABSENT), account)


def _received_at(snapshot: Mapping[str, Any], prefix: str, stop: str) -> Any:
    return event(snapshot, field(snapshot, f"{prefix}.{stop}.sequence")).get("receivedAt", ABSENT)


def assert_payer_stop(snapshot: Mapping[str, Any], *, payer: str, period_price: int,
                      period_seconds: int, payer_notice_seconds: int = 0,
                      part: int = 0) -> None:
    """The buyer's stop: the part stopped by its payer, the started period charged.

    Exact: the stop's cause ``payer`` and treatment ``charged``, the stopping
    event's account the payer, nothing left reserved. By relation: the stop
    effective at the payments authority's receipt of the event plus the payer's
    notice; settled the periods from the part's start through the one the stop
    falls in, at ``period_price``; what the part kept equal to what it settled;
    the rest of what was paid refunded. Everything else is ignored (module
    docstring).
    """
    prefix, _ = _stopped_part(snapshot, part)
    effective = field(snapshot, f"{prefix}.stop.effectiveAt")
    periods = _periods(field(snapshot, f"{prefix}.started"), effective, period_seconds,
                       started_period=True)
    require(f"the payer's stop of part {part}", [
        Check(f"{prefix}.stop.cause", field(snapshot, f"{prefix}.stop.cause"), "payer"),
        Check(f"{prefix}.stop.partialPeriod", field(snapshot, f"{prefix}.stop.partialPeriod"),
              "charged"),
        _stopper_check(snapshot, prefix, "stop", account=payer),
        Check(f"{prefix}.stop.effectiveAt", effective,
              _plus(_received_at(snapshot, prefix, "stop"), payer_notice_seconds),
              f"the stop's receivedAt plus the payer's notice of {payer_notice_seconds}s"),
        *_settlement_checks(
            snapshot, prefix, settled_expected=_times(periods, period_price),
            settled_relation=f"{periods!r} started periods of {period_seconds}s at {period_price}",
        ),
    ])


def assert_funds_exhausted(snapshot: Mapping[str, Any], *, funded_boundary: int,
                           funded_periods: int, period_price: int, part: int = 0) -> None:
    """Funds running out: the part stopped by its terms at the funded boundary.

    Exact: the stop's cause ``terms``, the stopping event the terms' own,
    ``funded_periods`` periods at ``period_price`` settled, nothing left
    reserved. By relation: the stop effective at ``funded_boundary``, the funded
    boundary a read of the snapshot reported before the stop; what the part kept
    equal to what it settled; the rest of what was paid refunded. The treatment
    is ignored: a stop at a funded boundary falls between periods, so no period
    is in progress for it to treat. Everything else is ignored (module
    docstring).
    """
    prefix, _ = _stopped_part(snapshot, part)
    require(f"the funding stop of part {part}", [
        Check(f"{prefix}.stop.cause", field(snapshot, f"{prefix}.stop.cause"), "terms"),
        _stopper_check(snapshot, prefix, "stop", account=None),
        Check(f"{prefix}.stop.effectiveAt", field(snapshot, f"{prefix}.stop.effectiveAt"),
              funded_boundary, "the funded boundary the snapshot reported before the stop"),
        *_settlement_checks(snapshot, prefix, settled_expected=funded_periods * period_price,
                            settled_relation=None),
    ])


def assert_payee_stop_pending(snapshot: Mapping[str, Any], *, payee: str,
                              payee_notice_seconds: int, part: int = 0) -> None:
    """A spot seller's notice, held as a pending stop.

    Exact: the pending stop's cause ``payee`` and treatment ``returned``, the
    notice's account the payee, no stop yet. By relation: the pending stop due
    at the payments authority's receipt of the notice plus the seller's notice.
    Everything else is ignored (module docstring).
    """
    prefix, _ = _stopped_part(snapshot, part)
    require(f"the seller's pending stop of part {part}", [
        Check(f"{prefix}.pendingStop.cause", field(snapshot, f"{prefix}.pendingStop.cause"),
              "payee"),
        Check(f"{prefix}.pendingStop.partialPeriod",
              field(snapshot, f"{prefix}.pendingStop.partialPeriod"), "returned"),
        _stopper_check(snapshot, prefix, "pendingStop", account=payee),
        Check(f"{prefix}.pendingStop.at", field(snapshot, f"{prefix}.pendingStop.at"),
              _plus(_received_at(snapshot, prefix, "pendingStop"), payee_notice_seconds),
              f"the notice's receivedAt plus the seller's notice of {payee_notice_seconds}s"),
        Check(f"{prefix}.stop", field(snapshot, f"{prefix}.stop"), ABSENT),
    ])


def assert_payee_stop(snapshot: Mapping[str, Any], *, payee: str, payee_notice_seconds: int,
                      period_price: int, period_seconds: int, part: int = 0) -> None:
    """A spot seller's preemption taking effect: the period it falls in returned.

    Exact: the stop's cause ``payee`` and treatment ``returned``, the stopping
    event's account the payee, nothing left reserved. By relation: the stop
    effective at the payments authority's receipt of the notice plus the
    seller's notice; settled only the whole periods from the part's start to the
    stop, at ``period_price``; what the part kept equal to what it settled; the
    rest of what was paid, the unstarted remainder, refunded. Everything else is
    ignored (module docstring).
    """
    prefix, _ = _stopped_part(snapshot, part)
    effective = field(snapshot, f"{prefix}.stop.effectiveAt")
    periods = _periods(field(snapshot, f"{prefix}.started"), effective, period_seconds,
                       started_period=False)
    require(f"the seller's stop of part {part}", [
        Check(f"{prefix}.stop.cause", field(snapshot, f"{prefix}.stop.cause"), "payee"),
        Check(f"{prefix}.stop.partialPeriod", field(snapshot, f"{prefix}.stop.partialPeriod"),
              "returned"),
        _stopper_check(snapshot, prefix, "stop", account=payee),
        Check(f"{prefix}.stop.effectiveAt", effective,
              _plus(_received_at(snapshot, prefix, "stop"), payee_notice_seconds),
              f"the notice's receivedAt plus the seller's notice of {payee_notice_seconds}s"),
        *_settlement_checks(
            snapshot, prefix, settled_expected=_times(periods, period_price),
            settled_relation=f"{periods!r} whole periods of {period_seconds}s at {period_price}",
        ),
    ])


def assert_term_end(snapshot: Mapping[str, Any], *, agreement_end: int, period_price: int,
                    period_seconds: int, part: int = 0) -> None:
    """The term end: the part ended by its terms at the Agreement's end, the
    final partial period returned.

    Exact: the stop's cause ``terms`` and treatment ``returned``, the stopping
    event the terms' own, nothing left reserved. By relation: the stop effective
    at ``agreement_end``, the whole second the Agreement ends at; settled the
    whole periods from the part's start to that end, at ``period_price``; what
    the part kept equal to what it settled; the rest of what was paid refunded.
    Everything else is ignored (module docstring).
    """
    prefix, _ = _stopped_part(snapshot, part)
    periods = _periods(field(snapshot, f"{prefix}.started"), agreement_end, period_seconds,
                       started_period=False)
    require(f"the term end of part {part}", [
        Check(f"{prefix}.stop.cause", field(snapshot, f"{prefix}.stop.cause"), "terms"),
        Check(f"{prefix}.stop.partialPeriod", field(snapshot, f"{prefix}.stop.partialPeriod"),
              "returned"),
        _stopper_check(snapshot, prefix, "stop", account=None),
        Check(f"{prefix}.stop.effectiveAt", field(snapshot, f"{prefix}.stop.effectiveAt"),
              agreement_end, "the Agreement's end"),
        *_settlement_checks(
            snapshot, prefix, settled_expected=_times(periods, period_price),
            settled_relation=f"{periods!r} whole periods of {period_seconds}s at {period_price}",
        ),
    ])
