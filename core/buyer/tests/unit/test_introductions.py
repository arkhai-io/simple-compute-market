from __future__ import annotations

from typing import Any

import pytest
from market_identity import Ed25519Signer

import core_buyer.introductions as introductions


def _transport() -> introductions.IntroductionTransport:
    signer = Ed25519Signer(b"\x71" * 32)
    return introductions.IntroductionTransport(
        seller_url="https://seller.example/",
        principal=signer.identity,
        signer=signer,
        resolve_seller_principals=lambda: None,
    )


def test_start_sends_the_accepted_ids_and_contact_payload(monkeypatch) -> None:
    captured: dict[str, Any] = {}
    monkeypatch.setattr(
        introductions,
        "_signed_json",
        lambda url, body, **kwargs: (
            captured.update(url=url, body=body, kwargs=kwargs)
            or {"revealed": True, "counterparty_contact": {"telegram": "@seller"}}
        ),
    )

    response = _transport().start(
        negotiation_id="negotiation-1",
        obligation_ref="a" * 64,
        contact_payload={"email": "buyer@example.com"},
    )

    assert response["counterparty_contact"] == {"telegram": "@seller"}
    assert captured["url"] == "https://seller.example/api/v1/introductions"
    assert captured["body"] == {
        "negotiation_id": "negotiation-1",
        "obligation_ref": "a" * 64,
        "contact_payload": {"email": "buyer@example.com"},
    }
    assert captured["kwargs"]["operation"] == "introduction_start"
    assert captured["kwargs"]["resource"] == "a" * 64


def test_read_is_a_signed_idempotent_get(monkeypatch) -> None:
    calls: list[dict[str, Any]] = []
    monkeypatch.setattr(
        introductions,
        "_signed_json",
        lambda url, body, **kwargs: (
            calls.append({"url": url, "body": body, **kwargs})
            or {"revealed": True, "counterparty_contact": {"telegram": "@seller"}}
        ),
    )

    transport = _transport()
    first = transport.read(obligation_ref="a" * 64)
    again = transport.read(obligation_ref="a" * 64)

    assert first == again
    assert all(call["method"] == "GET" for call in calls)
    assert all(call["operation"] == "introduction_read" for call in calls)
    assert calls[0]["url"].endswith("/api/v1/introductions/" + "a" * 64)


def test_refusals_surface_cleanly(monkeypatch) -> None:
    def refuse(url: str, body: Any, **kwargs: Any) -> Any:
        raise RuntimeError("introduction has not been started")

    monkeypatch.setattr(introductions, "_signed_json", refuse)
    with pytest.raises(RuntimeError, match="has not been started"):
        _transport().read(obligation_ref="a" * 64)
