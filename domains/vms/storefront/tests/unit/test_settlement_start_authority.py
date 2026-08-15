from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from arkhai_vms import make_vm_provision_terms
from fastapi import HTTPException
from market_identity import Ed25519Signer
from starlette.requests import Request

import market_storefront.container as _container
from market_storefront.controllers.settle_controller import SettleController
from market_storefront.middleware import buyer_auth
from market_storefront.models.settle_models import VmSettleRequest

_BUYER = Ed25519Signer(b"\x71" * 32).identity
_OTHER_BUYER = Ed25519Signer(b"\x72" * 32).identity
_SELLER = Ed25519Signer(b"\x73" * 32).identity
_ACCEPTED_SSH = "ssh-ed25519 AAAAaccepted buyer@test"


def _request() -> Request:
    return Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/api/v1/settle/escrow-1",
            "headers": [],
        }
    )


def _thread() -> dict:
    return {
        "negotiation_id": "neg-1",
        "terminal_state": "success",
        "buyer_principal": _BUYER.model_dump(mode="json"),
        "buyer_escrow_proposal": {
            "chain_name": "anvil",
            "escrow_address": "0x" + "11" * 20,
            "fields": {"token": "0x" + "22" * 20},
            "expiration_unix": 1_900_000_000,
        },
        "provision_terms": make_vm_provision_terms(
            duration_seconds=3600,
            ssh_public_key=_ACCEPTED_SSH,
        ).model_dump(mode="json"),
    }


def _body(*, buyer=_BUYER, ssh_public_key: str = _ACCEPTED_SSH) -> VmSettleRequest:
    return VmSettleRequest(
        negotiation_id="neg-1",
        buyer_principal=buyer,
        buyer_evm_address="0x" + "33" * 20,
        ssh_public_key=ssh_public_key,
        chain_name="anvil",
    )


def _controller(db) -> SettleController:
    controller = object.__new__(SettleController)
    controller._db = db
    return controller


@pytest.mark.asyncio
async def test_settlement_start_rejects_cross_buyer_substitution() -> None:
    db = SimpleNamespace(
        load_negotiation_thread_row=AsyncMock(return_value=_thread()),
        load_escrow=AsyncMock(return_value=None),
    )

    with pytest.raises(HTTPException) as exc_info:
        await _controller(db).settle_escrow(
            "escrow-1", _body(buyer=_OTHER_BUYER), _request()
        )

    assert exc_info.value.status_code == 403
    assert "persisted owner" in str(exc_info.value.detail)
    db.load_escrow.assert_not_awaited()


@pytest.mark.asyncio
async def test_settlement_start_rejects_ssh_key_substitution(monkeypatch) -> None:
    db = SimpleNamespace(
        load_negotiation_thread_row=AsyncMock(return_value=_thread()),
        load_escrow=AsyncMock(return_value=None),
    )
    monkeypatch.setattr(
        buyer_auth,
        "_verify",
        AsyncMock(return_value=SimpleNamespace(exact_retry=False)),
    )

    with pytest.raises(HTTPException) as exc_info:
        await _controller(db).settle_escrow(
            "escrow-1",
            _body(ssh_public_key="ssh-ed25519 AAAAsubstituted attacker@test"),
            _request(),
        )

    assert exc_info.value.status_code == 403
    assert "accepted provision terms" in str(exc_info.value.detail)


@pytest.mark.asyncio
async def test_settlement_start_passes_only_persisted_inputs_to_coordinator(
    monkeypatch,
) -> None:
    db = SimpleNamespace(
        load_negotiation_thread_row=AsyncMock(return_value=_thread()),
        load_escrow=AsyncMock(return_value=None),
    )
    monkeypatch.setattr(
        buyer_auth,
        "_verify",
        AsyncMock(return_value=SimpleNamespace(exact_retry=False)),
    )
    monkeypatch.setattr(_container, "configured_chain_names", lambda: ("anvil",))
    coordinator = SimpleNamespace(
        start=AsyncMock(
            return_value={
                "escrow_uid": "escrow-1",
                "negotiation_id": "neg-1",
                "status": "provisioning",
            }
        )
    )
    composition = SimpleNamespace(
        coordinator=coordinator,
        mechanism_clients={"alkahest.v1": object()},
        local_principal=_SELLER,
    )
    monkeypatch.setattr(_container, "resolved_settlement_composition", composition)

    response = await _controller(db).settle_escrow("escrow-1", _body(), _request())

    assert response.status_code == 202
    coordinator.start.assert_awaited_once_with(
        escrow_uid="escrow-1",
        negotiation_id="neg-1",
        mechanism_client=composition.mechanism_clients["alkahest.v1"],
        chain_name="anvil",
        request=None,
    )
