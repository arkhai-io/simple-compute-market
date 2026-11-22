"""Authority-side typed transport for a pinned registry's RFQ routes."""

import re
from typing import Self, TypeVar

import httpx
from market_core.rfq import (
    CloseRfq,
    CreateRfq,
    EditRfq,
    RfqAccountClaim,
    RfqAudience,
    RfqDetail,
    RfqInput,
    RfqInvocation,
    RfqMutationReceipt,
    RfqOperation,
    RfqSearchPage,
    RfqTarget,
    SearchRfqs,
)
from market_identity import Signer
from pydantic import BaseModel

from registry_client.auth import RegistryClientError
from registry_client.rfq_auth import SignedRfqRequest, sign_rfq_invocation

_Outcome = TypeVar("_Outcome", bound=BaseModel)
_ErrorCode = re.compile(r"[a-z][a-z0-9_]{0,127}")


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
        if isinstance(result, RfqSearchPage) and any(entry.registry != self._audience for entry in result.results):
            raise ValueError("invalid RFQ registry provenance")
        if isinstance(result, RfqDetail) and (result.registry != self._audience or result.rfq_id != target.rfq_id):
            raise ValueError("invalid RFQ registry provenance")
        return result


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
