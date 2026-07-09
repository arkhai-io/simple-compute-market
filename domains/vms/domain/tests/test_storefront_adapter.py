from __future__ import annotations

import pytest

pytest.importorskip("core_storefront.publication_sources")

from arkhai_vms.storefront_adapter import (  # noqa: E402
    vm_candidate_skip_keys,
    vm_listing_resource_key,
    vm_offer_resource_for_listing,
    vm_publication_adapter,
)


def test_vm_candidate_skip_keys_include_current_and_legacy_keys() -> None:
    assert vm_candidate_skip_keys({
        "resource_key": "pool:pool-a:gpus:2",
        "legacy_resource_key": "host-a:gpus:2",
        "resource_id": "host-a",
        "pool_id": "pool-a",
        "gpu_count": 2,
    }) == {
        "pool:pool-a:gpus:2",
        "host-a:gpus:2",
        "host-a",
        "pool-a",
    }


def test_vm_candidate_skip_keys_fallback_to_resource_key() -> None:
    assert vm_candidate_skip_keys({
        "resource_id": "host-a",
        "gpu_count": "1",
    }) == {
        "host-a:gpus:1",
        "host-a",
    }


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

    def offer_resource(candidate: dict) -> dict:
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
        offer_resource=offer_resource,
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
    assert adapter.offer_resource({"gpu_count": 1}) == {"gpu_count": 1}
    assert adapter.skip_keys({"resource_id": "host-a", "gpu_count": 1}) == {
        "host-a:gpus:1",
        "host-a",
    }
    assert adapter.reopen_error_label == "reopen derived listing"
    assert vm_listing_resource_key("host-a", 2) == "host-a:gpus:2"


def test_vm_offer_resource_for_listing_builds_domain_payload() -> None:
    offer = vm_offer_resource_for_listing({
        "pool_id": "pool-a",
        "resource_id": "host-a",
        "gpu_model": "H200",
        "gpu_count": 2,
        "sla": 0.99,
        "region": "California, US",
    })

    assert offer == {
        "pool_id": "pool-a",
        "resource_id": "host-a",
        "gpu_model": "H200",
        "gpu_count": 2,
        "sla": 0.99,
        "region": "California, US",
    }


def test_vm_offer_resource_for_listing_marks_interruptible() -> None:
    offer = vm_offer_resource_for_listing(
        {
            "pool_id": "pool-a",
            "gpu_model": "H200",
            "gpu_count": 2,
            "sla": 0.99,
            "region": "California, US",
        },
        interruptible=True,
    )

    assert offer["interruptible"] is True
    assert offer["settlement_model"] == "splitter_refund"
