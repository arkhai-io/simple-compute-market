"""The VM storefront's time: its setting, its time route, its status and its warning.

The real app and lifespan compose the storefront from configuration, as
``test_degraded_startup`` does, with its registry, site and chain unreachable,
and every request goes through the canonical storefront client. The process's
source is installed before the application is built, as the composition root
installs it: an injected source mounts the time-setting route, a wall source
mounts none. The client and the storefront share this process's source, so a
setting moves both, and a response signed at the instant set verifies.

Every key, address, and principal here is a deterministic development value,
never used on a public network.
"""

from __future__ import annotations

import base64
import logging
import os
import subprocess
import sys
from contextlib import ExitStack, asynccontextmanager
from unittest.mock import patch

import httpx
import injected_time
import pytest
from injected_time import InjectedTime, WallTime
from market_identity import TrustedIdentitySet
from storefront_client import StorefrontClient
from storefront_client.client import StorefrontClientError

import market_storefront.server as server
from market_storefront.domain_runtime import (
    build_vm_storefront_domain,
    build_vm_storefront_registry,
)
from market_storefront.utils import config as storefront_config
from market_storefront.utils import sqlite_client as sqlite_module
from market_storefront.utils.migrations import migrate_storefront_database
from tests._settings_overrides import replaced_setting
from tests.integration.test_degraded_startup import (
    _CHAINS,
    _CONFIGURATION,
    _SEED,
    ADMIN,
    SIGNER,
    _Chain,
    lifecycle_registry,  # noqa: F401 - a fixture this module's tests take
)

T = 1794822300


class _Recording(httpx.AsyncBaseTransport):
    """The app's transport, keeping each response's signed timestamp."""

    def __init__(self, app) -> None:
        self._inner = httpx.ASGITransport(app=app, raise_app_exceptions=False)
        self.timestamps: list[int] = []

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        response = await self._inner.handle_async_request(request)
        stamp = response.headers.get("X-Market-Timestamp")
        if stamp is not None:
            self.timestamps.append(int(stamp))
        return response


@pytest.fixture
def installed_source():
    """Restore the process's source after a test installs one."""
    before = injected_time.installed()
    yield
    injected_time.install(before)


@asynccontextmanager
async def _started(tmp_path, monkeypatch, *, source, settlement=None):
    """The composed storefront, started over ``source``, and its administrator."""
    monkeypatch.setenv(
        "ARKHAI_IDENTITY_CREDENTIAL", base64.urlsafe_b64encode(_SEED).rstrip(b"=").decode()
    )
    monkeypatch.setattr(sqlite_module, "_sqlite_client", None)
    injected_time.install(source)
    chain = _Chain()
    app = server.build_vm_storefront_app(
        registry=build_vm_storefront_registry(build_vm_storefront_domain()),
        seams=server.VmCompositionSeams(
            alkahest_client_constructor=chain.constructor,
            alkahest_json_rpc=chain.rpc,
        ),
    )
    configuration = {**_CONFIGURATION, "db_path": str(tmp_path / "storefront.db")}
    if settlement is not None:
        configuration["settlement"] = settlement
    migrate_storefront_database(configuration["db_path"])
    transport = _Recording(app)
    with ExitStack() as stack:
        for key, value in configuration.items():
            stack.enter_context(replaced_setting(key, value))
        stack.enter_context(patch.dict(storefront_config.CHAINS, _CHAINS, clear=True))
        async with app.router.lifespan_context(app):
            async with StorefrontClient(
                "http://seller",
                signer=ADMIN,
                caller_role="admin",
                expected_publishers=TrustedIdentitySet(identities=(SIGNER.identity,)),
                transport=transport,
            ) as admin:
                yield admin, transport


async def test_an_injected_storefront_is_set_through_its_route_and_reports_it(
    tmp_path, monkeypatch, lifecycle_registry, installed_source
):
    async with _started(tmp_path, monkeypatch, source=InjectedTime(start=T)) as (
        admin,
        transport,
    ):
        before = await admin.get_system_status()
        answer = await admin.set_time(T + 900)
        signed_at = transport.timestamps[-1]
        after = await admin.get_system_status()
        with pytest.raises(StorefrontClientError) as backward:
            await admin.set_time(T)
        with pytest.raises(StorefrontClientError) as invalid:
            await admin.set_time(True)  # type: ignore[arg-type]
        held = await admin.get_system_status()

    assert before.time == {"source": "injected", "now": T}
    assert (answer.source, answer.now) == ("injected", T + 900)
    assert signed_at == T + 900
    assert after.time == {"source": "injected", "now": T + 900}
    assert transport.timestamps[-1] == T + 900
    assert backward.value.status_code == 409
    assert invalid.value.status_code == 422
    assert held.time == {"source": "injected", "now": T + 900}


async def test_a_wall_time_storefront_serves_no_time_route_and_reports_wall(
    tmp_path, monkeypatch, lifecycle_registry, installed_source
):
    async with _started(tmp_path, monkeypatch, source=WallTime()) as (admin, _):
        status = await admin.get_system_status()
        with pytest.raises(StorefrontClientError) as missing:
            await admin.set_time(T)

    assert status.time == {"source": "wall"}
    assert missing.value.status_code == 404


async def test_an_injected_storefront_announces_its_time_and_warns_beside_live_payments(
    tmp_path, monkeypatch, lifecycle_registry, installed_source, caplog
):
    settlement = {
        **_CONFIGURATION["settlement"],
        "arkhai_payments": {"enabled": False, "livemode": True},
    }
    with caplog.at_level(logging.INFO, logger=server.logger.name):
        async with _started(
            tmp_path, monkeypatch, source=InjectedTime(start=T), settlement=settlement
        ) as (admin, _):
            status = await admin.get_system_status()

    messages = [(record.levelno, record.getMessage()) for record in caplog.records]
    assert status.time == {"source": "injected", "now": T}
    assert any(
        level == logging.INFO and "[Time] source" in text and str(T) in text
        for level, text in messages
    ), messages
    assert any(
        level == logging.WARNING
        and "[Time] source" in text
        and "[Settlement.arkhai_payments] livemode" in text
        for level, text in messages
    ), messages


def test_a_storefront_started_with_a_misspelled_source_refuses_naming_it():
    """The composition root itself, started in a process of its own with
    ``[Time] source`` set through the loader's override layer."""
    started = subprocess.run(
        [sys.executable, "-c", "import market_storefront.server"],
        env={**os.environ, "STOREFRONT_TIME__SOURCE": "injectd"},
        capture_output=True,
        text=True,
        timeout=120,
    )

    assert started.returncode != 0
    assert "InvalidTimeSource" in started.stderr
    assert "[Time] source" in started.stderr and "injectd" in started.stderr
