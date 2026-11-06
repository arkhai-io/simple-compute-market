"""The payments service's HTTP API, served over the payments kit's engine.

The double mirrors the service's routes, bearer authentication, approval admission,
read authorization, idempotency and error codes, and serves whatever the engine
serves. All state is the engine's, in this process's memory; a restart loses it,
since a run lives only as long as its lane.
"""

from __future__ import annotations

import json
import re
import threading
import time
from collections.abc import Callable, Mapping
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException

from market_arkhai_payments.canonical import jcs_sha256, wire_json
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

from payments_lane_double.accounts import AccountDirectory
from payments_lane_double.admission import admit

_TRANSACTION_ID = re.compile(r"^[0-9a-f]{64}$")
# The scheme name is case-insensitive (RFC 7235); a token never holds whitespace,
# which the account fixture refuses.
_BEARER = re.compile(r"^bearer (\S+)$", re.IGNORECASE)
Clock = Callable[[], int]


def wall_clock() -> int:
    return int(time.time())


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
        match = _BEARER.fullmatch(authorization or "")
        account = self.directory.account_for_token(match.group(1)) if match else None
        if account is None:
            raise PaymentsAPIError(401, "authentication_required")
        return account

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


def create_app(directory: AccountDirectory, *, clock: Clock = wall_clock) -> FastAPI:
    """The double's ASGI app over a fresh engine funded from ``directory``."""

    double = PaymentsDouble(directory, clock=clock)
    app = FastAPI(title="payments lane double", docs_url=None, redoc_url=None,
                  openapi_url=None)
    app.state.double = double

    @app.exception_handler(PaymentsAPIError)
    async def payments_error(_: Request, exc: PaymentsAPIError) -> JSONResponse:
        return _error(exc.status_code, exc.code)

    @app.exception_handler(StarletteHTTPException)
    async def unmatched(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        # An unknown path or method still answers with the published error body.
        return _error(exc.status_code, "invalid_request")

    @app.exception_handler(Exception)
    async def unexpected(_: Request, __: Exception) -> JSONResponse:
        return _error(500, "internal_error")

    def caller(request: Request) -> str:
        return double.authenticate(request.headers.get("authorization"))

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/transactions")
    async def approve(request: Request) -> Any:
        account = caller(request)
        return double.approve(account, await _body(request, ApprovalRequest))

    @app.get("/transactions/{transaction}")
    async def snapshot(transaction: str, request: Request) -> Any:
        account = caller(request)
        return double.snapshot(account, _transaction(transaction))

    @app.get("/transactions/{transaction}/mandate")
    async def mandate(transaction: str, request: Request) -> Any:
        account = caller(request)
        return double.mandate(account, _transaction(transaction))

    @app.post("/transactions/{transaction}/attachments")
    async def attach(transaction: str, request: Request) -> Any:
        account = caller(request)
        identifier = _transaction(transaction)
        return double.attach(account, identifier, await _body(request, DealAttachment))

    @app.post("/transactions/{transaction}/events")
    async def submit(transaction: str, request: Request) -> Any:
        account = caller(request)
        identifier = _transaction(transaction)
        try:
            request_id = RequestId.model_validate(request.headers.get("idempotency-key")).root
        except ValidationError:
            raise PaymentsAPIError(400, "invalid_request") from None
        return double.submit(account, identifier, request_id,
                             await _body(request, EventCommand))

    @app.get("/balances/{account}")
    async def balance(account: str, request: Request) -> Any:
        authenticated = caller(request)
        try:
            identifier = AccountId.model_validate(account).root
        except ValidationError:
            raise PaymentsAPIError(400, "invalid_request") from None
        return double.balance(authenticated, identifier)

    return app
