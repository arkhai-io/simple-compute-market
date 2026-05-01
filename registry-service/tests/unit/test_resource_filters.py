"""Unit tests for resource filtering functionality."""

import pytest
from src.api.utils import matches_resource_filters
from src.db.models import Listing, OrderStatusEnum


def test_matches_resource_filters_compute(db_session, sample_agent):
    """Test compute resource filtering."""
    order = Listing(
        listing_id="test-order-compute",
        agent_id=sample_agent.agent_id,
        seller="http://localhost:8001/.well-known/agent-card.json",
        offer_resource={"gpu_model": "A100", "region": "us-west"},
        demand_resource={"token": "USDC"},
        max_duration_seconds=12960000,
        status=OrderStatusEnum.open,
    )
    
    assert matches_resource_filters(order, offer_resource_type="compute") is True
    assert matches_resource_filters(order, offer_resource_type="token") is False


def test_matches_resource_filters_region(db_session, sample_agent):
    """Test region filtering."""
    order = Listing(
        listing_id="test-order-region",
        agent_id=sample_agent.agent_id,
        seller="http://localhost:8001/.well-known/agent-card.json",
        offer_resource={"gpu_model": "A100", "region": "us-west"},
        demand_resource={"token": "USDC"},
        max_duration_seconds=12960000,
        status=OrderStatusEnum.open,
    )
    
    assert matches_resource_filters(order, region="us-west") is True
    assert matches_resource_filters(order, region="us-east") is False


def test_matches_resource_filters_bidirectional(db_session, sample_agent):
    """Test bidirectional filtering skips resource type check."""
    order = Listing(
        listing_id="test-order-bidirectional",
        agent_id=sample_agent.agent_id,
        seller="http://localhost:8001/.well-known/agent-card.json",
        offer_resource={"gpu_model": "A100", "region": "us-west"},
        demand_resource={"token": "USDC"},
        max_duration_seconds=12960000,
        status=OrderStatusEnum.open,
    )
    
    # With bidirectional=True, resource type filtering is skipped
    assert matches_resource_filters(order, offer_resource_type="token", bidirectional=True) is True
    assert matches_resource_filters(order, offer_resource_type="token", bidirectional=False) is False


def test_matches_resource_filters_gpu_model(db_session, sample_agent):
    """Test GPU model filtering."""
    order = Listing(
        listing_id="test-order-gpu",
        agent_id=sample_agent.agent_id,
        seller="http://localhost:8001/.well-known/agent-card.json",
        offer_resource={"gpu_model": "A100", "region": "us-west"},
        demand_resource={"token": "USDC"},
        max_duration_seconds=12960000,
        status=OrderStatusEnum.open,
    )
    
    assert matches_resource_filters(order, gpu_model="A100") is True
    assert matches_resource_filters(order, gpu_model="H100") is False


def test_matches_resource_filters_sla(db_session, sample_agent):
    """Test SLA filtering."""
    order = Listing(
        listing_id="test-order-sla",
        agent_id=sample_agent.agent_id,
        seller="http://localhost:8001/.well-known/agent-card.json",
        offer_resource={"gpu_model": "A100", "region": "us-west", "sla": 0.99},
        demand_resource={"token": "USDC"},
        max_duration_seconds=12960000,
        status=OrderStatusEnum.open,
    )

    assert matches_resource_filters(order, sla=0.99) is True
    assert matches_resource_filters(order, sla=0.95) is False


# ---------------------------------------------------------------------------
# New host/slice spec filters
# ---------------------------------------------------------------------------


def _make_listing(sample_agent, **offer_extras):
    """Build a Listing with the given offer fields merged into a stock compute offer."""
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
    return Listing(
        listing_id="test-listing",
        agent_id=sample_agent.agent_id,
        seller="http://localhost:8001/.well-known/agent-card.json",
        offer_resource=offer,
        demand_resource={"token": "USDC"},
        max_duration_seconds=12960000,
        status=OrderStatusEnum.open,
    )


