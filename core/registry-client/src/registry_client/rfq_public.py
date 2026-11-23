"""Unsigned open RFQ requests with pinned, operation-bound registry replies."""

import re
from typing import Self, TypeVar
from uuid import uuid4

import httpx
from market_core.rfq import (
    RfqAudience, RfqInput, RfqOperation, RfqSearchPage, RfqSummary, RfqTarget,
    SearchRfqs, validate_rfq_provenance,
)
from market_identity import Identity, TrustedIdentitySet
from pydantic import BaseModel

from registry_client.auth import REQUEST_ID_HEADER, RegistryClientError, verify_registry_response_context

_Outcome = TypeVar("_Outcome", bound=BaseModel)
_ERROR_CODE = re.compile(r"[a-z][a-z0-9_]{0,127}")


class _PublicReplies:
    def __init__(self, audience: RfqAudience):
        self._audience = audience
        self._pins = TrustedIdentitySet(
            identities=(Identity.model_validate(audience.principal.model_dump(mode="json")),),
        )

    def _decode(self, target: RfqTarget, request_id: str, response: httpx.Response, outcome: type[_Outcome]) -> _Outcome:
        body = response.json()
        verify_registry_response_context(
            headers=response.headers, expected_registries=self._pins,
            method=target.method, operation=target.operation.value, resource=target.resource,
            request_id=request_id, status=response.status_code, body=body,
        )
        if response.status_code != 200:
            code = body.get("detail") if isinstance(body, dict) else None
            if not isinstance(code, str) or not _ERROR_CODE.fullmatch(code):
                code = "rfq_registry_refused"
            raise RegistryClientError(target.method, target.path, response.status_code, code)
        result = outcome.model_validate(body)
        validate_rfq_provenance(target, self._audience, result)
        return result


class RfqPublicRegistryClient(_PublicReplies):
    """Discover open requests without an account using the registry's public posture."""

    def __init__(
        self, base_url: str, *, audience: RfqAudience, transport: httpx.AsyncBaseTransport | None = None,
        timeout: float = 30.0,
    ):
        super().__init__(audience)
        self._http = httpx.AsyncClient(base_url=base_url, transport=transport, timeout=timeout)

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self._http.aclose()

    async def _exchange(
        self, target: RfqTarget, inputs: RfqInput, outcome: type[_Outcome], request_id: str | None,
    ) -> _Outcome:
        request_id = request_id or uuid4().hex
        response = await self._http.post(
            target.path, headers={REQUEST_ID_HEADER: request_id}, json=inputs.model_dump(mode="json"),
        )
        return self._decode(target, request_id, response, outcome)

    async def search(self, inputs: SearchRfqs, *, request_id: str | None = None) -> RfqSearchPage:
        return await self._exchange(RfqTarget(RfqOperation.SEARCH), inputs, RfqSearchPage, request_id)

    async def read(self, rfq_id: str, *, request_id: str | None = None) -> RfqSummary:
        return await self._exchange(RfqTarget(RfqOperation.READ, rfq_id), RfqInput(), RfqSummary, request_id)


class SyncRfqPublicRegistryClient(_PublicReplies):
    """Synchronous client for the same signed public discovery outcomes."""

    def __init__(
        self, base_url: str, *, audience: RfqAudience, transport: httpx.BaseTransport | None = None,
        timeout: float = 30.0,
    ):
        super().__init__(audience)
        self._http = httpx.Client(base_url=base_url, transport=transport, timeout=timeout)

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *exc: object) -> None:
        self._http.close()

    def _exchange(
        self, target: RfqTarget, inputs: RfqInput, outcome: type[_Outcome], request_id: str | None,
    ) -> _Outcome:
        request_id = request_id or uuid4().hex
        response = self._http.post(
            target.path, headers={REQUEST_ID_HEADER: request_id}, json=inputs.model_dump(mode="json"),
        )
        return self._decode(target, request_id, response, outcome)

    def search(self, inputs: SearchRfqs, *, request_id: str | None = None) -> RfqSearchPage:
        return self._exchange(RfqTarget(RfqOperation.SEARCH), inputs, RfqSearchPage, request_id)

    def read(self, rfq_id: str, *, request_id: str | None = None) -> RfqSummary:
        return self._exchange(RfqTarget(RfqOperation.READ, rfq_id), RfqInput(), RfqSummary, request_id)
