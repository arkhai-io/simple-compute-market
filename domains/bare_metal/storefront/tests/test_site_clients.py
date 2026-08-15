from __future__ import annotations

import json

import pytest
from market_identity import Identity

from arkhai_bare_metal_storefront.domain_runtime import get_market_domain_contract
from arkhai_bare_metal_storefront.site_clients import (
    BareMetalSiteBinding,
    DurableReservationSiteMap,
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
