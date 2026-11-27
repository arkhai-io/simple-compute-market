"""The offering's validation and the gate configuration it projects."""

from __future__ import annotations

from pathlib import Path

import pytest

from arkhai_api_gate import GateConfig, PurchasePointer
from arkhai_api_gateway import GatewayOffering, read_upstream_credential


def _offering(**overrides: object) -> GatewayOffering:
    values: dict[str, object] = {
        "service": "served-model",
        "scope_service": "served-model",
        "scope_resource_id": "quota-1",
        "default_charge": 4,
        "purchase": PurchasePointer(storefront_url="http://storefront"),
        "upstream_base_url": "http://model/v1",
    }
    values.update(overrides)
    return GatewayOffering(**values)  # type: ignore[arg-type]


def test_an_offering_names_a_service() -> None:
    with pytest.raises(ValueError, match="service"):
        _offering(service="")


@pytest.mark.parametrize(
    "scope",
    [
        {"scope_service": ""},
        {"scope_resource_id": ""},
        {"scope_service": None},
        {"scope_resource_id": None},
    ],
)
def test_an_offering_scopes_both_service_and_resource_or_neither(scope: dict) -> None:
    with pytest.raises(ValueError, match="both service and resource"):
        _offering(**scope)
    assert _offering(scope_service=None, scope_resource_id=None).scope_service is None


def test_an_offerings_default_charge_is_non_negative() -> None:
    with pytest.raises(ValueError, match="non-negative"):
        _offering(default_charge=-1)
    assert _offering(default_charge=0).default_charge == 0


@pytest.mark.parametrize(
    ("url", "match"),
    [
        ("model/v1", "absolute"),
        ("//model/v1", "absolute"),
        ("ftp://model/v1", "absolute"),
        ("http:///v1", "absolute"),
        ("http://model:port/v1", "malformed"),
        ("http://user:pass@model/v1", "credentials"),
        ("http://token@model/v1", "credentials"),
        ("http://model/v1?key=value", "query or fragment"),
        ("http://model/v1?", "query or fragment"),
        ("http://model/v1#part", "query or fragment"),
    ],
)
def test_an_unusable_upstream_base_url_is_refused(url: str, match: str) -> None:
    with pytest.raises(ValueError, match=match):
        _offering(upstream_base_url=url)


@pytest.mark.parametrize(
    "url",
    [
        "http://model",
        "http://model/",
        "http://model/v1",
        "http://model/v1/",
        "https://model.example:8443/v1",
        "http://127.0.0.1:8000/v1",
    ],
)
def test_an_absolute_http_upstream_base_url_is_accepted(url: str) -> None:
    assert _offering(upstream_base_url=url).upstream_base_url == url


def test_the_gate_is_configured_from_the_offering() -> None:
    base = GateConfig(service_url="http://authority", authority_label="authority")

    config = _offering().gate_config(base)

    assert config.scope_service == "served-model"
    assert config.scope_resource_id == "quota-1"
    assert config.amount_per_request == 4
    assert config.purchase == PurchasePointer(storefront_url="http://storefront")
    assert config.service_url == "http://authority"


def test_an_upstream_credential_is_read_stripped(tmp_path: Path) -> None:
    path = tmp_path / "credential"
    path.write_text("secret\n", encoding="utf-8")

    assert read_upstream_credential(path) == "secret"


def test_an_empty_upstream_credential_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "credential"
    path.write_text("\n", encoding="utf-8")

    with pytest.raises(ValueError, match="empty"):
        read_upstream_credential(path)
