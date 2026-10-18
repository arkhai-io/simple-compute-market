"""The configuration checks behind the storefront's refusal to start when it
states a retired setting or could never publish, over configuration sources the
tests build."""

from __future__ import annotations

from typing import Any

import pytest
from dynaconf import Dynaconf
from market_identity import Ed25519Signer

from market_storefront.startup_refusal import (
    StorefrontStartupError,
    publication_startup_problems,
    require_publishable_storefront,
    retired_setting_problems,
)
from market_storefront.utils.config import configured_capacity_sites

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


@pytest.mark.parametrize("stated", [True, False])
def test_the_removed_registry_switch_is_refused_and_registries_are_still_checked(
    stated,
) -> None:
    """Stating the switch refuses startup whatever its value, rather than be
    ignored: an operator who turned publication off is not silently switched on.
    The registry checks no longer depend on it."""
    source = _source(
        enable_registry_discovery=stated, registry={"urls": [], "authorities": {}}
    )
    assert retired_setting_problems(source) == [
        "enable_registry_discovery was removed: the storefront always publishes "
        "to every [registry].urls entry, and one that cannot publish refuses to start"
    ]
    assert publication_startup_problems(source) == [
        "no registry to publish to: [registry].urls is empty"
    ]


def test_the_removed_provisioning_trust_set_is_refused() -> None:
    """Each site's responses verify against its own service peer, so a
    configured provisioning trust set would be trust nothing reads."""
    source = _source(
        provisioning={"identity": {"principals": [{"scheme": "ed25519", "identifier": "x"}]}}
    )
    assert retired_setting_problems(source) == [
        "provisioning.identity was removed: every site's responses are verified "
        "against the principals of the [Identity.service_peers] entry bound to "
        "that site, which rotate through the storefront's identity routes"
    ]
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


@pytest.mark.parametrize(
    ("url", "reason"),
    [
        pytest.param("http://home:8081/v1", "without a path", id="a path"),
        pytest.param("http://home:secret", "with a numeric port",
                     id="a port that is not a number"),
        pytest.param("https://user:secret@home:8081", "without credentials",
                     id="credentials"),
        pytest.param("http://home:8081?secret=1", "without a query or fragment",
                     id="a query"),
        pytest.param("home:8081", "its scheme is http or https", id="no scheme"),
        pytest.param("", "its scheme is http or https", id="empty"),
    ],
)
def test_a_site_url_that_is_not_an_http_origin_is_refused_under_its_key(
    url: str, reason: str
) -> None:
    """The site's clients join their routes to its URL, so a path would prefix
    every route and fail only at the first poll; the refusal names the site's
    key and the reason, never the URL."""
    source = _source(
        capacity={"sites": {"home": url, "away": "http://away:8081"}},
    )
    (problem,) = publication_startup_problems(source)
    assert problem.startswith("[capacity.sites.home] must be an HTTP(S) origin")
    assert reason in problem
    assert "secret" not in problem


def test_a_site_url_is_read_as_its_origin() -> None:
    source = _source(
        capacity={"sites": {"home": " http://home:8081/ ", "away": "https://away"}},
    )
    assert configured_capacity_sites(source) == {
        "home": "http://home:8081",
        "away": "https://away",
    }


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


@pytest.mark.parametrize("spelling", ["claims_sweep_interval", "CLAIMS_SWEEP_INTERVAL"])
def test_the_renamed_servicing_interval_is_refused_naming_its_replacement(
    spelling,
) -> None:
    source = _source(**{spelling: 30})
    assert retired_setting_problems(source) == [
        "claims_sweep_interval was renamed settlement_servicing_interval_seconds; "
        "state settlement_servicing_interval_seconds instead"
    ]
    # A retired setting is not a reason the storefront cannot publish.
    assert publication_startup_problems(source) == []
    with pytest.raises(StorefrontStartupError) as refused:
        require_publishable_storefront(source)
    assert str(refused.value).startswith("the storefront states retired settings: ")
    assert "cannot publish" not in str(refused.value)
    assert retired_setting_problems(_source()) == []


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
    retired, publication = message.split(". the storefront cannot publish: ")
    assert retired == (
        "the storefront states retired settings: claims_sweep_interval was renamed "
        "settlement_servicing_interval_seconds; state "
        "settlement_servicing_interval_seconds instead"
    )
    for named in (
        "[registry].urls is empty",
        "no settlement mechanism is enabled",
        "site 'away' is bound to no service peer",
        "site 'home' is bound to no service peer",
    ):
        assert named in publication
