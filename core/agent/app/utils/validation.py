"""Domain-agnostic validation helpers."""

from __future__ import annotations

from typing import Any


def validate_model(model_cls: Any, payload: dict[str, Any]) -> Any:
    """Validate a dict payload against a model class exposing model_validate()."""
    return model_cls.model_validate(payload)
