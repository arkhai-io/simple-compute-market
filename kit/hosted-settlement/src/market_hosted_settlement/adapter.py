from __future__ import annotations

import hashlib
import json
import re
from typing import Any, Literal

from hosted_settlement_client import (
    REQUEST_PROTOCOL,
    RESPONSE_PROTOCOL,
    CheckEscrowRequest,
    ConditionDescriptor,
    ConditionState,
    CreateEscrowRequest,
    EscrowResult,
    ExpectedAuthorities,
    FinancialState,
    FulfillmentPublicationRequest,
    FulfillmentRef,
    FundingProfile,
    FundingMode,
    HostedSettlementAsyncClient,
    HostedSettlementError,
    NormalizedFundingState,
    OperationRequest,
    Principal,
    canonical_json,
)
from hosted_settlement_client import (
    IdentityScheme as HostedIdentityScheme,
)
from market_identity import Signer as MarketplaceSigner
from market_identity import TrustedIdentitySet
from market_settlement_runtime import (
    ConditionOutcome,
    EffectOutcome,
    MaterializationOutcome,
    SettlementManualRequired,
    StatusOutcome,
    obligation_payload_hash,
)
from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, field_validator

MECHANISM = "fiat.stripe.v1"
EXPECTED_HOSTED_REQUEST_PROTOCOL = "arkhai.hosted-request-signature.v2"
EXPECTED_HOSTED_RESPONSE_PROTOCOL = "arkhai.hosted-response-signature.v2"
REQUIRED_HOSTED_CAPABILITIES = frozenset(
    {
        "account-owner-admission.v1",
        "account-owner-rotation.v1",
        "account-owner-retirement.v1",
        "operator-recovery-redaction.v1",
        "provider-neutral-seller-onboarding.v1",
        "scheme-tagged-identities.v1",
        "signer-injected-client.v1",
    }
)
_CURRENCY = re.compile(r"^[a-z]{3}$")
_FULFILLMENT: TypeAdapter[FulfillmentRef] = TypeAdapter(FulfillmentRef)
_CONTRACT_FINGERPRINT = re.compile(r"^sha256:[0-9a-f]{64}$")
_UNCERTAIN_RESPONSE_CODES = frozenset(
    {
        "invalid_response",
        "invalid_error_response",
        "response_request_mismatch",
        "response_too_large",
        "redirect_refused",
    }
)


class HostedSettlementTemporaryError(RuntimeError):
    """A provider-redacted failure that is safe to retry under the same identity."""


async def _released_call(operation: str, call: Any) -> Any:
    """Map released-client errors to stable, persistence-safe runtime failures."""

    try:
        return await call()
    except HostedSettlementError as exc:
        if exc.retryable or exc.code in _UNCERTAIN_RESPONSE_CODES:
            raise HostedSettlementTemporaryError(
                f"hosted settlement {operation} temporarily unavailable"
            ) from None
        raise SettlementManualRequired(
            f"hosted settlement {operation} rejected"
        ) from None
    except Exception:
        raise HostedSettlementTemporaryError(
            f"hosted settlement {operation} temporarily unavailable"
        ) from None


class HostedObligationParams(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    account_ref: str = Field(min_length=1, max_length=256)
    authority_id: str = Field(
        min_length=1,
        max_length=256,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]*$",
    )
    country: Literal["US"]
    environment: str = Field(
        min_length=1,
        max_length=256,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]*$",
    )
    payer_principal: Principal
    claimant_principal: Principal
    funds_flow: Literal["separate_charges_transfers"]
    funding_profile: FundingProfile
    funding_authorization_ref: str = Field(min_length=1, max_length=256)
    interaction: FundingMode
    contract_fingerprint: str = Field(
        min_length=71,
        max_length=71,
        pattern=_CONTRACT_FINGERPRINT,
    )
    condition: ConditionDescriptor


