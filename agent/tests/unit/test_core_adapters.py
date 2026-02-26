"""Compatibility tests for legacy <-> core adapter seams."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.append(str(REPO_ROOT))

from app.adapters.from_core import (  # noqa: E402
    core_domain_action_to_legacy,
    core_domain_event_to_legacy,
)
from app.adapters.to_core import (  # noqa: E402
    event_payload_to_core_domain_event,
    legacy_action_to_core,
    legacy_domain_event_to_core,
)
from app.schema.pydantic_models import (  # noqa: E402
    Action,
    ActionType,
    DomainEvent,
    EventType,
)
from core.action import ActionDispatcher, ActionHandler  # noqa: E402
from core.policy import PolicyEngine  # noqa: E402
from core.schemas import DomainAction as CoreDomainAction  # noqa: E402
from core.schemas import DecisionContext as CoreDecisionContext  # noqa: E402


def test_domain_event_round_trip_legacy_core_legacy() -> None:
    legacy = DomainEvent(
        event_id="evt_123",
        event_type=EventType.ORDER_CREATE,
        source="test-source",
        data={"foo": "bar"},
    )

    core_event = legacy_domain_event_to_core(legacy)
    restored = core_domain_event_to_legacy(core_event)

    assert restored.event_id == legacy.event_id
    assert restored.event_type == legacy.event_type
    assert restored.source == legacy.source
    assert restored.data == legacy.data


def test_action_round_trip_legacy_core_legacy() -> None:
    legacy_action = Action(
        action_type=ActionType.MAKE_OFFER,
        parameters={"k": "v"},
    )

    core_action = legacy_action_to_core(legacy_action)
    restored = core_domain_action_to_legacy(core_action)

    assert restored.action_type == legacy_action.action_type
    assert restored.parameters == legacy_action.parameters


def test_event_payload_to_core_domain_event_normalizes_event_type() -> None:
    payload = {
        "event_id": "evt_payload",
        "event_type": EventType.ORDER_CLOSE,
        "source": "payload-source",
        "data": {"order_id": "ord_1"},
    }

    core_event = event_payload_to_core_domain_event(payload)
    assert core_event.event_type == EventType.ORDER_CLOSE.value
    assert core_event.data == {"order_id": "ord_1"}


class _EchoActionHandler(ActionHandler):
    async def execute(self, action: CoreDomainAction, **kwargs):
        return {"action_type": action.action_type, "kwargs": kwargs}


@pytest.mark.asyncio
async def test_action_dispatcher_smoke() -> None:
    dispatcher = ActionDispatcher()
    dispatcher.register("make_offer", _EchoActionHandler())
    result = await dispatcher.dispatch(CoreDomainAction(action_type="make_offer"), trace_id="t1")
    assert result["action_type"] == "make_offer"
    assert result["kwargs"]["trace_id"] == "t1"


def test_policy_engine_smoke() -> None:
    engine = PolicyEngine()

    def returns_none(_ctx):
        return None

    def choose_make_offer(_ctx):
        return CoreDomainAction(action_type="make_offer", parameters={"x": 1})

    engine.register(returns_none)
    engine.register(choose_make_offer)

    ctx = CoreDecisionContext(
        event=event_payload_to_core_domain_event(
            {
                "event_id": "evt_p",
                "event_type": EventType.MAKE_OFFER.value,
                "source": "s",
                "data": {},
            }
        ),
        agent_id="agent",
    )
    action = engine.evaluate(ctx)
    assert action is not None
    assert action.action_type == "make_offer"
