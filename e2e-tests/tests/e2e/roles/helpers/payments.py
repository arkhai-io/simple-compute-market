"""Explicit payments policy for the payment deal scenarios, which read it here.

A run names its payments target in PAYMENTS.SERVICE_URL. A lane that runs its
own target, the payments lane double, also sets PAYMENTS.LANE_OWNED: an unready
target is then the lane's own failure and fails the scenario by name, where an
external target that is not ready blocks it.

The buyer's bearer key is a setting, PAYMENTS.BUYER_API_KEY, never a variable of
the runner's environment. The buyer reads its key from the variable its
configuration's ``api_key_env`` names, so the harness hands the key to each
buyer it runs under that name: to a ``market`` process in its environment, and
to an in-process payments client as the environment it resolves the key from.
"""

import os
import ssl
from collections.abc import Callable
from functools import partial
from typing import Any

import httpx
import pytest
from market_arkhai_payments import (
    ArkhaiPaymentsConfig, ArkhaiPaymentsConfigurationError, PaymentsClient,
    payments_client_for_owner, resolve_payments_api_key,
)
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


#: The compute dispute coverage a payments option the harness states carries
#: when the run names none: the fourteen-day minimum filing window of the
#: Arkhai mediation contract's default authority description, plus a day
#: covering the delivery deadline.
DEFAULT_DISPUTE_WINDOW_SECONDS = 15 * 86400


def dispute_window_seconds(*, delivery_deadline_seconds: int) -> int:
    """PAYMENTS.DISPUTE_WINDOW_SECONDS: the dispute coverage, in whole seconds,
    that every compute payments option the harness states carries, and that it
    expects of an option on a listing it created.

    The market refuses compute terms whose coverage is less than the delivery
    deadline plus the dispute authority's advertised minimum filing window, so
    a run against an authority advertising a shorter minimum may name a
    shorter coverage. The harness cannot read that minimum, so a value fails
    here only when it is not an integer or does not cover
    ``delivery_deadline_seconds``; the authority's minimum is checked where
    the option is published.
    """
    value = payment_setting("DISPUTE_WINDOW_SECONDS", DEFAULT_DISPUTE_WINDOW_SECONDS)
    seconds = None
    # A bool is an int to Python, but no number of seconds.
    if type(value) is int:
        seconds = value
    elif isinstance(value, str) and value.strip().isdecimal():
        seconds = int(value.strip())
    if seconds is None or seconds < delivery_deadline_seconds:
        pytest.fail(
            "PAYMENTS.DISPUTE_WINDOW_SECONDS must be an integer number of seconds "
            f"covering the {delivery_deadline_seconds}-second delivery deadline, "
            f"not {value!r}"
        )
    return seconds


def target_ready(
    url: str,
    *,
    ca_bundle: str | None = None,
    get: Callable[..., Any] = httpx.get,
) -> bool:
    """Whether the service at `url`, a payments or mediation target, reports
    itself ready.

    Environment proxies are never used: the probe asks the target itself. A CA
    bundle, such as a lane's CA for its doubles, is the only trust the probe
    has, just as the service's client trusts it alone. A bundle that cannot be
    loaded leaves the target not ready, as the client could not reach it
    either.
    """
    try:
        # ssl.SSLError, a malformed bundle, is an OSError like a missing one.
        verify: ssl.SSLContext | bool = (
            ssl.create_default_context(cafile=ca_bundle) if ca_bundle else True
        )
        health = get(url + "/health", timeout=5.0, trust_env=False, verify=verify)
        return health.status_code == 200 and health.json().get("status") == "ok"
    except (httpx.HTTPError, ValueError, OSError):
        return False


def configured_payments(
    *, ready: Callable[[str], bool] | None = None
) -> ArkhaiPaymentsConfig:
    """Return the explicit service policy, blocking only an absent or unready
    external target.

    With no target configured the scenario is blocked. With one configured, a
    missing setting the run supplies itself is a broken configuration, so it
    fails, naming the setting, before the target is asked whether it is ready.
    An unready target blocks the scenario, unless it is the lane's own
    (PAYMENTS.LANE_OWNED), which fails it, naming the target. Readiness is
    `target_ready` under the configured CA bundle unless `ready` is given.
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
        ca_bundle_path=str(payment_setting("CA_BUNDLE_PATH")) or None,
        livemode=payment_flag("LIVEMODE"),
    )
    if not config.development_auth and not config.api_key_env:
        pytest.fail("PAYMENTS.API_KEY_ENV is required without DEVELOPMENT_AUTH")
    if not config.development_auth:
        try:
            resolve_payments_api_key(config, environment=buyer_payments_environment(config))
        except ArkhaiPaymentsConfigurationError:
            pytest.fail("PAYMENTS.BUYER_API_KEY is missing or unusable", pytrace=False)
    if ready is None:
        ready = partial(target_ready, ca_bundle=config.ca_bundle_path)
    if not ready(url):
        if lane_owned:
            pytest.fail(f"the lane's own payments service at {url} is not ready")
        pytest.skip(f"blocked: payments service at {url} is not ready")
    return config


def buyer_payments_environment(config: ArkhaiPaymentsConfig) -> dict[str, str]:
    """The buyer's bearer key under the variable its configuration names, for
    the buyer processes and clients the harness runs; empty when the run states
    no key or the buyer uses development authentication."""
    key = str(payment_setting("BUYER_API_KEY"))
    if config.development_auth or not config.api_key_env or not key:
        return {}
    return {config.api_key_env: key}


def buyer_payments_client(
    config: ArkhaiPaymentsConfig,
    owner: str,
    *,
    transport: httpx.BaseTransport | None = None,
) -> PaymentsClient:
    """A payments client acting as the buyer account `owner`, its key resolved
    from `buyer_payments_environment` over the runner's own environment, so a
    key the settings state needs no variable in the runner's process."""
    return payments_client_for_owner(
        config,
        owner,
        environment={**os.environ, **buyer_payments_environment(config)},
        transport=transport,
    )


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
    if config.ca_bundle_path:
        section += (f"ca_bundle_path = {_toml_quote(config.ca_bundle_path)}",)
    if config.development_auth:
        return section + ("development_auth = true",)
    assert config.api_key_env is not None
    return section + (f"api_key_env = {_toml_quote(config.api_key_env)}",)
