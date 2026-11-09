"""The migration engine: chains, the startup check, and applying a chain.

A chain begins with baseline migrations, whose fixed DDL reproduces the schema
the chain is supported from, followed by every later migration in order. A
database recording every ID of the chain's floor -- the chain an earlier
release recorded -- is adopted: its floor records are replaced by the
baseline's in one transaction, without running the baselines, and the later
migrations then apply. Each migration runs in its own transaction with its
record, so a failure leaves the migrations before it recorded and no trace of
itself. Compatibility is the exact set of recorded IDs.

A migration runs inside the engine's transaction, where SQLite ignores
``PRAGMA foreign_keys``: a migration that rebuilds a referenced table cannot
switch enforcement off around the rebuild.
See openspec/specs/deployment-state/spec.md.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Collection, Iterable, Sequence
from contextlib import AbstractContextManager
from dataclasses import dataclass
from typing import Any, Generic, Protocol, TypeVar

from market_schema_migrations.result import CheckResult, CheckState, refusal_message

logger = logging.getLogger(__name__)

LEDGER_TABLE = "schema_migrations"
"""The table recording each applied migration's ID; the engine owns it."""

LEDGER_DDL = (
    f"CREATE TABLE IF NOT EXISTS {LEDGER_TABLE} ("
    "id VARCHAR(255) PRIMARY KEY, "
    "applied_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP)"
)
"""The ledger a fresh database gets. A database whose ledger an earlier engine
created keeps that table: the engine reads and writes only its ``id`` column,
and every earlier ledger defaults its other column."""

C = TypeVar("C")
C_co = TypeVar("C_co", covariant=True)


@dataclass(frozen=True)
class Migration(Generic[C]):
    """One step of a chain: its ID, recorded once applied, and its body.

    The body takes only the connection: no migration reads a service's
    configuration, so one database migrates to one schema and one set of rows
    under any configuration.
    """

    id: str
    apply: Callable[[C], None]


class MigrationConnection(Protocol[C_co]):
    """What the engine needs of a database connection.

    Each adapter wraps one kind of connection, and ``native`` is the connection
    a migration's body receives. Every method other than ``transaction`` runs
    inside a transaction it opened.
    """

    @property
    def native(self) -> C_co: ...

    def transaction(self) -> AbstractContextManager[None]:
        """Begin a transaction; commit it on success, roll it back on an error."""
        ...

    def table_names(self) -> set[str]: ...

    def recorded_ids(self) -> list[str]:
        """Every ID the ledger records; only called when the ledger exists."""
        ...

    def create_ledger(self) -> None: ...

    def record(self, ids: Iterable[str]) -> None: ...

    def forget(self, ids: Iterable[str]) -> None: ...


@dataclass(frozen=True)
class Chain(Generic[C]):
    """A service's migrations, in the order they apply.

    ``service`` and ``command`` name the service and its migration command in
    every refusal. ``baselines`` begin the chain and ``migrations`` follow them.
    ``floor_ids`` are the IDs the chain of the release it is supported from
    recorded; a chain with none adopts no database, so it refuses every
    non-empty database it did not build.
    """

    service: str
    command: str
    baselines: tuple[Migration[C], ...]
    migrations: tuple[Migration[C], ...] = ()
    floor_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.baselines:
            raise ValueError(f"{self.service}'s chain names no baseline migration")
        ids = self.ids
        duplicates = sorted({i for i in ids if ids.count(i) > 1})
        if duplicates:
            raise ValueError(
                f"{self.service}'s chain lists migrations more than once: "
                + ", ".join(duplicates)
            )
        floor_duplicates = sorted(
            {i for i in self.floor_ids if self.floor_ids.count(i) > 1}
        )
        if floor_duplicates:
            raise ValueError(
                f"{self.service}'s floor lists migrations more than once: "
                + ", ".join(floor_duplicates)
            )
        overlap = sorted(set(self.floor_ids) & set(ids))
        if overlap:
            # A floor ID is deleted at adoption; one the chain also lists would
            # be forgotten and never run.
            raise ValueError(
                f"{self.service}'s floor names migrations its chain lists: "
                + ", ".join(overlap)
            )

    @property
    def ids(self) -> tuple[str, ...]:
        return tuple(m.id for m in (*self.baselines, *self.migrations))

    @property
    def baseline_ids(self) -> tuple[str, ...]:
        return tuple(m.id for m in self.baselines)


@dataclass(frozen=True)
class MigrateReport:
    """What one run did: whether it adopted the database, and what it applied."""

    adopted: bool
    applied: tuple[str, ...]


class MigrationRefused(RuntimeError):
    """The database is ahead or unsupported, so the run applied nothing."""

    def __init__(self, result: CheckResult, *, service: str, command: str) -> None:
        super().__init__(refusal_message(result, service=service, command=command))
        self.result = result


