"""The dispute authority's HTTP API and the double's control routes, over the service.

The routes are thin: each authenticates its caller, hands the request's parts to
``MediationDouble``, and answers its body or its refusal. A call to payments may
wait on the network, so the service runs in Starlette's thread pool, and the
transport-fault middleware runs the classifier, whose filing match may read a
transaction's parties, on a worker thread: nothing waits on payments on the event
loop. Beside the API the double serves the lane doubles' control routes under
``/test/``, authenticated by the fixture control token. The
transport-fault middleware wraps the whole app and leaves the control and health
routes alone.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Awaitable, Callable
from typing import Any

from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool
from starlette.exceptions import HTTPException as StarletteHTTPException

from lane_double_controls import routes as controls
from lane_double_controls.clock import PerceivedClock, WallClock, wall_clock
from lane_double_controls.middleware import TransportFaultMiddleware
from lane_double_controls.models import ClockAdvance, ClockView, ControlError, Rule, Ruling, Status
from market_arkhai_mediation.contract import resource_bytes

from mediation_lane_double.authority import AuthorityFixture
from mediation_lane_double.rules import RuleBook
from mediation_lane_double.service import ApiRefusal, MediationDouble, PaymentsPeer

# The installed contract resources status reports, by their path in the kit wheel.
_CONTRACT = ("mediation.schema.json", "mediation.vectors.json", "publication.json")


async def _control_body(request: Request, model: type[BaseModel]) -> Any:
    try:
        return model.model_validate(json.loads(await request.body()))
    except ValueError as error:
        # A ValidationError is a ValueError, so a body the model refuses lands here too.
        raise ControlError(422, "invalid_request", str(error)) from None


def create_app(authority: AuthorityFixture, payments: PaymentsPeer, *,
               clock: WallClock = wall_clock) -> FastAPI:
    """The double's ASGI app over fresh state, calling ``payments`` as the authority.

    ``clock`` is the wall clock the perceived clock adds its offset to.
    """

    perceived = PerceivedClock(clock)
    rules = RuleBook()
    double = MediationDouble(authority, payments, clock=perceived, rules=rules)
    app = FastAPI(title="mediation lane double", docs_url=None, redoc_url=None,
                  openapi_url=None)
    app.state.double = double
    app.state.clock = perceived
    app.add_middleware(TransportFaultMiddleware, classify=double.fault_for)

    @app.exception_handler(ApiRefusal)
    async def refused(_: Request, exc: ApiRefusal) -> JSONResponse:
        return JSONResponse({"code": exc.code}, status_code=exc.status)

    @app.exception_handler(ControlError)
    async def control_error(_: Request, exc: ControlError) -> JSONResponse:
        return JSONResponse(exc.body(), status_code=exc.status)

    @app.exception_handler(StarletteHTTPException)
    async def unmatched(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        # An unknown path or method still answers with its surface's error body.
        if controls.is_control_path(request.url.path):
            return await control_error(request, ControlError(
                exc.status_code, "invalid_request", "no such control route"))
        return JSONResponse({"code": "invalid_request"}, status_code=exc.status_code)

    @app.exception_handler(Exception)
    async def unexpected(_: Request, __: Exception) -> JSONResponse:
        return JSONResponse({"code": "temporarily_unavailable"}, status_code=500)

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/cases")
    async def file(request: Request) -> Any:
        actor = double.authenticate(request.headers.get("authorization"))
        return await run_in_threadpool(double.file, actor, request.headers.get("idempotency-key"),
                                       await request.body())

    @app.post("/append")
    async def append(request: Request) -> Any:
        actor = double.authenticate(request.headers.get("authorization"))
        return await run_in_threadpool(double.append, actor,
                                       request.headers.get("idempotency-key"),
                                       await request.body())

    @app.get("/cases/{case_ref}")
    async def case(case_ref: str, request: Request) -> Any:
        actor = double.authenticate(request.headers.get("authorization"))
        return await run_in_threadpool(double.case, actor, case_ref)

    @app.get("/record")
    async def record(request: Request) -> Any:
        actor = double.authenticate(request.headers.get("authorization"))
        return await run_in_threadpool(double.record, actor, dict(request.query_params))

    @app.get("/respondent")
    async def respondent(request: Request) -> Any:
        actor = double.authenticate(request.headers.get("authorization"))
        return await run_in_threadpool(double.respondent, actor, dict(request.query_params))

    _add_controls(app, authority, double, perceived, rules)
    return app


def _add_controls(app: FastAPI, authority: AuthorityFixture, double: MediationDouble,
                  perceived: PerceivedClock, rules: RuleBook) -> None:
    """Register a handler for each control route the mediation double serves."""

    def clock_view() -> ClockView:
        return ClockView(perceived_now=perceived(), offset_seconds=perceived.offset)

    async def install(request: Request) -> Response:
        view = rules.install(await _control_body(request, Rule))
        return JSONResponse(view.model_dump(mode="json", exclude_none=True), status_code=201)

    async def listing(request: Request) -> Any:
        return rules.listing().model_dump(mode="json", exclude_none=True)

    async def delete(request: Request) -> Response:
        rules.delete(request.path_params["rule_id"])
        return Response(status_code=204)

    async def resume(request: Request) -> Any:
        view = await run_in_threadpool(double.resume, request.path_params["rule_id"])
        return view.model_dump(mode="json", exclude_none=True)

    async def advance(request: Request) -> Any:
        perceived.advance((await _control_body(request, ClockAdvance)).seconds)
        return clock_view().model_dump(mode="json")

    async def reset(request: Request) -> Any:
        perceived.reset()
        return clock_view().model_dump(mode="json")

    async def status(request: Request) -> Any:
        return Status(perceived_now=perceived(), offset_seconds=perceived.offset, contracts={
            f"contract_data/{name}": hashlib.sha256(resource_bytes(name)).hexdigest()
            for name in _CONTRACT
        }).model_dump(mode="json")

    async def cases(request: Request) -> Any:
        transaction = request.query_params.get("transaction")
        if not transaction:
            raise ControlError(422, "invalid_request", "a case listing names its transaction")
        return (await run_in_threadpool(double.cases, transaction)).model_dump(mode="json")

    async def decide(request: Request) -> Any:
        ruling = await _control_body(request, Ruling)
        view = await run_in_threadpool(double.decide, request.path_params["case_ref"], ruling)
        return view.model_dump(mode="json")

    async def close(request: Request) -> Any:
        view = await run_in_threadpool(double.close_case, request.path_params["case_ref"])
        return view.model_dump(mode="json")

    handlers: dict[controls.ControlRoute, Callable[[Request], Awaitable[Any]]] = {
        controls.RULES: install, controls.RULE_LIST: listing, controls.RULE_DELETE: delete,
        controls.RULE_RESUME: resume, controls.CLOCK_ADVANCE: advance,
        controls.CLOCK_RESET: reset, controls.STATUS: status, controls.CASE_LIST: cases,
        controls.CASE_DECIDE: decide, controls.CASE_CLOSE: close,
    }
    # Every control route the contract gives the mediation double has its handler,
    # so a route the contract adds cannot go unserved.
    if set(handlers) != set(controls.routes_for("mediation")):
        raise RuntimeError("the mediation double serves a different set of control routes "
                           "than the control contract gives it")

    def authorized(handler: Callable[[Request], Awaitable[Any]]
                   ) -> Callable[[Request], Awaitable[Any]]:
        async def endpoint(request: Request) -> Any:
            controls.authorize(request.headers.get("authorization"), authority.control_token)
            return await handler(request)
        return endpoint

    for route, handler in handlers.items():
        app.add_api_route(route.path, authorized(handler), methods=[route.method])
