from __future__ import annotations

import pytest

pytest.importorskip("core_storefront.publication_sources")

from arkhai_vms.storefront_adapter import (  # noqa: E402
    vm_candidate_skip_keys,
    vm_listing_resource_for_listing,
    vm_publication_adapter,
)


def test_vm_candidate_skip_keys_name_the_structural_key_and_source() -> None:
    assert vm_candidate_skip_keys({
        "resource_key": "pool:1:s:6:pool-a:shape:capability-shape.v1:abc",
        "resource_id": "host-a",
        "pool_id": "pool-a",
    }) == {
        "pool:1:s:6:pool-a:shape:capability-shape.v1:abc",
        "host-a",
        "pool-a",
    }


def test_vm_candidate_skip_keys_refuse_a_candidate_without_a_structural_key() -> None:
    # Rebuilding a key from published fields would key a shaped listing as a
    # GPU-count slice it is not.
    with pytest.raises(ValueError, match="structural key"):
        vm_candidate_skip_keys({"resource_id": "host-a", "gpu_count": 1})


_BASE = {"sla": 99.0, "region": "us-east", "offering_mode": "vm", "capacity_backing": "backed"}


def test_a_default_shape_publishes_the_gpu_family_only() -> None:
    listing = vm_listing_resource_for_listing({
        **_BASE,
        "pool_id": "pool-a",
        "listing_shape": {"gpu": {"count": 2, "model": "H100"}},
        # Fields outside the shape are not commitments and are not published.
        "ram_gb": 512,
        "gpu_count": 8,
    })
    assert listing == {
        "pool_id": "pool-a", "gpu_model": "H100", "gpu_count": 2, **_BASE,
    }


def test_a_stated_shape_publishes_every_declared_quantity() -> None:
    listing = vm_listing_resource_for_listing({
        **_BASE,
        "pool_id": "pool-a",
        "resource_id": "host-a",
        "listing_shape": {
            "gpu": {"count": 1, "model": "H100"},
            "cpu": {"count": 8},
            "memory": {"gib": 64},
            "storage": {"gib": 500},
        },
    })
    assert {k: listing[k] for k in ("gpu_count", "vcpu_count", "ram_gb", "disk_gb")} == {
        "gpu_count": 1, "vcpu_count": 8, "ram_gb": 64, "disk_gb": 500,
    }
    assert listing["gpu_model"] == "H100"
    assert listing["resource_id"] == "host-a"


def test_a_candidate_without_a_shape_is_refused() -> None:
    with pytest.raises(ValueError, match="listing shape"):
        vm_listing_resource_for_listing({**_BASE, "pool_id": "p", "gpu_model": "H100", "gpu_count": 1})


def test_vm_publication_adapter_fills_core_publication_source_slots() -> None:
    def open_keys(db_path: str) -> set[str]:
        return {db_path}

    def close_stale(
        db_path: str,
        base_url: str,
        private_key: str | None,
    ) -> list[str]:
        return [db_path, base_url, private_key or ""]

    def available_candidates(db_path: str) -> list[dict]:
        return [{"resource_id": db_path, "gpu_count": 1}]

    def listing_resource(candidate: dict) -> dict:
        return dict(candidate)

    def record_published(
        db_path: str,
        candidate: dict,
        listing_id: str,
    ) -> None:
        assert db_path
        assert candidate
        assert listing_id

    def reopen_existing(*args):
        return {"status": "published", "args": args}

    adapter = vm_publication_adapter(
        open_keys=open_keys,
        close_stale=close_stale,
        available_candidates=available_candidates,
        listing_resource=listing_resource,
        record_published=record_published,
        reopen_existing=reopen_existing,
    )

    assert adapter.name == "vms"
    assert adapter.open_keys("db") == {"db"}
    assert adapter.close_stale("db", "http://storefront", None) == [
        "db",
        "http://storefront",
        "",
    ]
    assert adapter.available_candidates("host-a") == [
        {"resource_id": "host-a", "gpu_count": 1},
    ]
    assert adapter.listing_resource({"gpu_count": 1}) == {"gpu_count": 1}
    assert adapter.pricing_resource(
        {"min_price": "1"},
        {"gpu_count": 1},
    ) == {"min_price": "1"}
    assert adapter.skip_keys({"resource_key": "k", "resource_id": "host-a"}) == {
        "k",
        "host-a",
    }
    assert adapter.reopen_error_label == "reopen derived listing"


def test_vm_listing_resource_for_listing_builds_domain_payload() -> None:
    listing_resource = vm_listing_resource_for_listing({
        "offering_mode": "vm",
        "capacity_backing": "unbacked",
        "pool_id": "pool-a",
        "resource_id": "host-a",
        "listing_shape": {"gpu": {"count": 2, "model": "H200"}},
        "sla": 0.99,
        "region": "California, US",
    })

    assert listing_resource == {
        "offering_mode": "vm",
        "capacity_backing": "unbacked",
        "pool_id": "pool-a",
        "resource_id": "host-a",
        "gpu_model": "H200",
        "gpu_count": 2,
        "sla": 0.99,
        "region": "California, US",
    }


def test_vm_listing_resource_for_listing_marks_interruptible() -> None:
    listing_resource = vm_listing_resource_for_listing(
        {
            "offering_mode": "vm",
            "capacity_backing": "backed",
            "pool_id": "pool-a",
            "listing_shape": {"gpu": {"count": 2, "model": "H200"}},
            "sla": 0.99,
            "region": "California, US",
        },
        interruptible=True,
    )

    assert listing_resource["interruptible"] is True
    assert listing_resource["settlement_model"] == "splitter_refund"


def test_vm_listing_resource_requires_the_candidate_backing() -> None:
    with pytest.raises(KeyError):
        vm_listing_resource_for_listing({
            "offering_mode": "vm",
            "pool_id": "pool-a",
            "listing_shape": {"gpu": {"count": 2, "model": "H200"}},
            "sla": 0.99,
            "region": "California, US",
        })
