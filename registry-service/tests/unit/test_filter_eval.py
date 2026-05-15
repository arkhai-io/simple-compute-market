"""Unit tests for the filter evaluator.

Replaces test_resource_filters.py — same semantic coverage (equality
filters, numeric ">=" filters, AND-combination, missing-field rejection)
but driven through the spec-driven ``build_criteria`` + ``evaluate_all``
path rather than the dropped ``matches_resource_filters`` helper.
"""

from __future__ import annotations

import pytest

from src.api.filter_eval import (
    FilterParamError,
    build_criteria,
    evaluate_all,
)
from src.api.filter_spec import get_loaded_spec


@pytest.fixture
def spec():
    return get_loaded_spec()


def _listing(**offer_extras) -> dict:
    """Stock compute listing as the registry returns it from order_to_dict."""
    offer = {
        "gpu_model": "H200",
        "region": "California, US",
        "gpu_count": 4,
        "vcpu_count": 96,
        "ram_gb": 1024,
        "disk_gb": 10000,
        "host_cpu_cores": 192,
        "host_ram_gb": 2048,
        "host_disk_gb": 20000,
        "total_gpu_count": 8,
        "cpu_type": "AMD EPYC 9654",
        "host_disk_type": "Samsung MZTL3T8HEFK",
        "motherboard": "Supermicro H13DSG-O-CPU",
        "gpu_interconnect": "nvswitch",
        "virtualization_type": "vm",
        "static_ip": True,
        "datacenter_grade": True,
        "nic_speed_gbps": 200,
        "internet_download_mbps": 10000,
        "internet_upload_mbps": 10000,
        "open_ports_count": 128,
        **offer_extras,
    }
    return {
        "listing_id": "L1",
        "seller": "",
        "offer_resource": offer,
        "accepted_escrows": [
            {
                "chain_name": "anvil",
                "escrow_address": "0x" + "11" * 20,
                "fields": {"token": "0x" + "ab" * 20},
            }
        ],
        "max_duration_seconds": 12960000,
        "status": "open",
    }


def _match(spec, listing, **params) -> bool:
    """Helper: stringify URL params (FastAPI gives strings), evaluate."""
    stringified = {k: str(v) for k, v in params.items() if v is not None}
    criteria = build_criteria(spec, stringified)
    return evaluate_all(listing, criteria)


# ---------------------------------------------------------------------------
# Equality filters
# ---------------------------------------------------------------------------


class TestEqualityFilters:
    def test_region(self, spec):
        listing = _listing()
        assert _match(spec, listing, region="California, US") is True
        assert _match(spec, listing, region="New York, US") is False

    def test_gpu_model(self, spec):
        listing = _listing(gpu_model="H200")
        assert _match(spec, listing, gpu_model="H200") is True
        assert _match(spec, listing, gpu_model="A100") is False

    def test_cpu_type(self, spec):
        listing = _listing(cpu_type="AMD EPYC 9654")
        assert _match(spec, listing, cpu_type="AMD EPYC 9654") is True
        assert _match(spec, listing, cpu_type="Intel Xeon W5-2465X") is False

    def test_gpu_interconnect(self, spec):
        listing = _listing(gpu_interconnect="nvswitch")
        assert _match(spec, listing, gpu_interconnect="nvswitch") is True
        assert _match(spec, listing, gpu_interconnect="pcie_only") is False

    def test_virtualization_type(self, spec):
        listing = _listing(virtualization_type="bare_metal")
        assert _match(spec, listing, virtualization_type="bare_metal") is True
        assert _match(spec, listing, virtualization_type="vm") is False

    def test_datacenter_grade_bool(self, spec):
        listing_true = _listing(datacenter_grade=True)
        listing_false = _listing(datacenter_grade=False)
        assert _match(spec, listing_true, datacenter_grade="true") is True
        assert _match(spec, listing_true, datacenter_grade="false") is False
        assert _match(spec, listing_false, datacenter_grade="true") is False

    def test_sla_number(self, spec):
        listing = _listing(sla=0.99)
        assert _match(spec, listing, sla="0.99") is True
        assert _match(spec, listing, sla="0.95") is False


