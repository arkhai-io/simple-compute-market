"""One migration engine for every in-house stateful service.

A service declares a :class:`Chain` -- its baselines, its later migrations, and
the required :class:`Floor` naming the release it is supported from and the IDs
that release's chain recorded -- and runs :func:`migrate` from its migration
command and :func:`check` at startup, refusing any result but compatible with
:func:`refusal_message`. A database the floor release ran on is adopted
whatever earlier releases recorded in it; one older than the floor is refused,
to be upgraded through the floor release first. ``market_schema_migrations.sqlite``
adapts a ``sqlite3`` connection; ``market_schema_migrations.sqlalchemy_adapter``,
installed with the ``sqlalchemy`` extra, adapts a SQLAlchemy one.
"""

from market_schema_migrations.engine import (
    LEDGER_TABLE,
    Chain,
    Floor,
    MigrateReport,
    Migration,
    MigrationConnection,
    MigrationFailed,
    MigrationRefused,
    check,
    classify,
    migrate,
)
from market_schema_migrations.result import (
    CheckResult,
    CheckState,
    UnsupportedCause,
    describe,
    refusal_message,
)
from market_schema_migrations.snapshot import schema_snapshot
from market_schema_migrations.sqlite import (
    SqliteMigrationConnection,
    check_sqlite_file,
    connect_read_only,
)

__all__ = [
    "LEDGER_TABLE",
    "Chain",
    "CheckResult",
    "CheckState",
    "Floor",
    "MigrateReport",
    "Migration",
    "MigrationConnection",
    "MigrationFailed",
    "MigrationRefused",
    "SqliteMigrationConnection",
    "UnsupportedCause",
    "check",
    "check_sqlite_file",
    "classify",
    "connect_read_only",
    "describe",
    "migrate",
    "refusal_message",
    "schema_snapshot",
]
