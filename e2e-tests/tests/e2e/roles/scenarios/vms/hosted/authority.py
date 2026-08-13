from __future__ import annotations

from pathlib import Path
from typing import Any
import tomllib

from hosted_settlement_client import ClientConfig, HostedSettlementClient
from market_hosted_settlement import MarketplaceSignerAdapter, adapt_expected_authorities
from market_hosted_settlement.settlement_config import StripeSettlementConfig


def released_authority_client(*, config_path: Path, signer: Any, caller_role: str):
    """Build only the released public hosted client from the hosted TOML fixture."""

    with config_path.open("rb") as source:
        document = tomllib.load(source)
    config = StripeSettlementConfig.model_validate(document["Settlement"]["stripe"])
    if config.authority is None or not config.base_url:
        raise RuntimeError("hosted authority client configuration is incomplete")
    return HostedSettlementClient(
        ClientConfig(
            base_url=config.base_url,
            signer=MarketplaceSignerAdapter(signer),
            caller_role=caller_role,
            authority_id=config.authority_id or "",
            environment=config.environment or "",
            expected_authorities=adapt_expected_authorities(config.authority.as_trusted_set()),
            timeout_seconds=config.request_timeout_seconds,
            allow_insecure_loopback=config.allow_insecure_loopback,
        )
    )
