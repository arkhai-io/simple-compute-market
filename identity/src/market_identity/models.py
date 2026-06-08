"""Scheme-tagged identity models."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field, field_validator


class Identity(BaseModel):
    """A scheme-tagged identity.

    ``scheme`` names a verifier registered in
    :mod:`market_identity.registry` (e.g. ``"eip191"``).
    ``identifier`` is the scheme-specific principal. For ``eip191``,
    this is the lowercase 0x hex wallet address; other schemes may carry
    DIDs, OIDC ``sub`` claims, or any other scheme-defined identifier.
    """

    scheme: str = Field(
        description=(
            "Name of the identity scheme. Must match a verifier registered "
            "via :func:`market_identity.registry.register_identity_scheme`."
        ),
    )
    identifier: str = Field(
        description=(
            "Scheme-specific principal. For ``eip191`` this is the lowercase "
            "0x-prefixed hex wallet address; for other schemes the value is "
            "scheme-defined."
        ),
    )

    @field_validator("identifier", mode="after")
    @classmethod
    def _normalize_identifier(cls, value: str, info: Any) -> str:
        scheme = info.data.get("scheme") if hasattr(info, "data") else None
        if scheme == "eip191":
            return value.lower()
        return value
