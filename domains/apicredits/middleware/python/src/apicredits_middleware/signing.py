"""Marketplace identity v2 mapping for this middleware's outbound calls.

The credits service authenticates every non-health route against a signed
request envelope and signs every response, including refusals. A gated
application calls it in the ``service`` role: it may spend and check
credits, but not mint grants or revoke keys.

Why this module exists here rather than being imported:

``core/storefront-client`` already owns an equivalent mapping
(``build_authenticated_request``), and ``kit/site-client`` and
``compute_provisioning`` each own another. This package cannot use any of
them. It is a *published* library embedded in third-party seller
applications, so it must not acquire a dependency on a marketplace
storefront client to make an HTTP call. ``market_identity`` is a
different matter: it is the identity contract itself, is transport
neutral, and is the smallest thing that can produce a signature the
service will accept.

``market_identity`` is an optional dependency
(``arkhai-apicredits-middleware[signed]``). Unsigned deployments keep the
httpx-only dependency set, so the import is deferred to the point of use
and a missing install is reported as configuration rather than as an
``ImportError`` from inside a request.

Header names are repeated here rather than imported for the same
packaging reason. They are protocol constants, fixed by the wire format,
and this is the seventh place in the repository that spells them; see
`3ax`-series cleanup notes.
"""

from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass
from typing import Any, Mapping

SIGNATURE_VERSION_HEADER = "X-Market-Signature-Version"
IDENTITY_SCHEME_HEADER = "X-Market-Identity-Scheme"
IDENTITY_IDENTIFIER_HEADER = "X-Market-Identity-Identifier"
ROLE_HEADER = "X-Market-Role"
REQUEST_ID_HEADER = "X-Market-Request-ID"
TIMESTAMP_HEADER = "X-Market-Timestamp"
SIGNATURE_HEADER = "X-Market-Signature"

#: The role this middleware presents. Narrower than the storefront's
#: ``seller`` on purpose: a compromised gated app must not be able to mint
#: grants or revoke keys, which one shared admin secret could not express.
GATED_APP_ROLE = "service"

#: The role the authority signs its *responses* with. Distinct from
#: ``GATED_APP_ROLE`` despite the identical string: one describes the
#: caller, the other the responder. See `market_site.auth._signed_headers`.
AUTHORITY_RESPONSE_ROLE = "service"

DEFAULT_MAX_RESPONSE_SKEW = 300

_INSTALL_HINT = (
    "signed authentication to the credits service requires the 'signed' "
    "extra: pip install 'arkhai-apicredits-middleware[signed]'"
)


class SigningConfigurationError(RuntimeError):
    """The signing configuration cannot be used as given."""


class ResponseAuthenticationError(RuntimeError):
    """The authority's response did not satisfy the identity v2 contract.

    Raised rather than returned because the gate's callers already treat an
    unusable answer as a denial. Letting this surface as a distinct type
    keeps "the service refused us" separable from "something answered for
    the service" in an operator's logs.
    """


def _identity_module() -> Any:
    try:
        import market_identity
    except ImportError as exc:  # pragma: no cover - exercised by config tests
        raise SigningConfigurationError(_INSTALL_HINT) from exc
    return market_identity


@dataclass(frozen=True)
class SignedCall:
    """The signed envelope fields one request was built with.

    Retained so the response can be verified against the *same* operation,
    resource and request id that were signed, rather than against values
    recomputed from the response.
    """

    method: str
    operation: str
    resource: str
    request_id: str
    headers: dict[str, str]
    content: bytes | None


