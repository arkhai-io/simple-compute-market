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
        self.reserve_call_count = 0
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
        self.reserve_call_count += 1
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
async def test_reserve_with_no_site_still_uses_placement_fan_out():
    """The default (site omitted) is byte-for-byte today's behavior --
    _reserve_by_placement, unchanged, for a listing with no site
    mapping."""
    client, a, b = _aggregate(placement=fill_first)
    reserved = await client.reserve(claim={"gpu_count": 1}, deal_ref={}, site=None)
    assert reserved["site"] == "dc-a"


@pytest.mark.asyncio
async def test_reserve_pinned_to_a_site_reserves_there():
    client, a, b = _aggregate()
    reserved = await client.reserve(claim={"gpu_count": 1}, deal_ref={}, site="dc-b")
    assert reserved["site"] == "dc-b"
    assert a.available == 4  # untouched
    assert b.available == 7


@pytest.mark.asyncio
async def test_reserve_pinned_to_a_site_ignores_placement_preference():
    """A listing mapped to a site reserves only there, regardless of
    placement policy: placement would prefer dc-b (more free units),
    but a mapping to dc-a must still reserve at dc-a."""
    client, a, b = _aggregate(placement=most_available)
    # Confirm placement really would pick the other site if left to
    # choose -- otherwise this test wouldn't actually exercise anything.
    unpinned = await client.reserve(claim={"gpu_count": 1}, deal_ref={})
    assert unpinned["site"] == "dc-b"

    pinned = await client.reserve(claim={"gpu_count": 1}, deal_ref={}, site="dc-a")
    assert pinned["site"] == "dc-a"


@pytest.mark.asyncio
async def test_reserve_pinned_to_an_unknown_site_raises():
    client, a, b = _aggregate()
    with pytest.raises(KeyError):
        await client.reserve(claim={"gpu_count": 1}, deal_ref={}, site="dc-ghost")


@pytest.mark.asyncio
async def test_reserve_pinned_to_a_broken_site_propagates_not_falls_back():
    """No fallback for a pinned reservation: a site error must not be
    silently absorbed by trying another site, unlike the placement path
    (test_reserve_falls_back_past_a_broken_site)."""
    client, a, b = _aggregate()
    a.broken = True
    with pytest.raises(ConnectionError):
        await client.reserve(claim={"gpu_count": 1}, deal_ref={}, site="dc-a")
    # b was never touched -- confirms no fallback attempt happened.
    assert b.available == 8


@pytest.mark.asyncio
async def test_reserve_pinned_returns_none_on_refusal_not_an_exception():
    """A pinned site correctly refusing (no capacity) is not an error --
    still returns None, same as the placement path's per-site refusal."""
    client, a, b = _aggregate()
    reserved = await client.reserve(claim={"gpu_count": 99}, deal_ref={}, site="dc-a")
    assert reserved is None


@pytest.mark.asyncio
async def test_reserve_pinned_records_the_reservation_site():
    client, a, b = _aggregate()
    reserved = await client.reserve(claim={"gpu_count": 1}, deal_ref={}, site="dc-b")
    capacity_reservation_id = reserved["capacity_reservation_id"]
    assert client.reservation_sites[capacity_reservation_id] == "dc-b"


# ---------------------------------------------------------------------------
# Regression proof: reserve() always hits the site's real, live endpoint --
# no shortcut exists that could answer from cached/projected data instead.
# Structurally confirmed too: aggregation.py has zero references to any
# projection cache -- these tests prove the observable behavior that fact
# implies, so a future regression that adds such a reference would also
# have to break one of these to slip through.
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_reserve_by_placement_actually_calls_the_winning_sites_reserve():
    client, a, b = _aggregate(placement=fill_first)
    assert a.reserve_call_count == 0
    reserved = await client.reserve(claim={"gpu_count": 1}, deal_ref={})
    assert reserved["site"] == "dc-a"
    assert a.reserve_call_count == 1
    assert b.reserve_call_count == 0  # never consulted -- fill_first packed a first


