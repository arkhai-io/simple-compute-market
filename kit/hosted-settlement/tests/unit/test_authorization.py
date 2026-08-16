from __future__ import annotations

from types import SimpleNamespace

import pytest
import market_hosted_settlement.authorization as authorization_module
from hosted_settlement_client import (
    FundingAuthorizationResult,
    FundingMode,
    FundingProfile,
    HostedSettlementError,
    InstrumentKind,
    InstrumentListResult,
    InstrumentProjection,
    InstrumentReadiness,
    PayerProfileResult,
    PayerProfileState,
)
from market_hosted_settlement import (
    REQUIRED_STRIPE_CAPABILITIES,
    AuthorizationReservationJournal,
    FundingSelection,
    HostedAuthorizationError,
    HostedFundingAuthorizer,
    MarketplaceSignerAdapter,
    OffSessionPolicy,
    ReservationState,
    StripeSettlementConfig,
    stripe_contract_fingerprint,
    payer_compatibility_context,
    derive_accepted_funding_authorization,
)
from market_identity import (
    AuthorityBindingState,
    AuthorityPayerBinding,
    Ed25519Signer,
)
from market_settlement_runtime import obligation_payload_hash


SIGNER = Ed25519Signer(bytes(range(32)))
SELLER = Ed25519Signer(bytes(reversed(range(32)))).identity
AUTHORITY = Ed25519Signer(b"a" * 32).identity


def _config(**updates) -> StripeSettlementConfig:
    payload = {
        "enabled": True,
        "base_url": "https://settlement.example",
        "authority_id": "authority-main",
        "environment": "production",
        "authority": {"principals": [AUTHORITY.model_dump(mode="json")]},
        "expected_manifest_digest": "sha256:" + "ab" * 32,
    }
    payload.update(updates)
    return StripeSettlementConfig.model_validate(payload)


def _obligation(profile: FundingProfile = FundingProfile.CARD) -> dict:
    return {
        "payer": "buyer",
        "claimant": "seller",
        "payer_principal": SIGNER.identity.model_dump(mode="json"),
        "claimant_principal": SELLER.model_dump(mode="json"),
        "amount": "60",
        "asset": "usd",
        "expiration_unix": 2000,
        "conditions": [],
        "mechanism": "fiat.stripe.v1",
        "params": {
            "account_ref": "seller-account",
            "authority_id": "authority-main",
            "payer_principal": MarketplaceSignerAdapter(SIGNER).principal.model_dump(
                mode="json"
            ),
            "claimant_principal": MarketplaceSignerAdapter(
                Ed25519Signer(bytes(reversed(range(32))))
            ).principal.model_dump(mode="json"),
            "country": "US",
            "environment": "production",
            "funds_flow": "separate_charges_transfers",
            "funding_profile": profile.value,
            "interaction": "saved_instrument",
            "contract_fingerprint": stripe_contract_fingerprint(_config()),
            "condition": {
                "condition_id": "vm",
                "evaluator": {"kind": "builtin.v1", "version": "v1", "params": {}},
                "demand": {"encoding": "application/jcs+json", "value": {}},
            },
        },
    }


def _accepted(profile: FundingProfile = FundingProfile.CARD):
    return derive_accepted_funding_authorization(
        obligation_ref="a" * 64,
        obligation=_obligation(profile),
    )


def _binding() -> AuthorityPayerBinding:
    return AuthorityPayerBinding(
        authority_id="authority-main",
        environment="production",
        binding_ref="payer-opaque-1234",
        bound_principal=SIGNER.identity,
    )


