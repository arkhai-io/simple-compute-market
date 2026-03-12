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
        from core.agent.app.utils.serializer import json_serializer
        
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
