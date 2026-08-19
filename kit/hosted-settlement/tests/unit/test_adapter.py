from __future__ import annotations

import hashlib
import json
from typing import Any

import market_hosted_settlement.adapter as adapter_module
from market_hosted_settlement import hosted_projected_reason
import pytest
from hosted_settlement_client import (
    AccountReadiness,
    BuyerAction,
    ClientConfig,
    ConditionDescriptor,
    ConditionState,
    CreateEscrowRequest,
    EscrowResult,
    ExpectedAuthorities,
    FinancialState,
    FulfillmentPublicationResult,
    FundingProfile,
    FundingProfileReadiness,
    HostedSettlementAsyncClient,
    HostedSettlementError,
    ManifestHealth,
    NormalizedFundingState,
    OperationReceipt,
    OperationRequest,
    PayerActionKind,
    Principal,
)
from market_hosted_settlement import (
    REQUIRED_HOSTED_CAPABILITIES,
    HostedConditionalEscrowClient,
    MarketplaceSignerAdapter,
)
from market_identity import Identity, IdentityScheme
from market_settlement_runtime import (
    SettlementManualRequired,
    SettlementRuntime,
    SettlementSQLiteRepository,
    obligation_payload_hash,
)

BUYER = Identity(
    scheme=IdentityScheme.ED25519,
    identifier="ERERERERERERERERERERERERERERERERERERERERERE",
)
SELLER = Identity(
    scheme=IdentityScheme.ED25519,
    identifier="IiIiIiIiIiIiIiIiIiIiIiIiIiIiIiIiIiIiIiIiIiI",
)
EIP191 = Identity(
    scheme=IdentityScheme.EIP191,
    identifier="0x3333333333333333333333333333333333333333",
)


class FakeMarketplaceSigner:
    __slots__ = ("identity", "messages", "_signature")

    def __init__(self, identity: Identity, signature: bytes) -> None:
        self.identity = identity
        self.messages: list[bytes] = []
        self._signature = signature

    def sign(self, message: bytes) -> bytes:
        self.messages.append(message)
        return self._signature


class FakeClient:
    def __init__(self) -> None:
        self.materialize_request: Any = None
        self.publication_request: Any = None
        self.status_call: tuple[str, str] | None = None
        self.collect_call: tuple[str, OperationRequest] | None = None
        self.reclaim_call: tuple[str, OperationRequest] | None = None
        self.escrow_result = self.escrow()
        self.health_result = ManifestHealth(
            ready=True,
            manifest_digest="sha256:" + "aa" * 32,
            schema_version=5,
            funding_profiles=tuple(
                FundingProfileReadiness(
                    profile=profile,
                    ready=True,
                    funding_deadline_seconds=3600,
                    availability_delay_seconds=0,
                )
                for profile in FundingProfile
            ),
            capabilities=tuple(sorted(REQUIRED_HOSTED_CAPABILITIES)),
        )

    @staticmethod
    def escrow(**updates: Any) -> EscrowResult:
        values: dict[str, Any] = {
            "escrow_ref": "escrow-public",
            "financial_state": FinancialState.AWAITING_PAYMENT,
            "condition_state": ConditionState.PENDING,
            "funding_profile": FundingProfile.CARD,
            "funding_state": NormalizedFundingState.ACTION_REQUIRED,
            "funding_reason": "payer_action_required",
            "funding_deadline_unix": 2_000_000_100,
            "action": BuyerAction(
                kind=PayerActionKind.PAYMENT,
                operation_ref="funding-action-1",
                url="https://checkout.example/secret-session",
                expires_at_unix=2_000_000_100,
            ),
            "condition_anchor": "0x" + "66" * 32,
            "expiration_unix": 2_000_003_600,
        }
        values.update(updates)
        return EscrowResult(**values)

    async def health(self, *, request_id: str) -> ManifestHealth:
        return self.health_result

    async def account_readiness(
        self, account_ref: str, *, request_id: str
    ) -> AccountReadiness:
        return AccountReadiness(
            account_ref=account_ref,
            ready=True,
            capabilities=("transfers",),
            funding_profiles=self.health_result.funding_profiles,
        )

    async def publish_fulfillment(self, request: Any) -> FulfillmentPublicationResult:
        self.publication_request = request
        return FulfillmentPublicationResult(
            request_id=request.request_id,
            attestation_uid="0x" + "99" * 32,
        )

    async def materialize(self, request: Any) -> EscrowResult:
        self.materialize_request = request
        return self.escrow_result

    async def get_status(self, escrow_ref: str, *, request_id: str) -> EscrowResult:
        self.status_call = (escrow_ref, request_id)
        return self.escrow_result

    async def collect(
        self, escrow_ref: str, request: OperationRequest
    ) -> OperationReceipt:
        self.collect_call = (escrow_ref, request)
        return OperationReceipt(
            escrow_ref=escrow_ref,
            operation_ref=request.request_id,
            financial_state=FinancialState.COLLECTED,
            receipt="sha256:" + "77" * 32,
        )

    async def reclaim(
        self, escrow_ref: str, request: OperationRequest
    ) -> OperationReceipt:
        self.reclaim_call = (escrow_ref, request)
        return OperationReceipt(
            escrow_ref=escrow_ref,
            operation_ref=request.request_id,
            financial_state=FinancialState.RECLAIMED,
            receipt="sha256:" + "88" * 32,
        )