@pytest.mark.asyncio
async def test_reserve_by_placement_calls_every_site_it_actually_falls_back_through():
    """Placement's fallback tries sites in order -- each one it visits
    must be a real call, not a cached/skipped answer."""
    client, a, b = _aggregate(placement=fill_first)
    a.units = 0  # a refuses immediately, no capacity
    reserved = await client.reserve(claim={"gpu_count": 1}, deal_ref={})
    assert reserved["site"] == "dc-b"
    assert a.reserve_call_count == 1  # visited and asked, not skipped
    assert b.reserve_call_count == 1


@pytest.mark.asyncio
async def test_reserve_pinned_to_a_site_actually_calls_that_sites_reserve():
    client, a, b = _aggregate()
    assert b.reserve_call_count == 0
    await client.reserve(claim={"gpu_count": 1}, deal_ref={}, site="dc-b")
    assert b.reserve_call_count == 1
    assert a.reserve_call_count == 0  # not pinned, never touched


@pytest.mark.asyncio
async def test_reserve_pinned_call_count_is_exactly_one_even_on_refusal():
    """A pinned site refusing must still show exactly one real call --
    proves the refusal came from actually asking, not from a projection
    answering "no" without a live round trip."""
    client, a, b = _aggregate()
    reserved = await client.reserve(claim={"gpu_count": 99}, deal_ref={}, site="dc-a")
    assert reserved is None
    assert a.reserve_call_count == 1


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

from core_storefront.aggregation import (  # noqa: E402
    ClaimMatcher,
    _coarse_resource_matches_claim,
    _site_available_units,
)


def test_resource_matches_claim_no_claim_matches_everything():
    row = {"pool_id": "pool-a", "resource_id": "r1", "available_units": 0}
    assert _coarse_resource_matches_claim(row, None) is True
    assert _coarse_resource_matches_claim(row, {}) is True


def test_resource_matches_claim_filters_by_pool_id():
    row = {"pool_id": "pool-a", "resource_id": "r1", "available_units": 100}
    assert _coarse_resource_matches_claim(row, {"pool_id": "pool-a"}) is True
    assert _coarse_resource_matches_claim(row, {"pool_id": "pool-b"}) is False


def test_resource_matches_claim_filters_by_resource_id():
    row = {"pool_id": "pool-a", "resource_id": "r1", "available_units": 100}
    assert _coarse_resource_matches_claim(row, {"resource_id": "r1"}) is True
    assert _coarse_resource_matches_claim(row, {"resource_id": "r2"}) is False


def test_resource_matches_claim_dimensions_requires_every_requested_dimension():
    row = {
        "pool_id": "pool-a", "resource_id": "r1", "available_units": 4,
        "available": {"gpu_count": 4, "ram_gb": 64},
    }
    assert _coarse_resource_matches_claim(
        row, {"dimensions": {"gpu_count": 2, "ram_gb": 32}},
    ) is True
    # Enough GPUs, not enough RAM -- must fail on the RAM dimension alone.
    assert _coarse_resource_matches_claim(
        row, {"dimensions": {"gpu_count": 2, "ram_gb": 128}},
    ) is False


def test_resource_matches_claim_legacy_units_shape_apicredits_style():
    row = {"pool_id": None, "resource_id": "quota-1", "available_units": 10}
    assert _coarse_resource_matches_claim(row, {"units": 5}) is True
    assert _coarse_resource_matches_claim(row, {"units": 50}) is False
    assert _coarse_resource_matches_claim(row, {"gpu_count": 5}) is True


