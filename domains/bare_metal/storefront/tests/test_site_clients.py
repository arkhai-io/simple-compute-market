from __future__ import annotations

import json
from types import SimpleNamespace

import pytest
from market_identity import Identity

from arkhai_bare_metal_storefront.domain_runtime import get_market_domain_contract
from arkhai_bare_metal_storefront.site_clients import (
    BareMetalSiteBinding,
    DurableReservationSiteMap,
    SelectedSiteFulfillmentClient,
    parse_site_bindings,
)
from arkhai_bare_metal_storefront.sqlite_client import SQLiteClient


PRINCIPAL = {
    "scheme": "eip191",
    "identifier": "0x1111111111111111111111111111111111111111",
}


def _bindings_json() -> str:
    return json.dumps(
        [
            {
                "site_id": "site-a",
                "authority_url": "https://provisioning.internal:8443",
                "authority_principal": PRINCIPAL,
            }
        ]
    )


def test_site_binding_diagnostics_redact_routing_url() -> None:
    binding = parse_site_bindings(_bindings_json())[0]
    assert binding.diagnostic() == {
        "site_id": "site-a",
        "authority_principal": PRINCIPAL,
    }
    assert "provisioning.internal" not in repr(binding)
    assert "authority_url" not in binding.diagnostic()


@pytest.mark.parametrize(
    "payload",
    [
        "not-json",
        "[]",
        json.dumps(
            [
                {
                    "site_id": "site-a",
                    "authority_url": "https://user:secret@example.test",
                    "authority_principal": PRINCIPAL,
                }
            ]
        ),
        json.dumps(
            [
                {
                    "site_id": "site-a",
                    "authority_url": "https://user:secret＠example.test",
                    "authority_principal": PRINCIPAL,
                }
            ]
        ),
        json.dumps(
            [
                {
                    "site_id": "site-a",
                    "authority_url": "https://one.example.test",
                    "authority_principal": PRINCIPAL,
                },
                {
                    "site_id": "site-a",
                    "authority_url": "https://two.example.test",
                    "authority_principal": PRINCIPAL,
                },
            ]
        ),
    ],
)
def test_invalid_site_bindings_fail_closed_without_echoing_payload(payload: str) -> None:
    with pytest.raises(ValueError) as raised:
        parse_site_bindings(payload)
    assert "secret" not in str(raised.value)
    assert "one.example.test" not in str(raised.value)


def test_selected_site_binding_survives_restart_and_rejects_authority_rotation(
    tmp_path,
) -> None:
    db_path = str(tmp_path / "storefront.db")
    SQLiteClient(
        db_path,
        domain=get_market_domain_contract(),
    )
    binding = BareMetalSiteBinding(
        site_id="site-a",
        authority_url="https://one.example.test",
        authority_principal=Identity.model_validate(PRINCIPAL),
    )
    routes = DurableReservationSiteMap(db_path, {"site-a": binding})
    routes["reservation-1"] = "site-a"

    restarted = DurableReservationSiteMap(db_path, {"site-a": binding})
    assert restarted == {"reservation-1": "site-a"}

    replacement = BareMetalSiteBinding(
        site_id="site-a",
        authority_url="https://two.example.test",
        authority_principal=Identity.model_validate(
            {
                "scheme": "eip191",
                "identifier": "0x2222222222222222222222222222222222222222",
            }
        ),
    )
    with pytest.raises(RuntimeError, match="site authority changed"):
        DurableReservationSiteMap(db_path, {"site-a": replacement})


class _RecordingFulfillmentClient:
    def __init__(self, site_id: str) -> None:
        self.site_id = site_id
        self.calls = []

    async def schedule_resource(self, request):
        self.calls.append(("schedule", request.capacity_reservation_id))
        return self.site_id

    async def begin_fulfillment(self, request):
        self.calls.append(("begin", request.capacity_reservation_id))
        return self.site_id

    async def get_fulfillment_status(self, fulfillment_id):
        self.calls.append(("status", fulfillment_id))
        return self.site_id

    async def get_fulfillment_result(self, fulfillment_id):
        self.calls.append(("result", fulfillment_id))
        return self.site_id

    async def begin_fulfillment_teardown(self, fulfillment_id):
        self.calls.append(("teardown", fulfillment_id))
        return self.site_id


async def test_every_fulfillment_verb_routes_to_persisted_site_after_restart(
    tmp_path,
) -> None:
    db_path = str(tmp_path / "storefront.db")
    SQLiteClient(db_path, domain=get_market_domain_contract())
    bindings = {
        site_id: BareMetalSiteBinding(
            site_id=site_id,
            authority_url=f"https://{site_id}.example.test",
            authority_principal=Identity.model_validate(PRINCIPAL),
        )
        for site_id in ("site-a", "site-b")
    }
    first_routes = DurableReservationSiteMap(db_path, bindings)
    first_routes["reservation-b"] = "site-b"

    restarted_routes = DurableReservationSiteMap(db_path, bindings)
    clients = {
        site_id: _RecordingFulfillmentClient(site_id)
        for site_id in bindings
    }
    fulfillment = SelectedSiteFulfillmentClient(clients, restarted_routes)
    request = SimpleNamespace(capacity_reservation_id="reservation-b")

    assert await fulfillment.schedule_resource(request) == "site-b"
    assert await fulfillment.begin_fulfillment(request) == "site-b"
    assert (
        await fulfillment.get_fulfillment_status(
            "fulfillment-b",
            capacity_reservation_id="reservation-b",
        )
        == "site-b"
    )
    assert (
        await fulfillment.get_fulfillment_result(
            "fulfillment-b",
            capacity_reservation_id="reservation-b",
        )
        == "site-b"
    )
    assert (
        await fulfillment.begin_fulfillment_teardown(
            "fulfillment-b",
            capacity_reservation_id="reservation-b",
        )
        == "site-b"
    )

    assert clients["site-a"].calls == []
    assert clients["site-b"].calls == [
        ("schedule", "reservation-b"),
        ("begin", "reservation-b"),
        ("status", "fulfillment-b"),
        ("result", "fulfillment-b"),
        ("teardown", "fulfillment-b"),
    ]


def test_reservation_site_binding_is_immutable(tmp_path) -> None:
    db_path = str(tmp_path / "storefront.db")
    SQLiteClient(db_path, domain=get_market_domain_contract())
    bindings = {
        site_id: BareMetalSiteBinding(
            site_id=site_id,
            authority_url=f"https://{site_id}.example.test",
            authority_principal=Identity.model_validate(PRINCIPAL),
        )
        for site_id in ("site-a", "site-b")
    }
    routes = DurableReservationSiteMap(db_path, bindings)
    routes["reservation-1"] = "site-a"

    with pytest.raises(RuntimeError, match="conflicts with its persisted"):
        routes["reservation-1"] = "site-b"

    assert routes["reservation-1"] == "site-a"
    assert DurableReservationSiteMap(db_path, bindings) == {
        "reservation-1": "site-a"
    }
