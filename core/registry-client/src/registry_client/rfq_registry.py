"""Authority-side typed transport for a pinned registry's RFQ routes."""

import re
from dataclasses import dataclass, field
from typing import Self, TypeVar

import httpx
from market_core.rfq import (
    CloseRfq,
    CreateRfq,
    EditRfq,
    OfferResponse,
    ResponseVersion,
    RfqAccountClaim,
    RfqAccountRequest,
    RfqAudience,
    RfqDetail,
    RfqInput,
    RfqIntroductionDetail,
    RfqInvocation,
    RfqMutationReceipt,
    RfqOperation,
    RfqResponseDetail,
    RfqResponseInbox,
    RfqSearchPage,
    RfqTarget,
    SearchRfqs,
    ShareContact,
    rfq_route_models,
    validate_rfq_provenance,
)
from market_identity import Signer
from pydantic import BaseModel, JsonValue

from registry_client.auth import (
    IDENTITY_IDENTIFIER_HEADER,
    IDENTITY_SCHEME_HEADER,
    REQUEST_ID_HEADER,
    ROLE_HEADER,
    SIGNATURE_HEADER,
    SIGNATURE_VERSION_HEADER,
    TIMESTAMP_HEADER,
    RegistryClientError,
)
from registry_client.rfq_auth import SignedRfqRequest, sign_rfq_invocation

_Outcome = TypeVar("_Outcome", bound=BaseModel)
_ErrorCode = re.compile(r"[a-z][a-z0-9_]{0,127}")


RFQ_PROOF_HEADERS = (
    SIGNATURE_VERSION_HEADER, IDENTITY_SCHEME_HEADER, IDENTITY_IDENTIFIER_HEADER,
    ROLE_HEADER, REQUEST_ID_HEADER, TIMESTAMP_HEADER, SIGNATURE_HEADER,
)


@dataclass(frozen=True)
class RfqRegistryReply:
    """A registry result the account entry point can return to its client."""

    status: int
    body: JsonValue = field(repr=False)
    proof: dict[str, str]


class _RfqRegistryProtocol:
    def __init__(self, signer: Signer, audience: RfqAudience):
        self._signer = signer
        self._audience = audience

    def _sign(
        self, target: RfqTarget, account: RfqAccountClaim, inputs: RfqInput, request_id: str | None,
    ) -> SignedRfqRequest:
        return sign_rfq_invocation(
            signer=self._signer, target=target, request_id=request_id,
            invocation=RfqInvocation(
                account=account, audience=self._audience, inputs=inputs.model_dump(mode="json"),
            ),
        )

    def _decode(
        self, target: RfqTarget, signed: SignedRfqRequest, response: httpx.Response, outcome: type[_Outcome],
    ) -> _Outcome:
        body = response.json()
        signed.verify_response(response.headers, status=response.status_code, body=body)
        if response.status_code != 200:
            code = body.get("detail") if isinstance(body, dict) else None
            if not isinstance(code, str) or not _ErrorCode.fullmatch(code):
                code = "rfq_registry_refused"
            raise RegistryClientError(target.method, target.path, response.status_code, code)
        result = outcome.model_validate(body)
        validate_rfq_provenance(target, self._audience, result)
        return result


    def _sign_forward(
        self, target: RfqTarget, account: RfqAccountClaim, request: RfqAccountRequest,
    ) -> SignedRfqRequest:
        if request.registry != self._audience:
            raise ValueError("invalid RFQ registry audience")
        inputs = rfq_route_models(target.operation).inputs.model_validate(request.inputs)
        return self._sign(target, account, inputs, request.request_id)

    def _verified_reply(
        self, target: RfqTarget, signed: SignedRfqRequest, response: httpx.Response,
    ) -> RfqRegistryReply:
        body = response.json()
        if (response.status_code == 404 and SIGNATURE_HEADER not in response.headers
                and body == {"detail": "Not Found"}):
            # An older registry has no RFQ route and cannot sign this refusal.
            return RfqRegistryReply(501, {"detail": "rfq_not_supported"}, {})
        signed.verify_response(response.headers, status=response.status_code, body=body)
        if response.status_code == 200:
            result = rfq_route_models(target.operation).outcome.model_validate(body)
            validate_rfq_provenance(target, self._audience, result)
        return RfqRegistryReply(
            response.status_code, body, {name: response.headers[name] for name in RFQ_PROOF_HEADERS},
        )


