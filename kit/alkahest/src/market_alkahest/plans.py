"""Alkahest as a settlement-mechanism codec behind the plan envelope.

The negotiated outcome travels as a settlement plan: per obligation,
lifecycle universals as typed fields plus a ``{mechanism, params}``
envelope. This module is the ``alkahest.v1`` side of that contract —
it converts between the envelope and this kit's typed ``EscrowTerms``
shape and materializes whole plans from negotiated proposals.

The plan models here are structural mirrors of the ``market_core``
carriers (same field names, same wire serialization, same legacy
coercions): the kit must not import market-core, and the determinism
contract is structural — both sides derive byte-identical payloads.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, field_serializer, field_validator, model_validator

from .schemas import (
    EscrowTerms,
    _parse_uint256_str,
    _serialize_uint256_str,
)

ALKAHEST_MECHANISM = "alkahest.v1"
"""Mechanism tag this codec owns. ``params`` carries
``{chain_name?, escrow_contract, obligation_data}`` — exactly
``EscrowTerms`` minus ``maker``/``expiration_unix``, which are
lifecycle universals on the obligation itself."""


class SettlementObligation(BaseModel):
    """Structural mirror of ``market_core.schemas.SettlementObligation``."""

    payer: Literal["buyer", "seller"] = Field(
        description="Which side funds/materializes this obligation.",
    )
    claimant: Literal["buyer", "seller"] = Field(
        description="Which side collects when the condition set passes.",
    )
    amount: int | None = Field(
        default=None,
        description="Obligation value in base units; string on the wire.",
    )
    asset: str | None = Field(
        default=None,
        description="Mechanism-scoped asset identifier.",
    )
    expiration_unix: int = Field(
        gt=0,
        description="Absolute UTC unix-time collect-vs-reclaim boundary.",
    )
    conditions: list[dict[str, Any]] = Field(
        default_factory=list,
        description="Declared condition descriptors gating collection.",
    )
    mechanism: str = Field(
        description="Settlement mechanism codec identifier.",
    )
    params: dict[str, Any] = Field(
        default_factory=dict,
        description="Mechanism-specific materialization params.",
    )

    @field_validator("amount", mode="before")
    @classmethod
    def _parse_obligation_amount(cls, v: Any) -> int | None:
        return _parse_uint256_str(v, "amount")

    @field_serializer("amount")
    def _serialize_obligation_amount(self, v: int | None) -> str | None:
        return _serialize_uint256_str(v)

    @model_validator(mode="before")
    @classmethod
    def _coerce_legacy_escrow_terms(cls, value: Any) -> Any:
        """LEGACY: flat ``EscrowTerms`` dicts normalize into the envelope.

        Mirrors the market-core coercion byte-for-byte; see there for
        the contract. Removed with the client-wheel wire bump.
        """
        if not isinstance(value, dict):
            return value
        if "mechanism" in value or "escrow_contract" not in value:
            return value

        data = dict(value)
        maker = data.pop("maker", "buyer")
        obligation_data = data.pop("obligation_data", {}) or {}
        params: dict[str, Any] = {
            "escrow_contract": data.pop("escrow_contract"),
            "obligation_data": obligation_data,
        }
        if data.get("chain_name") is not None:
            params["chain_name"] = data.pop("chain_name")
        else:
            data.pop("chain_name", None)

        amount = obligation_data.get("amount")
        return {
            "payer": maker,
            "claimant": "seller" if maker == "buyer" else "buyer",
            "amount": amount if isinstance(amount, (int, str)) else None,
            "asset": obligation_data.get("token"),
            "expiration_unix": data.pop("expiration_unix", None),
            "mechanism": ALKAHEST_MECHANISM,
            "params": params,
            **data,
        }


class SettlementPlan(BaseModel):
    """Structural mirror of ``market_core.schemas.SettlementPlan``."""

    obligations: list[SettlementObligation] = Field(
        description="Every obligation the deal materializes.",
    )
    service_terms: dict[str, Any] = Field(
        default_factory=dict,
        description="Off-chain servicing duties. Opaque envelope.",
    )

    @model_validator(mode="before")
    @classmethod
    def _coerce_legacy_terms_list(cls, value: Any) -> Any:
        """LEGACY: bare ``list[EscrowTerms]`` wraps into a plan."""
        if isinstance(value, list):
            return {"obligations": value}
        return value


def escrow_terms_to_settlement_obligation(
    terms: EscrowTerms | dict[str, Any],
) -> SettlementObligation:
    """Wrap this kit's typed alkahest shape in the mechanism envelope."""
    payload = terms.model_dump() if isinstance(terms, EscrowTerms) else terms
    return SettlementObligation.model_validate(payload)


