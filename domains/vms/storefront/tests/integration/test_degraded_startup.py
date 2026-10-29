"""The VM storefront starts while its registry, site, and chain refuse connections.

The real app and lifespan compose the storefront from configuration, its signer
from a development credential supplied as the Secret boundary supplies it, and
run every startup step and start every loop. The registry, the provisioning
site, and the provisioning service point at a port nothing listens on, so each
connection is refused. The chain is reached only through the two Alkahest
boundaries the composition root takes as seams -- the SDK's per-chain client
construction and the chain's JSON-RPC endpoint -- which a test double replaces,
refusing until it is switched to answering; the composition itself is not
patched. Nothing waits for a dependency: the storefront answers its health
check, and system status, read through the typed client, reports each
dependency degraded. Of the dependencies, only the chain is brought back here.

Every key, address, and principal here is a deterministic development value,
never used on a public network.
"""

from __future__ import annotations

import asyncio
import base64
import threading
from contextlib import ExitStack
from unittest.mock import patch

import httpx
import pytest
from market_alkahest.dev_chain import anvil_address_book_path
from market_config.config_loader import ChainConfig
from market_identity import Ed25519Signer, TrustedIdentitySet
from storefront_client import StorefrontClient

import market_storefront.server as server
from market_storefront import lifecycle
from market_storefront.domain_runtime import (
    build_vm_storefront_domain,
    build_vm_storefront_registry,
)
from market_storefront.utils import config as storefront_config
from market_storefront.utils import sqlite_client as sqlite_module
from tests._settings_overrides import replaced_setting

pytestmark = pytest.mark.asyncio

_SEED = b"\x79" * 32
SIGNER = Ed25519Signer(_SEED)
ADMIN = Ed25519Signer(b"\x7a" * 32)
_REGISTRY = Ed25519Signer(b"\x7b" * 32)
_SITE = Ed25519Signer(b"\x7c" * 32)

#: Nothing listens on the discard port, so every connection to it is refused.
_REFUSED = "http://127.0.0.1:9"


def _principal(signer: Ed25519Signer) -> dict:
    return signer.identity.model_dump(mode="json")


_CONFIGURATION = {
    "registry": {
        "urls": [_REFUSED],
        "discovery_timeout": 1.0,
        "authorities": {_REFUSED: {"authority": "registry", "principals": [_principal(_REGISTRY)]}},
        # Replaced whole, so the packaged empty write-token table is restated.
        "auth": {},
    },
    "settlement": {
        "schema_version": 1,
        "priority": ["alkahest.v1"],
        "alkahest": {
            "enabled": True,
            "address_books": {"anvil": str(anvil_address_book_path())},
        },
    },
    # Anvil's first published development account, a key and the address it
    # signs as; never use it on a public network.
    "wallet": {
        "address": "0xf39fd6e51aad88f6f4ce6ab8827279cfffb92266",
        "private_key": "0xac0974bec39a17e36ba4a6b4d238ff944bacb478cbed5efcae784d7bf4f2ff80",
    },
    "capacity.sites": {"default": _REFUSED},
    "provisioning.service_url": _REFUSED,
    "identity": {
        "principal": _principal(SIGNER),
        "administrators": {"operator": {"principals": [_principal(ADMIN)]}},
        "service_peers": {
            "provisioning_default": {
                "role": "service",
                "site_id": "default",
                "principals": [_principal(_SITE)],
            }
        },
    },
}
_CHAINS = {"anvil": ChainConfig(name="anvil", rpc_url=_REFUSED, chain_id=31337)}


class _Chain:
    """The chain's JSON-RPC endpoint and the SDK's client construction over it:
    both refuse the connection until ``answering`` is set."""

    def __init__(self) -> None:
        self.answering = False
        self.constructed: list[str] = []

    def rpc(self, rpc_url, method, params, timeout):
        if not self.answering:
            raise ConnectionRefusedError("connection refused")
        return hex(31337) if method == "eth_chainId" else "0x6080"

    def constructor(self, _policy):
        def construct(chain_name: str) -> object:
            if not self.answering:
                raise ConnectionRefusedError("websocket upgrade refused")
            self.constructed.append(chain_name)
            return f"client:{chain_name}"

        return construct


@pytest.fixture
async def lifecycle_registry():
    """A clean loop registry and pause flag, as a fresh process has; every
    timer startup started is cancelled and awaited before the event loop closes."""
    await lifecycle.reset_for_tests()
    yield
    await lifecycle.reset_for_tests()


def _admin(app) -> StorefrontClient:
    return StorefrontClient(
        "http://seller",
        signer=ADMIN,
        caller_role="admin",
        expected_publishers=TrustedIdentitySet(identities=(SIGNER.identity,)),
        transport=httpx.ASGITransport(app=app, raise_app_exceptions=False),
    )


def _alkahest(status) -> dict:
    (alkahest,) = [item for item in status.settlement if item["mechanism"] == "alkahest.v1"]
    return alkahest