class RfqRegistryClient(_RfqRegistryProtocol):
    """Sign admitted account operations and verify each pinned registry reply."""

    def __init__(
        self,
        base_url: str,
        *,
        signer: Signer,
        audience: RfqAudience,
        transport: httpx.AsyncBaseTransport | None = None,
        timeout: float = 30.0,
    ):
        super().__init__(signer, audience)
        self._http = httpx.AsyncClient(base_url=base_url, transport=transport, timeout=timeout)

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.close_transport()

    async def close_transport(self) -> None:
        await self._http.aclose()

    async def _exchange(
        self, target: RfqTarget, account: RfqAccountClaim, inputs: RfqInput,
        outcome: type[_Outcome], request_id: str | None,
    ) -> _Outcome:
        signed = self._sign(target, account, inputs, request_id)
        response = await self._http.post(target.path, headers=signed.headers(), json=signed.body())
        return self._decode(target, signed, response, outcome)

    async def forward(
        self, target: RfqTarget, account: RfqAccountClaim, request: RfqAccountRequest,
    ) -> RfqRegistryReply:
        """Forward after the account entry point admits the current credential."""
        signed = self._sign_forward(target, account, request)
        response = await self._http.post(target.path, headers=signed.headers(), json=signed.body())
        return self._verified_reply(target, signed, response)

    async def create(
        self, account: RfqAccountClaim, inputs: CreateRfq, *, request_id: str | None = None,
    ) -> RfqMutationReceipt:
        return await self._exchange(RfqTarget(RfqOperation.CREATE), account, inputs, RfqMutationReceipt, request_id)

    async def search(
        self, account: RfqAccountClaim, inputs: SearchRfqs, *, request_id: str | None = None,
    ) -> RfqSearchPage:
        return await self._exchange(RfqTarget(RfqOperation.SEARCH), account, inputs, RfqSearchPage, request_id)

    async def read(
        self, account: RfqAccountClaim, rfq_id: str, *, request_id: str | None = None,
    ) -> RfqDetail:
        return await self._exchange(
            RfqTarget(RfqOperation.READ, rfq_id), account, RfqInput(), RfqDetail, request_id,
        )

    async def edit(
        self, account: RfqAccountClaim, rfq_id: str, inputs: EditRfq, *, request_id: str | None = None,
    ) -> RfqMutationReceipt:
        return await self._exchange(
            RfqTarget(RfqOperation.EDIT, rfq_id), account, inputs, RfqMutationReceipt, request_id,
        )

    async def close(
        self, account: RfqAccountClaim, rfq_id: str, inputs: CloseRfq, *, request_id: str | None = None,
    ) -> RfqMutationReceipt:
        return await self._exchange(
            RfqTarget(RfqOperation.CLOSE, rfq_id), account, inputs, RfqMutationReceipt, request_id,
        )

    async def respond(
        self, account: RfqAccountClaim, rfq_id: str, inputs: OfferResponse,
        *, request_id: str | None = None,
    ) -> RfqMutationReceipt:
        return await self._exchange(
            RfqTarget(RfqOperation.RESPOND, rfq_id), account, inputs, RfqMutationReceipt, request_id,
        )

    async def response_inbox(
        self, account: RfqAccountClaim, rfq_id: str,
        *, request_id: str | None = None,
    ) -> RfqResponseInbox:
        return await self._exchange(
            RfqTarget(RfqOperation.LIST_RESPONSES, rfq_id), account, RfqInput(), RfqResponseInbox, request_id,
        )

    async def read_response(
        self, account: RfqAccountClaim, rfq_id: str, response_id: str,
        *, request_id: str | None = None,
    ) -> RfqResponseDetail:
        return await self._exchange(
            RfqTarget(RfqOperation.READ_RESPONSE, rfq_id, response_id), account, RfqInput(), RfqResponseDetail, request_id,
        )

    async def reconfirm(
        self, account: RfqAccountClaim, rfq_id: str, response_id: str, inputs: OfferResponse,
        *, request_id: str | None = None,
    ) -> RfqMutationReceipt:
        return await self._exchange(
            RfqTarget(RfqOperation.RECONFIRM, rfq_id, response_id), account, inputs, RfqMutationReceipt, request_id,
        )

    async def withdraw(
        self, account: RfqAccountClaim, rfq_id: str, response_id: str, inputs: ResponseVersion,
        *, request_id: str | None = None,
    ) -> RfqMutationReceipt:
        return await self._exchange(
            RfqTarget(RfqOperation.WITHDRAW, rfq_id, response_id), account, inputs, RfqMutationReceipt, request_id,
        )

    async def dismiss(
        self, account: RfqAccountClaim, rfq_id: str, response_id: str, inputs: ResponseVersion,
        *, request_id: str | None = None,
    ) -> RfqMutationReceipt:
        return await self._exchange(
            RfqTarget(RfqOperation.DISMISS, rfq_id, response_id), account, inputs, RfqMutationReceipt, request_id,
        )

    async def select(
        self, account: RfqAccountClaim, rfq_id: str, response_id: str, inputs: ShareContact,
        *, request_id: str | None = None,
    ) -> RfqMutationReceipt:
        return await self._exchange(
            RfqTarget(RfqOperation.SELECT, rfq_id, response_id), account, inputs, RfqMutationReceipt, request_id,
        )

    async def read_introduction(
        self, account: RfqAccountClaim, introduction_id: str,
        *, request_id: str | None = None,
    ) -> RfqIntroductionDetail:
        return await self._exchange(
            RfqTarget(RfqOperation.READ_INTRODUCTION, introduction_id=introduction_id), account, RfqInput(), RfqIntroductionDetail, request_id,
        )

    async def end_introduction(
        self, account: RfqAccountClaim, introduction_id: str, inputs: ResponseVersion,
        *, request_id: str | None = None,
    ) -> RfqMutationReceipt:
        return await self._exchange(
            RfqTarget(RfqOperation.END_INTRODUCTION, introduction_id=introduction_id), account, inputs, RfqMutationReceipt, request_id,
        )


