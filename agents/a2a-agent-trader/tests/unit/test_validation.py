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
    ResourceImbalanceEvent,
    MakeOfferEvent,
    GPUModel,
    Region,
    Tag,
)
from app.agent import _parse_domain_event
from app.utils.validation import (
    validate_alert,
    validate_market_order,
    extract_compute_resource,
    extract_token_resource,
)


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


class TestMarketOrderResourceDeserialization:
    """Tests for MarketOrder resource polymorphic deserialization."""
    
    def test_compute_resource_offer(self):
        """Test MarketOrder with ComputeResource as offer_resource."""
        order_data = {
            "order_id": "test_order",
            "tag": "sell",
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
            "tag": "buy",
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
            "tag": "sell",
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
                    "tag": "sell",
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
            "tag": "sell",
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

