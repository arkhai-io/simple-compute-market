"""Tests for agent sub-group commands (threads, thread, decisions, decision).

All commands now call the agent HTTP API via _fetch_json.
Tests mock _fetch_json to return sample JSON responses.
"""
from __future__ import annotations

import copy
import json
import os
from unittest.mock import patch

import typer
from typer.testing import CliRunner

# Ensure Rich uses a wide terminal so table columns aren't truncated.
os.environ["COLUMNS"] = "300"

from market.cli import app  # noqa: E402

runner = CliRunner()

# ── Sample data constants ────────────────────────────────────────────────

NEG_ACTIVE = "neg-active-001"
NEG_SUCCESS = "neg-success-002"
NEG_FAILURE = "neg-failure-003"

OUR_ORDER = "order-ours-aaa"
THEIR_ORDER = "order-theirs-bbb"

DEC_1 = "dec-001"
DEC_2 = "dec-002"
DEC_3 = "dec-003"

# ── Sample API responses ────────────────────────────────────────────────

SAMPLE_NEGOTIATIONS = [
    {
        "negotiation_id": NEG_ACTIVE, "our_order_id": OUR_ORDER,
        "their_order_id": THEIR_ORDER, "status": "active",
        "terminal_state": None, "updated_at": "2025-01-01T01:00:00",
        "round_count": 3,
    },
    {
        "negotiation_id": NEG_SUCCESS, "our_order_id": OUR_ORDER,
        "their_order_id": "order-theirs-ccc", "status": "success",
        "terminal_state": "accepted", "updated_at": "2025-01-02T02:00:00",
        "round_count": 2,
    },
    {
        "negotiation_id": NEG_FAILURE, "our_order_id": "order-ours-ddd",
        "their_order_id": "order-theirs-ddd", "status": "failure",
        "terminal_state": "rejected", "updated_at": "2025-01-03T03:00:00",
        "round_count": 0,
    },
]

SAMPLE_NEGOTIATION_DETAIL = {
    "negotiation_id": NEG_ACTIVE, "our_order_id": OUR_ORDER,
    "their_order_id": THEIR_ORDER, "our_agent_id": "agent-a",
    "their_agent_id": "agent-b", "status": "active",
    "terminal_state": None, "created_at": "2025-01-01T00:00:00",
    "updated_at": "2025-01-01T01:00:00", "our_strategy": "aggressive",
    "our_initial_price": 100,
    "messages": [
        {"round": 0, "sender": "agent-a", "action_taken": "MAKE_OFFER",
         "our_price": 100, "their_price": None, "proposed_price": 100,
         "message_type": "offer", "timestamp": "2025-01-01T00:01:00"},
        {"round": 1, "sender": "agent-b", "action_taken": "COUNTER_OFFER",
         "our_price": 100, "their_price": 80, "proposed_price": 90,
         "message_type": "counter", "timestamp": "2025-01-01T00:02:00"},
        {"round": 2, "sender": "agent-a", "action_taken": "COUNTER_OFFER",
         "our_price": 90, "their_price": 80, "proposed_price": 85,
         "message_type": "counter", "timestamp": "2025-01-01T00:03:00"},
    ],
}

SAMPLE_DECISIONS = [
    {"decision_id": DEC_1, "event_type": "order_matched", "policy_used": "default_policy",
     "action_type": "MAKE_OFFER", "timestamp": "2025-01-01T00:00:30",
     "outcome_json": {"status": "sent"}},
    {"decision_id": DEC_2, "event_type": "counter_received", "policy_used": "aggressive_policy",
     "action_type": "COUNTER_OFFER", "timestamp": "2025-01-01T00:02:30",
     "outcome_json": None},
    {"decision_id": DEC_3, "event_type": "offer_received", "policy_used": "default_policy",
     "action_type": "ACCEPT_OFFER", "timestamp": "2025-01-02T00:02:00",
     "outcome_json": {"status": "accepted", "final_price": 50}},
]

SAMPLE_DECISION_DETAIL = {
    "decision_id": DEC_1, "event_id": "evt-1", "event_type": "order_matched",
    "agent_id": "agent-a", "policy_used": "default_policy",
    "action_type": "MAKE_OFFER", "timestamp": "2025-01-01T00:00:30",
    "context_json": {"order_id": OUR_ORDER},
    "outcome_json": {"status": "sent"}, "outcome_timestamp": "2025-01-01T00:00:31",
}


def _not_found_side_effect(url: str) -> dict:
    """Simulate _fetch_json raising typer.Exit on 404."""
    raise typer.Exit(code=1)


