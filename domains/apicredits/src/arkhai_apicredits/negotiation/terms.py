"""API-credits provision-term construction.

``ProvisionTerms{kind: "api_credits.v1", version: 1, payload: ...}``
is fixed at round 0. ``key`` is the buyer's key disposition:
``{"mode": "new"}`` or ``{"mode": "existing", "key_id": "ak_…"}``.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)

API_CREDITS_PROVISION_KIND = "api_credits.v1"
API_CREDITS_PROVISION_VERSION = 1


class ApiCreditsKeyIntent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mode: Literal["new", "existing"] = "new"
    key_id: str | None = None

    @model_validator(mode="after")
    def _validate_existing_key(self) -> "ApiCreditsKeyIntent":
        if self.mode == "existing" and not self.key_id:
            raise ValueError("key.key_id is required when key.mode is existing")
        return self


class ApiCreditsProvisionPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    quantity: int = Field(ge=1)
    key: ApiCreditsKeyIntent = Field(default_factory=ApiCreditsKeyIntent)


class ApiCreditsProvisionTerms(BaseModel):
    """API-credit provision envelope with domain-owned payload validation."""

    model_config = ConfigDict(extra="forbid")

    kind: Literal["api_credits.v1"] = API_CREDITS_PROVISION_KIND
    version: Literal[1] = API_CREDITS_PROVISION_VERSION
    payload: dict[str, Any]

    @field_validator("payload")
    @classmethod
    def _validate_payload(cls, value: dict[str, Any]) -> dict[str, Any]:
        return ApiCreditsProvisionPayload.model_validate(value).model_dump(
            exclude_none=True,
        )

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


def make_api_credits_provision_terms(
    *,
    quantity: int,
    key_mode: str = "new",
    key_id: str | None = None,
) -> ApiCreditsProvisionTerms:
    key: dict[str, Any] = {"mode": key_mode}
    if key_id is not None:
        key["key_id"] = key_id
    return ApiCreditsProvisionTerms(
        payload={"quantity": int(quantity), "key": key},
    )


# ---------------------------------------------------------------------------
# api_credits.v1 payload accessors
# ---------------------------------------------------------------------------
# Wire-received provision terms arrive as the core opaque carrier
# (market_core.schemas.ProvisionTerms) or a plain dict; these are the
# domain's interpretation of the api_credits.v1 payload, accepting any
# carrier with a ``payload`` attribute or key.


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
