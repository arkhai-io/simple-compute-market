"""The version 3 marketplace profile of RFC 9421 HTTP Message Signatures.

A request signs its method, the covered ``Market-*`` fields, and an RFC 9530
``Content-Digest`` over the body bytes sent. Its ``keyid`` is the complete
principal, ``created`` its signing instant, and ``tag`` the profile. ``alg`` is
omitted: the principal's scheme selects the cryptography, through the scheme
registry every marketplace proof dispatches on. A request addressed to marketplace
authorities covers ``Market-Audience``, the principals its caller would accept the
answer from; a signed delivery to an endpoint known only by its URL covers
``@target-uri`` in its place.

A response signs its status and content digest and binds the request it answers
through RFC 9421's ``req`` flag over the request's method, operation, resource and
request ID.

Freshness belongs to the caller: an authority and a client each compare ``created``
with their own process's time source, which this module never reads.
``VerifiedRequest.fresh`` states the profile's bounds for a request, and whether an
operation is held to them is the authority's to decide.
"""

from __future__ import annotations

import datetime
import hashlib
import re
from collections.abc import Mapping
from dataclasses import dataclass, field

import http_sf
from http_message_signatures import (
    ContentDigest,
    HTTPMessageSignaturesException,
    HTTPMessageSigner,
    HTTPMessageVerifier,
    HTTPSignatureAlgorithm,
    HTTPSignatureKeyResolver,
    InvalidSignature,
)
from http_message_signatures.structures import get_header_fields
from pydantic import Field, ValidationError, field_validator

from market_identity.canonical import frame_fields
from market_identity.models import (
    _REQUEST_ID,
    _TOKEN,
    ContractModel,
    Identity,
    IdentityScheme,
    TrustedIdentitySet,
)
from market_identity.registry import Signer, get_identity_verifier
from market_identity.verification import VerificationCode
from market_identity.wire import (
    CONTENT_DIGEST,
    MARKET_AUDIENCE,
    MARKET_OPERATION,
    MARKET_REQUEST_ID,
    MARKET_REQUEST_ORIGIN,
    MARKET_RESOURCE,
    MARKET_ROLE,
    REQUEST_PROFILE,
    RESPONSE_PROFILE,
    SIGNATURE,
    SIGNATURE_INPUT,
    SIGNATURE_LABEL,
)

_TARGET_URI = "@target-uri"
_ORIGIN = re.compile(r"^(?:0|[1-9][0-9]{0,14})$")
_MAX_RESOURCE_CHARACTERS = 1024
_SIGNATURE_PARAMETERS = frozenset({"created", "keyid", "tag"})

# A request bound by its audience covers no part of its URL, and a response's
# ``req`` components name only the request's method and fields; the library still
# parses a URL for every request message, so those messages carry this reserved,
# never-resolvable one, which no signature base reads.
_UNCOVERED_TARGET = "https://market.invalid/"

_AUDIENCE_COVERAGE = (
    "@method",
    MARKET_ROLE.lower(),
    MARKET_OPERATION.lower(),
    MARKET_RESOURCE.lower(),
    MARKET_AUDIENCE.lower(),
    MARKET_REQUEST_ID.lower(),
    MARKET_REQUEST_ORIGIN.lower(),
    CONTENT_DIGEST.lower(),
)
_DELIVERY_COVERAGE = tuple(
    _TARGET_URI if component == MARKET_AUDIENCE.lower() else component
    for component in _AUDIENCE_COVERAGE
)
_RESPONSE_COVERAGE = (
    '"@status"',
    f'"{CONTENT_DIGEST.lower()}"',
    '"@method";req',
    f'"{MARKET_OPERATION.lower()}";req',
    f'"{MARKET_RESOURCE.lower()}";req',
    f'"{MARKET_REQUEST_ID.lower()}";req',
)