class FailingMaterializeClient(FakeClient):
    def __init__(self, error: Exception) -> None:
        super().__init__()
        self.error = error

    async def materialize(self, request: Any) -> EscrowResult:
        self.materialize_request = request
        raise self.error

    async def get_status(self, escrow_ref: str, *, request_id: str) -> EscrowResult:
        raise self.error

    async def collect(
        self, escrow_ref: str, request: OperationRequest
    ) -> OperationReceipt:
        raise self.error

    async def reclaim(
        self, escrow_ref: str, request: OperationRequest
    ) -> OperationReceipt:
        raise self.error


class CommitThenInvalidResponseClient(FakeClient):
    def __init__(self) -> None:
        super().__init__()
        self.materialize_requests: list[Any] = []
        self.provider_effects = 0

    async def materialize(self, request: Any) -> EscrowResult:
        self.materialize_requests.append(request)
        if self.provider_effects == 0:
            self.provider_effects = 1
            raise HostedSettlementError(
                code="response_request_mismatch",
                message="client_secret=must-never-persist",
                retryable=False,
                status_code=200,
            )
        return self.escrow_result


def _obligation(
    *,
    funding_profile: FundingProfile = FundingProfile.CARD,
    include_authorization: bool = True,
    legacy: bool = False,
    **updates: Any,
) -> dict[str, Any]:
    params: dict[str, Any] = {
        "account_ref": "account-1",
        "payer_principal": BUYER.model_dump(mode="json"),
        "claimant_principal": SELLER.model_dump(mode="json"),
        "funds_flow": "separate_charges_transfers",
        "condition": {
            "protocol": "arkhai.condition.v1",
            "condition_id": "condition-1",
            "evaluator": {
                "kind": "builtin.v1",
                "version": "trivial.v1",
                "params": {"kind": "trivial"},
            },
            "demand": {"encoding": "application/jcs+json", "value": True},
        },
    }
    if legacy:
        params.update(
            {
                "payment_method_types": ["card"],
                "legacy_recovery": "hosted-card.v1",
            }
        )
    else:
        params.update(
            {
                "funding_profile": funding_profile.value,
                "authority_id": "hosted-authority-1",
                "environment": "test",
                "country": "US",
                "interaction": "interactive",
                "contract_fingerprint": "sha256:" + "11" * 32,
            }
        )
        if include_authorization:
            params["funding_authorization_ref"] = "funding-authorization-1"
    value = {
        "payer": "buyer",
        "claimant": "seller",
        "payer_principal": BUYER.model_dump(mode="json"),
        "claimant_principal": SELLER.model_dump(mode="json"),
        "amount": 1200,
        "asset": "usd",
        "expiration_unix": 2_000_003_600,
        "conditions": [],
        "mechanism": "fiat.stripe.v1",
        "params": params,
    }
    value.update(updates)
    return value