class TestSliceMinFilters:
    def test_gpu_count_min_match(self, db_session, sample_agent):
        order = _make_listing(sample_agent, gpu_count=4)
        assert matches_resource_filters(order, gpu_count_min=2) is True
        assert matches_resource_filters(order, gpu_count_min=4) is True
        assert matches_resource_filters(order, gpu_count_min=8) is False

    def test_vcpu_ram_disk_min(self, db_session, sample_agent):
        order = _make_listing(sample_agent, vcpu_count=32, ram_gb=256, disk_gb=4000)
        assert matches_resource_filters(order, vcpu_count_min=32, ram_gb_min=128, disk_gb_min=4000) is True
        assert matches_resource_filters(order, vcpu_count_min=64) is False
        assert matches_resource_filters(order, ram_gb_min=512) is False
        assert matches_resource_filters(order, disk_gb_min=5000) is False

    def test_unknown_offer_field_rejects_min_filter(self, db_session, sample_agent):
        """If offer doesn't carry a numeric field the buyer asked for, reject."""
        order = _make_listing(sample_agent)
        # Strip the field
        order.offer_resource = {k: v for k, v in order.offer_resource.items() if k != "vcpu_count"}
        assert matches_resource_filters(order, vcpu_count_min=8) is False


class TestHostContextFilters:
    def test_host_cpu_cores_min(self, db_session, sample_agent):
        order = _make_listing(sample_agent, host_cpu_cores=96)
        assert matches_resource_filters(order, host_cpu_cores_min=64) is True
        assert matches_resource_filters(order, host_cpu_cores_min=96) is True
        assert matches_resource_filters(order, host_cpu_cores_min=192) is False

    def test_total_gpu_count_min(self, db_session, sample_agent):
        order = _make_listing(sample_agent, total_gpu_count=8)
        assert matches_resource_filters(order, total_gpu_count_min=4) is True
        assert matches_resource_filters(order, total_gpu_count_min=16) is False

    def test_internet_uplink_min(self, db_session, sample_agent):
        order = _make_listing(sample_agent, internet_upload_mbps=1000)
        assert matches_resource_filters(order, internet_upload_mbps_min=500) is True
        assert matches_resource_filters(order, internet_upload_mbps_min=10000) is False


class TestEqualityFilters:
    def test_cpu_type_exact(self, db_session, sample_agent):
        order = _make_listing(sample_agent, cpu_type="AMD EPYC 9654")
        assert matches_resource_filters(order, cpu_type="AMD EPYC 9654") is True
        assert matches_resource_filters(order, cpu_type="Intel Xeon W5-2465X") is False

    def test_gpu_interconnect_match(self, db_session, sample_agent):
        order = _make_listing(sample_agent, gpu_interconnect="nvswitch")
        assert matches_resource_filters(order, gpu_interconnect="nvswitch") is True
        assert matches_resource_filters(order, gpu_interconnect="pcie_only") is False

    def test_virtualization_type(self, db_session, sample_agent):
        order = _make_listing(sample_agent, virtualization_type="bare_metal")
        assert matches_resource_filters(order, virtualization_type="bare_metal") is True
        assert matches_resource_filters(order, virtualization_type="vm") is False

    def test_datacenter_grade_bool(self, db_session, sample_agent):
        order = _make_listing(sample_agent, datacenter_grade=True)
        assert matches_resource_filters(order, datacenter_grade=True) is True
        assert matches_resource_filters(order, datacenter_grade=False) is False

    def test_combined_filters_all_must_match(self, db_session, sample_agent):
        order = _make_listing(sample_agent, gpu_count=2, host_cpu_cores=192, gpu_interconnect="nvswitch")
        # All three pass
        assert matches_resource_filters(
            order, gpu_count_min=2, host_cpu_cores_min=128, gpu_interconnect="nvswitch"
        ) is True
        # One mismatch fails the whole match
        assert matches_resource_filters(
            order, gpu_count_min=2, host_cpu_cores_min=128, gpu_interconnect="pcie_only"
        ) is False

