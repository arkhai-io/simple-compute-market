"""AggregateCapacityClient: union reads, routed writes, fallback on refusal."""

from __future__ import annotations

from typing import Any, Mapping

import pytest

from core_storefront.aggregation import (
    AggregateCapacityClient,
    fill_first,
    most_available,
)
from core_storefront.capacity import CapacityClient, CapacityDelta


class FakeSite:
    """In-memory single-resource site ledger."""

    def __init__(self, resource_id: str, units: int, *, broken: bool = False) -> None:
        self.resource_id = resource_id
        self.units = units
        self.broken = broken
        self.reservations: dict[str, int] = {}
        self.committed: list[str] = []
        self._seq = 0

    def _check(self) -> None:
        if self.broken:
            raise ConnectionError("site down")

    @property
    def available(self) -> int:
        return self.units - sum(self.reservations.values())

    async def snapshot(self) -> list[dict[str, Any]]:
        self._check()
        return [{
            "resource_id": self.resource_id,
            "value": self.units,
            "available_units": self.available,
            "state": "available" if self.available else "leased",
            "attributes": {"vm_host": "h"},
        }]

    async def probe(
        self,
        *,
        claim: Mapping[str, Any] | None = None,
        lease_start_utc=None,
        lease_duration_seconds=None,
    ):
        self._check()
        requested = int((claim or {}).get("gpu_count") or 1)
        if self.available < requested:
            return None
        return {"resource_id": self.resource_id, "allocated_gpu_count": requested}

    async def reserve(
        self,
        *,
        claim=None,
        deal_ref=None,
        ttl_seconds=None,
        lease_start_utc=None,
        lease_duration_seconds=None,
    ):
        self._check()
        requested = int((claim or {}).get("gpu_count") or 1)
        if self.available < requested:
            return None
        self._seq += 1
        capacity_reservation_id = f"{self.resource_id}-a{self._seq}"
        self.reservations[capacity_reservation_id] = requested
        return {
            "resource_id": self.resource_id,
            "capacity_reservation_id": capacity_reservation_id,
            "allocated_gpu_count": requested,
        }

    async def commit(self, *, resource_id, capacity_reservation_id=None,
                     lease_start_utc=None, lease_duration_seconds=None,
                     lease_end_utc=None, idempotency_ref=None) -> None:
        self._check()
        if capacity_reservation_id not in self.reservations:
            raise LookupError(f"unknown reservation {capacity_reservation_id}")
        self.committed.append(capacity_reservation_id)

    async def release(self, *, capacity_reservation_id=None, deal_ref=None, **extra):
        self._check()
        if capacity_reservation_id not in self.reservations:
            return None
        self.reservations.pop(capacity_reservation_id)
        return {"capacity_reservation_id": capacity_reservation_id, "state": "released", **extra}

    async def truncate_lease(self, *, capacity_reservation_id, lease_end_utc):
        self._check()
        if capacity_reservation_id not in self.reservations:
            return None
        return {"capacity_reservation_id": capacity_reservation_id, "lease_end_utc": lease_end_utc}

    def subscribe(self, subscriber):
        return lambda: None


def _aggregate(**kw) -> tuple[AggregateCapacityClient, FakeSite, FakeSite]:
    a = FakeSite("res-a", 4)
    b = FakeSite("res-b", 8)
    client = AggregateCapacityClient({"dc-a": a, "dc-b": b}, **kw)
    return client, a, b


@pytest.mark.asyncio
async def test_satisfies_the_capacity_client_protocol():
    client, _, _ = _aggregate()
    assert isinstance(client, CapacityClient)


@pytest.mark.asyncio
async def test_snapshot_is_a_site_tagged_union():
    client, _, _ = _aggregate()
    rows = await client.snapshot()
    assert {(r["site"], r["resource_id"]) for r in rows} == {
        ("dc-a", "res-a"), ("dc-b", "res-b"),
    }


