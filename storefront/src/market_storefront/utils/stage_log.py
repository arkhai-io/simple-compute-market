"""Compatibility wrapper for structured storefront stage logging."""

from __future__ import annotations

from typing import Any

from market_core.storefront.stage_log import (
    set_stage_event_db_path,
    stage_event as _core_stage_event,
)


def _configure_db_path() -> None:
    try:
        from market_storefront.utils.config import settings

        set_stage_event_db_path(settings.db_path)
    except Exception:
        set_stage_event_db_path(None)


def stage_event(stage: str, event: str, **fields: Any) -> None:
    """Emit a structured stage-boundary log entry."""
    _configure_db_path()
    _core_stage_event(stage, event, **fields)


__all__ = ["set_stage_event_db_path", "stage_event"]
