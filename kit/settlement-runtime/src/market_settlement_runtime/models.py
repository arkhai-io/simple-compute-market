"""Public, mechanism-neutral settlement lifecycle models."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from typing import Any, Literal

from market_identity import Identity
from pydantic import BaseModel, Field, model_validator

Party = Literal["buyer", "seller"]
OperationKind = Literal[
    "materialize", "status", "fulfill", "check", "collect", "reclaim"
]
OperationState = Literal["pending", "in_progress", "succeeded", "manual_required"]
MaterializationState = Literal[
    "pending", "in_progress", "materialized", "manual_required"
]
ConditionState = Literal["pending", "ready", "failed", "manual_required"]
TerminalEffectState = Literal["pending", "in_progress", "succeeded", "manual_required"]
ConditionDecision = Literal["pending", "ready", "failed", "manual_required"]
MaterializationStatus = Literal[
    "requires_action", "pending", "ready", "manual_required"
]
EscrowStatus = Literal[
    "requires_action",
    "pending",
    "ready",
    "collected",
    "reclaimed",
    "expired",
    "failed",
    "manual_required",
]


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def obligation_payload_hash(obligation: Mapping[str, Any]) -> str:
    return hashlib.sha256(canonical_json(dict(obligation)).encode()).hexdigest()


def _canonical_obligation_principals(
    obligation: Mapping[str, Any],
) -> tuple[dict[str, Any], Identity, Identity]:
    snapshot = dict(obligation)
    for field in ("payer_principal", "claimant_principal"):
        if field not in snapshot:
            raise ValueError(f"settlement obligation requires {field}")
    payer = Identity.model_validate(snapshot["payer_principal"])
    claimant = Identity.model_validate(snapshot["claimant_principal"])
    snapshot["payer_principal"] = payer.model_dump(mode="json")
    snapshot["claimant_principal"] = claimant.model_dump(mode="json")
    return snapshot, payer, claimant


def derive_obligation_ref(
    agreement_ref: str, obligation_index: int, obligation: Mapping[str, Any]
) -> str:
    if not agreement_ref:
        raise ValueError("agreement_ref must be non-empty")
    if obligation_index < 0:
        raise ValueError("obligation_index must be non-negative")
    identity = {
        "protocol": "arkhai.settlement-obligation.v1",
        "agreement_ref": agreement_ref,
        "obligation_index": obligation_index,
        "obligation": dict(obligation),
    }
    return hashlib.sha256(canonical_json(identity).encode()).hexdigest()


class SettlementOperationRecord(BaseModel):
    obligation_ref: str
    operation: OperationKind
    request_hash: str
    state: OperationState = "pending"
    attempts: int = Field(default=0, ge=0)
    uncertain_acknowledgement: bool = False
    receipt: dict[str, Any] | None = None
    last_error: str | None = None
    lease_owner: str | None = None
    lease_until_unix: float | None = None
    next_attempt_unix: float | None = None


class SettlementObligationRecord(BaseModel):
    obligation_ref: str
    agreement_ref: str
    obligation_index: int = Field(ge=0)
    obligation_hash: str
    obligation: dict[str, Any]
    payer_principal: Identity
    claimant_principal: Identity
    mechanism_ref: str | None = None
    mechanism_status: str | None = None
    mechanism_state: dict[str, Any] = Field(default_factory=dict)
    mechanism_params: dict[str, Any] = Field(default_factory=dict)
    buyer_action: dict[str, Any] | None = None
    condition_anchor: str | None = None
    fulfillment_ref: str | None = None
    materialization_state: MaterializationState = "pending"
    condition_state: ConditionState = "pending"
    collection_state: TerminalEffectState = "pending"
    reclaim_state: TerminalEffectState = "pending"
    materialization_receipt: dict[str, Any] | None = None
    status_receipt: dict[str, Any] | None = None
    collection_receipt: dict[str, Any] | None = None
    reclaim_receipt: dict[str, Any] | None = None
    last_error: str | None = None
    version: int = Field(default=0, ge=0)

    @model_validator(mode="before")
    @classmethod
    def bind_principals(cls, value: Any) -> Any:
        if not isinstance(value, Mapping):
            return value
        data = dict(value)
        obligation = data.get("obligation")
        if not isinstance(obligation, Mapping):
            return data
        payer_value = data.get("payer_principal")
        claimant_value = data.get("claimant_principal")
        if payer_value is not None and claimant_value is not None:
            payer = Identity.model_validate(payer_value)
            claimant = Identity.model_validate(claimant_value)
            if (
                "payer_principal" in obligation
                or "claimant_principal" in obligation
            ):
                snapshot, nested_payer, nested_claimant = (
                    _canonical_obligation_principals(obligation)
                )
                if nested_payer != payer or nested_claimant != claimant:
                    raise ValueError(
                        "settlement obligation principals do not match its record"
                    )
                data["obligation"] = snapshot
            data["payer_principal"] = payer
            data["claimant_principal"] = claimant
            return data
        snapshot, payer, claimant = _canonical_obligation_principals(obligation)
        data["obligation"] = snapshot
        data["payer_principal"] = payer
        data["claimant_principal"] = claimant
        return data

    @classmethod
    def from_obligation(
        cls, *, agreement_ref: str, obligation_index: int, obligation: Mapping[str, Any]
    ) -> "SettlementObligationRecord":
        snapshot, payer, claimant = _canonical_obligation_principals(obligation)
        return cls(
            obligation_ref=derive_obligation_ref(
                agreement_ref, obligation_index, snapshot
            ),
            agreement_ref=agreement_ref,
            obligation_index=obligation_index,
            obligation_hash=obligation_payload_hash(snapshot),
            obligation=snapshot,
            payer_principal=payer,
            claimant_principal=claimant,
        )


class MaterializationOutcome(BaseModel):
    mechanism_ref: str
    status: MaterializationStatus = "pending"
    buyer_action: dict[str, Any] | None = None
    condition_anchor: str | None = None
    receipt: dict[str, Any] | None = None
    mechanism_state: dict[str, Any] = Field(default_factory=dict)
    last_error: str | None = None


class StatusOutcome(BaseModel):
    status: EscrowStatus
    mechanism_ref: str
    buyer_action: dict[str, Any] | None = None
    condition_anchor: str | None = None
    receipt: dict[str, Any] | None = None
    mechanism_state: dict[str, Any] = Field(default_factory=dict)
    last_error: str | None = None


class ConditionOutcome(BaseModel):
    decision: ConditionDecision
    receipt: dict[str, Any] | None = None
    mechanism_state: dict[str, Any] = Field(default_factory=dict)
    last_error: str | None = None


class EffectOutcome(BaseModel):
    receipt: dict[str, Any]
    mechanism_state: dict[str, Any] = Field(default_factory=dict)


class SettlementOperationOutcome(BaseModel):
    obligation_ref: str
    operation: OperationKind
    status: Literal["succeeded", "pending", "manual_required", "busy", "terminal"]
    receipt: dict[str, Any] | None = None


class SettlementPlanStatus(BaseModel):
    agreement_ref: str
    status: Literal["active", "partial", "complete", "manual_required"]
    obligations: list[SettlementObligationRecord]


def aggregate_settlement_status(
    obligations: list[SettlementObligationRecord],
) -> Literal["active", "partial", "complete", "manual_required"]:
    if any(
        "manual_required"
        in (
            item.materialization_state,
            item.condition_state,
            item.collection_state,
            item.reclaim_state,
        )
        for item in obligations
    ):
        return "manual_required"
    terminal = [
        item.collection_state == "succeeded" or item.reclaim_state == "succeeded"
        for item in obligations
    ]
    if obligations and all(terminal):
        return "complete"
    if any(terminal):
        return "partial"
    return "active"