@pytest.mark.asyncio
async def test_snapshot_skips_a_broken_site():
    client, a, _ = _aggregate()
    a.broken = True
    rows = await client.snapshot()
    assert [r["site"] for r in rows] == ["dc-b"]


@pytest.mark.asyncio
async def test_reserve_fill_first_packs_then_falls_back():
    client, a, b = _aggregate(placement=fill_first)

    # dc-a (4 units) fills first…
    for _ in range(4):
        reserved = await client.reserve(claim={"gpu_count": 1}, deal_ref={})
        assert reserved["site"] == "dc-a"
    # …then dc-b takes the overflow.
    reserved = await client.reserve(claim={"gpu_count": 1}, deal_ref={})
    assert reserved["site"] == "dc-b"
    assert a.available == 0 and b.available == 7


@pytest.mark.asyncio
async def test_reserve_returns_none_only_when_every_site_refuses():
    client, a, b = _aggregate()
    assert await client.reserve(claim={"gpu_count": 6}, deal_ref={}) is not None  # b fits
    assert await client.reserve(claim={"gpu_count": 6}, deal_ref={}) is None


@pytest.mark.asyncio
async def test_reserve_falls_back_past_a_broken_site():
    client, a, b = _aggregate(placement=fill_first)
    a.broken = True
    reserved = await client.reserve(claim={"gpu_count": 1}, deal_ref={})
    assert reserved["site"] == "dc-b"


@pytest.mark.asyncio
async def test_most_available_spreads():
    client, a, b = _aggregate(placement=most_available)
    # b (8 free) beats a (4 free).
    assert (await client.reserve(claim={"gpu_count": 1}, deal_ref={}))["site"] == "dc-b"


@pytest.mark.asyncio
async def test_writes_route_to_the_owning_site():
    client, a, b = _aggregate(placement=fill_first)
    reserved = await client.reserve(claim={"gpu_count": 2}, deal_ref={})
    capacity_reservation_id = reserved["capacity_reservation_id"]

    await client.commit(
        resource_id=reserved["resource_id"],
        capacity_reservation_id=capacity_reservation_id,
        lease_start_utc="2099-01-01T00:00:00Z",
        lease_end_utc="2099-01-01 01:00",
    )
    assert a.committed == [capacity_reservation_id]

    truncated = await client.truncate_lease(
        capacity_reservation_id=capacity_reservation_id, lease_end_utc="2026-01-01 00:00",
    )
    assert truncated["site"] == "dc-a"

    released = await client.release(capacity_reservation_id=capacity_reservation_id)
    assert released["site"] == "dc-a"
    assert a.available == 4


@pytest.mark.asyncio
async def test_cold_cache_fans_out_to_find_the_owner():
    """After a restart the reservation→site cache is empty; writes ask
    every site and the holder answers."""
    client, a, b = _aggregate()
    reserved = await client.reserve(claim={"gpu_count": 5}, deal_ref={})  # lands on b
    assert reserved["site"] == "dc-b"

    cold = AggregateCapacityClient({"dc-a": a, "dc-b": b})
    released = await cold.release(capacity_reservation_id=reserved["capacity_reservation_id"])
    assert released["site"] == "dc-b"

    # And a commit that no site recognizes propagates the failure.
    with pytest.raises(LookupError):
        await cold.commit(
            resource_id="res-a", capacity_reservation_id="ghost",
            lease_end_utc="2099-01-01 00:00",
        )


@pytest.mark.asyncio
async def test_site_deltas_reach_aggregate_subscribers_tagged():
    client, _, _ = _aggregate()
    seen: list[CapacityDelta] = []

    async def record(delta: CapacityDelta) -> None:
        seen.append(delta)

    client.subscribe(record)
    await client.emit_site_delta(
        "dc-b", CapacityDelta(kind="reserved", version=7, resource_id="res-b"),
    )
    assert seen[0].site == "dc-b"
    assert (seen[0].kind, seen[0].version, seen[0].resource_id) == (
        "reserved", 7, "res-b",
    )


