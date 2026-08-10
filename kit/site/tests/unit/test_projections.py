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


# ---------------------------------------------------------------------------
# Pool metadata (label/enabled/mechanism/policy_tags/pool_views)
# ---------------------------------------------------------------------------

def test_pool_metadata_omitted_by_default():
    """No pool_metadata argument reproduces exactly what this function
    returned before pool metadata existed -- no `pool_metadata` key at all."""
    rows = resource_pool_projection(_resources())
    assert "pool_metadata" not in rows[0]


def test_pool_metadata_explicit_none_matches_omitted_default():
    with_default = resource_pool_projection(_resources())
    with_explicit_none = resource_pool_projection(_resources(), pool_metadata=None)
    assert with_default == with_explicit_none


def test_pool_absent_from_directory_has_no_pool_metadata_key():
    """A pool directory covering some but not all pools leaves the
    uncovered pool exactly as if no directory were supplied -- not an
    empty `pool_metadata: {}`, no key at all."""
    resources = _resources()
    resources.append({
        "resource_id": "host-c",
        "pool_id": "pool-2",
        "resource_type": "compute.vm",
        "resource_subtype": "h100",
        "capacity": {"gpu_count": 8},
        "available": {"gpu_count": 8},
        "attributes": {},
        "enabled": True,
    })
    rows = resource_pool_projection(
        resources, pool_metadata={"pool-1": {"label": "Pool One", "enabled": True}},
    )
    by_pool = {row["resource_pool_id"]: row for row in rows}
    assert by_pool["pool-1"]["pool_metadata"] == {"label": "Pool One", "enabled": True}
    assert "pool_metadata" not in by_pool["pool-2"]


def test_pool_metadata_allowlist_drops_unknown_fields():
    """Provider secrets/config must be structurally dropped, not merely
    undocumented -- a field outside the allowlist never reaches the
    projected row even if the caller's directory includes it."""
    rows = resource_pool_projection(
        _resources(),
        pool_metadata={
            "pool-1": {
                "label": "Pool One",
                "enabled": True,
                "mechanism": "ansible",
                "policy_tags": {"region": "eu"},
                "provider_config": {"ssh_key": "top-secret"},
                "extra_vars": {"api_token": "also-secret"},
            },
        },
    )
    meta = rows[0]["pool_metadata"]
    assert set(meta) == {"label", "enabled", "mechanism", "policy_tags"}
    assert "provider_config" not in meta
    assert "extra_vars" not in meta


def test_pool_metadata_policy_tags_and_pool_views_are_copied_not_aliased():
    """The projection must not let a caller mutate cached state through
    the dict it handed in, or through the dict it gets back."""
    policy_tags = {"region": "eu"}
    pool_views = {"vm.ansible_pool_defaults.v1": {"default_vm_ram": 65536}}
    rows = resource_pool_projection(
        _resources(),
        pool_metadata={"pool-1": {"policy_tags": policy_tags, "pool_views": pool_views}},
    )
    meta = rows[0]["pool_metadata"]
    meta["policy_tags"]["region"] = "us"
    meta["pool_views"]["vm.ansible_pool_defaults.v1"]["default_vm_ram"] = 1
    assert policy_tags == {"region": "eu"}
    assert pool_views["vm.ansible_pool_defaults.v1"]["default_vm_ram"] == 65536


def test_pool_metadata_change_advances_digest_with_identical_resources():
    resources = _resources()
    before = canonical_digest(
        resource_pool_projection(resources, pool_metadata={"pool-1": {"enabled": True}}),
    )
    after = canonical_digest(
        resource_pool_projection(resources, pool_metadata={"pool-1": {"enabled": False}}),
    )
    assert after != before


def test_service_pool_directory_is_consulted_once_per_call():
    resources = _resources()
    calls = []

    def pool_directory():
        calls.append(1)
        return {"pool-1": {"label": "Pool One"}}

    service = SiteProjectionService(
        object(),
        resource_inventory=lambda: resources,
        pool_directory=pool_directory,
    )
    _, rows = service.resource_pools()

    assert rows[0]["pool_metadata"] == {"label": "Pool One"}
    assert len(calls) == 1


def test_service_without_pool_directory_omits_pool_metadata():
    service = SiteProjectionService(object(), resource_inventory=lambda: _resources())
    _, rows = service.resource_pools()
    assert "pool_metadata" not in rows[0]
