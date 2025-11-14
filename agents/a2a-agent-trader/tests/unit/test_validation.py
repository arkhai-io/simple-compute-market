"""Unit tests for validation models and resource parsing."""

import pytest
from pydantic import ValidationError
import os

# Set a valid agent_id before importing agent module to avoid validation errors
os.environ['AGENT_ID'] = 'test_agent'

from app.schema.pydantic_models import (
    ResourceAlertRequest,
    MarketOrder,
    ComputeResource,
    TokenResource,
    Resource,
    ResourceImbalanceEvent,
    MakeOfferEvent,
    GPUModel,
    Region,
)
from app.agent import _parse_domain_event
from app.utils.validation import (
    validate_alert,
    validate_market_order,
    extract_compute_resource,
    extract_token_resource,
    extract_resources_from_make_offer_event,
)
from app.schema.pydantic_models import DecisionContext


class TestResourceAlertRequest:
    """Tests for ResourceAlertRequest validation."""
    
    def test_valid_alert(self):
        """Test validation of a valid alert."""
        alert_data = {
            "event_type": "resource_imbalance",
            "resource": {
                "gpu_model": "H200",
                "quantity": 1,
                "sla": 90.0,
                "region": "California, US",
            },
            "value": 0.05,
            "label": "LOW UTILIZATION",
            "threshold": "<=0.30",
        }
        alert = ResourceAlertRequest.model_validate(alert_data)
        assert alert.event_type == "resource_imbalance"
        assert alert.value == 0.05
        assert alert.label == "LOW UTILIZATION"
        assert alert.resource["gpu_model"] == "H200"
    
    def test_missing_required_fields(self):
        """Test that missing required fields raise ValidationError."""
        alert_data = {
            "event_type": "resource_imbalance",
            "resource": {
                "gpu_model": "H200",
                # Missing quantity, sla, region
            },
            "value": 0.05,
            "label": "LOW UTILIZATION",
            "threshold": "<=0.30",
        }
        with pytest.raises(ValidationError):
            ResourceAlertRequest.model_validate(alert_data)
    
    def test_value_out_of_range(self):
        """Test that value outside 0.0-1.0 range raises ValidationError."""
        alert_data = {
            "event_type": "resource_imbalance",
            "resource": {
                "gpu_model": "H200",
                "quantity": 1,
                "sla": 90.0,
                "region": "California, US",
            },
            "value": 1.5,  # Out of range
            "label": "LOW UTILIZATION",
            "threshold": "<=0.30",
        }
        with pytest.raises(ValidationError):
            ResourceAlertRequest.model_validate(alert_data)
    
    def test_to_resource_imbalance_event(self):
        """Test conversion to ResourceImbalanceEvent."""
        alert_data = {
            "event_type": "resource_imbalance",
            "resource": {
                "gpu_model": "H200",
                "quantity": 2,
                "sla": 95.0,
                "region": "Tokyo, JP",
            },
            "value": 0.15,
            "label": "LOW UTILIZATION",
            "threshold": "<=0.30",
        }
        alert = ResourceAlertRequest.model_validate(alert_data)
        event = alert.to_resource_imbalance_event(
            event_id="test_event",
            source="test_source"
        )
        
        assert isinstance(event, ResourceImbalanceEvent)
        assert event.event_id == "test_event"
        assert event.source == "test_source"
        assert event.severity == 0.15  # value mapped to severity
        assert event.resource.gpu_model == GPUModel.H200
        assert event.resource.quantity == 2
        assert event.resource.sla == 95.0
        assert event.resource.region == Region.TOKYO_JP
        assert event.data["label"] == "LOW UTILIZATION"
        assert event.data["threshold"] == "<=0.30"


