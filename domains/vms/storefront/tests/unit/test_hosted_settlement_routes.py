from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from arkhai_vms import make_vm_provision_terms
from fastapi import HTTPException
from hosted_settlement_client import ConditionDescriptor
from market_identity import Ed25519Signer
from market_settlement_runtime import (
    SettlementObligationRecord,
    SettlementOperationOutcome,
    derive_obligation_ref,
)
from pydantic import ValidationError
from starlette.requests import Request

import market_storefront.container as container
from market_storefront.controllers.settle_controller import SettlementsController
from market_storefront.middleware import buyer_auth
from market_storefront.middleware.seller_auth import _safe_replay_body
from market_storefront.models.hosted_settlement_models import SettlementStartRequest
from market_storefront.settlement_composition import load_hosted_agreement

BUYER = Ed25519Signer(b"\x61" * 32).identity
SELLER = Ed25519Signer(b"\x62" * 32).identity
CONDITION = ConditionDescriptor.model_validate(
    {
        "protocol": "arkhai.condition.v1",
        "condition_id": "vm-fulfillment-1",
        "evaluator": {
            "kind": "builtin.v1",
            "version": "trivial.v1",
            "params": {"kind": "trivial"},
        },
        "demand": {"encoding": "application/jcs+json", "value": True},
    }
).model_dump(mode="json")


def _request(method: str = "POST") -> Request:
    return Request(
        {
            "type": "http",
            "method": method,
            "path": "/api/v1/settlements",
            "headers": [],
        }
    )


def _accepted_state(*, legacy: bool = False):
    option_params = {
        "account_ref": "account-seller",
        "claimant_principal": SELLER.model_dump(mode="json"),
        "funds_flow": "separate_charges_transfers",
        "condition": CONDITION,
    }
    if legacy:
        option_params["payment_method_types"] = ["card"]
    else:
        option_params.update(
            {
                "funding_profile": "us_ach_debit.v1",
                "authority_id": "hosted-authority-1",
                "environment": "test",
                "country": "US",
                "interaction": "interactive",
                "contract_fingerprint": "sha256:" + "11" * 32,
            }
        )
    obligation_params = {
        **option_params,
        "payer_principal": BUYER.model_dump(mode="json"),
        "claimant_principal": SELLER.model_dump(mode="json"),
    }
    obligation = {
        "payer": "buyer",
        "claimant": "seller",
        "payer_principal": BUYER.model_dump(mode="json"),
        "claimant_principal": SELLER.model_dump(mode="json"),
        "amount": 125,
        "asset": "usd",
        "expiration_unix": 2_000_000_000,
        "conditions": [CONDITION],
        "mechanism": "fiat.stripe.v1",
        "params": obligation_params,
    }
    option = {
        "option_id": "accepted-option",
        "mechanism": "fiat.stripe.v1",
        "asset": "usd",
        "rates": [{"field": "amount", "value": "125"}],
        "params": option_params,
    }
    provision = make_vm_provision_terms(
        duration_seconds=3600,
        ssh_public_key="ssh-ed25519 AAAAaccepted buyer@test",
    ).model_dump(mode="json")
    listing = {
        "listing_id": "listing-1",
        "offer_resource": {"gpu_model": "H100", "gpu_count": 1},
        "settlement_options": [option],
    }
    settlement_plan = {
        "buyer_principal": BUYER.model_dump(mode="json"),
        "seller_principal": SELLER.model_dump(mode="json"),
        "obligations": [obligation],
    }
    if not legacy:
        settlement_plan["service_terms"] = {
            "vm.v1": {
                "listing_id": "listing-1",
                "order": dict(listing),
                "provision": provision,
            }
        }
    thread = {
        "terminal_state": "success",
        "buyer_principal": BUYER.model_dump(mode="json"),
        "our_listing_id": "listing-1",
        "agreed_price": 125,
        "buyer_escrow_proposal": {
            "settlement_selection": {
                "option_id": "accepted-option",
                "mechanism": "fiat.stripe.v1",
                "expiration_unix": 2_000_000_000,
            }
        },
        "settlement_plan": settlement_plan,
        "provision_terms": provision,
    }
    db = SimpleNamespace(
        load_negotiation_thread_row=AsyncMock(return_value=thread),
        load_listing=AsyncMock(return_value=listing),
    )
    normalized = SettlementObligationRecord.from_obligation(
        agreement_ref="negotiation-1",
        obligation_index=0,
        obligation=obligation,
    ).obligation
    return db, thread, listing, normalized


