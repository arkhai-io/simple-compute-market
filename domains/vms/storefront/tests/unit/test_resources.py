"""Unit tests for the resource adapter registry (resources.py)."""

import pytest

from arkhai_vms_listings.models import (
    ComputeResource,
    ERC20TokenMetadata,
    GPUModel,
    Region,
    TokenResource,
)
from arkhai_vms_listings.resources import (
    parse_resource_from_dict,
    register_resource_adapter,
)
from arkhai_vms_listings import resources as _resource_registry

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

    def to_dict(self, resource: InformationResource) -> dict[str, _Any]:
        return {"resource_type": self.resource_type, "content": resource.content, "format": resource.format}


class TestThirdPartyAdapterRegistration:
    @pytest.fixture(autouse=True)
    def _register(self):
        resource_type_snapshot = dict(_resource_registry._RESOURCE_TYPE_TO_ADAPTER)
        register_resource_adapter(InformationNoteAdapter())
        yield
        _resource_registry._RESOURCE_TYPE_TO_ADAPTER.clear()
        _resource_registry._RESOURCE_TYPE_TO_ADAPTER.update(resource_type_snapshot)

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
