"""Immutable payment operations for caller-owned write-before-call journals."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from typing import Any

from market_deal_lifecycle.operations import OperationKeys

from .canonical import jcs_bytes


@dataclass(frozen=True)
class PaymentOperation:
    transaction: str
    account: str
    part: str
    kind: str
    request_id: str
    event_json: str

    @classmethod
    def create(cls, *, transaction: str, account: str, part: str,
               event: dict[str, Any], keys: OperationKeys) -> PaymentOperation:
        return cls(transaction, account, part, str(event["kind"]),
                   keys.part_event(part, str(event["kind"])), jcs_bytes(event).decode())

    @property
    def event(self) -> dict[str, Any]:
        return dict(json.loads(self.event_json))

    @property
    def digest(self) -> str:
        return hashlib.sha256(jcs_bytes({
            "version": 1, "transaction": self.transaction, "account": self.account,
            "part": self.part, "request_id": self.request_id, "event": self.event,
        })).hexdigest()


def operations_digest(operations: tuple[PaymentOperation, ...]) -> str:
    return hashlib.sha256(jcs_bytes([operation.digest for operation in operations])).hexdigest()