@pytest.mark.parametrize(
    ("identity", "signature"),
    [
        (BUYER, b"\x11" * 64),
        (EIP191, b"\x22" * 65),
    ],
)
def test_marketplace_signer_bridge_implements_the_released_client_interface(
    identity: Identity,
    signature: bytes,
) -> None:
    marketplace_signer = FakeMarketplaceSigner(identity, signature)
    bridge = MarketplaceSignerAdapter(marketplace_signer)

    assert bridge.principal == Principal.model_validate(
        identity.model_dump(mode="json")
    )
    assert bridge.sign(b"hosted canonical request") == signature
    assert marketplace_signer.messages == [b"hosted canonical request"]
    assert not hasattr(bridge, "private_key")


@pytest.mark.asyncio
async def test_conditional_adapter_instantiates_from_injected_signer() -> None:
    bridge = MarketplaceSignerAdapter(
        FakeMarketplaceSigner(BUYER, b"\x11" * 64)
    )
    hosted_client = HostedSettlementAsyncClient(
        ClientConfig(
            base_url="https://hosted.example",
            signer=bridge,
            caller_role="buyer",
            authority_id="hosted-authority",
            environment="test",
            expected_authorities=ExpectedAuthorities(
                principals=(
                    Principal.model_validate(SELLER.model_dump(mode="json")),
                )
            ),
        )
    )
    try:
        adapter = HostedConditionalEscrowClient(hosted_client)
        assert adapter is not None
    finally:
        await hosted_client.aclose()


@pytest.mark.asyncio
async def test_adapter_publishes_only_a_stable_fulfillment_digest() -> None:
    client = FakeClient()
    adapter = HostedConditionalEscrowClient(client)  # type: ignore[arg-type]

    first = await adapter.publish_fulfillment(
        condition_anchor="0x" + "66" * 32,
        evidence='{"connection_details":"ssh private@host"}',
    )
    first_request = client.publication_request
    second = await adapter.publish_fulfillment(
        condition_anchor="0x" + "66" * 32,
        evidence='{"connection_details":"ssh private@host"}',
    )

    assert first == second == "0x" + "99" * 32
    assert client.publication_request == first_request
    assert first_request.evidence_digest == (
        "sha256:"
        + hashlib.sha256(b'{"connection_details":"ssh private@host"}').hexdigest()
    )
    assert "private@host" not in first_request.model_dump_json()


@pytest.mark.asyncio
@pytest.mark.parametrize("funding_profile", tuple(FundingProfile))
async def test_adapter_produces_exact_released_client_requests(
    funding_profile: FundingProfile,
) -> None:
    client = FakeClient()
    client.escrow_result = client.escrow(funding_profile=funding_profile)
    adapter = HostedConditionalEscrowClient(client)  # type: ignore[arg-type]
    obligation = _obligation(funding_profile=funding_profile)
    accepted_obligation = _obligation(
        funding_profile=funding_profile,
        include_authorization=False,
    )

    result = await adapter.materialize(
        obligation,
        operation_ref="arkhai:settlement:obligation-1:materialize",
    )

    assert result.status == "requires_action"
    assert result.mechanism_ref == "escrow-public"
    assert result.buyer_action == {
        "kind": "payment",
        "operation_ref": "funding-action-1",
        "expires_at_unix": 2_000_000_100,
        "url": "https://checkout.example/secret-session",
        "bank_instructions": None,
    }
    assert client.materialize_request == CreateEscrowRequest(
        request_id="arkhai:settlement:obligation-1:materialize",
        obligation_ref="obligation-1",
        obligation_hash="0x" + obligation_payload_hash(accepted_obligation),
        payer=Principal.model_validate(BUYER.model_dump(mode="json")),
        claimant=Principal.model_validate(SELLER.model_dump(mode="json")),
        account_ref="account-1",
        amount=1200,
        currency="usd",
        expiration_unix=2_000_003_600,
        funding_profile=funding_profile,
        funding_authorization_ref="funding-authorization-1",
        marketplace_operation_id="obligation-1",
        condition=ConditionDescriptor.model_validate(
            obligation["params"]["condition"]
        ),
    )

    collected = await adapter.collect(
        obligation,
        mechanism_ref="escrow-public",
        fulfillment_ref="opaque-fulfillment",
        operation_ref="collect-1",
        mechanism_state={},
    )
    reclaimed = await adapter.reclaim_expired(
        obligation,
        mechanism_ref="escrow-public",
        operation_ref="reclaim-1",
        mechanism_state={},
    )
    assert collected.receipt["funding_profile"] == funding_profile.value
    assert reclaimed.receipt["funding_authorization_ref"] == (
        "funding-authorization-1"
    )
    assert client.collect_call == (
        "escrow-public",
        OperationRequest(request_id="collect-1"),
    )
    assert client.reclaim_call == (
        "escrow-public",
        OperationRequest(request_id="reclaim-1"),
    )