async def test_the_storefront_starts_degraded_and_recovers_its_chain_without_a_restart(
    tmp_path, monkeypatch, lifecycle_registry
):
    """Spec scenario "The VM storefront starts before its registry and chain",
    for the start and the chain's recovery; the registry is not brought back."""
    monkeypatch.setenv(
        "ARKHAI_IDENTITY_CREDENTIAL", base64.urlsafe_b64encode(_SEED).rstrip(b"=").decode()
    )
    # The process's database client is created by the first startup; this test
    # starts from none and leaves none behind.
    monkeypatch.setattr(sqlite_module, "_sqlite_client", None)
    chain = _Chain()
    app = server.build_vm_storefront_app(
        registry=build_vm_storefront_registry(build_vm_storefront_domain()),
        seams=server.VmCompositionSeams(
            alkahest_client_constructor=chain.constructor,
            alkahest_json_rpc=chain.rpc,
        ),
    )
    configuration = {**_CONFIGURATION, "db_path": str(tmp_path / "storefront.db")}
    with ExitStack() as stack:
        for key, value in configuration.items():
            stack.enter_context(replaced_setting(key, value))
        stack.enter_context(patch.dict(storefront_config.CHAINS, _CHAINS, clear=True))
        async with app.router.lifespan_context(app):
            async with _admin(app) as admin:
                health = await admin.get_health()
                # Held, so the cycles below are the steps this test runs.
                held = await admin.admin_pause_lifecycle_loops()
                publication = await admin.admin_run_lifecycle_cycle("publication")
                await admin.admin_run_lifecycle_cycle("alkahest-chain-probe")
                degraded = await admin.get_system_status()

                chain.answering = True
                probed = await admin.admin_run_lifecycle_cycle("alkahest-chain-probe")
                recovered = await admin.get_system_status()

    assert health.checks["database"] == "ok"
    assert held["loops"], held
    assert set(held["loops"].values()) == {"paused"}, held

    # The registry is reported failing, and status degraded for it.
    assert degraded.checks["registry"] == "unreachable"
    assert degraded.status == "degraded"
    # The site's projection was never loaded, so its listings are held, not closed.
    families = degraded.site_projections["default"]
    assert families, degraded.site_projections
    assert {family["state"] for family in families.values()} == {"unavailable"}, families
    # Alkahest is unready for reachability alone: the probe could not reach the chain.
    alkahest = _alkahest(degraded)
    assert alkahest["ready"] is False
    assert [(b["code"], b["kind"]) for b in alkahest["blockers"]] == [
        ("alkahest.chain_unreachable", "reachability")
    ]
    # Publication runs, holding the unloaded site's listings rather than closing
    # them: it closes nothing.
    outcome = degraded.lifecycle[lifecycle.PUBLICATION]["last_outcome"]
    assert (outcome["trigger"], outcome["completed"]) == ("step", True), outcome
    assert {"action": "hold", "site_id": "default", "reason": "site_projection_unknown"} in (
        publication["actions"]
    ), publication
    assert "close" not in publication["counts"], publication

    # Once the chain answers, a stepped probe builds the client it could not
    # construct before, and Alkahest is ready with no restart.
    assert probed["probed"] == ["anvil"]
    assert chain.constructed == ["anvil"]
    assert _alkahest(recovered)["ready"] is True
    assert _alkahest(recovered)["public_details"]["chain_probe"]["anvil"]["result"] == "reachable"


async def test_the_storefront_starts_while_a_chain_client_never_finishes_building(
    tmp_path, monkeypatch, lifecycle_registry
):
    """A websocket chain that accepts the connection and never upgrades it holds
    its client's construction for good. Startup constructs no client, so the
    storefront still starts and answers its health check; the probe constructs
    on a thread of its own, and, waiting on it no longer than the RPC timeout,
    reports the chain unreachable while its JSON-RPC answers."""
    monkeypatch.setenv(
        "ARKHAI_IDENTITY_CREDENTIAL", base64.urlsafe_b64encode(_SEED).rstrip(b"=").decode()
    )
    monkeypatch.setattr(sqlite_module, "_sqlite_client", None)
    never_upgraded = threading.Event()
    constructed_on: list[str] = []

    def constructor(_policy):
        def construct(chain_name: str) -> object:
            constructed_on.append(threading.current_thread().name)
            # Only the probe's own construction thread is held: one anywhere
            # else, as startup's would be, fails at once, so the assertion below
            # names it rather than the test hanging.
            if threading.current_thread().name.startswith("alkahest-client-"):
                never_upgraded.wait()
            raise ConnectionError("websocket closed")

        return construct

    def answering(rpc_url, method, params, timeout):
        # The chain's JSON-RPC answers, so only the missing client reads unreachable.
        return hex(31337) if method == "eth_chainId" else "0x6080"

    app = server.build_vm_storefront_app(
        registry=build_vm_storefront_registry(build_vm_storefront_domain()),
        seams=server.VmCompositionSeams(
            alkahest_client_constructor=constructor, alkahest_json_rpc=answering
        ),
    )
    configuration = {
        **_CONFIGURATION,
        "settlement": {
            **_CONFIGURATION["settlement"],
            "alkahest": {
                **_CONFIGURATION["settlement"]["alkahest"],
                "rpc_timeout_seconds": 0.2,
            },
        },
        "db_path": str(tmp_path / "storefront.db"),
    }
    try:
        with ExitStack() as stack:
            for key, value in configuration.items():
                stack.enter_context(replaced_setting(key, value))
            stack.enter_context(patch.dict(storefront_config.CHAINS, _CHAINS, clear=True))
            async with app.router.lifespan_context(app):
                async with _admin(app) as admin:
                    health = await admin.get_health()
                    await admin.admin_pause_lifecycle_loops()
                    await asyncio.wait_for(
                        admin.admin_run_lifecycle_cycle("alkahest-chain-probe"), timeout=5
                    )
                    status = await admin.get_system_status()
    finally:
        never_upgraded.set()

    assert health.checks["database"] == "ok"
    assert constructed_on and all(
        name.startswith("alkahest-client-") for name in constructed_on
    ), constructed_on
    alkahest = _alkahest(status)
    assert alkahest["ready"] is False
    assert [(b["code"], b["kind"]) for b in alkahest["blockers"]] == [
        ("alkahest.chain_unreachable", "reachability")
    ]
