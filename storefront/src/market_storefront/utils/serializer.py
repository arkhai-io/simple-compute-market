"""JSON serialization utilities for handling non-serializable objects."""

import types
from datetime import datetime
from enum import Enum
from typing import Any


def json_serializer(obj: Any) -> Any:
    """JSON encoder that handles common non-serializable types for json.dumps(default=...).
    
    Handles:
    - datetime objects → ISO format strings
    - Enum objects → their .value
    - mappingproxy objects → dict (from Python internals like Enum.__members__)
    - Pydantic models → dict via model_dump()
    - Other objects with __dict__ → dict
    
    Note: json.dumps() automatically recurses through nested structures, so this handler
    only needs to convert individual non-serializable objects.
    
    Example:
        import json
        from market_storefront.utils.serializer import json_serializer
        
        data = {"enum": MyEnum.VALUE, "date": datetime.now()}
        json_str = json.dumps(data, default=json_serializer)
    """
    if isinstance(obj, datetime):
        return obj.isoformat()
    if isinstance(obj, Enum):
        return obj.value
    if isinstance(obj, types.MappingProxyType):
        # Convert immutable mappingproxy to regular dict
        return dict(obj)
    if hasattr(obj, 'model_dump'):
        # Pydantic models - use mode='json' to handle nested Enums automatically
        try:
            return obj.model_dump(mode='json')
        except (TypeError, ValueError):
            # Fallback if mode='json' not supported
            return obj.model_dump()
    if hasattr(obj, '__dict__'):
        return obj.__dict__
    raise TypeError(f"Object of type {type(obj)} is not JSON serializable")


# ---------------------------------------------------------------------------
# Context serialisation for pipeline experience recording
# ---------------------------------------------------------------------------

import json as _json
import logging as _logging

_logger = _logging.getLogger(__name__)
_MAX_CONTEXT_JSON_CHARS = 100_000
_MAX_PAST_EXPERIENCES = 5


def serialize_context_for_storage(decision_context) -> str:
    """Serialise a DecisionContext for SQLite storage, trimming heavy fields."""
    ctx_dict = decision_context.model_dump(mode="json")

    past_exps = ctx_dict.get("past_experiences") or []
    trimmed = [
        {
            "decision_id": e.get("decision_id"),
            "event_id": e.get("event_id"),
            "event_type": e.get("event_type"),
            "action_type": e.get("action_type"),
            "policy_used": e.get("policy_used"),
            "timestamp": e.get("timestamp"),
        }
        for e in past_exps[:_MAX_PAST_EXPERIENCES]
    ]
    ctx_dict["past_experiences"] = trimmed

    context_json = _json.dumps(ctx_dict, default=json_serializer)
    if len(context_json) > _MAX_CONTEXT_JSON_CHARS:
        _logger.warning(
            "[PIPELINE] Context JSON too large (%d chars); storing truncated metadata.",
            len(context_json),
        )
        context_json = _json.dumps({
            "truncated": True,
            "original_length": len(context_json),
            "message": "Context JSON exceeded max size and was trimmed for storage.",
        })
    return context_json
