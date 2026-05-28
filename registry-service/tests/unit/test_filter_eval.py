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
        "storefront_url": "",
        "offer_resource": offer,
        "accepted_escrows": [
            {
                "chain_name": "anvil",
                "escrow_address": "0x" + "11" * 20,
                "literal_fields": {"token": "0x" + "ab" * 20},
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
# Array-projection filter — accepted_escrows[*].literal_fields.token
# ---------------------------------------------------------------------------


class TestTokenArrayFilter:
    def test_token_matches_any_advertised(self, spec):
        listing = _listing()
        listing["accepted_escrows"] = [
            {"chain_name": "anvil", "escrow_address": "0xa", "literal_fields": {"token": "USDC"}},
            {"chain_name": "anvil", "escrow_address": "0xb", "literal_fields": {"token": "WETH"}},
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


# ---------------------------------------------------------------------------
# Raw set-form URL syntax (a2)
# ---------------------------------------------------------------------------


class TestSetFormIn:
    """``?<filter>=in:[v1,v2,...]`` — multi-value membership."""

    def test_multi_value_passes_on_any_match(self, spec):
        listing = _listing(gpu_model="H200")
        assert _match(spec, listing, gpu_model="in:[H100,H200,A100]") is True
        assert _match(spec, listing, gpu_model="in:[H100,A100]") is False

    def test_single_value_in_set_form(self, spec):
        listing = _listing(gpu_model="H200")
        assert _match(spec, listing, gpu_model="in:[H200]") is True
        assert _match(spec, listing, gpu_model="in:[A100]") is False

    def test_empty_set_matches_nothing(self, spec):
        listing = _listing()
        assert _match(spec, listing, gpu_model="in:[]") is False

    def test_array_projection_token(self, spec):
        listing = _listing()
        listing["accepted_escrows"] = [
            {"chain_name": "anvil", "escrow_address": "0xa", "literal_fields": {"token": "USDC"}},
            {"chain_name": "anvil", "escrow_address": "0xb", "literal_fields": {"token": "WETH"}},
        ]
        assert _match(spec, listing, token="in:[USDC,DAI]") is True
        assert _match(spec, listing, token="in:[DAI,FRAX]") is False

    def test_whitespace_around_items_stripped(self, spec):
        listing = _listing(gpu_model="H200")
        assert _match(spec, listing, gpu_model="in:[ H100 , H200 , A100 ]") is True

    def test_unbracketed_value_falls_through_to_sugar(self, spec):
        """``?gpu_model=in:foo`` (no brackets) is the literal string ``in:foo``."""
        listing = _listing(gpu_model="in:foo")
        assert _match(spec, listing, gpu_model="in:foo") is True
        assert _match(spec, listing, gpu_model="H200") is False


class TestSetFormNotIn:
    """``?<filter>=not_in:[v1,v2,...]`` — set complement."""

    def test_excluded_value_rejects(self, spec):
        listing = _listing()
        listing["accepted_escrows"] = [
            {"chain_name": "anvil", "escrow_address": "0xa", "literal_fields": {"token": "USDC"}},
        ]
        assert _match(spec, listing, token_exclude="not_in:[USDC]") is False
        assert _match(spec, listing, token_exclude="not_in:[DAI,FRAX]") is True

    def test_not_in_requires_set_form(self, spec):
        """Single-value URL form on a not_in filter raises (ambiguous)."""
        with pytest.raises(FilterParamError, match="must be invoked via set-form"):
            build_criteria(spec, {"token_exclude": "USDC"})

    def test_not_in_with_empty_escrows_passes(self, spec):
        """on_missing: pass — seller with no escrows isn't filtered out."""
        listing = _listing()
        listing["accepted_escrows"] = []
        assert _match(spec, listing, token_exclude="not_in:[USDC]") is True


class TestSetFormRange:
    """``?<filter>=range:[min,max]`` — bounded intervals with bracket/paren."""

    def test_closed_interval(self, spec):
        listing = _listing(ram_gb=64)
        assert _match(spec, listing, ram_gb_min="range:[32,128]") is True
        assert _match(spec, listing, ram_gb_min="range:[128,256]") is False

    def test_inclusive_boundary(self, spec):
        listing = _listing(ram_gb=64)
        assert _match(spec, listing, ram_gb_min="range:[64,128]") is True

    def test_exclusive_boundary(self, spec):
        listing = _listing(ram_gb=64)
        # (64,128] — strictly > 64, so 64 fails
        assert _match(spec, listing, ram_gb_min="range:(64,128]") is False
        # [16,64) — strictly < 64, so 64 fails
        assert _match(spec, listing, ram_gb_min="range:[16,64)") is False
        # [16,64] — inclusive, 64 passes
        assert _match(spec, listing, ram_gb_min="range:[16,64]") is True

    def test_open_upper(self, spec):
        listing = _listing(ram_gb=1024)
        assert _match(spec, listing, ram_gb_min="range:[16,)") is True
        assert _match(spec, listing, ram_gb_min="range:[2048,)") is False

    def test_open_lower(self, spec):
        listing = _listing(ram_gb=64)
        assert _match(spec, listing, ram_gb_min="range:(,128]") is True
        assert _match(spec, listing, ram_gb_min="range:(,32]") is False

    def test_set_form_overrides_alias_kind(self, spec):
        """A ``lower_bound``-aliased filter still accepts full range:[a,b]."""
        listing = _listing(ram_gb=64)
        assert _match(spec, listing, ram_gb_min="range:[32,128]") is True
        assert _match(spec, listing, ram_gb_min="range:[100,200]") is False

    def test_unbounded_both_sides_raises(self, spec):
        with pytest.raises(FilterParamError, match="needs at least one bound"):
            build_criteria(spec, {"ram_gb_min": "range:(,)"})

    def test_missing_comma_raises(self, spec):
        with pytest.raises(FilterParamError, match="needs a ',' separator"):
            build_criteria(spec, {"ram_gb_min": "range:[64]"})


class TestSetFormExists:
    """``?<filter>=exists:true|false`` — presence test."""

    def test_exists_true_matches_when_present(self, spec):
        listing = _listing()
        listing["oracle_address"] = "0x" + "22" * 20
        assert _match(spec, listing, has_oracle="exists:true") is True

    def test_exists_true_rejects_when_absent(self, spec):
        listing = _listing()
        listing.pop("oracle_address", None)
        # on_missing: fail by default → no path → criterion fails
        assert _match(spec, listing, has_oracle="exists:true") is False

    def test_exists_false_matches_when_absent(self, spec):
        """exists:false + on_missing override is the cleanest way to ask
        'show me listings WITHOUT an oracle' since on_missing=fail
        otherwise rejects them first."""
        listing = _listing()
        listing.pop("oracle_address", None)
        # Without strict override, on_missing=fail rejects before we get
        # to evaluate the exists target.
        assert _match(spec, listing, has_oracle="exists:false") is False
        # With strict.has_oracle=false (override on_missing → pass),
        # the criterion ignores the missing path entirely.
        assert _match(
            spec, listing,
            **{"has_oracle": "exists:false", "strict.has_oracle": "false"},
        ) is True

    def test_exists_unbracketed_payload_falls_through_to_sugar(self, spec):
        """``?has_oracle=exists:maybe`` is not a valid exists payload."""
        # exists isn't in the URL-sugar table either, so this raises.
        with pytest.raises(FilterParamError, match="must be invoked via set-form"):
            build_criteria(spec, {"has_oracle": "exists:maybe"})


# ---------------------------------------------------------------------------
# Per-query strict.* override (a2)
# ---------------------------------------------------------------------------


class TestStrictOverride:
    """``?strict.<filter>=true|false`` flips spec-level on_missing per request."""

    def test_strict_true_tightens_token_filter(self, spec):
        """token defaults to on_missing: pass; strict tightens to fail."""
        listing = _listing()
        listing["accepted_escrows"] = []
        # Default behavior: empty escrows passes the token criterion.
        assert _match(spec, listing, token="USDC") is True
        # Strict: empty escrows fails.
        assert _match(spec, listing, **{"token": "USDC", "strict.token": "true"}) is False

    def test_strict_false_loosens_gpu_model(self, spec):
        """gpu_model defaults to on_missing: fail; strict=false loosens."""
        listing = _listing()
        del listing["offer_resource"]["gpu_model"]
        assert _match(spec, listing, gpu_model="H200") is False
        assert _match(
            spec, listing,
            **{"gpu_model": "H200", "strict.gpu_model": "false"},
        ) is True

    def test_strict_unknown_filter_raises(self, spec):
        with pytest.raises(FilterParamError, match="strict.banana: unknown filter"):
            build_criteria(spec, {"strict.banana": "true"})

    def test_strict_empty_target_raises(self, spec):
        with pytest.raises(FilterParamError, match="missing filter name"):
            build_criteria(spec, {"strict.": "true"})

    def test_strict_invalid_bool_raises(self, spec):
        with pytest.raises(FilterParamError, match="expected boolean"):
            build_criteria(spec, {"strict.token": "maybe"})

    def test_strict_without_filter_use_is_a_noop(self, spec):
        """Specifying strict.X but no ?X=... is allowed — the override
        just doesn't end up in any criterion. (Typo of an unrelated
        existing filter name; caller's bug, not our problem.)"""
        listing = _listing()
        assert _match(spec, listing, **{"strict.gpu_model": "true"}) is True


# ---------------------------------------------------------------------------
# Op-mismatch and structural guards
# ---------------------------------------------------------------------------


class TestSetFormOpMismatch:
    def test_in_filter_rejects_not_in_set_form(self, spec):
        """gpu_model declares op: in — not_in:[...] must be rejected."""
        with pytest.raises(FilterParamError, match="declares op='in'"):
            build_criteria(spec, {"gpu_model": "not_in:[H100]"})

    def test_range_filter_rejects_exists_set_form(self, spec):
        with pytest.raises(FilterParamError, match="declares op='range'"):
            build_criteria(spec, {"ram_gb_min": "exists:true"})


# ---------------------------------------------------------------------------
# Coexistence — set-form and URL-sugar on the same request
# ---------------------------------------------------------------------------


class TestMixedForms:
    def test_set_form_and_sugar_both_applied(self, spec):
        """One query, one criterion in each form — both ANDed together."""
        listing = _listing(gpu_model="H200", ram_gb=64)
        assert _match(spec, listing,
                      gpu_model="in:[H200,A100]", ram_gb_min=32) is True
        assert _match(spec, listing,
                      gpu_model="in:[A100]", ram_gb_min=32) is False
        assert _match(spec, listing,
                      gpu_model="in:[H200,A100]", ram_gb_min=128) is False
