"""Credentialed transport for the trusted RFQ account entry point."""

import re
from typing import Self, TypeVar
from uuid import uuid4

import httpx
from market_core.rfq import (
    CloseRfq,
    CreateRfq,
    EditRfq,
    OfferResponse,
    ResponseVersion,
    RfqAccountRequest,
    RfqAudience,
    RfqDetail,
    RfqInput,
    RfqIntroductionDetail,
    RfqMutationReceipt,
    RfqOperation,
    RfqResponseDetail,
    RfqResponseInbox,
    RfqSearchPage,
    RfqSummary,
    RfqTarget,
    SearchRfqs,
    ShareContact,
    rfq_route_models,
    validate_rfq_provenance,
)
from market_identity import Identity, TrustedIdentitySet
from pydantic import BaseModel, ValidationError

from registry_client.auth import verify_registry_response_context
from registry_client.rfq_registry import RFQ_PROOF_HEADERS

_CODE = re.compile(r"(?:rfq_|stale_rfq_|invalid_rfq_|contact_sharing_)[a-z0-9_]{1,100}")
_Outcome = TypeVar("_Outcome", bound=BaseModel)
_AMBIGUOUS = (
    httpx.DecodingError, httpx.ReadError, httpx.ReadTimeout, httpx.RemoteProtocolError,
    httpx.WriteError, httpx.WriteTimeout,
)
_UNSIGNED_CODES = {
    400: "rfq_invalid_request",
    401: "rfq_auth_required",
    403: "rfq_account_forbidden",
    422: "rfq_invalid_request",
    502: "rfq_registry_unavailable",
    503: "rfq_account_unavailable",
}
_UNSIGNED_DETAILS = {
    (403, "rfq_contact_permission_required"),
    (403, "rfq_csrf_required"),
    (403, "rfq_registry_audience_refused"),
    (422, "rfq_contact_consent_required"),
}

class RfqAccountError(Exception):
    """An RFQ operation refusal or a transport failure with a safe retry ID."""

    def __init__(self, code: str, request_id: str, status: int | None = None):
        self.code = code
        self.request_id = request_id
        self.status = status
        super().__init__(f"{code} (RFQ request {request_id})")


