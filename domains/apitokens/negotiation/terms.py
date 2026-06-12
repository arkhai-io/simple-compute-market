"""API-tokens provision-term construction.

``ProvisionTerms{kind: "api_tokens.v1", payload: {quantity, key}}`` —
fixed at round 0 exactly like VM duration. ``key`` is the buyer's key
disposition: ``{"mode": "new"}`` or
``{"mode": "existing", "key_id": "ak_…"}``.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

API_TOKENS_PROVISION_KIND = "api_tokens.v1"


class ApiTokensProvisionTerms(BaseModel):
    """API-tokens provision terms matching the api_tokens.v1 wire shape."""

    kind: str = Field(default=API_TOKENS_PROVISION_KIND)
    payload: dict[str, Any] = Field(default_factory=dict)

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


def make_api_tokens_provision_terms(
    *,
    quantity: int,
    key_mode: str = "new",
    key_id: str | None = None,
) -> ApiTokensProvisionTerms:
    key: dict[str, Any] = {"mode": key_mode}
    if key_id is not None:
        key["key_id"] = key_id
    return ApiTokensProvisionTerms(
        payload={"quantity": int(quantity), "key": key},
    )


# ---------------------------------------------------------------------------
# api_tokens.v1 payload accessors
# ---------------------------------------------------------------------------
# Wire-received provision terms arrive as the core opaque carrier
# (market_core.schemas.ProvisionTerms) or a plain dict; these are the
# domain's interpretation of the api_tokens.v1 payload, accepting any
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
