"""The VM storefront refuses to start when it states a retired setting or could
never publish, and starts when its terms live in its pools.

The real app and lifespan compose the storefront from configuration, its signer
from a development credential supplied as the Secret boundary supplies it. Each
refused case starts from a configuration the storefront can publish under and
breaks one thing; the refusal names it under its heading before the storefront
opens its database or starts any loop.
"""

from __future__ import annotations

import base64
from contextlib import ExitStack
from typing import Any

import pytest
from market_identity import Ed25519Signer

import market_storefront.server as server
from market_storefront import lifecycle
from market_storefront.domain_runtime import (
    build_vm_storefront_domain,
    build_vm_storefront_registry,
)
from market_storefront.startup_refusal import (
    CANNOT_PUBLISH_HEADING,
    RETIRED_SETTINGS_HEADING,
    StorefrontStartupError,
)
from market_storefront.utils import sqlite_client as sqlite_module
from tests._settings_overrides import replaced_setting

pytestmark = pytest.mark.asyncio

# Deterministic development keys; never used on any network.
SEED = b"\x76" * 32
SIGNER = Ed25519Signer(SEED)
_REGISTRY = Ed25519Signer(b"\x77" * 32)
_SITE = Ed25519Signer(b"\x78" * 32)
_REGISTRY_URL = "http://registry.test:8080"

_PUBLISHABLE: dict[str, Any] = {
    "registry": {
        "urls": [_REGISTRY_URL],
        "discovery_timeout": 5.0,
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
    "capacity.sites": {"default": "http://site.test:8081"},
}
_PEER = {
    "role": "service",
    "site_id": "default",
    "principals": [_SITE.identity.model_dump(mode="json")],
}


def _identity(peers: dict[str, Any]) -> dict[str, Any]:
    # Replaced at its root: an empty table set on a dotted key leaves the
    # previous one in place.
    return {
        "identity": {
            "principal": SIGNER.identity.model_dump(mode="json"),
            "service_peers": peers,
        }
    }


_PUBLISHABLE.update(_identity({"provisioning_default": _PEER}))

_CASES = {
    "no registry": (
        {"registry": {"urls": [], "authorities": {}}},
        [CANNOT_PUBLISH_HEADING, "no registry to publish to: [registry].urls is empty"],
    ),
    "a registry without its pin": (
        {"registry": {"urls": [_REGISTRY_URL], "authorities": {}}},
        [CANNOT_PUBLISH_HEADING, "[registry].authorities:", _REGISTRY_URL],
    ),
    "no enabled mechanism": (
        {"settlement": {"schema_version": 1, "priority": []}},
        [CANNOT_PUBLISH_HEADING, "no settlement mechanism is enabled under [Settlement]"],
    ),
    "a site with no peer": (
        _identity({}),
        [CANNOT_PUBLISH_HEADING, "site 'default' is bound to no service peer"],
    ),
    "a site with two peers": (
        _identity(
            {
                "provisioning_default": _PEER,
                "provisioning_twin": {
                    **_PEER,
                    "principals": [_REGISTRY.identity.model_dump(mode="json")],
                },
            }
        ),
        [CANNOT_PUBLISH_HEADING, "site 'default' is bound to 2 service peers"],
    ),
    "the renamed servicing interval": (
        {"claims_sweep_interval": 30},
        [
            RETIRED_SETTINGS_HEADING,
            "claims_sweep_interval was renamed settlement_servicing_interval_seconds",
        ],
    ),
    "the removed registry switch": (
        {"enable_registry_discovery": False},
        [RETIRED_SETTINGS_HEADING, "enable_registry_discovery was removed"],
    ),
    "the removed provisioning trust set": (
        # Replaced at its root, so the retired table is gone again afterwards.
        {"provisioning": {"identity": {"principals": [_SITE.identity.model_dump(mode="json")]}}},
        [RETIRED_SETTINGS_HEADING, "provisioning.identity was removed"],
    ),
    "the removed provisioning preflight": (
        # Replaced at its root, so the retired keys are gone again afterwards.
        {
            "provisioning": {
                "service_url": "http://site.test:8081",
                "fail_on_unreachable": False,
                "preflight_timeout": 30,
            }
        },
        [
            RETIRED_SETTINGS_HEADING,
            "provisioning.fail_on_unreachable was removed",
            "provisioning.preflight_timeout was removed",
        ],
    ),
}


def _signer_credential(monkeypatch) -> None:
    monkeypatch.setenv(
        "ARKHAI_IDENTITY_CREDENTIAL", base64.urlsafe_b64encode(SEED).rstrip(b"=").decode()
    )


@pytest.mark.parametrize("case", sorted(_CASES))
async def test_a_storefront_that_cannot_start_names_why(tmp_path, monkeypatch, case):
    changes, named = _CASES[case]
    _signer_credential(monkeypatch)
    db_path = tmp_path / "storefront.db"
    app = server.build_vm_storefront_app(
        registry=build_vm_storefront_registry(build_vm_storefront_domain())
    )
    configuration = {**_PUBLISHABLE, **changes, "db_path": str(db_path)}
    with ExitStack() as stack:
        for key, value in configuration.items():
            stack.enter_context(replaced_setting(key, value))
        with pytest.raises(StorefrontStartupError) as refused:
            async with app.router.lifespan_context(app):
                pass

    message = str(refused.value)
    for text in named:
        assert text in message
    retired = RETIRED_SETTINGS_HEADING in message
    assert (CANNOT_PUBLISH_HEADING in message) is not retired, message
    assert getattr(app.state, "storefront_container", None) is None
    assert not db_path.exists()
    assert lifecycle.loop_states() == {}


async def test_a_storefront_whose_terms_live_in_its_pools_starts(tmp_path, monkeypatch):
    """Spec scenario "A storefront's terms live in its pools": with no
    storefront-wide settlement clause the refusal passes and the lifespan opens
    the storefront's database. It stops at the next startup check, an unusable
    poll interval, because the steps after it reach the provisioning service and
    the sites; whether such a storefront publishes is
    tests/integration/test_pool_overrides_api.py's."""
    _signer_credential(monkeypatch)
    # The process's database client is created by the first startup that gets
    # this far and is not the lifespan's to clear; this test starts from none.
    monkeypatch.setattr(sqlite_module, "_sqlite_client", None)
    db_path = tmp_path / "storefront.db"
    app = server.build_vm_storefront_app(
        registry=build_vm_storefront_registry(build_vm_storefront_domain())
    )
    configuration = {
        **_PUBLISHABLE,
        "pricing": {"settlements": []},
        "capacity": {"sites": {"default": "http://site.test:8081"}, "poll_interval": 0},
        "db_path": str(db_path),
    }
    with ExitStack() as stack:
        for key, value in configuration.items():
            stack.enter_context(replaced_setting(key, value))
        with pytest.raises(ValueError, match=r"capacity\.poll_interval"):
            async with app.router.lifespan_context(app):
                pass

    assert db_path.exists()
    assert getattr(app.state, "storefront_container", None) is None
    assert lifecycle.loop_states() == {}
