"""Alkahest as a settlement-mechanism codec behind the plan envelope.

The negotiated outcome travels as a settlement plan: per obligation,
lifecycle universals as typed fields plus a ``{mechanism, params}``
envelope. This module is the ``alkahest.v1`` side of that contract —
it converts between the envelope and this kit's typed ``EscrowTerms``
shape and materializes whole plans from negotiated proposals.

The plan models here are structural mirrors of the ``market_core``
carriers (same field names, same wire serialization): the kit must not
import market-core, and the determinism contract is structural — both sides
derive byte-identical payloads.
"""

from __future__ import annotations
from collections.abc import Mapping
from copy import deepcopy

from typing import Any, Literal

from pydantic import (
    BaseModel,
    Field,
    field_serializer,
    field_validator,
)

from .alkahest import materialize_escrow_terms_from_proposal
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


class SettlementPlan(BaseModel):
    """Structural mirror of ``market_core.schemas.SettlementPlan``."""

    obligations: list[SettlementObligation] = Field(
        description="Every obligation the deal materializes.",
    )
    service_terms: dict[str, Any] = Field(
        default_factory=dict,
        description="Off-chain servicing duties. Opaque envelope.",
    )


def escrow_terms_to_settlement_obligation(
    terms: EscrowTerms | dict[str, Any],
) -> SettlementObligation:
    """Wrap this kit's typed alkahest shape in the mechanism envelope.

    The maker funds the escrow and the other side claims it; the asset is the
    escrowed token and the amount its obligation amount, which travels in its
    decimal-string uint256 form.
    """
    model = terms if isinstance(terms, EscrowTerms) else EscrowTerms.model_validate(terms)
    obligation_data = dict(model.obligation_data)
    amount = obligation_data.get("amount")
    if isinstance(amount, int) and not isinstance(amount, bool):
        obligation_data["amount"] = str(amount)
        amount = obligation_data["amount"]
    params: dict[str, Any] = {
        "escrow_contract": model.escrow_contract,
        "obligation_data": obligation_data,
    }
    if model.chain_name is not None:
        params["chain_name"] = model.chain_name
    return SettlementObligation(
        payer=model.maker,
        claimant="seller" if model.maker == "buyer" else "buyer",
        amount=amount if isinstance(amount, str) else None,
        asset=obligation_data.get("token"),
        expiration_unix=model.expiration_unix,
        mechanism=ALKAHEST_MECHANISM,
        params=params,
    )


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
        raise ValueError(f"not an {ALKAHEST_MECHANISM} obligation: {ob.mechanism!r}")
    obligation_data = dict(ob.params.get("obligation_data") or {})
    amount = obligation_data.get("amount")
    if isinstance(amount, str) and amount.isdecimal():
        obligation_data["amount"] = int(amount)
    return EscrowTerms(
        maker=ob.payer,
        chain_name=ob.params.get("chain_name"),
        escrow_contract=ob.params["escrow_contract"],
        obligation_data=obligation_data,
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
        plan
        if isinstance(plan, SettlementPlan)
        else SettlementPlan.model_validate(plan)
    )
    return [settlement_obligation_to_escrow_terms(ob) for ob in plan_model.obligations]


def _comparable_obligation_value(value: Any) -> Any:
    """An obligation-data value with address and byte hex compared case-insensitively.

    Only ``0x``-prefixed strings are lowercased; any other string must match exactly.
    """
    if isinstance(value, str):
        return value.lower() if value[:2].lower() == "0x" else value
    if isinstance(value, Mapping):
        return {str(key): _comparable_obligation_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_comparable_obligation_value(item) for item in value]
    return value


def _comparable_terms(terms: EscrowTerms) -> dict[str, Any]:
    obligation_data = dict(terms.obligation_data)
    amount = obligation_data.get("amount")
    if isinstance(amount, str) and amount.isdecimal():
        obligation_data["amount"] = int(amount)
    return {
        "maker": terms.maker,
        "chain_name": terms.chain_name,
        "escrow_contract": terms.escrow_contract.lower(),
        "expiration_unix": terms.expiration_unix,
        "obligation_data": _comparable_obligation_value(obligation_data),
    }


