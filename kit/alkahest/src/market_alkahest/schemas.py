"""Alkahest-owned wire/helper schemas.

These models are intentionally local to the Alkahest kit. Higher-level
packages can re-export or structurally validate them, but the kit should
not import market-core just to materialize settlement data.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, field_serializer, field_validator


class ERC20TokenMetadata(BaseModel):
    """Resolved ERC-20 token metadata used by token helpers/listings."""

    symbol: str
    name: str | None = None
    contract_address: str
    decimals: int
    chain_id: int | None = None


def _parse_uint256_str(v: Any, field_name: str) -> int | None:
    if v is None:
        return None
    if isinstance(v, bool):
        raise ValueError(f"{field_name}: expected non-negative decimal, got bool")
    if isinstance(v, int):
        if v < 0:
            raise ValueError(f"{field_name}: must be non-negative, got {v}")
        return v
    if isinstance(v, str):
        s = v.strip()
        if not s:
            return None
        if not s.isdigit():
            raise ValueError(
                f"{field_name}: must be a non-negative decimal-digit string, "
                f"got {v!r}"
            )
        return int(s)
    raise ValueError(
        f"{field_name}: must be int, decimal string, or None; got "
        f"{type(v).__name__}"
    )


def _serialize_uint256_str(v: int | None) -> str | None:
    return None if v is None else str(v)


class EscrowTerms(BaseModel):
    """One on-chain Alkahest escrow obligation in flat form."""

    maker: Literal["buyer", "seller"] = Field(
        description="Which side calls doObligation for this escrow.",
    )
    chain_name: str | None = Field(
        default=None,
        description="Alkahest chain identifier for this escrow.",
    )
    escrow_contract: str = Field(
        description="Address of the on-chain escrow obligation contract.",
    )
    obligation_data: dict[str, Any] = Field(
        description="Literal ObligationData struct for the escrow contract.",
    )
    expiration_unix: int = Field(
        gt=0,
        description="Absolute UTC unix-time at which the escrow expires.",
    )


PER_UNIT_SECONDS: dict[str, int] = {
    "hour": 3600,
}


class RateValue(BaseModel):
    """One rate-bearing obligation-data slot."""

    field: str = Field(description="Obligation-data field path the rate populates.")
    per: str = Field(default="hour", description="Unit the rate scales by.")
    value: int = Field(description="Rate amount in base units.")

    @field_validator("value", mode="before")
    @classmethod
    def _parse_value(cls, v: Any) -> int:
        parsed = _parse_uint256_str(v, "value")
        if parsed is None:
            raise ValueError("RateValue.value must not be null")
        return parsed

    @field_serializer("value")
    def _serialize_value(self, v: int) -> str:
        return _serialize_uint256_str(v) or "0"


def compute_rate_total(rate: RateValue, duration_seconds: int) -> int:
    """Multiply a rate by the negotiated duration."""
    divisor = PER_UNIT_SECONDS.get(rate.per)
    if divisor is None:
        raise ValueError(f"unknown rate.per unit: {rate.per!r}")
    return rate.value * duration_seconds // divisor


def accepted_demands(accepted_or_proposal: Any) -> list[dict[str, Any]]:
    """Return arbiter demands advertised/negotiated for this escrow shape."""
    if isinstance(accepted_or_proposal, dict):
        raw = accepted_or_proposal.get("demands")
    else:
        raw = getattr(accepted_or_proposal, "demands", None)
    if not isinstance(raw, list):
        return []
    out: list[dict[str, Any]] = []
    for item in raw:
        if isinstance(item, dict):
            out.append(dict(item))
        else:
            dumped = item.model_dump() if hasattr(item, "model_dump") else None
            if isinstance(dumped, dict):
                out.append(dumped)
    return out


def _rates_of(entry: Any) -> list[Any]:
    if isinstance(entry, dict):
        out = entry.get("rates")
        return out if isinstance(out, list) else []
    return list(getattr(entry, "rates", []) or [])


def _literal_fields_of(entry: Any) -> dict[str, Any]:
    if isinstance(entry, dict):
        out = entry.get("literal_fields")
        return out if isinstance(out, dict) else {}
    return dict(getattr(entry, "literal_fields", {}) or {})


def primary_rate_value(accepted_or_proposal: Any) -> int | None:
    """Return the first advertised/negotiated rate value, if present."""
    rates = _rates_of(accepted_or_proposal)
    if not rates:
        return None
    first = rates[0]
    if isinstance(first, dict):
        value = first.get("value")
    else:
        value = getattr(first, "value", None)
    if isinstance(value, str) and value.strip().isdigit():
        return int(value.strip())
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    return None


def accepted_token_address(accepted_or_proposal: Any) -> str | None:
    """Return the token literal from ERC-20/ERC-1155-style escrow entries."""
    literals = _literal_fields_of(accepted_or_proposal)
    val = literals.get("token") if isinstance(literals, dict) else None
    return val if isinstance(val, str) and val else None


def accepted_recipient_address(accepted_or_proposal: Any) -> str | None:
    """Return the escrow demand recipient from an accepted/proposed escrow."""
    for demand in accepted_demands(accepted_or_proposal):
        data = demand.get("demand_data")
        if isinstance(data, dict):
            val = data.get("recipient")
            if isinstance(val, str) and val:
                return val
    literals = _literal_fields_of(accepted_or_proposal)
    val = literals.get("recipient") if isinstance(literals, dict) else None
    return val if isinstance(val, str) and val else None


__all__ = [
    "ERC20TokenMetadata",
    "EscrowTerms",
    "PER_UNIT_SECONDS",
    "RateValue",
    "accepted_demands",
    "accepted_recipient_address",
    "accepted_token_address",
    "compute_rate_total",
    "primary_rate_value",
]
