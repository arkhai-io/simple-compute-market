"""The application the core wraps, in either form.

The wrapper reads every request's whole body, which the signature's digest
covers, and hands the application the same bytes. In the middleware form it binds
the request through the authority's route table and admits it before the
application runs. In the dependency form a route admits it through its
:class:`~market_authenticated_requests.dependency.RouteAdmission`, and the wrapper
finishes what the route admitted. In
both, a request carrying a request identity that no route of the application
serves is answered with a signed refusal, since in the dependency form no route's
admission ever runs for it -- verified first, unless it is of a public operation's
shape, which is refused over its stated identity unverified; and the wrapper holds
a handler's response until it is recorded and signed. A public operation's route,
bound in the middleware form's table or admitted through its
:class:`~market_authenticated_requests.dependency.PublicAdmission`, is answered
signed over the request identity its request states.

Each form verifies a request against the raw query string it arrived with
(:func:`received_query`), never one the framework decoded and re-encoded.
"""

from __future__ import annotations

import logging
from typing import Any

from market_identity import is_public_request, stated_request_binding
from request_replay.asgi import (
    CapturedResponse,
    Receive,
    Scope,
    Send,
    capture,
    read_body,
    replayed_receive,
    send_response,
)
from starlette.datastructures import Headers
from starlette.routing import BaseRoute, Match

from market_authenticated_requests.core import Admitted, AdmissionCore, Answer, PublicAdmitted, Verified
from market_authenticated_requests.routes import (
    PublicBinding,
    ResourceUnbound,
    RouteNotServed,
    RouteTable,
    Unauthenticated,
)

logger = logging.getLogger(__name__)

#: Where the wrapper leaves its work for the dependency form, in the request's
#: state: the body it read, the request a route admitted, and the answer a route
#: refused it with.
BODY_KEY = "authenticated_request_body"
ADMITTED_KEY = "authenticated_request"
ANSWER_KEY = "authenticated_request_answer"


def received_query(scope: Scope) -> str:
    """The query suffix a request arrived with, as the profile verifies it: ``?``
    and the ASGI ``query_string`` exactly as received, or empty where it is empty.

    The bytes are decoded one character each, so a byte no URL query may hold
    reaches verification as it came and fails it as malformed.
    """

    raw: bytes = scope.get("query_string", b"")
    return "?" + raw.decode("latin-1") if raw else ""


