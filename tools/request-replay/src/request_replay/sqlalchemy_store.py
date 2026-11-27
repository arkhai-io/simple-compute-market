"""The store over a SQLAlchemy engine.

Only a consumer holding SQLAlchemy imports this module, through the package's
``sqlalchemy`` extra; nothing else in the package imports it.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import (
    BigInteger,
    Column,
    Engine,
    Integer,
    LargeBinary,
    MetaData,
    String,
    Table,
    Text,
    case,
    delete,
    insert,
    inspect,
    select,
    text,
    tuple_,
    update,
)
from sqlalchemy.engine import Connection
from sqlalchemy.exc import IntegrityError

from request_replay.ddl import DEFAULT_TABLE, table_name
from request_replay.policy import Resolution
from request_replay.store import COLUMNS, Entry, Outcome, Row, row_from_columns

# A key whose row a concurrent sweep deletes, or that expires, between the failed
# insert and the read is claimed again; past this many such races the database is
# not settling.
_CLAIM_ATTEMPTS = 3


def replay_table(table: str = DEFAULT_TABLE, metadata: MetaData | None = None) -> Table:
    """The table as SQLAlchemy reads and writes it.

    It describes the table :mod:`request_replay.ddl` creates and is never used
    to create it.
    """

    return Table(
        table_name(table),
        metadata if metadata is not None else MetaData(),
        Column("principal", String(512), primary_key=True),
        Column("request_id", String(128), primary_key=True),
        Column("request_hash", String(128), nullable=False),
        Column("resolution", String(16), nullable=False),
        Column("origin", BigInteger, nullable=False),
        Column("expires_at", BigInteger, nullable=False),
        Column("lease_until", BigInteger),
        Column("lease_owner", String(64)),
        Column("outcome_status", Integer),
        Column("outcome_headers", Text),
        Column("outcome_body", LargeBinary),
    )


class SqlAlchemyReplayStore:
    """Rows in one table of the database ``engine`` names, a transaction per step.

    A claim inserts and takes a unique-key conflict as the key being held, so it
    relies on no locking read; every other step is one conditional statement. The
    table must exist: the store creates nothing (:mod:`request_replay.ddl`).
    """

    def __init__(self, engine: Engine, *, table: str = DEFAULT_TABLE) -> None:
        self._engine = engine
        self._table = replay_table(table)
        self._columns = [self._table.c[name] for name in COLUMNS]

    def claim(
        self, entry: Entry, *, now: int, expires_at: int, lease_until: int, owner: str
    ) -> Row | None:
        for _ in range(_CLAIM_ATTEMPTS):
            try:
                self._insert(entry, now=now, expires_at=expires_at, lease_until=lease_until, owner=owner)
                return None
            except IntegrityError:
                existing = self.get(entry.principal, entry.request_id, now=now)
                if existing is not None:
                    return existing
        raise RuntimeError(
            f"the replay key of request {entry.request_id} kept changing while it was claimed"
        )

    def _insert(self, entry: Entry, *, now: int, expires_at: int, lease_until: int, owner: str) -> None:
        """Replace an expired row under the key and insert the reservation, or raise
        ``IntegrityError`` when a live row holds the key."""

        t = self._table
        key = (t.c.principal == entry.principal) & (t.c.request_id == entry.request_id)
        with self._engine.begin() as connection:
            connection.execute(delete(t).where(key & (t.c.expires_at <= now)))
            connection.execute(
                insert(t).values(
                    principal=entry.principal,
                    request_id=entry.request_id,
                    request_hash=entry.request_hash,
                    resolution=entry.resolution.value,
                    origin=entry.origin,
                    expires_at=expires_at,
                    lease_until=lease_until,
                    lease_owner=owner,
                )
            )

    def reclaim(
        self, entry: Entry, *, now: int, expires_at: int, lease_until: int, owner: str
    ) -> bool:
        t = self._table
        statement = (
            update(t)
            .where(
                (t.c.principal == entry.principal)
                & (t.c.request_id == entry.request_id)
                & (t.c.request_hash == entry.request_hash)
                & (t.c.resolution == Resolution.RERUN.value)
                & t.c.outcome_status.is_(None)
                & (t.c.expires_at > now)
                & (t.c.lease_until.is_(None) | (t.c.lease_until <= now))
            )
            .values(lease_until=lease_until, lease_owner=owner, expires_at=self._raised(expires_at))
        )
        return self._changed_one(statement)

    def renew(self, principal: str, request_id: str, owner: str, *, now: int, lease_until: int) -> bool:
        t = self._table
        statement = (
            update(t)
            .where(
                (t.c.principal == principal)
                & (t.c.request_id == request_id)
                & (t.c.lease_owner == owner)
                & t.c.outcome_status.is_(None)
                & (t.c.lease_until > now)
            )
            .values(lease_until=lease_until, expires_at=self._raised(lease_until))
        )
        return self._changed_one(statement)

    def conclude(self, principal: str, request_id: str, *, now: int) -> Row | None:
        t = self._table
        key = (t.c.principal == principal) & (t.c.request_id == request_id)
        statement = (
            update(t)
            .where(
                key
                & (t.c.resolution == Resolution.RECORDED.value)
                & t.c.outcome_status.is_(None)
                & (t.c.lease_until <= now)
                & (t.c.expires_at > now)
            )
            .values(lease_until=None)
        )
        # Under SQLite the update takes the database's write lock whether or not it
        # matches, and the read after it is in the same transaction, behind it.
        with self._engine.begin() as connection:
            connection.execute(statement)
            row = self._row(connection, principal, request_id)
        return row if row is not None and row.expires_at > now else None

    def record(self, principal: str, request_id: str, owner: str, outcome: Outcome) -> bool:
        t = self._table
        statement = (
            update(t)
            .where((t.c.principal == principal) & (t.c.request_id == request_id) & (t.c.lease_owner == owner))
            .values(
                outcome_status=outcome.status,
                outcome_headers=outcome.headers_json(),
                outcome_body=outcome.body,
                lease_until=None,
                lease_owner=None,
            )
        )
        return self._changed_one(statement)

    def release(self, principal: str, request_id: str, owner: str) -> bool:
        t = self._table
        statement = (
            update(t)
            .where((t.c.principal == principal) & (t.c.request_id == request_id) & (t.c.lease_owner == owner))
            .values(lease_until=None, lease_owner=None)
        )
        return self._changed_one(statement)

    def get(self, principal: str, request_id: str, *, now: int) -> Row | None:
        with self._engine.begin() as connection:
            row = self._row(connection, principal, request_id)
        return row if row is not None and row.expires_at > now else None

    def sweep_batch(self, *, now: int, limit: int) -> int:
        t = self._table
        batch = (
            select(t.c.principal, t.c.request_id)
            .where(t.c.expires_at <= now)
            .order_by(t.c.expires_at)
            .limit(limit)
        )
        # The outer condition holds the delete to rows still expired when it runs,
        # whatever a concurrent claim replaced since the batch was selected.
        statement = delete(t).where(
            tuple_(t.c.principal, t.c.request_id).in_(batch) & (t.c.expires_at <= now)
        )
        with self._engine.begin() as connection:
            return int(connection.execute(statement).rowcount)

    def _raised(self, value: int) -> Any:
        expires_at = self._table.c.expires_at
        return case((expires_at < value, value), else_=expires_at)

    def _changed_one(self, statement: Any) -> bool:
        with self._engine.begin() as connection:
            return bool(connection.execute(statement).rowcount == 1)

    def _row(self, connection: Connection, principal: str, request_id: str) -> Row | None:
        t = self._table
        found = connection.execute(
            select(*self._columns).where((t.c.principal == principal) & (t.c.request_id == request_id))
        ).first()
        return None if found is None else row_from_columns(tuple(found))


def table_snapshot(engine: Engine, *, exclude: frozenset[str] | set[str] = frozenset()) -> dict[str, list[tuple[Any, ...]]]:
    """Every table's rows but those excluded, each table's rows in a fixed order.

    Two snapshots are equal exactly when every included table holds the same
    rows, so a test compares a database's state before and after a step.
    """

    with engine.connect() as connection:
        names = sorted(set(inspect(connection).get_table_names()) - set(exclude))
        return {
            name: sorted(
                (tuple(row) for row in connection.execute(text(f'SELECT * FROM "{name}"'))),
                key=repr,
            )
            for name in names
        }
