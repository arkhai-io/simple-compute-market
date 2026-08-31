"""Authenticated v2 contracts for both site-capacity clients."""

from __future__ import annotations
import time

import httpx
import pytest
from market_identity import (
    Ed25519Signer,
    Eip191Signer,
    Signer,
    TrustedIdentitySet,
    VerificationCode,
)

from fake_site import FakeSite
from market_site_client import (
    SiteCapacityAdminClient,
    SiteCapacityAdminClientError,
    SiteCapacityAuthenticationError,
    SiteCapacityClient,
    SiteCapacityClientError,
)


@pytest.fixture(params=("ed25519", "eip191"))
def signer_pair(request: pytest.FixtureRequest) -> tuple[Signer, Signer]:
    if request.param == "ed25519":
        return Ed25519Signer(b"\x11" * 32), Ed25519Signer(b"\x22" * 32)
    return Eip191Signer(b"\x11" * 32), Eip191Signer(b"\x22" * 32)


@pytest.fixture
def site(signer_pair: tuple[Signer, Signer]) -> FakeSite:
    caller, authority = signer_pair
    fake = FakeSite(
        caller=caller,
        authority=authority,
        deliverable_modes={"vm"},
    )
    fake.add_resource(
        "compute-kvm1-001",
        8,
        attributes={"vm_host": "kvm1", "gpu_model": "H200"},
    )
    return fake


@pytest.fixture
def capacity_client(
    site: FakeSite, signer_pair: tuple[Signer, Signer]
) -> SiteCapacityClient:
    caller, authority = signer_pair
    return SiteCapacityClient(
        "http://site-authority:8081",
        caller,
        TrustedIdentitySet(identities=(authority.identity,)),
        transport=site.transport(),
    )


@pytest.fixture
def admin_client(
    site: FakeSite, signer_pair: tuple[Signer, Signer]
) -> SiteCapacityAdminClient:
    caller, authority = signer_pair
    return SiteCapacityAdminClient(
        "http://site-authority:8081",
        caller,
        TrustedIdentitySet(identities=(authority.identity,)),
        transport=site.transport(),
    )


@pytest.mark.asyncio
async def test_every_public_async_method_uses_the_exact_route_contract(
    capacity_client: SiteCapacityClient,
    admin_client: SiteCapacityAdminClient,
    site: FakeSite,
) -> None:
    registered = await admin_client.register_resource(
        "resource-new",
        total_units=4,
        pool_id="pool-a",
        request_id="resource-put",
    )
    assert registered["resource_id"] == "resource-new"
    assert {row["resource_id"] for row in await admin_client.list_resources()} == {
        "compute-kvm1-001",
        "resource-new",
    }

    assert (await capacity_client.snapshot())[0]["available_units"] == 8
    assert (await capacity_client.resource_pool_projection_version())["revision"] == 1
    assert (await capacity_client.resource_pool_projection())["resource_pools"] == []
    assert (await capacity_client.capacity_bucket_projection_version())["revision"] == 1
    assert (await capacity_client.capacity_bucket_projection())["capacity_buckets"] == []
    assert await capacity_client.probe(
        claim={"executor_kind": "vm", "gpu_model": "A100"}
    ) is None
    assert (
        await capacity_client.probe(
            claim={"executor_kind": "vm", "gpu_model": "H200"}
        )
    )["vm_host"] == "kvm1"

    reserved = await capacity_client.reserve(
        claim={"executor_kind": "vm", "gpu_count": 3},
        deal_ref={"escrow_uid": "0xesc"},
        request_id="reserve",
    )
    assert reserved is not None
    reservation_id = reserved["capacity_reservation_id"]
    assert "resource_id" not in reserved
    await capacity_client.commit(
        capacity_reservation_id=reservation_id,
        idempotency_ref="0xesc",
        request_id="commit",
    )
    assert (await capacity_client.get_reservation(reservation_id))["state"] == "leased"
    assert [
        row["capacity_reservation_id"]
        for row in await capacity_client.list_reservations(escrow_uid="0xesc")
    ] == [reservation_id]
    truncated = await capacity_client.truncate_lease(
        capacity_reservation_id=reservation_id,
        lease_end_utc="2026-06-01 00:00",
        request_id="truncate",
    )
    assert truncated is not None
    assert truncated["lease_end_utc"] == "2026-06-01 00:00"
    released = await capacity_client.release(
        deal_ref={"escrow_uid": "0xesc"},
        failure_reason="provisioning_failed",
        request_id="release",
    )
    assert released is not None
    assert released["state"] == "released"
    events, latest = await capacity_client.events_after(0, request_id="events")
    assert latest == events[-1]["version"]

    assert [seen["operation"] for seen in site.seen_requests] == [
        "capacity_resource_put",
        "capacity_resources_list",
        "capacity_snapshot",
        "capacity_resource_pools_version",
        "capacity_resource_pools_get",
        "capacity_buckets_version",
        "capacity_buckets_get",
        "capacity_probe",
        "capacity_probe",
        "capacity_reserve",
        "capacity_commit",
        "capacity_reservation_get",
        "capacity_reservations_list",
        "capacity_truncate_lease",
        "capacity_release",
        "capacity_events",
    ]
    assert all(
        seen["verification"] == VerificationCode.VERIFIED
        for seen in site.seen_requests
    )
    assert next(
        seen for seen in site.seen_requests if seen["operation"] == "capacity_commit"
    )["body"] == {"idempotency_ref": "0xesc"}
    assert next(
        seen
        for seen in site.seen_requests
        if seen["operation"] == "capacity_reservations_list"
    )["body"] == {"escrow_uid": "0xesc"}
    assert site.seen_requests[-1]["body"] == {"after": 0, "limit": 500}


