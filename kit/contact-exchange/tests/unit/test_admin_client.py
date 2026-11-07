"""The typed operator client builds exactly the request the storefront binds."""

from __future__ import annotations

import asyncio
import inspect

import pytest
from pydantic import ValidationError

from market_contact_exchange import (
    DELETE_INTRODUCTION_PAYLOADS_OPERATION,
    INTRODUCTION_PAYLOADS_ROUTE,
    IntroductionAdminClient,
    IntroductionPayloadsDeletion,
    SyncIntroductionAdminClient,
)

_REF = "ab" * 32
_ANSWER = {
    "obligation_ref": _REF,
    "redacted": True,
    "payloads_deleted_at": "2026-10-01T12:00:00Z",
}


class _Recording:
    """Stands where a core storefront client's ``authenticated_request`` does."""

    def __init__(self, answer: dict | None = None) -> None:
        self.calls: list[tuple] = []
        self._answer = dict(_ANSWER) if answer is None else answer

    def authenticated_request(self, method, path, **kwargs):
        self.calls.append((method, path, kwargs))
        return self._answer


class _AsyncRecording(_Recording):
    async def authenticated_request(self, method, path, **kwargs):
        return super().authenticated_request(method, path, **kwargs)


def test_the_request_is_the_one_the_storefront_binds() -> None:
    recording = _Recording()
    outcome = SyncIntroductionAdminClient(recording).delete_introduction_payloads(
        _REF, request_id="delete-1"
    )
    assert outcome == IntroductionPayloadsDeletion(**_ANSWER)
    assert recording.calls == [
        (
            "DELETE",
            f"/api/v1/admin/introductions/{_REF}/payloads",
            {
                "role": "admin",
                "operation": "admin_delete_introduction_payloads",
                "resource": _REF,
                "request_id": "delete-1",
            },
        )
    ]
    assert INTRODUCTION_PAYLOADS_ROUTE.format(obligation_ref=_REF) == recording.calls[0][1]
    assert DELETE_INTRODUCTION_PAYLOADS_OPERATION == recording.calls[0][2]["operation"]


def test_both_variants_send_the_same_request() -> None:
    sync_recording, async_recording = _Recording(), _AsyncRecording()
    SyncIntroductionAdminClient(sync_recording).delete_introduction_payloads(_REF)
    asyncio.run(
        IntroductionAdminClient(async_recording).delete_introduction_payloads(_REF)
    )
    assert sync_recording.calls == async_recording.calls


def test_the_variants_share_one_signature() -> None:
    assert inspect.signature(
        IntroductionAdminClient.delete_introduction_payloads
    ) == inspect.signature(SyncIntroductionAdminClient.delete_introduction_payloads)


def test_a_never_revealed_deal_has_no_deletion_time() -> None:
    answer = {"obligation_ref": _REF, "redacted": False, "payloads_deleted_at": None}
    outcome = SyncIntroductionAdminClient(_Recording(answer)).delete_introduction_payloads(_REF)
    assert outcome.redacted is False and outcome.payloads_deleted_at is None


def test_an_unexpected_answer_is_refused() -> None:
    with pytest.raises(ValidationError):
        SyncIntroductionAdminClient(
            _Recording({**_ANSWER, "contact": "x"})
        ).delete_introduction_payloads(_REF)
