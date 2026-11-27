"""The dependency form: a route that admits its requests inside the application.

A route takes its declaration as a dependency,
``Depends(RouteAdmission(core, operation=..., roles=..., exact_retry=...))``, and
receives the :class:`Admitted` request; a refusal never reaches its handler. A route
whose operation acts on one object names how it derives that object's identifier as
``resource=``; one given none declares that its operation has no target. A public
operation's route takes ``Depends(PublicAdmission(core, operation=...))`` instead,
and receives the request identity its answer is signed over. The route inventory
finds every route taking either through the framework's own dependency tree.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import NoReturn

from market_identity import ExactRetry
from starlette.exceptions import HTTPException
from starlette.requests import Request

from market_authenticated_requests.application import ADMITTED_KEY, ANSWER_KEY, BODY_KEY, received_query
from market_authenticated_requests.core import Admitted, AdmissionCore, Answer, PublicAdmitted
from market_authenticated_requests.routes import PublicBinding, ResourceOf, ResourceUnbound, RouteBinding


class RouteAdmission:
    """One route's declaration, admitting each of its requests when called."""

    def __init__(
        self,
        core: AdmissionCore,
        *,
        operation: str,
        roles: Iterable[str],
        exact_retry: ExactRetry,
        resource: ResourceOf | None = None,
    ) -> None:
        # Validated here, where the route is declared, so a route missing its
        # resolution fails as its module is imported.
        RouteBinding(operation=operation, resource=None, roles=frozenset(roles), exact_retry=exact_retry)
        self.core = core
        self.operation = operation
        self.roles = frozenset(roles)
        self.exact_retry = exact_retry
        self._resource = resource

    async def __call__(self, request: Request) -> Admitted:
        state = request.scope.get("state", {})
        if BODY_KEY not in state:
            raise RuntimeError(
                f"route {self.operation} admits through the admission core, "
                "but the core's application wrapper is not installed"
            )
        body: bytes = state[BODY_KEY]
        try:
            resource = None if self._resource is None else self._resource(dict(request.path_params), body)
        except ResourceUnbound as unbound:
            refused = self.core.verify(request.method, request.headers, body, query=received_query(request.scope))
            self._refuse(
                state,
                refused
                if isinstance(refused, Answer)
                else self.core.refuse_unbound(refused, unbound, operation=self.operation),
            )
        binding = RouteBinding(
            operation=self.operation, resource=resource, roles=self.roles, exact_retry=self.exact_retry
        )
        verified = self.core.verify(
            request.method, request.headers, body, query=received_query(request.scope), route=binding
        )
        if isinstance(verified, Answer):
            self._refuse(state, verified)
        admitted = self.core.admit(verified, binding)
        if isinstance(admitted, Answer):
            self._refuse(state, admitted)
        state[ADMITTED_KEY] = admitted
        return admitted

    @staticmethod
    def _refuse(state: dict[str, object], answer: Answer) -> NoReturn:
        _refuse(state, answer)


class PublicAdmission:
    """A public operation's route, admitting each of its requests when called.

    The operation acts on no target and admits no role: its request carries a
    request identity and no signature, and nothing is reserved.
    """

    def __init__(self, core: AdmissionCore, *, operation: str) -> None:
        self.core = core
        self.binding = PublicBinding(operation)

    async def __call__(self, request: Request) -> PublicAdmitted:
        state = request.scope.get("state", {})
        if BODY_KEY not in state:
            raise RuntimeError(
                f"public route {self.binding.operation} admits through the admission core, "
                "but the core's application wrapper is not installed"
            )
        admitted = self.core.admit_public(request.method, request.headers, self.binding)
        if isinstance(admitted, Answer):
            _refuse(state, admitted)
        state[ADMITTED_KEY] = admitted
        return admitted


def _refuse(state: dict[str, object], answer: Answer) -> NoReturn:
    # The application wrapper sends the signed answer in place of whatever the
    # framework renders for this exception.
    state[ANSWER_KEY] = answer
    raise HTTPException(status_code=answer.status)
