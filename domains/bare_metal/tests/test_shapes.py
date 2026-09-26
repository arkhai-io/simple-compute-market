"""A bare-metal listing's shape read from its declaration."""

from __future__ import annotations

import pytest

from arkhai_bare_metal import BareMetalShapeError, derive_bare_metal_shape


def test_quantities_other_than_units_and_the_model_form_the_shape():
    shape = derive_bare_metal_shape(
        {"units": 1, "gpu_count": 8, "vcpu_count": 96, "ram_gb": 2048, "disk_gb": 7680},
        {"gpu_model": "H200", "physical_host_id": "p-1", "allocation_mode": "exclusive"},
    )

    assert shape == {
        "cpu": {"count": 96},
        "gpu": {"count": 8, "model": "H200"},
        "memory": {"gib": 2048},
        "storage": {"gib": 7680},
    }


def test_an_integral_number_of_any_numeric_type_is_a_quantity():
    shape = derive_bare_metal_shape({"units": 1.0, "gpu_count": 8.0}, {"gpu_model": "H200"})

    assert shape == {"gpu": {"count": 8, "model": "H200"}}


@pytest.mark.parametrize(
    ("capacity", "attributes", "reason"),
    [
        ({"gpu_count": 8}, {"gpu_model": "H200"}, "capacity.units"),
        ({"units": 0, "gpu_count": 8}, {"gpu_model": "H200"}, "capacity.units"),
        ({"units": True, "gpu_count": 8}, {"gpu_model": "H200"}, "capacity.units"),
        ({"units": 1, "gpu_count": 8, "nic_gbps": 400}, {"gpu_model": "H200"}, "nic_gbps"),
        ({"units": 1, "gpu_count": 8.5}, {"gpu_model": "H200"}, "gpu.count"),
        ({"units": 1}, {"gpu_model": "H200"}, "gpu.count"),
        ({"units": 1, "gpu_count": 8}, {}, "gpu.model"),
        ({"units": 1, "gpu_count": 8}, {"gpu_model": ""}, "gpu.model"),
    ],
)
def test_every_reason_a_declaration_is_not_a_shape_is_named(capacity, attributes, reason):
    with pytest.raises(BareMetalShapeError) as refused:
        derive_bare_metal_shape(capacity, attributes)

    assert any(problem.startswith(reason) for problem in refused.value.problems), (
        refused.value.problems
    )


def test_every_problem_is_reported_not_only_the_first():
    with pytest.raises(BareMetalShapeError) as refused:
        derive_bare_metal_shape({"units": 2, "fpga_count": 1}, {})

    reasons = " ".join(refused.value.problems)
    assert "units" in reasons and "fpga_count" in reasons
