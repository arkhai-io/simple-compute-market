"""Provider-neutral seller onboarding through the exact released client."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from hosted_settlement_client import (
    AccountLinkResult,
    ClientConfig,
    HostedSettlementClient,
    SellerOnboarding,
)
from market_identity import Signer

from .adapter import MarketplaceSignerAdapter, adapt_expected_authorities
from .settlement_config import StripeSettlementConfig


class HostedSellerError(RuntimeError):
    """A provider-redacted seller onboarding failure."""


def onboard_hosted_seller(
    config: StripeSettlementConfig,
    *,
    signer: Signer,
    account_ref: str,
    open_browser: bool,
    open_url: Callable[[str], Any],
    client_factory: Callable[[ClientConfig], Any] = HostedSettlementClient,
) -> AccountLinkResult:
    """Create one transient seller onboarding action through the hosted kit."""

    resolved = StripeSettlementConfig.model_validate(config)
    if (
        not resolved.enabled
        or resolved.base_url is None
        or resolved.authority_id is None
        or resolved.environment is None
        or resolved.authority is None
        or resolved.account_ref is None
    ):
        raise HostedSellerError("hosted seller onboarding is not configured")
    if account_ref != resolved.account_ref:
        raise HostedSellerError("hosted seller account does not match configuration")

    try:
        client = client_factory(
            ClientConfig(
                base_url=resolved.base_url,
                signer=MarketplaceSignerAdapter(signer),
                caller_role="seller",
                authority_id=resolved.authority_id,
                environment=resolved.environment,
                expected_authorities=adapt_expected_authorities(
                    resolved.authority.as_trusted_set()
                ),
                timeout_seconds=resolved.request_timeout_seconds,
                allow_insecure_loopback=resolved.allow_insecure_loopback,
            )
        )
    except Exception:
        raise HostedSellerError("hosted seller client construction failed") from None

    try:
        workflow = SellerOnboarding(client, open_url=open_url)
        return workflow.onboard(account_ref, open_browser=open_browser)
    except Exception:
        raise HostedSellerError("hosted seller onboarding failed") from None
    finally:
        try:
            client.close()
        except Exception:
            pass


__all__ = ["HostedSellerError", "onboard_hosted_seller"]
