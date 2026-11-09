"""The run's dispute authority, for the payment scenarios' case stages and buyers.

A run names its mediation target in MEDIATION.SERVICE_URL, the origin of the
dispute authority the registries recommend, which the case stages reach through
the authority their Agreement pins. A lane that runs its own target, the
mediation lane double, also sets MEDIATION.LANE_OWNED: an unready target is then
the lane's own failure and fails setup by name, where an external target that
is not ready, or none at all, blocks the stages that need it.

The buyer's mediation token is a setting, MEDIATION.BUYER_API_KEY, never a
variable of the runner's environment: the harness writes the buyer's
``[[DisputeCredential]]`` naming the variable MEDIATION.API_KEY_ENV names, and
hands the token to each ``market`` process under that variable, as the buyer's
own credential resolves it. The credential is bound to the authority's identity,
MEDIATION.ACCOUNT and MEDIATION.RECORD_KEY at the target's origin, and trusts
MEDIATION.CA_BUNDLE_PATH alone when one is set.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from functools import partial

import pytest

from e2e_harness.settings import settings
from tests.e2e.roles.buyer_cli import _toml_quote
from tests.e2e.roles.helpers.payments import target_ready

#: The interface every authority the harness files with serves.
INTERFACE = "arkhai.mediation.v1"
_TARGET_KEY = "SERVICE_URL"
# What a configured target needs, whoever runs it: the identity the buyer's
# credential binds to and the variable its token is handed over under.
_REQUIRED_KEYS = ("ACCOUNT", "RECORD_KEY", "API_KEY_ENV")
# What a lane-owned target, a double with controls, needs besides.
_LANE_OWNED_KEYS = ("CONTROL_TOKEN",)


@dataclass(frozen=True)
class MediationTarget:
    """The run's mediation target, as its settings name it."""

    service_url: str
    account: str
    record_key: str
    api_key_env: str
    lane_owned: bool
    ca_bundle_path: str | None = None
    buyer_api_key: str | None = None
    control_token: str | None = None


def mediation_setting(name: str, default: object = "") -> object:
    """Read MEDIATION.<name> from the E2E settings."""
    value = settings.get(f"MEDIATION.{name}", default)
    return default if value is None or (isinstance(value, str) and not value.strip()) else value


def _flag(name: str) -> bool:
    """MEDIATION.<name> as a strict boolean; a settings file may hold "false"."""
    value = mediation_setting(name, False)
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in ("true", "false"):
        return text == "true"
    pytest.fail(f"MEDIATION.{name} must be true or false, not {value!r}")


def mediation_if_configured(
    *, ready: Callable[[str], bool] | None = None,
) -> MediationTarget | None:
    """The run's mediation target, or None when the run names none and claims
    none as its own.

    With a target named, a missing setting the run supplies itself fails,
    naming it, before the target is asked whether it is ready; then an unready
    target blocks the caller, unless it is the lane's own, which fails it,
    naming the target. Readiness is the target's ``/health`` under its CA
    bundle unless ``ready`` is given.
    """
    lane_owned = _flag("LANE_OWNED")
    if not mediation_setting(_TARGET_KEY):
        if lane_owned:
            pytest.fail(f"MEDIATION.LANE_OWNED is set but MEDIATION.{_TARGET_KEY} is not configured")
        return None
    required = _REQUIRED_KEYS + (_LANE_OWNED_KEYS if lane_owned else ())
    missing = [key for key in required if not mediation_setting(key)]
    if missing:
        pytest.fail(f"MEDIATION.{', MEDIATION.'.join(missing)} not configured")
    target = MediationTarget(
        service_url=str(mediation_setting(_TARGET_KEY)).strip().rstrip("/"),
        account=str(mediation_setting("ACCOUNT")),
        record_key=str(mediation_setting("RECORD_KEY")),
        api_key_env=str(mediation_setting("API_KEY_ENV")),
        lane_owned=lane_owned,
        ca_bundle_path=str(mediation_setting("CA_BUNDLE_PATH")) or None,
        buyer_api_key=str(mediation_setting("BUYER_API_KEY")) or None,
        control_token=str(mediation_setting("CONTROL_TOKEN")) or None,
    )
    if ready is None:
        ready = partial(target_ready, ca_bundle=target.ca_bundle_path)
    if not ready(target.service_url):
        if lane_owned:
            pytest.fail(f"the lane's own mediation service at {target.service_url} is not ready")
        pytest.skip(f"blocked: mediation service at {target.service_url} is not ready")
    return target


def configured_mediation(*, ready: Callable[[str], bool] | None = None) -> MediationTarget:
    """The run's mediation target for a stage that files with it: a blocked
    skip naming the setting when the run names none."""
    target = mediation_if_configured(ready=ready)
    if target is None:
        pytest.skip(f"blocked: MEDIATION.{_TARGET_KEY} not configured")
    return target


def buyer_mediation_environment(target: MediationTarget | None) -> dict[str, str]:
    """The buyer's mediation token under the variable its credential names, for
    the buyer processes the harness runs; empty when the run names no target or
    states no token."""
    if target is None or not target.buyer_api_key:
        return {}
    return {target.api_key_env: target.buyer_api_key}


def buyer_dispute_credential_toml(target: MediationTarget | None) -> tuple[str, ...]:
    """The buyer's ``[[DisputeCredential]]`` for the target's authority, naming
    its token's variable rather than stating it; nothing when the run names no
    target."""
    if target is None:
        return ()
    lines = (
        "[[DisputeCredential]]",
        f"interface = {_toml_quote(INTERFACE)}",
        f"origin = {_toml_quote(target.service_url)}",
        f"account = {_toml_quote(target.account)}",
        f"record_key = {_toml_quote(target.record_key)}",
        f"api_key_env = {_toml_quote(target.api_key_env)}",
    )
    if target.ca_bundle_path:
        lines += (f"ca_bundle_path = {_toml_quote(target.ca_bundle_path)}",)
    return lines
