from __future__ import annotations

from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from arkhai_bare_metal_contracts import (
    PHYSICAL_HOST_ID_REF_KEY,
    BareMetalLeaseCreate,
    bare_metal_executor_ref,
)


def test_bare_metal_lease_create_keeps_machine_and_physical_ids_separate():
    body = BareMetalLeaseCreate(
        allocation_id="alloc-1",
        escrow_uid="0xbm",
        machine_id="bm-node-1",
        physical_host_id="host-physical-1",
        lease_end_utc=datetime(2099, 1, 1, 1, 0, tzinfo=timezone.utc),
    )

    assert body.machine_id == "bm-node-1"
    assert body.physical_host_id == "host-physical-1"


def test_bare_metal_executor_ref_uses_reserved_physical_host_key():
    ref = bare_metal_executor_ref(
        "host-physical-1",
        access_ref={"ssh_user": "tenant-a"},
    )

    assert ref == {
        PHYSICAL_HOST_ID_REF_KEY: "host-physical-1",
        "ssh_user": "tenant-a",
    }


def test_bare_metal_lease_create_rejects_blank_identity_fields():
    with pytest.raises(ValidationError):
        BareMetalLeaseCreate(
            escrow_uid="0xbm",
            machine_id=" ",
            physical_host_id="host-physical-1",
            lease_end_utc=datetime(2099, 1, 1, 1, 0, tzinfo=timezone.utc),
        )