# ── threads ──────────────────────────────────────────────────────────────

def test_threads_lists_all() -> None:
    with patch("market.groups.agent._fetch_json") as mock:
        mock.return_value = {"negotiations": SAMPLE_NEGOTIATIONS, "total": 3}
        result = runner.invoke(app, ["agent", "threads"])
        assert result.exit_code == 0
        assert NEG_ACTIVE in result.output
        assert NEG_SUCCESS in result.output
        assert NEG_FAILURE in result.output
        assert "/negotiations" in mock.call_args[0][0]


def test_threads_filter_status() -> None:
    filtered = [n for n in SAMPLE_NEGOTIATIONS if n["status"] == "active"]
    with patch("market.groups.agent._fetch_json") as mock:
        mock.return_value = {"negotiations": filtered, "total": 1}
        result = runner.invoke(app, ["agent", "threads", "--status", "active"])
        assert result.exit_code == 0
        assert NEG_ACTIVE in result.output
        assert NEG_SUCCESS not in result.output
        assert "status=active" in mock.call_args[0][0]


def test_threads_filter_order() -> None:
    filtered = [n for n in SAMPLE_NEGOTIATIONS if THEIR_ORDER in (n["our_order_id"], n["their_order_id"])]
    with patch("market.groups.agent._fetch_json") as mock:
        mock.return_value = {"negotiations": filtered, "total": 1}
        result = runner.invoke(app, ["agent", "threads", "--order-id", THEIR_ORDER])
        assert result.exit_code == 0
        assert NEG_ACTIVE in result.output
        assert NEG_FAILURE not in result.output


# ── thread detail ────────────────────────────────────────────────────────

def test_thread_detail() -> None:
    with patch("market.groups.agent._fetch_json") as mock:
        mock.return_value = SAMPLE_NEGOTIATION_DETAIL
        result = runner.invoke(app, ["agent", "thread", NEG_ACTIVE])
        assert result.exit_code == 0
        assert "Thread Detail" in result.output
        assert "aggressive" in result.output
        assert "100" in result.output
        assert "Rounds" in result.output
        assert "MAKE_OFFER" in result.output
        assert "COUNTER_OFFER" in result.output
        assert "Price Progression" in result.output


def test_thread_detail_success() -> None:
    detail = {
        **SAMPLE_NEGOTIATION_DETAIL,
        "negotiation_id": NEG_SUCCESS, "status": "success",
        "messages": [
            {"round": 0, "sender": "agent-a", "action_taken": "MAKE_OFFER",
             "our_price": 50, "their_price": None, "proposed_price": 50,
             "message_type": "offer", "timestamp": "2025-01-02T00:01:00"},
            {"round": 1, "sender": "agent-c", "action_taken": "ACCEPT_OFFER",
             "our_price": 50, "their_price": 50, "proposed_price": 50,
             "message_type": "accept", "timestamp": "2025-01-02T00:02:00"},
        ],
    }
    with patch("market.groups.agent._fetch_json") as mock:
        mock.return_value = detail
        result = runner.invoke(app, ["agent", "thread", NEG_SUCCESS])
        assert result.exit_code == 0
        assert "ACCEPT_OFFER" in result.output


def test_thread_not_found() -> None:
    with patch("market.groups.agent._fetch_json") as mock:
        mock.return_value = {"error": "Negotiation not found"}
        result = runner.invoke(app, ["agent", "thread", "nonexistent"])
        assert result.exit_code == 1
        assert "not found" in result.output


# ── decisions ────────────────────────────────────────────────────────────

def test_decisions_lists_all() -> None:
    with patch("market.groups.agent._fetch_json") as mock:
        mock.return_value = {"decisions": SAMPLE_DECISIONS, "total": 3}
        result = runner.invoke(app, ["agent", "decisions"])
        assert result.exit_code == 0
        assert DEC_1 in result.output
        assert DEC_2 in result.output
        assert DEC_3 in result.output
        assert "default_policy" in result.output


def test_decisions_filter_event() -> None:
    filtered = [d for d in SAMPLE_DECISIONS if d["event_type"] == "order_matched"]
    with patch("market.groups.agent._fetch_json") as mock:
        mock.return_value = {"decisions": filtered, "total": 1}
        result = runner.invoke(app, ["agent", "decisions", "--event-type", "order_matched"])
        assert result.exit_code == 0
        assert DEC_1 in result.output
        assert DEC_2 not in result.output


