"""Neutral stop permissions derived from accepted rights, never implicit roles."""

from dataclasses import dataclass

from .terms import EarlyTermination, partial_period


@dataclass(frozen=True)
class StopAuthority:
    account: str
    notice_seconds: int
    partial_period: str
    role: str


def derive_stop_authorities(
    early: EarlyTermination | None, *, payer: str, payee: str, dispute: str,
    stoppable: bool, supported_partial_periods: frozenset[str] = frozenset(),
) -> tuple[StopAuthority, ...]:
    if not stoppable:
        if early is not None:
            raise ValueError("a once part has no stop authority")
        return ()
    # An authority-specified treatment is a contract capability too. No
    # composition gets outcome authority merely by assuming it is supported.
    if "chosen" not in supported_partial_periods:
        raise ValueError("installed payment contract has no chosen stop treatment")
    entries = []
    if early is not None:
        for role, entitlement in early.entitlements.items():
            entries.append(StopAuthority(
                {"payer": payer, "payee": payee}[role], entitlement.notice_seconds,
                partial_period(entitlement.settles_through, supported_partial_periods), role,
            ))
    entries.append(StopAuthority(dispute, 0, "chosen", "dispute"))
    return tuple(entries)


def entitled_stop(
    account: str, authorities: tuple[StopAuthority, ...], *,
    notice_seconds: int, partial_period: str,
) -> StopAuthority:
    """Refuse a missing entry, notice waiver or treatment override before I/O.

    Parties cannot use the dispute authority's chosen entry; only the dispute
    authority applies outcome effects through its own interface.
    """
    for entry in authorities:
        if entry.account == account and entry.role != "dispute":
            if entry.notice_seconds != notice_seconds or entry.partial_period != partial_period:
                raise ValueError("stop must preserve its committed notice and treatment")
            return entry
    raise ValueError("sender has no entitled stop entry")
