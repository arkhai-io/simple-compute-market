"""What a VM deal records of how to reach its VM, and the connect line it gives."""

import pytest
from pydantic import ValidationError

from arkhai_vms import VmConnectionDetails


def test_a_full_record_gives_the_connect_line():
    details = VmConnectionDetails.model_validate_json(
        '{"host": "203.0.113.5", "port": 2222, "user": "tenant1", '
        '"ready_at": "2030-01-01T00:00:01Z", "provisioned_resource_ids": ["res-1"]}'
    )

    assert details.connect == "ssh -p 2222 tenant1@203.0.113.5"


@pytest.mark.parametrize("missing", ["host", "port", "user"])
def test_a_record_missing_a_part_gives_no_connect_line(missing):
    fields = {"host": "203.0.113.5", "port": 2222, "user": "tenant1"}
    del fields[missing]

    assert VmConnectionDetails(**fields).connect is None


def test_nothing_beyond_the_delivery_is_recorded():
    with pytest.raises(ValidationError):
        VmConnectionDetails.model_validate(
            {"host": "203.0.113.5", "port": 22, "user": "t", "vm_name": "guest"}
        )
