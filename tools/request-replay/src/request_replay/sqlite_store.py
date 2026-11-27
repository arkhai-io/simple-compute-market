"""The store over a standard-library ``sqlite3`` database."""

from __future__ import annotations

import sqlite3
from collections.abc import Callable, Iterator
from contextlib import closing, contextmanager

from request_replay.ddl import DEFAULT_TABLE, table_name
from request_replay.policy import Resolution
from request_replay.store import COLUMNS, Entry, Outcome, Row, row_from_columns, same_request

_COLUMNS = ", ".join(COLUMNS)


class SqliteReplayStore:
    """Rows in one table of a SQLite database, a connection per step.

    ``connect`` opens a connection to the database, outside any transaction; the
    store closes it after the step. Every step is one ``BEGIN IMMEDIATE``
    transaction, which takes the write lock before reading, so a step's read and
    its write see no other writer between them. The table must exist: the store
    creates nothing (:mod:`request_replay.ddl`).
    """

    def __init__(self, connect: Callable[[], sqlite3.Connection], *, table: str = DEFAULT_TABLE) -> None:
        self._connect = connect
        self._table = table_name(table)

    def claim(
        self, entry: Entry, *, now: int, expires_at: int, lease_until: int, owner: str
    ) -> Row | None:
        with self._transaction() as connection:
            connection.execute(
                f"DELETE FROM {self._table} "
                "WHERE principal = ? AND request_id = ? AND expires_at <= ?",
                (entry.principal, entry.request_id, now),
            )
            existing = self._row(connection, entry.principal, entry.request_id)
            if existing is not None:
                return existing
            connection.execute(
                f"INSERT INTO {self._table} (principal, request_id, request_hash, resolution, "
                "origin, expires_at, lease_until, lease_owner) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    entry.principal,
                    entry.request_id,
                    entry.request_hash,
                    entry.resolution.value,
                    entry.origin,
                    expires_at,
                    lease_until,
                    owner,
                ),
            )
            return None

    def reclaim(
        self, entry: Entry, *, now: int, expires_at: int, lease_until: int, owner: str
    ) -> bool:
        with self._transaction() as connection:
            cursor = connection.execute(
                f"UPDATE {self._table} SET lease_until = ?, lease_owner = ?, "
                "expires_at = CASE WHEN expires_at < ? THEN ? ELSE expires_at END "
                "WHERE principal = ? AND request_id = ? AND request_hash = ? "
                "AND resolution = ? AND outcome_status IS NULL AND expires_at > ? "
                "AND (lease_until IS NULL OR lease_until <= ?)",
                (
                    lease_until,
                    owner,
                    expires_at,
                    expires_at,
                    entry.principal,
                    entry.request_id,
                    entry.request_hash,
                    Resolution.RERUN.value,
                    now,
                    now,
                ),
            )
            return cursor.rowcount == 1

    def renew(self, principal: str, request_id: str, owner: str, *, now: int, lease_until: int) -> bool:
        with self._transaction() as connection:
            cursor = connection.execute(
                f"UPDATE {self._table} SET lease_until = ?, "
                "expires_at = CASE WHEN expires_at < ? THEN ? ELSE expires_at END "
                "WHERE principal = ? AND request_id = ? AND lease_owner = ? "
                "AND outcome_status IS NULL AND lease_until > ?",
                (lease_until, lease_until, lease_until, principal, request_id, owner, now),
            )
            return cursor.rowcount == 1

    def conclude(self, entry: Entry, *, now: int) -> Row | None:
        with self._transaction() as connection:
            connection.execute(
                f"UPDATE {self._table} SET lease_until = NULL "
                "WHERE principal = ? AND request_id = ? AND request_hash = ? AND origin = ? "
                "AND resolution = ? AND outcome_status IS NULL AND lease_until <= ? "
                "AND expires_at > ?",
                (
                    entry.principal,
                    entry.request_id,
                    entry.request_hash,
                    entry.origin,
                    Resolution.RECORDED.value,
                    now,
                    now,
                ),
            )
            row = self._row(connection, entry.principal, entry.request_id)
        return row if row is not None and row.expires_at > now and same_request(row, entry) else None

    def record(self, principal: str, request_id: str, owner: str, outcome: Outcome) -> bool:
        with self._transaction() as connection:
            cursor = connection.execute(
                f"UPDATE {self._table} SET outcome_status = ?, outcome_headers = ?, "
                "outcome_body = ?, lease_until = NULL, lease_owner = NULL "
                "WHERE principal = ? AND request_id = ? AND lease_owner = ?",
                (
                    outcome.status,
                    outcome.headers_json(),
                    outcome.body,
                    principal,
                    request_id,
                    owner,
                ),
            )
            return cursor.rowcount == 1

    def release(self, principal: str, request_id: str, owner: str) -> bool:
        with self._transaction() as connection:
            cursor = connection.execute(
                f"UPDATE {self._table} SET lease_until = NULL, lease_owner = NULL "
                "WHERE principal = ? AND request_id = ? AND lease_owner = ?",
                (principal, request_id, owner),
            )
            return cursor.rowcount == 1

    def get(self, principal: str, request_id: str, *, now: int) -> Row | None:
        with self._transaction() as connection:
            row = self._row(connection, principal, request_id)
        return row if row is not None and row.expires_at > now else None

    def sweep_batch(self, *, now: int, limit: int) -> int:
        with self._transaction() as connection:
            cursor = connection.execute(
                f"DELETE FROM {self._table} WHERE rowid IN ("
                f"SELECT rowid FROM {self._table} WHERE expires_at <= ? "
                "ORDER BY expires_at LIMIT ?)",
                (now, limit),
            )
            return cursor.rowcount

    @contextmanager
    def _transaction(self) -> Iterator[sqlite3.Connection]:
        # Statements rather than the driver's commit(), which does nothing under
        # autocommit=True; the driver opens no transaction of its own while one
        # it did not open is in progress.
        with closing(self._connect()) as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                yield connection
            except BaseException:
                # SQLite has already rolled back after some errors; rolling back
                # again would raise over the error that matters.
                if connection.in_transaction:
                    connection.execute("ROLLBACK")
                raise
            connection.execute("COMMIT")

    def _row(self, connection: sqlite3.Connection, principal: str, request_id: str) -> Row | None:
        found = connection.execute(
            f"SELECT {_COLUMNS} FROM {self._table} WHERE principal = ? AND request_id = ?",
            (principal, request_id),
        ).fetchone()
        return None if found is None else row_from_columns(found)