# ---------------------------------------------------------------------------
# Numeric ">=" range filters (lower_bound alias_kind)
# ---------------------------------------------------------------------------


class TestRangeFilters:
    def test_gpu_count_min(self, spec):
        listing = _listing(gpu_count=4)
        assert _match(spec, listing, gpu_count_min=2) is True
        assert _match(spec, listing, gpu_count_min=4) is True   # inclusive
        assert _match(spec, listing, gpu_count_min=8) is False

    def test_vcpu_ram_disk(self, spec):
        listing = _listing(vcpu_count=32, ram_gb=256, disk_gb=4000)
        assert _match(spec, listing,
                      vcpu_count_min=32, ram_gb_min=128, disk_gb_min=4000) is True
        assert _match(spec, listing, vcpu_count_min=64) is False
        assert _match(spec, listing, ram_gb_min=512) is False
        assert _match(spec, listing, disk_gb_min=5000) is False

    def test_missing_numeric_field_rejects(self, spec):
        """on_missing=fail in the spec means a missing numeric axis rejects."""
        listing = _listing()
        del listing["offer_resource"]["vcpu_count"]
        assert _match(spec, listing, vcpu_count_min=8) is False

    def test_host_context_filters(self, spec):
        listing = _listing(host_cpu_cores=96, host_ram_gb=512, internet_upload_mbps=1000)
        assert _match(spec, listing, host_cpu_cores_min=64) is True
        assert _match(spec, listing, host_cpu_cores_min=192) is False
        assert _match(spec, listing, host_ram_gb_min=512) is True
        assert _match(spec, listing, internet_upload_mbps_min=10000) is False


# ---------------------------------------------------------------------------
# Array-projection filter — accepted_escrows[*].fields.token
# ---------------------------------------------------------------------------


class TestTokenArrayFilter:
    def test_token_matches_any_advertised(self, spec):
        listing = _listing()
        listing["accepted_escrows"] = [
            {"chain_name": "anvil", "escrow_address": "0xa", "fields": {"token": "USDC"}},
            {"chain_name": "anvil", "escrow_address": "0xb", "fields": {"token": "WETH"}},
        ]
        assert _match(spec, listing, token="USDC") is True
        assert _match(spec, listing, token="WETH") is True
        assert _match(spec, listing, token="DAI") is False

    def test_token_on_missing_pass_doesnt_reject(self, spec):
        """Token filter is underreport-friendly: missing path → criterion passes.

        A seller advertising no escrows shouldn't be invisible to a token
        query (the buyer's policy may still negotiate; the registry just
        doesn't filter them out preemptively).
        """
        listing = _listing()
        listing["accepted_escrows"] = []
        assert _match(spec, listing, token="USDC") is True


# ---------------------------------------------------------------------------
# AND combination + unknown filter rejection
# ---------------------------------------------------------------------------


class TestCombination:
    def test_all_must_match(self, spec):
        listing = _listing(gpu_count=2, host_cpu_cores=192, gpu_interconnect="nvswitch")
        assert _match(spec, listing,
                      gpu_count_min=2, host_cpu_cores_min=128,
                      gpu_interconnect="nvswitch") is True
        assert _match(spec, listing,
                      gpu_count_min=2, host_cpu_cores_min=128,
                      gpu_interconnect="pcie_only") is False

    def test_no_filters_passes_everything(self, spec):
        assert _match(spec, _listing()) is True

    def test_unknown_filter_raises(self, spec):
        with pytest.raises(FilterParamError, match="unknown filter"):
            build_criteria(spec, {"banana": "yellow"})

    def test_non_numeric_value_on_range_raises(self, spec):
        with pytest.raises(FilterParamError, match="expected integer"):
            build_criteria(spec, {"ram_gb_min": "lots"})

    def test_invalid_bool_raises(self, spec):
        with pytest.raises(FilterParamError, match="expected boolean"):
            build_criteria(spec, {"datacenter_grade": "maybe"})