class Client:
    def __init__(self, *, authorization_error: HostedSettlementError | None = None):
        self.calls: list[str] = []
        self.authorization_error = authorization_error
        self.request = None

    async def health(self, *, request_id: str):
        self.calls.append("health")
        return SimpleNamespace(
            ready=True,
            manifest_digest="sha256:" + "ab" * 32,
            api_version="0.2.1",
            schema_version=5,
            payer_profile_protocol="arkhai.payer-profile.v1",
            funding_authorization_protocol="arkhai.funding-authorization.v1",
            funding_profile_protocol="arkhai.funding-profile.v1",
            capabilities=REQUIRED_STRIPE_CAPABILITIES,
            funding_profiles=tuple(
                SimpleNamespace(profile=profile, ready=True)
                for profile in FundingProfile
            ),
        )

    async def show_payer_profile(self, payer_profile_ref: str, *, request_id: str):
        self.calls.append("show")
        return PayerProfileResult(
            payer_profile_ref=payer_profile_ref,
            primary_principal=MarketplaceSignerAdapter(SIGNER).principal,
            state=PayerProfileState.ACTIVE,
            version=1,
        )

    async def list_payer_instruments(self, payer_profile_ref: str, *, request_id: str):
        self.calls.append("instruments")
        return InstrumentListResult(
            payer_profile_ref=payer_profile_ref,
            instruments=(
                InstrumentProjection(
                    instrument_ref="instrument-opaque-1",
                    label="primary",
                    kind=InstrumentKind.CARD,
                    readiness=InstrumentReadiness.READY,
                    is_default=True,
                    revoked=False,
                ),
            ),
        )

    async def authorize_funding(self, request):
        self.calls.append("authorize")
        self.request = request
        if self.authorization_error is not None:
            raise self.authorization_error
        return FundingAuthorizationResult(
            funding_authorization_ref="funding-auth-safe-1",
            expires_at_unix=request.expires_at_unix,
        )


def test_derivation_uses_marketplace_obligation_hash_and_safe_receipt() -> None:
    obligation = _obligation()
    accepted = derive_accepted_funding_authorization(
        obligation_ref="a" * 64,
        obligation=obligation,
    )
    assert accepted.obligation_hash == "0x" + obligation_payload_hash(obligation)
    assert accepted.marketplace_operation_id == "a" * 64
    assert accepted.amount == 60
    assert accepted.authority_id == "authority-main"
    assert accepted.environment == "production"
    assert accepted.country == "US"


def test_derivation_rejects_inconsistent_payer_parameter() -> None:
    obligation = _obligation()
    obligation["params"]["payer_principal"] = MarketplaceSignerAdapter(
        Ed25519Signer(b"\x44" * 32)
    ).principal.model_dump(mode="json")

    with pytest.raises(ValueError, match="payer principal is inconsistent"):
        derive_accepted_funding_authorization(
            obligation_ref="a" * 64,
            obligation=obligation,
        )


@pytest.mark.asyncio
async def test_exact_saved_authorization_revalidates_once_and_signs_released_model() -> None:
    client = Client()
    selection = FundingSelection(
        FundingMode.SAVED_INSTRUMENT,
        "instrument-opaque-1",
    )
    receipt = await HostedFundingAuthorizer(
        config=_config(), client=client, signer=SIGNER
    ).authorize(_accepted(), binding=_binding(), selection=selection)
    assert client.calls == ["health", "show", "instruments", "authorize"]
    assert client.request.marketplace_operation_id == "a" * 64
    assert client.request.payer_profile_ref == "payer-opaque-1234"
    assert client.request.instrument_ref == "instrument-opaque-1"
    assert receipt.model_dump(mode="json") == {
        "funding_profile": "card.v1",
        "marketplace_operation_id": "a" * 64,
        "funding_authorization_ref": "funding-auth-safe-1",
        "expires_at_unix": 2000,
    }


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("authority_id", "other-authority"),
        ("environment", "staging"),
    ],
)
async def test_authorization_rejects_mismatched_accepted_authority_binding(
    field: str, value: str
) -> None:
    obligation = _obligation()
    obligation["params"] = {**obligation["params"], field: value}
    accepted = derive_accepted_funding_authorization(
        obligation_ref="a" * 64,
        obligation=obligation,
    )
    client = Client()
    with pytest.raises(HostedAuthorizationError, match="authority binding"):
        await HostedFundingAuthorizer(
            config=_config(), client=client, signer=SIGNER
        ).authorize(
            accepted,
            binding=_binding(),
            selection=FundingSelection(
                FundingMode.SAVED_INSTRUMENT,
                "instrument-opaque-1",
            ),
        )
    assert client.calls == []