class TestResourceParseFromDict:
    """Tests for Resource.parse_from_dict helper method."""
    
    def test_parse_token_resource_from_dict(self):
        """Test parsing TokenResource from dictionary."""
        token_dict = {
            "token": "USDT",
            "amount": 1000000000000000000,
        }
        resource = Resource.parse_from_dict(token_dict)
        
        assert isinstance(resource, TokenResource)
        assert resource.token == "USDT"
        assert resource.amount == 1000000000000000000
    
    def test_parse_compute_resource_from_dict(self):
        """Test parsing ComputeResource from dictionary."""
        compute_dict = {
            "gpu_model": "H200",
            "quantity": 1,
            "sla": 90.0,
            "region": "California, US",
        }
        resource = Resource.parse_from_dict(compute_dict)
        
        assert isinstance(resource, ComputeResource)
        assert resource.gpu_model == GPUModel.H200
        assert resource.quantity == 1
        assert resource.sla == 90.0
        assert resource.region == Region.CALIFORNIA_US
    
    def test_parse_token_takes_precedence_over_compute(self):
        """Test that token key takes precedence when both keys are present."""
        mixed_dict = {
            "token": "USDT",
            "amount": 1000000000000000000,
            "gpu_model": "H200",  # Should be ignored
            "quantity": 1,  # Should be ignored
        }
        resource = Resource.parse_from_dict(mixed_dict)
        
        assert isinstance(resource, TokenResource)
        assert resource.token == "USDT"
        assert not hasattr(resource, "gpu_model")
    
    def test_parse_invalid_dict_raises_value_error(self):
        """Test that invalid dict (missing both keys) raises ValueError."""
        invalid_dict = {
            "invalid": "data",
        }
        
        with pytest.raises(ValueError) as exc_info:
            Resource.parse_from_dict(invalid_dict)
        
        assert "token" in str(exc_info.value).lower() or "gpu_model" in str(exc_info.value).lower()
    
    def test_parse_existing_compute_resource_passes_through(self):
        """Test that existing ComputeResource instance passes through unchanged."""
        compute_res = ComputeResource(
            gpu_model=GPUModel.H200,
            quantity=1,
            sla=90.0,
            region=Region.CALIFORNIA_US,
        )
        result = Resource.parse_from_dict(compute_res)
        
        assert result is compute_res
        assert isinstance(result, ComputeResource)
    
    def test_parse_existing_token_resource_passes_through(self):
        """Test that existing TokenResource instance passes through unchanged."""
        token_res = TokenResource(token="USDT", amount=1000000000000000000)
        result = Resource.parse_from_dict(token_res)
        
        assert result is token_res
        assert isinstance(result, TokenResource)
    
    def test_parse_non_dict_passes_through(self):
        """Test that non-dict, non-Resource values pass through unchanged."""
        # Test with string
        result = Resource.parse_from_dict("some_string")
        assert result == "some_string"
        
        # Test with int
        result = Resource.parse_from_dict(42)
        assert result == 42
        
        # Test with None
        result = Resource.parse_from_dict(None)
        assert result is None
        
        # Test with list
        result = Resource.parse_from_dict([1, 2, 3])
        assert result == [1, 2, 3]


class TestMarketOrderResourceDeserialization:
    """Tests for MarketOrder resource polymorphic deserialization.
    
    These tests verify that MarketOrder correctly uses Resource.parse_from_dict()
    helper to parse offer_resource and demand_resource fields.
    """
    
    def test_compute_resource_offer(self):
        """Test MarketOrder with ComputeResource as offer_resource."""
        order_data = {
            "order_id": "test_order",
            "order_maker": "agent1",
            "offer_resource": {
                "gpu_model": "H200",
                "quantity": 1,
                "sla": 90.0,
                "region": "California, US",
            },
            "demand_resource": {
                "token": "USDT",
                "amount": 9000000000000000000,
            },
            "duration": 1,
        }
        order = MarketOrder.model_validate(order_data)
        
        assert isinstance(order.offer_resource, ComputeResource)
        assert order.offer_resource.gpu_model == GPUModel.H200
        assert isinstance(order.demand_resource, TokenResource)
        assert order.demand_resource.token == "USDT"
    
    def test_token_resource_offer(self):
        """Test MarketOrder with TokenResource as offer_resource."""
        order_data = {
            "order_id": "test_order",
            "order_maker": "agent1",
            "offer_resource": {
                "token": "USDT",
                "amount": 10000000000000000000,
            },
            "demand_resource": {
                "gpu_model": "Tesla V100",
                "quantity": 1,
                "sla": 99.9,
                "region": "New York, US",
            },
            "duration": 1,
        }
        order = MarketOrder.model_validate(order_data)
        
        assert isinstance(order.offer_resource, TokenResource)
        assert order.offer_resource.token == "USDT"
        assert isinstance(order.demand_resource, ComputeResource)
        assert order.demand_resource.gpu_model == GPUModel.TESLA_V100
    
    def test_invalid_resource_structure(self):
        """Test that invalid resource structure raises ValidationError."""
        order_data = {
            "order_id": "test_order",
            "order_maker": "agent1",
            "offer_resource": {
                # Missing both token and gpu_model
                "invalid": "data",
            },
            "demand_resource": {
                "token": "USDT",
                "amount": 9000000000000000000,
            },
            "duration": 1,
        }
        with pytest.raises(ValidationError):
            MarketOrder.model_validate(order_data)
    
    def test_resource_with_both_keys_prioritizes_token(self):
        """Test that resource with both token and gpu_model is parsed as TokenResource.
        
        When a resource dict contains both 'token' and 'gpu_model' keys, the parser
        prioritizes 'token' and creates a TokenResource. The 'gpu_model' key is ignored.
        This behavior ensures deterministic parsing when ambiguous data is provided.
        """
        order_data = {
            "order_id": "test_order",
            "order_maker": "agent1",
            "offer_resource": {
                "token": "USDT",
                "amount": 1000000000000000000,
                "gpu_model": "H200",  # Should be ignored - token takes precedence
                "quantity": 1,  # This would be invalid for TokenResource but ignored
            },
            "demand_resource": {
                "token": "USDT",
                "amount": 9000000000000000000,
            },
            "duration": 1,
        }
        order = MarketOrder.model_validate(order_data)
        assert isinstance(order.offer_resource, TokenResource)
        assert order.offer_resource.token == "USDT"
        # Verify gpu_model was not used
        assert not hasattr(order.offer_resource, 'gpu_model')
    
    def test_resource_already_instance_passes_through(self):
        """Test that Resource instances (not dicts) pass through unchanged."""
        compute_res = ComputeResource(
            gpu_model=GPUModel.H200,
            quantity=1,
            sla=90.0,
            region=Region.CALIFORNIA_US,
        )
        token_res = TokenResource(token="USDT", amount=1000000000000000000)
        
        # Create order with Resource instances directly
        order = MarketOrder(
            order_id="test_order",
            order_maker="agent1",
            offer_resource=compute_res,
            demand_resource=token_res,
            duration=1,
        )
        
        # Resources should be unchanged
        assert order.offer_resource is compute_res
        assert order.demand_resource is token_res


