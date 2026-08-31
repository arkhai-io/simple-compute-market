from __future__ import annotations

import pytest
from hosted_settlement_client import (
    FundingProfile,
    HostedSettlementError,
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
    DIRECT_INSTRUMENT_SETUP_CAPABILITY,
    HostedPayerError,
    HostedPayerFacade,
    MarketplaceSignerAdapter,
    StripeSettlementConfig,
    instrument_list_projection,
    payer_command_context_from_config,
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

    async def verify_payer_setup(self, request):
        await self._result(request)
        return PayerSetupResult(
            setup_ref=request.setup_ref,
            readiness=InstrumentReadiness.READY,
        )


def _facade(
    seed: bytes = b"a" * 32,
    *,
    capabilities: tuple[str, ...] = (DIRECT_INSTRUMENT_SETUP_CAPABILITY,),
) -> tuple[HostedPayerFacade, Client, Ed25519Signer]:
    signer = Ed25519Signer(seed)
    client = Client(MarketplaceSignerAdapter(signer).principal)
    return (
        HostedPayerFacade(
            client=client,
            signer=signer,
            authority_id="authority-main",
            environment="production",
            capabilities=capabilities,
        ),
        client,
        signer,
    )


def test_configured_payer_client_uses_authority_payer_role(monkeypatch) -> None:
    captured = []

    class CapturingClient:
        def __init__(self, config) -> None:
            captured.append(config)

    monkeypatch.setattr(
        "market_hosted_settlement.payer.HostedSettlementAsyncClient",
        CapturingClient,
    )
    context = payer_command_context_from_config(
        StripeSettlementConfig(
            enabled=True,
            base_url="https://settlement.example",
            authority_id="authority-main",
            environment="production",
            authority={
                "principals": [
                    {
                        "scheme": "ed25519",
                        "identifier": MarketplaceSignerAdapter(
                            Ed25519Signer(b"b" * 32)
                        ).principal.identifier,
                    }
                ]
            },
        ),
        profiles=object(),
        dispatch_action=lambda _action, _binding: None,
    )

    context.facade(Ed25519Signer(b"a" * 32))

    assert len(captured) == 1
    assert captured[0].caller_role == "payer"


@pytest.mark.asyncio
async def test_profile_creation_uses_released_dual_scheme_signing_helper() -> None:
    facade, client, signer = _facade()
    first = await facade.create(country="US")
    second = await facade.create(country="US")
    assert first.payer_profile_ref == "payer_opaque_1234"
    assert second == first
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


@pytest.mark.asyncio
async def test_a_payer_refusal_keeps_the_authority_name_for_it() -> None:
    """A refusal that says only "failed" cannot be repaired by whoever hit it.

    The authority's code is a bounded identifier, not provider text, so it is
    the one part of the refusal that is both safe to keep and worth keeping.
    """

    from market_hosted_settlement.payer import HostedPayerError, HostedPayerFacade

    facade = object.__new__(HostedPayerFacade)

    async def refuse() -> None:
        raise HostedSettlementError(
            code="setup_provider_unavailable",
            message="provider text that stays redacted",
            retryable=False,
            status_code=503,
        )

    with pytest.raises(HostedPayerError) as caught:
        await facade._remote("setup start", refuse)

    assert caught.value.code == "setup_provider_unavailable"
    assert "setup_provider_unavailable" in str(caught.value)
    assert "provider text" not in str(caught.value)


@pytest.mark.asyncio
async def test_a_payer_refusal_repeats_no_vocabulary_but_the_authority_own() -> None:
    from market_hosted_settlement.payer import HostedPayerError, HostedPayerFacade

    facade = object.__new__(HostedPayerFacade)

    async def refuse() -> None:
        raise HostedSettlementError(
            code="Not A Code",
            message="unused",
            retryable=False,
            status_code=503,
        )

    with pytest.raises(HostedPayerError) as caught:
        await facade._remote("setup start", refuse)

    assert caught.value.code == ""
    assert str(caught.value) == "hosted payer setup start failed"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "evidence",
    [{"amounts": (32, 45)}, {"descriptor_code": "SM11AA"}],
)
async def test_a_payer_submits_one_form_of_its_own_verification_evidence(
    evidence: dict[str, object],
) -> None:
    facade, client, _signer = _facade()

    result = await facade.verify_setup(
        payer_profile_ref="payer_opaque_1234",
        setup_ref="setup_opaque_1234",
        **evidence,
    )

    assert result.readiness is InstrumentReadiness.READY
    assert len(client.requests) == 1
    submitted = client.requests[0]
    assert submitted.payer_profile_ref == "payer_opaque_1234"
    assert submitted.setup_ref == "setup_opaque_1234"
    assert submitted.protocol == "arkhai.payer-setup-verification.v1"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "evidence",
    [{}, {"amounts": (32, 45), "descriptor_code": "SM11AA"}],
)
async def test_verification_carrying_both_or_neither_never_reaches_the_authority(
    evidence: dict[str, object],
) -> None:
    """The two are alternative accounts of one deposit, so both says nothing."""

    facade, client, _signer = _facade()

    with pytest.raises(HostedPayerError, match="exactly one"):
        await facade.verify_setup(
            payer_profile_ref="payer_opaque_1234",
            setup_ref="setup_opaque_1234",
            **evidence,
        )

    assert client.requests == []


@pytest.mark.asyncio
async def test_a_release_that_does_not_declare_direct_setup_names_the_prerequisite() -> (
    None
):
    """An absent capability is a prerequisite, not a call that failed obscurely."""

    facade, client, _signer = _facade(capabilities=("payer-profile.v1",))

    with pytest.raises(HostedPayerError) as refused:
        await facade.verify_setup(
            payer_profile_ref="payer_opaque_1234",
            setup_ref="setup_opaque_1234",
            amounts=(32, 45),
        )

    assert DIRECT_INSTRUMENT_SETUP_CAPABILITY in str(refused.value)
    assert refused.value.code == "capability_unavailable"
    assert client.requests == []


@pytest.mark.asyncio
async def test_a_verified_setup_projects_readiness_and_no_evidence() -> None:
    facade, _client, _signer = _facade()

    result = await facade.verify_setup(
        payer_profile_ref="payer_opaque_1234",
        setup_ref="setup_opaque_1234",
        descriptor_code="SM11AA",
    )
    projection = payer_setup_projection(result)

    assert projection == {"setup_ref": "setup_opaque_1234", "readiness": "ready"}
    assert "SM11AA" not in repr(projection)


def test_a_setup_awaiting_payer_verification_projects_as_pending_not_revoked() -> None:
    """Not ready, and not reported as something that went wrong."""

    projection = payer_setup_projection(
        PayerSetupResult(
            setup_ref="setup_opaque_1234",
            readiness=InstrumentReadiness.VERIFICATION_PENDING,
        )
    )

    assert projection == {
        "setup_ref": "setup_opaque_1234",
        "readiness": "verification_pending",
    }
