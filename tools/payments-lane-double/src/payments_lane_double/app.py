"""The payments service's HTTP API, served over the payments kit's engine.

The double mirrors the service's routes, bearer authentication, approval admission,
read authorization, idempotency and error codes, and serves whatever the engine
serves. All state is the engine's, in this process's memory; a restart loses it,
since a run lives only as long as its lane.

Beside the API it serves the lane doubles' control routes under ``/test/``,
authenticated by the fixture control token: rules programming refusals and
transport faults, the perceived clock the engine reads, funding, signer rotation
and status. The transport-fault middleware wraps the whole app and leaves the
control and health routes alone.
"""

from __future__ import annotations

import json
import re
import threading
from collections.abc import Awaitable, Callable, Mapping
from typing import Any

from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException

from lane_double_controls import routes as controls
from lane_double_controls.clock import PerceivedClock, WallClock, wall_clock
from lane_double_controls.middleware import FaultRequest, TransportFaultMiddleware
from lane_double_controls.models import (
    ClockAdvance,
    ClockView,
    ControlError,
    Funded,
    Funding,
    Rule,
    SignerIdentity,
    Status,
)
from market_arkhai_payments.canonical import jcs_sha256, wire_json
from market_arkhai_payments.contracts import get_contract
from market_arkhai_payments.errors import PaymentsAPIError
from market_arkhai_payments.fixtures import PaymentsAuthority
from market_arkhai_payments.models import (
    AccountId,
    ApprovalRequest,
    DealAttachment,
    EventCommand,
    Mandate,
    RequestId,
)
from market_arkhai_payments.receipts import transaction_id

from payments_lane_double.accounts import AccountDirectory, bearer_token
from payments_lane_double.admission import admit
from payments_lane_double.rules import RuleBook

_TRANSACTION_ID = re.compile(r"^[0-9a-f]{64}$")
Clock = Callable[[], int]
# The installed contract resources status reports, by their path in the kit wheel.
_SCHEMA = "schema/payments.schema.json"
_VECTORS = "test-vectors/payments.json"


class PaymentsDouble:
    """The service's behaviour over one engine, free of any web framework.

    Each method takes the authenticated account and the request's parsed parts,
    returns the response body, and refuses with the service's ``PaymentsAPIError``.
    One lock serialises every call, as the engine is not safe to enter twice.
    """

    def __init__(self, directory: AccountDirectory, *, clock: Clock = wall_clock) -> None:
        self.directory = directory
        # Receipts are always signed in test mode, so a live-configured role
        # refuses every receipt the double signs.
        self.engine = PaymentsAuthority(signer=directory.signer(), clock=clock, livemode=False)
        for entry in directory.accounts:
            if entry.funding:
                self.engine.fund(entry.account, directory.asset, entry.funding)
        self._clock = clock
        self._lock = threading.Lock()
        # Every mandate the double approved, by transaction: read authorization
        # and the repeat check need the mandate, which the engine keeps private.
        self._mandates: dict[str, Mandate] = {}

    def authenticate(self, authorization: str | None) -> str:
        token = bearer_token(authorization)
        account = self.directory.account_for_token(token) if token else None
        if account is None:
            raise PaymentsAPIError(401, "authentication_required")
        return account

    def fund(self, funding: Funding) -> Funded:
        """Credit an account in the directory, as the funding control does."""

        if not self.directory.knows(funding.account):
            raise ControlError(404, "account_not_found",
                               f"{funding.account} is not in the double's account directory")
        with self._lock:
            self.engine.fund(funding.account, self.directory.asset, int(funding.amount))
        return Funded(account=funding.account, amount=funding.amount)

    def rotate_signer(self) -> SignerIdentity:
        """Sign every later receipt and snapshot with the fixture's second key."""

        signer = self.directory.rotated_signer()
        with self._lock:
            self.engine.signer = signer
        return SignerIdentity(scheme=signer.identity.scheme.value,
                              identifier=signer.identity.identifier)

    def approve(self, account: str, request: ApprovalRequest) -> Any:
        mandate = request.mandate
        wire = wire_json(mandate)
        if account != wire["from"]:
            raise PaymentsAPIError(403, "caller_not_authorized")
        transaction = transaction_id(mandate)
        with self._lock:
            if transaction not in self._mandates:
                admit(wire, now=self._clock(), directory=self.directory)
            agreement = _agreement(request.attachments or [], wire["deal"])
            # The engine returns an approval it already made before any check of
            # time, funds or attachments, so a repeat gets its original receipt.
            receipt = self.engine.approve(mandate, account=account, agreement=agreement)
            self._mandates[transaction] = mandate
        return wire_json(receipt)

    def snapshot(self, account: str, transaction: str) -> Any:
        with self._lock:
            self._readable(account, transaction)
            signed = self.engine.snapshot(transaction)
        # The verifier frames the snapshot exactly as it was signed, so the body
        # carries every property the signer set and no other.
        return signed.model_dump(mode="json", by_alias=True, exclude_unset=True)

    def mandate(self, account: str, transaction: str) -> Any:
        with self._lock:
            return wire_json(self._readable(account, transaction))

    def attach(self, account: str, transaction: str, attachment: DealAttachment) -> Any:
        with self._lock:
            stored = self.engine.attach_agreement(
                transaction, wire_json(attachment.content), account=account)
        return wire_json(stored)

    def submit(self, account: str, transaction: str, request_id: str,
               command: EventCommand) -> Any:
        with self._lock:
            return self.engine.submit(transaction, {
                "account": account, "requestId": request_id, "event": wire_json(command)})

    def balance(self, caller: str, account: str) -> Any:
        if caller != account:
            raise PaymentsAPIError(403, "caller_not_authorized")
        with self._lock:
            return wire_json(self.engine.balance(account))

    def _readable(self, account: str, transaction: str) -> Mandate:
        mandate = self._mandates.get(transaction)
        if mandate is None:
            raise PaymentsAPIError(404, "transaction_not_found")
        if account not in _readers(wire_json(mandate)):
            raise PaymentsAPIError(403, "caller_not_authorized")
        return mandate


