"""A VM scenario's listing shape and claim carry GPUs only when its resource does."""

from __future__ import annotations

from tests.e2e.roles.scenarios.vms.conftest import capacity_source_for
from tests.e2e.roles.scenarios.vms.host_registry import claim_attributes, resource_gpus

SITE = "e2e-site"


def test_a_gpu_less_resource_states_cpu_memory_and_storage_alone():
    source = capacity_source_for(
        {"vcpu_count": 7, "ram_gb": 28, "disk_gb": 160}, site_id=SITE
    )
    assert source["listing_shape"] == {
        "cpu": {"count": 7},
        "memory": {"gib": 28},
        "storage": {"gib": 160},
    }
    assert source["site_id"] == SITE


def test_a_gpu_resource_states_its_gpus_beside_its_other_dimensions():
    source = capacity_source_for(
        {
            "resource_id": "deal-1",
            "gpu_model": "RTX 5080",
            "gpu_count": 1,
            "vcpu_count": 8,
        },
        site_id=SITE,
    )
    assert source == {
        "site_id": SITE,
        "listing_shape": {
            "gpu": {"count": 1, "model": "RTX 5080"},
            "cpu": {"count": 8},
        },
        "resource_id": "deal-1",
    }


def test_several_gpus_are_stated_with_memory_and_storage():
    source = capacity_source_for(
        {"gpu_model": "H200", "gpu_count": 4, "ram_gb": 256, "disk_gb": 1000},
        site_id=SITE,
    )
    assert source["listing_shape"] == {
        "gpu": {"count": 4, "model": "H200"},
        "memory": {"gib": 256},
        "storage": {"gib": 1000},
    }


def test_a_zero_gpu_count_states_no_gpu_family():
    source = capacity_source_for(
        {"gpu_model": "RTX 5080", "gpu_count": 0, "vcpu_count": 4}, site_id=SITE
    )
    assert source["listing_shape"] == {"cpu": {"count": 4}}


def test_a_model_without_a_count_is_no_gpu():
    assert resource_gpus({"gpu_model": "RTX 5080"}) is None
    assert resource_gpus({"gpu_count": 2}) is None
    assert resource_gpus({"gpu_count": 2, "gpu_model": "H200"}) == (2, "H200")


def test_a_claim_requires_a_gpu_count_only_of_a_gpu_shape():
    assert claim_attributes({"vcpu_count": 7}, resource_id="r") == {"resource_id": "r"}
    assert claim_attributes(
        {"gpu_model": "RTX 5080", "gpu_count": 1}, resource_id="r"
    ) == {"resource_id": "r", "gpu_count": 1}
