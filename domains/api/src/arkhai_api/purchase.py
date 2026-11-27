"""The prepaid purchase shape: a quantity of credits onto a new key or an existing one."""

from __future__ import annotations

from functools import cache
from typing import Any, Literal, Self

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictInt,
    create_model,
    field_validator,
    model_validator,
)

PROVISION_TERMS_VERSION = 1


class KeyIntent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mode: Literal["new", "existing"] = "new"
    key_id: str | None = None

    @model_validator(mode="after")
    def _validate_key_shape(self) -> Self:
        # Exactly two shapes are admitted: a new key names no identifier, an
        # existing key names a non-blank one.
        if self.key_id is not None and not self.key_id.strip():
            raise ValueError("key.key_id must be non-blank")
        if self.mode == "existing" and self.key_id is None:
            raise ValueError("key.key_id is required when key.mode is existing")
        if self.mode == "new" and self.key_id is not None:
            raise ValueError("key.key_id is not admitted when key.mode is new")
        return self


class PurchasePayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    quantity: StrictInt = Field(ge=1)
    key: KeyIntent = Field(default_factory=KeyIntent)


class ProvisionTerms(BaseModel):
    """The provision envelope; ``provision_terms_model`` binds ``kind`` to one domain's literal."""

    model_config = ConfigDict(extra="forbid")

    kind: str
    version: Literal[1] = PROVISION_TERMS_VERSION
    payload: dict[str, Any]

    @field_validator("payload")
    @classmethod
    def _validate_payload(cls, value: dict[str, Any]) -> dict[str, Any]:
        return PurchasePayload.model_validate(value).model_dump(exclude_none=True)

    @classmethod
    def purchase(cls, *, quantity: int, key_mode: str = "new", key_id: str | None = None) -> Self:
        key: dict[str, Any] = {"mode": key_mode}
        if key_id is not None:
            key["key_id"] = key_id
        return cls(payload={"quantity": quantity, "key": key})

    @property
    def quantity(self) -> int | None:
        raw = self.payload.get("quantity")
        return int(raw) if raw is not None else None

    @property
    def key_mode(self) -> str:
        key = self.payload.get("key")
        mode = key.get("mode") if isinstance(key, dict) else None
        return mode if isinstance(mode, str) else "new"

    @property
    def key_id(self) -> str | None:
        key = self.payload.get("key")
        raw = key.get("key_id") if isinstance(key, dict) else None
        return str(raw) if raw else None


@cache
def provision_terms_model(kind: str) -> type[ProvisionTerms]:
    """The ``ProvisionTerms`` class bound to one kind literal; one class per kind."""

    return create_model(
        "ProvisionTerms",
        __base__=ProvisionTerms,
        kind=(Literal[kind], kind),  # type: ignore[valid-type]
    )


# Received terms are the core carrier or a plain dict; both expose ``payload``.


def provision_payload(terms: Any) -> dict[str, Any]:
    if isinstance(terms, dict):
        raw = terms.get("payload")
    else:
        raw = getattr(terms, "payload", None)
    return raw if isinstance(raw, dict) else {}


def provision_quantity(terms: Any) -> int | None:
    raw = provision_payload(terms).get("quantity")
    try:
        return int(raw) if raw is not None else None
    except (TypeError, ValueError):
        return None


def provision_key_mode(terms: Any) -> str:
    key = provision_payload(terms).get("key")
    mode = key.get("mode") if isinstance(key, dict) else None
    return mode if isinstance(mode, str) and mode else "new"


def provision_key_id(terms: Any) -> str | None:
    key = provision_payload(terms).get("key")
    raw = key.get("key_id") if isinstance(key, dict) else None
    return str(raw) if raw else None
