from market_storefront.services.fulfillment_requests import (
    build_vm_fulfillment_requests,
)


def test_vm_requests_preserve_schedule_shape_and_strict_provider_fields():
    schedule, begin = build_vm_fulfillment_requests(
        capacity_reservation_id="reservation-1",
        order={
            "listing_id": "listing-1",
            "offer_resource": {
                "resource_type": "compute.gpu",
                "resource_id": "resource-1",
                "pool_id": "pool-ignored-for-specific-resource",
                "gpu_model": "H200",
                "region": "us-east",
                "gpu_count": 2,
                "vcpu_count": 8,
                "ram_gb": 32,
                "disk_gb": 100,
            },
        },
        ssh_public_key="ssh-ed25519 AAAA",
        vm_target="vm-1",
    )

    assert schedule.resource_id == "resource-1"
    assert schedule.requirements == {
        "resource_kind": "compute.gpu",
        "dimensions": {
            "gpu_count": 2,
            "vcpu_count": 8,
            "ram_gb": 32,
            "disk_gb": 100,
        },
        "attributes": {"region": "us-east", "gpu_model": "H200"},
    }
    assert begin.fulfillment_request.kind == "vms.fulfillment"
    assert begin.fulfillment_request.payload == {
        "vm_target": "vm-1",
        "image_setup_type": "scratch",
        "vm_ram": 32768,
        "vm_vcpus": 8,
        "vm_disk_size": "100G",
        "ssh_pubkey": "ssh-ed25519 AAAA",
        "gpu_provisioned": True,
        "vm_gpu_count": 2,
    }
