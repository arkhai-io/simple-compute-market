"""Conflicting VM settlement retries preserve authority and report HTTP 409."""

import sqlite3
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

import market_storefront.container as container
from market_storefront.domain_runtime import build_vm_storefront_domain
from market_storefront.middleware import buyer_auth
from market_storefront.payment_repository import VmSettlementRepository, add_vm_settlement_records
from tests.fulfillment_fixtures import vm_delivery_evidence
from tests.unit.test_settlement_start_authority import _body, _controller, _request, _thread, _SELLER


@pytest.mark.asyncio
async def test_second_escrow_for_accepted_negotiation_returns_conflict(tmp_path, monkeypatch):
    repository = VmSettlementRepository()
    repository.db_path = str(tmp_path / "settlement.db")
    with sqlite3.connect(repository.db_path) as conn:
        add_vm_settlement_records(conn)
    first = vm_delivery_evidence(negotiation_id="neg-1", settlement_ref="escrow-1")
    await repository.save_vm_settlement_evidence(first)

    async def prepare(**fields):
        await repository.save_vm_settlement_evidence(
            replace(first, settlement_ref=fields["escrow_uid"])
        )
        raise AssertionError("a changed reference must stop before delivery")

    db = SimpleNamespace(
        load_negotiation_thread_row=AsyncMock(return_value=_thread()),
        load_escrow=AsyncMock(return_value=None),
    )
    monkeypatch.setattr(buyer_auth, "_verify", AsyncMock(return_value=SimpleNamespace(exact_retry=False)))
    monkeypatch.setattr(container, "configured_chain_names", lambda: ("anvil",))
    monkeypatch.setattr(container, "resolved_settlement_composition", SimpleNamespace(
        coordinator=SimpleNamespace(start=prepare),
        seller_stages=build_vm_storefront_domain().settlement.seller_stages,
        mechanism_clients={"alkahest.v1": object()}, evidence_clients={"anvil": object()},
        local_principal=_SELLER,
    ))
    with pytest.raises(HTTPException) as error:
        await _controller(db).settle_escrow("escrow-2", _body(), _request())
    assert error.value.status_code == 409
    assert await repository.load_vm_settlement_evidence(negotiation_id="neg-1") == first
    assert await repository.load_vm_delivery(negotiation_id="neg-1") is None
