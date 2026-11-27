"""The version 3 marketplace profile of RFC 9421 HTTP Message Signatures.

A request signs its method, RFC 9421's ``@query`` -- its query string exactly as
sent, with its leading ``?``, or ``?`` alone where it has none -- the covered
``Market-*`` fields, and an RFC 9530 ``Content-Digest`` over the body bytes sent.
Its ``keyid`` is the complete principal, ``created`` its signing instant, and
``tag`` the profile. ``alg`` is omitted: the principal's scheme selects the
cryptography, through the scheme registry every marketplace proof dispatches on. A request addressed to marketplace
authorities covers ``Market-Audience``, the principals its caller would accept the
answer from; a signed delivery to an endpoint known only by its URL covers
``@target-uri`` in its place.

An authority verifies ``@query`` against the raw query string it received, never a
re-encoding, so a typed client sends exactly the query it signed: it builds both
from :func:`encode_query`.

A public operation's request carries a request identity -- ``Market-Operation`` and
``Market-Request-ID`` -- and no signature, audience, origin or content digest
(:func:`build_public_request`); its answer is signed as every response is, over that
identity.

``Market-Resource`` is present exactly when the request's operation acts on one
object, which the route, not the request, decides; so a request, and the response
answering it, each have two coverage lists, with and without the resource.

A response signs its status and content digest and binds the request it answers
through RFC 9421's ``req`` flag over the request's method, operation, resource where
the request carries one, and request ID.

The profile accepts one spelling of everything it signs: the covered components in
the profile's order, the parameters ``created``, ``keyid``, ``tag`` in that order,
the audience in its canonical list serialization, and one canonical ``sha-256``
member of ``Content-Digest``. Any other spelling is malformed, though RFC 9421 would
verify it, so that a record of the signed values (:mod:`market_identity.records`)
rebuilds the exact signature base. Signing and verifying produce those records.

Freshness belongs to the caller: an authority and a client each compare ``created``
with their own process's time source, which this module never reads.
``VerifiedRequest.fresh`` states the profile's bounds for a request, and whether an
operation is held to them is the authority's to decide.
"""

from __future__ import annotations

import datetime
import hashlib
import re
import secrets
import urllib.parse
from collections.abc import Iterable, Mapping
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
from market_identity.codes import VerificationCode
from market_identity.models import (
    _REQUEST_ID,
    _TOKEN,
    ContractModel,
    Identity,
    IdentityScheme,
    SignatureProof,
    TrustedIdentitySet,
)
from market_identity.records import (
    MAX_RESOURCE_CHARACTERS,
    RequestRecord,
    ResponseRecord,
    covered_query,
    principal_text,
    resource_is_signable,
)
from market_identity.registry import Signer, get_identity_verifier
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
_SIGNATURE_PARAMETERS = ("created", "keyid", "tag")
_DIGEST_ALGORITHM = "sha-256"
# The fields only a signed request carries, none of which a public request may.
_SIGNED_ONLY = (SIGNATURE, SIGNATURE_INPUT, MARKET_AUDIENCE, MARKET_REQUEST_ORIGIN, CONTENT_DIGEST)

# A request bound by its audience covers its URL's query and nothing else of it,
# and a response's ``req`` components name only the request's method and fields;
# the library still parses a URL for every request message, so those messages carry
# this reserved, never-resolvable one, with the request's query appended, whose
# scheme, host and path no signature base reads.
_PLACEHOLDER_URL = "https://market.invalid/"


def _request_coverage(*, resource: bool, delivery: bool) -> tuple[str, ...]:
    """A request's covered components in the profile's order."""

    return (
        "@method",
        "@query",
        MARKET_ROLE.lower(),
        MARKET_OPERATION.lower(),
        *((MARKET_RESOURCE.lower(),) if resource else ()),
        _TARGET_URI if delivery else MARKET_AUDIENCE.lower(),
        MARKET_REQUEST_ID.lower(),
        MARKET_REQUEST_ORIGIN.lower(),
        CONTENT_DIGEST.lower(),
    )


def _response_coverage(*, resource: bool) -> tuple[str, ...]:
    """A response's covered components, serialized, in the profile's order."""

    return (
        '"@status"',
        f'"{CONTENT_DIGEST.lower()}"',
        '"@method";req',
        f'"{MARKET_OPERATION.lower()}";req',
        *((f'"{MARKET_RESOURCE.lower()}";req',) if resource else ()),
        f'"{MARKET_REQUEST_ID.lower()}";req',
    )


