"""Replay capacity-bound derivation through invocation-owned storefront apps.

Temporary change evidence, not a collected acceptance suite. All service/chain
boundaries are existing fixture doubles; no public deployment or lease is used.
"""

from __future__ import annotations

import argparse
import asyncio
from copy import deepcopy
from dataclasses import asdict
from pathlib import Path
import sys
from tempfile import TemporaryDirectory

from market_resource_pools_contracts import (
    CapacityBounds, capacity_bound_hint, resolve_capacity_bounds,
)
from market_pool_overrides import PoolOverrideClient

ROOT = Path(__file__).resolve().parents[3]
HINT_END = "2035-01-02T00:00:00Z"
OVERRIDE_END = "2035-01-01T00:00:00Z"
DEFAULT_END = "2035-01-03T00:00:00Z"


def row(value):
    data = {**value.extra, **asdict(value)}
    data.pop("extra", None)
    return data


def pure():
    hint = capacity_bound_hint({
        "capacity_bounds": {"vm": {
            "max_duration_seconds": 7200, "available_until_utc": HINT_END,
        }},
    }, "vm")
    resolved = resolve_capacity_bounds(
        CapacityBounds(available_until_utc=OVERRIDE_END), hint,
        CapacityBounds(max_duration_seconds=86400, available_until_utc=DEFAULT_END),
    )
    assert resolved.max_duration_seconds == 7200
    assert resolved.available_until_utc == OVERRIDE_END
    for relative in (0, -1):
        unlimited = resolve_capacity_bounds(CapacityBounds(max_duration_seconds=relative), hint)
        assert unlimited.positive_max_duration_seconds is None
        assert unlimited.available_until_utc == HINT_END
    for bad in ("2035-01-01", "2035-01-01T00:00:00", "bad", 123, True,
                "2035-01-01T01:00:00+01:00"):
        try:
            CapacityBounds(available_until_utc=bad)
        except ValueError:
            pass
        else:
            raise AssertionError(f"accepted malformed UTC bound: {bad!r}")
    for bad in (True, "3600", 1.5):
        try:
            CapacityBounds(max_duration_seconds=bad)
        except ValueError:
            pass
        else:
            raise AssertionError(f"accepted malformed relative bound: {bad!r}")
    print("strict UTC/integer validation; independent tiers; nonpositive masking: PASS")


async def vm(path):
    sys.path.insert(0, str(ROOT / "domains/vms/storefront"))
    import tests.conftest  # Lazy: install only this mode's public domain configuration.
    from tests.publication_app import publication_app, pool  # Lazy: only the VM environment has these fixtures.
    from tests._settings_overrides import replaced_setting  # Lazy: only the VM environment has these fixtures.

    with replaced_setting("pricing.defaults", {}), \
         replaced_setting("pricing.default_max_duration_seconds", 86400), \
         replaced_setting("pricing.default_available_until_utc", DEFAULT_END):
        async with publication_app(path) as app:
            projected = pool("bounded", backing="backed", capacity_bounds={
                "vm": {"max_duration_seconds": 7200, "available_until_utc": HINT_END},
            })
            app.pools.append(projected)
            await app.client.get_system_status()
            await app.client.admin_run_lifecycle_cycle("site-projections")
            await app.client.admin_run_lifecycle_cycle("publication")
            page = await app.client.list_listings(status="open")
            (listing,) = page.listings
            identity = listing.listing_id
            declared = row(await app.client.get_listing(identity))
            assert declared["max_duration_seconds"] == 7200
            assert declared["available_until_utc"] == HINT_END

            overrides = PoolOverrideClient(app.client)
            address = {"site_id": "site-a", "pool_id": "bounded", "offering_mode": "vm"}
            await overrides.put_pool_override({
                **address, "terms": {"available_until_utc": OVERRIDE_END},
            })
            await app.client.admin_run_lifecycle_cycle("publication")
            updated = row(await app.client.get_listing(identity))
            assert updated["max_duration_seconds"] == 7200
            assert updated["available_until_utc"] == OVERRIDE_END
            sent = app.registries.to("publish", identity)[-1][1]
            assert sent["available_until_utc"] == OVERRIDE_END
            assert "available_until_utc" not in sent["listing_resource"]

            await overrides.put_pool_override({
                **address, "terms": {"max_duration_seconds": 0},
            })
            await app.client.admin_run_lifecycle_cycle("publication")
            unlimited = row(await app.client.get_listing(identity))
            assert unlimited["max_duration_seconds"] is None
            assert unlimited["available_until_utc"] == HINT_END

            projected["pool_metadata"]["policy_tags"]["capacity_bounds"]["vm"][
                "available_until_utc"
            ] = "not-a-date"
            await app.client.admin_run_lifecycle_cycle("site-projections")
            held = await app.client.admin_run_lifecycle_cycle("publication")
            assert any(item.get("reason") == "capacity_bounds_unreadable"
                       for item in held["actions"])
            assert row(await app.client.get_listing(identity)) == unlimited
            print("VM typed admin publication/read: override/hint/default; identity; hold: PASS")

            # Withdraw all bounds: absent now means absent after republication,
            # rather than silently retaining the last stored absolute/relative end.
            del projected["pool_metadata"]["policy_tags"]["capacity_bounds"]
            await overrides.delete_pool_override(**address)
            with replaced_setting("pricing.default_max_duration_seconds", 0), \
                 replaced_setting("pricing.default_available_until_utc", None):
                await app.client.admin_run_lifecycle_cycle("publication")
                withdrawn = row(await app.client.get_listing(identity))
                assert withdrawn["available_until_utc"] is None
                assert withdrawn["max_duration_seconds"] is None
                sent = app.registries.to("publish", identity)[-1][1]
                assert "available_until_utc" not in sent
            print("VM bound withdrawal clears persisted/publication values: PASS")