class RequestBinding(ContractModel):
    """What a response binds of the request it answers."""

    method: str = Field(min_length=1, max_length=32)
    operation: str = Field(min_length=1, max_length=128)
    resource: str = Field(max_length=_MAX_RESOURCE_CHARACTERS)
    request_id: str = Field(min_length=1, max_length=128)

    @field_validator("method")
    @classmethod
    def normalize_method(cls, value: str) -> str:
        if not value.isascii() or not value.isalpha():
            raise ValueError("method must contain only ASCII letters")
        return value.upper()

    @field_validator("operation")
    @classmethod
    def validate_operation(cls, value: str) -> str:
        if not _TOKEN.fullmatch(value):
            raise ValueError("operation must be a bounded ASCII token")
        return value

    @field_validator("resource")
    @classmethod
    def validate_resource(cls, value: str) -> str:
        # The resource travels as a header field value, which a signature base
        # holds as printable ASCII with surrounding whitespace trimmed.
        if value and (
            not value.isascii()
            or not value.isprintable()
            or value != value.strip(" \t")
        ):
            raise ValueError(
                "resource must be printable ASCII with no surrounding whitespace"
            )
        return value

    @field_validator("request_id")
    @classmethod
    def validate_request_id(cls, value: str) -> str:
        if not _REQUEST_ID.fullmatch(value):
            raise ValueError("request_id must be a bounded ASCII token")
        return value


class MarketRequest(RequestBinding):
    """The semantic fields a version 3 request states and its signature covers."""

    role: str = Field(min_length=1, max_length=64)
    origin: int = Field(ge=0, le=999_999_999_999_999)

    @field_validator("role")
    @classmethod
    def validate_role(cls, value: str) -> str:
        if not _TOKEN.fullmatch(value):
            raise ValueError("role must be a bounded ASCII token")
        return value

    @property
    def binding(self) -> RequestBinding:
        """The method, operation, resource and request ID a response binds."""

        return RequestBinding(
            method=self.method,
            operation=self.operation,
            resource=self.resource,
            request_id=self.request_id,
        )


class VerifiedRequest(MarketRequest):
    """A version 3 request whose signature, coverage and body digest verified."""

    principal: Identity
    created: int = Field(ge=0)
    audience: tuple[Identity, ...] | None = None
    target_uri: str | None = None
    body_digest: str

    def addressed_to(self, identity: Identity) -> bool:
        """Whether the request's audience lists this complete principal."""

        return self.audience is not None and identity in self.audience

    def fresh(self, *, now: int, max_skew: int) -> bool:
        """Whether ``created`` is within the skew and the origin is no later than it.

        An origin is the request's first signing instant, so it may be far in the
        past on a retry, but never later than the authority's instant plus the skew.
        """

        if max_skew < 0:
            raise ValueError("max_skew must not be negative")
        return abs(now - self.created) <= max_skew and self.origin <= now + max_skew

    @property
    def request_hash(self) -> str:
        """Fingerprint what the request asks, for its replay reservation.

        Covers the profile, principal, role, method, operation, resource, origin and
        body. ``created`` is excluded, since every re-signing of a retry is fresh;
        so is the request ID, the reservation's key; and so is the audience or
        target, which say where the request is addressed rather than what it asks,
        and which a caller's trust set, rotated between attempts, may change.
        """

        return hashlib.sha256(
            frame_fields(
                (
                    REQUEST_PROFILE,
                    self.principal.scheme.value,
                    self.principal.identifier,
                    self.role,
                    self.method,
                    self.operation,
                    self.resource,
                    str(self.origin),
                    self.body_digest,
                )
            )
        ).hexdigest()


class RequestVerification(ContractModel):
    """The outcome of verifying one request under the version 3 profile."""

    code: VerificationCode
    request: VerifiedRequest | None = None

    @property
    def verified(self) -> bool:
        return self.code == VerificationCode.VERIFIED


class ResponseVerification(ContractModel):
    """The outcome of verifying one response against its request and authority."""

    code: VerificationCode
    principal: Identity | None = None
    created: int | None = None

    @property
    def verified(self) -> bool:
        return self.code == VerificationCode.VERIFIED


def principal_text(identity: Identity) -> str:
    """The complete principal as the profile writes it: ``<scheme>:<identifier>``."""

    return f"{identity.scheme.value}:{identity.identifier}"


def format_audience(audience: TrustedIdentitySet) -> str:
    """Serialize an audience as a structured list of principal tokens."""

    return http_sf.ser(
        [(http_sf.Token(principal_text(identity)), {}) for identity in audience.identities]
    )


