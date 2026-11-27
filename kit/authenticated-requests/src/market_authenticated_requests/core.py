"""The admission core: version 3 verification, admission, and every signed answer.

One core serves an authority in both forms. It verifies a request under
``kit/identity``'s version 3 profile, checks the route's operation and resource
against what the request states, the audience against the authority's own signing
principal, freshness, and the caller's role and principal against the authority's
trust; reserves the request in the replay store; and answers every request that
carries a request identity signed, refusals, recorded outcomes, and a handler's
failure included. A request carrying no request identity -- a version 2 request
among them -- is answered unsigned, since no identity may be invented to sign it.

A replay store that fails while a request is reserved, resolved or concluded is
answered with a signed 503 ``admission_unavailable``: nothing about the request was
concluded, so its caller retries the same request. A signed 500 answers any other
failure: a route raising after the request was admitted, or the request failing
before its admission outside the replay store.

A request's ``@query`` is verified against the raw query string the authority
received, which the wrapper and a route's admission hand the core as it arrived.

A public operation's request states a request identity and carries no signature,
audience, origin or content digest; the core answers it signed over that identity,
unverified and reserving nothing, and refuses one carrying any of those fields as
malformed. A request stating a request identity and carrying no signature field that
no route serves is refused signed and unverified as well, since the core cannot know
which authority its caller meant.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
from collections.abc import AsyncIterator, Awaitable, Callable, Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any

import injected_time
from market_identity import (
    ExactRetry,
    RequestBinding,
    RequestRecord,
    ResponseRecord,
    Signer,
    TrustedIdentitySet,
    VerificationCode,
    VerifiedRequest,
    is_public_request,
    principal_text,
    sign_market_response,
    stated_request_binding,
    verify_market_request,
)
from market_identity.wire import REQUEST_PROFILE, RefusalCode
from request_replay import (
    Answered,
    Attempt,
    ChangedReuse,
    Dispatch,
    Entry,
    Expired,
    InProgress,
    Outcome,
    OutcomeUnknown,
    Policy,
    Renewal,
    ReplayStore,
    RequestReplay,
    Resolution,
    StoreUnavailable,
)

from market_authenticated_requests.routes import PublicBinding, ResourceUnbound, RouteBinding, RouteNotServed
from market_authenticated_requests.settings import AuthenticatedRequestsSettings

logger = logging.getLogger(__name__)

DEFAULT_MAX_SKEW_SECONDS = 300
DEFAULT_LEASE_SECONDS = 30

#: The detail of the signed 500 answering a route that raised after
#: authentication; it reveals nothing of the error, which is logged.
ROUTE_FAILURE_DETAIL = "The request failed"

#: The detail of the signed 400 refusing a public operation's request that carries
#: a field only a signed request carries.
_PUBLIC_SHAPE_DETAIL = (
    "A public operation's request carries no signature, audience, origin or content digest"
)

#: The detail of the signed 503 answering a request whose replay store failed.
ADMISSION_UNAVAILABLE_DETAIL = (
    "The request could not be admitted and nothing about it was concluded; retry the same request"
)

Headers = list[tuple[bytes, bytes]]


@dataclass(frozen=True)
class Answer:
    """A whole response the core sends as it is."""

    status: int
    headers: Headers
    body: bytes


@dataclass(frozen=True)
class Verified:
    """A request whose version 3 signature verified, with the exact body it carried."""

    request: VerifiedRequest
    body: bytes

    @property
    def record(self) -> RequestRecord:
        """The request's evidence record; every request the core verifies is
        addressed by its audience, so it has one."""

        record = self.request.record
        assert record is not None
        return record


@dataclass(frozen=True)
class SignedOutcome:
    """A signed answer to a verified request, for evidence capture: the request's
    and the response's records, each with its exact body."""

    request: RequestRecord
    request_body: bytes
    response: ResponseRecord
    response_body: bytes


@dataclass
class Admitted:
    """A request admitted for dispatch to its handler.

    ``record`` and ``body`` are the request's evidence record and exact body, for
    a handler that keeps the request before it answers. ``exact_retry`` tells the
    handler it serves an exact retry of a request it has seen, which only a re-run
    route dispatches.
    """

    request: VerifiedRequest
    record: RequestRecord
    body: bytes
    binding: RouteBinding
    attempt: Attempt
    exact_retry: bool
    renewal: Renewal | None = field(default=None, repr=False)

    @property
    def verified(self) -> Verified:
        return Verified(self.request, self.body)