async def bare(path):
    sys.path.insert(0, str(ROOT / "domains/bare_metal/storefront/tests"))
    from pytest import MonkeyPatch  # Lazy: the pure diagnostic does not patch an app.
    from test_publication_cycle import Site, pool, member  # Lazy: only the bare-metal environment has these fixtures.
    from test_http_system import _derivation_runtime, _app, _admin_client  # Lazy: only the bare-metal environment has these fixtures.
    from test_http_publication_rates import _Sites  # Lazy: only the bare-metal environment has these fixtures.

    projected = pool("pool-1", member("r1", "pool-1"), policy_tags={
        "capacity_bounds": {"bare_metal": {
            "max_duration_seconds": 7200, "available_until_utc": HINT_END,
        }},
    })
    site = Site(projected)
    with MonkeyPatch.context() as patches:
        runtime = _derivation_runtime(
            path, patches, {"site-a": site},
            default_max_duration_seconds=86400,
            default_available_until_utc=DEFAULT_END,
            capacity_client=_Sites(site),
        )
        app = _app(runtime)
        async with app.router.lifespan_context(app):
            async with _admin_client(app) as admin:
                await admin.get_system_status()
                await admin.admin_run_lifecycle_cycle("publication")
                (listing,) = (await admin.list_listings(status="open")).listings
                identity = listing.listing_id
                declared = row(await admin.get_listing(identity))
                assert declared["max_duration_seconds"] == 7200
                assert declared["available_until_utc"] == HINT_END
                overrides = PoolOverrideClient(admin)
                address = {"site_id": "site-a", "pool_id": "pool-1",
                           "offering_mode": "bare_metal"}
                await overrides.put_pool_override({
                    **address, "terms": {"available_until_utc": OVERRIDE_END},
                })
                await admin.admin_run_lifecycle_cycle("publication")
                updated = row(await admin.get_listing(identity))
                assert updated["max_duration_seconds"] == 7200
                assert updated["available_until_utc"] == OVERRIDE_END
                sent = runtime.registry_configuration.recording.sent[-1][3]
                assert sent["available_until_utc"] == OVERRIDE_END
                assert "available_until_utc" not in sent["listing_resource"]
                assert "max_duration_seconds" not in sent["listing_resource"]

                broken = deepcopy(projected)
                broken["pool_metadata"]["policy_tags"]["capacity_bounds"]["bare_metal"][
                    "available_until_utc"
                ] = "not-a-date"
                site.serve(broken)
                await admin.admin_run_lifecycle_cycle("site-projections")
                held = await admin.admin_run_lifecycle_cycle("publication")
                assert any(item.get("reason") == "capacity_bounds_unreadable"
                           for item in held["actions"])
                assert row(await admin.get_listing(identity)) == updated
                print("bare-metal typed publication/read: independent bounds; identity; hold: PASS")

                site.serve(projected)
                await overrides.put_pool_override({
                    **address, "terms": {"max_duration_seconds": -1},
                })
                held = await admin.admin_run_lifecycle_cycle("publication")
                assert any(item.get("reason") == "pool_lease_bound_missing"
                           for item in held["actions"])
                assert row(await admin.get_listing(identity)) == updated
                print("bare-metal retains positive relative reserved-bound admission: PASS")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("surface", choices=("pure", "vm", "bare"))
    args = parser.parse_args()
    pure()
    if args.surface != "pure":
        with TemporaryDirectory(prefix="capacity-bounds-") as directory:
            asyncio.run((vm if args.surface == "vm" else bare)(Path(directory)))