@pytest.mark.asyncio
async def test_resource_registration_body_uses_json_defaults_and_omits_none(
    admin_client: SiteCapacityAdminClient, site: FakeSite
) -> None:
    await admin_client.register_resource(
        "r1", total_units=1, request_id="registration-defaults"
    )
    assert site.seen_requests[-1]["resource"] == "r1"
    assert site.seen_requests[-1]["body"] == {
        "total_units": 1,
        "resource_type": "compute.gpu",
        "attributes": {},
        "enabled": True,
    }


@pytest.mark.asyncio
async def test_later_exact_retry_refreshes_signature_without_redispatch(
    capacity_client: SiteCapacityClient,
    site: FakeSite,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clock = [int(time.time())]
    monkeypatch.setattr("market_site_client.client.time.time", lambda: clock[0])
    first = await capacity_client.reserve(
        claim={"executor_kind": "vm", "gpu_count": 1},
        deal_ref={"escrow_uid": "exact"},
        request_id="stable-request",
    )
    dispatches = site.dispatch_count
    clock[0] += 1
    second = await capacity_client.reserve(
        claim={"executor_kind": "vm", "gpu_count": 1},
        deal_ref={"escrow_uid": "exact"},
        request_id="stable-request",
    )

    assert second == first
    assert site.dispatch_count == dispatches
    assert site.seen_requests[-1]["verification"] == VerificationCode.EXACT_RETRY
    assert site.seen_requests[-1]["timestamp"] > site.seen_requests[-2]["timestamp"]
    assert site.seen_requests[-1]["signature"] != site.seen_requests[-2]["signature"]


@pytest.mark.asyncio
async def test_changed_local_request_id_reuse_fails_before_transport(
    capacity_client: SiteCapacityClient, site: FakeSite
) -> None:
    await capacity_client.probe(
        claim={"executor_kind": "vm", "gpu_count": 1},
        request_id="fixed",
    )
    sent = len(site.seen_requests)

    with pytest.raises(ValueError, match="changed request content"):
        await capacity_client.probe(
            claim={"executor_kind": "vm", "gpu_count": 2},
            request_id="fixed",
        )

    assert len(site.seen_requests) == sent


@pytest.mark.asyncio
async def test_changed_reuse_from_an_independent_client_gets_verified_conflict(
    site: FakeSite, signer_pair: tuple[Signer, Signer]
) -> None:
    caller, authority = signer_pair
    first = SiteCapacityClient(
        "http://site-authority:8081",
        caller,
        TrustedIdentitySet(identities=(authority.identity,)),
        transport=site.transport(),
    )
    second = SiteCapacityClient(
        "http://site-authority:8081",
        caller,
        TrustedIdentitySet(identities=(authority.identity,)),
        transport=site.transport(),
    )
    await first.probe(
        claim={"executor_kind": "vm", "gpu_count": 1},
        request_id="shared",
    )

    with pytest.raises(SiteCapacityClientError) as excinfo:
        await second.probe(
            claim={"executor_kind": "vm", "gpu_count": 2},
            request_id="shared",
        )

    assert excinfo.value.status_code == 409
    assert site.seen_requests[-1]["verification"] == VerificationCode.CHANGED_REUSE


@pytest.mark.asyncio
async def test_request_body_mutation_is_rejected_but_signed_error_is_accepted(
    capacity_client: SiteCapacityClient, site: FakeSite
) -> None:
    site.mutate_next_request_body = True
    with pytest.raises(SiteCapacityClientError) as excinfo:
        await capacity_client.reserve(
            claim={"executor_kind": "vm", "gpu_count": 1},
            request_id="mutated-request",
        )

    assert excinfo.value.status_code == 403
    assert "body_hash_mismatch" in str(excinfo.value)
    assert site.seen_requests[-1]["verification"] == VerificationCode.BODY_HASH_MISMATCH

@pytest.mark.asyncio
async def test_response_body_mutation_is_rejected(
    capacity_client: SiteCapacityClient, site: FakeSite
) -> None:
    site.mutate_next_response_body = True
    with pytest.raises(SiteCapacityAuthenticationError, match="invalid_proof"):
        await capacity_client.snapshot(request_id="mutated-response")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("failure", "expected"),
    (
        ("wrong_role", "context_mismatch"),
        ("wrong_request_id", "context_mismatch"),
        ("wrong_operation", "invalid_proof"),
        ("wrong_resource", "invalid_proof"),
    ),
)
async def test_mismatched_response_acknowledgements_are_rejected(
    capacity_client: SiteCapacityClient,
    site: FakeSite,
    failure: str,
    expected: str,
) -> None:
    if failure == "wrong_role":
        site.response_role = "seller"
    elif failure == "wrong_request_id":
        site.response_request_id = "different"
    elif failure == "wrong_operation":
        site.response_operation = "capacity_probe"
    else:
        site.response_resource = "different"

    with pytest.raises(SiteCapacityAuthenticationError, match=expected):
        await capacity_client.snapshot(request_id=f"ack-{failure}")