def _controller(db) -> SettlementsController:
    controller = object.__new__(SettlementsController)
    controller._db = db
    return controller


def test_start_request_accepts_only_three_safe_references() -> None:
    with pytest.raises(ValidationError, match="payer_principal"):
        SettlementStartRequest.model_validate(
            {
                "negotiation_id": "negotiation-1",
                "obligation_ref": "a" * 64,
                "funding_authorization_ref": "authorization-1",
                "payer_principal": BUYER.model_dump(mode="json"),
                "amount": 125,
                "payment_method_id": "provider-value",
            }
        )


@pytest.mark.asyncio
async def test_start_binds_authorization_after_registering_accepted_obligation(
    monkeypatch,
) -> None:
    db, _thread, _listing, obligation = _accepted_state()
    obligation_ref = derive_obligation_ref("negotiation-1", 0, obligation)
    accepted = SettlementObligationRecord.from_obligation(
        agreement_ref="negotiation-1",
        obligation_index=0,
        obligation=obligation,
    )
    mechanism_params = {
        "funding_profile": "us_ach_debit.v1",
        "funding_authorization_ref": "authorization-1",
    }
    bound = accepted.model_copy(update={"mechanism_params": mechanism_params})
    stored = bound.model_copy(
        update={
            "mechanism_ref": "settlement-1",
            "mechanism_status": "requires_action",
            "mechanism_state": {
                **mechanism_params,
                "funding_reason": "payer_action_required",
            },
            "buyer_action": {"kind": "confirmation", "expires_at_unix": 999},
            "materialization_receipt": {
                "funding_reason": "payer_action_required"
            },
        }
    )
    runtime = SimpleNamespace(
        register_plan=AsyncMock(return_value=[accepted]),
        bind_mechanism_params=AsyncMock(return_value=bound),
        materialize=AsyncMock(
            return_value=SettlementOperationOutcome(
                obligation_ref=obligation_ref,
                operation="materialize",
                status="pending",
                action={
                    "kind": "confirmation",
                    "operation_ref": "action-1",
                    "expires_at_unix": 999,
                    "url": "https://checkout.example/transient",
                },
                receipt={"funding_reason": "payer_action_required"},
            )
        ),
    )
    composition = SimpleNamespace(
        runtime=runtime,
        repository=SimpleNamespace(
            load_settlement_obligation=AsyncMock(return_value=stored.model_dump())
        ),
        mechanism_clients={"fiat.stripe.v1": object()},
        local_principal=SELLER,
    )
    monkeypatch.setattr(container, "resolved_settlement_composition", composition)
    monkeypatch.setattr(
        buyer_auth,
        "_verify",
        AsyncMock(return_value=SimpleNamespace(exact_retry=False)),
    )

    response = await _controller(db).start(
        SettlementStartRequest(
            negotiation_id="negotiation-1",
            obligation_ref=obligation_ref,
            funding_authorization_ref="authorization-1",
        ),
        _request(),
    )

    registered = runtime.register_plan.await_args.kwargs["obligations"][0]
    assert "funding_authorization_ref" not in registered["params"]
    runtime.bind_mechanism_params.assert_awaited_once_with(
        obligation_ref,
        mechanism_params,
        local_principal=BUYER,
    )
    assert response.funding_profile.value == "us_ach_debit.v1"
    assert response.funding_authorization_ref == "authorization-1"
    assert response.action["url"] == "https://checkout.example/transient"


@pytest.mark.asyncio
async def test_changed_authorization_retry_fails_before_materialization(monkeypatch) -> None:
    db, _thread, _listing, obligation = _accepted_state()
    obligation_ref = derive_obligation_ref("negotiation-1", 0, obligation)
    accepted = SettlementObligationRecord.from_obligation(
        agreement_ref="negotiation-1",
        obligation_index=0,
        obligation=obligation,
    )
    runtime = SimpleNamespace(
        register_plan=AsyncMock(return_value=[accepted]),
        bind_mechanism_params=AsyncMock(
            side_effect=ValueError("mechanism_params are immutable")
        ),
        materialize=AsyncMock(),
    )
    composition = SimpleNamespace(
        runtime=runtime,
        repository=object(),
        mechanism_clients={"fiat.stripe.v1": object()},
        local_principal=SELLER,
    )
    monkeypatch.setattr(container, "resolved_settlement_composition", composition)
    monkeypatch.setattr(
        buyer_auth,
        "_verify",
        AsyncMock(return_value=SimpleNamespace(exact_retry=False)),
    )

    with pytest.raises(HTTPException) as exc_info:
        await _controller(db).start(
            SettlementStartRequest(
                negotiation_id="negotiation-1",
                obligation_ref=obligation_ref,
                funding_authorization_ref="changed-authorization",
            ),
            _request(),
        )

    assert exc_info.value.status_code == 409
    runtime.materialize.assert_not_awaited()


