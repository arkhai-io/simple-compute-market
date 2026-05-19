"""Unit tests for ri.action.make_offer_from_resource.

The callable was previously broken — it produced a ``MAKE_OFFER`` action
without the ``offer``/``demand`` parameters that
``action_executor.execute_action`` requires (line 199-203). Any resource
alert that fired the policy would hit ``ValueError: MAKE_OFFER requires
explicit 'offer' and 'demand' parameters`` on dispatch.

The fix builds a complete offer/demand pair from the alerting compute
resource plus CONFIG defaults (default_token_address + default_min_price);
decimals are resolved on chain via ``service.clients.token.resolve_token``.
"""
from __future__ import annotations

import dataclasses
from unittest.mock import patch

import pytest

from market_storefront.models.domain_models import (
    Action as DomainAction,
    ActionType as DomainActionType,
    ComputeResource,
    DecisionContext,
    GPUModel,
    Region,
    ResourceImbalanceEvent,
)
from market_storefront.utils.config import CONFIG
from service.clients.token import ERC20TokenMetadata, TokenResolutionError


_RESOURCE = ComputeResource(
    gpu_model=GPUModel.H200,
    gpu_count=1,
    sla=99.0,
    region=Region.CALIFORNIA_US,
)

_MOCK_ADDRESS = "0x1234567890123456789012345678901234567890"
_MOCK_TOKEN = ERC20TokenMetadata(
    symbol="MOCK",
    contract_address=_MOCK_ADDRESS,
    decimals=6,
    chain_id=1,
)


def _build_context(*, imbalance_type: str = "surplus") -> DecisionContext:
    event = ResourceImbalanceEvent(
        event_id="evt-1",
        source="resource-monitor",
        resource=_RESOURCE,
        imbalance_type=imbalance_type,
        severity=0.5,
    )
    return DecisionContext(
        event=event,
        agent_id="seller-1",
        available_resources={},
        market_state={},
        negotiation_history=[],
        past_experiences=[],
    )


def _patched_config(**overrides):
    """Build a CONFIG-shaped clone with the requested overrides.

    CONFIG is a frozen dataclass — `dataclasses.replace` is the only
    supported way to flip a field for a test.
    """
    return dataclasses.replace(CONFIG, **overrides)


@pytest.fixture
def stubbed_resolve_token():
    """Patch the chain-RPC resolver inside policy/store.py to return the
    canned MOCK metadata without an RPC. ``_resolve_chain_id`` is imported
    lazily inside the function so we patch it at its source module."""
    def fake_resolve(address, *, rpc_url, chain_id, refresh=False):
        if address.lower() == _MOCK_ADDRESS.lower():
            return _MOCK_TOKEN
        raise TokenResolutionError(f"untested address: {address}")
    with patch("domain.compute.agent.app.policy.store.resolve_token", fake_resolve), \
         patch("market_storefront.utils.config._resolve_chain_id", lambda: 1):
        yield


class TestRiActionMakeOfferFromResource:
    def test_surplus_with_defaults_produces_complete_make_offer(self, stubbed_resolve_token):
        """Action carries offer + demand so action_executor.execute_action
        does not raise ``MAKE_OFFER requires explicit 'offer' and 'demand' parameters``."""
        from domain.compute.agent.app.policy.store import (
            ri_action_make_offer_from_resource,
        )

        cfg = _patched_config(
            default_token_address=_MOCK_ADDRESS,
            default_min_price="1000",
            default_max_duration_seconds=3600,
            chain_rpc_url="http://rpc",
        )
        with patch("domain.compute.agent.app.policy.store.CONFIG", cfg):
            action = ri_action_make_offer_from_resource(_build_context())

        assert isinstance(action, DomainAction)
        assert action.action_type == DomainActionType.MAKE_OFFER

        params = action.parameters
        assert "offer" in params and isinstance(params["offer"], dict)
        assert "demand" in params and isinstance(params["demand"], dict)
        assert params["offer"]["gpu_model"] == "H200"
        assert params["demand"]["amount"] == 1000
        assert params["demand"]["token"]["contract_address"] == _MOCK_TOKEN.contract_address
        assert params["max_duration_seconds"] == 3600
        assert params["paused"] is False

    def test_returns_none_when_default_min_price_unset(self, stubbed_resolve_token):
        """Without a configured floor price we cannot synthesise a demand
        and so the policy falls through to no_action rather than producing
        an incomplete MAKE_OFFER."""
        from domain.compute.agent.app.policy.store import (
            ri_action_make_offer_from_resource,
        )

        cfg = _patched_config(default_min_price=None)
        with patch("domain.compute.agent.app.policy.store.CONFIG", cfg):
            action = ri_action_make_offer_from_resource(_build_context())

        assert action is None

    def test_returns_none_for_non_surplus_imbalance(self, stubbed_resolve_token):
        """Deficit alerts are a buy-side concern; the seller storefront skips them."""
        from domain.compute.agent.app.policy.store import (
            ri_action_make_offer_from_resource,
        )

        cfg = _patched_config(
            default_min_price="1000",
            default_token_address=_MOCK_ADDRESS,
            chain_rpc_url="http://rpc",
        )
        with patch("domain.compute.agent.app.policy.store.CONFIG", cfg):
            action = ri_action_make_offer_from_resource(
                _build_context(imbalance_type="deficit"),
            )

        assert action is None

    def test_returns_none_when_token_address_unset(self):
        """default_token_address=None → fall through cleanly."""
        from domain.compute.agent.app.policy.store import (
            ri_action_make_offer_from_resource,
        )

        cfg = _patched_config(
            default_min_price="1000",
            default_token_address=None,
            chain_rpc_url="http://rpc",
        )
        with patch("domain.compute.agent.app.policy.store.CONFIG", cfg):
            action = ri_action_make_offer_from_resource(_build_context())

        assert action is None

    def test_returns_none_when_chain_resolve_fails(self):
        """RPC unreachable / bad address → fall through cleanly."""
        from domain.compute.agent.app.policy.store import (
            ri_action_make_offer_from_resource,
        )

        def always_fail(*a, **k):
            raise TokenResolutionError("RPC down")

        cfg = _patched_config(
            default_min_price="1000",
            default_token_address=_MOCK_ADDRESS,
            chain_rpc_url="http://rpc",
        )
        with patch("domain.compute.agent.app.policy.store.resolve_token", always_fail), \
             patch("market_storefront.utils.config._resolve_chain_id", lambda: 1), \
             patch("domain.compute.agent.app.policy.store.CONFIG", cfg):
            action = ri_action_make_offer_from_resource(_build_context())

        assert action is None
