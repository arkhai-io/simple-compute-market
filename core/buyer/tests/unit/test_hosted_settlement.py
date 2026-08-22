from __future__ import annotations

from typing import Any
from types import SimpleNamespace

import pytest
from market_identity import Ed25519Signer

import core_buyer.hosted_settlement as hosted
from core_buyer.action_policy import BuyerActionPolicy


def _transport() -> hosted.HostedSettlementTransport:
    signer = Ed25519Signer(b"\x71" * 32)
    return hosted.HostedSettlementTransport(
        seller_url="https://seller.example/",
        principal=signer.identity,
        signer=signer,
        resolve_seller_principals=lambda: None,
    )


def test_start_sends_only_accepted_ids_and_safe_authorization(monkeypatch) -> None:
    captured: dict[str, Any] = {}
    monkeypatch.setattr(
        hosted,
        "_signed_json",
        lambda url, body, **kwargs: (
            captured.update(url=url, body=body, kwargs=kwargs)
            or {"settlement_ref": "settlement-1"}
        ),
    )

    response = _transport().start(
        negotiation_id="negotiation-1",
        obligation_ref="a" * 64,
        funding_authorization_ref="authorization-safe-1",
    )

    assert response == {"settlement_ref": "settlement-1"}
    assert captured["url"] == "https://seller.example/api/v1/settlements"
    assert captured["body"] == {
        "negotiation_id": "negotiation-1",
        "obligation_ref": "a" * 64,
        "funding_authorization_ref": "authorization-safe-1",
    }
    assert captured["kwargs"]["operation"] == "settlement_start"


def test_resume_handles_action_transiently_and_keeps_exact_reference(monkeypatch) -> None:
    projections = iter(
        [
            {
                "settlement_ref": "settlement-1",
                "status": "requires_action",
                "action": {"kind": "confirmation", "url": "https://action.invalid"},
            },
            {"settlement_ref": "settlement-1", "status": "collected"},
        ]
    )
    monkeypatch.setattr(
        hosted.HostedSettlementTransport,
        "status",
        lambda _transport, *, settlement_ref: next(projections),
    )
    actions: list[dict[str, Any]] = []
    polls: list[tuple[int, str]] = []

    result = _transport().resume(
        settlement_ref="settlement-1",
        poll_interval=0,
        total_timeout=10,
        on_action=lambda action: actions.append(dict(action)),
        on_poll=lambda attempt, body: polls.append((attempt, str(body["status"]))),
        sleep=lambda _seconds: None,
        monotonic=iter((0.0, 0.0)).__next__,
    )

    assert result["status"] == "collected"
    assert actions == [{"kind": "confirmation", "url": "https://action.invalid"}]
    assert polls == [(1, "requires_action"), (2, "collected")]


def test_wait_times_out_without_mutating_operation(monkeypatch) -> None:
    monkeypatch.setattr(
        hosted.HostedSettlementTransport,
        "status",
        lambda _transport, *, settlement_ref: {
            "settlement_ref": settlement_ref,
            "status": "funding",
        },
    )
    ticks = iter((0.0, 2.0))

    with pytest.raises(TimeoutError, match="stable public status"):
        _transport().wait(
            settlement_ref="settlement-1",
            poll_interval=0,
            total_timeout=1,
            sleep=lambda _seconds: None,
            monotonic=ticks.__next__,
        )