def settlement_obligation_to_escrow_terms(
    obligation: SettlementObligation | dict[str, Any],
) -> EscrowTerms:
    """Unwrap an ``alkahest.v1`` obligation into the typed alkahest shape.

    Raises ``ValueError`` for any other mechanism — dispatching across
    mechanisms is the caller's job; this codec only interprets its own
    params.
    """
    ob = (
        obligation
        if isinstance(obligation, SettlementObligation)
        else SettlementObligation.model_validate(obligation)
    )
    if ob.mechanism != ALKAHEST_MECHANISM:
        raise ValueError(
            f"not an {ALKAHEST_MECHANISM} obligation: {ob.mechanism!r}"
        )
    return EscrowTerms(
        maker=ob.payer,
        chain_name=ob.params.get("chain_name"),
        escrow_contract=ob.params["escrow_contract"],
        obligation_data=ob.params.get("obligation_data") or {},
        expiration_unix=ob.expiration_unix,
    )


def escrow_terms_from_settlement_plan(
    plan: SettlementPlan | dict[str, Any] | list[Any],
) -> list[EscrowTerms]:
    """All of a plan's alkahest obligations as typed ``EscrowTerms``.

    Raises ``ValueError`` if the plan carries an obligation under a
    mechanism this codec doesn't own — a caller that reaches for the
    alkahest view of a mixed-mechanism plan has a dispatching bug, and
    silently dropping obligations would under-materialize the deal.
    """
    plan_model = (
        plan if isinstance(plan, SettlementPlan)
        else SettlementPlan.model_validate(plan)
    )
    return [
        settlement_obligation_to_escrow_terms(ob)
        for ob in plan_model.obligations
    ]


def materialize_settlement_plan_from_proposal(
    *,
    proposal: Any,
    seller_wallet_address: str | None,
    agreed_amount: int | None,
    duration_seconds: int,
    addr_config_path: str | None = None,
) -> SettlementPlan:
    """Derive the settlement plan from a negotiated escrow proposal.

    The deterministic counterpart of
    ``materialize_escrow_terms_from_proposal`` — same inputs, same
    derivation, with each materialized escrow wrapped in the
    ``alkahest.v1`` envelope. Single-obligation plans today; the shape
    already admits N obligations and mixed mechanisms.
    """
    from .alkahest import materialize_escrow_terms_from_proposal

    terms = materialize_escrow_terms_from_proposal(
        proposal=proposal,
        seller_wallet_address=seller_wallet_address,
        agreed_amount=agreed_amount,
        duration_seconds=duration_seconds,
        addr_config_path=addr_config_path,
    )
    return SettlementPlan(
        obligations=[escrow_terms_to_settlement_obligation(t) for t in terms],
    )


def settlement_plan_payload_from_proposal(
    *,
    proposal: Any,
    seller_wallet_address: str | None,
    agreed_amount: int | None,
    duration_seconds: int,
    addr_config_path: str | None = None,
) -> dict[str, Any]:
    """JSON-serializable variant of the plan materialization."""
    return materialize_settlement_plan_from_proposal(
        proposal=proposal,
        seller_wallet_address=seller_wallet_address,
        agreed_amount=agreed_amount,
        duration_seconds=duration_seconds,
        addr_config_path=addr_config_path,
    ).model_dump()