def sign_market_request(
    *,
    signer: Signer,
    request: MarketRequest,
    body: bytes,
    created: int,
    audience: TrustedIdentitySet | None = None,
    target_uri: str | None = None,
) -> dict[str, str]:
    """Sign a request and return every header the profile adds to it.

    A request to marketplace authorities names its ``audience``, the principals its
    caller would accept the answer from. A delivery to an endpoint that is no
    marketplace authority names its ``target_uri``, the endpoint's URL, instead.
    """

    if (audience is None) == (target_uri is None):
        raise ValueError("a request binds exactly one of its audience or its target URI")
    headers = {
        MARKET_ROLE: request.role,
        MARKET_OPERATION: request.operation,
        MARKET_RESOURCE: request.resource,
        MARKET_REQUEST_ID: request.request_id,
        MARKET_REQUEST_ORIGIN: str(request.origin),
    }
    if audience is not None:
        headers[MARKET_AUDIENCE] = format_audience(audience)
        coverage, url = _AUDIENCE_COVERAGE, _UNCOVERED_TARGET
    else:
        assert target_uri is not None
        coverage, url = _DELIVERY_COVERAGE, target_uri
    _sign(
        signer,
        _RequestMessage(method=request.method, url=url, headers=headers),
        tag=REQUEST_PROFILE,
        coverage=coverage,
        body=body,
        created=created,
    )
    return headers


def sign_market_response(
    *,
    signer: Signer,
    status: int,
    body: bytes,
    request: RequestBinding,
    created: int,
) -> dict[str, str]:
    """Sign a response to ``request`` and return the headers the profile adds."""

    if isinstance(status, bool) or not isinstance(status, int) or not 100 <= status <= 599:
        raise ValueError("status must be an HTTP status code")
    headers: dict[str, str] = {}
    _sign(
        signer,
        _ResponseMessage(status_code=status, headers=headers, request=_bound_request(request)),
        tag=RESPONSE_PROFILE,
        coverage=_RESPONSE_COVERAGE,
        body=body,
        created=created,
    )
    return headers


def verify_market_request(
    *,
    method: str,
    headers: Mapping[str, str],
    body: bytes,
    target_uri: str | None = None,
) -> RequestVerification:
    """Verify a request's profile signature, coverage and body digest.

    An authority verifies a request bound by its audience; a delivery's receiver
    passes its own endpoint as ``target_uri``, so a delivery made for any other
    endpoint fails. A request carrying no signature under the profile is
    ``unsupported_version``. Freshness, the audience's membership, and whom the
    principal is trusted as are the caller's to judge from the verified request.
    """

    coverage = _AUDIENCE_COVERAGE if target_uri is None else _DELIVERY_COVERAGE
    selected = _select(headers, REQUEST_PROFILE, _serialized(coverage))
    if isinstance(selected, VerificationCode):
        return RequestVerification(code=selected)
    label, keyid, created = selected
    principal = _principal(keyid)
    if isinstance(principal, VerificationCode):
        return RequestVerification(code=principal)
    fields = get_header_fields(headers)
    try:
        stated = MarketRequest(
            method=method,
            role=fields[MARKET_ROLE],
            operation=fields[MARKET_OPERATION],
            resource=fields[MARKET_RESOURCE],
            request_id=fields[MARKET_REQUEST_ID],
            origin=_origin(fields[MARKET_REQUEST_ORIGIN]),
        )
        audience = _audience(fields[MARKET_AUDIENCE]) if target_uri is None else None
    except (KeyError, ValueError, ValidationError):
        return RequestVerification(code=VerificationCode.MALFORMED_ENVELOPE)
    message = _RequestMessage(
        method=stated.method,
        url=_UNCOVERED_TARGET if target_uri is None else target_uri,
        headers=headers,
    )
    failure = _verify(message, tag=REQUEST_PROFILE, label=label, body=body)
    if failure is not None:
        return RequestVerification(code=failure)
    return RequestVerification(
        code=VerificationCode.VERIFIED,
        request=VerifiedRequest(
            **stated.model_dump(mode="python"),
            principal=principal,
            created=created,
            audience=audience,
            target_uri=target_uri,
            body_digest=hashlib.sha256(body).hexdigest(),
        ),
    )


def verify_market_response(
    *,
    status: int,
    headers: Mapping[str, str],
    body: bytes,
    request: RequestBinding,
    expected_principals: TrustedIdentitySet,
    now: int,
    max_skew: int,
) -> ResponseVerification:
    """Verify a response against the request it answers and the authority expected.

    The caller accepts a response only when its signature, body digest and request
    binding verify, its principal is one the caller expected, and its ``created``
    is within the skew of the caller's own instant.
    """

    if max_skew < 0:
        raise ValueError("max_skew must not be negative")
    selected = _select(headers, RESPONSE_PROFILE, frozenset(_RESPONSE_COVERAGE))
    if isinstance(selected, VerificationCode):
        return ResponseVerification(code=selected)
    label, keyid, created = selected
    principal = _principal(keyid)
    if isinstance(principal, VerificationCode):
        return ResponseVerification(code=principal)
    if not expected_principals.allows(principal):
        return ResponseVerification(code=VerificationCode.WRONG_PRINCIPAL, principal=principal)
    message = _ResponseMessage(
        status_code=status, headers=headers, request=_bound_request(request)
    )
    failure = _verify(message, tag=RESPONSE_PROFILE, label=label, body=body)
    if failure is not None:
        return ResponseVerification(code=failure, principal=principal)
    if abs(now - created) > max_skew:
        return ResponseVerification(
            code=VerificationCode.TIMESTAMP_SKEW, principal=principal, created=created
        )
    return ResponseVerification(
        code=VerificationCode.VERIFIED, principal=principal, created=created
    )


