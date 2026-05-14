"""Unit tests for matches_listing_filters — the storefront's local listing
filter that mirrors the registry-service's ``matches_resource_filters``.
"""
import pytest

from market_storefront.utils.listing_filters import matches_listing_filters


def _listing(**offer_overrides) -> dict:
    """Build a listing dict with a stock H200 compute offer."""
    offer = {
        "gpu_model": "H200",
        "region": "California, US",
        "sla": 99.0,
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
        **offer_overrides,
    }
    return {"offer_resource": offer}


class TestEqualityFilters:
    def test_no_filters_matches_anything(self):
        assert matches_listing_filters(_listing()) is True

    def test_region_match_and_mismatch(self):
        assert matches_listing_filters(_listing(), region="California, US") is True
        assert matches_listing_filters(_listing(), region="New York, US") is False

    def test_gpu_model_match(self):
        assert matches_listing_filters(_listing(gpu_model="H200"), gpu_model="H200") is True
        assert matches_listing_filters(_listing(gpu_model="H200"), gpu_model="RTX 4090") is False

    def test_sla_exact_match(self):
        assert matches_listing_filters(_listing(sla=99.0), sla=99.0) is True
        assert matches_listing_filters(_listing(sla=99.0), sla=99.5) is False

    def test_cpu_type_exact_match(self):
        assert matches_listing_filters(_listing(cpu_type="AMD EPYC 9654"), cpu_type="AMD EPYC 9654") is True
        assert matches_listing_filters(_listing(cpu_type="AMD EPYC 9654"), cpu_type="Intel Xeon W5") is False

    def test_gpu_interconnect(self):
        assert matches_listing_filters(_listing(gpu_interconnect="nvswitch"), gpu_interconnect="nvswitch") is True
        assert matches_listing_filters(_listing(gpu_interconnect="nvswitch"), gpu_interconnect="pcie_only") is False

    def test_virtualization_type(self):
        assert matches_listing_filters(_listing(virtualization_type="bare_metal"), virtualization_type="bare_metal") is True
        assert matches_listing_filters(_listing(virtualization_type="vm"), virtualization_type="bare_metal") is False

    def test_datacenter_grade_bool(self):
        assert matches_listing_filters(_listing(datacenter_grade=True), datacenter_grade=True) is True
        assert matches_listing_filters(_listing(datacenter_grade=True), datacenter_grade=False) is False

    def test_static_ip_bool(self):
        assert matches_listing_filters(_listing(static_ip=False), static_ip=True) is False
        assert matches_listing_filters(_listing(static_ip=True), static_ip=True) is True


class TestMinFilters:
    def test_gpu_count_min_geq(self):
        listing = _listing(gpu_count=4)
        assert matches_listing_filters(listing, gpu_count_min=2) is True
        assert matches_listing_filters(listing, gpu_count_min=4) is True
        assert matches_listing_filters(listing, gpu_count_min=8) is False

    def test_combined_min_filters(self):
        listing = _listing(vcpu_count=32, ram_gb=256, disk_gb=4000)
        assert matches_listing_filters(
            listing, vcpu_count_min=32, ram_gb_min=128, disk_gb_min=4000,
        ) is True
        assert matches_listing_filters(
            listing, vcpu_count_min=64,
        ) is False

    def test_host_context_min(self):
        listing = _listing(host_cpu_cores=192, host_ram_gb=2048, total_gpu_count=8)
        assert matches_listing_filters(
            listing, host_cpu_cores_min=64, host_ram_gb_min=512, total_gpu_count_min=4,
        ) is True
        assert matches_listing_filters(listing, host_cpu_cores_min=512) is False
        assert matches_listing_filters(listing, host_ram_gb_min=4096) is False
        assert matches_listing_filters(listing, total_gpu_count_min=16) is False

    def test_missing_field_rejects_min_filter(self):
        listing = _listing()
        del listing["offer_resource"]["vcpu_count"]
        assert matches_listing_filters(listing, vcpu_count_min=4) is False

    def test_internet_uplink_min(self):
        listing = _listing(internet_upload_mbps=1000)
        assert matches_listing_filters(listing, internet_upload_mbps_min=500) is True
        assert matches_listing_filters(listing, internet_upload_mbps_min=10000) is False


class TestJsonStringResources:
    def test_offer_resource_as_json_string(self):
        """SQLite stores offer_resource as a JSON string — filter must decode."""
        import json
        listing = {
            "offer_resource": json.dumps({"gpu_model": "H200", "gpu_count": 4}),
        }
        assert matches_listing_filters(listing, gpu_model="H200", gpu_count_min=2) is True
        assert matches_listing_filters(listing, gpu_count_min=8) is False

    def test_malformed_json_treated_as_empty(self):
        listing = {"offer_resource": "not-json-at-all"}
        # Filter still returns True with no constraints; rejects when constraints required.
        assert matches_listing_filters(listing) is True
        assert matches_listing_filters(listing, gpu_model="H200") is False