@dataclass(frozen=True)
class PublicAdmitted:
    """A public operation's request admitted for dispatch: the request identity its
    answer is signed over, which is the route's operation and the request ID the
    caller stated."""

    binding: RequestBinding


class AdmissionCore:
    """Admits an authority's requests and signs its answers.

    ``signer`` gives the authority's signing identity, whose principal a
    request's audience must list. ``trust`` gives the principals trusted in a
    role. ``store`` is the replay store bound to the authority's own database.
    ``time_setting_operation`` names the operation that sets the time under
    injected time: while the installed source is settable, its request is
    exempt from both freshness bounds, every other check kept. ``clock`` is the
    process's time source in whole seconds; ``sleep`` waits durations of the
    core's own loops, on the monotonic clock. ``on_signed_outcome`` receives
    every signed answer to a request that verified, as both records and bodies.
    """

    def __init__(
        self,
        *,
        signer: Callable[[], Signer],
        trust: Callable[[str], TrustedIdentitySet],
        store: ReplayStore,
        settings: AuthenticatedRequestsSettings | None = None,
        max_skew_seconds: int = DEFAULT_MAX_SKEW_SECONDS,
        lease_seconds: int = DEFAULT_LEASE_SECONDS,
        time_setting_operation: str | None = None,
        clock: Callable[[], int] = injected_time.now,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        on_signed_outcome: Callable[[SignedOutcome], None] | None = None,
    ) -> None:
        self._settings = settings if settings is not None else AuthenticatedRequestsSettings()
        self._signer = signer
        self._trust = trust
        self._max_skew = max_skew_seconds
        self._time_setting_operation = time_setting_operation
        self._clock = clock
        self._sleep = sleep
        self._on_signed_outcome = on_signed_outcome
        self._replay = RequestReplay(
            store,
            Policy(
                skew_seconds=max_skew_seconds,
                retention_seconds=self._settings.recorded_outcome_retention_seconds,
                lease_seconds=lease_seconds,
            ),
            clock=clock,
        )

    @property
    def settings(self) -> AuthenticatedRequestsSettings:
        return self._settings

    # -- verification and admission -------------------------------------------

    def verify(
        self,
        method: str,
        headers: Mapping[str, str],
        body: bytes,
        *,
        query: str,
        route: RouteBinding | None = None,
    ) -> Verified | Answer:
        """The verified request, or the answer refusing it.

        ``query`` is the raw query string received, with its ``?`` prepended, or
        empty where there was none
        (:func:`~market_authenticated_requests.application.received_query`).
        A refusal binds the caller's stated request ID, and the operation and
        resource of ``route`` where the request reached one, else those it
        states. An unsupported protocol is answered over the stated fields alone.
        """

        verification = verify_market_request(method=method, headers=headers, body=body, query=query)
        if verification.verified and verification.request is not None:
            return Verified(verification.request, body)
        stated = stated_request_binding(method=method, headers=headers)
        if verification.code == VerificationCode.UNSUPPORTED_VERSION:
            return self.answer(
                stated,
                400,
                {
                    "code": RefusalCode.UNSUPPORTED_PROTOCOL.value,
                    "supported": [REQUEST_PROFILE],
                },
            )
        logger.warning(
            "authenticated request refused: code=%s %s operation=%r",
            verification.code.value,
            method,
            None if stated is None else stated.operation,
        )
        if stated is not None and route is not None:
            stated = RequestBinding.model_construct(
                method=stated.method,
                operation=route.operation,
                resource=route.resource,
                request_id=stated.request_id,
            )
        return self.answer(stated, 401, {"detail": _VERIFICATION_DETAIL.get(verification.code, "Invalid request proof")})

    def refuse_unserved(self, verified: Verified, not_served: RouteNotServed) -> Answer:
        """A verified request no route serves: a signed 404, or 405 with ``Allow``."""

        return self._not_served(verified.request.binding, not_served, verified=verified)

    def refuse_unserved_public(self, stated: RequestBinding, not_served: RouteNotServed) -> Answer:
        """A request stating a request identity and carrying no signature field
        that no route serves: the signed 404, or 405 with ``Allow``, over the
        identity it states, unverified."""

        return self._not_served(stated, not_served, verified=None)

    def _not_served(
        self, binding: RequestBinding, not_served: RouteNotServed, *, verified: Verified | None
    ) -> Answer:
        headers: Headers = []
        if not_served.allowed_methods:
            headers.append((b"allow", ", ".join(not_served.allowed_methods).encode("latin-1")))
        return self.answer(
            binding,
            not_served.status_code,
            {"code": RefusalCode.OPERATION_NOT_SERVED.value, "operation": binding.operation},
            headers=headers,
            verified=verified,
        )

    def refuse_unbound(
        self, verified: Verified, unbound: ResourceUnbound, *, operation: str | None = None
    ) -> Answer:
        """A request whose route found no resource in its body: a signed 400, bound
        over the route's ``operation`` where it is known."""

        binding = verified.request.binding
        if operation is not None:
            binding = RequestBinding.model_construct(
                method=binding.method, operation=operation, resource=binding.resource, request_id=binding.request_id
            )
        return self.answer(binding, 400, {"detail": unbound.detail}, verified=verified)

    def fail_unadmitted(self, method: str, headers: Mapping[str, str], error: BaseException) -> Answer:
        """A request that failed before its admission: a 500 signed over the request
        identity it states, or unsigned when it states none."""

        logger.error(
            "request failed before its admission: %s",
            method,
            exc_info=(type(error), error, error.__traceback__),
        )
        status, headers_out, body = _json(500, {"detail": ROUTE_FAILURE_DETAIL})
        return self.sign_stated(method, headers, status, headers_out, body)

    def admit(self, verified: Verified, binding: RouteBinding) -> Admitted | Answer:
        """Check a verified request against its route and the authority, then reserve it.

        A request must state the operation the route binds, and the route's
        resource exactly when its operation has a target: a resource stated for
        an operation with none, or none for one with a target, is a mismatch.
        """

        request = verified.request
        route = RequestBinding(
            method=request.method,
            operation=binding.operation,
            resource=binding.resource,
            request_id=request.request_id,
        )
        if (request.operation, request.resource) != (route.operation, route.resource):
            return self.answer(
                route,
                400,
                {
                    "code": RefusalCode.OPERATION_MISMATCH.value,
                    "stated": {"operation": request.operation, "resource": request.resource},
                    "bound": {"operation": route.operation, "resource": route.resource},
                },
                verified=verified,
            )
        if not request.addressed_to(self._signer().identity):
            return self.answer(route, 421, {"code": RefusalCode.AUDIENCE_MISMATCH.value}, verified=verified)
        if not self._exempt_from_freshness(binding) and not request.fresh(
            now=self._clock(), max_skew=self._max_skew
        ):
            return self.answer(
                route, 401, {"detail": _VERIFICATION_DETAIL[VerificationCode.TIMESTAMP_SKEW]}, verified=verified
            )
        if request.role not in binding.roles:
            return self.answer(route, 403, {"detail": "Marketplace role is not authorized"}, verified=verified)
        if not self._trust(request.role).allows(request.principal):
            return self.answer(
                route, 403, {"detail": _VERIFICATION_DETAIL[VerificationCode.WRONG_PRINCIPAL]}, verified=verified
            )
        try:
            admission = self._replay.admit(
                Entry(
                    principal=principal_text(request.principal),
                    request_id=request.request_id,
                    request_hash=request.request_hash,
                    resolution=Resolution(binding.exact_retry.value),
                    origin=request.origin,
                )
            )
        except StoreUnavailable:
            # Reserving, resolving or concluding failed, so nothing was dispatched
            # and nothing about the request is known: an earlier attempt may still
            # run, and its caller retries this request rather than reading state.
            logger.exception(
                "admitting request %s for %s failed in the replay store", request.request_id, binding.operation
            )
            return self.answer(
                route,
                503,
                {"code": RefusalCode.ADMISSION_UNAVAILABLE.value, "detail": ADMISSION_UNAVAILABLE_DETAIL},
                verified=verified,
            )
        if isinstance(admission, Dispatch):
            admitted = Admitted(
                request=request,
                record=verified.record,
                body=verified.body,
                binding=binding,
                attempt=admission.attempt,
                exact_retry=admission.exact_retry,
            )
            if binding.exact_retry is ExactRetry.RECORDED:
                # A recorded request is never dispatched twice, so its lease must
                # outlive its handler however long that runs.
                admitted.renewal = Renewal.start(self._replay, admission.attempt, sleep=self._sleep)
            return admitted
        if isinstance(admission, Answered):
            outcome = admission.outcome
            return self._signed(
                route,
                outcome.status,
                [(name.encode("latin-1"), value.encode("latin-1")) for name, value in outcome.headers],
                outcome.body,
                verified=verified,
            )
        if isinstance(admission, InProgress):
            return self.answer(route, 409, {"detail": "The authenticated request is still in progress"}, verified=verified)
        if isinstance(admission, ChangedReuse):
            return self.answer(
                route, 409, {"detail": "Request ID was reused with changed signed content"}, verified=verified
            )
        if isinstance(admission, OutcomeUnknown):
            return self.answer(
                route,
                409,
                {
                    "code": RefusalCode.EXACT_RETRY_OUTCOME_UNKNOWN.value,
                    "detail": "The request's attempt ended without a recorded outcome; "
                    "read current state before sending a new request",
                },
                verified=verified,
            )
        assert isinstance(admission, Expired)
        return self.answer(
            route,
            410,
            {
                "code": RefusalCode.EXACT_RETRY_EXPIRED.value,
                "detail": "The request's recorded outcome has expired; "
                "read current state before sending a new request",
            },
            verified=verified,
        )

    def admit_public(self, method: str, headers: Mapping[str, str], public: PublicBinding) -> PublicAdmitted | Answer:
        """Check a request to a public operation's route, which reserves nothing.

        Its request must be of a public operation's shape: a request carrying
        signature fields, an audience, an origin or a content digest is malformed,
        since each operation's message has one shape, and one stating no request
        identity is answered unsigned. It must
        state the route's operation and no resource, or it is a mismatch, signed
        over the route's operation.
        """

        stated = stated_request_binding(method=method, headers=headers)
        if stated is None:
            return self.answer(
                None, 400, {"detail": "A public operation's request states Market-Operation and Market-Request-ID"}
            )
        if not is_public_request(headers):
            return self.answer(stated, 400, {"detail": _PUBLIC_SHAPE_DETAIL})
        route = RequestBinding.model_construct(
            method=stated.method, operation=public.operation, resource=None, request_id=stated.request_id
        )
        if (stated.operation, stated.resource) != (route.operation, route.resource):
            return self.answer(
                route,
                400,
                {
                    "code": RefusalCode.OPERATION_MISMATCH.value,
                    "stated": {"operation": stated.operation, "resource": stated.resource},
                    "bound": {"operation": route.operation, "resource": None},
                },
            )
        return PublicAdmitted(route)

    def finish_public(self, admitted: PublicAdmitted, status: int, headers: Headers, body: bytes) -> Answer:
        """A public operation's handler's response, signed over its request identity."""

        return self._signed(admitted.binding, status, headers, body, verified=None)

    def fail_public(self, admitted: PublicAdmitted, error: BaseException) -> Answer:
        """A public operation whose handler raised: a signed 500, nothing recorded."""

        logger.error(
            "public route %s failed",
            admitted.binding.operation,
            exc_info=(type(error), error, error.__traceback__),
        )
        status, headers, body = _json(500, {"detail": ROUTE_FAILURE_DETAIL})
        return self.finish_public(admitted, status, headers, body)

    async def finish(self, admitted: Admitted, status: int, headers: Headers, body: bytes) -> Answer:
        """Complete an admitted request with its handler's response, and sign it.

        A recorded route records the response as it is, so an exact retry is
        answered with the same status, headers and body under a fresh signature.
        """

        if admitted.renewal is not None:
            await admitted.renewal.stop()
        try:
            self._replay.complete(
                admitted.attempt,
                Outcome(
                    status=status,
                    headers=tuple((name.decode("latin-1"), value.decode("latin-1")) for name, value in headers),
                    body=body,
                ),
            )
        except Exception:
            # The handler answered, so its answer is sent. Unrecorded, an exact
            # retry of a recorded route is told the outcome is unknown once the
            # attempt's lease ends, and is never dispatched again.
            logger.exception(
                "recording the outcome of request %s for %s failed",
                admitted.request.request_id,
                admitted.binding.operation,
            )
        return self._signed(admitted.request.binding, status, headers, body, verified=admitted.verified)

    def sign_stated(self, method: str, headers: Mapping[str, str], status: int, response_headers: Headers, body: bytes) -> Answer:
        """An answer the application gave a request no admission reached, signed over
        the request identity it states, or unsigned when it states none."""

        stated = stated_request_binding(method=method, headers=headers)
        if stated is None:
            return Answer(status, response_headers, body)
        return self._signed(stated, status, response_headers, body, verified=None)

    async def fail(self, admitted: Admitted, error: BaseException) -> Answer:
        """Complete an admitted request whose handler raised: a signed 500.

        On a recorded route the 500 is the request's outcome, so its exact retry
        is answered the same and never dispatched; whether the handler wrote
        anything before it raised is not known here.
        """

        logger.error(
            "route %s failed after authentication",
            admitted.binding.operation,
            exc_info=(type(error), error, error.__traceback__),
        )
        status, headers, body = _json(500, {"detail": ROUTE_FAILURE_DETAIL})
        return await self.finish(admitted, status, headers, body)

    # -- answers ---------------------------------------------------------------

    def answer(
        self,
        binding: RequestBinding | None,
        status: int,
        payload: dict[str, Any],
        *,
        headers: Iterable[tuple[bytes, bytes]] = (),
        verified: Verified | None = None,
    ) -> Answer:
        """A JSON answer, signed over ``binding``, or unsigned when there is none."""

        status, json_headers, body = _json(status, payload)
        all_headers = [*json_headers, *headers]
        if binding is None:
            return Answer(status, all_headers, body)
        return self._signed(binding, status, all_headers, body, verified=verified)

    def _signed(
        self,
        binding: RequestBinding,
        status: int,
        headers: Headers,
        body: bytes,
        *,
        verified: Verified | None,
    ) -> Answer:
        signature = sign_market_response(
            signer=self._signer(), status=status, body=body, request=binding, created=self._clock()
        )
        signed = [
            *headers,
            *((name.lower().encode("latin-1"), value.encode("latin-1")) for name, value in signature.headers.items()),
        ]
        if verified is not None and self._on_signed_outcome is not None:
            self._on_signed_outcome(
                SignedOutcome(
                    request=verified.record,
                    request_body=verified.body,
                    response=signature.record,
                    response_body=body,
                )
            )
        return Answer(status, signed, body)

    def _exempt_from_freshness(self, binding: RouteBinding) -> bool:
        return (
            self._time_setting_operation is not None
            and binding.operation == self._time_setting_operation
            and injected_time.TimeRouteService(injected_time.installed()).settable
        )

    # -- the sweep -------------------------------------------------------------

    def sweep(self) -> int:
        """Delete every replay row expired now."""

        return self._replay.sweep()

    @contextlib.asynccontextmanager
    async def sweeping(self) -> AsyncIterator[None]:
        """Sweep expired replay rows at startup and then every interval.

        For the authority's lifespan: the sweep runs beside the application,
        each in a worker thread so a backlog never blocks the event loop, and
        stops when the lifespan ends.
        """

        async def sweep_every_interval() -> None:
            while True:
                try:
                    swept = await asyncio.to_thread(self._replay.sweep)
                except Exception:
                    logger.exception("sweeping expired replay rows failed")
                else:
                    if swept:
                        logger.info("swept %d expired replay rows", swept)
                await self._sleep(self._settings.replay_prune_interval_seconds)

        task = asyncio.create_task(sweep_every_interval())
        try:
            yield
        finally:
            task.cancel()
            await asyncio.wait({task})


_VERIFICATION_DETAIL = {
    VerificationCode.UNKNOWN_SCHEME: "Unsupported identity scheme",
    VerificationCode.WRONG_PRINCIPAL: "Request principal is not trusted",
    VerificationCode.MALFORMED_ENVELOPE: "Malformed request proof",
    VerificationCode.CONTEXT_MISMATCH: "Request proof does not cover this request",
    VerificationCode.BODY_HASH_MISMATCH: "Request body does not match its proof",
    VerificationCode.TIMESTAMP_SKEW: "Request timestamp is outside the allowed skew",
    VerificationCode.INVALID_PROOF: "Invalid request proof",
}


def _json(status: int, payload: dict[str, Any]) -> tuple[int, Headers, bytes]:
    body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    return (
        status,
        [(b"content-type", b"application/json"), (b"content-length", str(len(body)).encode("ascii"))],
        body,
    )
