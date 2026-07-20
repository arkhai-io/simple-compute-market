from __future__ import annotations

from compute_provisioning_service.services.release_executors import (
    PHYSICAL_HOST_ID_REF_KEY,
    bare_metal_executor_ref,
    get_physical_host_id,
)


def test_bare_metal_executor_ref_keeps_physical_host_id_separate_from_target():
    ref = bare_metal_executor_ref(
        "host-kvm1",
        access_ref={"ssh_user": "tenant-x"},
    )

    assert ref == {
        PHYSICAL_HOST_ID_REF_KEY: "host-kvm1",
        "ssh_user": "tenant-x",
    }


def test_get_physical_host_id_reads_reserved_executor_ref_key():
    allocation = {
        "executor_kind": "bare_metal",
        "executor_target": "bare-metal-node-7",
        "executor_ref": {
            PHYSICAL_HOST_ID_REF_KEY: "host-kvm1",
        },
    }

    assert get_physical_host_id(allocation) == "host-kvm1"


def test_get_physical_host_id_treats_executor_target_as_executor_local():
    allocation = {
        "executor_kind": "bare_metal",
        "executor_target": "host-kvm1",
        "executor_ref": {},
    }

    assert get_physical_host_id(allocation) is None
