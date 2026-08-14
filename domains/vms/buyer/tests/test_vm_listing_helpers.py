from domains.vms.listings import format_resource




def test_format_resource_prioritizes_vm_listing_fields():
    rendered = format_resource({
        "type": "compute",
        "gpu_model": "H200",
        "gpu_count": 2,
        "region": "us-central1",
        "custom": "value",
    })
    assert rendered.splitlines() == [
        "type=compute",
        "gpu_model=H200",
        "gpu_count=2",
        "region=us-central1",
        "custom=value",
    ]
