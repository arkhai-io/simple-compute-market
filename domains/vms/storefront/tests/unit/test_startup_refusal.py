"""The configuration checks behind the storefront's refusal to start when it
could never publish, over configuration sources the tests build."""

from __future__ import annotations

from typing import Any

import pytest
from dynaconf import Dynaconf
from market_identity import Ed25519Signer

from market_storefront.startup_refusal import (
    StorefrontStartupError,
    publication_startup_problems,
    require_publishable_storefront,
)

# Deterministic development keys; never used on a public network.
_REGISTRY = Ed25519Signer(b"\x71" * 32)
_HOME_SITE = Ed25519Signer(b"\x72" * 32)
_AWAY_SITE = Ed25519Signer(b"\x73" * 32)
_REGISTRY_URL = "http://registry.test:8080"


def _peer(site_id: str, signer: Ed25519Signer) -> dict[str, Any]:
    return {
        "role": "service",
        "site_id": site_id,
        "principals": [signer.identity.model_dump(mode="json")],
    }


def _source(**changes: Any) -> Dynaconf:
    """A configuration the storefront can publish under, with ``changes``."""
    values: dict[str, Any] = {
        "enable_registry_discovery": True,
        "registry": {
            "urls": [_REGISTRY_URL],
            "authorities": {
                _REGISTRY_URL: {
                    "authority": "registry",
                    "principals": [_REGISTRY.identity.model_dump(mode="json")],
                }
            },
        },
        "settlement": {
            "schema_version": 1,
            "priority": ["alkahest.v1"],
            "alkahest": {"enabled": True},
        },
        "capacity": {"sites": {"home": "http://home:8081", "away": "http://away:8081"}},
        "identity": {
            "service_peers": {
                "home-peer": _peer("home", _HOME_SITE),
                "away-peer": _peer("away", _AWAY_SITE),
            }
        },
        "pricing": {"settlements": []},
    }
    values.update(changes)
    source = Dynaconf(environments=False)
    for key, value in values.items():
        source.set(key, value)
    return source


def test_a_storefront_whose_terms_live_in_its_pools_is_not_refused() -> None:
    """No storefront-wide settlement clause is configured; pools supply them."""
    assert publication_startup_problems(_source()) == []
    require_publishable_storefront(_source())


def test_no_registry_is_refused() -> None:
    source = _source(registry={"urls": [], "authorities": {}})
    assert publication_startup_problems(source) == [
        "no registry to publish to: [registry].urls is empty"
    ]


def test_a_registry_without_its_authority_pin_is_refused() -> None:
    source = _source(registry={"urls": [_REGISTRY_URL], "authorities": {}})
    (problem,) = publication_startup_problems(source)
    assert problem.startswith("[registry].authorities:")
    assert _REGISTRY_URL in problem


def test_registries_are_not_checked_while_publication_to_them_is_off() -> None:
    source = _source(
        enable_registry_discovery=False, registry={"urls": [], "authorities": {}}
    )
    assert publication_startup_problems(source) == []


def test_no_enabled_settlement_mechanism_is_refused() -> None:
    for settlement in (
        {"schema_version": 1, "priority": []},
        {"schema_version": 1, "priority": [], "alkahest": {"enabled": False}},
    ):
        assert publication_startup_problems(_source(settlement=settlement)) == [
            "no settlement mechanism is enabled under [Settlement]"
        ]


def test_no_configured_site_is_refused() -> None:
    (problem,) = publication_startup_problems(_source(capacity={"sites": {}}))
    assert "[capacity.sites]" in problem


def test_a_site_bound_to_no_service_peer_or_to_two_is_refused() -> None:
    source = _source(
        capacity={
            "sites": {
                "home": "http://home:8081",
                "away": "http://away:8081",
                "lonely": "http://lonely:8081",
            }
        },
        identity={
            "service_peers": {
                "home-peer": _peer("home", _HOME_SITE),
                "away-peer": _peer("away", _AWAY_SITE),
                "away-twin": _peer("away", _REGISTRY),
            }
        },
    )
    (problem,) = publication_startup_problems(source)
    assert "site 'lonely' is bound to no service peer" in problem
    assert "site 'away' is bound to 2 service peers" in problem
    assert "'home'" not in problem


def test_the_renamed_servicing_interval_is_refused_naming_its_replacement() -> None:
    assert publication_startup_problems(_source(claims_sweep_interval=30)) == [
        "claims_sweep_interval was renamed settlement_servicing_interval_seconds; "
        "state settlement_servicing_interval_seconds instead"
    ]


def test_every_problem_is_named_in_one_refusal() -> None:
    source = _source(
        claims_sweep_interval=30,
        registry={"urls": [], "authorities": {}},
        settlement={"schema_version": 1, "priority": []},
        identity={"service_peers": {}},
    )
    with pytest.raises(StorefrontStartupError) as refused:
        require_publishable_storefront(source)
    message = str(refused.value)
    assert message.startswith("the storefront cannot publish: ")
    for named in (
        "claims_sweep_interval was renamed",
        "[registry].urls is empty",
        "no settlement mechanism is enabled",
        "site 'away' is bound to no service peer",
        "site 'home' is bound to no service peer",
    ):
        assert named in message