class RequestBinding(ContractModel):
    """What a response binds of the request it answers."""

    method: str = Field(min_length=1, max_length=32)
    operation: str = Field(min_length=1, max_length=128)
    #: The object the operation acts on; ``None`` for an operation with no target.
    resource: str | None = Field(default=None, max_length=MAX_RESOURCE_CHARACTERS)
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
    def validate_resource(cls, value: str | None) -> str | None:
        # The resource travels as a header field value, which a signature base
        # holds as printable ASCII with surrounding whitespace trimmed; an
        # operation with no target sends no field rather than an empty one.
        if value is not None and not resource_is_signable(value):
            raise ValueError(
                "resource must be non-empty printable ASCII with no surrounding whitespace"
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
    #: The covered ``@query``: ``?`` and the query as received, or ``?`` alone.
    query: str = Field(min_length=1)
    audience: tuple[Identity, ...] | None = None
    target_uri: str | None = None
    body_digest: str
    #: The signature value, in its scheme's canonical encoding.
    proof: str

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
    def record(self) -> RequestRecord | None:
        """The request's evidence record, or ``None`` for a delivery bound by its
        target, which no record represents."""

        if self.audience is None:
            return None
        return RequestRecord(
            principal=principal_text(self.principal),
            role=self.role,
            method=self.method,
            query=self.query,
            operation=self.operation,
            resource=self.resource,
            request_id=self.request_id,
            timestamp=self.created,
            origin=self.origin,
            audience=tuple(principal_text(member) for member in self.audience),
            proof=self.proof,
        )

    @property
    def request_hash(self) -> str:
        """Fingerprint what the request asks, for its replay reservation.

        Covers the profile, principal, role, method, query, operation, whether it
        names a resource and which, origin and body; the query by its digest, as the
        body, since a query may be longer than one framed field holds. ``created``
        is excluded, since every re-signing of a retry is fresh; so is the request
        ID, the reservation's key; and so is the audience or target, which say where
        the request is addressed rather than what it asks, and which a caller's
        trust set, rotated between attempts, may change.
        """

        resource = ("absent",) if self.resource is None else ("present", self.resource)
        return hashlib.sha256(
            frame_fields(
                (
                    REQUEST_PROFILE,
                    self.principal.scheme.value,
                    self.principal.identifier,
                    self.role,
                    self.method,
                    hashlib.sha256(self.query.encode("ascii")).hexdigest(),
                    self.operation,
                    *resource,
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
    """The outcome of verifying one response against its request and authority.

    ``record`` is the verified response's evidence record.
    """

    code: VerificationCode
    principal: Identity | None = None
    created: int | None = None
    record: ResponseRecord | None = None

    @property
    def verified(self) -> bool:
        return self.code == VerificationCode.VERIFIED


@dataclass(frozen=True)
class SignedRequest:
    """The headers signing adds to a request, and the request's evidence record.

    ``record`` is ``None`` for a delivery bound by its target, which no record
    represents.
    """

    headers: dict[str, str]
    record: RequestRecord | None


@dataclass(frozen=True)
class PublicRequest:
    """The headers a public operation's request carries, and the binding its signed
    answer is verified against through :func:`verify_market_response`."""

    headers: dict[str, str]
    binding: RequestBinding


@dataclass(frozen=True)
class SignedResponse:
    """The headers signing adds to a response, and the response's evidence record."""

    headers: dict[str, str]
    record: ResponseRecord


def format_audience(audience: TrustedIdentitySet) -> str:
    """Serialize an audience as a structured list of principal tokens."""

    return _serialize_audience(principal_text(identity) for identity in audience.identities)


def _serialize_audience(members: Iterable[str]) -> str:
    return http_sf.ser([(http_sf.Token(member), {}) for member in members])


def sign_market_request(
    *,
    signer: Signer,
    request: MarketRequest,
    body: bytes,
    created: int,
    query: str = "",
    audience: TrustedIdentitySet | None = None,
    target_uri: str | None = None,
) -> SignedRequest:
    """Sign a request: every header the profile adds to it, and its record.

    ``query`` is the query suffix the request is sent with, as :func:`encode_query`
    builds it: empty where it has none, or ``?`` and the query. A request to
    marketplace authorities names its ``audience``, the principals its caller would
    accept the answer from. A delivery to an endpoint that is no marketplace
    authority names its ``target_uri``, the endpoint's URL, instead, and its query
    is the target URI's own.
    """

    if (audience is None) == (target_uri is None):
        raise ValueError("a request binds exactly one of its audience or its target URI")
    if target_uri is not None and query:
        raise ValueError("a delivery's query is its target URI's")
    covered = covered_query(query)
    headers = {
        MARKET_ROLE: request.role,
        MARKET_OPERATION: request.operation,
        MARKET_REQUEST_ID: request.request_id,
        MARKET_REQUEST_ORIGIN: str(request.origin),
    }
    if request.resource is not None:
        headers[MARKET_RESOURCE] = request.resource
    if audience is not None:
        headers[MARKET_AUDIENCE] = format_audience(audience)
        url = _PLACEHOLDER_URL + covered
    else:
        assert target_uri is not None
        url = target_uri
    proof = _sign(
        signer,
        _RequestMessage(method=request.method, url=url, headers=headers),
        tag=REQUEST_PROFILE,
        coverage=_request_coverage(resource=request.resource is not None, delivery=audience is None),
        body=body,
        created=created,
    )
    record = None
    if audience is not None:
        record = RequestRecord(
            principal=principal_text(signer.identity),
            role=request.role,
            method=request.method,
            query=covered,
            operation=request.operation,
            resource=request.resource,
            request_id=request.request_id,
            timestamp=created,
            origin=request.origin,
            audience=tuple(principal_text(identity) for identity in audience.identities),
            proof=proof,
        )
    return SignedRequest(headers=headers, record=record)


def sign_market_response(
    *,
    signer: Signer,
    status: int,
    body: bytes,
    request: RequestBinding,
    created: int,
) -> SignedResponse:
    """Sign a response to ``request``: the headers the profile adds, and its record."""

    if isinstance(status, bool) or not isinstance(status, int) or not 100 <= status <= 599:
        raise ValueError("status must be an HTTP status code")
    headers: dict[str, str] = {}
    proof = _sign(
        signer,
        _ResponseMessage(status_code=status, headers=headers, request=_bound_request(request)),
        tag=RESPONSE_PROFILE,
        coverage=_response_coverage(resource=request.resource is not None),
        body=body,
        created=created,
    )
    return SignedResponse(
        headers=headers,
        record=_response_record(principal_text(signer.identity), status, request, created, proof),
    )


def verify_market_request(
    *,
    method: str,
    headers: Mapping[str, str],
    body: bytes,
    query: str = "",
    target_uri: str | None = None,
) -> RequestVerification:
    """Verify a request's profile signature, spelling and body digest.

    An authority verifies a request bound by its audience, passing as ``query`` the
    raw query string it received with its ``?`` prepended -- never one decoded and
    re-encoded, which a signature over another spelling would fail -- or nothing
    where it received none. A delivery's receiver passes its own endpoint, query
    included, as ``target_uri``, so a delivery made for any other endpoint fails. A
    request carrying no signature under the profile is ``unsupported_version``.
    Freshness, the audience's membership, and whom the principal is trusted as are
    the caller's to judge from the verified request.
    """

    if target_uri is not None and query:
        raise ValueError("a delivery's query is its target URI's")
    if query and not query.startswith("?"):
        raise ValueError("a query suffix is empty or starts with '?'")

    fields = get_header_fields(headers)
    coverage = _request_coverage(resource=MARKET_RESOURCE in fields, delivery=target_uri is not None)
    selected = _select(headers, REQUEST_PROFILE, tuple(f'"{component}"' for component in coverage))
    if isinstance(selected, VerificationCode):
        return RequestVerification(code=selected)
    label, keyid, created = selected
    principal = _principal(keyid)
    if isinstance(principal, VerificationCode):
        return RequestVerification(code=principal)
    try:
        stated = MarketRequest(
            method=method,
            role=fields[MARKET_ROLE],
            operation=fields[MARKET_OPERATION],
            resource=fields.get(MARKET_RESOURCE),
            request_id=fields[MARKET_REQUEST_ID],
            origin=_origin(fields[MARKET_REQUEST_ORIGIN]),
        )
        audience = _audience(fields[MARKET_AUDIENCE]) if target_uri is None else None
        _require_canonical_digest(fields[CONTENT_DIGEST])
        proof = _proof(fields[SIGNATURE], label, principal)
        if target_uri is None:
            covered = covered_query(query)
            url = _PLACEHOLDER_URL + covered
        else:
            covered, url = "?" + urllib.parse.urlsplit(target_uri).query, target_uri
    except (KeyError, ValueError, ValidationError):
        return RequestVerification(code=VerificationCode.MALFORMED_ENVELOPE)
    message = _RequestMessage(method=stated.method, url=url, headers=headers)
    failure = _verify(message, tag=REQUEST_PROFILE, label=label, body=body)
    if failure is not None:
        return RequestVerification(code=failure)
    return RequestVerification(
        code=VerificationCode.VERIFIED,
        request=VerifiedRequest(
            **stated.model_dump(mode="python"),
            principal=principal,
            created=created,
            query=covered,
            audience=audience,
            target_uri=target_uri,
            body_digest=hashlib.sha256(body).hexdigest(),
            proof=proof,
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

    The caller accepts a response only when its signature, spelling, body digest
    and request binding verify, its principal is one the caller expected, and its
    ``created`` is within the skew of the caller's own instant.
    """

    if max_skew < 0:
        raise ValueError("max_skew must not be negative")
    result = _check_market_response(
        status=status, headers=headers, body=body, request=request, expected_principals=expected_principals
    )
    if result.verified and result.created is not None and abs(now - result.created) > max_skew:
        return ResponseVerification(
            code=VerificationCode.TIMESTAMP_SKEW, principal=result.principal, created=result.created
        )
    return result


def _check_market_response(
    *,
    status: int,
    headers: Mapping[str, str],
    body: bytes,
    request: RequestBinding,
    expected_principals: TrustedIdentitySet,
) -> ResponseVerification:
    """Verify a response's signature, spelling, body digest, request binding and
    principal, judging no freshness: a retained response is not a live answer."""

    selected = _select(headers, RESPONSE_PROFILE, _response_coverage(resource=request.resource is not None))
    if isinstance(selected, VerificationCode):
        return ResponseVerification(code=selected)
    label, keyid, created = selected
    principal = _principal(keyid)
    if isinstance(principal, VerificationCode):
        return ResponseVerification(code=principal)
    if not expected_principals.allows(principal):
        return ResponseVerification(code=VerificationCode.WRONG_PRINCIPAL, principal=principal)
    fields = get_header_fields(headers)
    try:
        _require_canonical_digest(fields[CONTENT_DIGEST])
        proof = _proof(fields[SIGNATURE], label, principal)
    except (KeyError, ValueError, ValidationError):
        return ResponseVerification(code=VerificationCode.MALFORMED_ENVELOPE, principal=principal)
    message = _ResponseMessage(
        status_code=status, headers=headers, request=_bound_request(request)
    )
    failure = _verify(message, tag=RESPONSE_PROFILE, label=label, body=body)
    if failure is not None:
        return ResponseVerification(code=failure, principal=principal)
    return ResponseVerification(
        code=VerificationCode.VERIFIED,
        principal=principal,
        created=created,
        record=_response_record(keyid, status, request, created, proof),
    )


def stated_request_binding(
    *, method: str, headers: Mapping[str, str]
) -> RequestBinding | None:
    """The request identity a request states, whether or not it verifies.

    A request carries a request identity when it carries ``Market-Operation`` and
    ``Market-Request-ID``, with ``Market-Resource`` where it states one; an
    authority signs a refusal over whatever values it stated, and answers a
    request carrying none unauthenticated rather than inventing an identity to
    sign. A stated value is taken as it is, unless no signature base can hold it.
    """

    fields = get_header_fields(headers)
    try:
        operation, request_id = fields[MARKET_OPERATION], fields[MARKET_REQUEST_ID]
    except KeyError:
        return None
    resource = fields.get(MARKET_RESOURCE)
    stated = (method, operation, request_id, *(() if resource is None else (resource,)))
    if not all(_signable(value) for value in stated) or not method.isalpha():
        return None
    # The stated values answer only for themselves: a refusal binds what the caller
    # sent, so they are not held to the token forms a verified request must take.
    return RequestBinding.model_construct(
        method=method.upper(),
        operation=operation,
        resource=resource,
        request_id=request_id,
    )


def encode_query(items: Iterable[tuple[str, str]]) -> str:
    """The query suffix a typed client both signs and sends for ``items``.

    Each key and value is percent-encoded as RFC 3986 asks, every character but
    the unreserved ones escaped and a space as ``%20``, and the items are joined in
    their given order, a repeated key kept where it stands. The suffix is ``?`` and
    the query for a non-empty sequence and empty otherwise, so a client appends it
    to its path as it is. A client never lets its HTTP library encode the query,
    whose spelling (``+`` for a space, say) the authority would verify as another.
    """

    pairs = [
        f"{urllib.parse.quote(key, safe='')}={urllib.parse.quote(value, safe='')}"
        for key, value in items
    ]
    return "?" + "&".join(pairs) if pairs else ""


def build_public_request(*, method: str, operation: str) -> PublicRequest:
    """A public operation's request identity, under a fresh request ID.

    A public operation acts on no target, so its request states no resource, and it
    carries no signature, audience, origin or digest: only ``Market-Operation`` and
    ``Market-Request-ID``, over which the authority signs its answer. The request ID
    is 128 random bits, so the signed answer binds this request and no replay of an
    older answer verifies.
    """

    binding = RequestBinding(method=method, operation=operation, request_id=secrets.token_hex(16))
    headers = {MARKET_OPERATION: binding.operation, MARKET_REQUEST_ID: binding.request_id}
    return PublicRequest(headers=headers, binding=binding)


def is_public_request(headers: Mapping[str, str]) -> bool:
    """Whether a request has a public operation's shape, the one
    :func:`build_public_request` builds: it states a request identity,
    ``Market-Operation`` and ``Market-Request-ID``, and carries no ``Signature``,
    ``Signature-Input``, ``Market-Audience``, ``Market-Request-Origin`` or
    ``Content-Digest``."""

    fields = get_header_fields(headers)
    return (
        MARKET_OPERATION in fields
        and MARKET_REQUEST_ID in fields
        and not any(name in fields for name in _SIGNED_ONLY)
    )


def carries_signature_fields(headers: Mapping[str, str]) -> bool:
    """Whether a request carries ``Signature`` or ``Signature-Input``, so that an
    authority verifies it before answering, whatever else it states."""

    fields = get_header_fields(headers)
    return SIGNATURE in fields or SIGNATURE_INPUT in fields


def _rebuild_request_headers(record: RequestRecord, body: bytes) -> dict[str, str]:
    """The signed headers ``record`` was taken from, with ``body``'s digest.

    The profile's one accepted spelling makes these the headers the request was
    signed with whenever ``body`` is the body it carried.
    """

    headers = {
        MARKET_ROLE: record.role,
        MARKET_OPERATION: record.operation,
        MARKET_AUDIENCE: _serialize_audience(record.audience),
        MARKET_REQUEST_ID: record.request_id,
        MARKET_REQUEST_ORIGIN: str(record.origin),
        CONTENT_DIGEST: _digest(body),
    }
    if record.resource is not None:
        headers[MARKET_RESOURCE] = record.resource
    coverage = _request_coverage(resource=record.resource is not None, delivery=False)
    return headers | _signature_fields(record, tuple((component, {}) for component in coverage))


def _rebuild_response_headers(record: ResponseRecord, body: bytes) -> dict[str, str]:
    """The signed headers ``record`` was taken from, with ``body``'s digest."""

    components: list[tuple[str, dict[str, bool]]] = [("@status", {}), (CONTENT_DIGEST.lower(), {})]
    components += [
        ("@method", {"req": True}),
        (MARKET_OPERATION.lower(), {"req": True}),
        *(((MARKET_RESOURCE.lower(), {"req": True}),) if record.resource is not None else ()),
        (MARKET_REQUEST_ID.lower(), {"req": True}),
    ]
    return {CONTENT_DIGEST: _digest(body)} | _signature_fields(record, tuple(components))


def _record_binding(record: ResponseRecord) -> RequestBinding:
    """The request binding a response record holds, as its signature binds it."""

    return RequestBinding.model_construct(
        method=record.method,
        operation=record.operation,
        resource=record.resource,
        request_id=record.request_id,
    )


def _response_record(
    principal: str, status: int, request: RequestBinding, created: int, proof: str
) -> ResponseRecord:
    return ResponseRecord(
        principal=principal,
        status=status,
        timestamp=created,
        method=request.method,
        operation=request.operation,
        resource=request.resource,
        request_id=request.request_id,
        proof=proof,
    )


def _signature_fields(
    record: RequestRecord | ResponseRecord, components: tuple[tuple[str, dict[str, bool]], ...]
) -> dict[str, str]:
    signature = SignatureProof(scheme=record.identity.scheme, value=record.proof).to_bytes()
    parameters = {"created": record.timestamp, "keyid": record.principal, "tag": record.protocol}
    return {
        SIGNATURE_INPUT: http_sf.ser({SIGNATURE_LABEL: (list(components), parameters)}),
        SIGNATURE: http_sf.ser({SIGNATURE_LABEL: (signature, {})}),
    }


def _digest(body: bytes) -> str:
    return http_sf.ser({_DIGEST_ALGORITHM: (hashlib.sha256(body).digest(), {})})


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
) -> str:
    """Sign ``message`` in place, adding the profile's headers; answer the proof."""

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
    return _proof(get_header_fields(message.headers)[SIGNATURE], SIGNATURE_LABEL, signer.identity)


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
    headers: Mapping[str, str], tag: str, coverage: tuple[str, ...]
) -> tuple[str, str, int] | VerificationCode:
    """Find the one signature under ``tag``, checking its parameters and coverage
    are exactly the profile's, in its order."""

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
    if not isinstance(member, list) or tuple(params) != _SIGNATURE_PARAMETERS:
        return VerificationCode.MALFORMED_ENVELOPE
    created, keyid = params["created"], params["keyid"]
    if type(created) is not int or created < 0 or not isinstance(keyid, str):
        return VerificationCode.MALFORMED_ENVELOPE
    if tuple(http_sf.ser(component) for component in member) != coverage:
        return VerificationCode.MALFORMED_ENVELOPE
    return label, keyid, created


def _require_canonical_digest(value: str) -> None:
    """Refuse a ``Content-Digest`` other than one canonical ``sha-256`` member."""

    members = http_sf.parse(value.encode("ascii"), tltype="dictionary")
    if list(members) != [_DIGEST_ALGORITHM]:
        raise ValueError("Content-Digest carries one sha-256 member")
    digest, params = members[_DIGEST_ALGORITHM]
    if not isinstance(digest, bytes) or params or http_sf.ser(members) != value:
        raise ValueError("Content-Digest is spelled as its canonical serialization")


def _proof(value: str, label: str, principal: Identity) -> str:
    """The signature under ``label``, in its principal's scheme's canonical encoding."""

    signatures = http_sf.parse(value.encode("ascii"), tltype="dictionary")
    signature, params = signatures[label]
    if not isinstance(signature, bytes) or params:
        raise ValueError("a signature is a byte sequence")
    return SignatureProof.from_bytes(principal.scheme, signature).value


def _principal(text: str) -> Identity | VerificationCode:
    scheme, separator, identifier = text.partition(":")
    if not separator:
        return VerificationCode.MALFORMED_ENVELOPE
    try:
        known = IdentityScheme(scheme)
    except ValueError:
        return VerificationCode.UNKNOWN_SCHEME
    try:
        identity = Identity(scheme=known, identifier=identifier)
    except ValidationError:
        return VerificationCode.MALFORMED_ENVELOPE
    # One spelling of a principal, as of everything signed: an address spelled in
    # another case names the same principal, but its record could not rebuild the
    # signature base.
    if principal_text(identity) != text:
        return VerificationCode.MALFORMED_ENVELOPE
    return identity


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
    if http_sf.ser(members) != value:
        raise ValueError("an audience is spelled as its canonical list serialization")
    return tuple(audience)


def _bound_request(request: RequestBinding) -> _RequestMessage:
    headers = {MARKET_OPERATION: request.operation, MARKET_REQUEST_ID: request.request_id}
    if request.resource is not None:
        headers[MARKET_RESOURCE] = request.resource
    return _RequestMessage(method=request.method, url=_PLACEHOLDER_URL, headers=headers)
