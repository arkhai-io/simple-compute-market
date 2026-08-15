from __future__ import annotations

import pytest
from hosted_settlement_client import AccountLinkResult
from market_hosted_settlement import (
    HostedSellerError,
    StripeSettlementConfig,
    onboard_hosted_seller,
)
from market_identity import Ed25519Signer

_SIGNER = Ed25519Signer(b"s" * 32)


def _config() -> StripeSettlementConfig:
    return StripeSettlementConfig(
        enabled=True,
        base_url="https://settlement.example",
        authority_id="hosted-authority",
        environment="production",
        authority={"principals": [_SIGNER.identity.model_dump(mode="json")]},
        expected_manifest_digest="sha256:" + "a" * 64,
        account_ref="seller-main",
        condition_profile="vm-fulfillment",
        condition_profiles={
            "vm-fulfillment": {
                "condition_id": "vm-fulfillment",
                "evaluator": {
                    "kind": "builtin.v1",
                    "version": "trivial.v1",
                    "resolver_id": "vm-portable",
                    "params": {"kind": "trivial"},
                },
                "demand": {"encoding": "application/jcs+json", "value": {}},
            }
        },
    )


class Client:
    def __init__(self, config, *, fail: bool = False) -> None:
        self.config = config
        self.fail = fail
        self.closed = False
        self.requests = []

    def create_account_link(self, request):
        self.requests.append(request)
        if self.fail:
            raise RuntimeError("https://provider.example/cus_secret")
        return AccountLinkResult(
            account_ref=request.account_ref,
            url="https://settlement.example/transient-action",
            expires_at_unix=2_000_000_000,
        )

    def close(self) -> None:
        self.closed = True


def test_seller_onboarding_builds_and_closes_the_released_client() -> None:
    clients = []

    def factory(config):
        client = Client(config)
        clients.append(client)
        return client

    result = onboard_hosted_seller(
        _config(),
        signer=_SIGNER,
        account_ref="seller-main",
        open_browser=False,
        open_url=lambda _url: pytest.fail("browser must remain transiently disabled"),
        client_factory=factory,
    )

    assert str(result.url) == "https://settlement.example/transient-action"
    assert result.expires_at_unix == 2_000_000_000
    assert clients[0].config.caller_role == "seller"
    assert clients[0].config.authority_id == "hosted-authority"
    assert clients[0].requests[0].account_ref == "seller-main"
    assert clients[0].closed is True


def test_seller_onboarding_redacts_remote_failures_and_closes_client() -> None:
    clients = []

    def factory(config):
        client = Client(config, fail=True)
        clients.append(client)
        return client

    with pytest.raises(HostedSellerError) as caught:
        onboard_hosted_seller(
            _config(),
            signer=_SIGNER,
            account_ref="seller-main",
            open_browser=False,
            open_url=lambda _url: None,
            client_factory=factory,
        )

    assert str(caught.value) == "hosted seller onboarding failed"
    assert "provider" not in str(caught.value)
    assert "cus_secret" not in str(caught.value)
    assert clients[0].closed is True
