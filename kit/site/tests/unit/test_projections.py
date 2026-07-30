from market_site.projections import (
    ProjectionRevisionTracker,
    SiteProjectionService,
    canonical_digest,
    capacity_bucket_projection,
    resource_pool_projection,
)


def _resources():
    return [
        {
            "resource_id": "host-a",
            "pool_id": "pool-1",
            "resource_type": "compute.vm",
            "resource_subtype": "h100",
            "capacity": {"gpu_count": 8, "ram_gb": 512},
            "available": {"gpu_count": 8, "ram_gb": 512},
            "attributes": {"region": "eu", "vm_host": "host-a"},
            "enabled": True,
        },
        {
            "resource_id": "host-b",
            "pool_id": "pool-1",
            "resource_type": "compute.vm",
            "resource_subtype": "h100",
            "capacity": {"ram_gb": 512, "gpu_count": 8},
            "available": {"ram_gb": 512, "gpu_count": 8},
            "attributes": {"vm_host": "host-b", "region": "eu"},
            "enabled": True,
        },
    ]


def test_canonical_digest_ignores_mapping_order():
    assert canonical_digest([{"b": 2, "a": 1}]) == canonical_digest([{"a": 1, "b": 2}])


def test_resource_pool_projection_preserves_individual_inventory():
    rows = resource_pool_projection(_resources())
    assert rows[0]["resource_pool_id"] == "pool-1"
    assert [r["physical_resource_id"] for r in rows[0]["resources"]] == ["host-a", "host-b"]
    assert rows[0]["resources"][0]["available"] == {
        "gpu_count": 8,
        "ram_gb": 512,
    }


def test_resource_pool_projection_preserves_allowlisted_publication_views():
    resources = _resources()
    resources[0]["publication_views"] = {
        "bare_metal.v1": {
            "physical_resource_id": "host-a",
            "physical_host_id": "physical-host-a",
            "machine_id": "machine-a",
            "available": True,
        },
    }

    rows = resource_pool_projection(resources)

    assert rows[0]["resources"][0]["publication_views"] == {
        "bare_metal.v1": {
            "physical_resource_id": "host-a",
            "physical_host_id": "physical-host-a",
            "machine_id": "machine-a",
            "available": True,
        },
    }


def test_resource_pool_digest_changes_with_publication_availability():
    resources = _resources()
    resources[0]["publication_views"] = {
        "bare_metal.v1": {"available": True},
    }
    before = canonical_digest(resource_pool_projection(resources))
    resources[0]["publication_views"]["bare_metal.v1"]["available"] = False

    after = canonical_digest(resource_pool_projection(resources))

    assert after != before


def test_capacity_projection_vertically_groups_identical_hosts():
    rows = capacity_bucket_projection(_resources())
    assert len(rows) == 1
    assert rows[0]["resource_count"] == 2
    assert rows[0]["available"] == {"gpu_count": 8, "ram_gb": 512}
    assert "physical_resource_ids" not in rows[0]


def test_capacity_projection_regroups_after_reservation():
    resources = _resources()
    resources[1]["available"] = {"gpu_count": 7, "ram_gb": 512}
    rows = capacity_bucket_projection(resources)
    assert sorted(row["resource_count"] for row in rows) == [1, 1]


def test_projection_revisions_are_digest_driven():
    tracker = ProjectionRevisionTracker()
    first = tracker.observe([{"a": 1}])
    same = tracker.observe([{"a": 1}])
    changed = tracker.observe([{"a": 2}])
    assert same == first
    assert changed.revision == first.revision + 1
    assert changed.digest != first.digest


def test_resource_pool_revision_tracks_publication_view_changes():
    resources = _resources()
    resources[0]["publication_views"] = {
        "bare_metal.v1": {"available": True},
    }
    service = SiteProjectionService(
        object(),
        resource_inventory=lambda: resources,
    )
    first, _ = service.resource_pools()
    resources[0]["publication_views"]["bare_metal.v1"]["available"] = False

    changed, _ = service.resource_pools()

    assert changed.revision == first.revision + 1
    assert changed.digest != first.digest
