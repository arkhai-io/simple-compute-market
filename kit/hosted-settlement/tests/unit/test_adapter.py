from __future__ import annotations

import hashlib
import json
from typing import Any

import market_hosted_settlement.adapter as adapter_module
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
    ManifestHealth,
    NormalizedFundingState,
    OperationReceipt,
    OperationRequest,
    PayerActionKind,
    Principal,
    canonical_json,
)
from market_hosted_settlement import (
    REQUIRED_HOSTED_CAPABILITIES,
    HostedConditionalEscrowClient,
    MarketplaceSignerAdapter,
)
from market_identity import Identity, IdentityScheme
from market_settlement_runtime import (
    SettlementRuntime,
    SettlementSQLiteRepository,
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
        params["funding_profile"] = funding_profile.value
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
        "expires_at_unix": 2_000_000_100,
    }
    assert client.materialize_request == CreateEscrowRequest(
        request_id="arkhai:settlement:obligation-1:materialize",
        obligation_ref="obligation-1",
        obligation_hash="0x"
        + hashlib.sha256(canonical_json(accepted_obligation)).hexdigest(),
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
            expected_contract_version="0.2.0",
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
