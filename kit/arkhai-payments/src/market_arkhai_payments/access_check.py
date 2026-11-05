"""Proof that a role can reach and authenticate to its payments service.

Readiness never contacts the service, so the role's own CA trust, key and
service origin are proven together only by an authenticated read made from the
role's own process. The check reads one account's balance with exactly the client
the role would build, and reports the first step that failed.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any, Literal

import httpx
from pydantic import ValidationError

from market_arkhai_payments.errors import (
    PaymentsAPIError,
    PaymentsProtocolError,
    PaymentsTransportError,
)
from market_arkhai_payments.models import AccountId
from market_arkhai_payments.settlement_config import (
    ArkhaiPaymentsConfig,
    ArkhaiPaymentsConfigurationError,
    payments_client_for_owner,
    resolve_payments_api_key,
)

AccessStep = Literal["configuration", "credential", "transport", "refused"]


@dataclass(frozen=True)
class PaymentsAccessOutcome:
    """What one payments access check found.

    No field ever carries a credential: every ``detail`` is composed here from
    fixed text and public configuration, never from an exception's message, which
    may echo request material.
    """

    outcome: Literal["ok", "failed"]
    account: str
    service_url: str | None = None
    assets: tuple[str, ...] = field(default_factory=tuple)
    held: int | None = None
    step: AccessStep | None = None
    code: str | None = None
    detail: str | None = None

    @property
    def ok(self) -> bool:
        return self.outcome == "ok"

    def json_line(self) -> str:
        """The outcome as one JSON object on one line, unset fields omitted."""

        body: dict[str, Any] = {"check": "payments", "outcome": self.outcome}
        if self.service_url is not None:
            body["service_url"] = self.service_url
        body["account"] = self.account
        if self.ok:
            body["assets"] = list(self.assets)
            body["held"] = self.held
        else:
            body["step"] = self.step
            if self.code is not None:
                body["code"] = self.code
            body["detail"] = self.detail
        return json.dumps(body)


def check_payments_access(
    config: ArkhaiPaymentsConfig | Mapping[str, Any] | None,
    account: str,
    *,
    environment: Mapping[str, str] | None = None,
    transport: httpx.BaseTransport | None = None,
) -> PaymentsAccessOutcome:
    """Read ``account``'s balance through the client the configuration builds.

    ``config`` is the role's ``[Settlement.arkhai_payments]`` section, parsed or
    raw, or ``None`` when the role configures none. ``account`` is the account
    whose balance is read; the service answers only for the credential's own
    account, so a seller checks its payee account. A malformed account is the
    caller's error and raises ``ValueError`` rather than producing an outcome.
    """

    account = AccountId.model_validate(account).root
    if config is None:
        return _failed(account, None, "configuration",
                       "no [Settlement.arkhai_payments] section is configured")
    try:
        section = ArkhaiPaymentsConfig.model_validate(config)
    except ValidationError as exc:
        return _failed(account, None, "configuration",
                       "[Settlement.arkhai_payments] is invalid: " + _locations(exc))
    service_url = section.service_url
    if not section.enabled:
        return _failed(account, service_url, "configuration",
                       "[Settlement.arkhai_payments] is not enabled")
    if service_url is None:
        return _failed(account, None, "configuration", "service_url is not configured")
    if not section.development_auth:
        if section.api_key is None and section.api_key_env is None:
            return _failed(account, service_url, "configuration",
                           "neither api_key nor api_key_env is configured")
        try:
            resolve_payments_api_key(section, environment=environment)
        except ArkhaiPaymentsConfigurationError:
            # Validation refuses an unusable api_key, so only a variable fails here.
            return _failed(account, service_url, "credential",
                           f"environment variable {section.api_key_env} is unset, empty, "
                           "or not a single-line key")
    try:
        client = payments_client_for_owner(
            section, account, environment=environment, transport=transport,
        )
    except OSError:
        # The client loads its trust bundle when it is built, before any request,
        # so a missing, unreadable, or malformed bundle raises here (ssl.SSLError
        # is an OSError). A configured ca_bundle_path is the role's own setting;
        # without one, the bundle is the one SSL_CERT_FILE names for the process.
        if section.ca_bundle_path is not None:
            return _failed(account, service_url, "configuration",
                           "the CA bundle ca_bundle_path names could not be loaded")
        return _failed(account, service_url, "transport",
                       "the trust bundle SSL_CERT_FILE names could not be loaded")
    try:
        with client:
            balance = client.get_balance(account)
    except PaymentsAPIError as exc:
        return _failed(account, service_url, "refused",
                       f"payments service refused the balance read with HTTP {exc.status_code}",
                       code=exc.code)
    except PaymentsTransportError:
        return _failed(account, service_url, "transport",
                       "payments service could not be reached over a trusted connection")
    except PaymentsProtocolError:
        return _failed(account, service_url, "transport",
                       "payments service answered outside its published contract")
    return PaymentsAccessOutcome(
        outcome="ok", account=account, service_url=service_url,
        assets=tuple(sorted(balance.available)), held=len(balance.held),
    )


def check_configured_payments_access(
    read_section: Callable[[], ArkhaiPaymentsConfig | Mapping[str, Any] | None],
    account: str,
    *,
    environment: Mapping[str, str] | None = None,
    transport: httpx.BaseTransport | None = None,
) -> PaymentsAccessOutcome:
    """Check a role's payments access from its own configuration.

    ``read_section`` reads the role's ``[Settlement.arkhai_payments]`` section
    from the configuration the role serves with. A ``ValueError`` it raises is a
    configuration the role cannot read, reported as the ``configuration`` step
    without its message, which may quote a value. The account is validated before
    the configuration is read, so a ``ValueError`` this raises is always the
    caller's malformed account.
    """

    account = AccountId.model_validate(account).root
    try:
        section = read_section()
    except ValueError:
        return _failed(account, None, "configuration", "the role's configuration cannot be read")
    return check_payments_access(section, account, environment=environment, transport=transport)


def _failed(account: str, service_url: str | None, step: AccessStep, detail: str, *,
            code: str | None = None) -> PaymentsAccessOutcome:
    return PaymentsAccessOutcome(outcome="failed", account=account, service_url=service_url,
                                 step=step, code=code, detail=detail)


def _locations(exc: ValidationError) -> str:
    # Each error's location and type code only: a message may quote its input,
    # and an input may be a credential pasted under the wrong key.
    return ", ".join(
        f"{'.'.join(str(part) for part in error['loc']) or 'section'} ({error['type']})"
        for error in exc.errors(include_input=False)
    )


__all__ = [
    "AccessStep",
    "PaymentsAccessOutcome",
    "check_configured_payments_access",
    "check_payments_access",
]