def test_coarse_matcher_ignores_categorical_attributes_by_design():
    """The coarse default is documented as not checking arbitrary
    categorical claim attributes (e.g. region/gpu_model) -- pins that
    this is a deliberate, named limitation, not an oversight, so a
    caller who needs exact semantics knows to inject a stronger
    ClaimMatcher rather than assume this one already checks everything
    a claim might name."""
    row = {
        "pool_id": "pool-a", "resource_id": "r1", "available_units": 4,
        "available": {"gpu_count": 4},
        "attributes": {"region": "us-east", "gpu_model": "L40"},
    }
    # A completely mismatched region/gpu_model still "matches" the
    # coarse default -- this is the documented gap an injected matcher
    # closes, not a bug in the coarse matcher itself.
    assert _coarse_resource_matches_claim(
        row,
        {
            "pool_id": "pool-a",
            "region": "eu-west",
            "gpu_model": "A100",
            "dimensions": {"gpu_count": 1},
        },
    ) is True


def test_site_available_units_ignores_non_matching_pool_rows():
    """A site with abundant capacity in an unrelated pool must not be
    ranked as available for a request it cannot serve."""
    snapshot = [
        {"pool_id": "wrong-pool", "resource_id": "r1", "available_units": 500},
        {"pool_id": "right-pool", "resource_id": "r2", "available_units": 2},
    ]
    claim = {"pool_id": "right-pool"}
    assert _site_available_units(snapshot, claim, _coarse_resource_matches_claim) == 2
    assert _site_available_units(snapshot, None, _coarse_resource_matches_claim) == 502


def test_site_available_units_accepts_an_injected_claim_matcher():
    """The matcher is a parameter, not a hardcoded call -- a caller can
    inject a stricter (or looser) one and _site_available_units must use
    exactly that one, not silently fall back to the coarse default."""
    snapshot = [{"pool_id": "p", "resource_id": "r1", "available_units": 5}]

    def _reject_everything(row: Mapping[str, Any], claim: Mapping[str, Any] | None) -> bool:
        return False

    assert _site_available_units(snapshot, {"pool_id": "p"}, _reject_everything) == 0
    assert _site_available_units(snapshot, {"pool_id": "p"}, _coarse_resource_matches_claim) == 5


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


@pytest.mark.asyncio
async def test_most_available_uses_an_injected_exact_claim_matcher_when_given_one():
    """A composition root injecting an exact ClaimMatcher (e.g. VM's
    kit/site-backed one) must see it actually change the ranking --
    proves claim_matcher is threaded through, not just accepted and
    ignored."""
    client, a, b = _aggregate(placement=most_available)

    async def snapshot_a():
        return [{
            "resource_id": "r-a", "pool_id": "gpu-pool",
            "available_units": 1, "state": "available",
            "attributes": {"region": "eu-west"},
        }]

    async def snapshot_b():
        return [{
            "resource_id": "r-b", "pool_id": "gpu-pool",
            "available_units": 20, "state": "available",
            "attributes": {"region": "us-east"},
        }]

    a.snapshot = snapshot_a  # type: ignore[method-assign]
    b.snapshot = snapshot_b  # type: ignore[method-assign]

    snapshots = {"dc-a": await a.snapshot(), "dc-b": await b.snapshot()}
    claim = {"pool_id": "gpu-pool", "region": "eu-west"}

    def _region_exact_matcher(row: Mapping[str, Any], claim: Mapping[str, Any] | None) -> bool:
        if not claim:
            return True
        if row.get("pool_id") != claim.get("pool_id"):
            return False
        return row.get("attributes", {}).get("region") == claim.get("region")

    # Coarse default ignores region -- site B's larger raw total wins.
    coarse_order = most_available(["dc-a", "dc-b"], snapshots, claim=claim)
    assert coarse_order == ["dc-b", "dc-a"]

    # Injected exact matcher excludes B entirely (wrong region) -- A wins.
    exact_order = most_available(
        ["dc-a", "dc-b"], snapshots, claim=claim, claim_matcher=_region_exact_matcher,
    )
    assert exact_order == ["dc-a", "dc-b"]