def require_escrow_terms_fund_plan(
    terms: list[EscrowTerms | dict[str, Any]],
    plan: Any,
) -> None:
    """Refuse unless ``terms`` are exactly the escrows ``plan`` commits to.

    ``terms`` are what a buyer derived for itself from its accepted proposal or
    selection and the listing's release condition; ``plan`` is the seller's
    committed copy. Every escrow must agree in maker, chain, contract, expiry,
    and obligation data, so a plan naming another arbiter, recipient, token, or
    amount than the buyer derived is caught before anything is funded. ``plan``
    is this kit's ``SettlementPlan``, its wire form, or any other model of the
    shared settlement-plan contract, such as core's, which is read through its
    wire form. Raises ``ValueError`` starting ``seller_plan_mismatch`` and
    naming the first escrow and field that differ.
    """
    if not isinstance(plan, SettlementPlan) and hasattr(plan, "model_dump"):
        plan = plan.model_dump(mode="json")
    derived = [
        _comparable_terms(
            item if isinstance(item, EscrowTerms) else EscrowTerms.model_validate(item)
        )
        for item in terms
    ]
    planned = [_comparable_terms(item) for item in escrow_terms_from_settlement_plan(plan)]
    if len(derived) != len(planned):
        raise ValueError(
            f"seller_plan_mismatch: the plan commits to {len(planned)} escrow(s), "
            f"the buyer derived {len(derived)}"
        )
    for index, (mine, theirs) in enumerate(zip(derived, planned)):
        for field in ("maker", "chain_name", "escrow_contract", "expiration_unix"):
            if mine[field] != theirs[field]:
                raise ValueError(
                    f"seller_plan_mismatch: escrow {index} {field} differs from the "
                    "buyer's derivation"
                )
        mine_data, theirs_data = mine["obligation_data"], theirs["obligation_data"]
        for key in sorted(set(mine_data) | set(theirs_data)):
            if mine_data.get(key) != theirs_data.get(key):
                raise ValueError(
                    f"seller_plan_mismatch: escrow {index} obligation field {key!r} "
                    "differs from the buyer's derivation"
                )


def materialize_settlement_plan_from_proposal(
    *,
    proposal: Any,
    listing: Any,
    agreed_amount: int | None,
    duration_seconds: int,
    addr_config_path: str | None = None,
    service_terms: dict[str, Any] | None = None,
) -> SettlementPlan:
    """Derive the settlement plan from a negotiated escrow proposal.

    The deterministic counterpart of
    ``materialize_escrow_terms_from_proposal`` — same inputs, same
    derivation, with each materialized escrow wrapped in the
    ``alkahest.v1`` envelope, so its release condition is the one
    ``listing`` authorizes. Single-obligation plans today; the shape
    already admits N obligations and mixed mechanisms.
    """
    terms = materialize_escrow_terms_from_proposal(
        proposal=proposal,
        listing=listing,
        agreed_amount=agreed_amount,
        duration_seconds=duration_seconds,
        addr_config_path=addr_config_path,
    )
    return SettlementPlan(
        obligations=[escrow_terms_to_settlement_obligation(t) for t in terms],
        service_terms=dict(service_terms or {}),
    )


class IntervalAllocation(BaseModel):
    """One deterministic interval boundary and its conserved amount."""

    interval_index: int = Field(ge=0)
    duration_seconds: int = Field(gt=0)
    expiration_unix: int = Field(gt=0)
    amount: int = Field(gt=0)


