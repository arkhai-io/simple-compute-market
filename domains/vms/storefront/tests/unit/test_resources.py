"""Unit tests for VM listing resource dispatch and serialization.

The adapter registry (resources.py), the models' own parser, the compute test
in pricing.py, and the buyer CLI's display all decide a payload's kind; these
tests hold them to one rule.
"""

import pytest
from pydantic import ValidationError

from arkhai_vms_listings.buyer_cli import format_resource
from arkhai_vms_listings.listing_comparison import UNCHANGED, compare_listing
from arkhai_vms_listings.models import (
    ComputeDomainResource,
    ComputeResource,
    ERC20TokenMetadata,
    GPUModel,
    Region,
    TokenResource,
    payload_resource_type,
)
from arkhai_vms_listings.pricing import extract_compute_from_order, resource_is_compute
from arkhai_vms_listings.resources import (
    ComputeGpuResourceAdapter,
    parse_resource_from_dict,
    register_resource_adapter,
)
from arkhai_vms_listings import resources as _resource_registry
from market_resource_pools_contracts.backing import capacity_backing

BACKED = capacity_backing("backed")

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

    def test_a_stored_gpu_listing_naming_no_resource_type_is_compute(self):
        data = {"gpu_model": "H200", "gpu_count": 1, "sla": 90.0, "region": "California, US"}
        result = parse_resource_from_dict(data)
        assert isinstance(result, ComputeResource)
        assert (result.gpu_count, result.gpu_model) == (1, "H200")

    def test_a_compute_mapping_without_gpus_is_compute(self):
        data = {"vcpu_count": 8, "ram_gb": 32, "sla": 90.0, "region": "California, US"}
        result = parse_resource_from_dict(data)
        assert isinstance(result, ComputeResource)
        assert (result.gpu_count, result.gpu_model) == (None, None)
        assert (result.vcpu_count, result.ram_gb) == (8, 32)

    def test_a_compute_mapping_stating_no_quantity_is_refused_by_compute_validation(self):
        with pytest.raises(ValidationError, match="a shape must name at least one family"):
            parse_resource_from_dict({"sla": 90.0, "region": "California, US"})

    @pytest.mark.parametrize(
        ("resource", "reason"),
        [
            ({"gpu_model": "H200", "vcpu_count": 8}, "gpu.count: is required"),
            ({"gpu_count": 2, "vcpu_count": 8}, "gpu.model: is required"),
        ],
        ids=["model-alone", "count-alone"],
    )
    def test_one_gpu_field_without_the_other_is_refused(self, resource, reason):
        with pytest.raises(ValidationError, match=reason):
            parse_resource_from_dict({**resource, "sla": 90.0, "region": "California, US"})

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

    def test_an_explicit_resource_type_decides_over_the_payload_keys(self):
        """A compute type selects compute even beside a ``token`` key."""
        data = {
            "resource_type": "compute.gpu",
            "token": "0xdac17f958d2ee523a2206206994597c13d831ec7",
            "vcpu_count": 8,
            "sla": 90.0,
            "region": "California, US",
        }
        assert isinstance(parse_resource_from_dict(data), ComputeResource)


# ---------------------------------------------------------------------------
# One dispatch rule at every seam
# ---------------------------------------------------------------------------

_GPU_LESS = {"vcpu_count": 8, "ram_gb": 32, "sla": 90.0, "region": "California, US"}
_STORED_GPU = {"gpu_model": "H200", "gpu_count": 1, "sla": 90.0, "region": "California, US"}
_TOKEN = {
    "token": {"symbol": "USDT", "contract_address": USDT.contract_address, "decimals": 6},
    "amount": 1_000_000,
}
_EXPLICIT_COMPUTE = {"resource_type": "compute.gpu", **_TOKEN, **_GPU_LESS}


@pytest.mark.parametrize(
    ("payload", "resource_type", "domain_type"),
    [
        (_GPU_LESS, "compute.gpu", ComputeResource),
        (_STORED_GPU, "compute.gpu", ComputeResource),
        (_TOKEN, "token.erc20", TokenResource),
        (_EXPLICIT_COMPUTE, "compute.gpu", ComputeResource),
    ],
    ids=["gpu-less", "stored-gpu", "token", "explicit-type"],
)
def test_every_seam_dispatches_a_payload_alike(payload, resource_type, domain_type):
    assert payload_resource_type(payload) == resource_type
    assert isinstance(parse_resource_from_dict(dict(payload)), domain_type)
    assert isinstance(ComputeDomainResource.parse_from_dict(dict(payload)), domain_type)
    assert resource_is_compute(payload) is (domain_type is ComputeResource)
    rendered = format_resource(dict(payload))
    if domain_type is ComputeResource:
        assert "region=California, US" in rendered.splitlines()
    else:
        assert rendered.splitlines()[0] == "symbol=USDT"


def test_a_parsed_resource_is_compute_by_its_type():
    assert resource_is_compute(parse_resource_from_dict(dict(_GPU_LESS))) is True
    assert resource_is_compute(TOKEN) is False


def test_an_empty_mapping_is_not_compute():
    assert resource_is_compute({}) is False
    with pytest.raises(ValueError, match="not compute"):
        extract_compute_from_order({"listing_id": "lst-1"})


def test_a_payload_naming_the_token_type_renders_as_a_token():
    assert format_resource({"resource_type": "token.erc20", "amount": 5}) == "amount=5"


# ---------------------------------------------------------------------------
# Serialization
# ---------------------------------------------------------------------------


def test_a_resource_without_gpus_serializes_no_gpu_key():
    resource = parse_resource_from_dict(dict(_GPU_LESS))

    for dumped in (resource.model_dump(), resource.model_dump(mode="json")):
        assert "gpu_count" not in dumped
        assert "gpu_model" not in dumped
        assert (dumped["vcpu_count"], dumped["ram_gb"]) == (8, 32)
    network = ComputeGpuResourceAdapter().to_dict(resource)
    assert "gpu_count" not in network
    assert "gpu_model" not in network


def test_a_gpu_resource_serializes_both_gpu_fields():
    dumped = parse_resource_from_dict(dict(_STORED_GPU)).model_dump(mode="json")

    assert (dumped["gpu_count"], dumped["gpu_model"]) == (1, "H200")
    assert "asking_rate" not in dumped


def test_a_stored_null_gpu_field_and_a_missing_one_compare_equal():
    stored_with_null = {
        **_GPU_LESS,
        "pool_id": "pool-a",
        "gpu_model": None,
        "gpu_count": None,
        "capacity_backing": "backed",
    }
    fresh = parse_resource_from_dict({**_GPU_LESS, "pool_id": "pool-a"}).model_dump(
        mode="json"
    )
    fresh["capacity_backing"] = "backed"

    comparison = compare_listing(
        stored_resource=stored_with_null,
        stored_terms={},
        fresh_resource=fresh,
        fresh_terms={},
        binding_backing=BACKED,
        source_backing=BACKED,
    )

    assert comparison.outcome == UNCHANGED


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