class SyncRfqRegistryClient(_RfqRegistryProtocol):
    """Synchronous transport for the same signed RFQ operations."""

    def __init__(
        self,
        base_url: str,
        *,
        signer: Signer,
        audience: RfqAudience,
        transport: httpx.BaseTransport | None = None,
        timeout: float = 30.0,
    ):
        super().__init__(signer, audience)
        self._http = httpx.Client(base_url=base_url, transport=transport, timeout=timeout)

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close_transport()

    def close_transport(self) -> None:
        self._http.close()

    def _exchange(
        self, target: RfqTarget, account: RfqAccountClaim, inputs: RfqInput,
        outcome: type[_Outcome], request_id: str | None,
    ) -> _Outcome:
        signed = self._sign(target, account, inputs, request_id)
        response = self._http.post(target.path, headers=signed.headers(), json=signed.body())
        return self._decode(target, signed, response, outcome)

    def forward(
        self, target: RfqTarget, account: RfqAccountClaim, request: RfqAccountRequest,
    ) -> RfqRegistryReply:
        """Forward after the account entry point admits the current credential."""
        signed = self._sign_forward(target, account, request)
        response = self._http.post(target.path, headers=signed.headers(), json=signed.body())
        return self._verified_reply(target, signed, response)

    def create(
        self, account: RfqAccountClaim, inputs: CreateRfq, *, request_id: str | None = None,
    ) -> RfqMutationReceipt:
        return self._exchange(RfqTarget(RfqOperation.CREATE), account, inputs, RfqMutationReceipt, request_id)

    def search(
        self, account: RfqAccountClaim, inputs: SearchRfqs, *, request_id: str | None = None,
    ) -> RfqSearchPage:
        return self._exchange(RfqTarget(RfqOperation.SEARCH), account, inputs, RfqSearchPage, request_id)

    def read(
        self, account: RfqAccountClaim, rfq_id: str, *, request_id: str | None = None,
    ) -> RfqDetail:
        return self._exchange(
            RfqTarget(RfqOperation.READ, rfq_id), account, RfqInput(), RfqDetail, request_id,
        )

    def edit(
        self, account: RfqAccountClaim, rfq_id: str, inputs: EditRfq, *, request_id: str | None = None,
    ) -> RfqMutationReceipt:
        return self._exchange(
            RfqTarget(RfqOperation.EDIT, rfq_id), account, inputs, RfqMutationReceipt, request_id,
        )

    def close(
        self, account: RfqAccountClaim, rfq_id: str, inputs: CloseRfq, *, request_id: str | None = None,
    ) -> RfqMutationReceipt:
        return self._exchange(
            RfqTarget(RfqOperation.CLOSE, rfq_id), account, inputs, RfqMutationReceipt, request_id,
        )

    def respond(
        self, account: RfqAccountClaim, rfq_id: str, inputs: OfferResponse,
        *, request_id: str | None = None,
    ) -> RfqMutationReceipt:
        return self._exchange(
            RfqTarget(RfqOperation.RESPOND, rfq_id), account, inputs, RfqMutationReceipt, request_id,
        )

    def response_inbox(
        self, account: RfqAccountClaim, rfq_id: str,
        *, request_id: str | None = None,
    ) -> RfqResponseInbox:
        return self._exchange(
            RfqTarget(RfqOperation.LIST_RESPONSES, rfq_id), account, RfqInput(), RfqResponseInbox, request_id,
        )

    def read_response(
        self, account: RfqAccountClaim, rfq_id: str, response_id: str,
        *, request_id: str | None = None,
    ) -> RfqResponseDetail:
        return self._exchange(
            RfqTarget(RfqOperation.READ_RESPONSE, rfq_id, response_id), account, RfqInput(), RfqResponseDetail, request_id,
        )

    def reconfirm(
        self, account: RfqAccountClaim, rfq_id: str, response_id: str, inputs: OfferResponse,
        *, request_id: str | None = None,
    ) -> RfqMutationReceipt:
        return self._exchange(
            RfqTarget(RfqOperation.RECONFIRM, rfq_id, response_id), account, inputs, RfqMutationReceipt, request_id,
        )

    def withdraw(
        self, account: RfqAccountClaim, rfq_id: str, response_id: str, inputs: ResponseVersion,
        *, request_id: str | None = None,
    ) -> RfqMutationReceipt:
        return self._exchange(
            RfqTarget(RfqOperation.WITHDRAW, rfq_id, response_id), account, inputs, RfqMutationReceipt, request_id,
        )

    def dismiss(
        self, account: RfqAccountClaim, rfq_id: str, response_id: str, inputs: ResponseVersion,
        *, request_id: str | None = None,
    ) -> RfqMutationReceipt:
        return self._exchange(
            RfqTarget(RfqOperation.DISMISS, rfq_id, response_id), account, inputs, RfqMutationReceipt, request_id,
        )

    def select(
        self, account: RfqAccountClaim, rfq_id: str, response_id: str, inputs: ShareContact,
        *, request_id: str | None = None,
    ) -> RfqMutationReceipt:
        return self._exchange(
            RfqTarget(RfqOperation.SELECT, rfq_id, response_id), account, inputs, RfqMutationReceipt, request_id,
        )

    def read_introduction(
        self, account: RfqAccountClaim, introduction_id: str,
        *, request_id: str | None = None,
    ) -> RfqIntroductionDetail:
        return self._exchange(
            RfqTarget(RfqOperation.READ_INTRODUCTION, introduction_id=introduction_id), account, RfqInput(), RfqIntroductionDetail, request_id,
        )

    def end_introduction(
        self, account: RfqAccountClaim, introduction_id: str, inputs: ResponseVersion,
        *, request_id: str | None = None,
    ) -> RfqMutationReceipt:
        return self._exchange(
            RfqTarget(RfqOperation.END_INTRODUCTION, introduction_id=introduction_id), account, inputs, RfqMutationReceipt, request_id,
        )
