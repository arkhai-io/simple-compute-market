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