class _LegacyCardObligationParams(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    account_ref: str = Field(min_length=1, max_length=256)
    payer_principal: Principal
    claimant_principal: Principal
    funds_flow: Literal["separate_charges_transfers"]
    payment_method_types: tuple[Literal["card"], ...]
    condition: ConditionDescriptor

    @field_validator("payment_method_types")
    @classmethod
    def validate_payment_methods(
        cls, value: tuple[Literal["card"], ...]
    ) -> tuple[Literal["card"], ...]:
        if value != ("card",):
            raise ValueError("legacy hosted recovery supports exactly card")
        return value


class MarketplaceSignerAdapter:
    """Expose a marketplace signer through the hosted client signer protocol."""

    __slots__ = ("_principal", "_signer")

    def __init__(self, signer: MarketplaceSigner) -> None:
        identity = signer.identity
        self._principal = Principal(
            scheme=HostedIdentityScheme(identity.scheme.value),
            identifier=identity.identifier,
        )
        self._signer = signer

    @property
    def principal(self) -> Principal:
        return self._principal

    def sign(self, message: bytes) -> bytes:
        return self._signer.sign(message)


def adapt_expected_authorities(
    trusted: TrustedIdentitySet,
) -> ExpectedAuthorities:
    """Convert shared marketplace trust pins at the hosted wire boundary."""

    if not isinstance(trusted, TrustedIdentitySet):
        raise TypeError("trusted must be a market_identity.TrustedIdentitySet")
    return ExpectedAuthorities(
        principals=tuple(
            Principal(
                scheme=HostedIdentityScheme(identity.scheme.value),
                identifier=identity.identifier,
            )
            for identity in trusted.identities
        )
    )


class HostedConditionalEscrowClient:
    """Maps the generic settlement runtime to the released hosted contract."""

    def __init__(self, client: HostedSettlementAsyncClient) -> None:
        if (
            REQUEST_PROTOCOL != EXPECTED_HOSTED_REQUEST_PROTOCOL
            or RESPONSE_PROTOCOL != EXPECTED_HOSTED_RESPONSE_PROTOCOL
        ):
            raise ValueError("hosted settlement client lacks identity v2")
        self._client = client

    async def publish_fulfillment(
        self,
        *,
        condition_anchor: str,
        evidence: str | None,
    ) -> str:
        evidence_digest = "sha256:" + hashlib.sha256(
            (evidence or "").encode()
        ).hexdigest()
        operation_digest = hashlib.sha256(
            f"{condition_anchor}\0{evidence_digest}".encode()
        ).hexdigest()
        result = await _released_call(
            "fulfillment publication",
            lambda: self._client.publish_fulfillment(
                FulfillmentPublicationRequest(
                    request_id=f"fulfillment:{operation_digest}",
                    condition_anchor=condition_anchor,
                    evidence_digest=evidence_digest,
                )
            ),
        )
        return result.attestation_uid

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
        health = await _released_call(
            "readiness",
            lambda: self._client.health(request_id=f"{operation_ref}:health"),
        )
        if not health.ready:
            raise ValueError("hosted settlement authority is not ready")
        if health.manifest_digest != expected_manifest_digest:
            raise ValueError("hosted settlement manifest digest does not match")
        if health.api_version != expected_contract_version:
            raise ValueError("hosted settlement contract version does not match")
        if health.schema_version != expected_schema_version:
            raise ValueError("hosted settlement schema version does not match")
        missing = sorted(
            REQUIRED_HOSTED_CAPABILITIES.union(required_capabilities).difference(
                health.capabilities
            )
        )
        if missing:
            raise ValueError(
                "hosted settlement authority lacks required capabilities: "
                + ", ".join(missing)
            )

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
        account = await _released_call(
            "account readiness",
            lambda: self._client.account_readiness(
                account_ref,
                request_id=f"{operation_ref}:account",
            ),
        )
        if account.account_ref != account_ref or not account.ready:
            raise ValueError("hosted settlement account is not ready")
        if "transfers" not in account.capabilities:
            raise ValueError("hosted settlement account transfers are not active")

    async def materialize(
        self, obligation: dict[str, Any], *, operation_ref: str
    ) -> MaterializationOutcome:
        params, amount, currency, expiration, legacy = _validate_obligation(
            obligation,
            allow_legacy=False,
        )
        if legacy or not isinstance(params, HostedObligationParams):
            raise ValueError("legacy hosted card obligations are recovery-only")
        obligation_ref = _obligation_ref_from_operation(operation_ref)
        result = await _released_call(
            "materialization",
            lambda: self._client.materialize(
                CreateEscrowRequest(
                    request_id=operation_ref,
                    obligation_ref=obligation_ref,
                    obligation_hash="0x"
                    + obligation_payload_hash(_accepted_obligation(obligation)),
                    payer=params.payer_principal,
                    claimant=params.claimant_principal,
                    account_ref=params.account_ref,
                    amount=amount,
                    currency=currency,
                    expiration_unix=expiration,
                    funding_profile=params.funding_profile,
                    funding_authorization_ref=params.funding_authorization_ref,
                    marketplace_operation_id=obligation_ref,
                    condition=params.condition,
                )
            ),
        )
        _require_result_profile(result, params.funding_profile)
        return MaterializationOutcome(
            mechanism_ref=result.escrow_ref,
            status=_materialization_status(result),
            buyer_action=_safe_action(result),
            condition_anchor=result.condition_anchor,
            receipt=_status_receipt(result, params, legacy=False),
            mechanism_state=_mechanism_state(result, params, legacy=False),
        )

    async def get_status(
        self,
        obligation: dict[str, Any],
        *,
        mechanism_ref: str,
        operation_ref: str,
        mechanism_state: dict[str, Any],
    ) -> StatusOutcome:
        params, _amount, _currency, _expiration, legacy = _validate_obligation(
            obligation,
            allow_legacy=True,
        )
        result = await _released_call(
            "status",
            lambda: self._client.get_status(
                mechanism_ref,
                request_id=operation_ref,
            ),
        )
        if isinstance(params, HostedObligationParams):
            _require_result_profile(result, params.funding_profile)
        return StatusOutcome(
            status=_escrow_status(result, mechanism_state),
            mechanism_ref=result.escrow_ref,
            buyer_action=_safe_action(result),
            condition_anchor=result.condition_anchor,
            receipt=_status_receipt(result, params, legacy=legacy),
            mechanism_state=_mechanism_state(
                result,
                params,
                legacy=legacy,
            ),
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
        _validate_obligation(obligation, allow_legacy=True)
        del mechanism_state
        fulfillment = _decode_fulfillment(fulfillment_ref)
        result = await _released_call(
            "condition check",
            lambda: self._client.check(
                mechanism_ref,
                CheckEscrowRequest(request_id=operation_ref, fulfillment=fulfillment),
            ),
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
        params, _amount, _currency, _expiration, legacy = _validate_obligation(
            obligation,
            allow_legacy=True,
        )
        del fulfillment_ref, mechanism_state
        result = await _released_call(
            "collection",
            lambda: self._client.collect(
                mechanism_ref,
                OperationRequest(request_id=operation_ref),
            ),
        )
        receipt = result.model_dump(mode="json")
        receipt.update(_operation_identity(params, legacy=legacy))
        return EffectOutcome(
            receipt=receipt,
            mechanism_state={
                **_operation_identity(params, legacy=legacy),
                "financial_state": result.financial_state.value,
            },
        )

    async def reclaim_expired(
        self,
        obligation: dict[str, Any],
        *,
        mechanism_ref: str,
        operation_ref: str,
        mechanism_state: dict[str, Any],
    ) -> EffectOutcome:
        params, _amount, _currency, _expiration, legacy = _validate_obligation(
            obligation,
            allow_legacy=True,
        )
        del mechanism_state
        result = await _released_call(
            "reclaim",
            lambda: self._client.reclaim(
                mechanism_ref,
                OperationRequest(request_id=operation_ref),
            ),
        )
        receipt = result.model_dump(mode="json")
        receipt.update(_operation_identity(params, legacy=legacy))
        return EffectOutcome(
            receipt=receipt,
            mechanism_state={
                **_operation_identity(params, legacy=legacy),
                "financial_state": result.financial_state.value,
            },
        )

    async def get_buyer_action(
        self, mechanism_ref: str, *, operation_ref: str
    ) -> dict[str, Any] | None:
        """Fetch a redirect for immediate return; callers must not persist it."""
        result = await _released_call(
            "buyer action",
            lambda: self._client.get_status(
                mechanism_ref,
                request_id=operation_ref,
            ),
        )
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
    *,
    allow_legacy: bool,
) -> tuple[
    HostedObligationParams | _LegacyCardObligationParams,
    int,
    str,
    int,
    bool,
]:
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
    values = dict(raw_params)
    legacy_marker = values.pop("legacy_recovery", None)
    condition = ConditionDescriptor.model_validate_json(
        canonical_json(values.get("condition"))
    )
    legacy = legacy_marker is not None
    if legacy:
        if legacy_marker != "hosted-card.v1" or not allow_legacy:
            raise ValueError("legacy hosted card obligations are recovery-only")
        params: HostedObligationParams | _LegacyCardObligationParams = (
            _LegacyCardObligationParams.model_validate(
                {**values, "condition": condition}
            )
        )
    else:
        if "payment_method_types" in values:
            raise ValueError(
                "payment_method_types is legacy-only; funding_profile is required"
            )
        params = HostedObligationParams.model_validate(
            {**values, "condition": condition}
        )
    payer_principal = Principal.model_validate(obligation.get("payer_principal"))
    claimant_principal = Principal.model_validate(
        obligation.get("claimant_principal")
    )
    if params.payer_principal != payer_principal:
        raise ValueError("hosted payer principal does not match the obligation")
    if params.claimant_principal != claimant_principal:
        raise ValueError("hosted claimant principal does not match the obligation")
    return params, amount, currency, expiration, legacy


def _accepted_obligation(obligation: dict[str, Any]) -> dict[str, Any]:
    snapshot = dict(obligation)
    raw_params = snapshot.get("params")
    if not isinstance(raw_params, dict):
        raise ValueError("hosted settlement params must be an object")
    params = dict(raw_params)
    params.pop("funding_authorization_ref", None)
    params.pop("legacy_recovery", None)
    snapshot["params"] = params
    return snapshot


def _require_result_profile(
    result: EscrowResult,
    expected: FundingProfile,
) -> None:
    if result.funding_profile != expected:
        raise ValueError("hosted result funding profile does not match accepted terms")


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
    status = _escrow_status(result, {})
    if status in {"collected", "ready"}:
        return "ready"
    if status == "manual_required":
        return "manual_required"
    if status == "requires_action":
        return "requires_action"
    return "pending"


def _escrow_status(
    result: EscrowResult,
    previous: dict[str, Any],
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
    previous_financial = previous.get("financial_state")
    previous_funding = previous.get("funding_state")
    post_collection_risk = (
        previous_financial == FinancialState.COLLECTED.value
        and (
            result.financial_state == FinancialState.OPERATOR_REVIEW
            or result.incident
            or result.funding_state
            in {
                NormalizedFundingState.RETURNED,
                NormalizedFundingState.FAILED,
                NormalizedFundingState.AMBIGUOUS,
            }
        )
    )
    if post_collection_risk:
        return "manual_required"
    if result.financial_state == FinancialState.OPERATOR_REVIEW or result.incident:
        return "manual_required"
    if result.funding_state == NormalizedFundingState.AMBIGUOUS:
        return "manual_required"
    if previous_financial == FinancialState.COLLECTED.value:
        return "collected"
    if result.funding_state in {
        NormalizedFundingState.RETURNED,
        NormalizedFundingState.FAILED,
    }:
        return "failed"
    if (
        result.funding_state == NormalizedFundingState.EXPIRED
        or result.financial_state == FinancialState.EXPIRED
    ):
        return "expired"
    if previous_financial == FinancialState.RECLAIMED.value:
        return "reclaimed"
    if result.financial_state == FinancialState.COLLECTED:
        return "collected"
    if result.financial_state == FinancialState.RECLAIMED:
        return "reclaimed"
    if result.funding_state in {
        NormalizedFundingState.AVAILABLE,
        NormalizedFundingState.TRANSFERRED,
    }:
        return "ready"
    if previous_funding in {
        NormalizedFundingState.AVAILABLE.value,
        NormalizedFundingState.TRANSFERRED.value,
    }:
        return "ready"
    if (
        result.action is not None
        or result.funding_state == NormalizedFundingState.ACTION_REQUIRED
    ):
        return "requires_action"
    return "pending"


def _safe_action(result: EscrowResult) -> dict[str, Any] | None:
    """Return the current action to the caller; persistence sanitizes it later."""

    if result.action is None:
        return None
    return result.action.model_dump(mode="json")

def _status_receipt(
    result: EscrowResult,
    params: HostedObligationParams | _LegacyCardObligationParams,
    *,
    legacy: bool,
) -> dict[str, Any]:
    receipt = {
        "escrow_ref": result.escrow_ref,
        "financial_state": result.financial_state.value,
        "funding_state": result.funding_state.value,
        "funding_reason": result.funding_reason,
        "funding_deadline_unix": result.funding_deadline_unix,
        "condition_state": result.condition_state.value,
        "expiration_unix": result.expiration_unix,
        "incident": (
            result.incident.model_dump(mode="json") if result.incident else None
        ),
    }
    receipt.update(_operation_identity(params, legacy=legacy))
    return receipt


def _mechanism_state(
    result: EscrowResult,
    params: HostedObligationParams | _LegacyCardObligationParams,
    *,
    legacy: bool,
) -> dict[str, Any]:
    return {
        **_operation_identity(params, legacy=legacy),
        "financial_state": result.financial_state.value,
        "funding_state": result.funding_state.value,
        "funding_reason": result.funding_reason,
        "funding_deadline_unix": result.funding_deadline_unix,
        "condition_state": result.condition_state.value,
        "expiration_unix": result.expiration_unix,
        "incident": (
            result.incident.model_dump(mode="json") if result.incident else None
        ),
    }


def _operation_identity(
    params: HostedObligationParams | _LegacyCardObligationParams,
    *,
    legacy: bool,
) -> dict[str, Any]:
    if legacy:
        return {
            "legacy_recovery": "hosted-card.v1",
            "terminal_risk_monitoring": True,
        }
    assert isinstance(params, HostedObligationParams)
    return {
        "funding_profile": params.funding_profile.value,
        "funding_authorization_ref": params.funding_authorization_ref,
        "terminal_risk_monitoring": True,
    }