@pytest.mark.asyncio
async def test_runtime_never_persists_transient_action_material(tmp_path) -> None:
    client = FakeClient()
    adapter = HostedConditionalEscrowClient(client)  # type: ignore[arg-type]
    repository = SettlementSQLiteRepository(str(tmp_path / "hosted.db"))
    runtime = SettlementRuntime(
        repository,
        {"fiat.stripe.v1": adapter},
        clock=lambda: 2_000_000_000,
    )
    record = (
        await runtime.register_plan(
            agreement_ref="agreement-1",
            obligations=[_obligation(include_authorization=False)],
        )
    )[0]
    await runtime.bind_mechanism_params(
        record.obligation_ref,
        {
            "funding_profile": "card.v1",
            "funding_authorization_ref": "funding-authorization-1",
        },
        local_principal=BUYER,
    )

    await runtime.materialize(
        obligation_ref=record.obligation_ref,
        local_principal=BUYER,
        worker_id="buyer",
    )

    stored = await repository.load_settlement_obligation(record.obligation_ref)
    assert stored is not None
    assert stored["buyer_action"] == {
        "kind": "payment",
        "expires_at_unix": 2_000_000_100,
    }
    assert stored["mechanism_params"] == {
        "funding_profile": "card.v1",
        "funding_authorization_ref": "funding-authorization-1",
    }
    assert "checkout.example" not in json.dumps(stored, sort_keys=True)
    assert "bank_instructions" not in json.dumps(stored, sort_keys=True)
    assert (
        await adapter.get_buyer_action(
            "escrow-public",
            operation_ref="immediate-action",
        )
    )["url"] == "https://checkout.example/secret-session"


@pytest.mark.asyncio
@pytest.mark.parametrize("retryable", [False, True])
async def test_hosted_errors_are_redacted_and_retry_classified_in_sqlite(
    tmp_path,
    retryable: bool,
) -> None:
    canary = "sk_live_secret provider_payload customer_private"
    client = FailingMaterializeClient(
        HostedSettlementError(
            code="provider_failure",
            message=canary,
            retryable=retryable,
            status_code=503 if retryable else 409,
        )
    )
    adapter = HostedConditionalEscrowClient(client)  # type: ignore[arg-type]
    repository = SettlementSQLiteRepository(str(tmp_path / f"redacted-{retryable}.db"))
    runtime = SettlementRuntime(
        repository,
        {"fiat.stripe.v1": adapter},
        clock=lambda: 2_000_000_000,
    )
    record = (
        await runtime.register_plan(
            agreement_ref="agreement-redacted",
            obligations=[_obligation(include_authorization=False)],
        )
    )[0]
    await runtime.bind_mechanism_params(
        record.obligation_ref,
        {
            "funding_profile": "card.v1",
            "funding_authorization_ref": "funding-authorization-1",
        },
        local_principal=BUYER,
    )

    if retryable:
        with pytest.raises(
            RuntimeError,
            match="hosted settlement materialization temporarily unavailable",
        ):
            await runtime.materialize(
                obligation_ref=record.obligation_ref,
                local_principal=BUYER,
                worker_id="buyer",
            )
    else:
        outcome = await runtime.materialize(
            obligation_ref=record.obligation_ref,
            local_principal=BUYER,
            worker_id="buyer",
        )
        assert outcome.status == "manual_required"

    operation = await repository.load_settlement_operation(
        record.obligation_ref,
        "materialize",
    )
    assert operation is not None
    assert operation["state"] == ("pending" if retryable else "manual_required")
    assert operation["uncertain_acknowledgement"] is retryable
    serialized = json.dumps(operation, sort_keys=True)
    assert canary not in serialized
    assert "customer_private" not in serialized
    # The authority's own word for what it refused survives the redaction that
    # its message does not: an obligation parked for repair has to say why.
    assert "provider_failure" in serialized