class TestParseDomainEvent:
    """Tests for _parse_domain_event function."""
    
    def test_parse_resource_imbalance_event(self):
        """Test parsing ResourceImbalanceEvent."""
        payload = {
            "event_type": "resource_imbalance",
            "event_id": "test_event",
            "source": "test_source",
            "data": {
                "resource": {
                    "gpu_model": "H200",
                    "quantity": 1,
                    "sla": 90.0,
                    "region": "California, US",
                },
                "imbalance_type": "surplus",
                "severity": 0.5,
            },
        }
        event = _parse_domain_event(payload)
        
        assert isinstance(event, ResourceImbalanceEvent)
        assert event.event_id == "test_event"
        assert event.resource.gpu_model == GPUModel.H200
        assert event.severity == 0.5
    
    def test_parse_make_offer_event(self):
        """Test parsing MakeOfferEvent."""
        payload = {
            "event_type": "make_offer",
            "event_id": "test_event",
            "source": "test_source",
            "data": {
                "offer": {
                    "order_id": "test_order",
                    "order_maker": "agent1",
                    "offer_resource": {
                        "gpu_model": "H200",
                        "quantity": 1,
                        "sla": 90.0,
                        "region": "California, US",
                    },
                    "demand_resource": {
                        "token": "USDT",
                        "amount": 9000000000000000000,
                    },
                    "duration": 1,
                },
            },
        }
        event = _parse_domain_event(payload)
        
        assert isinstance(event, MakeOfferEvent)
        assert event.order.order_id == "test_order"
        assert isinstance(event.order.offer_resource, ComputeResource)
        assert isinstance(event.order.demand_resource, TokenResource)
    
    def test_parse_missing_required_fields(self):
        """Test that missing required fields raise ValueError."""
        payload = {
            "event_type": "resource_imbalance",
            "data": {
                "resource": {
                    "gpu_model": "H200",
                    # Missing quantity, sla, region
                },
            },
        }
        with pytest.raises(ValueError):
            _parse_domain_event(payload)