def _readers(mandate: Mapping[str, Any]) -> set[str]:
    """The parties, and every account any part names in any of its authorities."""

    readers = {mandate["from"], mandate["to"]}
    for part in mandate["parts"]:
        for entries in part["authorities"].values():
            readers.update(entry["account"] if isinstance(entry, dict) else entry
                           for entry in entries)
    return readers


def _agreement(attachments: list[DealAttachment], deal: str) -> Any:
    """The Agreement the engine stores with a new approval, or ``None``.

    Every deal attachment must hash to the mandate's deal. Handing the engine one
    that does not, when there is one, lets it refuse with ``deal_mismatch`` at the
    point in its order where the service does, after the funds check.
    """

    contents = [wire_json(attachment.content) for attachment in attachments]
    for content in contents:
        if jcs_sha256(content) != deal:
            return content
    return contents[0] if contents else None


def _error(status: int, code: str) -> JSONResponse:
    return JSONResponse({"error": code}, status_code=status)


async def _body(request: Request, model: type[BaseModel]) -> Any:
    try:
        return model.model_validate(json.loads(await request.body()))
    except (ValueError, ValidationError):
        raise PaymentsAPIError(400, "invalid_request") from None


def _transaction(value: str) -> str:
    if not _TRANSACTION_ID.fullmatch(value):
        raise PaymentsAPIError(400, "invalid_request")
    return value


async def _fault_request(request: Request) -> FaultRequest:
    return FaultRequest(method=request.method, path=request.url.path,
                        headers={name.lower(): value for name, value in request.headers.items()},
                        body=await request.body())


async def _control_body(request: Request, model: type[BaseModel]) -> Any:
    try:
        return model.model_validate(json.loads(await request.body()))
    except ValueError as error:
        # A ValidationError is a ValueError, so a body the model refuses lands here too.
        raise ControlError(422, "invalid_request", str(error)) from None


