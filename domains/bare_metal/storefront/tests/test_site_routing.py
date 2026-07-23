from __future__ import annotations

import json

import pytest

from arkhai_bare_metal_storefront.domain_runtime import get_market_domain_contract
from arkhai_bare_metal_storefront.site_capacity import BareMetalSiteCapacity
from arkhai_bare_metal_storefront.site_config import parse_trusted_site_bindings
from arkhai_bare_metal_storefront.site_routing import (
    AgreementSiteRouter,
    AgreementSiteRoutingError,
)
from arkhai_bare_metal_storefront.sqlite_client import SQLiteClient


class _Remote:
    def __init__(self, reservation=None) -> None:
        self.reservation = reservation
        self.reserve_calls = 0
        self.commits = []

    async def snapshot(self):
        return []

    async def reserve(self, **_kwargs):
        self.reserve_calls += 1
        return self.reservation

    async def commit(self, **kwargs):
        self.commits.append(kwargs)


def _sites():
    return parse_trusted_site_bindings(json.dumps([
        {
            "site_id": "east",
            "authority_url": "https://east.internal",
            "admin_key": "east-secret",
        },
        {
            "site_id": "west",
            "authority_url": "https://west.internal",
            "admin_key": "west-secret",
        },
    ]))


def _db(tmp_path):
    return SQLiteClient(
        str(tmp_path / "storefront.db"),
        domain=get_market_domain_contract(),
    )


async def test_selected_site_route_survives_restart_and_is_idempotent(tmp_path) -> None:
    east = _Remote()
    west = _Remote({
        "capacity_reservation_id": "reservation-west",
        "resource_id": "machine-west",
    })
    first = AgreementSiteRouter(
        db=_db(tmp_path),
        sites=_sites(),
        capacity=BareMetalSiteCapacity({"east": east, "west": west}),
    )

    selected = await first.reserve_for_agreement(
        negotiation_id="negotiation-1",
        claim={"resource_type": "bare_metal", "units": 1},
    )
    retried = await first.reserve_for_agreement(
        negotiation_id="negotiation-1",
        claim={"resource_type": "bare_metal", "units": 1},
    )

    assert selected is not None
    assert selected.site_id == "west"
    assert selected.capacity_reservation_id == "reservation-west"
    assert retried == selected
    assert east.reserve_calls == 1
    assert west.reserve_calls == 1

    restarted_west = _Remote()
    restarted = AgreementSiteRouter(
        db=_db(tmp_path),
        sites=_sites(),
        capacity=BareMetalSiteCapacity({
            "east": _Remote(),
            "west": restarted_west,
        }),
    )
    loaded = await restarted.load(negotiation_id="negotiation-1")
    routed_client = await restarted.client_for_agreement(
        negotiation_id="negotiation-1",
    )
    committed = await restarted.commit_reservation(
        negotiation_id="negotiation-1",
        idempotency_ref="commit-1",
    )

    assert loaded == selected
    assert routed_client is restarted_west
    assert committed == selected
    assert restarted_west.commits == [{
        "resource_id": "machine-west",
        "capacity_reservation_id": "reservation-west",
        "lease_start_utc": None,
        "lease_end_utc": None,
        "idempotency_ref": "commit-1",
    }]


@pytest.mark.parametrize(
    "claim",
    [
        {"site_id": "east"},
        {"authority_url": "https://buyer.invalid"},
        {"nested": {"service_url": "https://buyer.invalid"}},
        {"credential": "buyer-secret"},
    ],
)
async def test_buyer_routing_material_is_rejected_before_reservation(
    tmp_path,
    claim,
) -> None:
    east = _Remote()
    router = AgreementSiteRouter(
        db=_db(tmp_path),
        sites=_sites(),
        capacity=BareMetalSiteCapacity({"east": east, "west": _Remote()}),
    )

    with pytest.raises(AgreementSiteRoutingError, match="forbidden"):
        await router.reserve_for_agreement(
            negotiation_id="negotiation-untrusted",
            claim=claim,
        )

    assert east.reserve_calls == 0


async def test_conflicting_or_unconfigured_durable_route_fails_closed(tmp_path) -> None:
    db = _db(tmp_path)
    await db.record_agreement_site_route(
        negotiation_id="negotiation-conflict",
        site_id="east",
        capacity_reservation_id="reservation-east",
        reserved_resource_id="resource-east",
    )
    with pytest.raises(ValueError, match="different site"):
        await db.record_agreement_site_route(
            negotiation_id="negotiation-conflict",
            site_id="west",
            capacity_reservation_id="reservation-west",
            reserved_resource_id="resource-west",
        )

    await db.record_agreement_site_route(
        negotiation_id="negotiation-orphan",
        site_id="removed-site",
        capacity_reservation_id="reservation-orphan",
        reserved_resource_id="resource-orphan",
    )
    router = AgreementSiteRouter(
        db=db,
        sites=_sites(),
        capacity=BareMetalSiteCapacity({"east": _Remote(), "west": _Remote()}),
    )
    with pytest.raises(AgreementSiteRoutingError, match="unconfigured site"):
        await router.load(negotiation_id="negotiation-orphan")
