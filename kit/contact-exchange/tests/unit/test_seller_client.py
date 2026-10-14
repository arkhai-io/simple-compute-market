"""The typed seller client builds exactly the request the storefront binds."""

from __future__ import annotations

import asyncio
import inspect

import pytest
from pydantic import ValidationError

from market_contact_exchange import (
    INTRODUCTION_READ_OPERATION,
    INTRODUCTION_ROUTE,
    IntroductionReveal,
    IntroductionSellerClient,
    SyncIntroductionSellerClient,
)
from market_contact_exchange.introduction_routes import (
    IntroductionRecord,
    introduction_projection,
)

_REF = "ab" * 32


def _record() -> IntroductionRecord:
    return IntroductionRecord(
        obligation_ref=_REF,
        agreement_ref="agreement-1",
        buyer_contact={"email": "buyer@example.test"},
        seller_contact={"email": "seller@example.test"},
        introduction_package={"listing_id": "listing-1"},
    )


class _Recording:
    """Stands where a core storefront client's ``authenticated_request`` does."""

    def __init__(self, answer: dict | None = None) -> None:
        self.calls: list[tuple] = []
        self._answer = (
            introduction_projection(_record(), for_role="seller")
            if answer is None
            else answer
        )

    def authenticated_request(self, method, path, **kwargs):
        self.calls.append((method, path, kwargs))
        return self._answer


class _AsyncRecording(_Recording):
    async def authenticated_request(self, method, path, **kwargs):
        return super().authenticated_request(method, path, **kwargs)


def test_the_request_is_the_one_the_storefront_binds() -> None:
    recording = _Recording()
    reveal = SyncIntroductionSellerClient(recording).read_introduction(
        _REF, request_id="read-1"
    )
    assert reveal.counterparty_contact == {"email": "buyer@example.test"}
    assert recording.calls == [
        (
            "GET",
            f"/api/v1/introductions/{_REF}",
            {
                "role": "seller",
                "operation": "introduction_read",
                "resource": _REF,
                "request_id": "read-1",
            },
        )
    ]
    assert INTRODUCTION_ROUTE.format(obligation_ref=_REF) == recording.calls[0][1]
    assert INTRODUCTION_READ_OPERATION == recording.calls[0][2]["operation"]


def test_the_seller_view_is_the_route_projection() -> None:
    projection = introduction_projection(
        _record(), for_role="seller", retention={"seconds": 2592000}
    )
    reveal = SyncIntroductionSellerClient(_Recording(projection)).read_introduction(_REF)
    assert reveal == IntroductionReveal.model_validate(projection)
    assert reveal.retention == {"seconds": 2592000}


def test_both_variants_send_the_same_request() -> None:
    sync_recording, async_recording = _Recording(), _AsyncRecording()
    SyncIntroductionSellerClient(sync_recording).read_introduction(_REF)
    asyncio.run(IntroductionSellerClient(async_recording).read_introduction(_REF))
    assert sync_recording.calls == async_recording.calls


def test_the_variants_share_one_signature() -> None:
    assert inspect.signature(
        IntroductionSellerClient.read_introduction
    ) == inspect.signature(SyncIntroductionSellerClient.read_introduction)


def test_an_unexpected_answer_is_refused() -> None:
    projection = introduction_projection(_record(), for_role="seller")
    with pytest.raises(ValidationError):
        SyncIntroductionSellerClient(
            _Recording({**projection, "buyer_contact": {}})
        ).read_introduction(_REF)
