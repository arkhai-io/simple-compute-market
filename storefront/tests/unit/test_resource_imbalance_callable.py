"""Unit tests for ri.action.make_offer_from_resource.

The callable was previously broken — it produced a ``MAKE_OFFER`` action
without the ``offer``/``demand`` parameters that
``action_executor.execute_action`` requires (line 199-203). Any resource
alert that fired the policy would hit ``ValueError: MAKE_OFFER requires
explicit 'offer' and 'demand' parameters`` on dispatch.

The fix builds a complete offer/demand pair from the alerting compute
resource plus CONFIG defaults (default_token + default_min_price).
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
from service.clients.token import ERC20TokenMetadata, TokenRegistry


_RESOURCE = ComputeResource(
    gpu_model=GPUModel.H200,
    gpu_count=1,
    sla=99.0,
    region=Region.CALIFORNIA_US,
)

_MOCK_TOKEN = ERC20TokenMetadata(
    symbol="MOCK",
    contract_address="0x1234567890123456789012345678901234567890",
    decimals=6,
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
def mock_token_registry():
    """Patch TOKEN_REGISTRY in the policy store module to resolve "MOCK"
    without loading a real token registry file."""
    fake_registry = TokenRegistry()
    fake_registry.register_token(_MOCK_TOKEN)
    with patch("domain.compute.agent.app.policy.store.TOKEN_REGISTRY", fake_registry):
        yield


class TestRiActionMakeOfferFromResource:
    def test_surplus_with_defaults_produces_complete_make_offer(self, mock_token_registry):
        """Action carries offer + demand so action_executor.execute_action
        does not raise ``MAKE_OFFER requires explicit 'offer' and 'demand' parameters``."""
        from domain.compute.agent.app.policy.store import (
            ri_action_make_offer_from_resource,
        )

        cfg = _patched_config(
            default_token="MOCK",
            default_min_price="1000",
            default_max_duration_seconds=3600,
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

    def test_returns_none_when_default_min_price_unset(self, mock_token_registry):
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

    def test_returns_none_for_non_surplus_imbalance(self, mock_token_registry):
        """Deficit alerts are a buy-side concern; the seller storefront skips them."""
        from domain.compute.agent.app.policy.store import (
            ri_action_make_offer_from_resource,
        )

        cfg = _patched_config(default_min_price="1000", default_token="MOCK")
        with patch("domain.compute.agent.app.policy.store.CONFIG", cfg):
            action = ri_action_make_offer_from_resource(
                _build_context(imbalance_type="deficit"),
            )

        assert action is None

    def test_returns_none_when_token_unresolvable(self):
        """Misconfigured default_token (missing from registry) → fall through."""
        from domain.compute.agent.app.policy.store import (
            ri_action_make_offer_from_resource,
        )

        empty_registry = TokenRegistry()
        cfg = _patched_config(default_min_price="1000", default_token="DOES_NOT_EXIST")
        with patch("domain.compute.agent.app.policy.store.TOKEN_REGISTRY", empty_registry), \
             patch("domain.compute.agent.app.policy.store.CONFIG", cfg):
            action = ri_action_make_offer_from_resource(_build_context())

        assert action is None
