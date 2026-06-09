"""Unit tests for the resource adapter registry (resources.py)."""

import pytest

from domains.vms.listings.models import (
    ComputeResource,
    ERC20TokenMetadata,
    GPUModel,
    Region,
    TokenResource,
)
from market_storefront.resources import (
    adapt_db_resource_to_domain_resource,
    adapt_domain_resource_to_db_resource,
    parse_resource_from_dict,
    register_resource_adapter,
)
from domains.vms.listings import resources as _resource_registry

USDT = ERC20TokenMetadata(
    symbol="USDT",
    contract_address="0xdac17f958d2ee523a2206206994597c13d831ec7",
    decimals=6,
)

COMPUTE = ComputeResource(
    gpu_model=GPUModel.H200,
    gpu_count=2,
    sla=99.0,
    region=Region.CALIFORNIA_US,
)

TOKEN = TokenResource(token=USDT, amount=5_000_000)


# ---------------------------------------------------------------------------
# parse_resource_from_dict
# ---------------------------------------------------------------------------

class TestParseResourceFromDict:
    def test_compute_via_resource_type(self):
        data = {
            "resource_type": "compute.gpu",
            "gpu_model": "H200",
            "gpu_count": 2,
            "sla": 99.0,
            "region": "California, US",
        }
        result = parse_resource_from_dict(data)
        assert isinstance(result, ComputeResource)
        assert result.gpu_model == GPUModel.H200
        assert result.gpu_count == 2

    def test_compute_via_discriminator_key_fallback(self):
        """No resource_type in payload — falls back to gpu_model discriminator."""
        data = {"gpu_model": "H200", "gpu_count": 1, "sla": 90.0, "region": "California, US"}
        result = parse_resource_from_dict(data)
        assert isinstance(result, ComputeResource)

    def test_token_via_resource_type(self):
        data = {
            "resource_type": "token.erc20",
            "token": {"symbol": "USDT", "contract_address": "0xdac17f958d2ee523a2206206994597c13d831ec7", "decimals": 6},
            "amount": 5_000_000,
        }
        result = parse_resource_from_dict(data)
        assert isinstance(result, TokenResource)
        assert result.token.symbol == "USDT"
        assert result.amount == 5_000_000

    def test_token_via_discriminator_key_fallback(self):
        """No resource_type — falls back to token discriminator."""
        data = {
            "token": {"symbol": "USDT", "contract_address": "0xdac17f958d2ee523a2206206994597c13d831ec7", "decimals": 6},
            "amount": 1_000_000,
        }
        result = parse_resource_from_dict(data)
        assert isinstance(result, TokenResource)

    def test_non_dict_passes_through(self):
        assert parse_resource_from_dict("raw_string") == "raw_string"
        assert parse_resource_from_dict(42) == 42
        assert parse_resource_from_dict(None) is None

    def test_existing_domain_instance_passes_through(self):
        assert parse_resource_from_dict(COMPUTE) is COMPUTE
        assert parse_resource_from_dict(TOKEN) is TOKEN

    def test_unknown_dict_raises(self):
        with pytest.raises(ValueError, match="Cannot determine resource type"):
            parse_resource_from_dict({"unknown_key": "value"})


# ---------------------------------------------------------------------------
# DB round-trip: from_domain_resource / to_domain_resource
# ---------------------------------------------------------------------------