@pytest.mark.asyncio
async def test_an_authority_refusal_names_itself_without_naming_the_provider() -> None:
    """The code is the authority's vocabulary; the message can be anything."""

    canary = "sk_live_secret declined by acct_1Example for card 4242"
    client = FailingMaterializeClient(
        HostedSettlementError(
            code="funding_profile_unsupported",
            message=canary,
            retryable=False,
            status_code=409,
        )
    )
    adapter = HostedConditionalEscrowClient(client)  # type: ignore[arg-type]

    with pytest.raises(SettlementManualRequired) as refused:
        await adapter.materialize(_obligation(), operation_ref="arkhai:settlement:obligation-1:materialize")

    assert "funding_profile_unsupported" in str(refused.value)
    assert canary not in str(refused.value)
    # The released client's traceback can carry request and response fragments.
    assert refused.value.__cause__ is None


@pytest.mark.asyncio
async def test_an_authority_that_does_not_speak_codes_is_not_repeated() -> None:
    """A free-text code is treated as the authority having named nothing."""

    client = FailingMaterializeClient(
        HostedSettlementError(
            code="card declined for customer cus_1Example",
            message="unused",
            retryable=False,
            status_code=409,
        )
    )
    adapter = HostedConditionalEscrowClient(client)  # type: ignore[arg-type]

    with pytest.raises(SettlementManualRequired) as refused:
        await adapter.materialize(_obligation(), operation_ref="arkhai:settlement:obligation-1:materialize")

    assert str(refused.value) == "hosted settlement materialization rejected"


@pytest.mark.asyncio
async def test_a_retryable_failure_names_its_code_too() -> None:
    """Retry classification is unchanged; only what it says is."""

    client = FailingMaterializeClient(
        HostedSettlementError(
            code="authority_unavailable",
            message="upstream timeout contacting acct_1Example",
            retryable=True,
            status_code=503,
        )
    )
    adapter = HostedConditionalEscrowClient(client)  # type: ignore[arg-type]

    with pytest.raises(RuntimeError) as unavailable:
        await adapter.materialize(_obligation(), operation_ref="arkhai:settlement:obligation-1:materialize")

    assert not isinstance(unavailable.value, SettlementManualRequired)
    assert "authority_unavailable" in str(unavailable.value)
    assert "acct_1Example" not in str(unavailable.value)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("operation", "safe_name"),
    [
        ("status", "status"),
        ("collect", "collection"),
        ("reclaim", "reclaim"),
    ],
)
async def test_every_hosted_lifecycle_error_discards_provider_detail(
    operation: str,
    safe_name: str,
) -> None:
    canary = "client_secret=secret provider_object=private"
    client = FailingMaterializeClient(
        HostedSettlementError(
            code="temporarily_unavailable",
            message=canary,
            retryable=True,
            status_code=503,
        )
    )
    adapter = HostedConditionalEscrowClient(client)  # type: ignore[arg-type]
    obligation = _obligation()

    with pytest.raises(
        RuntimeError,
        match=f"hosted settlement {safe_name} temporarily unavailable",
    ) as caught:
        if operation == "status":
            await adapter.get_status(
                obligation,
                mechanism_ref="escrow-public",
                operation_ref="status-1",
                mechanism_state={},
            )
        elif operation == "collect":
            await adapter.collect(
                obligation,
                mechanism_ref="escrow-public",
                fulfillment_ref="fulfillment-public",
                operation_ref="collect-1",
                mechanism_state={},
            )
        else:
            await adapter.reclaim_expired(
                obligation,
                mechanism_ref="escrow-public",
                operation_ref="reclaim-1",
                mechanism_state={},
            )

    assert canary not in str(caught.value)
    assert "client_secret" not in str(caught.value)




