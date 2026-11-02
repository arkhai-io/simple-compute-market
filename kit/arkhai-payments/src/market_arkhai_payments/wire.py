"""Serialization of required nullable fields in the payments wire contract."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, SerializationInfo, SerializerFunctionWrapHandler, model_serializer


class WireModel(BaseModel):
    """Keep required nulls even when optional absent fields are omitted."""

    @model_serializer(mode="wrap")
    def _wire(self, handler: SerializerFunctionWrapHandler, info: SerializationInfo) -> Any:
        value = handler(self)
        # A null cap means unbounded. Dropping it changes both the terms and hash.
        if isinstance(value, dict):
            for name, field in type(self).model_fields.items():
                if field.is_required() and getattr(self, name) is None:
                    key = (field.serialization_alias or name) if info.by_alias else name
                    value[key] = None
        return value