def stated_request_binding(
    *, method: str, headers: Mapping[str, str]
) -> RequestBinding | None:
    """The request identity a request states, whether or not it verifies.

    A request carries a request identity when it carries ``Market-Operation``,
    ``Market-Resource`` and ``Market-Request-ID``; an authority signs a refusal
    over whatever values it stated, and answers a request carrying none
    unauthenticated rather than inventing an identity to sign. A stated value is
    taken as it is, unless no signature base can hold it.
    """

    fields = get_header_fields(headers)
    try:
        stated = (
            method,
            fields[MARKET_OPERATION],
            fields[MARKET_RESOURCE],
            fields[MARKET_REQUEST_ID],
        )
    except KeyError:
        return None
    if not all(_signable(value) for value in stated) or not stated[0].isalpha():
        return None
    # The stated values answer only for themselves: a refusal binds what the caller
    # sent, so they are not held to the token forms a verified request must take.
    return RequestBinding.model_construct(
        method=method.upper(),
        operation=stated[1],
        resource=stated[2],
        request_id=stated[3],
    )


def _signable(value: str) -> bool:
    return value.isascii() and value.isprintable() and value == value.strip(" \t")


@dataclass
class _RequestMessage:
    method: str
    url: str
    headers: Mapping[str, str]


@dataclass
class _ResponseMessage:
    status_code: int
    headers: Mapping[str, str]
    request: _RequestMessage = field(repr=False)


class _PrincipalAlgorithm(HTTPSignatureAlgorithm):
    """Signs or verifies with a marketplace principal, dispatching on its scheme.

    The library builds one algorithm per key from whatever its key resolver returns;
    here that is the caller's signer, or the principal ``keyid`` names, so one
    algorithm serves every scheme the identity registry knows.
    """

    # Never written to a signature: the profile omits ``alg``.
    algorithm_id = "arkhai-market-principal"

    def __init__(self, public_key: Identity | None = None, private_key: Signer | None = None):
        self._principal = public_key
        self._signer = private_key

    def sign(self, message: bytes) -> bytes:
        assert self._signer is not None
        return self._signer.sign(message)

    def verify(self, signature: bytes, message: bytes) -> None:
        assert self._principal is not None
        verifier = get_identity_verifier(self._principal.scheme)
        if not verifier.verify_signature(self._principal, message, signature):
            raise InvalidSignature("signature does not verify for its principal")


class _SignerResolver(HTTPSignatureKeyResolver):
    def __init__(self, signer: Signer) -> None:
        self._signer = signer
        self._keyid = principal_text(signer.identity)

    def resolve_private_key(self, key_id: str) -> Signer:
        if key_id != self._keyid:
            raise KeyError(key_id)
        return self._signer

    def resolve_public_key(self, key_id: str) -> None:
        return None


class _PrincipalResolver(HTTPSignatureKeyResolver):
    def resolve_private_key(self, key_id: str) -> None:
        raise KeyError(key_id)

    def resolve_public_key(self, key_id: str) -> Identity | None:
        principal = _principal(key_id)
        return None if isinstance(principal, VerificationCode) else principal


class _Verifier(HTTPMessageVerifier):
    def validate_created_and_expires(self, sig_input, max_age=None) -> None:
        # The library judges ``created`` against the wall clock. Freshness here is
        # judged by the caller against its process's one time source, which a test
        # sets for every party at once, so the library checks presence alone.
        if "created" not in sig_input.params:
            raise InvalidSignature('signature is missing its "created" parameter')


_VERIFIER = _Verifier(signature_algorithm=_PrincipalAlgorithm, key_resolver=_PrincipalResolver())