def test_accepted_authorization_rejects_non_us_country() -> None:
    obligation = _obligation()
    obligation["params"] = {**obligation["params"], "country": "CA"}
    with pytest.raises(ValueError):
        derive_accepted_funding_authorization(
            obligation_ref="a" * 64,
            obligation=obligation,
        )


@pytest.mark.asyncio
async def test_push_bank_transfer_rejects_saved_mode_before_any_client_call() -> None:
    client = Client()
    with pytest.raises(HostedAuthorizationError, match="requires interactive"):
        await HostedFundingAuthorizer(
            config=_config(), client=client, signer=SIGNER
        ).authorize(
            _accepted(FundingProfile.US_BANK_TRANSFER),
            binding=_binding(),
            selection=FundingSelection(
                FundingMode.SAVED_INSTRUMENT,
                "instrument-opaque-1",
            ),
        )
    assert client.calls == []


@pytest.mark.asyncio
async def test_selection_must_match_accepted_interaction_before_client_call() -> None:
    obligation = _obligation()
    obligation["params"]["interaction"] = "interactive"
    accepted = derive_accepted_funding_authorization(
        obligation_ref="a" * 64,
        obligation=obligation,
    )
    client = Client()
    with pytest.raises(HostedAuthorizationError, match="accepted interaction"):
        await HostedFundingAuthorizer(
            config=_config(), client=client, signer=SIGNER
        ).authorize(
            accepted,
            binding=_binding(),
            selection=FundingSelection(
                FundingMode.SAVED_INSTRUMENT,
                "instrument-opaque-1",
            ),
        )
    assert client.calls == []


@pytest.mark.asyncio
async def test_retained_predecessor_authorizes_during_hosted_owner_overlap() -> None:
    class RotatedPayerClient(Client):
        async def show_payer_profile(self, payer_profile_ref: str, *, request_id: str):
            self.calls.append("show")
            return PayerProfileResult(
                payer_profile_ref=payer_profile_ref,
                primary_principal=MarketplaceSignerAdapter(
                    Ed25519Signer(b"b" * 32)
                ).principal,
                state=PayerProfileState.ACTIVE,
                version=2,
            )

    client = RotatedPayerClient()
    receipt = await HostedFundingAuthorizer(
        config=_config(),
        client=client,
        signer=SIGNER,
    ).authorize(
        _accepted(),
        binding=_binding(),
        selection=FundingSelection(
            FundingMode.SAVED_INSTRUMENT,
            "instrument-opaque-1",
        ),
    )
    assert receipt.funding_authorization_ref == "funding-auth-safe-1"
    assert client.calls == ["health", "show", "instruments", "authorize"]


@pytest.mark.asyncio
async def test_retired_local_binding_rejects_before_any_authority_call() -> None:
    client = Client()
    binding = _binding().model_copy(
        update={"state": AuthorityBindingState.RETIRED}
    )
    with pytest.raises(HostedAuthorizationError, match="binding is not active"):
        await HostedFundingAuthorizer(
            config=_config(), client=client, signer=SIGNER
        ).authorize(
            _accepted(),
            binding=binding,
            selection=FundingSelection(
                FundingMode.SAVED_INSTRUMENT,
                "instrument-opaque-1",
            ),
        )
    assert client.calls == []


