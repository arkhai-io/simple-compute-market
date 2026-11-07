"""The host an executor runs a job against, as the host authority resolved it.

An executor receives this value from the lookup made immediately before
execution, never the host registry's record, so what it can see of a host is
exactly its identity, pool, and connection.
"""

from __future__ import annotations

from dataclasses import dataclass

from .connection import ConnectionEnvelope


@dataclass(frozen=True)
class ExecutionHost:
    host_id: str
    pool_id: str | None
    connection: ConnectionEnvelope

    def __post_init__(self) -> None:
        if not self.host_id or not self.host_id.strip():
            raise ValueError("an execution host needs a host_id")


__all__ = ["ExecutionHost"]
