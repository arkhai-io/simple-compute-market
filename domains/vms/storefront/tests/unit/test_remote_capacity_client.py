"""RemoteCapacityClient: wire contract, mode dispatch, and delta delivery.

The FakeSite transport mirrors the provisioning service's
/api/v1/capacity surface (whose shapes are pinned by that service's own
integration tests); these tests pin the storefront half of the contract.
"""

from __future__ import annotations

import asyncio
import itertools
import json
from types import SimpleNamespace
from unittest.mock import patch

import httpx
import pytest

from core_storefront.capacity import CapacityClient, CapacityDelta
from market_storefront.services import capacity_client as cc


class FakeSite:
    """In-memory site authority behind an httpx.MockTransport."""

    def __init__(self) -> None:
        self.resources: dict[str, dict] = {}
        self.allocations: dict[str, dict] = {}
        self.events: list[dict] = []
        self._versions = itertools.count(1)
        self._ids = itertools.count(1)
        self.seen_admin_keys: list[str | None] = []

    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self._handle)

    def _emit(self, kind: str, resource_id: str | None) -> None:
        self.events.append({
            "version": next(self._versions),
            "kind": kind,
            "resource_id": resource_id,
            "occurred_at": "2026-01-01T00:00:00Z",
        })

    def _available(self, rid: str) -> int:
        held = sum(
            a["units"] for a in self.allocations.values()
            if a["resource_id"] == rid
            and a["state"] in ("reserved", "provisioning", "leased", "releasing")
        )
        return self.resources[rid]["total_units"] - held

    def _handle(self, request: httpx.Request) -> httpx.Response:
        self.seen_admin_keys.append(request.headers.get("X-Admin-Key"))
        path = request.url.path
        body = json.loads(request.content) if request.content else {}

        if request.method == "PUT" and path.startswith("/api/v1/capacity/resources/"):
            rid = path.rsplit("/", 1)[1]
            self.resources[rid] = {
                "resource_id": rid,
                "total_units": body["total_units"],
                "attributes": body.get("attributes") or {},
                "enabled": body.get("enabled", True),
            }
            self._emit("released", rid)
            return httpx.Response(200, json=self.resources[rid])

        if path == "/api/v1/capacity/snapshot":
            return httpx.Response(200, json={"resources": [
                {
                    "resource_id": rid,
                    "resource_type": "compute.gpu",
                    "value": row["total_units"],
                    "available_units": self._available(rid),
                    "attributes": row["attributes"],
                    "enabled": True,
                }
                for rid, row in self.resources.items() if row["enabled"]
            ]})

        if path == "/api/v1/capacity/probe":
            return httpx.Response(200, json={"match": self._match(body["claim"])})

        if path == "/api/v1/capacity/reservations":
            match = self._match(body["claim"])
            if match is None:
                return httpx.Response(200, json={"allocation": None})
            allocation_id = f"alloc-{next(self._ids)}"
            self.allocations[allocation_id] = {
                "allocation_id": allocation_id,
                "resource_id": match["resource_id"],
                "units": match["allocated_gpu_count"],
                "state": "reserved",
                "deal_ref": body.get("deal_ref") or {},
            }
            self._emit("reserved", match["resource_id"])
            return httpx.Response(200, json={"allocation": {
                **match,
                "allocation_id": allocation_id,
                "hold_expires_at": None,
            }})

        if path.endswith("/commit"):
            allocation_id = path.split("/")[-2]
            allocation = self.allocations.get(allocation_id)
            if allocation is None:
                return httpx.Response(404, json={"detail": "not found"})
            allocation["state"] = "leased"
            allocation["lease_end_utc"] = body["lease_end_utc"]
            self._emit("committed", allocation["resource_id"])
            return httpx.Response(200, json={"allocation": allocation})

        if path == "/api/v1/capacity/releases":
            allocation = None
            if body.get("allocation_id"):
                allocation = self.allocations.get(body["allocation_id"])
            else:
                escrow = (body.get("deal_ref") or {}).get("escrow_uid")
                allocation = next(
                    (a for a in self.allocations.values()
                     if a["deal_ref"].get("escrow_uid") == escrow
                     and a["state"] != "released"),
                    None,
                )
            if allocation is None or allocation["state"] == "released":
                return httpx.Response(200, json={"allocation": None})
            allocation["state"] = "released"
            allocation["failure_reason"] = body.get("failure_reason")
            self._emit("released", allocation["resource_id"])
            return httpx.Response(200, json={"allocation": allocation})

        if path.endswith("/truncate-lease"):
            allocation_id = path.split("/")[-2]
            allocation = self.allocations.get(allocation_id)
            if allocation is None:
                return httpx.Response(200, json={"allocation": None})
            allocation["lease_end_utc"] = body["lease_end_utc"]
            self._emit("lease_truncated", allocation["resource_id"])
            return httpx.Response(200, json={"allocation": allocation})

        if path == "/api/v1/capacity/allocations":
            escrow = request.url.params.get("escrow_uid")
            state = request.url.params.get("state")
            rows = [
                a for a in self.allocations.values()
                if (escrow is None or a["deal_ref"].get("escrow_uid") == escrow)
                and (state is None or a["state"] == state)
            ]
            return httpx.Response(200, json={
                "allocations": rows, "total": len(rows),
            })

        if path == "/api/v1/capacity/events":
            after = int(request.url.params.get("after", 0))
            limit = int(request.url.params.get("limit", 500))
            page = [e for e in self.events if e["version"] > after][:limit]
            latest = self.events[-1]["version"] if self.events else 0
            return httpx.Response(200, json={
                "events": page, "latest_version": latest,
            })

        return httpx.Response(404, json={"detail": f"unhandled {path}"})

    def _match(self, claim: dict) -> dict | None:
        requested = int(claim.get("gpu_count") or 1)
        for rid, row in self.resources.items():
            if not row["enabled"]:
                continue
            attrs = row["attributes"]
            if any(
                attrs.get(k) != v for k, v in claim.items() if k != "gpu_count"
            ):
                continue
            available = self._available(rid)
            if available < requested:
                continue
            return {
                "resource_id": rid,
                "pool_id": None,
                "member_id": None,
                "vm_host": attrs.get("vm_host"),
                "allocated_gpu_count": requested,
                "available_gpu_count": available,
                "attributes": attrs,
            }
        return None