def test_decisions_filter_action() -> None:
    filtered = [d for d in SAMPLE_DECISIONS if d["action_type"] == "ACCEPT_OFFER"]
    with patch("market.groups.agent._fetch_json") as mock:
        mock.return_value = {"decisions": filtered, "total": 1}
        result = runner.invoke(app, ["agent", "decisions", "--action-type", "ACCEPT_OFFER"])
        assert result.exit_code == 0
        assert DEC_3 in result.output
        assert DEC_1 not in result.output
        assert DEC_2 not in result.output


# ── decision detail ──────────────────────────────────────────────────────

def test_decision_detail() -> None:
    with patch("market.groups.agent._fetch_json") as mock:
        mock.return_value = SAMPLE_DECISION_DETAIL
        result = runner.invoke(app, ["agent", "decision", DEC_1])
        assert result.exit_code == 0
        assert "Decision Detail" in result.output
        assert "order_matched" in result.output
        assert "default_policy" in result.output
        assert "Context" in result.output
        assert "Outcome" in result.output
        assert "sent" in result.output


def test_decision_detail_no_outcome() -> None:
    detail = {
        "decision_id": DEC_2, "event_id": "evt-2", "event_type": "counter_received",
        "agent_id": "agent-a", "policy_used": "aggressive_policy",
        "action_type": "COUNTER_OFFER", "timestamp": "2025-01-01T00:02:30",
        "context_json": {"round": 1}, "outcome_json": None, "outcome_timestamp": None,
    }
    with patch("market.groups.agent._fetch_json") as mock:
        mock.return_value = detail
        result = runner.invoke(app, ["agent", "decision", DEC_2])
        assert result.exit_code == 0
        assert "Decision Detail" in result.output
        assert "aggressive_policy" in result.output
        assert "Outcome" not in result.output


def test_decision_not_found() -> None:
    with patch("market.groups.agent._fetch_json") as mock:
        mock.return_value = {"error": "Decision not found"}
        result = runner.invoke(app, ["agent", "decision", "nonexistent"])
        assert result.exit_code == 1
        assert "not found" in result.output


# ── error handling ───────────────────────────────────────────────────────

# ── order match ──────────────────────────────────────────────────────────

SAMPLE_REGISTRY_ORDER = {
    "order": {
        "order_id": "order-123",
        "offer_resource": {"gpu_model": "H200", "quantity": 1, "sla": 99.9, "region": "California, US"},
        "demand_resource": {"token": "MOCK", "amount": 9.0},
        "duration_hours": 1,
    }
}


def test_match_with_price_override() -> None:
    captured_payload: dict | None = None

    def mock_post(url: str, payload: dict) -> dict:
        nonlocal captured_payload
        captured_payload = payload
        return {"status": "ok", "order_id": "new-order-456"}

    with (
        patch("market.cli._fetch_json", return_value=copy.deepcopy(SAMPLE_REGISTRY_ORDER)),
        patch("market.cli._post_json", side_effect=mock_post),
    ):
        result = runner.invoke(app, [
            "order", "match", "order-123",
            "--price", "6.0",
            "--agent-url", "http://localhost:8001",
            "--registry-url", "http://localhost:8080",
        ])
        assert result.exit_code == 0, result.output
        assert captured_payload is not None
        # The flipped demand (originally offer_resource with gpu) has no "amount",
        # so the flipped offer (originally demand_resource with token) should be overridden.
        offer = captured_payload["offer"]
        assert offer["amount"] == 6.0


def test_match_without_price_keeps_original() -> None:
    captured_payload: dict | None = None

    def mock_post(url: str, payload: dict) -> dict:
        nonlocal captured_payload
        captured_payload = payload
        return {"status": "ok", "order_id": "new-order-789"}

    with (
        patch("market.cli._fetch_json", return_value=copy.deepcopy(SAMPLE_REGISTRY_ORDER)),
        patch("market.cli._post_json", side_effect=mock_post),
    ):
        result = runner.invoke(app, [
            "order", "match", "order-123",
            "--agent-url", "http://localhost:8001",
            "--registry-url", "http://localhost:8080",
        ])
        assert result.exit_code == 0, result.output
        assert captured_payload is not None
        # Without --price, the original amount (9.0) should be preserved
        offer = captured_payload["offer"]
        assert offer["amount"] == 9.0


# ── error handling ───────────────────────────────────────────────────────

def test_api_connection_error() -> None:
    with patch("market.groups.agent._fetch_json", side_effect=_not_found_side_effect):
        result = runner.invoke(app, ["agent", "threads"])
        assert result.exit_code == 1
