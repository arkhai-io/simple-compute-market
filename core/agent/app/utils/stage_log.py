"""Structured stage-boundary logging.

Emits JSON log entries at each marketplace stage transition, documenting
what a hypothetical functional stage would return. Each entry has:

    stage       — discovery | negotiation | settlement | provision
    event       — specific transition within the stage
    deal fields — IDs, prices, resources, attestations as applicable

These logs serve three purposes:
1. Observability: grep for stage=settlement to see all escrow creations
2. Documentation: the logged fields ARE the stage's functional output
3. Rewrite guide: when stages become real functions, these become returns

Usage:
    from core.agent.app.utils.stage_log import stage_event
    stage_event("discovery", "order_published", order_id=oid, offer=spec)
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any

_logger = logging.getLogger("stage")


def stage_event(stage: str, event: str, **fields: Any) -> None:
    """Emit a structured stage-boundary log entry.

    All values are JSON-serialized. Non-serializable values (Pydantic
    models, enums) should be converted before passing.
    """
    entry = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "stage": stage,
        "event": event,
        **fields,
    }
    _logger.info(json.dumps(entry, default=str))
