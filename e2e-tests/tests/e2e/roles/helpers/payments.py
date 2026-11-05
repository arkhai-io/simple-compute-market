"""Explicit payments policy for the payment deal scenarios, which read it here.

A run names its payments target in PAYMENTS.SERVICE_URL. A lane that runs its
own target, the payments lane double, also sets PAYMENTS.LANE_OWNED: an unready
target is then the lane's own failure and fails the scenario by name, where an
external target that is not ready blocks it.
"""

import os
import ssl
from collections.abc import Callable, Mapping
from typing import Any

import httpx
import pytest
from market_arkhai_payments import ArkhaiPaymentsConfig
from market_identity import Identity, IdentityScheme

from e2e_harness.settings import settings
from tests.e2e.roles.buyer_cli import _toml_quote

# Whether a payments target is configured at all; with none, and none claimed as
# the lane's own, payment scenarios are blocked rather than failed: the target is
# an authority the run does not supply.
_TARGET_KEY = "SERVICE_URL"
# Everything else a configured payments run supplies itself: the service policy
# it pins and its parties' accounts and credentials.
_REQUIRED_KEYS = (
    "SERVICE_IDENTITY",
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


def target_ready(
    url: str,
    *,
    get: Callable[..., Any] = httpx.get,
    environ: Mapping[str, str] = os.environ,
) -> bool:
    """Whether the payments service at `url` reports itself ready.

    Environment proxies are never used: the probe asks the target itself. httpx
    reads SSL_CERT_FILE only alongside the proxy variables, so a CA bundle it
    names, such as a lane's CA for its payments double, is loaded here as the
    only trust the probe has, just as the payments client trusts it.
    """
    cafile = environ.get("SSL_CERT_FILE")
    verify: ssl.SSLContext | bool = ssl.create_default_context(cafile=cafile) if cafile else True
    try:
        health = get(url + "/health", timeout=5.0, trust_env=False, verify=verify)
        return health.status_code == 200 and health.json().get("status") == "ok"
    except (httpx.HTTPError, ValueError):
        return False


def configured_payments(
    *, ready: Callable[[str], bool] = target_ready
) -> ArkhaiPaymentsConfig:
    """Return the explicit service policy, blocking only an absent or unready
    external target.

    With no target configured the scenario is blocked. With one configured, a
    missing setting the run supplies itself is a broken configuration, so it
    fails, naming the setting, before the target is asked whether it is ready.
    An unready target blocks the scenario, unless it is the lane's own
    (PAYMENTS.LANE_OWNED), which fails it, naming the target.
    """
    lane_owned = payment_flag("LANE_OWNED")
    if not payment_setting(_TARGET_KEY):
        if lane_owned:
            pytest.fail(f"PAYMENTS.LANE_OWNED is set but PAYMENTS.{_TARGET_KEY} is not configured")
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
        development_auth=payment_flag("DEVELOPMENT_AUTH"),
        api_key_env=str(payment_setting("API_KEY_ENV")) or None,
        livemode=payment_flag("LIVEMODE"),
    )
    if not config.development_auth and not config.api_key_env:
        pytest.fail("PAYMENTS.API_KEY_ENV is required without DEVELOPMENT_AUTH")
    if not ready(url):
        if lane_owned:
            pytest.fail(f"the lane's own payments service at {url} is not ready")
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
        f"livemode = {str(config.livemode).lower()}",
    )
    if config.development_auth:
        return section + ("development_auth = true",)
    assert config.api_key_env is not None
    return section + (f"api_key_env = {_toml_quote(config.api_key_env)}",)
