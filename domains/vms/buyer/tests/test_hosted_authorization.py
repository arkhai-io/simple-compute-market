from __future__ import annotations

from types import SimpleNamespace

import pytest

from core_buyer.action_policy import BuyerActionRequired
from domains.vms.buyer import hosted_authorization
from market_hosted_settlement import (
    AutomationDecision,
    AutomationPolicyRefused,
    FundingMode,
    FundingSelection,
    StripeSettlementConfig,
)
from market_identity import (
    AuthorityBindingState,
    AuthorityPayerBinding,
    Ed25519Signer,
)


SIGNER = Ed25519Signer(b"a" * 32)


class Profiles:
    def authority_payer_binding(self, profile_id, **coordinates):
        return AuthorityPayerBinding(
            authority_id=coordinates["authority_id"],
            environment=coordinates["environment"],
            binding_ref="payer_binding_opaque",
            bound_principal=coordinates["principal"],
            state=AuthorityBindingState.ACTIVE,
        )


class Client:
    def __init__(self) -> None:
        self.closed = 0

    async def aclose(self) -> None:
        self.closed += 1


def _config(tmp_path) -> StripeSettlementConfig:
    return StripeSettlementConfig(
        enabled=True,
        base_url="https://settlement.example",
        authority_id="authority-main",
        environment="production",
        authority={"principals": [SIGNER.identity.model_dump(mode="json")]},
        expected_manifest_digest="sha256:" + "ab" * 32,
        authorization_journal_path=str((tmp_path / "journal.json").absolute()),
    )


@pytest.mark.asyncio
async def test_owned_client_closes_when_automation_requires_interaction(
    monkeypatch,
    tmp_path,
) -> None:
    client = Client()

    class Authorizer:
        def __init__(self, **_kwargs):
            pass

        async def authorize_automatically(self, *_args, **_kwargs):
            raise AutomationPolicyRefused(
                AutomationDecision(allowed=False, reason="disabled")
            )

    monkeypatch.setattr(
        hosted_authorization,
        "derive_accepted_funding_authorization",
        lambda **_kwargs: SimpleNamespace(expires_at_unix=2_000_000_000),
    )
    monkeypatch.setattr(hosted_authorization, "HostedFundingAuthorizer", Authorizer)
    monkeypatch.setattr(
        hosted_authorization,
        "payer_command_context_from_config",
        lambda *_args, **_kwargs: SimpleNamespace(
            client_factory=lambda _signer: client
        ),
    )

    with pytest.raises(BuyerActionRequired):
        await hosted_authorization.prepare_hosted_funding_authorization_async(
            buyer_profile_id="11111111-1111-4111-8111-111111111111",
            principal=SIGNER.identity,
            signer=SIGNER,
            stripe_config=_config(tmp_path),
            obligation_ref="a" * 64,
            obligation={},
            selection=FundingSelection(mode=FundingMode.SAVED_INSTRUMENT, instrument_ref="instrument_opaque"),
            automatic=True,
            profiles=Profiles(),
        )
    assert client.closed == 1


@pytest.mark.asyncio
async def test_injected_authorization_client_remains_caller_owned(
    monkeypatch,
    tmp_path,
) -> None:
    client = Client()
    receipt = object()

    class Authorizer:
        def __init__(self, **_kwargs):
            pass

        async def authorize(self, *_args, **_kwargs):
            return receipt

    monkeypatch.setattr(
        hosted_authorization,
        "derive_accepted_funding_authorization",
        lambda **_kwargs: SimpleNamespace(expires_at_unix=2_000_000_000),
    )
    monkeypatch.setattr(hosted_authorization, "HostedFundingAuthorizer", Authorizer)

    result = await hosted_authorization.prepare_hosted_funding_authorization_async(
        buyer_profile_id="11111111-1111-4111-8111-111111111111",
        principal=SIGNER.identity,
        signer=SIGNER,
        stripe_config=_config(tmp_path),
        obligation_ref="a" * 64,
        obligation={},
        selection=FundingSelection(mode=FundingMode.INTERACTIVE),
        automatic=False,
        profiles=Profiles(),
        client=client,
    )
    assert result is receipt
    assert client.closed == 0
