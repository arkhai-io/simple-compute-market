from __future__ import annotations

import hashlib
import json
from typing import Any

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
    HostedSettlementAsyncClient,
    ManifestHealth,
    OperationReceipt,
    OperationRequest,
    Principal,
    canonical_json,
)
from market_identity import Identity, IdentityScheme
from market_settlement_runtime import (
    SettlementRuntime,
    SettlementSQLiteRepository,
)

import market_hosted_settlement.adapter as adapter_module
from market_hosted_settlement import (
    HostedConditionalEscrowClient,
    MarketplaceSignerAdapter,
    REQUIRED_HOSTED_CAPABILITIES,
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
        self.status_call: tuple[str, str] | None = None
        self.collect_call: tuple[str, OperationRequest] | None = None
        self.reclaim_call: tuple[str, OperationRequest] | None = None
        self.health_result = ManifestHealth(
            ready=True,
            manifest_digest="sha256:" + "aa" * 32,
            schema_version=4,
            capabilities=tuple(sorted(REQUIRED_HOSTED_CAPABILITIES)),
        )

    @staticmethod
    def escrow() -> EscrowResult:
        return EscrowResult(
            escrow_ref="escrow-public",
            financial_state=FinancialState.AWAITING_PAYMENT,
            condition_state=ConditionState.PENDING,
            action=BuyerAction(
                url="https://checkout.example/secret-session",
                expires_at_unix=2_000_000_100,
            ),
            condition_anchor="0x" + "66" * 32,
            expiration_unix=2_000_003_600,
        )

    async def health(self, *, request_id: str) -> ManifestHealth:
        return self.health_result

    async def account_readiness(
        self, account_ref: str, *, request_id: str
    ) -> AccountReadiness:
        return AccountReadiness(
            account_ref=account_ref,
            ready=True,
            capabilities=("transfers",),
        )

    async def materialize(self, request: Any) -> EscrowResult:
        self.materialize_request = request
        return self.escrow()

    async def get_status(self, escrow_ref: str, *, request_id: str) -> EscrowResult:
        self.status_call = (escrow_ref, request_id)
        return self.escrow()

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


def _obligation(**updates: Any) -> dict[str, Any]:
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
        "params": {
            "account_ref": "account-1",
            "payer_principal": BUYER.model_dump(mode="json"),
            "claimant_principal": SELLER.model_dump(mode="json"),
            "funds_flow": "separate_charges_transfers",
            "payment_method_types": ["card"],
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
        },
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
async def test_adapter_produces_exact_released_client_requests() -> None:
    client = FakeClient()
    adapter = HostedConditionalEscrowClient(client)  # type: ignore[arg-type]
    obligation = _obligation()

    result = await adapter.materialize(
        obligation,
        operation_ref="arkhai:settlement:obligation-1:materialize",
    )

    assert result.status == "requires_action"
    assert result.mechanism_ref == "escrow-public"
    assert result.buyer_action == {
        "kind": "redirect",
        "expires_at_unix": 2_000_000_100,
    }
    assert client.materialize_request == CreateEscrowRequest(
        request_id="arkhai:settlement:obligation-1:materialize",
        obligation_ref="obligation-1",
        obligation_hash="0x"
        + hashlib.sha256(canonical_json(obligation)).hexdigest(),
        payer=Principal.model_validate(BUYER.model_dump(mode="json")),
        claimant=Principal.model_validate(SELLER.model_dump(mode="json")),
        account_ref="account-1",
        amount=1200,
        currency="usd",
        expiration_unix=2_000_003_600,
        condition=ConditionDescriptor.model_validate(
            obligation["params"]["condition"]
        ),
    )

    await adapter.collect(
        obligation,
        mechanism_ref="escrow-public",
        fulfillment_ref="opaque-fulfillment",
        operation_ref="collect-1",
        mechanism_state={},
    )
    await adapter.reclaim_expired(
        obligation,
        mechanism_ref="escrow-public",
        operation_ref="reclaim-1",
        mechanism_state={},
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
async def test_runtime_never_persists_checkout_url(tmp_path) -> None:
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
            obligations=[_obligation()],
        )
    )[0]

    await runtime.materialize(
        obligation_ref=record.obligation_ref,
        local_principal=BUYER,
        worker_id="buyer",
    )

    stored = await repository.load_settlement_obligation(record.obligation_ref)
    assert stored is not None
    assert stored["buyer_action"] == {
        "kind": "redirect",
        "expires_at_unix": 2_000_000_100,
    }
    assert "checkout.example" not in json.dumps(stored, sort_keys=True)
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
            expected_contract_version="0.1.0",
            expected_schema_version=4,
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