@pytest.mark.asyncio
async def test_stale_profile_readiness_rejects_before_payer_or_authorization() -> None:
    class StaleProfileClient(Client):
        async def health(self, *, request_id: str):
            health = await super().health(request_id=request_id)
            health.funding_profiles = tuple(
                SimpleNamespace(profile=profile, ready=profile is not FundingProfile.CARD)
                for profile in FundingProfile
            )
            return health

    client = StaleProfileClient()
    with pytest.raises(HostedAuthorizationError, match="profile is not ready"):
        await HostedFundingAuthorizer(
            config=_config(), client=client, signer=SIGNER
        ).authorize(
            _accepted(),
            binding=_binding(),
            selection=FundingSelection(
                FundingMode.SAVED_INSTRUMENT,
                "instrument-opaque-1",
            ),
        )
    assert client.calls == ["health"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("readiness", "revoked"),
    [
        (InstrumentReadiness.PENDING, False),
        (InstrumentReadiness.READY, True),
    ],
)
async def test_unready_or_revoked_saved_instrument_never_authorizes(
    readiness: InstrumentReadiness,
    revoked: bool,
) -> None:
    class UnreadyInstrumentClient(Client):
        async def list_payer_instruments(
            self, payer_profile_ref: str, *, request_id: str
        ):
            self.calls.append("instruments")
            return InstrumentListResult(
                payer_profile_ref=payer_profile_ref,
                instruments=(
                    InstrumentProjection(
                        instrument_ref="instrument-opaque-1",
                        label="primary",
                        kind=InstrumentKind.CARD,
                        readiness=readiness,
                        is_default=True,
                        revoked=revoked,
                    ),
                ),
            )

    client = UnreadyInstrumentClient()
    with pytest.raises(
        HostedAuthorizationError,
        match="instrument or mandate readiness is unavailable",
    ):
        await HostedFundingAuthorizer(
            config=_config(), client=client, signer=SIGNER
        ).authorize(
            _accepted(),
            binding=_binding(),
            selection=FundingSelection(
                FundingMode.SAVED_INSTRUMENT,
                "instrument-opaque-1",
            ),
        )
    assert client.calls == ["health", "show", "instruments"]


@pytest.mark.asyncio
async def test_pre_negotiation_readiness_uses_exact_selected_instrument() -> None:
    context = await payer_compatibility_context(
        config=_config(),
        binding=_binding(),
        signer=SIGNER,
        client=Client(),
        funding_mode=FundingMode.SAVED_INSTRUMENT,
        instrument_ref="another-instrument",
        action_capable=True,
    )
    assert context["profile_readiness"]["card.v1"] == {
        "interactive": False,
        "saved_instrument": False,
    }


@pytest.mark.asyncio
async def test_pre_negotiation_readiness_respects_action_refusal() -> None:
    context = await payer_compatibility_context(
        config=_config(),
        binding=_binding(),
        signer=SIGNER,
        client=Client(),
        funding_mode=FundingMode.INTERACTIVE,
        action_capable=False,
    )
    assert context["interactions"] == ()
    assert all(
        not any(modes.values())
        for modes in context["profile_readiness"].values()
    )


@pytest.mark.asyncio
async def test_interactive_ach_readiness_does_not_require_saved_mandate() -> None:
    class NoInstruments(Client):
        async def list_payer_instruments(
            self, payer_profile_ref: str, *, request_id: str
        ):
            self.calls.append("instruments")
            return InstrumentListResult(
                payer_profile_ref=payer_profile_ref,
                instruments=(),
            )

    context = await payer_compatibility_context(
        config=_config(),
        binding=_binding(),
        signer=SIGNER,
        client=NoInstruments(),
    )
    ach = context["profile_readiness"]["us_ach_debit.v1"]
    assert ach == {"interactive": True, "saved_instrument": False}


