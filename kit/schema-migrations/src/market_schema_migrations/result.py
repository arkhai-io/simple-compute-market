"""What a startup check found, and the words a service refuses a database with.

This module knows nothing of the engine: a result is plain data, so a service
whose migrations run on another engine can report through the same result and
refuse with the same message.

Every chain is supported from a floor release. A database that release ran on
is adopted whatever earlier releases recorded in it; a database older than the
floor upgrades through the floor release first, since the image cannot reach it
itself, and a database the chain did not build is not the service's to
migrate. No refusal sends an operator to a fresh database: that discards a
deployment's state, and is never the remedy for a database that can upgrade.
See openspec/specs/deployment-state/spec.md#requirement-service-owned-migration-history.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass


class CheckState(enum.Enum):
    """How a database stands against the migrations an image carries."""

    ABSENT = "absent"
    """No database file, or one recording no migrations and holding no tables."""

    BEHIND = "behind"
    """Every recorded migration is known and some are pending, or the supported
    baseline is still to be adopted."""

    AHEAD = "ahead"
    """The database records a migration this image does not know on a history
    a newer image of this chain built: a ledger recording the chain's baselines
    and an unknown ID, or, where a service records a single revision, one that
    neither the chain nor its history up to its floor holds."""

    UNSUPPORTED = "unsupported"
    """No step of the chain reaches the database: it is older than the floor, or
    the chain did not build it."""

    COMPATIBLE = "compatible"
    """The recorded migrations are exactly the image's."""


class UnsupportedCause(enum.Enum):
    """Why a database is unsupported, as far as its ledger can tell."""

    OLDER_OR_SHARED = "older than the floor, or another service's"
    """The ledger records some of the floor's migrations but not all, and none
    of the chain's baselines. Services sharing part of their history record the
    same IDs, so the ledger cannot tell an older database of the service's own
    from another service's."""

    NOT_THIS_CHAIN = "not built by this chain"
    """The database holds tables but records no migration, or records none of
    the floor's migrations or the chain's baselines."""


@dataclass(frozen=True)
class CheckResult:
    """One database's state, with the migration IDs that make it so.

    ``pending`` lists, in the order they would apply, the migrations a run would
    apply; ``unknown`` the recorded migrations the image does not know on a
    database a newer image of the chain built -- one recording its baselines,
    or at a single revision neither the chain nor its history up to its floor
    holds -- which take precedence over pending ones, since this image cannot
    vouch for such a database. ``missing`` lists the floor's migrations an older
    database never recorded. ``adopting`` lists the baseline migrations a run
    would record, without running them, in place of the floor release's
    records, so a preview names every ID the run records even when no migration
    follows the baseline; ``set_aside``, sorted, every other recorded ID the
    adoption would forget, which earlier releases wrote and the chain does not
    list. ``current`` is the newest migration the database records that the
    image knows, or the revision it is at, where a service has one. ``floor``
    names the release the chain is supported from, and ``cause`` says why an
    unsupported database is.
    """

    state: CheckState
    pending: tuple[str, ...] = ()
    unknown: tuple[str, ...] = ()
    missing: tuple[str, ...] = ()
    adopting: tuple[str, ...] = ()
    set_aside: tuple[str, ...] = ()
    current: str | None = None
    floor: str | None = None
    cause: UnsupportedCause | None = None

    @property
    def compatible(self) -> bool:
        return self.state is CheckState.COMPATIBLE

    @property
    def adoption_pending(self) -> bool:
        """The supported baseline is still to be adopted."""

        return bool(self.adopting)


def _ids(ids: tuple[str, ...]) -> str:
    return ", ".join(ids)


def _floor(result: CheckResult) -> str:
    return result.floor if result.floor is not None else "the release it is supported from"


def _released(release: str, service: str) -> str:
    """The service as a release shipped it: "example 1.0.0's billing service"
    for the service "the billing service"."""

    bare = service[4:] if service.startswith("the ") else service
    return f"{release}'s {bare}"


def describe(result: CheckResult) -> str:
    """One line naming the state and every differing migration ID."""

    parts = [result.state.value]
    if result.cause is not None:
        parts[0] = f"{result.state.value} ({result.cause.value})"
    if result.current is not None:
        parts.append(f"at {result.current}")
    if result.adopting:
        parts.append(f"supported baseline to be adopted: {_ids(result.adopting)}")
        parts.append(f"replacing the records of {_floor(result)}")
    if result.set_aside:
        parts.append(f"records set aside: {_ids(result.set_aside)}")
    if result.unknown:
        parts.append(f"unknown: {_ids(result.unknown)}")
    if result.pending:
        parts.append(f"pending: {_ids(result.pending)}")
    if result.missing:
        parts.append(f"missing: {_ids(result.missing)}")
    return "; ".join(parts)


def refusal_message(result: CheckResult, *, service: str, command: str) -> str:
    """Why ``service`` will not start on this database, and what to do.

    Every message names the migration command; each state names the remedy it
    calls for, since they differ: a behind or absent database is migrated; an
    ahead one is restored from its backup or served by the image that wrote it;
    an older one, once the operator confirms it is the service's, upgrades
    through the floor release first; and one the chain did not build is not the
    service's to migrate, so no remedy is named for it.
    """

    state = result.state
    if state is CheckState.COMPATIBLE:
        return f"{service}'s database is compatible with its migrations."
    if state is CheckState.ABSENT:
        return (
            f"{service} found no migrated database at its configured location. "
            f"Run `{command}` to create it before starting {service}."
        )
    if state is CheckState.BEHIND:
        steps = []
        if result.adopting:
            adoption = (
                "its supported baseline is to be adopted "
                f"(recording {_ids(result.adopting)}), replacing the records of "
                f"{_floor(result)}"
            )
            if result.set_aside:
                adoption += (
                    " and setting aside records earlier releases wrote: "
                    f"{_ids(result.set_aside)}"
                )
            steps.append(adoption)
        if result.pending:
            steps.append(f"migrations {_ids(result.pending)} are pending")
        at = f" at {result.current}" if result.current is not None else ""
        return (
            f"{service}'s database{at} is behind its migrations: "
            f"{' and '.join(steps)}. "
            f"Run `{command}` to apply them before starting {service}; "
            f"`{command} --check` lists them without changing anything."
        )
    if state is CheckState.AHEAD:
        pending = (
            f" It also lacks migrations {_ids(result.pending)}."
            if result.pending
            else ""
        )
        at = f" at {result.current}" if result.current is not None else ""
        return (
            f"{service}'s database{at} is ahead of this image: it records "
            f"migrations {_ids(result.unknown)}, which this image does not know."
            f"{pending} `{command}` will not change it. Restore the backup taken "
            "before the upgrade that wrote them, or run the image that wrote them."
        )
    if result.cause is UnsupportedCause.OLDER_OR_SHARED:
        floor = _floor(result)
        released = _released(floor, service)
        lacks = (
            f"lacks migrations {_ids(result.missing)} that {released} recorded"
            if result.missing
            else f"lacks migrations that {released} recorded"
        )
        return (
            f"{service}'s database {lacks}. If it is {service}'s database, it "
            f"predates {floor}, the release it is supported from: upgrade it "
            f"through {floor} first — run {released} on it — then run "
            f"`{command}`. Confirm it is first: `{command}` cannot tell another "
            "service's database from an older one of its own."
        )
    return (
        f"{service}'s database was not built by `{command}`: it holds tables, but "
        f"its ledger shows no state {service}'s migrations or the release it is "
        f"supported from leave, so `{command}` cannot migrate it. Check that "
        f"{service} is configured with its own database."
    )