class MigrationFailed(RuntimeError):
    """A migration raised; it left no trace, and the ones before it stay recorded."""

    def __init__(self, *, service: str, migration_id: str, cause: BaseException) -> None:
        super().__init__(f"{service}'s migration {migration_id} failed: {cause}")
        self.migration_id = migration_id


def classify(
    chain: Chain[C],
    *,
    tables: Collection[str] | None,
    recorded: Sequence[str] | None,
) -> CheckResult:
    """Judge a database from its tables and the IDs its ledger records.

    ``tables`` is ``None`` when there is no database file; ``recorded`` is
    ``None`` when the database has no ledger. A database records the chain once
    it records any baseline: then an ID the chain does not list is unknown and
    makes it ahead, whatever else it lacks. A database recording no baseline
    but every floor ID is behind, its adoption pending. Anything else holding
    tables or records predates the baseline and is unsupported.
    """

    if not recorded:
        if not set(tables or ()) - {LEDGER_TABLE}:
            return CheckResult(CheckState.ABSENT)
        return CheckResult(CheckState.UNSUPPORTED, missing=chain.floor_ids)

    known = set(recorded)
    ids = chain.ids
    if known & set(chain.baseline_ids):
        unknown = tuple(sorted(known - set(ids)))
        pending = tuple(i for i in ids if i not in known)
        current = next((i for i in reversed(ids) if i in known), None)
        if unknown:
            return CheckResult(
                CheckState.AHEAD, pending=pending, unknown=unknown, current=current
            )
        if pending:
            return CheckResult(CheckState.BEHIND, pending=pending, current=current)
        return CheckResult(CheckState.COMPATIBLE, current=current)

    floor = set(chain.floor_ids)
    if floor and floor <= known:
        unknown = tuple(sorted(known - floor - set(ids)))
        pending = tuple(m.id for m in chain.migrations if m.id not in known)
        state = CheckState.AHEAD if unknown else CheckState.BEHIND
        return CheckResult(
            state, pending=pending, unknown=unknown, adopting=chain.baseline_ids
        )

    return CheckResult(
        CheckState.UNSUPPORTED,
        missing=tuple(i for i in chain.floor_ids if i not in known),
    )


def check(chain: Chain[Any], connection: MigrationConnection[Any]) -> CheckResult:
    """Read the database's state without changing it.

    Issues no DDL and writes nothing, so a startup may call it on a connection
    it opened read-only. It runs no migration, so the connection need not be
    the kind the chain's migrations take: it reads only tables and the ledger.
    """

    with connection.transaction():
        tables = connection.table_names()
        recorded = connection.recorded_ids() if LEDGER_TABLE in tables else None
    return classify(chain, tables=tables, recorded=recorded)


def migrate(chain: Chain[C], connection: MigrationConnection[C]) -> MigrateReport:
    """Bring the database to the chain's head, or refuse it applying nothing.

    An ahead database is refused, since applying pending migrations over
    unknown ones deepens a divergence only the image that wrote them can
    judge; an unsupported one is refused, since no chain step reaches it.
    """

    # The state is read, and a floor database adopted, in one transaction, so
    # the floor records adoption replaces are the ones the check found.
    with connection.transaction():
        tables = connection.table_names()
        recorded = connection.recorded_ids() if LEDGER_TABLE in tables else None
        result = classify(chain, tables=tables, recorded=recorded)
        if result.state in (CheckState.AHEAD, CheckState.UNSUPPORTED):
            raise MigrationRefused(result, service=chain.service, command=chain.command)
        if result.state is CheckState.ABSENT:
            connection.create_ledger()
        if result.adoption_pending:
            connection.forget(chain.floor_ids)
            connection.record(chain.baseline_ids)
    if result.state is CheckState.COMPATIBLE:
        return MigrateReport(adopted=False, applied=())

    if result.adoption_pending:
        logger.info(
            "%s: adopted the supported baseline (%s)",
            chain.service,
            ", ".join(chain.baseline_ids),
        )

    pending = set(chain.ids if result.state is CheckState.ABSENT else result.pending)
    applied: list[str] = []
    for migration in (*chain.baselines, *chain.migrations):
        if migration.id not in pending:
            continue
        try:
            with connection.transaction():
                migration.apply(connection.native)
                connection.record((migration.id,))
        except Exception as exc:
            raise MigrationFailed(
                service=chain.service, migration_id=migration.id, cause=exc
            ) from exc
        applied.append(migration.id)
        logger.info("%s: applied migration %s", chain.service, migration.id)
    return MigrateReport(adopted=result.adoption_pending, applied=tuple(applied))
