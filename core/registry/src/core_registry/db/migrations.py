"""The registry's migrations: Alembic behind the contract every service keeps.

The registry's chain is its Alembic script directory, packaged with it
(``core_registry/alembic``), and begins at one baseline revision reproducing
the schema the v0.3.0 release builds. Its state is reported as every other
service reports its own (``market_schema_migrations.CheckResult``) and refused
in the same words (``refusal_message``), naming ``registry-migrate``:

- no database file, or no table but ``alembic_version`` and no revision:
  *absent*;
- tables but no revision: *unsupported*, a database no supported release built;
- the script head: *compatible*;
- an earlier revision of the script: *behind*, with the revisions after it
  pending;
- ``018_listing_resource_column``, where the v0.3.0 release leaves a database:
  *behind*, with the baseline revision to be adopted and the revisions after
  it pending;
- a revision of the chain the release squashed into its baseline: *unsupported*,
  naming the revisions it lacks;
- any other revision: *ahead*, written by an image this one does not know.

Alembic upgrades only from a revision its script holds, and the floor revision
is not among them, so adoption rewrites the floor revision to the baseline in
one transaction, without running the baseline, before upgrading. The check opens the database
read-only and creates no file; only the migration command writes.
See openspec/specs/deployment-state/spec.md#requirement-service-owned-migration-history.
"""

from __future__ import annotations

import logging
import sqlite3
from collections.abc import Collection, Sequence
from dataclasses import dataclass
from pathlib import Path

from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from market_schema_migrations import (
    CheckResult,
    CheckState,
    MigrateReport,
    MigrationFailed,
    MigrationRefused,
    connect_read_only,
    refusal_message,
)
from sqlalchemy import create_engine, inspect, pool, text
from sqlalchemy.engine import Connection, make_url

logger = logging.getLogger(__name__)

SERVICE = "the registry"
COMMAND = "registry-migrate"
SCRIPT_LOCATION = "core_registry:alembic"
VERSION_TABLE = "alembic_version"

FLOOR_REVISION = "018_listing_resource_column"
"""The revision a database the v0.3.0 release built or migrated records."""

PRE_FLOOR_REVISIONS: tuple[str, ...] = (
    "001_initial",
    "002_add_owner_field",
    "003_add_market_orders_table",
    "004_standardize_agent_ids_and_metadata",
    "005_simplify_to_erc8004_canonical_ids",
    "006_rename_duration_to_duration_hours",
    "007_add_oracle_address",
    "008_rename_orders_to_listings",
    "009_listing_max_duration_seconds",
    "010_drop_listing_attestations",
    "011_listing_accepted_escrows",
    "012_pluggable_identity_scheme",
    "013_api_key_scope",
    "014_agent_to_publisher",
    "015_listing_settlement_options",
    "016_marketplace_principal_auth",
    "017_publisher_replay_leases",
)
"""The revisions before the floor, oldest first, which the baseline replaced.

A database at one of them predates the supported baseline: it is refused as
unsupported, naming what it lacks, rather than as ahead, whose remedy -- the
image that wrote it -- would not serve it."""


class IncompatibleDatabase(RuntimeError):
    """The registry will not start on its database; the message says why."""

    def __init__(self, result: CheckResult) -> None:
        super().__init__(refusal_message(result, service=SERVICE, command=COMMAND))
        self.result = result


def alembic_config(database_url: str) -> Config:
    """The Alembic configuration of the packaged script directory."""

    config = Config()
    config.set_main_option("script_location", SCRIPT_LOCATION)
    config.set_main_option("sqlalchemy.url", database_url)
    return config


def script_revisions() -> tuple[str, ...]:
    """The script's revisions in the order they apply, base first.

    The script is one line of revisions, which every revision a later change
    adds continues; a branch would leave no single head to compare with.
    """

    script = ScriptDirectory.from_config(alembic_config("sqlite://"))
    heads = script.get_heads()
    if len(heads) != 1:
        raise RuntimeError(
            f"{SERVICE}'s migration script has {len(heads)} heads; it must have one"
        )
    return tuple(reversed([s.revision for s in script.walk_revisions()]))


def classify(
    tables: Collection[str],
    revisions: Sequence[str] | None,
    known: Sequence[str],
) -> CheckResult:
    """The state of a database holding ``tables`` and recording ``revisions``.

    ``revisions`` is ``None`` when the database has no ``alembic_version``
    table; ``known`` is the script's revisions, base first.
    """

    others = set(tables) - {VERSION_TABLE}
    if not revisions:
        return CheckResult(CheckState.UNSUPPORTED if others else CheckState.ABSENT)
    retired = (FLOOR_REVISION, *PRE_FLOOR_REVISIONS)
    unknown = tuple(r for r in revisions if r not in known and r not in retired)
    if unknown:
        return CheckResult(CheckState.AHEAD, unknown=unknown)
    if len(revisions) > 1:
        return CheckResult(CheckState.UNSUPPORTED)
    revision = revisions[0]
    if revision in PRE_FLOOR_REVISIONS:
        after = PRE_FLOOR_REVISIONS[PRE_FLOOR_REVISIONS.index(revision) + 1 :]
        return CheckResult(
            CheckState.UNSUPPORTED,
            missing=(*after, FLOOR_REVISION),
            current=revision,
        )
    if revision == FLOOR_REVISION:
        # The floor stands for the baseline, which adoption records unrun.
        return CheckResult(
            CheckState.BEHIND,
            pending=tuple(known[1:]),
            adopting=(known[0],),
            current=revision,
        )
    position = list(known).index(revision)
    if position == len(known) - 1:
        return CheckResult(CheckState.COMPATIBLE, current=revision)
    return CheckResult(
        CheckState.BEHIND, pending=tuple(known[position + 1 :]), current=revision
    )