@pytest.fixture
def site() -> FakeSite:
    fake = FakeSite()
    fake.resources["compute-kvm1-001"] = {
        "resource_id": "compute-kvm1-001",
        "total_units": 8,
        "attributes": {"vm_host": "kvm1", "gpu_model": "H200"},
        "enabled": True,
    }
    return fake


@pytest.fixture
def client(site: FakeSite) -> cc.RemoteCapacityClient:
    return cc.RemoteCapacityClient(
        "http://site-authority:8081", "test-key", transport=site.transport(),
    )


def _settings(mode: str = "site", url: str = "http://site-authority:8081"):
    return SimpleNamespace(
        capacity=SimpleNamespace(mode=mode, authority_url=url, poll_interval=0.01),
        provisioning=SimpleNamespace(service_url="http://prov:8081"),
        admin_api_key="test-key",
    )


@pytest.mark.asyncio
async def test_remote_client_speaks_the_capacity_wire_contract(
    client: cc.RemoteCapacityClient, site: FakeSite,
):
    assert isinstance(client, CapacityClient)

    snapshot = await client.snapshot()
    assert snapshot[0]["available_units"] == 8

    assert await client.probe(claim={"gpu_model": "A100"}) is None
    match = await client.probe(claim={"gpu_model": "H200"})
    assert match["vm_host"] == "kvm1"

    reserved = await client.reserve(
        claim={"gpu_count": 3}, deal_ref={"escrow_uid": "0xesc"},
    )
    assert reserved["allocation_id"]
    assert reserved["available_gpu_count"] == 8

    await client.commit(
        resource_id=reserved["resource_id"],
        allocation_id=reserved["allocation_id"],
        lease_end_utc="2099-01-01 00:00",
        idempotency_ref="0xesc",
    )
    truncated = await client.truncate_lease(
        allocation_id=reserved["allocation_id"], lease_end_utc="2026-06-01 00:00",
    )
    assert truncated["lease_end_utc"] == "2026-06-01 00:00"

    released = await client.release(
        deal_ref={"escrow_uid": "0xesc"}, failure_reason="provisioning_failed",
    )
    assert released["state"] == "released"
    assert released["failure_reason"] == "provisioning_failed"

    events, latest = await client.events_after(0)
    assert [e["kind"] for e in events] == [
        "reserved", "committed", "lease_truncated", "released",
    ]
    assert latest == events[-1]["version"]
    # Every call authenticated.
    assert set(site.seen_admin_keys) == {"test-key"}


@pytest.mark.asyncio
async def test_commit_without_allocation_id_is_an_error(
    client: cc.RemoteCapacityClient,
):
    with pytest.raises(ValueError, match="allocation_id"):
        await client.commit(
            resource_id="r", allocation_id=None, lease_end_utc="2099-01-01 00:00",
        )


@pytest.mark.asyncio
async def test_site_held_by_resource_derives_consumption(
    client: cc.RemoteCapacityClient,
):
    await client.reserve(claim={"gpu_count": 3}, deal_ref={})
    held = await cc.site_held_by_resource(client)
    assert held == {"compute-kvm1-001": 3}