@pytest.mark.asyncio
async def test_commit_then_invalid_response_retries_exact_identity_once(tmp_path) -> None:
    client = CommitThenInvalidResponseClient()
    adapter = HostedConditionalEscrowClient(client)  # type: ignore[arg-type]
    repository = SettlementSQLiteRepository(str(tmp_path / "commit-then-invalid.db"))
    runtime = SettlementRuntime(
        repository,
        {"fiat.stripe.v1": adapter},
        clock=lambda: 2_000_000_000,
    )
    record = (
        await runtime.register_plan(
            agreement_ref="agreement-unknown-ack",
            obligations=[_obligation(include_authorization=False)],
        )
    )[0]
    await runtime.bind_mechanism_params(
        record.obligation_ref,
        {
            "funding_profile": "card.v1",
            "funding_authorization_ref": "funding-authorization-1",
        },
        local_principal=BUYER,
    )

    with pytest.raises(
        RuntimeError,
        match="hosted settlement materialization temporarily unavailable",
    ):
        await runtime.materialize(
            obligation_ref=record.obligation_ref,
            local_principal=BUYER,
            worker_id="buyer-first",
        )
    first_operation = await repository.load_settlement_operation(
        record.obligation_ref,
        "materialize",
    )
    assert first_operation is not None
    assert first_operation["uncertain_acknowledgement"] is True

    recovered = await runtime.materialize(
        obligation_ref=record.obligation_ref,
        local_principal=BUYER,
        worker_id="buyer-recovery",
    )

    assert recovered.status == "pending"
    assert client.provider_effects == 1
    assert len(client.materialize_requests) == 2
    assert client.materialize_requests[0] == client.materialize_requests[1]
    stored = await repository.load_settlement_operation(
        record.obligation_ref,
        "materialize",
    )
    assert stored is not None
    assert stored["uncertain_acknowledgement"] is False
    assert "client_secret" not in json.dumps(stored, sort_keys=True)
@pytest.mark.asyncio
async def test_readiness_fails_on_identity_capability_drift() -> None:
    client = FakeClient()
    client.health_result = client.health_result.model_copy(
        update={
            "capabilities": tuple(
                capability
                for capability in client.health_result.capabilities
                if capability != "scheme-tagged-identities.v1"
            )
        }
    )
    adapter = HostedConditionalEscrowClient(client)  # type: ignore[arg-type]

    with pytest.raises(
        ValueError,
        match="scheme-tagged-identities.v1",
    ):
        await adapter.verify_contract_ready(
            expected_manifest_digest="sha256:" + "aa" * 32,
            expected_contract_version="0.2.1",
            expected_schema_version=5,
            required_capabilities=(),
            operation_ref="publication",
        )


