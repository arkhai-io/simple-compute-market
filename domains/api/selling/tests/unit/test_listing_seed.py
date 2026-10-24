"""The development seed publishes the bundle's mapping of its table, once per quota resource."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from types import SimpleNamespace

from arkhai_api_selling.lifecycle import ListingSeed
from tests.bundles import EXAMPLE


class _Store:
    def __init__(self, rows: list[dict]) -> None:
        self._rows = rows

    async def list_listings(self, *, limit: int, offset: int) -> list[dict]:
        return self._rows[offset : offset + limit]


class _Listings:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def publish_from_quota(self, **request) -> dict:
        self.calls.append(request)
        return {"listing_id": "L-seeded", "registry_status": "published"}


@dataclass(frozen=True)
class _RecordingSeed(ListingSeed):
    """A seed recording its quota registration rather than calling an authority."""

    registered: list[dict] = field(default_factory=list)

    async def register_quota(self, **quota) -> None:
        self.registered.append(quota)


def _seed(rows: list[dict], listings: _Listings, registered: list[dict]) -> ListingSeed:
    return _RecordingSeed(
        EXAMPLE,
        sqlite_client=lambda: _Store(rows),
        listing_service=lambda: listings,
        signer=lambda: None,
        site=lambda: None,
        accepted_escrows=lambda table: [{"chain_name": table["chain"]}],
        settlement_settings=frozenset({"chain", "token"}),
        pool_id="default",
        registered=registered,
    )


async def test_a_seed_registers_its_quota_and_publishes_the_mapping_of_its_listing_keys():
    listings, registered = _Listings(), []

    await _seed([], listings, registered).run(
        {
            "resource_id": "quota-a",
            "total_units": 7,
            "chain": "anvil",
            "token": "T",
            "paused": True,
            "product": "Example",
        }
    )

    assert registered == [{"resource_id": "quota-a", "total_units": 7}]
    assert listings.calls == [
        {
            "resource_id": "quota-a",
            "accepted_escrows": [{"chain_name": "anvil"}],
            "product": "Example",
        }
    ]


async def test_a_seed_whose_quota_already_has_an_open_listing_publishes_nothing():
    listings, registered = _Listings(), []
    stored = {"listing_id": "L-1", "status": "open", "listing_resource": json.dumps({"product": "Example", "quota": "quota-a"})}

    await _seed([stored], listings, registered).run({"resource_id": "quota-a", "product": "Example"})

    assert (registered, listings.calls) == ([], [])


async def test_no_table_seeds_nothing_and_a_failing_seed_does_not_raise():
    listings, registered = _Listings(), []

    await _seed([], listings, registered).run(None)
    await _seed([], listings, registered).run({"resource_id": "quota-a"})

    assert registered == [{"resource_id": "quota-a", "total_units": 100}]
    assert listings.calls == []


class _AdminClient:
    calls: list[tuple] = []

    def __init__(self, base_url, *, signer, expected_authorities, **_options) -> None:
        self._base_url = base_url

    async def register_resource(self, resource_id, **declaration) -> None:
        self.calls.append((self._base_url, resource_id, declaration))


async def test_a_seeds_quota_is_declared_in_its_pool_under_the_bundles_offering_mode():
    _AdminClient.calls = []
    seed = ListingSeed(
        EXAMPLE,
        sqlite_client=lambda: _Store([]),
        listing_service=lambda: None,
        signer=lambda: object(),
        site=lambda: SimpleNamespace(url="https://quota.example", expected_authorities=None),
        accepted_escrows=lambda table: [],
        settlement_settings=frozenset(),
        pool_id="seeded",
        admin_client=_AdminClient,
    )

    await seed.register_quota(resource_id="quota-a", total_units=9)

    assert _AdminClient.calls == [
        (
            "https://quota.example",
            "quota-a",
            {"pool_id": "seeded", "capacity": {"units": 9}, "resource_type": "example"},
        )
    ]


async def test_a_seeded_listing_past_the_first_page_is_found():
    listings, registered = _Listings(), []
    others = [
        {"listing_id": f"L-{index}", "status": "open", "listing_resource": {"product": "Other"}}
        for index in range(250)
    ]
    seeded = {"listing_id": "L-seeded", "status": "open", "listing_resource": {"product": "Example", "quota": "quota-a"}}

    await _seed([*others, seeded], listings, registered).run({"resource_id": "quota-a", "product": "Example"})

    assert (registered, listings.calls) == ([], [])
