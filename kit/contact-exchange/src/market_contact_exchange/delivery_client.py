"""Explicit delivery methods over the storefront's canonical signed transport."""
from __future__ import annotations

from typing import Any, Literal, Protocol

from pydantic import TypeAdapter

from .delivery_contract import (
    FinalizationCancel, FinalizationId, IntroductionFinalize, IntroductionReview,
    ObligationRef, finalization_resource,
)

REVIEW_ROUTE = "/api/v1/introductions/reviews"
FINALIZATION_ROUTE = "/api/v1/introductions/{obligation_ref}/finalizations/{finalization_id}"
CANCEL_ROUTE = FINALIZATION_ROUTE + "/cancel"
DELIVERY_ROUTE = "/api/v1/introductions/{obligation_ref}/delivery"


class _Transport(Protocol):
    def authenticated_request(self, method: str, path: str, **kwargs: Any) -> Any: ...


def _request(operation: str, body: Any = None, *, ref: str | None = None, fid: str | None = None, role: str = "buyer") -> tuple[str, str, dict[str, Any]]:
    if body is not None:
        ref = body.obligation_ref
        fid = body.finalization_id
    ref = TypeAdapter(ObligationRef).validate_python(ref)
    if fid is not None:
        fid = TypeAdapter(FinalizationId).validate_python(fid)
    paths = {
        "introduction_review": ("POST", REVIEW_ROUTE),
        "introduction_start": ("POST", "/api/v1/introductions"),
        "introduction_finalization_read": ("GET", FINALIZATION_ROUTE),
        "introduction_finalization_cancel": ("POST", CANCEL_ROUTE),
        "introduction_delivery_read": ("GET", DELIVERY_ROUTE),
    }
    method, path = paths[operation]
    return method, path.format(obligation_ref=ref, finalization_id=fid), {
        "role": role, "operation": operation,
        "resource": finalization_resource(ref, fid) if operation in {"introduction_finalization_read", "introduction_finalization_cancel"} else ref,
        **({"body": body.model_dump(mode="json")} if body is not None else {}),
    }


class ContactDeliveryClient:
    def __init__(self, transport: _Transport) -> None:
        self._transport = transport

    async def _call(self, operation: str, body: Any = None, *, request_id: str | None = None, **kwargs: Any) -> dict[str, Any]:
        method, path, options = _request(operation, body, **kwargs)
        return await self._transport.authenticated_request(method, path, **options, request_id=request_id)

    async def review(self, request: IntroductionReview, *, request_id: str | None = None) -> dict[str, Any]:
        return await self._call("introduction_review", IntroductionReview.model_validate(request), request_id=request_id)

    async def finalize(self, request: IntroductionFinalize, *, request_id: str | None = None) -> dict[str, Any]:
        return await self._call("introduction_start", IntroductionFinalize.model_validate(request), request_id=request_id)

    async def read_finalization(self, ref: str, fid: str, *, request_id: str | None = None) -> dict[str, Any]:
        return await self._call("introduction_finalization_read", ref=ref, fid=fid, request_id=request_id)

    async def cancel(self, request: FinalizationCancel, *, request_id: str | None = None) -> dict[str, Any]:
        return await self._call("introduction_finalization_cancel", FinalizationCancel.model_validate(request), request_id=request_id)

    async def read_delivery(self, ref: str, *, role: Literal["buyer", "seller"] = "buyer", request_id: str | None = None) -> dict[str, Any]:
        return await self._call("introduction_delivery_read", ref=ref, role=role, request_id=request_id)


class SyncContactDeliveryClient:
    def __init__(self, transport: _Transport) -> None:
        self._transport = transport

    def _call(self, operation: str, body: Any = None, *, request_id: str | None = None, **kwargs: Any) -> dict[str, Any]:
        method, path, options = _request(operation, body, **kwargs)
        return self._transport.authenticated_request(method, path, **options, request_id=request_id)

    def review(self, request: IntroductionReview, *, request_id: str | None = None) -> dict[str, Any]:
        return self._call("introduction_review", IntroductionReview.model_validate(request), request_id=request_id)

    def finalize(self, request: IntroductionFinalize, *, request_id: str | None = None) -> dict[str, Any]:
        return self._call("introduction_start", IntroductionFinalize.model_validate(request), request_id=request_id)

    def read_finalization(self, ref: str, fid: str, *, request_id: str | None = None) -> dict[str, Any]:
        return self._call("introduction_finalization_read", ref=ref, fid=fid, request_id=request_id)

    def cancel(self, request: FinalizationCancel, *, request_id: str | None = None) -> dict[str, Any]:
        return self._call("introduction_finalization_cancel", FinalizationCancel.model_validate(request), request_id=request_id)

    def read_delivery(self, ref: str, *, role: Literal["buyer", "seller"] = "buyer", request_id: str | None = None) -> dict[str, Any]:
        return self._call("introduction_delivery_read", ref=ref, role=role, request_id=request_id)