class AuthoritySigning:
    """Signs requests to one credits authority and verifies its responses.

    Constructed from already-resolved values rather than from environment
    or settings, so the same object serves a deployment reading a mounted
    credential and a test passing a generated one.
    """

    def __init__(
        self,
        *,
        signer: Any,
        expected_authorities: Any,
        max_response_skew: int = DEFAULT_MAX_RESPONSE_SKEW,
    ) -> None:
        identity = _identity_module()
        if not isinstance(signer, identity.Signer):
            raise SigningConfigurationError(
                "signer must implement market_identity.Signer"
            )
        if not isinstance(expected_authorities, identity.TrustedIdentitySet):
            raise SigningConfigurationError(
                "expected_authorities must be a market_identity.TrustedIdentitySet"
            )
        if max_response_skew < 0:
            raise SigningConfigurationError(
                "max_response_skew must not be negative"
            )
        self._identity = identity
        self._signer = signer
        self._expected_authorities = expected_authorities
        self._max_response_skew = max_response_skew

    @property
    def principal_identifier(self) -> str:
        """The public identifier this middleware signs as, for logging."""
        return str(self._signer.identity.identifier)

    def sign(
        self,
        *,
        method: str,
        operation: str,
        resource: str,
        body: Any = None,
    ) -> SignedCall:
        """Build the signed headers and the exact bytes to send.

        The body hash is taken over RFC 8785 canonical JSON, so those exact
        bytes must be transmitted. Serializing once here and sending
        ``content=`` is what keeps the hash the service recomputes equal to
        the one that was signed -- an httpx ``json=`` re-serialization is
        not guaranteed to agree.
        """
        identity = self._identity
        envelope_body = identity.EMPTY_BODY if body is None else body
        content = None if body is None else identity.canonical_json(body)
        request_id = uuid.uuid4().hex
        authenticated = identity.sign_request(
            signer=self._signer,
            envelope=identity.RequestEnvelope(
                role=GATED_APP_ROLE,
                principal=self._signer.identity,
                method=method,
                operation=operation,
                resource=resource,
                request_id=request_id,
                timestamp=int(time.time()),
                body_hash=identity.canonical_body_hash(envelope_body),
            ),
        )
        headers = {
            "Accept": "application/json",
            SIGNATURE_VERSION_HEADER: authenticated.protocol,
            IDENTITY_SCHEME_HEADER: authenticated.principal.scheme.value,
            IDENTITY_IDENTIFIER_HEADER: authenticated.principal.identifier,
            ROLE_HEADER: authenticated.role,
            REQUEST_ID_HEADER: authenticated.request_id,
            TIMESTAMP_HEADER: str(authenticated.timestamp),
            SIGNATURE_HEADER: authenticated.proof.value,
        }
        if content is not None:
            headers["Content-Type"] = "application/json"
        return SignedCall(
            method=authenticated.method,
            operation=authenticated.operation,
            resource=authenticated.resource,
            request_id=authenticated.request_id,
            headers=headers,
            content=content,
        )

    def verify(
        self,
        call: SignedCall,
        *,
        headers: Mapping[str, str],
        status: int,
        body: Any = None,
    ) -> None:
        """Verify one response came from a trusted authority, or raise.

        Applies to refusals as much as to successes. A 402 for an exhausted
        key is an authority decision the gate acts on, so it has to be
        established as the authority's before it is acted on -- otherwise
        anything on the path can deny service, or grant it.
        """
        identity = self._identity
        verified_body = identity.EMPTY_BODY if body is None else body
        try:
            scheme = _required(headers, IDENTITY_SCHEME_HEADER)
            protocol = _required(headers, SIGNATURE_VERSION_HEADER)
            if protocol != identity.RESPONSE_PROTOCOL:
                raise ResponseAuthenticationError(
                    f"HTTP {status}: unsupported response signature version"
                )
            principal = identity.Identity(
                scheme=scheme,
                identifier=_required(headers, IDENTITY_IDENTIFIER_HEADER),
            )
            authenticated = identity.AuthenticatedResponse(
                protocol=protocol,
                role=_required(headers, ROLE_HEADER),
                principal=principal,
                method=call.method,
                operation=call.operation,
                resource=call.resource,
                request_id=_required(headers, REQUEST_ID_HEADER),
                timestamp=int(_required(headers, TIMESTAMP_HEADER)),
                status=status,
                body_hash=identity.canonical_body_hash(verified_body),
                proof=identity.SignatureProof(
                    scheme=scheme,
                    value=_required(headers, SIGNATURE_HEADER),
                ),
            )
        except ResponseAuthenticationError:
            raise
        except (KeyError, TypeError, ValueError) as exc:
            raise ResponseAuthenticationError(
                f"HTTP {status}: missing or malformed credits-service "
                "response authentication"
            ) from exc

        result = identity.verify_response(
            authenticated,
            body=verified_body,
            now=int(time.time()),
            max_skew=self._max_response_skew,
            expected_role=AUTHORITY_RESPONSE_ROLE,
            expected_principals=self._expected_authorities,
            expected_method=call.method,
            expected_operation=call.operation,
            expected_resource=call.resource,
            expected_request_id=call.request_id,
        )
        if not result.verified:
            raise ResponseAuthenticationError(
                f"HTTP {status}: credits-service response authentication "
                f"failed: {result.code.value}"
            )


def _required(headers: Mapping[str, str], name: str) -> str:
    value = headers.get(name)
    if value is None:
        lowered = name.lower()
        for key, candidate in headers.items():
            if str(key).lower() == lowered:
                value = candidate
                break
    if value is None:
        raise KeyError(name)
    return str(value)


def build_signer(credential: str, scheme: str = "ed25519") -> Any:
    """Build a signer from one credential secret.

    ``create_signer`` requires canonical unpadded base64url for ed25519, so
    the credential is stripped: a file mounted from elsewhere may be
    newline terminated even though the identities committed to this
    repository deliberately are not.
    """
    identity = _identity_module()
    text = (credential or "").strip()
    if not text:
        raise SigningConfigurationError("identity credential is empty")
    try:
        return identity.create_signer(scheme, text)
    except (TypeError, ValueError) as exc:
        raise SigningConfigurationError(
            f"identity credential is not a usable {scheme} secret: {exc}"
        ) from exc


def build_trusted_authorities(raw: str | list[dict[str, Any]]) -> Any:
    """Build the authority trust set from JSON, or from an already-parsed list.

    ``TrustedIdentitySet`` cannot be empty and admits at most two
    identities -- enough for a rotation and no more -- so an empty
    configuration is refused here rather than becoming a set that trusts
    nothing and fails every response with a less obvious message.
    """
    identity = _identity_module()
    if isinstance(raw, str):
        text = raw.strip()
        if not text:
            raise SigningConfigurationError(
                "authority principals are required when signing is enabled"
            )
        try:
            parsed = json.loads(text)
        except ValueError as exc:
            raise SigningConfigurationError(
                "authority principals must be JSON"
            ) from exc
    else:
        parsed = raw
    if isinstance(parsed, dict):
        parsed = [parsed]
    if not isinstance(parsed, list) or not parsed:
        raise SigningConfigurationError(
            "authority principals must be a non-empty JSON list of "
            '{"scheme": ..., "identifier": ...} objects'
        )
    try:
        return identity.TrustedIdentitySet(
            identities=tuple(
                identity.Identity.model_validate(value) for value in parsed
            ),
        )
    except (TypeError, ValueError) as exc:
        raise SigningConfigurationError(
            f"authority principals are not a usable trust set: {exc}"
        ) from exc