class TestValidationUtilities:
    """Tests for validation utility functions."""
    
    def test_validate_alert(self):
        """Test validate_alert utility."""
        alert_data = {
            "event_type": "resource_imbalance",
            "resource": {
                "gpu_model": "H200",
                "quantity": 1,
                "sla": 90.0,
                "region": "California, US",
            },
            "value": 0.05,
            "label": "LOW UTILIZATION",
            "threshold": "<=0.30",
        }
        alert = validate_alert(alert_data)
        assert isinstance(alert, ResourceAlertRequest)
    
    def test_validate_market_order(self):
        """Test validate_market_order utility."""
        order_data = {
            "order_id": "test_order",
            "order_maker": "agent1",
            "offer_resource": {
                "gpu_model": "H200",
                "quantity": 1,
                "sla": 90.0,
                "region": "California, US",
            },
            "demand_resource": {
                "token": "USDT",
                "amount": 9000000000000000000,
            },
            "duration": 1,
        }
        order = validate_market_order(order_data)
        assert isinstance(order, MarketOrder)
    
    def test_extract_compute_resource(self):
        """Test extract_compute_resource utility."""
        compute_res = ComputeResource(
            gpu_model=GPUModel.H200,
            quantity=1,
            sla=90.0,
            region=Region.CALIFORNIA_US,
        )
        token_res = TokenResource(token="USDT", amount=1000000000000000000)
        
        assert extract_compute_resource(compute_res) == compute_res
        assert extract_compute_resource(token_res) is None
    
    def test_extract_token_resource(self):
        """Test extract_token_resource utility."""
        compute_res = ComputeResource(
            gpu_model=GPUModel.H200,
            quantity=1,
            sla=90.0,
            region=Region.CALIFORNIA_US,
        )
        token_res = TokenResource(token="USDT", amount=1000000000000000000)
        
        assert extract_token_resource(token_res) == token_res
        assert extract_token_resource(compute_res) is None
    
    def test_extract_resources_from_make_offer_event_valid(self):
        """Test extract_resources_from_make_offer_event with valid MakeOfferEvent."""
        order = MarketOrder(
            order_id="test_order",
            order_maker="agent1",
            offer_resource=ComputeResource(
                gpu_model=GPUModel.H200,
                quantity=1,
                sla=90.0,
                region=Region.CALIFORNIA_US,
            ),
            demand_resource=TokenResource(token="USDT", amount=1000000000000000000),
            duration=1,
        )
        make_offer_event = MakeOfferEvent.from_order(order)
        
        context = DecisionContext(
            event=make_offer_event,
            available_resources={},
            agent_id="test_agent",
        )
        
        order, offer_compute, demand_compute, offer_token, demand_token = extract_resources_from_make_offer_event(context)
        
        assert order is not None
        assert order.order_id == "test_order"
        assert offer_compute is not None
        assert isinstance(offer_compute, ComputeResource)
        assert offer_compute.gpu_model == GPUModel.H200
        assert demand_compute is None
        assert offer_token is None
        assert demand_token is not None
        assert isinstance(demand_token, TokenResource)
        assert demand_token.token == "USDT"
    
    def test_extract_resources_from_make_offer_event_mixed(self):
        """Test extract_resources_from_make_offer_event with mixed resource types."""
        order = MarketOrder(
            order_id="test_order",
            order_maker="agent1",
            offer_resource=TokenResource(token="USDT", amount=10000000000000000000),
            demand_resource=ComputeResource(
                gpu_model=GPUModel.TESLA_V100,
                quantity=2,
                sla=99.9,
                region=Region.NEW_YORK_US,
            ),
            duration=1,
        )
        make_offer_event = MakeOfferEvent.from_order(order)
        
        context = DecisionContext(
            event=make_offer_event,
            available_resources={},
            agent_id="test_agent",
        )
        
        order, offer_compute, demand_compute, offer_token, demand_token = extract_resources_from_make_offer_event(context)
        
        assert order is not None
        assert order.order_id == "test_order"
        assert offer_compute is None
        assert offer_token is not None
        assert isinstance(offer_token, TokenResource)
        assert offer_token.token == "USDT"
        assert demand_compute is not None
        assert isinstance(demand_compute, ComputeResource)
        assert demand_compute.gpu_model == GPUModel.TESLA_V100
        assert demand_token is None
    
    def test_extract_resources_from_make_offer_event_non_make_offer(self):
        """Test extract_resources_from_make_offer_event with non-MakeOfferEvent returns all None."""
        # Create a different event type
        resource_event = ResourceImbalanceEvent(
            event_id="test_event",
            source="test_source",
            resource=ComputeResource(
                gpu_model=GPUModel.H200,
                quantity=1,
                sla=90.0,
                region=Region.CALIFORNIA_US,
            ),
            imbalance_type="surplus",
            severity=0.5,
        )
        
        context = DecisionContext(
            event=resource_event,
            available_resources={},
            agent_id="test_agent",
        )
        
        order, offer_compute, demand_compute, offer_token, demand_token = extract_resources_from_make_offer_event(context)
        
        assert order is None
        assert offer_compute is None
        assert demand_compute is None
        assert offer_token is None
        assert demand_token is None

