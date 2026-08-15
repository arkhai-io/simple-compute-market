from __future__ import annotations

import pytest
from hosted_settlement_client import (
    FundingProfile,
    InstrumentKind,
    InstrumentListResult,
    InstrumentProjection,
    InstrumentReadiness,
    PayerAction,
    PayerActionKind,
    PayerProfileResult,
    PayerProfileState,
    PayerSetupResult,
    Principal,
    verify_payer_owner_rotation,
    verify_payer_profile_creation,
)
from market_hosted_settlement import (
    HostedPayerError,
    HostedPayerFacade,
    MarketplaceSignerAdapter,
    instrument_list_projection,
    payer_setup_projection,
)
from market_identity import Ed25519Signer


class Client:
    def __init__(self, principal: Principal) -> None:
        self.principal = principal
        self.requests = []
        self.failure: Exception | None = None

    async def _result(self, request):
        self.requests.append(request)
        if self.failure is not None:
            raise self.failure
        return request

    async def create_payer_profile(self, request):
        await self._result(request)
        return PayerProfileResult(
            payer_profile_ref="payer_opaque_1234",
            primary_principal=request.principal,
            state=PayerProfileState.ACTIVE,
            version=1,
        )

    async def rotate_payer_owner(self, request):
        await self._result(request)
        return PayerProfileResult(
            payer_profile_ref=request.payer_profile_ref,
            primary_principal=request.new_principal,
            state=PayerProfileState.ACTIVE,
            version=2,
        )

    async def start_payer_setup(self, request):
        await self._result(request)
        return PayerSetupResult(
            setup_ref="setup_opaque_1234",
            readiness=InstrumentReadiness.REQUIRES_ACTION,
            action=PayerAction(
                kind=PayerActionKind.SETUP,
                operation_ref="operation_opaque_1234",
                expires_at_unix=2_000_000_000,
                url="https://transient.example/secret-action",
            ),
        )


def _facade(seed: bytes = b"a" * 32) -> tuple[HostedPayerFacade, Client, Ed25519Signer]:
    signer = Ed25519Signer(seed)
    client = Client(MarketplaceSignerAdapter(signer).principal)
    return (
        HostedPayerFacade(
            client=client,
            signer=signer,
            authority_id="authority-main",
            environment="production",
        ),
        client,
        signer,
    )


@pytest.mark.asyncio
async def test_profile_creation_uses_released_dual_scheme_signing_helper() -> None:
    facade, client, signer = _facade()
    first = await facade.create(country="US")
    second = await facade.create(country="US")
    assert first.payer_profile_ref == "payer_opaque_1234"
    assert client.requests[0] == client.requests[1]
    assert client.requests[0].principal == MarketplaceSignerAdapter(signer).principal
    verify_payer_profile_creation(
        client.requests[0],
        authority_id="authority-main",
        environment="production",
    )


@pytest.mark.asyncio
async def test_owner_rotation_contains_both_exact_proofs() -> None:
    facade, client, _old = _facade()
    replacement = Ed25519Signer(b"b" * 32)
    result = await facade.rotate_owner(
        payer_profile_ref="payer_opaque_1234",
        new_signer=replacement,
        nonce="rotation-nonce",
        overlap_until_unix=1_900_000_000,
        valid_until_unix=2_000_000_000,
    )
    rotation = client.requests[0]
    verify_payer_owner_rotation(
        rotation,
        authority_id="authority-main",
        environment="production",
        now_unix=1_800_000_000,
    )
    assert result.primary_principal == MarketplaceSignerAdapter(replacement).principal


@pytest.mark.asyncio
async def test_setup_action_is_transient_and_safe_projection_is_redacted() -> None:
    facade, _client, _signer = _facade()
    result = await facade.start_setup(
        payer_profile_ref="payer_opaque_1234",
        funding_profile=FundingProfile.CARD,
        label="main card",
    )
    projection = payer_setup_projection(result)
    encoded = str(projection)
    assert projection == {
        "setup_ref": "setup_opaque_1234",
        "readiness": "requires_action",
        "action": {
            "kind": "setup",
            "expires_at_unix": 2_000_000_000,
        },
    }
    assert "transient.example" not in encoded
    assert "secret-action" not in encoded


@pytest.mark.asyncio
async def test_remote_failures_do_not_echo_provider_or_action_material() -> None:
    facade, client, _signer = _facade()
    client.failure = RuntimeError(
        "cus_secret pm_secret https://transient.example/secret-action"
    )
    with pytest.raises(HostedPayerError) as error:
        await facade.create(country="US")
    message = str(error.value)
    assert message == "hosted payer create failed"
    assert "cus_secret" not in message
    assert "pm_secret" not in message
    assert "transient" not in message


def test_instrument_projection_is_exact_and_provider_neutral() -> None:
    result = InstrumentListResult(
        payer_profile_ref="payer_opaque_1234",
        instruments=(
            InstrumentProjection(
                instrument_ref="instrument_opaque_1234",
                label="main card",
                kind=InstrumentKind.CARD,
                readiness=InstrumentReadiness.READY,
                is_default=True,
                revoked=False,
            ),
        ),
    )
    assert instrument_list_projection(result) == {
        "payer_profile_ref": "payer_opaque_1234",
        "instruments": [
            {
                "instrument_ref": "instrument_opaque_1234",
                "label": "main card",
                "kind": "card",
                "readiness": "ready",
                "is_default": True,
                "revoked": False,
            }
        ],
    }
