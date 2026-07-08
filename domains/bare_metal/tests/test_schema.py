from __future__ import annotations

from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from arkhai_bare_metal import (
    BARE_METAL_ACCESS_ACTIONS,
    BARE_METAL_SCHEMA_KIND,
    NODE_GRANT_ACCESS_ACTION,
    NODE_RECLAIM_ACCESS_ACTION,
    PHYSICAL_HOST_ID_REF_KEY,
    SSH_ACCESS_METHOD,
    BareMetalAccessResult,
    BareMetalLeaseCreate,
    BareMetalListing,
    BareMetalMessage,
    BareMetalTerms,
    bare_metal_executor_ref,
)


def test_bare_metal_listing_is_domain_payload_not_registry_row():
    listing = BareMetalListing(
        machine_id="bm-node-1",
        physical_host_id="host-physical-1",
        min_duration_seconds=3600,
        max_duration_seconds=7200,
        site={"region": "us-west"},
        capabilities={"gpu_model": "L40S", "ram_gb": 256},
    )

    assert listing.kind == BARE_METAL_SCHEMA_KIND
    assert listing.machine_id == "bm-node-1"
    assert listing.physical_host_id == "host-physical-1"
    assert listing.access_methods == [SSH_ACCESS_METHOD]
    assert "publisher" not in listing.model_dump()
    assert "storefront_url" not in listing.model_dump()


def test_bare_metal_listing_keeps_machine_and_physical_ids_separate():
    listing = BareMetalListing(
        machine_id="executor-local-node",
        physical_host_id="site-physical-host",
    )

    assert listing.machine_id != listing.physical_host_id


def test_bare_metal_listing_rejects_invalid_duration_bounds():
    with pytest.raises(ValidationError):
        BareMetalListing(
            machine_id="bm-node-1",
            physical_host_id="host-physical-1",
            min_duration_seconds=7200,
            max_duration_seconds=3600,
        )


def test_bare_metal_message_requires_access_material_for_ssh():
    with pytest.raises(ValidationError):
        BareMetalMessage(duration_seconds=3600)


def test_bare_metal_message_accepts_ssh_public_key():
    message = BareMetalMessage(
        duration_seconds=3600,
        ssh_public_key="ssh-ed25519 AAAA buyer",
    )

    assert message.kind == BARE_METAL_SCHEMA_KIND
    assert message.access_method == SSH_ACCESS_METHOD
    assert message.ssh_public_key == "ssh-ed25519 AAAA buyer"


def test_bare_metal_terms_are_canonical_negotiation_handoff():
    terms = BareMetalTerms(
        machine_id="bm-node-1",
        physical_host_id="host-physical-1",
        duration_seconds=3600,
        ssh_public_key="ssh-ed25519 AAAA buyer",
        listing_ref="listing-1",
    )

    assert terms.kind == BARE_METAL_SCHEMA_KIND
    assert terms.duration_seconds == 3600
    assert terms.listing_ref == "listing-1"
    assert "executor_action" not in terms.model_dump()
    assert "playbook" not in terms.model_dump()


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


def test_bare_metal_access_actions_are_domain_owned():
    assert BARE_METAL_ACCESS_ACTIONS == (
        NODE_GRANT_ACCESS_ACTION,
        NODE_RECLAIM_ACCESS_ACTION,
    )


def test_bare_metal_access_result_accepts_contract_action():
    result = BareMetalAccessResult(
        action=NODE_GRANT_ACCESS_ACTION,
        machine_id="bm-node-1",
        physical_host_id="host-physical-1",
        ssh_user="tenant-a",
        escrow_uid="0xbm",
    )

    assert result.action == NODE_GRANT_ACCESS_ACTION
    assert result.machine_id == "bm-node-1"
    assert result.status == "success"


def test_bare_metal_access_result_rejects_unknown_action():
    with pytest.raises(ValidationError):
        BareMetalAccessResult(
            action="delete_everything",
            machine_id="bm-node-1",
        )
