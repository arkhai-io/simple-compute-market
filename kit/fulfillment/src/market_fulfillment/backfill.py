"""Domain-neutral carriers for legacy fulfillment migration compilers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from .envelopes import VersionedEnvelope


@dataclass(frozen=True)
class LegacyFulfillmentBackfillInput:
    """Validated historical executor coordinates supplied to a domain compiler."""

    capacity_reservation_id: str
    executor_host: str
    executor_target: str
    create_job_id: str | None
    teardown_job_id: str | None
    playbook_path: str
    provider_extra_vars: dict[str, Any]


@dataclass(frozen=True)
class LegacyFulfillmentBackfillDraft:
    """VM-owned provider state ready for generic aggregate persistence."""

    provider_metadata: dict[str, Any]
    prepared_teardown_operation: VersionedEnvelope
    teardown_provider_metadata: dict[str, Any] | None


class LegacyFulfillmentBackfillCompiler(Protocol):
    def __call__(
        self, source: LegacyFulfillmentBackfillInput
    ) -> LegacyFulfillmentBackfillDraft: ...