def test_shared_settle_hook_returns_domain_result_and_private_credentials(
    monkeypatch,
) -> None:
    signer = Ed25519Signer(b"\x72" * 32)
    obligation = {
        "payer": "buyer",
        "claimant": "seller",
        "payer_principal": signer.identity.model_dump(mode="json"),
        "claimant_principal": Ed25519Signer(b"\x73" * 32).identity.model_dump(
            mode="json"
        ),
        "amount": 500,
        "asset": "usd",
        "expiration_unix": 2_000_000_000,
        "conditions": [{"kind": "portable", "value": "credit"}],
        "mechanism": "fiat.stripe.v1",
        "params": {},
    }
    monkeypatch.setattr(
        hosted,
        "make_publisher_trust_resolver",
        lambda **_kwargs: lambda: None,
    )
    monkeypatch.setattr(
        hosted.HostedSettlementTransport,
        "start",
        lambda _self, **_kwargs: {
            "settlement_ref": "settlement-safe-1",
            "status": "pending",
        },
    )
    monkeypatch.setattr(
        hosted.HostedSettlementTransport,
        "wait",
        lambda _self, **_kwargs: {
            "settlement_ref": "settlement-safe-1",
            "status": "ready",
            "result": {"fulfillment_id": "credit-fulfillment-1"},
            "tenant_credentials": {
                "credentials_ref": "credentials-safe-1",
                "key_id": "key-public-1",
                "secret": "buyer-only-secret",
            },
        },
    )
    hook = hosted.make_hosted_settle_hook(
        config=SimpleNamespace(
            principal=signer.identity,
            signer=signer,
        ),
        mechanism="fiat.stripe.v1",
        prepare_authorization=lambda _ref, _obligation: SimpleNamespace(
            funding_authorization_ref="funding-auth-safe-1",
            funding_profile=SimpleNamespace(value="card.v1"),
            expires_at_unix=2_000_000_000,
        ),
        poll_interval=0,
        total_timeout=1,
        sleep=lambda _seconds: None,
        action_policy=BuyerActionPolicy.FAIL,
        open_url=lambda _url: None,
        print_url=lambda _url: None,
    )
    result = hook(
        SimpleNamespace(
            outcome=SimpleNamespace(
                settlement_plan=SimpleNamespace(
                    obligations=(
                        SimpleNamespace(
                            mechanism="fiat.stripe.v1",
                            model_dump=lambda **_kwargs: obligation,
                        ),
                    )
                ),
                negotiation_id="negotiation-1",
                agreed_amount=500,
                rounds=1,
            ),
            match={
                "storefront_url": "https://seller.example",
                "listing_id": "listing-1",
            },
            attempts=[],
        ),
        lambda _stage, _body: None,
    )

    assert result.status == "ready"
    assert result.escrow_uid == "settlement-safe-1"
    assert result.fulfillment_uid == "credit-fulfillment-1"
    assert result.tenant_credentials == {
        "credentials_ref": "credentials-safe-1",
        "key_id": "key-public-1",
        "secret": "buyer-only-secret",
    }


def test_reclaim_signs_mechanism_options_it_does_not_read(monkeypatch) -> None:
    """This transport stays opaque to the mechanism's vocabulary.

    It signs the mapping into the body so the storefront can verify the payer
    asked for exactly this return, and reads no key of it.
    """

    captured: dict[str, Any] = {}
    monkeypatch.setattr(
        hosted,
        "_signed_json",
        lambda url, body, **kwargs: (
            captured.update(url=url, body=body, kwargs=kwargs)
            or {"status": "reclaimed"}
        ),
    )

    _transport().reclaim(
        settlement_ref="settlement-1",
        mechanism_options={"return_instructions_email": "payer@example.test"},
    )

    assert captured["url"] == (
        "https://seller.example/api/v1/settlements/settlement-1/reclaim"
    )
    assert captured["body"] == {"return_instructions_email": "payer@example.test"}
    assert captured["kwargs"]["operation"] == "settlement_reclaim"


def test_reclaim_without_options_sends_no_body(monkeypatch) -> None:
    """A caller with nothing to say sends the request this always sent."""

    captured: dict[str, Any] = {}
    monkeypatch.setattr(
        hosted,
        "_signed_json",
        lambda url, body, **kwargs: (
            captured.update(url=url, body=body, kwargs=kwargs)
            or {"status": "reclaimed"}
        ),
    )

    _transport().reclaim(settlement_ref="settlement-1")

    assert captured["body"] is None
