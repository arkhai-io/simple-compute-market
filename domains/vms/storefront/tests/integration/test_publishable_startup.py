"""The VM storefront refuses to start when it could never publish.

The real app and lifespan compose the storefront from configuration, its signer
from a development credential supplied as the Secret boundary supplies it. Each
case starts from a configuration the storefront can publish under and breaks
one thing; the refusal names it before the storefront opens its database or
starts any loop.
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
from market_storefront.startup_refusal import StorefrontStartupError
from market_storefront.utils import sqlite_client as sqlite_module
from tests.publication_app import _replaced_setting

pytestmark = pytest.mark.asyncio

# Deterministic development keys; never used on any network.
SEED = b"\x76" * 32
SIGNER = Ed25519Signer(SEED)
_REGISTRY = Ed25519Signer(b"\x77" * 32)
_SITE = Ed25519Signer(b"\x78" * 32)
_REGISTRY_URL = "http://registry.test:8080"

_PUBLISHABLE: dict[str, Any] = {
    "enable_registry_discovery": True,
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
        ["no registry to publish to: [registry].urls is empty"],
    ),
    "a registry without its pin": (
        {"registry": {"urls": [_REGISTRY_URL], "authorities": {}}},
        ["[registry].authorities:", _REGISTRY_URL],
    ),
    "no enabled mechanism": (
        {"settlement": {"schema_version": 1, "priority": []}},
        ["no settlement mechanism is enabled under [Settlement]"],
    ),
    "a site with no peer": (
        _identity({}),
        ["site 'default' is bound to no service peer"],
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
        ["site 'default' is bound to 2 service peers"],
    ),
    "the renamed servicing interval": (
        {"claims_sweep_interval": 30},
        ["claims_sweep_interval was renamed settlement_servicing_interval_seconds"],
    ),
}


@pytest.mark.parametrize("case", sorted(_CASES))
async def test_a_storefront_that_cannot_publish_refuses_to_start(
    tmp_path, monkeypatch, case
):
    changes, named = _CASES[case]
    monkeypatch.setenv(
        "ARKHAI_IDENTITY_CREDENTIAL", base64.urlsafe_b64encode(SEED).rstrip(b"=").decode()
    )
    # The process's database client is created by the first startup; this test
    # starts from none and leaves none behind.
    monkeypatch.setattr(sqlite_module, "_sqlite_client", None)
    db_path = tmp_path / "storefront.db"
    app = server.build_vm_storefront_app(
        registry=build_vm_storefront_registry(build_vm_storefront_domain())
    )
    configuration = {**_PUBLISHABLE, **changes, "db_path": str(db_path)}
    with ExitStack() as stack:
        for key, value in configuration.items():
            stack.enter_context(_replaced_setting(key, value))
        with pytest.raises(StorefrontStartupError) as refused:
            async with app.router.lifespan_context(app):
                pass

    for text in named:
        assert text in str(refused.value)
    assert getattr(app.state, "storefront_container", None) is None
    assert sqlite_module._sqlite_client is None
    assert not db_path.exists()
    assert lifecycle.loop_states() == {}
