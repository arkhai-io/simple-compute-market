"""Replay refusal, exact-retry resolution and in-flight leasing over an opaque request key.

A caller that has authenticated a request hands :class:`RequestReplay` an
:class:`Entry` -- an opaque principal and request ID, a hash of what the request
asks, its :class:`Resolution`, and its origin -- and dispatches, answers, or
refuses it as the :data:`Admission` says. Rows live in a durable store the caller
binds to its own database: :class:`SqliteReplayStore` over ``sqlite3``, or
``request_replay.sqlalchemy_store.SqlAlchemyReplayStore`` with the ``sqlalchemy``
extra. No store creates its table; :mod:`request_replay.ddl` publishes the
statements for the caller's migrations. The README is the interface.
"""

from request_replay.ddl import DEFAULT_TABLE, DIALECTS, statements
from request_replay.guard import (
    DEFAULT_SWEEP_BATCH,
    Admission,
    Answered,
    Attempt,
    ChangedReuse,
    Dispatch,
    Expired,
    InProgress,
    OutcomeUnknown,
    RequestReplay,
)
from request_replay.policy import Policy, Resolution
from request_replay.renewal import Renewal, renewing
from request_replay.sqlite_store import SqliteReplayStore
from request_replay.store import Entry, Outcome, ReplayStore, Row, StoreUnavailable

__all__ = [
    "DEFAULT_SWEEP_BATCH",
    "DEFAULT_TABLE",
    "DIALECTS",
    "Admission",
    "Answered",
    "Attempt",
    "ChangedReuse",
    "Dispatch",
    "Entry",
    "Expired",
    "InProgress",
    "Outcome",
    "OutcomeUnknown",
    "Policy",
    "Renewal",
    "ReplayStore",
    "RequestReplay",
    "Resolution",
    "Row",
    "SqliteReplayStore",
    "StoreUnavailable",
    "renewing",
    "statements",
]
