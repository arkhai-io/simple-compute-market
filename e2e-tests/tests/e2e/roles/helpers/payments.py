"""Explicit payments policy for payment deal scenarios: the API-credit
scenario reads it here, and other payment scenarios may reuse it."""

from collections.abc import Callable

import httpx
import pytest
from market_arkhai_payments import ArkhaiPaymentsConfig
from market_identity import Identity, IdentityScheme

from e2e_harness.settings import settings
from tests.e2e.roles.buyer_cli import _toml_quote

# Whether a payments target is configured at all; with none, payment scenarios
# are blocked rather than failed, which is what a pipeline without one runs.
_TARGET_KEY = "SERVICE_URL"
# Everything else a configured payments run supplies itself: the service policy
# it pins and its parties' accounts and credentials.
_REQUIRED_KEYS = (
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


def payment_flag(name: str) -> bool:
    """Read PAYMENTS.<name> as a boolean, failing on anything but one.

    A settings file may hold the text "false", which `bool()` reads as true.
    """
    value = payment_setting(name, False)
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in ("true", "false"):
        return text == "true"
    pytest.fail(f"PAYMENTS.{name} must be true or false, not {value!r}")


def target_ready(url: str) -> bool:
    """Whether the payments service at `url` reports itself ready."""
    try:
        health = httpx.get(url + "/health", timeout=5.0, trust_env=False)
        return health.status_code == 200 and health.json().get("status") == "ok"
    except (httpx.HTTPError, ValueError):
        return False


def configured_payments(
    *, ready: Callable[[str], bool] = target_ready
) -> ArkhaiPaymentsConfig:
    """Return the explicit service policy, blocking only an absent or unready target.

    With no target configured the scenario is blocked. With one configured, a
    missing setting the run supplies itself is a broken configuration, so it
    fails, naming the setting, before the target is asked whether it is ready.
    """
    if not payment_setting(_TARGET_KEY):
        pytest.skip(f"blocked: PAYMENTS.{_TARGET_KEY} not configured")
    missing = [key for key in _REQUIRED_KEYS if not payment_setting(key)]
    if missing:
        pytest.fail(f"PAYMENTS.{', PAYMENTS.'.join(missing)} not configured")
    url = str(payment_setting(_TARGET_KEY)).rstrip("/")
    config = ArkhaiPaymentsConfig(
        enabled=True,
        service_url=url,
        service_identity=Identity(
            scheme=IdentityScheme.ED25519,
            identifier=str(payment_setting("SERVICE_IDENTITY")),
        ),
        fee_bps=int(str(payment_setting("FEE_BPS", 250))),
        dispute_authority=str(payment_setting("DISPUTE_AUTHORITY")),
        development_auth=payment_flag("DEVELOPMENT_AUTH"),
        api_key_env=str(payment_setting("API_KEY_ENV")) or None,
        livemode=payment_flag("LIVEMODE"),
    )
    if not config.development_auth and not config.api_key_env:
        pytest.fail("PAYMENTS.API_KEY_ENV is required without DEVELOPMENT_AUTH")
    if not ready(url):
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
