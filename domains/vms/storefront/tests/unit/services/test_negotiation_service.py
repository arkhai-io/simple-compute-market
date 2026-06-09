"""Unit tests for NegotiationService.

Tests business logic in isolation using ``unittest.mock.AsyncMock`` for the
SQLite client dependency.  No HTTP layer, no database I/O.

Follows the provisioning-service unit test pattern: one class per service
method, each class covering the happy path + key error branches.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from market_core.storefront.services.negotiation_service import (
    NegotiationService,
    NegotiationServiceError,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _continue_negotiation_stub(**_: Any) -> dict[str, Any]:
    return {"action": "exit", "reason": "stubbed"}


def _stage_event_stub(*_: Any, **__: Any) -> None:
    return None


def _make_service(
    db: AsyncMock,
    *,
    continue_negotiation: AsyncMock | None = None,
    stage_event_fn: MagicMock | None = None,
) -> NegotiationService:
    return NegotiationService(
        sqlite_client=db,
        continue_negotiation=continue_negotiation or _continue_negotiation_stub,
        stage_event=stage_event_fn or _stage_event_stub,
    )


def _thread(
    neg_id: str = "neg-1",
    order_id: str = "ord-1",
    *,
    terminal_state: str | None = None,
    agreed_price: float | None = None,
    requested_duration_seconds: int | None = None,
) -> dict:
    return {
        "negotiation_id": neg_id,
        "our_listing_id": order_id,
        "their_agent_id": "0xBuyer",
        "terminal_state": terminal_state,
        "agreed_price": agreed_price,
        "requested_duration_seconds": requested_duration_seconds,
        "status": "active",
    }


def _order(order_id: str = "ord-1", duration_hours: int = 2) -> dict:
    # `duration_hours` here is just the test fixture knob; it controls the
    # listing's max_duration_seconds ceiling that the negotiation respects.
    return {
        "order_id": order_id,
        "status": "open",
        "max_duration_seconds": duration_hours * 3600,
        "offer_resource": {},
        "demand_resource": {},
    }


# ---------------------------------------------------------------------------
# list_for_order
# ---------------------------------------------------------------------------

class TestListForOrder:
    async def test_raises_404_if_order_not_found(self):
        db = AsyncMock()
        db.load_listing.return_value = None
        svc = _make_service(db)
        with pytest.raises(NegotiationServiceError) as exc_info:
            await svc.list_for_order(listing_id="ghost")
        assert exc_info.value.status_code == 404

    async def test_returns_threads_from_db(self):
        db = AsyncMock()
        db.load_listing.return_value = _order()
        db.list_negotiations_for_listing.return_value = [
            _thread("n1", "ord-1"),
            _thread("n2", "ord-1"),
        ]
        svc = _make_service(db)
        result = await svc.list_for_order(listing_id="ord-1")
        assert len(result) == 2
        db.list_negotiations_for_listing.assert_awaited_once_with(
            listing_id="ord-1",
            terminal_state=None,
            buyer_address=None,
            limit=50,
            offset=0,
        )

    async def test_passes_filters_to_db(self):
        db = AsyncMock()
        db.load_listing.return_value = _order()
        db.list_negotiations_for_listing.return_value = []
        svc = _make_service(db)
        await svc.list_for_order(
            listing_id="ord-1",
            terminal_state="success",
            buyer_address="0xBuyer",
            limit=10,
            offset=5,
        )
        db.list_negotiations_for_listing.assert_awaited_once_with(
            listing_id="ord-1",
            terminal_state="success",
            buyer_address="0xBuyer",
            limit=10,
            offset=5,
        )


# ---------------------------------------------------------------------------
# get_detail
# ---------------------------------------------------------------------------

class TestGetDetail:
    async def test_raises_404_if_not_found(self):
        db = AsyncMock()
        db.load_negotiation_detail.return_value = None
        svc = _make_service(db)
        with pytest.raises(NegotiationServiceError) as exc_info:
            await svc.get_detail(listing_id="ord-1", neg_id="ghost")
        assert exc_info.value.status_code == 404

    async def test_returns_detail(self):
        detail = {"negotiation_id": "neg-1", "messages": [], "stage_events": []}
        db = AsyncMock()
        db.load_negotiation_detail.return_value = detail
        svc = _make_service(db)
        result = await svc.get_detail(listing_id="ord-1", neg_id="neg-1")
        assert result is detail


# ---------------------------------------------------------------------------
# advance
# ---------------------------------------------------------------------------

class TestAdvance:
    async def test_raises_400_invalid_action(self):
        svc = _make_service(AsyncMock())
        with pytest.raises(NegotiationServiceError) as exc_info:
            await svc.advance(listing_id="o", neg_id="n", action="fly", proposal=None, reason=None)
        assert exc_info.value.status_code == 400

    async def test_raises_400_counter_without_price(self):
        svc = _make_service(AsyncMock())
        with pytest.raises(NegotiationServiceError) as exc_info:
            await svc.advance(listing_id="o", neg_id="n", action="counter", proposal=None, reason=None)
        assert exc_info.value.status_code == 400

    async def test_raises_404_thread_not_found(self):
        db = AsyncMock()
        db.load_negotiation_thread_row.return_value = None
        svc = _make_service(db)
        with pytest.raises(NegotiationServiceError) as exc_info:
            await svc.advance(listing_id="o", neg_id="ghost", action="exit", proposal=None, reason=None)
        assert exc_info.value.status_code == 404

    async def test_raises_404_thread_wrong_order(self):
        db = AsyncMock()
        db.load_negotiation_thread_row.return_value = _thread("neg-1", "ord-other")
        svc = _make_service(db)
        with pytest.raises(NegotiationServiceError) as exc_info:
            await svc.advance(listing_id="ord-1", neg_id="neg-1", action="exit", proposal=None, reason=None)
        assert exc_info.value.status_code == 404

    async def test_raises_409_already_terminal(self):
        db = AsyncMock()
        db.load_negotiation_thread_row.return_value = _thread(
            terminal_state="success", agreed_price=9000
        )
        svc = _make_service(db)
        with pytest.raises(NegotiationServiceError) as exc_info:
            await svc.advance(listing_id="ord-1", neg_id="neg-1", action="exit", proposal=None, reason=None)
        assert exc_info.value.status_code == 409

    async def test_delegates_to_continue_sync_negotiation(self):
        db = AsyncMock()
        db.load_negotiation_thread_row.return_value = _thread()

        mock_result = {"action": "exit", "reason": "operator_decision"}
        mock_continue = AsyncMock(return_value=mock_result)
        svc = _make_service(db, continue_negotiation=mock_continue)
        result = await svc.advance(
            listing_id="ord-1",
            neg_id="neg-1",
            action="exit",
            proposal=None,
            reason="operator_decision",
        )

        mock_continue.assert_awaited_once()
        assert result["action"] == "exit"
        assert result["neg_id"] == "neg-1"
# ---------------------------------------------------------------------------
# force_accept
# ---------------------------------------------------------------------------

class TestForceAccept:
    async def test_raises_404_thread_not_found(self):
        db = AsyncMock()
        db.load_negotiation_thread_row.return_value = None
        svc = _make_service(db)
        with pytest.raises(NegotiationServiceError) as exc_info:
            await svc.force_accept(listing_id="o", neg_id="ghost", amount=9000)
        assert exc_info.value.status_code == 404

    async def test_raises_404_thread_wrong_order(self):
        db = AsyncMock()
        db.load_negotiation_thread_row.return_value = _thread("neg-1", "ord-other")
        svc = _make_service(db)
        with pytest.raises(NegotiationServiceError) as exc_info:
            await svc.force_accept(listing_id="ord-1", neg_id="neg-1", amount=9000)
        assert exc_info.value.status_code == 404

    async def test_raises_409_already_terminal(self):
        db = AsyncMock()
        db.load_negotiation_thread_row.return_value = _thread(terminal_state="success")
        svc = _make_service(db)
        with pytest.raises(NegotiationServiceError) as exc_info:
            await svc.force_accept(listing_id="ord-1", neg_id="neg-1", amount=9000)
        assert exc_info.value.status_code == 409

    async def test_commits_agreed_terms_and_returns_result(self):
        db = AsyncMock()
        db.load_negotiation_thread_row.return_value = _thread()
        db.load_listing.return_value = _order(duration_hours=3)
        db.commit_agreed_terms = AsyncMock()
        db.save_negotiation_message = AsyncMock()
        db.update_negotiation_thread_terminal = AsyncMock()

        stage_event = MagicMock()
        svc = _make_service(db, stage_event_fn=stage_event)
        result = await svc.force_accept(
            listing_id="ord-1", neg_id="neg-1", amount=8500
        )

        db.save_negotiation_message.assert_awaited_once()
        db.update_negotiation_thread_terminal.assert_awaited_once_with(
            negotiation_id="neg-1",
            terminal_state="success",
        )
        db.commit_agreed_terms.assert_awaited_once_with(
            negotiation_id="neg-1",
            agreed_price=8500,
            agreed_duration_seconds=3 * 3600,
        )
        assert result["action"] == "accept"
        assert result["amount"] == 8500
        assert result["source"] == "admin_force_accept"
        stage_event.assert_called_once()
