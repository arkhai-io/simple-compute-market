"""Explicit payments policy shared by the payment deal scenarios."""

import httpx
import pytest
from market_arkhai_payments import ArkhaiPaymentsConfig
from market_identity import Identity, IdentityScheme

from e2e_harness.settings import settings
from tests.e2e.roles.buyer_cli import _toml_quote

_PAYMENTS_KEYS = (
    "SERVICE_URL",
    "SERVICE_IDENTITY",
    "DISPUTE_AUTHORITY",
    "BUYER_ACCOUNT",
    "BUYER_MARKETPLACE_CREDENTIAL",
    "SELLER_MARKETPLACE_CREDENTIAL",
)


def payment_setting(name: str, default: object = "") -> object:
    """Read PAYMENTS.<name> from the E2E settings."""
    value = settings.get(f"PAYMENTS.{name}", default)
    return default if value is None or value == "" else value


def configured_payments() -> ArkhaiPaymentsConfig:
    """Return the explicit service policy, blocking only an unavailable target."""
    missing = [key for key in _PAYMENTS_KEYS if not payment_setting(key)]
    if missing:
        pytest.skip(f"blocked: PAYMENTS.{', PAYMENTS.'.join(missing)} not configured")
    url = str(payment_setting("SERVICE_URL")).rstrip("/")
    config = ArkhaiPaymentsConfig(
        enabled=True,
        service_url=url,
        service_identity=Identity(
            scheme=IdentityScheme.ED25519,
            identifier=str(payment_setting("SERVICE_IDENTITY")),
        ),
        fee_bps=int(str(payment_setting("FEE_BPS", 250))),
        dispute_authority=str(payment_setting("DISPUTE_AUTHORITY")),
        development_auth=bool(payment_setting("DEVELOPMENT_AUTH", False)),
        api_key_env=str(payment_setting("API_KEY_ENV")) or None,
        livemode=bool(payment_setting("LIVEMODE", False)),
    )
    if not config.development_auth and not config.api_key_env:
        pytest.fail("PAYMENTS.API_KEY_ENV is required without DEVELOPMENT_AUTH")
    try:
        health = httpx.get(url + "/health", timeout=5.0, trust_env=False)
        ready = health.status_code == 200 and health.json().get("status") == "ok"
    except (httpx.HTTPError, ValueError):
        ready = False
    if not ready:
        pytest.skip(f"blocked: payments service at {url} is not ready")
    return config


def payment_config_toml(
    config: ArkhaiPaymentsConfig,
    *,
    table: str = "Settlement.arkhai_payments",
) -> tuple[str, ...]:
    """Serialize one payments table without domain configuration or payer policy."""
    identity = config.service_identity
    assert identity is not None
    section = (
        f"[{table}]",
        f"enabled = {str(config.enabled).lower()}",
        f"service_url = {_toml_quote(str(config.service_url))}",
        'service_identity = { scheme = "ed25519", identifier = '
        + _toml_quote(identity.identifier)
        + " }",
        f"fee_bps = {config.fee_bps}",
        f"dispute_authority = {_toml_quote(str(config.dispute_authority))}",
        f"livemode = {str(config.livemode).lower()}",
    )
    if config.development_auth:
        return section + ("development_auth = true",)
    assert config.api_key_env is not None
    return section + (f"api_key_env = {_toml_quote(config.api_key_env)}",)