def _sqlite_file(database_url: str) -> Path | None:
    """The file a SQLite URL names, or ``None`` for any other database."""

    url = make_url(database_url)
    if url.get_backend_name() != "sqlite":
        return None
    if not url.database or url.database == ":memory:":
        return None
    return Path(url.database)


def _read_sqlite(path: Path) -> tuple[set[str], list[str] | None]:
    connection = connect_read_only(path)
    try:
        tables = {
            str(row[0])
            for row in connection.execute(
                "SELECT name FROM sqlite_master "
                "WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
            )
        }
        if VERSION_TABLE not in tables:
            return tables, None
        revisions = [
            str(row[0])
            for row in connection.execute(f"SELECT version_num FROM {VERSION_TABLE}")
        ]
        return tables, revisions
    finally:
        connection.close()


def _read_engine(database_url: str) -> tuple[set[str], list[str] | None]:
    engine = create_engine(database_url, poolclass=pool.NullPool)
    try:
        with engine.connect() as connection:
            tables = set(inspect(connection).get_table_names())
            if VERSION_TABLE not in tables:
                return tables, None
            rows = connection.execute(text(f"SELECT version_num FROM {VERSION_TABLE}"))
            return tables, [str(row[0]) for row in rows]
    finally:
        engine.dispose()


def check_database(database_url: str) -> CheckResult:
    """The registry's database's state, read without changing anything.

    A SQLite file is opened read-only, so a missing one is *absent* and stays
    missing; any other database is only read.
    """

    path = _sqlite_file(database_url)
    if path is not None:
        if not path.is_file():
            return CheckResult(CheckState.ABSENT)
        try:
            tables, revisions = _read_sqlite(path)
        except sqlite3.DatabaseError as exc:
            raise RuntimeError(f"{SERVICE} cannot read its database {path}: {exc}") from exc
    else:
        tables, revisions = _read_engine(database_url)
    return classify(tables, revisions, script_revisions())


def require_compatible_database(database_url: str) -> CheckResult:
    """Check the database at startup, refusing any result but compatible."""

    result = check_database(database_url)
    if not result.compatible:
        raise IncompatibleDatabase(result)
    return result


@dataclass(frozen=True)
class _Plan:
    adopt: bool
    pending: tuple[str, ...]


def _plan(result: CheckResult, known: Sequence[str]) -> _Plan:
    if result.state in (CheckState.AHEAD, CheckState.UNSUPPORTED):
        raise MigrationRefused(result, service=SERVICE, command=COMMAND)
    if result.state is CheckState.ABSENT:
        return _Plan(adopt=False, pending=tuple(known))
    return _Plan(adopt=result.adoption_pending, pending=result.pending)


def _adopt(connection: Connection, baseline: str) -> None:
    """Record the baseline in place of the floor revision, running nothing."""

    with connection.begin():
        adopted = connection.execute(
            text(
                f"UPDATE {VERSION_TABLE} SET version_num = :baseline "
                "WHERE version_num = :floor"
            ),
            {"baseline": baseline, "floor": FLOOR_REVISION},
        ).rowcount
        if adopted != 1:
            # Another writer changed the revision between the check and here;
            # the transaction rolls back, so nothing is changed.
            raise MigrationFailed(
                service=SERVICE,
                migration_id=baseline,
                cause=RuntimeError(
                    f"the database records a revision other than {FLOOR_REVISION}; "
                    "nothing was changed"
                ),
            )
    logger.info("Adopted the v0.3.0 database at %s", baseline)


def migrate_database(database_url: str) -> MigrateReport:
    """Adopt a v0.3.0 database if it is one, then upgrade to the script head.

    Refuses an ahead or unsupported database, changing nothing. Rerun on a
    database at the head, it changes nothing.
    """

    known = script_revisions()
    plan = _plan(check_database(database_url), known)
    engine = create_engine(database_url, poolclass=pool.NullPool)
    try:
        with engine.connect() as connection:
            if plan.adopt:
                _adopt(connection, known[0])
            config = alembic_config(database_url)
            config.attributes["connection"] = connection
            # One revision at a time, so a failure names the revision that
            # failed and the ones before it stay applied.
            for revision in plan.pending:
                try:
                    command.upgrade(config, revision)
                    connection.commit()
                except Exception as exc:
                    raise MigrationFailed(
                        service=SERVICE, migration_id=revision, cause=exc
                    ) from exc
    finally:
        engine.dispose()
    return MigrateReport(adopted=plan.adopt, applied=plan.pending)
