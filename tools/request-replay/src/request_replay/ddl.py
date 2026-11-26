"""The replay table's statements, published as data for a consumer's migrations.

No store issues DDL: whoever composes a store creates its table through its own
migration chain, from these statements, so the schema a database holds is the one
its chain recorded. Instants are integer seconds; a recorded response's headers
are a JSON array of name and value pairs, and its body the bytes sent.
"""

from __future__ import annotations

import re

DEFAULT_TABLE = "request_replay"
DIALECTS = ("sqlite", "postgresql")

_IDENTIFIER = re.compile(r"^[a-z_][a-z0-9_]{0,62}$")

_TYPES = {
    "sqlite": {"integer": "INTEGER", "bytes": "BLOB"},
    "postgresql": {"integer": "BIGINT", "bytes": "BYTEA"},
}


def table_name(table: str) -> str:
    """``table`` if it is a plain lower-case SQL identifier; refuse anything else."""

    if not _IDENTIFIER.fullmatch(table):
        raise ValueError(f"{table!r} is not a plain lower-case SQL identifier")
    return table


def expiry_index_name(table: str) -> str:
    return f"ix_{table_name(table)}_expires_at"


def statements(dialect: str, *, table: str = DEFAULT_TABLE) -> tuple[str, ...]:
    """The table and its expiry index, in order, for ``dialect``.

    The index on ``expires_at`` is what lets a sweep find expired rows in
    bounded batches without reading the table.
    """

    if dialect not in _TYPES:
        raise ValueError(f"no replay table statements for dialect {dialect!r}; known: {DIALECTS}")
    types = _TYPES[dialect]
    name = table_name(table)
    return (
        f"CREATE TABLE {name} ("
        "principal VARCHAR(512) NOT NULL, "
        "request_id VARCHAR(128) NOT NULL, "
        "request_hash VARCHAR(128) NOT NULL, "
        "resolution VARCHAR(16) NOT NULL, "
        f"origin {types['integer']} NOT NULL, "
        f"expires_at {types['integer']} NOT NULL, "
        f"lease_until {types['integer']}, "
        "lease_owner VARCHAR(64), "
        "outcome_status INTEGER, "
        "outcome_headers TEXT, "
        f"outcome_body {types['bytes']}, "
        "PRIMARY KEY (principal, request_id))",
        f"CREATE INDEX {expiry_index_name(name)} ON {name} (expires_at)",
    )
