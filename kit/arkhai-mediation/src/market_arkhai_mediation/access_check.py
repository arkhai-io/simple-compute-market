"""Proof that a role can reach and authenticate to its dispute authority.

A role builds its mediation client only when a deal first needs it, so the
credential's token, its CA bundle and the authority's origin are proven together
only by an authenticated read made from the role's own process. The check makes
one respondent read with exactly the client the role would build and reports the
first step that failed. It reads nothing from the answer: an empty listing and a
full one are both access, and the read changes no state at the authority.
"""

from __future__ import annotations

import asyncio
import json
import re
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from typing import Any, Literal
from urllib.parse import urlsplit

import httpx
from jsonschema.exceptions import ValidationError as SchemaValidationError
from market_deal_lifecycle.configuration import DisputeCredential
from market_deal_lifecycle.terms import DisputeAuthority
from pydantic import ValidationError

from .client import (
    MediationAPIError,
    MediationClient,
    MediationCredential,
    MediationProtocolError,
    MediationTransportError,
)
from .contract import INTERFACE
from .models import RespondentAfter

AccessStep = Literal["configuration", "credential", "transport", "refused"]

# The contract's form of an authority origin, a scheme and a host with an
# optional port and nothing after it, also refusing a user part, which an origin
# a credential is bound to never carries.
_ORIGIN = re.compile(r"^https?://[^/?#\s@]+$")


@dataclass(frozen=True)
class MediationAccessOutcome:
    """What one mediation access check found.

    No field ever carries a credential: every ``detail`` is composed here from
    fixed text and public configuration, never from an exception's message, which
    may echo request material.
    """

    outcome: Literal["ok", "failed"]
    origin: str
    step: AccessStep | None = None
    code: str | None = None
    detail: str | None = None

    @property
    def ok(self) -> bool:
        return self.outcome == "ok"

    def json_line(self) -> str:
        """The outcome as one JSON object on one line, unset fields omitted."""

        body: dict[str, Any] = {"check": "mediation", "outcome": self.outcome,
                                "origin": self.origin}
        if not self.ok:
            body["step"] = self.step
            if self.code is not None:
                body["code"] = self.code
            body["detail"] = self.detail
        return json.dumps(body)


def authority_origin(value: str) -> str:
    """``value`` as an authority origin, or ``ValueError`` when it is not one."""

    url = urlsplit(value)
    if not _ORIGIN.fullmatch(value) or not url.hostname:
        raise ValueError("an authority origin is a scheme and a host, with an optional port")
    return value


def check_mediation_access(
    credentials: Iterable[DisputeCredential],
    origin: str,
    *,
    environment: Mapping[str, str] | None = None,
    transport: httpx.AsyncBaseTransport | None = None,
) -> MediationAccessOutcome:
    """Read the respondent listing at ``origin`` with the credential naming it.

    ``credentials`` are the role's ``[[DisputeCredential]]`` entries. Exactly one
    ``arkhai.mediation.v1`` credential must name ``origin``; it supplies the
    authority's identity, the token and the CA bundle. Two that do bind two
    authorities at one origin, which the origin alone cannot choose between. A
    malformed origin is the caller's error and raises ``ValueError`` rather than
    producing an outcome.
    """

    origin = authority_origin(origin)
    matches = [credential for credential in credentials
               if credential.origin == origin and credential.interface == INTERFACE]
    if not matches:
        return _failed(origin, "configuration",
                       "no arkhai.mediation.v1 dispute credential names the origin")
    if len(matches) > 1:
        return _failed(origin, "configuration",
                       "more than one arkhai.mediation.v1 dispute credential names the origin")
    credential = matches[0]
    try:
        token = MediationCredential(credential.identity, token=credential.resolve(environment))
    except ValueError:
        # The configuration refuses an unusable api_key, so only a variable fails here.
        return _failed(origin, "credential",
                       f"environment variable {credential.api_key_env} is unset, empty, "
                       "or not a single-line token")
    try:
        authority = DisputeAuthority.model_validate(
            credential.model_dump(include={"interface", "origin", "account", "record_key"})
            | {"params": {}}
        )
        client = MediationClient(authority, token, transport=transport,
                                 ca_bundle=credential.ca_bundle_path)
    except (ValidationError, SchemaValidationError):
        return _failed(origin, "configuration",
                       "the dispute credential's account or record_key is not one "
                       "arkhai.mediation.v1 admits")
    except OSError:
        # The client loads its trust bundle when it is built, before any request,
        # so a missing, unreadable, or malformed bundle raises here (ssl.SSLError
        # is an OSError). A configured ca_bundle_path is the role's own setting;
        # without one, the bundle is the one SSL_CERT_FILE names for the process.
        if credential.ca_bundle_path is not None:
            return _failed(origin, "configuration",
                           "the CA bundle ca_bundle_path names could not be loaded")
        return _failed(origin, "transport",
                       "the trust bundle SSL_CERT_FILE names could not be loaded")
    except ValueError:
        return _failed(origin, "configuration", "mediation requires HTTPS outside loopback")
    try:
        asyncio.run(_read_respondent(client))
    except MediationAPIError as exc:
        return _failed(origin, "refused",
                       f"mediation authority refused the respondent read with HTTP {exc.status}",
                       code=exc.code)
    except MediationTransportError:
        return _failed(origin, "transport",
                       "mediation authority could not be reached over a trusted connection")
    except MediationProtocolError:
        return _failed(origin, "transport",
                       "mediation authority answered outside its published contract")
    return MediationAccessOutcome(outcome="ok", origin=origin)


def check_configured_mediation_access(
    read_credentials: Callable[[], Iterable[DisputeCredential]],
    origin: str,
    *,
    environment: Mapping[str, str] | None = None,
    transport: httpx.AsyncBaseTransport | None = None,
) -> MediationAccessOutcome:
    """Check a role's mediation access from its own configuration.

    ``read_credentials`` reads the role's ``[[DisputeCredential]]`` entries from
    the configuration the role serves with. A ``ValueError`` it raises is a
    configuration the role cannot read, reported as the ``configuration`` step
    without its message, which may quote a value. The origin is validated before
    the configuration is read, so a ``ValueError`` this raises is always the
    caller's malformed origin.
    """

    origin = authority_origin(origin)
    try:
        credentials = list(read_credentials())
    except ValueError:
        return _failed(origin, "configuration", "the role's configuration cannot be read")
    return check_mediation_access(credentials, origin, environment=environment,
                                  transport=transport)


async def _read_respondent(client: MediationClient) -> None:
    async with client:
        await client.respondent(RespondentAfter(after=""))


def _failed(origin: str, step: AccessStep, detail: str, *,
            code: str | None = None) -> MediationAccessOutcome:
    return MediationAccessOutcome(outcome="failed", origin=origin, step=step, code=code,
                                  detail=detail)


__all__ = [
    "AccessStep",
    "MediationAccessOutcome",
    "authority_origin",
    "check_configured_mediation_access",
    "check_mediation_access",
]
