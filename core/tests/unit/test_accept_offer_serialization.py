"""Tests that accept_offer serializes Pydantic objects in order_dict to JSON primitives.

Regression test for: buyer's accept_offer result containing Python reprs like
ComputeResource(...) / TokenResource(...) / GPUModel.H200, which caused
'Cannot parse empty payload as DomainEvent' on the receiving seller agent.
"""

import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from core.agent.app.schema.pydantic_models import (
    ComputeResource,
    ERC20TokenMetadata,
    GPUModel,
    Region,
    TokenResource,
)


# --- fixtures ---

@pytest.fixture
def order_dict_with_pydantic_objects():
    """Order dict as it arrives from the policy store: resource fields are Pydantic instances."""
    return {
        "order_id": "f44d70df-9745-4c3b-b59a-9fc1cffc8a56",
        "order_maker": "http://seller:8001",
        "order_taker": None,
        "offer_resource": ComputeResource(
            resource_id="compute-h200-001",
            gpu_model=GPUModel.H200,
            quantity=1,
            sla=90.0,
            region=Region.CALIFORNIA_US,
            vm_host="vm1",
        ),
        "demand_resource": TokenResource(
            token=ERC20TokenMetadata(
                symbol="WETH",
                name="Wrapped Ether (WETH9)",
                contract_address="0xfff9976782d46cc05630d1f6ebab18b2324d6b14",
                decimals=18,
            ),
            amount=9_000_000_000_000,
        ),
        "duration_hours": 1,
        "maker_attestation": None,
        "taker_attestation": None,
        "oracle_address": None,
    }


# --- tests ---

class TestAcceptOfferSerialization:

    @pytest.mark.asyncio
    async def test_event_payload_is_json_serializable_when_order_contains_pydantic_objects(
        self, order_dict_with_pydantic_objects
    ):
        """accept_offer must send a JSON-serializable payload even when
        parameters['order'] is a dict containing Pydantic model instances.

        Regression intent: Pydantic reprs like `ComputeResource(...)` or
        `GPUModel.H200` used to leak into the outbound payload and break
        `ast.literal_eval` on the receiving agent. With HTTP transport
        the payload is `json.dumps`-ed directly, so non-JSON-safe values
        would crash the send rather than confuse the receiver — but the
        invariant is the same: everything must be primitive.
        """
        from core.agent.app.utils.action_executor import accept_offer

        captured_payloads = []

        def mock_fire_and_forget(*, peer_url, event_type, payload, message_type=None):
            captured_payloads.append({"peer_url": peer_url, "event_type": event_type, "payload": payload})

        our_url = "http://seller:8001"
        parameters = {
            "order_id": order_dict_with_pydantic_objects["order_id"],
            "negotiation_id": "neg-id",
            "our_order_id": "our-order-123",
            "their_order_id": order_dict_with_pydantic_objects["order_id"],
            "order": order_dict_with_pydantic_objects,
            "counterparty_url": "http://buyer:8000",
        }

        mock_txn = AsyncMock()
        mock_txn.__aenter__ = AsyncMock(return_value=mock_txn)
        mock_txn.__aexit__ = AsyncMock(return_value=None)
        mock_txn.cancel_competing = AsyncMock(return_value=[])
        mock_txn.ensure_thread = AsyncMock()
        mock_txn.add_message = AsyncMock()
        mock_txn.mark_terminal = AsyncMock()

        with (
            patch("core.agent.app.utils.action_executor.NegotiationThreadTransaction", return_value=mock_txn),
            patch("core.agent.app.utils.action_executor.get_sqlite_client", return_value=AsyncMock()),
            patch("core.agent.app.utils.action_executor.get_registry_client", return_value=AsyncMock()),
            patch("core.agent.app.utils.action_executor.dispatch_message_background", side_effect=mock_fire_and_forget),
            patch("core.agent.app.utils.action_executor.BASE_URL_OVERRIDE", our_url),
            patch("core.agent.app.utils.action_executor.AGENT_ID", "arkhai_seller_agent"),
            patch("core.agent.app.utils.action_executor.SSH_PUBLIC_KEY", None),
            patch("core.agent.app.utils.action_executor.CONFIG", MagicMock(enable_registry_discovery=False)),
        ):
            await accept_offer(alkahest_client=None, ctx=None, parameters=parameters)

        assert len(captured_payloads) == 1, "Expected exactly one HTTP dispatch"
        payload = captured_payloads[0]["payload"]

        try:
            json.dumps(payload)
        except (TypeError, ValueError) as exc:
            pytest.fail(f"Payload is not JSON-serializable: {exc}\npayload={payload}")

        payload_str = str(payload)
        assert "ComputeResource(" not in payload_str, "ComputeResource repr leaked into payload"
        assert "TokenResource(" not in payload_str, "TokenResource repr leaked into payload"
        assert "GPUModel." not in payload_str, "GPUModel enum repr leaked into payload"
        assert "Region." not in payload_str, "Region enum repr leaked into payload"

    @pytest.mark.asyncio
    async def test_event_payload_preserves_values_after_serialization(
        self, order_dict_with_pydantic_objects
    ):
        """Serialization must not drop or corrupt values."""
        from core.agent.app.utils.action_executor import accept_offer

        captured_payloads = []

        def mock_fire_and_forget(*, peer_url, event_type, payload, message_type=None):
            captured_payloads.append(payload)

        our_url = "http://seller:8001"
        parameters = {
            "order_id": order_dict_with_pydantic_objects["order_id"],
            "our_order_id": "our-order-123",
            "their_order_id": order_dict_with_pydantic_objects["order_id"],
            "order": order_dict_with_pydantic_objects,
            "counterparty_url": "http://buyer:8000",
        }

        mock_txn = AsyncMock()
        mock_txn.__aenter__ = AsyncMock(return_value=mock_txn)
        mock_txn.__aexit__ = AsyncMock(return_value=None)
        mock_txn.cancel_competing = AsyncMock(return_value=[])
        mock_txn.ensure_thread = AsyncMock()
        mock_txn.add_message = AsyncMock()
        mock_txn.mark_terminal = AsyncMock()

        with (
            patch("core.agent.app.utils.action_executor.NegotiationThreadTransaction", return_value=mock_txn),
            patch("core.agent.app.utils.action_executor.get_sqlite_client", return_value=AsyncMock()),
            patch("core.agent.app.utils.action_executor.get_registry_client", return_value=AsyncMock()),
            patch("core.agent.app.utils.action_executor.dispatch_message_background", side_effect=mock_fire_and_forget),
            patch("core.agent.app.utils.action_executor.BASE_URL_OVERRIDE", our_url),
            patch("core.agent.app.utils.action_executor.AGENT_ID", "arkhai_seller_agent"),
            patch("core.agent.app.utils.action_executor.SSH_PUBLIC_KEY", None),
            patch("core.agent.app.utils.action_executor.CONFIG", MagicMock(enable_registry_discovery=False)),
        ):
            await accept_offer(alkahest_client=None, ctx=None, parameters=parameters)

        payload = captured_payloads[0]
        offer = payload["offer"]

        assert offer["order_id"] == "f44d70df-9745-4c3b-b59a-9fc1cffc8a56"
        assert offer["offer_resource"]["gpu_model"] == "H200"
        assert offer["offer_resource"]["region"] == "California, US"
        assert offer["demand_resource"]["amount"] == 9_000_000_000_000
        assert offer["demand_resource"]["token"]["symbol"] == "WETH"