class SyncRfqAccountClient:
    """Submit account operations to one configured origin and verify its registry replies."""

    def __init__(
        self,
        base_url: str,
        *,
        credential: str | None = None,
        registry: RfqAudience,
        transport: httpx.BaseTransport | None = None,
        timeout: float = 30.0,
    ):
        try:
            url = httpx.URL(base_url)
        except httpx.InvalidURL:
            raise ValueError("invalid trusted RFQ account origin") from None
        local_http = url.scheme == "http" and url.host in {"127.0.0.1", "::1", "localhost"}
        if ((url.scheme != "https" and not local_http) or not url.host
                or url.userinfo or url.query or url.fragment or url.path not in {"", "/"}):
            raise ValueError("invalid trusted RFQ account origin")
        if credential is not None and (not credential or any(not 33 <= ord(char) <= 126 for char in credential)):
            raise ValueError("invalid RFQ account credential")
        self._authenticated = credential is not None
        self._registry = registry
        self._pins = TrustedIdentitySet(
            identities=(Identity.model_validate(registry.principal.model_dump(mode="json")),),
        )
        self._http = httpx.Client(
            base_url=url, headers={"Authorization": f"Bearer {credential}"} if credential is not None else None,
            follow_redirects=False, transport=transport, timeout=timeout,
        )

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *exc: object) -> None:
        self._http.close()

    def exchange(
        self, target: RfqTarget, inputs: RfqInput, *, request_id: str | None = None,
    ) -> BaseModel:
        """Exchange typed inputs and retry once if delivery could have succeeded."""
        models = rfq_route_models(target.operation)
        if type(inputs) is not models.inputs:
            raise TypeError("invalid input model for RFQ operation")
        outcome = RfqSummary if not self._authenticated and target.operation is RfqOperation.READ else models.outcome
        return self._exchange(target, inputs, outcome, request_id)

    def _exchange(
        self, target: RfqTarget, inputs: RfqInput, outcome: type[_Outcome], request_id: str | None,
    ) -> _Outcome:
        request = RfqAccountRequest(
            registry=self._registry, request_id=uuid4().hex if request_id is None else request_id,
            inputs=inputs.model_dump(mode="json"),
        )
        if not self._authenticated and target.operation not in {RfqOperation.SEARCH, RfqOperation.READ}:
            raise RfqAccountError("rfq_auth_required", request.request_id, 401)
        try:
            wire = request.model_dump_json().encode()
        except ValueError:
            raise RfqAccountError("rfq_invalid_inputs", request.request_id, 422) from None
        try:
            try:
                response = self._http.post(
                    target.path, content=wire, headers={"Content-Type": "application/json"},
                )
            except _AMBIGUOUS:
                response = self._http.post(
                    target.path, content=wire, headers={"Content-Type": "application/json"},
                )
        except httpx.RequestError:
            raise RfqAccountError("rfq_account_transport_failed", request.request_id) from None
        return self._outcome(target, request.request_id, response, outcome)

    def _outcome(
        self, target: RfqTarget, request_id: str, response: httpx.Response, outcome: type[_Outcome],
    ) -> _Outcome:
        status = response.status_code
        has_proof = any(name in response.headers for name in RFQ_PROOF_HEADERS)
        try:
            body = response.json()
        except ValueError:
            if has_proof:
                raise RfqAccountError("rfq_invalid_registry_reply", request_id, status) from None
            body = None
        if not has_proof:
            code = _UNSIGNED_CODES.get(status, "rfq_invalid_account_reply")
            detail = body.get("detail") if isinstance(body, dict) else None
            if isinstance(detail, str) and (status, detail) in _UNSIGNED_DETAILS:
                code = detail
            if (status == 404 and body == {"detail": "Not Found"}) or (
                status == 501 and body == {"detail": "rfq_not_supported"}
            ):
                code = "rfq_not_supported"
            raise RfqAccountError(code, request_id, status)
        try:
            verify_registry_response_context(
                headers=response.headers, expected_registries=self._pins, method=target.method,
                operation=target.operation.value, resource=target.resource,
                request_id=request_id, status=status, body=body,
            )
        except (ValueError, TypeError):
            raise RfqAccountError("rfq_invalid_registry_reply", request_id, status) from None
        if status != 200:
            detail = body.get("detail") if isinstance(body, dict) else None
            if status == 503 and detail == "rfq_not_available":
                detail = "rfq_not_supported"
            if not isinstance(detail, str) or not _CODE.fullmatch(detail):
                detail = "rfq_registry_refused"
            raise RfqAccountError(detail, request_id, status)
        try:
            result = outcome.model_validate(body)
            validate_rfq_provenance(target, self._registry, result)
        except (ValidationError, ValueError):
            raise RfqAccountError("rfq_invalid_registry_reply", request_id, status) from None
        return result

    def create(
        self, inputs: CreateRfq, *, request_id: str | None = None,
    ) -> RfqMutationReceipt:
        return self._exchange(RfqTarget(RfqOperation.CREATE), inputs, RfqMutationReceipt, request_id)

    def search(
        self, inputs: SearchRfqs, *, request_id: str | None = None,
    ) -> RfqSearchPage:
        return self._exchange(RfqTarget(RfqOperation.SEARCH), inputs, RfqSearchPage, request_id)

    def read(self, rfq_id: str, *, request_id: str | None = None) -> RfqSummary:
        if self._authenticated:
            return self.read_detail(rfq_id, request_id=request_id)
        return self._exchange(RfqTarget(RfqOperation.READ, rfq_id), RfqInput(), RfqSummary, request_id)

    def read_detail(
        self, rfq_id: str, *, request_id: str | None = None,
    ) -> RfqDetail:
        request_id = uuid4().hex if request_id is None else request_id
        if not self._authenticated:
            raise RfqAccountError("rfq_auth_required", request_id, 401)
        return self._exchange(
            RfqTarget(RfqOperation.READ, rfq_id), RfqInput(), RfqDetail, request_id,
        )

    def edit(
        self, rfq_id: str, inputs: EditRfq, *, request_id: str | None = None,
    ) -> RfqMutationReceipt:
        return self._exchange(
            RfqTarget(RfqOperation.EDIT, rfq_id), inputs, RfqMutationReceipt, request_id,
        )

    def close(
        self, rfq_id: str, inputs: CloseRfq, *, request_id: str | None = None,
    ) -> RfqMutationReceipt:
        return self._exchange(
            RfqTarget(RfqOperation.CLOSE, rfq_id), inputs, RfqMutationReceipt, request_id,
        )

    def respond(
        self, rfq_id: str, inputs: OfferResponse,
        *, request_id: str | None = None,
    ) -> RfqMutationReceipt:
        return self._exchange(
            RfqTarget(RfqOperation.RESPOND, rfq_id), inputs, RfqMutationReceipt, request_id,
        )

    def response_inbox(
        self, rfq_id: str,
        *, request_id: str | None = None,
    ) -> RfqResponseInbox:
        return self._exchange(
            RfqTarget(RfqOperation.LIST_RESPONSES, rfq_id), RfqInput(), RfqResponseInbox, request_id,
        )

    def read_response(
        self, rfq_id: str, response_id: str,
        *, request_id: str | None = None,
    ) -> RfqResponseDetail:
        return self._exchange(
            RfqTarget(RfqOperation.READ_RESPONSE, rfq_id, response_id), RfqInput(), RfqResponseDetail, request_id,
        )

    def reconfirm(
        self, rfq_id: str, response_id: str, inputs: OfferResponse,
        *, request_id: str | None = None,
    ) -> RfqMutationReceipt:
        return self._exchange(
            RfqTarget(RfqOperation.RECONFIRM, rfq_id, response_id), inputs, RfqMutationReceipt, request_id,
        )

    def withdraw(
        self, rfq_id: str, response_id: str, inputs: ResponseVersion,
        *, request_id: str | None = None,
    ) -> RfqMutationReceipt:
        return self._exchange(
            RfqTarget(RfqOperation.WITHDRAW, rfq_id, response_id), inputs, RfqMutationReceipt, request_id,
        )

    def dismiss(
        self, rfq_id: str, response_id: str, inputs: ResponseVersion,
        *, request_id: str | None = None,
    ) -> RfqMutationReceipt:
        return self._exchange(
            RfqTarget(RfqOperation.DISMISS, rfq_id, response_id), inputs, RfqMutationReceipt, request_id,
        )

    def select(
        self, rfq_id: str, response_id: str, inputs: ShareContact,
        *, request_id: str | None = None,
    ) -> RfqMutationReceipt:
        return self._exchange(
            RfqTarget(RfqOperation.SELECT, rfq_id, response_id), inputs, RfqMutationReceipt, request_id,
        )

    def read_introduction(
        self, introduction_id: str,
        *, request_id: str | None = None,
    ) -> RfqIntroductionDetail:
        return self._exchange(
            RfqTarget(RfqOperation.READ_INTRODUCTION, introduction_id=introduction_id), RfqInput(), RfqIntroductionDetail, request_id,
        )

    def end_introduction(
        self, introduction_id: str, inputs: ResponseVersion,
        *, request_id: str | None = None,
    ) -> RfqMutationReceipt:
        return self._exchange(
            RfqTarget(RfqOperation.END_INTRODUCTION, introduction_id=introduction_id), inputs, RfqMutationReceipt, request_id,
        )
