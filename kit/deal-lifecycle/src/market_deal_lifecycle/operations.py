"""Stable, domain-separated operation keys and an injected atomic replay guard."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Protocol

from market_deal_lifecycle_contracts.models import LifecycleCommand
from market_identity import canonical_json, frame_fields


class OperationStore(Protocol):
    async def check_and_record(self, negotiation_id: str, operation_key: str, digest: str) -> bool:
        """Atomically persist before I/O; true for new or identical, false for changed content."""
        ...


@dataclass(frozen=True)
class OperationKeys:
    negotiation_id: str
    operation_key: str
    store: OperationStore | None = field(default=None, compare=False, repr=False)

    def _derive(self, family: str, subject: str) -> str:
        return hashlib.sha256(frame_fields((
            "arkhai.deal-lifecycle.operation.v1", self.negotiation_id,
            self.operation_key, family, subject,
        ))).hexdigest()

    def part_event(self, part: str, kind: str) -> str:
        return self._derive("part_event", hashlib.sha256(frame_fields((part, kind))).hexdigest())

    def filing(self) -> str:
        return self._derive("filing", "")

    def append(self, case_ref: str) -> str:
        return self._derive("append", case_ref)


async def remember_command(command: LifecycleCommand, store: OperationStore) -> OperationKeys | None:
    digest = hashlib.sha256(canonical_json(command)).hexdigest()
    if not await store.check_and_record(command.negotiation_id, command.operation_key, digest):
        return None
    return OperationKeys(command.negotiation_id, command.operation_key, store)