@pytest.mark.asyncio
async def test_list_allocations_filters(client: cc.RemoteCapacityClient):
    reserved = await client.reserve(
        claim={"gpu_count": 1}, deal_ref={"escrow_uid": "0xq"},
    )
    rows = await client.list_allocations(escrow_uid="0xq")
    assert [a["allocation_id"] for a in rows] == [reserved["allocation_id"]]
    assert await client.list_allocations(state="released") == []


def test_build_dispatches_on_capacity_mode():
    cc._remote_subscriber_attached = False
    try:
        with patch("market_storefront.utils.config.settings", _settings()):
            built = cc.build_capacity_client(lambda: None)
        assert isinstance(built, cc.RemoteCapacityClient)
        assert built.base_url == "http://site-authority:8081"

        with patch("market_storefront.utils.config.settings", _settings(mode="")):
            embedded = cc.build_capacity_client(lambda: None)
        assert isinstance(embedded, cc.EmbeddedCapacityClient)
    finally:
        cc._remote_subscriber_attached = False
        cc._remote_bus = type(cc._remote_bus)()


def test_site_mode_defaults_authority_url_to_provisioning():
    cc._remote_subscriber_attached = False
    try:
        with patch(
            "market_storefront.utils.config.settings", _settings(url=""),
        ):
            built = cc.build_capacity_client(lambda: None)
        assert built.base_url == "http://prov:8081"
    finally:
        cc._remote_subscriber_attached = False
        cc._remote_bus = type(cc._remote_bus)()


@pytest.mark.asyncio
async def test_remote_subscriber_closes_and_reopens_with_site_held(
    client: cc.RemoteCapacityClient,
):
    calls: list[tuple[str, dict | None]] = []

    async def fake_close(db_path, *, held_by_resource=None):
        calls.append(("close", held_by_resource))
        return ["lst-1"]

    async def fake_reopen(db_path, *, held_by_resource=None):
        calls.append(("reopen", held_by_resource))
        return []

    subscriber = cc._make_remote_listing_subscriber(
        lambda: SimpleNamespace(db_path="/tmp/x.db"), client,
    )
    await client.reserve(claim={"gpu_count": 2}, deal_ref={})
    with patch.object(
        cc, "site_held_by_resource", wraps=cc.site_held_by_resource,
    ), patch(
        "market_storefront.services.publication_service."
        "close_stale_compute_listings_after_capacity_change",
        fake_close,
    ), patch(
        "market_storefront.services.publication_service."
        "reopen_available_compute_listings_after_capacity_change",
        fake_reopen,
    ):
        await subscriber(CapacityDelta(kind="reserved", version=1))
        await subscriber(CapacityDelta(kind="released", version=2))

    assert [c[0] for c in calls] == ["close", "reopen"]
    # Held counts came from the site snapshot, not local tables.
    assert calls[0][1] == {"compute-kvm1-001": 2}


@pytest.mark.asyncio
async def test_poller_positions_at_head_then_emits_new_deltas(site: FakeSite):
    """The poller skips history, reconciles once, then streams deltas."""
    client = cc.RemoteCapacityClient(
        "http://site-authority:8081", "test-key",
        transport=site.transport(),
    )
    seen: list[CapacityDelta] = []

    async def record(delta: CapacityDelta) -> None:
        seen.append(delta)

    client.subscribe(record)
    site._emit("reserved", "compute-kvm1-001")  # history — must NOT replay

    reconciles = 0

    async def fake_reconcile(db_path, *, held_by_resource=None):
        nonlocal reconciles
        reconciles += 1
        return []

    with patch.object(cc, "build_capacity_client", return_value=client), patch(
        "market_storefront.utils.config.settings", _settings(),
    ), patch(
        "market_storefront.utils.sqlite_client.get_sqlite_client",
        return_value=SimpleNamespace(db_path="/tmp/x.db"),
    ), patch(
        "market_storefront.services.publication_service."
        "close_stale_compute_listings_after_capacity_change",
        fake_reconcile,
    ), patch(
        "market_storefront.services.publication_service."
        "reopen_available_compute_listings_after_capacity_change",
        fake_reconcile,
    ):
        task = asyncio.create_task(cc.capacity_events_poller_loop())
        try:
            for _ in range(200):
                if reconciles >= 2:  # startup close+reopen ran
                    break
                await asyncio.sleep(0.01)
            site._emit("committed", "compute-kvm1-001")
            for _ in range(200):
                if seen:
                    break
                await asyncio.sleep(0.01)
        finally:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

    assert reconciles >= 2
    assert [d.kind for d in seen] == ["committed"]
    assert seen[0].resource_id == "compute-kvm1-001"
