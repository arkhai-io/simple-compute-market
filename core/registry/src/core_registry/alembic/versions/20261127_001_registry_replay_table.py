"""The admission core's replay table, the seller evidence's names, and the 0.4.0
replay table dropped.

The registry admits its signed requests through the admission core, whose replay
table (``authenticated_request_replay``) this revision creates from the core's
own statements. The 0.4.0 table, ``publisher_replay_reservations``, held a
reservation and response per version 2 request, none of which a version 3
request can retry, so it is dropped with its rows. The seller evidence columns
take the names a listing read serves them under, ``publication`` and
``updates``, keeping every row.

Dropping a table leaves its pages in a SQLite file, so on SQLite the revision
records in the database header that a compaction is owed, in its own
transaction; ``registry-migrate`` runs ``VACUUM`` after the upgrade and clears
the mark, and a run whose ``VACUUM`` failed leaves it for the next run.

Revision ID: 20261127_001_registry_replay_table
Revises: 20261106_001_registry_retained_publications
"""

from alembic import op
from market_authenticated_requests import replay_table_statements

revision = "20261127_001_registry_replay_table"
down_revision = "20261106_001_registry_retained_publications"
branch_labels = None
depends_on = None


def upgrade() -> None:
    dialect = op.get_bind().dialect.name
    for statement in replay_table_statements(dialect):
        op.execute(statement)
    op.execute("ALTER TABLE listings RENAME COLUMN publisher_publication TO publication")
    op.execute("ALTER TABLE listings RENAME COLUMN publisher_updates TO updates")
    op.execute("DROP TABLE publisher_replay_reservations")
    if dialect == "sqlite":
        op.execute("PRAGMA user_version = 1")


def downgrade() -> None:
    # The dropped reservations are not rebuilt, and an image before this one
    # reads the evidence under its old names and signs version 2 alone.
    raise NotImplementedError(
        "the replay table is not downgraded; restore the backup taken before the upgrade instead"
    )
