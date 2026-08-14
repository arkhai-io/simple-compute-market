"""Typed settlement publication clauses and their CLI-edge compiler."""

from __future__ import annotations

import re
import shlex
from collections.abc import Mapping
from decimal import Decimal, InvalidOperation
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .configuration import (
    SettlementConfig,
    SettlementConfigurationError,
    SettlementConfigurationRegistry,
    SettlementRole,
)

_DECIMAL_RATE = re.compile(r"(?:0|[1-9][0-9]*)(?:\.[0-9]+)?")
_UNIT = re.compile(r"[a-z][a-z0-9_-]*")


def _validate_public_json(value: Any, *, path: str) -> Any:
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        raise ValueError(f"{path} must not contain binary floating-point values")
    if isinstance(value, Mapping):
        result: dict[str, Any] = {}
        for key, item in value.items():
            if not isinstance(key, str) or not key:
                raise ValueError(f"{path} keys must be non-empty strings")
            result[key] = _validate_public_json(item, path=f"{path}.{key}")
        return result
    if isinstance(value, (list, tuple)):
        return [
            _validate_public_json(item, path=f"{path}[{index}]")
            for index, item in enumerate(value)
        ]
    raise ValueError(f"{path} must contain only JSON public values")


class SettlementPublicationClause(BaseModel):
    """One validated, role-neutral settlement option publication request."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    mechanism: str = Field(min_length=1)
    asset: str = Field(min_length=1)
    rate: str | None = None
    per: str | None = None
    public: dict[str, Any] = Field(default_factory=dict)
    mechanism_input: dict[str, Any] = Field(
        description="Mechanism-owned public publication input.",
    )

    @field_validator("mechanism", "asset")
    @classmethod
    def require_trimmed_identity(cls, value: str) -> str:
        if value != value.strip():
            raise ValueError("publication identities must be trimmed")
        return value

    @field_validator("rate")
    @classmethod
    def validate_decimal_rate(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if not isinstance(value, str) or not _DECIMAL_RATE.fullmatch(value):
            raise ValueError("rate must be positive decimal text without an exponent")
        try:
            parsed = Decimal(value)
        except InvalidOperation as exc:
            raise ValueError("rate must be valid decimal text") from exc
        if not parsed.is_finite() or parsed <= 0:
            raise ValueError("rate must be positive decimal text")
        return value

    @field_validator("per")
    @classmethod
    def validate_rate_unit(cls, value: str | None) -> str | None:
        if value is not None and not _UNIT.fullmatch(value):
            raise ValueError("per must be a canonical lowercase unit")
        return value

    @field_validator("public", "mechanism_input")
    @classmethod
    def validate_public_mappings(
        cls, value: dict[str, Any], info: Any
    ) -> dict[str, Any]:
        return _validate_public_json(value, path=info.field_name)

    @model_validator(mode="before")
    @classmethod
    def reject_binary_rate(cls, value: Any) -> Any:
        if isinstance(value, Mapping) and isinstance(value.get("rate"), float):
            raise ValueError("rate must not be a binary floating-point value")
        return value

    @model_validator(mode="after")
    def require_complete_rate(self) -> SettlementPublicationClause:
        if (self.rate is None) != (self.per is None):
            raise ValueError("rate and per must be supplied together")
        return self


def _parse_cli_clause(source: str) -> dict[str, Any]:
    try:
        tokens = shlex.split(source)
    except ValueError as exc:
        raise SettlementConfigurationError(
            f"invalid settlement clause quoting: {exc}"
        ) from exc
    if not tokens:
        raise SettlementConfigurationError("settlement publication clause is empty")

    scalar: dict[str, str] = {}
    public: dict[str, str] = {}
    mechanism_fields: dict[str, str] = {}
    seen: set[str] = set()
    for token in tokens:
        key, separator, raw_value = token.partition("=")
        if not separator or not key or not raw_value:
            raise SettlementConfigurationError(
                f"settlement publication term {token!r} must be name=value"
            )
        if key in seen:
            raise SettlementConfigurationError(
                f"duplicate settlement publication field {key!r}"
            )
        seen.add(key)
        if key in {"mechanism", "asset", "rate"}:
            scalar[key] = raw_value
        elif key.startswith("public.") and len(key) > len("public."):
            public[key.removeprefix("public.")] = raw_value
        else:
            mechanism_fields[key] = raw_value

    rate = scalar.pop("rate", None)
    if rate is not None:
        rate_text, separator, per = rate.partition("/")
        if not separator or not rate_text or not per or "/" in per:
            raise SettlementConfigurationError("rate must use <decimal>/<unit>")
        scalar["rate"] = rate_text
        scalar["per"] = per
    return {
        **scalar,
        "public": public,
        "_mechanism_fields": mechanism_fields,
    }


def compile_settlement_publication_clause(
    value: str | Mapping[str, Any] | SettlementPublicationClause,
    *,
    registry: SettlementConfigurationRegistry,
    config: SettlementConfig,
    role: SettlementRole,
) -> SettlementPublicationClause:
    """Compile one CLI or structured clause and validate its mechanism input."""

    if isinstance(value, str):
        raw = _parse_cli_clause(value)
        mechanism_fields = raw.pop("_mechanism_fields")
    elif isinstance(value, SettlementPublicationClause):
        raw = value.model_dump(mode="python")
        mechanism_fields = dict(raw.get("mechanism_input") or {})
    elif isinstance(value, Mapping):
        raw = dict(value)
        mechanism_fields = dict(raw.get("mechanism_input") or {})
    else:
        raise SettlementConfigurationError(
            "settlement publication clause must be DSL text or a structured mapping"
        )

    requested_mechanism = raw.get("mechanism")
    if not isinstance(requested_mechanism, str) or not requested_mechanism:
        raise SettlementConfigurationError("settlement publication requires mechanism")
    mechanism = registry.canonical_mechanism_id(requested_mechanism, role=role)
    registration = registry.registration(mechanism)

    if isinstance(value, str):
        prefix = f"{registration.config_key}."
        unqualified = sorted(
            key for key in mechanism_fields if not key.startswith(prefix)
        )
        if unqualified:
            raise SettlementConfigurationError(
                f"unknown settlement publication field {unqualified[0]!r}"
            )
        mechanism_fields = {
            key.removeprefix(prefix): item for key, item in mechanism_fields.items()
        }

    raw["mechanism"] = mechanism
    raw["mechanism_input"] = mechanism_fields
    try:
        clause = SettlementPublicationClause.model_validate(raw)
        validated_input = registry.validate_publication_input(
            mechanism,
            clause.mechanism_input,
            config,
            role=role,
        )
        return clause.model_copy(
            update={"mechanism_input": validated_input.model_dump(mode="json")}
        )
    except (ValueError, TypeError) as exc:
        if isinstance(exc, SettlementConfigurationError):
            raise
        raise SettlementConfigurationError(
            f"invalid settlement publication clause: {exc}"
        ) from exc


__all__ = [
    "SettlementPublicationClause",
    "compile_settlement_publication_clause",
]
