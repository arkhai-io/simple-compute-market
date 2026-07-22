from types import SimpleNamespace
from unittest.mock import MagicMock

from compute_provisioning_service.services.capacity_inventory import (
    load_capacity_resource_inventory,
)


def test_load_capacity_resource_inventory_projects_allowlisted_host_fields():
    host = SimpleNamespace(
        name="compute-kvm1-001",
        pool_id="gpu-pool",
        gpu_count=8,
        public_host="203.0.113.10",
        kvm_host="10.0.0.10",
        enabled=True,
    )
    query = MagicMock()
    query.order_by.return_value.all.return_value = [host]
    session = MagicMock()
    session.query.return_value = query
    session.__enter__.return_value = session
    session.__exit__.return_value = False

    result = load_capacity_resource_inventory(lambda: session)

    assert result == [
        {
            "resource_id": "compute-kvm1-001",
            "pool_id": "gpu-pool",
            "resource_type": "compute.gpu",
            "resource_subtype": None,
            "capacity": {"gpu_count": 8},
            "attributes": {
                "vm_host": "compute-kvm1-001",
                "public_host": "203.0.113.10",
                "gpu_count": 8,
            },
            "enabled": True,
        }
    ]