class AuthenticatedApplication:
    """An application whose authenticated requests the core admits and answers.

    Built by :func:`~market_authenticated_requests.inventory.install`, which
    checks the route inventory first.
    """

    def __init__(
        self,
        app: Any,
        core: AdmissionCore,
        *,
        routes: RouteTable | None,
        unauthenticated: Unauthenticated,
    ) -> None:
        self._app = app
        self._core = core
        self._routes = routes
        self._unauthenticated = unauthenticated

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self._app(scope, receive, send)
            return
        try:
            body = await read_body(receive)
        except ConnectionError:
            # The caller left before its request was whole: no one is waiting for
            # an answer, and nothing was admitted.
            return
        scope.setdefault("state", {})[BODY_KEY] = body
        downstream = replayed_receive(body, receive)
        method = str(scope["method"])
        headers = Headers(scope=scope)

        not_served = _unserved(self._app_routes(), scope)
        if not_served is not None:
            if stated_request_binding(method=method, headers=headers) is None:
                await self._app(scope, downstream, send)
                return
            await self._send(send, self._refuse_unserved(scope, method, headers, body, not_served))
            return

        marked = self._unauthenticated.marks(_route_path(self._app_routes(), scope))
        if self._routes is not None and not marked:
            await self._send(send, await self._middleware_form(scope, downstream, method, headers, body))
            return
        await self._send(send, await self._dependency_form(scope, downstream, method, headers, marked=marked))

    async def _middleware_form(
        self, scope: Scope, receive: Receive, method: str, headers: Headers, body: bytes
    ) -> Answer:
        assert self._routes is not None
        query = received_query(scope)
        try:
            binding = self._routes.resolve(method, str(scope["path"]), body)
        except RouteNotServed as not_served:
            return self._refuse_unserved(scope, method, headers, body, not_served)
        except ResourceUnbound as unbound:
            verified = self._core.verify(method, headers, body, query=query)
            return verified if isinstance(verified, Answer) else self._core.refuse_unbound(verified, unbound)
        except Exception as error:
            return self._core.fail_unadmitted(method, headers, error)
        if isinstance(binding, PublicBinding):
            return await self._public(scope, receive, method, headers, binding)
        verified = self._core.verify(method, headers, body, query=query, route=binding)
        if isinstance(verified, Answer):
            return verified
        try:
            admitted = self._core.admit(verified, binding)
        except Exception as error:
            # The authority's own trust or signer failing, as the dependency form's
            # wrapper answers it: a signed 500, nothing dispatched.
            return self._core.fail_unadmitted(method, headers, error)
        if isinstance(admitted, Answer):
            return admitted
        scope["state"][ADMITTED_KEY] = admitted
        return await self._run(admitted, scope, receive)

    async def _dependency_form(
        self, scope: Scope, receive: Receive, method: str, headers: Headers, *, marked: bool
    ) -> Answer:
        """Run the application; finish what a route admitted, or pass its answer on."""

        state = scope["state"]
        try:
            captured = await capture(self._app, scope, receive)
        except Exception as error:
            admitted = state.get(ADMITTED_KEY)
            if isinstance(admitted, Admitted):
                return await self._core.fail(admitted, error)
            if isinstance(admitted, PublicAdmitted):
                return self._core.fail_public(admitted, error)
            if marked:
                raise
            return self._core.fail_unadmitted(method, headers, error)
        except BaseException:
            _abandon(state.get(ADMITTED_KEY))
            raise
        answer = state.get(ANSWER_KEY)
        if isinstance(answer, Answer):
            return answer
        admitted = state.get(ADMITTED_KEY)
        if isinstance(admitted, Admitted):
            return await self._core.finish(admitted, captured.status, captured.headers, captured.body)
        if isinstance(admitted, PublicAdmitted):
            return self._core.finish_public(admitted, captured.status, captured.headers, captured.body)
        if marked:
            return Answer(captured.status, captured.headers, captured.body)
        # A declared route answered before its admission ran -- another of its
        # dependencies refused first -- so its answer names the request the
        # caller stated and is signed over it.
        return self._core.sign_stated(method, headers, captured.status, captured.headers, captured.body)

    async def _run(self, admitted: Admitted, scope: Scope, receive: Receive) -> Answer:
        try:
            captured: CapturedResponse = await capture(self._app, scope, receive)
        except Exception as error:
            return await self._core.fail(admitted, error)
        except BaseException:
            _abandon(admitted)
            raise
        return await self._core.finish(admitted, captured.status, captured.headers, captured.body)

    async def _public(
        self, scope: Scope, receive: Receive, method: str, headers: Headers, binding: PublicBinding
    ) -> Answer:
        admitted = self._core.admit_public(method, headers, binding)
        if isinstance(admitted, Answer):
            return admitted
        scope["state"][ADMITTED_KEY] = admitted
        try:
            captured = await capture(self._app, scope, receive)
        except Exception as error:
            return self._core.fail_public(admitted, error)
        return self._core.finish_public(admitted, captured.status, captured.headers, captured.body)

    def _refuse_unserved(
        self, scope: Scope, method: str, headers: Headers, body: bytes, not_served: RouteNotServed
    ) -> Answer:
        # A public operation's request carries no signature to verify, so it is
        # refused over the identity it states; a request carrying signature fields
        # is verified first, so that an unknown profile is still answered as one
        # and a forged signature as invalid.
        stated = stated_request_binding(method=method, headers=headers)
        if stated is not None and is_public_request(headers):
            return self._core.refuse_unserved_public(stated, not_served)
        verified = self._core.verify(method, headers, body, query=received_query(scope))
        if isinstance(verified, Verified):
            return self._core.refuse_unserved(verified, not_served)
        return verified

    def _app_routes(self) -> list[BaseRoute]:
        return list(getattr(self._app, "routes", ()))

    @staticmethod
    async def _send(send: Send, answer: Answer) -> None:
        await send_response(send, answer.status, answer.headers, answer.body)


def _unserved(routes: list[BaseRoute], scope: Scope) -> RouteNotServed | None:
    """Whether no route serves the request, by the application's own matching.

    A path some route serves under other methods is answered 405 naming them.
    """

    allowed: set[str] = set()
    for route in routes:
        match, _ = route.matches(scope)
        if match is Match.FULL:
            return None
        if match is Match.PARTIAL:
            allowed.update(getattr(route, "methods", None) or ())
    return RouteNotServed(allowed_methods=allowed)


def _route_path(routes: list[BaseRoute], scope: Scope) -> str:
    """The path template of the route serving the request."""

    for route in routes:
        match, _ = route.matches(scope)
        if match is Match.FULL:
            return str(getattr(route, "path", scope["path"]))
    return str(scope["path"])


def _abandon(admitted: object) -> None:
    """Stop renewing an attempt whose handler was cancelled.

    Its lease then ends, and an exact retry of a recorded route is told the
    outcome is unknown rather than in progress for as long as the process runs.
    """

    if isinstance(admitted, Admitted) and admitted.renewal is not None:
        admitted.renewal.cancel()