@pytest.mark.parametrize(
    ("protocol_name", "legacy_version"),
    [
        ("REQUEST_PROTOCOL", "arkhai.hosted-request-signature.v1"),
        ("RESPONSE_PROTOCOL", "arkhai.hosted-response-signature.v1"),
    ],
)
def test_adapter_rejects_a_client_without_identity_v2(
    monkeypatch,
    protocol_name: str,
    legacy_version: str,
) -> None:
    monkeypatch.setattr(adapter_module, protocol_name, legacy_version)
    with pytest.raises(ValueError, match="identity v2"):
        HostedConditionalEscrowClient(FakeClient())  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "updates, message",
    [
        ({"amount": 0}, "positive integer"),
        ({"asset": "USD"}, "lowercase ISO 4217"),
        ({"payer": "seller"}, "buyer-funded"),
        ({"mechanism": "alkahest.v1"}, "requires mechanism"),
        (
            {"payer_principal": EIP191.model_dump(mode="json")},
            "payer principal does not match",
        ),
    ],
)
@pytest.mark.asyncio
async def test_adapter_rejects_invalid_hosted_obligation(
    updates: dict[str, Any],
    message: str,
) -> None:
    adapter = HostedConditionalEscrowClient(FakeClient())  # type: ignore[arg-type]
    with pytest.raises(ValueError, match=message):
        await adapter.materialize(
            _obligation(**updates),
            operation_ref="arkhai:settlement:obligation-1:materialize",
        )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("funding_state", "financial_state", "expected"),
    [
        (NormalizedFundingState.AWAITING_EXTERNAL, FinancialState.AWAITING_PAYMENT, "pending"),
        (NormalizedFundingState.ACTION_REQUIRED, FinancialState.AWAITING_PAYMENT, "requires_action"),
        (NormalizedFundingState.SUCCEEDED_UNAVAILABLE, FinancialState.FUNDED, "pending"),
        (NormalizedFundingState.AVAILABLE, FinancialState.FUNDED, "ready"),
        (NormalizedFundingState.RETURNED, FinancialState.FUNDED, "failed"),
        (NormalizedFundingState.AMBIGUOUS, FinancialState.FUNDED, "manual_required"),
        (NormalizedFundingState.TRANSFERRED, FinancialState.COLLECTED, "collected"),
    ],
)
async def test_adapter_maps_authoritative_funding_states(
    funding_state: NormalizedFundingState,
    financial_state: FinancialState,
    expected: str,
) -> None:
    client = FakeClient()
    client.escrow_result = client.escrow(
        funding_state=funding_state,
        financial_state=financial_state,
        action=(
            client.escrow_result.action
            if funding_state == NormalizedFundingState.ACTION_REQUIRED
            else None
        ),
    )
    adapter = HostedConditionalEscrowClient(client)  # type: ignore[arg-type]

    status = await adapter.get_status(
        _obligation(),
        mechanism_ref="escrow-public",
        operation_ref="status",
        mechanism_state={},
    )

    assert status.status == expected
    assert status.mechanism_state["funding_state"] == funding_state.value
    assert status.receipt is not None
    assert status.receipt["funding_reason"] == "payer_action_required"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("funding_state", "financial_state", "expected"),
    [
        (
            NormalizedFundingState.RETURNED,
            FinancialState.FUNDED,
            "manual_required",
        ),
        (
            NormalizedFundingState.FAILED,
            FinancialState.FUNDED,
            "manual_required",
        ),
        (
            NormalizedFundingState.EXPIRED,
            FinancialState.EXPIRED,
            "collected",
        ),
    ],
)
async def test_post_collection_regression_fails_safe_without_rewriting_completion(
    funding_state,
    financial_state,
    expected,
) -> None:
    client = FakeClient()
    client.escrow_result = client.escrow(
        funding_state=funding_state,
        financial_state=financial_state,
        action=None,
    )
    adapter = HostedConditionalEscrowClient(client)  # type: ignore[arg-type]

    status = await adapter.get_status(
        _obligation(),
        mechanism_ref="escrow-public",
        operation_ref="status",
        mechanism_state={
            "financial_state": FinancialState.COLLECTED.value,
            "funding_state": NormalizedFundingState.TRANSFERRED.value,
        },
    )

    assert status.status == expected
    assert status.mechanism_state["financial_state"] == financial_state.value


