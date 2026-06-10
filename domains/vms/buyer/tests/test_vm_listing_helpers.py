from domains.vms.listings import build_vm_filter_params, format_resource


def test_build_vm_filter_params_drops_none_and_serializes_bools():
    assert build_vm_filter_params(
        gpu_model="H200",
        gpu_count_min=2,
        region=None,
        datacenter_grade=True,
        static_ip=False,
    ) == {
        "gpu_model": "H200",
        "gpu_count_min": 2,
        "datacenter_grade": "true",
        "static_ip": "false",
    }


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