def interval_amount_schedule(
    *,
    total_amount: int,
    start_unix: int,
    duration_seconds: int,
    interval_seconds: int,
) -> list[IntervalAllocation]:
    """Split a total proportionally and allocate rounding remainder earliest."""
    if total_amount <= 0:
        raise ValueError("total_amount must be positive")
    if start_unix <= 0:
        raise ValueError("start_unix must be positive")
    if duration_seconds <= 0:
        raise ValueError("duration_seconds must be positive")
    if interval_seconds <= 0:
        raise ValueError("interval_seconds must be positive")

    interval_count = (duration_seconds + interval_seconds - 1) // interval_seconds
    if total_amount < interval_count:
        raise ValueError(
            "total_amount cannot produce a positive amount for every interval"
        )
    durations = [
        min(interval_seconds, duration_seconds - index * interval_seconds)
        for index in range(interval_count)
    ]
    amounts = [
        total_amount * interval_duration // duration_seconds
        for interval_duration in durations
    ]
    remainder = total_amount - sum(amounts)
    for index in range(remainder):
        amounts[index] += 1

    elapsed = 0
    schedule: list[IntervalAllocation] = []
    for index, (interval_duration, amount) in enumerate(zip(durations, amounts)):
        elapsed += interval_duration
        schedule.append(
            IntervalAllocation(
                interval_index=index,
                duration_seconds=interval_duration,
                expiration_unix=start_unix + elapsed,
                amount=amount,
            )
        )
    return schedule


def split_settlement_obligation_into_intervals(
    obligation: SettlementObligation | dict[str, Any],
    *,
    start_unix: int,
    duration_seconds: int,
    interval_seconds: int,
) -> list[SettlementObligation]:
    """Produce independent Alkahest obligations without changing ABI demand."""
    template = (
        obligation
        if isinstance(obligation, SettlementObligation)
        else SettlementObligation.model_validate(obligation)
    )
    if template.mechanism != ALKAHEST_MECHANISM:
        raise ValueError(
            f"not an {ALKAHEST_MECHANISM} obligation: {template.mechanism!r}"
        )
    if template.amount is None:
        raise ValueError("interval policy requires a scalar obligation amount")
    expected_expiration = start_unix + duration_seconds
    if template.expiration_unix != expected_expiration:
        raise ValueError(
            "obligation expiration does not match the accepted interval duration"
        )

    schedule = interval_amount_schedule(
        total_amount=template.amount,
        start_unix=start_unix,
        duration_seconds=duration_seconds,
        interval_seconds=interval_seconds,
    )
    obligations: list[SettlementObligation] = []
    for allocation in schedule:
        params = deepcopy(template.params)
        obligation_data = params.get("obligation_data")
        if not isinstance(obligation_data, dict):
            raise ValueError("interval policy requires Alkahest obligation_data")
        obligation_data["amount"] = str(allocation.amount)
        obligations.append(
            template.model_copy(
                update={
                    "amount": allocation.amount,
                    "expiration_unix": allocation.expiration_unix,
                    "params": params,
                }
            )
        )
    return obligations


def build_penalty_bond_obligation(
    template: SettlementObligation | dict[str, Any],
    *,
    amount: int,
    expiration_unix: int | None = None,
) -> SettlementObligation:
    """Build an explicit seller-funded, buyer-claimable bond obligation."""
    if amount <= 0:
        raise ValueError("penalty bond amount must be positive")
    source = (
        template
        if isinstance(template, SettlementObligation)
        else SettlementObligation.model_validate(template)
    )
    if source.mechanism != ALKAHEST_MECHANISM:
        raise ValueError(
            f"not an {ALKAHEST_MECHANISM} obligation: {source.mechanism!r}"
        )
    params = deepcopy(source.params)
    obligation_data = params.get("obligation_data")
    if not isinstance(obligation_data, dict):
        raise ValueError("penalty bond requires Alkahest obligation_data")
    obligation_data["amount"] = str(amount)
    return source.model_copy(
        update={
            "payer": "seller",
            "claimant": "buyer",
            "amount": amount,
            "expiration_unix": expiration_unix or source.expiration_unix,
            "params": params,
        }
    )


def settlement_plan_payload_from_proposal(
    *,
    proposal: Any,
    listing: Any,
    agreed_amount: int | None,
    duration_seconds: int,
    addr_config_path: str | None = None,
    service_terms: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """JSON-serializable variant of the plan materialization."""
    return materialize_settlement_plan_from_proposal(
        proposal=proposal,
        listing=listing,
        agreed_amount=agreed_amount,
        duration_seconds=duration_seconds,
        addr_config_path=addr_config_path,
        service_terms=service_terms,
    ).model_dump()