def _sign(
    signer: Signer,
    message: _RequestMessage | _ResponseMessage,
    *,
    tag: str,
    coverage: tuple[str, ...],
    body: bytes,
    created: int,
) -> None:
    if isinstance(created, bool) or not isinstance(created, int) or created < 0:
        raise ValueError("created must be a non-negative integer instant")
    HTTPMessageSigner(
        signature_algorithm=_PrincipalAlgorithm,
        key_resolver=_SignerResolver(signer),
    ).sign(
        message,
        key_id=principal_text(signer.identity),
        created=datetime.datetime.fromtimestamp(created, tz=datetime.timezone.utc),
        label=SIGNATURE_LABEL,
        tag=tag,
        include_alg=False,
        covered_component_ids=coverage,
        body=body,
    )


def _verify(
    message: _RequestMessage | _ResponseMessage, *, tag: str, label: str, body: bytes
) -> VerificationCode | None:
    try:
        results = _VERIFIER.verify(message, max_age=None, expect_tag=tag, expect_label=label)
    except InvalidSignature:
        return VerificationCode.INVALID_PROOF
    except HTTPMessageSignaturesException:
        return VerificationCode.MALFORMED_ENVELOPE
    try:
        if not all(ContentDigest.verify_components(r.covered_components, body) for r in results):
            return VerificationCode.BODY_HASH_MISMATCH
    except InvalidSignature:
        return VerificationCode.BODY_HASH_MISMATCH
    return None


def _select(
    headers: Mapping[str, str], tag: str, coverage: frozenset[str]
) -> tuple[str, str, int] | VerificationCode:
    """Find the one signature under ``tag``, checking its parameters and coverage."""

    fields = get_header_fields(headers)
    if SIGNATURE_INPUT not in fields:
        return VerificationCode.UNSUPPORTED_VERSION
    try:
        inputs = http_sf.parse(fields[SIGNATURE_INPUT].encode("ascii"), tltype="dictionary")
    except (UnicodeEncodeError, ValueError, TypeError):
        return VerificationCode.MALFORMED_ENVELOPE
    selected = [
        (label, member, params)
        for label, (member, params) in inputs.items()
        if params.get("tag") == tag
    ]
    if not selected:
        return VerificationCode.UNSUPPORTED_VERSION
    if len(selected) > 1 or SIGNATURE not in fields:
        return VerificationCode.MALFORMED_ENVELOPE
    label, member, params = selected[0]
    if not isinstance(member, list) or set(params) != _SIGNATURE_PARAMETERS:
        return VerificationCode.MALFORMED_ENVELOPE
    created, keyid = params["created"], params["keyid"]
    if type(created) is not int or created < 0 or not isinstance(keyid, str):
        return VerificationCode.MALFORMED_ENVELOPE
    covered = [http_sf.ser(component) for component in member]
    if len(covered) != len(coverage) or set(covered) != coverage:
        return VerificationCode.MALFORMED_ENVELOPE
    return label, keyid, created


def _serialized(coverage: tuple[str, ...]) -> frozenset[str]:
    return frozenset(f'"{component}"' for component in coverage)


def _principal(text: str) -> Identity | VerificationCode:
    scheme, separator, identifier = text.partition(":")
    if not separator:
        return VerificationCode.MALFORMED_ENVELOPE
    try:
        known = IdentityScheme(scheme)
    except ValueError:
        return VerificationCode.UNKNOWN_SCHEME
    try:
        return Identity(scheme=known, identifier=identifier)
    except ValidationError:
        return VerificationCode.MALFORMED_ENVELOPE


def _origin(value: str) -> int:
    if not _ORIGIN.fullmatch(value):
        raise ValueError("origin must be a non-negative integer instant")
    return int(value)


def _audience(value: str) -> tuple[Identity, ...]:
    members = http_sf.parse(value.encode("ascii"), tltype="list")
    audience = []
    for member, params in members:
        if not isinstance(member, http_sf.Token) or params:
            raise ValueError("an audience lists principal tokens")
        principal = _principal(str(member))
        if isinstance(principal, VerificationCode):
            raise ValueError("an audience lists marketplace principals")
        audience.append(principal)
    if not audience:
        raise ValueError("an audience names at least one principal")
    return tuple(audience)


def _bound_request(request: RequestBinding) -> _RequestMessage:
    return _RequestMessage(
        method=request.method,
        url=_UNCOVERED_TARGET,
        headers={
            MARKET_OPERATION: request.operation,
            MARKET_RESOURCE: request.resource,
            MARKET_REQUEST_ID: request.request_id,
        },
    )
