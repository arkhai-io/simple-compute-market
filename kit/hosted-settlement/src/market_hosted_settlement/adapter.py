from __future__ import annotations

import hashlib
import json
import re
from typing import Any, Literal

from hosted_settlement_client import (
    CheckEscrowRequest,
    ConditionDescriptor,
    ConditionState,
    CreateEscrowRequest,
    EscrowResult,
    FinancialState,
    FulfillmentRef,
    HostedSettlementAsyncClient,
    OperationRequest,
    canonical_json,
)
from market_settlement_runtime import (
    ConditionOutcome,
    EffectOutcome,
    MaterializationOutcome,
    StatusOutcome,
)
from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, field_validator

MECHANISM = "fiat.stripe.v1"
_CURRENCY = re.compile(r"^[a-z]{3}$")
_FULFILLMENT: TypeAdapter[FulfillmentRef] = TypeAdapter(FulfillmentRef)


class HostedObligationParams(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    account_ref: str = Field(min_length=1, max_length=256)
    payer_address: str = Field(min_length=1, max_length=256)
    claimant_address: str = Field(min_length=1, max_length=256)
    funds_flow: Literal["separate_charges_transfers"]
    payment_method_types: tuple[Literal["card"], ...] = ("card",)
    condition: ConditionDescriptor

    @field_validator("payment_method_types")
    @classmethod
    def validate_payment_methods(
        cls, value: tuple[Literal["card"], ...]
    ) -> tuple[Literal["card"], ...]:
        if value != ("card",):
            raise ValueError(
                "hosted settlement supports exactly the card payment method"
            )
        return value


class HostedConditionalEscrowClient:
    """Maps the generic settlement runtime to the released hosted contract."""

    def __init__(self, client: HostedSettlementAsyncClient) -> None:
        self._client = client

    async def verify_contract_ready(
        self,
        *,
        expected_manifest_digest: str,
        expected_contract_version: str,
        expected_schema_version: int,
        required_capabilities: tuple[str, ...],
        operation_ref: str,
    ) -> None:
        """Verify the exact released authority contract without account state."""
        health = await self._client.health(request_id=f"{operation_ref}:health")
        if not health.ready:
            raise ValueError("hosted settlement authority is not ready")
        if health.manifest_digest != expected_manifest_digest:
            raise ValueError("hosted settlement manifest digest does not match")
        if health.api_version != expected_contract_version:
            raise ValueError("hosted settlement contract version does not match")
        if health.schema_version != expected_schema_version:
            raise ValueError("hosted settlement schema version does not match")
        missing = sorted(set(required_capabilities).difference(health.capabilities))
        if missing:
            raise ValueError("hosted settlement authority lacks required capabilities")

    async def verify_ready(
        self,
        *,
        account_ref: str,
        expected_manifest_digest: str,
        expected_contract_version: str,
        required_capabilities: tuple[str, ...],
        expected_schema_version: int,
        operation_ref: str,
    ) -> None:
        """Fail closed on release/capability skew before option publication."""
        await self.verify_contract_ready(
            expected_manifest_digest=expected_manifest_digest,
            expected_contract_version=expected_contract_version,
            required_capabilities=required_capabilities,
            expected_schema_version=expected_schema_version,
            operation_ref=operation_ref,
        )
        account = await self._client.account_readiness(
            account_ref,
            request_id=f"{operation_ref}:account",
        )
        if account.account_ref != account_ref or not account.ready:
            raise ValueError("hosted settlement account is not ready")
        if "transfers" not in account.capabilities:
            raise ValueError("hosted settlement account transfers are not active")

    async def materialize(
        self, obligation: dict[str, Any], *, operation_ref: str
    ) -> MaterializationOutcome:
        params, amount, currency, expiration = _validate_obligation(obligation)
        result = await self._client.materialize(
            CreateEscrowRequest(
                request_id=operation_ref,
                obligation_ref=_obligation_ref_from_operation(operation_ref),
                obligation_hash="0x"
                + hashlib.sha256(canonical_json(obligation)).hexdigest(),
                payer=params.payer_address,
                claimant=params.claimant_address,
                account_ref=params.account_ref,
                amount=amount,
                currency=currency,
                expiration_unix=expiration,
                condition=params.condition,
            )
        )
        return MaterializationOutcome(
            mechanism_ref=result.escrow_ref,
            status=_materialization_status(result),
            buyer_action=_safe_action(result),
            condition_anchor=result.condition_anchor,
            receipt=_status_receipt(result),
            mechanism_state=_mechanism_state(result),
        )

    async def get_status(
        self,
        obligation: dict[str, Any],
        *,
        mechanism_ref: str,
        operation_ref: str,
        mechanism_state: dict[str, Any],
    ) -> StatusOutcome:
        _validate_obligation(obligation)
        del mechanism_state
        result = await self._client.get_status(mechanism_ref, request_id=operation_ref)
        return StatusOutcome(
            status=_escrow_status(result),
            mechanism_ref=result.escrow_ref,
            buyer_action=_safe_action(result),
            condition_anchor=result.condition_anchor,
            receipt=_status_receipt(result),
            mechanism_state=_mechanism_state(result),
        )

    async def check(
        self,
        obligation: dict[str, Any],
        *,
        mechanism_ref: str,
        fulfillment_ref: str,
        operation_ref: str,
        mechanism_state: dict[str, Any],
    ) -> ConditionOutcome:
        _validate_obligation(obligation)
        del mechanism_state
        fulfillment = _decode_fulfillment(fulfillment_ref)
        result = await self._client.check(
            mechanism_ref,
            CheckEscrowRequest(request_id=operation_ref, fulfillment=fulfillment),
        )
        decision = _condition_decision(result.condition_state)
        return ConditionOutcome(
            decision=decision,
            receipt={
                "evaluation_digest": result.evaluation_digest,
                "evaluated_at_unix": result.evaluated_at_unix,
                "valid_until_unix": result.valid_until_unix,
            },
            mechanism_state={"condition_state": result.condition_state.value},
        )

    async def collect(
        self,
        obligation: dict[str, Any],
        *,
        mechanism_ref: str,
        fulfillment_ref: str,
        operation_ref: str,
        mechanism_state: dict[str, Any],
    ) -> EffectOutcome:
        _validate_obligation(obligation)
        del fulfillment_ref, mechanism_state
        result = await self._client.collect(
            mechanism_ref, OperationRequest(request_id=operation_ref)
        )
        return EffectOutcome(
            receipt=result.model_dump(mode="json"),
            mechanism_state={"financial_state": result.financial_state.value},
        )

    async def reclaim_expired(
        self,
        obligation: dict[str, Any],
        *,
        mechanism_ref: str,
        operation_ref: str,
        mechanism_state: dict[str, Any],
    ) -> EffectOutcome:
        _validate_obligation(obligation)
        del mechanism_state
        result = await self._client.reclaim(
            mechanism_ref, OperationRequest(request_id=operation_ref)
        )
        return EffectOutcome(
            receipt=result.model_dump(mode="json"),
            mechanism_state={"financial_state": result.financial_state.value},
        )

    async def get_buyer_action(
        self, mechanism_ref: str, *, operation_ref: str
    ) -> dict[str, Any] | None:
        """Fetch a redirect for immediate return; callers must not persist it."""
        result = await self._client.get_status(mechanism_ref, request_id=operation_ref)
        if result.action is None:
            return None
        return result.action.model_dump(mode="json")


def _obligation_ref_from_operation(operation_ref: str) -> str:
    prefix = "arkhai:settlement:"
    suffix = ":materialize"
    if not operation_ref.startswith(prefix) or not operation_ref.endswith(suffix):
        raise ValueError("hosted materialization requires a stable operation reference")
    obligation_ref = operation_ref[len(prefix) : -len(suffix)]
    if not obligation_ref:
        raise ValueError("hosted materialization operation has no obligation reference")
    return obligation_ref


def _validate_obligation(
    obligation: dict[str, Any],
) -> tuple[HostedObligationParams, int, str, int]:
    if obligation.get("mechanism") != MECHANISM:
        raise ValueError(f"hosted adapter requires mechanism {MECHANISM}")
    if obligation.get("payer") != "buyer" or obligation.get("claimant") != "seller":
        raise ValueError("hosted settlement must be buyer-funded and seller-claimed")
    raw_amount = obligation.get("amount")
    if isinstance(raw_amount, bool):
        amount = 0
    elif isinstance(raw_amount, int):
        amount = raw_amount
    elif (
        isinstance(raw_amount, str)
        and raw_amount.isdigit()
        and str(int(raw_amount)) == raw_amount
    ):
        amount = int(raw_amount)
    else:
        amount = 0
    if amount <= 0:
        raise ValueError(
            "hosted settlement amount must be a positive integer minor unit"
        )
    currency = obligation.get("asset")
    if not isinstance(currency, str) or not _CURRENCY.fullmatch(currency):
        raise ValueError(
            "hosted settlement asset must be a lowercase ISO 4217 currency"
        )
    expiration = obligation.get("expiration_unix")
    if (
        isinstance(expiration, bool)
        or not isinstance(expiration, int)
        or expiration <= 0
    ):
        raise ValueError(
            "hosted settlement expiration must be a positive unix timestamp"
        )
    raw_params = obligation.get("params")
    if not isinstance(raw_params, dict):
        raise ValueError("hosted settlement params must be an object")
    condition = ConditionDescriptor.model_validate_json(
        canonical_json(raw_params.get("condition"))
    )
    params = HostedObligationParams.model_validate(
        {**raw_params, "condition": condition}
    )
    return params, amount, currency, expiration


def _decode_fulfillment(value: str) -> FulfillmentRef:
    try:
        decoded = json.loads(value)
    except (TypeError, json.JSONDecodeError) as exc:
        raise ValueError("hosted fulfillment reference must be canonical JSON") from exc
    if canonical_json(decoded).decode() != value:
        raise ValueError(
            "hosted fulfillment reference must use canonical JSON encoding"
        )
    return _FULFILLMENT.validate_json(value)


def _condition_decision(
    state: ConditionState,
) -> Literal["pending", "ready", "failed", "manual_required"]:
    if state == ConditionState.SATISFIED:
        return "ready"
    if state == ConditionState.PENDING:
        return "pending"
    if state == ConditionState.INVALID:
        return "failed"
    return "manual_required"


def _materialization_status(
    result: EscrowResult,
) -> Literal["requires_action", "pending", "ready", "manual_required"]:
    if result.financial_state == FinancialState.OPERATOR_REVIEW:
        return "manual_required"
    if result.financial_state == FinancialState.FUNDED:
        return "ready"
    if result.action is not None:
        return "requires_action"
    return "pending"


def _escrow_status(
    result: EscrowResult,
) -> Literal[
    "requires_action",
    "pending",
    "ready",
    "collected",
    "reclaimed",
    "expired",
    "failed",
    "manual_required",
]:
    return {
        FinancialState.CREATING: "pending",
        FinancialState.AWAITING_PAYMENT: "requires_action"
        if result.action
        else "pending",
        FinancialState.FUNDED: "ready",
        FinancialState.COLLECTING: "pending",
        FinancialState.COLLECTED: "collected",
        FinancialState.RECLAIMING: "pending",
        FinancialState.RECLAIMED: "reclaimed",
        FinancialState.EXPIRED: "expired",
        FinancialState.OPERATOR_REVIEW: "manual_required",
    }[result.financial_state]


def _safe_action(result: EscrowResult) -> dict[str, Any] | None:
    if result.action is None:
        return None
    return {
        "kind": result.action.kind,
        "expires_at_unix": result.action.expires_at_unix,
    }


def _status_receipt(result: EscrowResult) -> dict[str, Any]:
    return {
        "escrow_ref": result.escrow_ref,
        "financial_state": result.financial_state.value,
        "condition_state": result.condition_state.value,
        "expiration_unix": result.expiration_unix,
    }


def _mechanism_state(result: EscrowResult) -> dict[str, Any]:
    return {
        "financial_state": result.financial_state.value,
        "condition_state": result.condition_state.value,
        "expiration_unix": result.expiration_unix,
    }