# ---------------------------------------------------------------------------
# most_available claim-awareness: most_available/fill_first must never
# rank a site above another based on capacity it cannot actually serve a
# given claim from (wrong pool, wrong resource, insufficient dimensions).
# ---------------------------------------------------------------------------

from core_storefront.aggregation import _resource_matches_claim, _site_available_units  # noqa: E402


def test_resource_matches_claim_no_claim_matches_everything():
    row = {"pool_id": "pool-a", "resource_id": "r1", "available_units": 0}
    assert _resource_matches_claim(row, None) is True
    assert _resource_matches_claim(row, {}) is True


def test_resource_matches_claim_filters_by_pool_id():
    row = {"pool_id": "pool-a", "resource_id": "r1", "available_units": 100}
    assert _resource_matches_claim(row, {"pool_id": "pool-a"}) is True
    assert _resource_matches_claim(row, {"pool_id": "pool-b"}) is False


def test_resource_matches_claim_filters_by_resource_id():
    row = {"pool_id": "pool-a", "resource_id": "r1", "available_units": 100}
    assert _resource_matches_claim(row, {"resource_id": "r1"}) is True
    assert _resource_matches_claim(row, {"resource_id": "r2"}) is False


def test_resource_matches_claim_dimensions_requires_every_requested_dimension():
    row = {
        "pool_id": "pool-a", "resource_id": "r1", "available_units": 4,
        "available": {"gpu_count": 4, "ram_gb": 64},
    }
    assert _resource_matches_claim(
        row, {"dimensions": {"gpu_count": 2, "ram_gb": 32}},
    ) is True
    # Enough GPUs, not enough RAM -- must fail on the RAM dimension alone.
    assert _resource_matches_claim(
        row, {"dimensions": {"gpu_count": 2, "ram_gb": 128}},
    ) is False


def test_resource_matches_claim_legacy_units_shape_apicredits_style():
    row = {"pool_id": None, "resource_id": "quota-1", "available_units": 10}
    assert _resource_matches_claim(row, {"units": 5}) is True
    assert _resource_matches_claim(row, {"units": 50}) is False
    assert _resource_matches_claim(row, {"gpu_count": 5}) is True


def test_site_available_units_ignores_non_matching_pool_rows():
    """A site with abundant capacity in an unrelated pool must not be
    ranked as available for a request it cannot serve."""
    snapshot = [
        {"pool_id": "wrong-pool", "resource_id": "r1", "available_units": 500},
        {"pool_id": "right-pool", "resource_id": "r2", "available_units": 2},
    ]
    claim = {"pool_id": "right-pool"}
    assert _site_available_units(snapshot, claim) == 2
    assert _site_available_units(snapshot, None) == 502


@pytest.mark.asyncio
async def test_most_available_ranks_by_claim_matching_capacity_not_raw_total():
    """A site with a huge unrelated-pool total must not outrank a site
    with less total but the actually-requested pool's capacity."""
    client, a, b = _aggregate(placement=most_available)
    a.units, a.reservations = 4, {}
    b.units, b.reservations = 8, {}

    async def snapshot_a():
        return [{
            "resource_id": "r-a", "pool_id": "target-pool",
            "available_units": 1, "state": "available", "attributes": {},
        }]

    async def snapshot_b():
        return [{
            "resource_id": "r-b", "pool_id": "other-pool",
            "available_units": 8, "state": "available", "attributes": {},
        }]

    a.snapshot = snapshot_a  # type: ignore[method-assign]
    b.snapshot = snapshot_b  # type: ignore[method-assign]

    snapshots = {"dc-a": await a.snapshot(), "dc-b": await b.snapshot()}
    order = most_available(
        ["dc-a", "dc-b"], snapshots, claim={"pool_id": "target-pool"},
    )
    assert order == ["dc-a", "dc-b"]