class TestDbRoundTrip:
    def test_compute_round_trip(self):
        db_row = adapt_domain_resource_to_db_resource(
            COMPUTE, resource_id="res-1", state="available"
        )
        assert db_row["resource_type"] == "compute.gpu"
        assert db_row["resource_id"] == "res-1"
        assert db_row["state"] == "available"
        assert db_row["attributes"]["gpu_model"] == "H200"

        restored = adapt_db_resource_to_domain_resource(db_row)
        assert isinstance(restored, ComputeResource)
        assert restored.gpu_model == COMPUTE.gpu_model
        assert restored.gpu_count == COMPUTE.gpu_count
        assert restored.sla == COMPUTE.sla
        assert restored.region == COMPUTE.region

    def test_token_round_trip(self):
        db_row = adapt_domain_resource_to_db_resource(
            TOKEN, resource_id="res-2", state="locked"
        )
        assert db_row["resource_type"] == "token.erc20"
        assert db_row["resource_id"] == "res-2"
        assert db_row["attributes"]["symbol"] == "USDT"

        restored = adapt_db_resource_to_domain_resource(db_row)
        assert isinstance(restored, TokenResource)
        assert restored.token.symbol == TOKEN.token.symbol
        assert restored.amount == TOKEN.amount

    def test_unsupported_domain_type_raises(self):
        with pytest.raises(ValueError, match="Unsupported domain resource type"):
            adapt_domain_resource_to_db_resource(object(), resource_id="x")

    def test_missing_resource_type_raises(self):
        with pytest.raises(ValueError, match="missing resource_type"):
            adapt_db_resource_to_domain_resource({"value": 1})


# ---------------------------------------------------------------------------
# Third-party / generic adapter registration
# ---------------------------------------------------------------------------

class InformationResource:
    """A plain note/document resource from the information domain."""

    def __init__(self, content: str, format: str):
        self.content = content
        self.format = format


from dataclasses import dataclass as _dc
from typing import Any as _Any


@_dc(frozen=True)
class InformationNoteAdapter:
    resource_type: str = "information.note"
    domain_type: type = InformationResource
    discriminator_key: str = "content"

    def from_dict(self, data: dict[str, _Any]) -> InformationResource:
        return InformationResource(content=data["content"], format=data.get("format", "plaintext"))

    def to_domain_resource(self, db_resource: dict[str, _Any]) -> InformationResource:
        attrs = db_resource.get("attributes") or {}
        return InformationResource(
            content=attrs.get("content", ""),
            format=attrs.get("format", "plaintext"),
        )

    def from_domain_resource(
        self,
        resource: InformationResource,
        *,
        resource_id: str,
        state: str | None = None,
    ) -> dict[str, _Any]:
        return {
            "resource_id": resource_id,
            "resource_type": self.resource_type,
            "resource_subtype": resource.format,
            "unit": "document",
            "value": 1,
            "state": state,
            "attributes": {"content": resource.content, "format": resource.format},
        }

    def to_dict(self, resource: InformationResource) -> dict[str, _Any]:
        return {"resource_type": self.resource_type, "content": resource.content, "format": resource.format}


class TestThirdPartyAdapterRegistration:
    @pytest.fixture(autouse=True)
    def _register(self):
        resource_type_snapshot = dict(_resource_registry._RESOURCE_TYPE_TO_ADAPTER)
        domain_type_snapshot = dict(_resource_registry._DOMAIN_TYPE_TO_ADAPTER)
        register_resource_adapter(InformationNoteAdapter())
        yield
        _resource_registry._RESOURCE_TYPE_TO_ADAPTER.clear()
        _resource_registry._RESOURCE_TYPE_TO_ADAPTER.update(resource_type_snapshot)
        _resource_registry._DOMAIN_TYPE_TO_ADAPTER.clear()
        _resource_registry._DOMAIN_TYPE_TO_ADAPTER.update(domain_type_snapshot)

    def test_parse_from_dict_via_resource_type(self):
        data = {"resource_type": "information.note", "content": "hello", "format": "markdown"}
        result = parse_resource_from_dict(data)
        assert isinstance(result, InformationResource)
        assert result.content == "hello"
        assert result.format == "markdown"

    def test_parse_from_dict_via_discriminator_key(self):
        data = {"content": "hello", "format": "plaintext"}
        result = parse_resource_from_dict(data)
        assert isinstance(result, InformationResource)
        assert result.content == "hello"

    def test_db_round_trip(self):
        resource = InformationResource(content="meeting notes", format="markdown")
        db_row = adapt_domain_resource_to_db_resource(resource, resource_id="res-3", state="active")
        assert db_row["resource_type"] == "information.note"
        assert db_row["attributes"]["content"] == "meeting notes"

        restored = adapt_db_resource_to_domain_resource(db_row)
        assert isinstance(restored, InformationResource)
        assert restored.content == "meeting notes"
        assert restored.format == "markdown"