@pytest.mark.asyncio
async def test_adapter_preserves_available_state_across_delayed_visibility() -> None:
    client = FakeClient()
    client.escrow_result = client.escrow(
        funding_state=NormalizedFundingState.AWAITING_EXTERNAL,
        action=None,
    )
    adapter = HostedConditionalEscrowClient(client)  # type: ignore[arg-type]
    client.escrow_result = client.escrow(
        funding_profile=FundingProfile.US_ACH_DEBIT,
        funding_state=NormalizedFundingState.AWAITING_EXTERNAL,
        action=None,
    )

    status = await adapter.get_status(
        _obligation(funding_profile=FundingProfile.US_ACH_DEBIT),
        mechanism_ref="escrow-public",
        operation_ref="status",
        mechanism_state={
            "financial_state": FinancialState.FUNDED.value,
            "funding_state": NormalizedFundingState.AVAILABLE.value,
        },
    )

    assert status.status == "ready"


@pytest.mark.asyncio
async def test_legacy_card_decoder_is_recovery_only() -> None:
    client = FakeClient()
    adapter = HostedConditionalEscrowClient(client)  # type: ignore[arg-type]
    legacy = _obligation(legacy=True)

    with pytest.raises(ValueError, match="recovery-only"):
        await adapter.materialize(
            legacy,
            operation_ref="arkhai:settlement:legacy-obligation:materialize",
        )
    status = await adapter.get_status(
        legacy,
        mechanism_ref="historical-settlement",
        operation_ref="historical-status",
        mechanism_state={"legacy_recovery": "hosted-card.v1"},
    )

    assert status.receipt is not None
    assert status.receipt["legacy_recovery"] == "hosted-card.v1"
    assert "funding_profile" not in status.receipt
    assert "funding_authorization_ref" not in status.receipt


@pytest.mark.asyncio
async def test_a_parked_obligation_projects_the_reason_it_was_parked_for(
    tmp_path,
) -> None:
    """manual_required is a request for human action; it owes a reason."""

    client = FailingMaterializeClient(
        HostedSettlementError(
            code="funding_profile_unsupported",
            message="sk_live_secret acct_1Example rejected 4242",
            retryable=False,
            status_code=409,
        )
    )
    adapter = HostedConditionalEscrowClient(client)  # type: ignore[arg-type]
    repository = SettlementSQLiteRepository(str(tmp_path / "parked.db"))
    runtime = SettlementRuntime(
        repository,
        {"fiat.stripe.v1": adapter},
        clock=lambda: 2_000_000_000,
    )
    record = (
        await runtime.register_plan(
            agreement_ref="agreement-parked",
            obligations=[_obligation(include_authorization=False)],
        )
    )[0]
    await runtime.bind_mechanism_params(
        record.obligation_ref,
        {
            "funding_profile": "card.v1",
            "funding_authorization_ref": "funding-authorization-1",
        },
        local_principal=BUYER,
    )

    outcome = await runtime.materialize(
        obligation_ref=record.obligation_ref,
        local_principal=BUYER,
        worker_id="buyer",
    )
    assert outcome.status == "manual_required"

    parked = await repository.load_settlement_obligation(record.obligation_ref)
    assert parked is not None
    reason = hosted_projected_reason(None, parked["mechanism_state"])
    assert reason == "funding_profile_unsupported"
    # The mechanism state a projection reads carries the code and nothing the
    # authority said around it.
    serialized = json.dumps(parked["mechanism_state"], sort_keys=True)
    assert "sk_live_secret" not in serialized
    assert "acct_1Example" not in serialized


def test_the_reason_prefers_what_the_obligation_is_currently_doing() -> None:
    """A funding reason outranks a parking reason it has moved on from."""

    assert hosted_projected_reason({"funding_reason": "awaiting_payment"}, {}) == (
        "awaiting_payment"
    )
    assert hosted_projected_reason(None, {"funding_reason": "processing"}) == "processing"
    assert hosted_projected_reason(None, {"manual_reason": "condition_rejected"}) == (
        "condition_rejected"
    )
    assert hosted_projected_reason(None, None) is None
    # A parked obligation that reached its state before this existed reports
    # nothing rather than an invented reason.
    assert hosted_projected_reason({}, {"manual_reason": ""}) is None