@pytest.mark.asyncio
async def test_accepted_plan_survives_current_publication_profile_removal() -> None:
    db, _thread, listing, obligation = _accepted_state()
    listing["settlement_options"] = []
    listing["offer_resource"] = {"gpu_model": "H200", "gpu_count": 8}

    recovered = await load_hosted_agreement(
        sqlite_client=db,
        negotiation_id="negotiation-1",
        expected_claimant=SELLER,
    )
    assert recovered.order["offer_resource"] == {"gpu_model": "H100", "gpu_count": 1}
    db.load_listing.assert_not_awaited()

    assert recovered.obligation == obligation
    assert recovered.funding_profile.value == "us_ach_debit.v1"


@pytest.mark.asyncio
async def test_legacy_card_plan_is_recovery_only() -> None:
    db, _thread, _listing, _obligation = _accepted_state(legacy=True)

    with pytest.raises(ValueError, match="recovery-only"):
        await load_hosted_agreement(
            sqlite_client=db,
            negotiation_id="negotiation-1",
            expected_claimant=SELLER,
        )
    recovered = await load_hosted_agreement(
        sqlite_client=db,
        negotiation_id="negotiation-1",
        expected_claimant=SELLER,
        allow_legacy_recovery=True,
    )
    assert recovered.funding_profile.value == "card.v1"
    assert recovered.legacy_recovery is True




@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("collection_state", "expected_status", "wake_count"),
    [
        ("pending", "failed", 1),
        ("succeeded", "manual_required", 0),
    ],
)
async def test_return_preserves_evidence_and_only_queues_precollection_cleanup(
    monkeypatch,
    collection_state,
    expected_status,
    wake_count,
) -> None:
    db, _thread, _listing, obligation = _accepted_state()
    accepted = SettlementObligationRecord.from_obligation(
        agreement_ref="negotiation-1",
        obligation_index=0,
        obligation=obligation,
    )
    failed = accepted.model_copy(
        update={
            "mechanism_ref": "settlement-1",
            "mechanism_status": (
                "manual_required" if collection_state == "succeeded" else "failed"
            ),
            "mechanism_state": {
                "funding_profile": "us_ach_debit.v1",
                "funding_authorization_ref": "authorization-1",
                "funding_reason": "returned",
            },
            "mechanism_params": {
                "funding_profile": "us_ach_debit.v1",
                "funding_authorization_ref": "authorization-1",
            },
            "materialization_state": "materialized",
            "fulfillment_ref": "portable-evidence-ref",
            "condition_state": "failed",
            "collection_state": collection_state,
            "status_receipt": {"funding_reason": "returned"},
        }
    )
    runtime = SimpleNamespace(
        reconcile_status=AsyncMock(
            return_value=SettlementOperationOutcome(
                obligation_ref=accepted.obligation_ref,
                operation="status",
                status="succeeded",
                receipt={"funding_reason": "returned"},
            )
        )
    )
    worker = SimpleNamespace(wake=AsyncMock())
    composition = SimpleNamespace(
        runtime=runtime,
        repository=SimpleNamespace(
            load_settlement_obligation=AsyncMock(return_value=failed.model_dump())
        ),
        worker=worker,
        mechanism_clients={"fiat.stripe.v1": object()},
        local_principal=SELLER,
    )
    controller = _controller(db)
    controller._record = AsyncMock(return_value=accepted)
    controller._authorize = AsyncMock(
        return_value=SimpleNamespace(exact_retry=False)
    )
    monkeypatch.setattr(container, "resolved_settlement_composition", composition)

    response = await controller.status("settlement-1", _request("GET"))

    assert response.status == expected_status
    assert response.receipt == {"funding_reason": "returned"}
    assert failed.fulfillment_ref == "portable-evidence-ref"
    assert worker.wake.await_count == wake_count
def test_replay_journal_strips_transient_action_details() -> None:
    body = {
        "settlement_ref": "settlement-1",
        "action": {
            "kind": "bank_instructions",
            "url": "https://checkout.example/transient",
            "bank_instructions": {"reference": "provider-private"},
        },
        "action_kind": "bank_instructions",
        "action_expires_at_unix": 999,
    }

    assert _safe_replay_body("settlement_status", body) == {
        **body,
        "action": None,
    }
