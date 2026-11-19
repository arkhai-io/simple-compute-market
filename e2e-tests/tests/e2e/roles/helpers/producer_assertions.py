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

- **exact** — equal to a value the row's own terms fix, or to an input the
  scenario itself sent: a stop's cause and partial-period treatment, the account
  that stopped the part, an amount derived from the row's price and a number of
  periods, a filing's filer and the kind and delivery end its claim names;
- **by relation** — equal to a value derived from another field of the output or
  from an instant an earlier read recorded: an effective instant equal to the
  authority's receipt of the stop plus the notice, a ``terms`` stop at the funded
  boundary the snapshot reported, a term end at the Agreement's end, the settled
  amount the periods between the part's start and its stop, the refund the rest
  of what was paid;
- **ignored** — every other field: identifiers (the transaction, request ids,
  the ledger), signatures and the snapshot's signing identity, ``observedAt``,
  sequence numbers (a payment assertion reads an event's only to find the event
  that stopped the part), the fee and net amounts, which are the producer's fee policy, holds,
  release instants, extensions and attachments.

A difference fails the assertion, never skips it, naming every differing field
with its expected and actual values.

A dispute row's output is two producers': the dispute authority's signed record
of the case, its entries as JSON in sequence as the mediation kit's public
client reads them, and the payments snapshot its effects moved. Its assertions
compare, besides the payment fields above, the claim the filing carries against
the delivery end the scenario filed, the filing's per-part protection, the ruled
entry's basis, delivery end and effects and their applied state, the authority's
stop, reversals and lifted extensions, and the closed case. A payment event's sequence
is read there to match an extension to the filing that reports it, and an
entry's to order the case's entries. They ignore the record's signatures, record
references, case references beyond finding the case, the entries' own ``at``
(the relations read the effects' instants), and the payload a payment event
carries, which is the authority's own: a reversal is matched to its effect by
the order the ruling lists its effects in.
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


# ===========================================================================
# A case ruled on a rate deal: the authority's record and the payments it moved
# ===========================================================================

def _case_entries(record: list[Mapping[str, Any]], case_ref: str,
                  kind: str) -> list[Mapping[str, Any]]:
    """The case's record entries of ``kind``, in sequence."""
    return sorted((entry for entry in record
                   if entry.get("case_ref") == case_ref and entry.get("kind") == kind),
                  key=lambda entry: entry.get("sequence", 0))


def _authority_events(snapshot: Mapping[str, Any], kind: str, authority: str,
                      part: int) -> list[Mapping[str, Any]]:
    """The payment events of ``kind`` the authority's account sent on ``part``, in
    sequence."""
    return sorted((entry for entry in snapshot.get("events", [])
                   if entry.get("account") == authority
                   and field(entry, "event.kind") == kind
                   and field(entry, "event.part") == part),
                  key=lambda entry: entry.get("sequence", 0))


def _protection_checks(record: list[Mapping[str, Any]], snapshot: Mapping[str, Any], *,
                       case_ref: str, filer: str, claimed_end: int, authority: str,
                       part: int) -> list[Check]:
    """The filing and its protection of ``part``: filed once by ``filer``,
    claiming ``delivery_end`` at ``claimed_end``, the end the scenario sent, the
    part held by an extension the authority opened at payments, which it lifted
    once the case closed."""
    filed = _case_entries(record, case_ref, "filed")
    entry: Mapping[str, Any] = filed[0] if filed else {}
    protection = next((item for item in entry.get("parts", []) if item.get("part") == part), {})
    extension = protection.get("extension_ref", ABSENT)
    case = f"case {case_ref}"
    return [
        Check(f"{case}: filed entries", len(filed), 1),
        Check(f"{case}: the filing's actor", entry.get("actor", ABSENT), filer),
        Check(f"{case}: the filed claim's kind", field(entry, "filing.request.kind"),
              "delivery_end"),
        Check(f"{case}: the filed claim's ended_at", field(entry, "filing.request.ended_at"),
              claimed_end),
        Check(f"{case}: the filing's protection of part {part}", protection.get("status", ABSENT),
              "held"),
        Check(f"the authority's extend events on part {part}",
              [item.get("sequence") for item in _authority_events(snapshot, "extend", authority, part)],
              [extension], f"the extension_ref {case}'s filing reports"),
        Check(f"the authority's lift events on part {part}",
              [field(item, "event.ref") for item in _authority_events(snapshot, "lift", authority, part)],
              [extension], f"the extension_ref {case}'s filing reports"),
        Check(f"parts.{part}.extensions", field(snapshot, f"parts.{part}.extensions"), []),
    ]


def _ruling_checks(record: list[Mapping[str, Any]], *, case_ref: str, basis: str,
                   kinds: list[str]) -> tuple[list[Check], dict[str, Mapping[str, Any]]]:
    """The ruling and the closed case: the ruled entry's basis and effects, the
    closed entry closing the case as ruled with those effects, each applied.
    Also the effects by kind, as the closed entry lists them."""
    ruled = _case_entries(record, case_ref, "ruled")
    closed = _case_entries(record, case_ref, "closed")
    ruling: Mapping[str, Any] = ruled[0] if ruled else {}
    closing: Mapping[str, Any] = closed[0] if closed else {}
    outcome = closing.get("outcome", [])
    case = f"case {case_ref}"
    effects = {item["effect"]["kind"]: item for item in outcome if "effect" in item}
    checks = [
        Check(f"{case}: the ruled entry's basis", ruling.get("basis", ABSENT), basis),
        Check(f"{case}: closed entries", len(closed), 1),
        Check(f"{case}: the closed entry's reason", closing.get("reason", ABSENT), "ruled"),
        Check(f"{case}: the closed entry's basis", closing.get("basis", ABSENT), basis),
        Check(f"{case}: the closed entry's effects, by kind",
              [field(item, "effect.kind") for item in outcome], kinds),
        Check(f"{case}: the ruled entry's effects",
              [(item.get("id"), item.get("effect")) for item in ruling.get("outcome", [])],
              [(item.get("id"), item.get("effect")) for item in outcome],
              "the closed entry's effects"),
        Check(f"{case}: the effects' states", [item.get("state") for item in outcome],
              ["applied"] * len(outcome)),
    ]
    return checks, effects


def _authority_stop_checks(snapshot: Mapping[str, Any], effects: Mapping[str, Mapping[str, Any]],
                           *, case_ref: str, authority: str, part: int) -> list[Check]:
    """The ruling's stop: stated at the delivery end, and taken by payments from
    the authority's account with the part's money accounted for. A stop time
    already passed when the authority sends it is a stop at its receipt, since
    payments never backdates one."""
    prefix = f"parts.{part}"
    stop = field(effects.get("stop", {}), "effect")
    stop_at = field(stop, "at")
    received = _received_at(snapshot, prefix, "stop")
    effective = (ABSENT if ABSENT in (stop_at, received) else max(int(stop_at), int(received)))
    gross = amount(field(snapshot, f"{prefix}.gross"))
    held = amount(field(snapshot, f"{prefix}.held"))
    released = amount(field(snapshot, f"{prefix}.released"))
    reversed_ = amount(field(snapshot, f"{prefix}.reversed"))
    remainder = (ABSENT if ABSENT in (gross, held, released, reversed_)
                 else gross - held - released - reversed_)
    case = f"case {case_ref}"
    return [
        Check(f"{case}: the stop effect's part", field(stop, "part"), part),
        Check(f"{case}: the stop effect's partialPeriod", field(stop, "partialPeriod"), "returned"),
        Check(f"{case}: the stop effect's at", stop_at,
              field(effects.get("end_delivery", {}), "effect.at"), "the ruling's delivery end"),
        Check(f"{prefix}.stop.cause", field(snapshot, f"{prefix}.stop.cause"), "authority"),
        Check(f"{prefix}.stop.partialPeriod", field(snapshot, f"{prefix}.stop.partialPeriod"),
              "returned"),
        _stopper_check(snapshot, prefix, "stop", account=authority),
        Check(f"{prefix}.stop.effectiveAt", field(snapshot, f"{prefix}.stop.effectiveAt"), effective,
              "the stop effect's at, or the authority's receipt of the stop once that passed"),
        Check(f"{prefix}.reserved", amount(field(snapshot, f"{prefix}.reserved")), 0),
        Check(f"{prefix}.refunded", amount(field(snapshot, f"{prefix}.refunded")), remainder,
              f"{prefix}.gross less the held, released and reversed amounts"),
    ]


def _ruled_end_check(effects: Mapping[str, Mapping[str, Any]], *, case_ref: str,
                     ruled_end: int) -> Check:
    """The ruling's delivery end, at ``ruled_end``."""
    return Check(f"case {case_ref}: the ruling's delivery end",
                 field(effects.get("end_delivery", {}), "effect.at"), ruled_end)


def _reversal_amounts(snapshot: Mapping[str, Any], *, authority: str, part: int) -> list[int]:
    return [int(field(item, "event.amount"))
            for item in _authority_events(snapshot, "reverse", authority, part)]


def assert_payee_filing_ruled(
    record: list[Mapping[str, Any]], snapshot: Mapping[str, Any], *, case_ref: str, payee: str,
    claimed_end: int, authority: str, penalty: int, period_price: int, period_seconds: int,
    part: int = 0,
) -> None:
    """A seller's ``delivery_end`` filing on a rate deal, ruled as the dispute
    authority documents a mechanical ruling.

    Exact: the case filed once by the payee, claiming ``delivery_end`` at
    ``claimed_end``, the end the storefront filed, ``part`` held; the ruling's
    basis ``payee_filed``, its delivery end the claimed one, as a mechanical
    ruling of the claim states it, its effects a delivery end, a ``stop``
    returning its period, a ``reverse`` and a ``penalty``, in that order, every
    one applied; the case closed as ruled; the part stopped by the authority's
    account with ``returned``, nothing reserved; the case's extension lifted. By relation:
    the extension the filing reports is the one the authority opened and lifted
    at payments; the ruled entry's effects are the closed entry's; the stop
    stated at the delivery end and effective then, or at its receipt once that
    passed; the reverse effect's amount the periods earned after the delivery end
    up to the stop at ``period_price``, and payments reversing exactly it first;
    the penalty's reversals after it the Agreement's ``penalty`` capped at what
    the part still held; the refund the rest of what was paid. The penalty
    effect's recorded amount is ignored, since a producer may record the term or
    its cap: what it moved is compared. Everything else is ignored (module
    docstring).
    """
    prefix = f"parts.{part}"
    ruling, effects = _ruling_checks(record, case_ref=case_ref, basis="payee_filed",
                                     kinds=["end_delivery", "stop", "reverse", "penalty"])
    end_at = field(effects.get("end_delivery", {}), "effect.at")
    started = field(snapshot, f"{prefix}.started")
    effective = field(snapshot, f"{prefix}.stop.effectiveAt")
    after_end = (ABSENT if ABSENT in (started, end_at, effective) else
                 _periods(started, effective, period_seconds, started_period=False)
                 - _periods(started, end_at, period_seconds, started_period=False))
    reverse_amount = amount(field(effects.get("reverse", {}), "effect.amount"))
    reversals = _reversal_amounts(snapshot, authority=authority, part=part)
    taken = sum(reversals[1:])
    held = amount(field(snapshot, f"{prefix}.held"))
    capped = ABSENT if held is ABSENT else min(penalty, taken + held)
    case = f"case {case_ref}"
    require(f"the ruling of {case} on the payee's filing", [
        *_protection_checks(record, snapshot, case_ref=case_ref, filer=payee,
                            claimed_end=claimed_end, authority=authority, part=part),
        *ruling,
        _ruled_end_check(effects, case_ref=case_ref, ruled_end=claimed_end),
        *_authority_stop_checks(snapshot, effects, case_ref=case_ref, authority=authority,
                                part=part),
        Check(f"{case}: the reverse effect's amount", reverse_amount,
              _times(after_end, period_price),
              f"{after_end!r} periods earned after the delivery end, at {period_price}"),
        Check(f"the authority's first reversal of part {part}", reversals[:1],
              [] if reverse_amount is ABSENT else [reverse_amount], "the reverse effect's amount"),
        Check(f"the authority's penalty reversals of part {part}", taken, capped,
              f"the Agreement's penalty of {penalty}, capped at what the part still held"),
    ])


def assert_contested_case_ruled(
    record: list[Mapping[str, Any]], snapshot: Mapping[str, Any], *, case_ref: str, payer: str,
    payee: str, claimed_end: int, authority: str, ruled_end: int | None = None,
    reverse_amount: int | None = None, part: int = 0,
) -> None:
    """A buyer's ``delivery_end`` filing the storefront contested, ruled by an
    operator with a stop and a reverse.

    Exact: the case filed once by the payer, claiming ``delivery_end`` at
    ``claimed_end``, the end the buyer filed, ``part`` held; one answer by the
    payee before the ruling, the contest; the ruling's basis ``operator``, its
    effects a delivery end, a ``stop`` returning its period and a ``reverse``,
    in that order, every one applied; the case closed as ruled; the part stopped
    by the authority's account with ``returned``, nothing reserved; the case's
    extension lifted; the ruling's delivery end ``ruled_end`` and the reverse
    effect's amount ``reverse_amount`` where the caller's own ruling fixed them,
    and each ignored where a policy it does not see chose it. By relation: the
    extension the filing reports is the one the authority opened and lifted at
    payments; the ruled entry's effects are the closed entry's; the stop stated
    at the delivery end and effective then, or at its receipt once that passed;
    payments reversing exactly the reverse effect's amount; the refund the rest
    of what was paid. Everything else is ignored (module docstring).
    """
    ruling, effects = _ruling_checks(record, case_ref=case_ref, basis="operator",
                                     kinds=["end_delivery", "stop", "reverse"])
    ruled = _case_entries(record, case_ref, "ruled")
    ruled_at = ruled[0].get("sequence", 0) if ruled else 0
    answers = [entry.get("actor") for entry in _case_entries(record, case_ref, "appended")
               if entry.get("sequence", 0) < ruled_at]
    effect_amount = amount(field(effects.get("reverse", {}), "effect.amount"))
    case = f"case {case_ref}"
    checks = [
        *_protection_checks(record, snapshot, case_ref=case_ref, filer=payer,
                            claimed_end=claimed_end, authority=authority, part=part),
        Check(f"{case}: the answers before the ruling", answers, [payee]),
        *ruling,
        *_authority_stop_checks(snapshot, effects, case_ref=case_ref, authority=authority,
                                part=part),
        Check(f"the authority's reversals of part {part}",
              _reversal_amounts(snapshot, authority=authority, part=part),
              [] if effect_amount is ABSENT else [effect_amount], "the reverse effect's amount"),
    ]
    if ruled_end is not None:
        checks.append(_ruled_end_check(effects, case_ref=case_ref, ruled_end=ruled_end))
    if reverse_amount is not None:
        checks.append(Check(f"{case}: the reverse effect's amount", effect_amount, reverse_amount))
    require(f"the ruling of {case} on the payer's contested filing", checks)