def create_app(directory: AccountDirectory, *, clock: WallClock = wall_clock) -> FastAPI:
    """The double's ASGI app over a fresh engine funded from ``directory``.

    ``clock`` is the wall clock the perceived clock adds its offset to.
    """

    perceived = PerceivedClock(clock)
    double = PaymentsDouble(directory, clock=perceived)
    rules = RuleBook(directory)
    app = FastAPI(title="payments lane double", docs_url=None, redoc_url=None,
                  openapi_url=None)
    app.state.double = double
    app.state.clock = perceived
    app.state.rules = rules
    app.add_middleware(TransportFaultMiddleware, classify=rules.fault_for)

    @app.exception_handler(PaymentsAPIError)
    async def payments_error(_: Request, exc: PaymentsAPIError) -> JSONResponse:
        return _error(exc.status_code, exc.code)

    @app.exception_handler(ControlError)
    async def control_error(_: Request, exc: ControlError) -> JSONResponse:
        return JSONResponse(exc.body(), status_code=exc.status)

    @app.exception_handler(StarletteHTTPException)
    async def unmatched(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        # An unknown path or method still answers with its surface's error body.
        if controls.is_control_path(request.url.path):
            return await control_error(request, ControlError(
                exc.status_code, "invalid_request", "no such control route"))
        return _error(exc.status_code, "invalid_request")

    @app.exception_handler(Exception)
    async def unexpected(_: Request, __: Exception) -> JSONResponse:
        return _error(500, "internal_error")

    async def caller(request: Request) -> str:
        account = double.authenticate(request.headers.get("authorization"))
        rules.refuse_if_programmed(await _fault_request(request))
        return account

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/transactions")
    async def approve(request: Request) -> Any:
        account = await caller(request)
        return double.approve(account, await _body(request, ApprovalRequest))

    @app.get("/transactions/{transaction}")
    async def snapshot(transaction: str, request: Request) -> Any:
        account = await caller(request)
        return double.snapshot(account, _transaction(transaction))

    @app.get("/transactions/{transaction}/mandate")
    async def mandate(transaction: str, request: Request) -> Any:
        account = await caller(request)
        return double.mandate(account, _transaction(transaction))

    @app.post("/transactions/{transaction}/attachments")
    async def attach(transaction: str, request: Request) -> Any:
        account = await caller(request)
        identifier = _transaction(transaction)
        return double.attach(account, identifier, await _body(request, DealAttachment))

    @app.post("/transactions/{transaction}/events")
    async def submit(transaction: str, request: Request) -> Any:
        account = await caller(request)
        identifier = _transaction(transaction)
        try:
            request_id = RequestId.model_validate(request.headers.get("idempotency-key")).root
        except ValidationError:
            raise PaymentsAPIError(400, "invalid_request") from None
        return double.submit(account, identifier, request_id,
                             await _body(request, EventCommand))

    @app.get("/balances/{account}")
    async def balance(account: str, request: Request) -> Any:
        authenticated = await caller(request)
        try:
            identifier = AccountId.model_validate(account).root
        except ValidationError:
            raise PaymentsAPIError(400, "invalid_request") from None
        return double.balance(authenticated, identifier)

    _add_controls(app, directory, double, perceived, rules)
    return app


def _add_controls(app: FastAPI, directory: AccountDirectory, double: PaymentsDouble,
                  perceived: PerceivedClock, rules: RuleBook) -> None:
    """Register a handler for each control route the payments double serves."""

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

    async def advance(request: Request) -> Any:
        perceived.advance((await _control_body(request, ClockAdvance)).seconds)
        return clock_view().model_dump(mode="json")

    async def reset(request: Request) -> Any:
        perceived.reset()
        return clock_view().model_dump(mode="json")

    async def status(request: Request) -> Any:
        metadata = get_contract().metadata
        return Status(perceived_now=perceived(), offset_seconds=perceived.offset, contracts={
            _SCHEMA: metadata["schema_sha256"], _VECTORS: metadata["vectors_sha256"],
        }).model_dump(mode="json")

    async def fund(request: Request) -> Any:
        return double.fund(await _control_body(request, Funding)).model_dump(mode="json")

    async def rotate(request: Request) -> Any:
        return double.rotate_signer().model_dump(mode="json")

    handlers: dict[controls.ControlRoute, Callable[[Request], Awaitable[Any]]] = {
        controls.RULES: install, controls.RULE_LIST: listing, controls.RULE_DELETE: delete,
        controls.CLOCK_ADVANCE: advance, controls.CLOCK_RESET: reset, controls.STATUS: status,
        controls.FUNDING: fund, controls.SIGNER_ROTATE: rotate,
    }
    # Every control route the contract gives the payments double has its handler,
    # so a route the contract adds cannot go unserved.
    if set(handlers) != set(controls.routes_for("payments")):
        raise RuntimeError("the payments double serves a different set of control routes "
                           "than the control contract gives it")

    def authorized(handler: Callable[[Request], Awaitable[Any]]
                   ) -> Callable[[Request], Awaitable[Any]]:
        async def endpoint(request: Request) -> Any:
            controls.authorize(request.headers.get("authorization"), directory.control_token)
            return await handler(request)
        return endpoint

    for route, handler in handlers.items():
        app.add_api_route(route.path, authorized(handler), methods=[route.method])
