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


class EscrowDemand(BaseModel):
    """One arbiter demand paired with an escrow obligation."""

    chain_name: str | None = Field(
        default=None,
        description="Optional chain identifier for multi-chain demand lists.",
    )
    arbiter: str = Field(description="Deployed arbiter contract address.")
    demand_data: dict[str, Any] = Field(
        default_factory=dict,
        description="Codec-specific arbiter demand data.",
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


class EscrowProposal(BaseModel):
    """Alkahest escrow proposal used as a concrete negotiation message."""

    chain_name: str
    escrow_address: str
    fields: dict[str, Any] = Field(default_factory=dict)
    literal_fields: dict[str, Any] | None = None
    rates: list[RateValue] | None = None
    demands: list[EscrowDemand] | None = None
    expiration_unix: int = Field(gt=0)


class AcceptedEscrow(BaseModel):
    """One escrow shape a listing advertises as acceptable."""

    chain_name: str
    escrow_address: str
    literal_fields: dict[str, Any] = Field(default_factory=dict)
    rates: list[RateValue] = Field(default_factory=list)


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


def _rates_as_input(rates: list[Any] | None) -> list[Any] | None:
    if rates is None:
        return None
    out: list[Any] = []
    for rate in rates:
        if isinstance(rate, dict):
            out.append(dict(rate))
        elif hasattr(rate, "model_dump"):
            out.append(rate.model_dump())
        else:
            out.append(rate)
    return out


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


def match_accepted_escrow(
    accepted_escrows: list[Any] | None,
    proposal: EscrowProposal,
) -> Any | None:
    """Return the accepted escrow matching a proposal's chain and contract."""
    if not accepted_escrows:
        return None
    for entry in accepted_escrows:
        chain_name = (
            entry.get("chain_name") if isinstance(entry, dict)
            else getattr(entry, "chain_name", None)
        )
        escrow_address = (
            entry.get("escrow_address") if isinstance(entry, dict)
            else getattr(entry, "escrow_address", None)
        )
        if chain_name != proposal.chain_name:
            continue
        if str(escrow_address or "").lower() != proposal.escrow_address.lower():
            continue
        return entry
    return None


def normalize_proposal_against_accepted_escrows(
    *,
    proposal: EscrowProposal | None,
    accepted_escrows: list[Any] | None,
) -> EscrowProposal | None:
    """Merge advertised literals/rates into a matching Alkahest proposal.

    Accepted-set membership and literal equality are policy decisions. This
    helper only performs mechanical normalization for a proposal that matches
    one advertised ``(chain_name, escrow_address)`` tuple.
    """
    if proposal is None:
        return None
    matched = match_accepted_escrow(accepted_escrows, proposal)
    if matched is None:
        return proposal

    literal_fields = _literal_fields_of(matched)
    literal_fields.update(dict(proposal.literal_fields or {}))
    rates = proposal.rates
    if rates is None:
        rates = _rates_of(matched)
    rates = _rates_as_input(rates)
    return EscrowProposal(
        chain_name=proposal.chain_name,
        escrow_address=proposal.escrow_address,
        fields=dict(proposal.fields or {}),
        literal_fields=literal_fields,
        rates=rates,
        demands=proposal.demands,
        expiration_unix=proposal.expiration_unix,
    )


__all__ = [
    "ERC20TokenMetadata",
    "EscrowDemand",
    "EscrowProposal",
    "EscrowTerms",
    "AcceptedEscrow",
    "PER_UNIT_SECONDS",
    "RateValue",
    "accepted_demands",
    "accepted_recipient_address",
    "accepted_token_address",
    "compute_rate_total",
    "match_accepted_escrow",
    "normalize_proposal_against_accepted_escrows",
    "primary_rate_value",
]