@pytest.mark.asyncio
async def test_wrong_authority_principal_is_rejected(
    site: FakeSite, signer_pair: tuple[Signer, Signer]
) -> None:
    caller, _ = signer_pair
    unexpected = Ed25519Signer(b"\x33" * 32)
    client = SiteCapacityClient(
        "http://site-authority:8081",
        caller,
        TrustedIdentitySet(identities=(unexpected.identity,)),
        transport=site.transport(),
    )
    with pytest.raises(SiteCapacityAuthenticationError, match="wrong_principal"):
        await client.snapshot(request_id="wrong-authority")


@pytest.mark.asyncio
async def test_authority_rotation_overlap_then_retired_identity_removal(
    site: FakeSite, signer_pair: tuple[Signer, Signer]
) -> None:
    caller, old_authority = signer_pair
    new_authority: Signer
    if old_authority.identity.scheme.value == "ed25519":
        new_authority = Eip191Signer(b"\x33" * 32)
    else:
        new_authority = Ed25519Signer(b"\x33" * 32)

    overlap = SiteCapacityClient(
        "http://site-authority:8081",
        caller,
        TrustedIdentitySet(
            identities=(old_authority.identity, new_authority.identity)
        ),
        transport=site.transport(),
    )
    await overlap.snapshot(request_id="rotation-old")
    site.authority = new_authority
    await overlap.snapshot(request_id="rotation-new")

    retired = SiteCapacityClient(
        "http://site-authority:8081",
        caller,
        TrustedIdentitySet(identities=(new_authority.identity,)),
        transport=site.transport(),
    )
    site.authority = old_authority
    with pytest.raises(SiteCapacityAuthenticationError, match="wrong_principal"):
        await retired.snapshot(request_id="retired-old")
    site.authority = new_authority
    await retired.snapshot(request_id="retired-new")


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ("missing", "unknown"))
async def test_missing_or_unknown_response_protocol_is_rejected(
    capacity_client: SiteCapacityClient, site: FakeSite, failure: str
) -> None:
    if failure == "missing":
        site.omit_response_authentication = True
    else:
        site.response_protocol = "arkhai.market-response.v1"

    with pytest.raises(SiteCapacityAuthenticationError, match="missing or malformed"):
        await capacity_client.snapshot(request_id=f"protocol-{failure}")


@pytest.mark.asyncio
async def test_ed25519_client_construction_needs_no_wallet_or_chain_configuration() -> None:
    caller = Ed25519Signer(b"\x44" * 32)
    authority = Ed25519Signer(b"\x55" * 32)
    site = FakeSite(
        caller=caller,
        authority=authority,
        deliverable_modes={"vm"},
    )
    site.add_resource("ed-resource", 1)
    client = SiteCapacityClient(
        "http://site-authority:8081",
        caller,
        TrustedIdentitySet(identities=(authority.identity,)),
        transport=site.transport(),
    )

    assert (await client.snapshot(request_id="ed25519-no-wallet"))[0][
        "resource_id"
    ] == "ed-resource"


@pytest.mark.asyncio
async def test_admin_transport_failure_keeps_the_typed_error_contract(
    signer_pair: tuple[Signer, Signer]
) -> None:
    caller, authority = signer_pair

    def fail(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    client = SiteCapacityAdminClient(
        "http://site-authority:8081",
        caller,
        TrustedIdentitySet(identities=(authority.identity,)),
        transport=httpx.MockTransport(fail),
    )
    with pytest.raises(SiteCapacityAdminClientError) as excinfo:
        await client.register_resource(
            "r1", total_units=1, request_id="transport-failure"
        )

    assert excinfo.value.status_code is None
    assert "r1" in str(excinfo.value)


@pytest.mark.asyncio
async def test_commit_requires_a_reservation_id(
    capacity_client: SiteCapacityClient,
) -> None:
    with pytest.raises(ValueError, match="capacity_reservation_id"):
        await capacity_client.commit(capacity_reservation_id=None)