def _policy() -> OffSessionPolicy:
    return OffSessionPolicy(
        enabled=True,
        authority_id="authority-main",
        environment="production",
        funding_profile=FundingProfile.CARD,
        currency="usd",
        max_purchase_minor_units=100,
        max_aggregate_minor_units=100,
        window_seconds=3600,
        seller_principals=(SELLER,),
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("retryable", "expected_state"),
    [
        (False, ReservationState.RELEASED),
        (True, ReservationState.RESERVED),
    ],
)
async def test_authenticated_authority_rejection_releases_only_when_no_effect(
    tmp_path, retryable: bool, expected_state: ReservationState
) -> None:
    error = HostedSettlementError(
        code="rejected",
        message="provider detail must be redacted",
        retryable=retryable,
        status_code=409 if not retryable else 503,
    )
    client = Client(authorization_error=error)
    journal = AuthorizationReservationJournal((tmp_path / "journal.json").absolute())
    selection = FundingSelection(
        FundingMode.SAVED_INSTRUMENT,
        "instrument-opaque-1",
    )
    authorizer = HostedFundingAuthorizer(config=_config(), client=client, signer=SIGNER)
    with pytest.raises(HostedAuthorizationError) as caught:
        await authorizer.authorize_automatically(
            _accepted(),
            binding=_binding(),
            selection=selection,
            policy=_policy(),
            journal=journal,
            now_unix=1000,
        )
    assert caught.value.uncertain is retryable
    assert "provider detail" not in str(caught.value)
    assert journal.snapshot()[0].state is expected_state
    assert client.calls == ["health", "show", "instruments", "authorize"]


@pytest.mark.asyncio
async def test_untrusted_invalid_response_keeps_reservation_for_exact_retry(
    tmp_path,
) -> None:
    client = Client(
        authorization_error=HostedSettlementError(
            code="invalid_response",
            message="untrusted response detail",
            retryable=False,
            status_code=200,
        )
    )
    journal = AuthorizationReservationJournal((tmp_path / "journal.json").absolute())
    selection = FundingSelection(
        FundingMode.SAVED_INSTRUMENT,
        "instrument-opaque-1",
    )
    authorizer = HostedFundingAuthorizer(config=_config(), client=client, signer=SIGNER)
    for _attempt in range(2):
        with pytest.raises(HostedAuthorizationError) as caught:
            await authorizer.authorize_automatically(
                _accepted(),
                binding=_binding(),
                selection=selection,
                policy=_policy(),
                journal=journal,
                now_unix=1000,
            )
        assert caught.value.uncertain is True
    records = journal.snapshot()
    assert len(records) == 1
    assert records[0].state is ReservationState.RESERVED
    assert client.calls.count("authorize") == 2


@pytest.mark.asyncio
async def test_deterministic_pre_send_failure_releases_reservation(
    tmp_path, monkeypatch
) -> None:
    client = Client()
    journal = AuthorizationReservationJournal((tmp_path / "journal.json").absolute())
    selection = FundingSelection(
        FundingMode.SAVED_INSTRUMENT,
        "instrument-opaque-1",
    )
    monkeypatch.setattr(
        authorization_module,
        "sign_funding_authorization",
        lambda **_kwargs: (_ for _ in ()).throw(ValueError("invalid exact input")),
    )
    with pytest.raises(HostedAuthorizationError) as caught:
        await HostedFundingAuthorizer(
            config=_config(), client=client, signer=SIGNER
        ).authorize_automatically(
            _accepted(),
            binding=_binding(),
            selection=selection,
            policy=_policy(),
            journal=journal,
            now_unix=1000,
        )
    assert caught.value.uncertain is False
    assert journal.snapshot()[0].state is ReservationState.RELEASED
    assert "authorize" not in client.calls


@pytest.mark.asyncio
async def test_successful_authorization_commits_aggregate_reservation(tmp_path) -> None:
    client = Client()
    journal = AuthorizationReservationJournal((tmp_path / "journal.json").absolute())
    receipt = await HostedFundingAuthorizer(
        config=_config(), client=client, signer=SIGNER
    ).authorize_automatically(
        _accepted(),
        binding=_binding(),
        selection=FundingSelection(
            FundingMode.SAVED_INSTRUMENT,
            "instrument-opaque-1",
        ),
        policy=_policy(),
        journal=journal,
        now_unix=1000,
    )
    assert receipt.funding_authorization_ref == "funding-auth-safe-1"
    assert journal.snapshot()[0].state is ReservationState.AUTHORIZED
