"""What a startup check found, and the words a service refuses a database with.

This module knows nothing of the engine: a result is plain data, so a service
whose migrations run on another engine can report through the same result and
refuse with the same message.
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
    """The database records a migration this image does not know."""

    UNSUPPORTED = "unsupported"
    """The database holds state from before the supported baseline."""

    COMPATIBLE = "compatible"
    """The recorded migrations are exactly the image's."""


@dataclass(frozen=True)
class CheckResult:
    """One database's state, with the migration IDs that make it so.

    ``pending`` lists, in the order they would apply, the migrations a run would
    apply; ``unknown`` the recorded migrations the image does not know, which
    take precedence over pending ones, since this image cannot vouch for such a
    database. ``missing`` lists the baseline-floor migrations an unsupported
    database never recorded. ``adopting`` lists the baseline migrations a run
    would record, without running them, in place of a supported database's
    floor records, so a preview names every ID the run records even when no
    migration follows the baseline. ``current`` is the newest migration the
    database records that the image knows, or the revision it is at, where a
    service has one.
    """

    state: CheckState
    pending: tuple[str, ...] = ()
    unknown: tuple[str, ...] = ()
    missing: tuple[str, ...] = ()
    adopting: tuple[str, ...] = ()
    current: str | None = None

    @property
    def compatible(self) -> bool:
        return self.state is CheckState.COMPATIBLE

    @property
    def adoption_pending(self) -> bool:
        """The supported baseline is still to be adopted."""

        return bool(self.adopting)


def _ids(ids: tuple[str, ...]) -> str:
    return ", ".join(ids)


def describe(result: CheckResult) -> str:
    """One line naming the state and every differing migration ID."""

    parts = [result.state.value]
    if result.current is not None:
        parts.append(f"at {result.current}")
    if result.adopting:
        parts.append(f"supported baseline to be adopted: {_ids(result.adopting)}")
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
    calls for, since they differ: a behind or absent database is migrated, an
    ahead one is restored from its backup or served by the image that wrote it,
    and an unsupported one is replaced by a fresh database.
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
            steps.append(
                "its supported baseline is to be adopted "
                f"(recording {_ids(result.adopting)})"
            )
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
    missing = (
        f" It lacks migrations {_ids(result.missing)} of the supported baseline."
        if result.missing
        else ""
    )
    return (
        f"{service}'s database predates its supported baseline and cannot be "
        f"migrated by `{command}`.{missing} Start {service} on a fresh database."
    )
