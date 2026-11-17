"""The bare-metal storefront's time: its setting, its time route, its status and its warning.

The composed application runs its own lifespan over a runtime the test builds,
and every request goes through the canonical storefront client, as the VM
storefront's are: the route, its signed operation and its answers are the same
on both. The process's source is installed before the application is built, as
the composition root installs it: an injected source mounts the time-setting
route, a wall source mounts none. The client and the storefront share this
process's source, so a setting moves both, and a response signed at the instant
set verifies.
"""

from __future__ import annotations

import dataclasses
import logging
import os
import subprocess
import sys
from contextlib import asynccontextmanager

import httpx
import injected_time
import pytest
from injected_time import InjectedTime, WallTime
from market_identity import Ed25519Signer, TrustedIdentitySet
from storefront_client import StorefrontClient
from storefront_client.client import StorefrontClientError

from arkhai_bare_metal_storefront import server
from test_http_system import ADMIN_SIGNER, SELLER_SIGNER, _app, _runtime

T = 1794822300


class _Recording(httpx.AsyncBaseTransport):
    """The app's transport, keeping each response's signed timestamp."""

    def __init__(self, app) -> None:
        self._inner = httpx.ASGITransport(app=app)
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
async def _started(tmp_path, *, source, payments_livemode=False):
    """The composed storefront, started over ``source``, and its administrator."""
    injected_time.install(source)
    runtime = dataclasses.replace(
        _runtime(str(tmp_path / "storefront.db")), payments_livemode=payments_livemode
    )
    app = _app(runtime)
    transport = _Recording(app)
    async with app.router.lifespan_context(app):
        async with StorefrontClient(
            "http://seller",
            signer=ADMIN_SIGNER,
            caller_role="admin",
            expected_publishers=TrustedIdentitySet(identities=(SELLER_SIGNER.identity,)),
            transport=transport,
        ) as admin:
            yield admin, transport


async def test_an_injected_storefront_is_set_through_its_route_and_reports_it(
    tmp_path, installed_source
) -> None:
    async with _started(tmp_path, source=InjectedTime(start=T)) as (admin, transport):
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


async def test_the_time_route_refuses_a_principal_it_does_not_trust(
    tmp_path, installed_source
) -> None:
    async with _started(tmp_path, source=InjectedTime(start=T)) as (admin, transport):
        async with StorefrontClient(
            "http://seller",
            signer=Ed25519Signer(b"\x5e" * 32),
            caller_role="admin",
            expected_publishers=TrustedIdentitySet(identities=(SELLER_SIGNER.identity,)),
            transport=transport,
        ) as stranger:
            with pytest.raises(StorefrontClientError) as refused:
                await stranger.set_time(T + 900)
        status = await admin.get_system_status()

    assert refused.value.status_code == 403
    assert status.time == {"source": "injected", "now": T}


async def test_a_wall_time_storefront_serves_no_time_route_and_reports_wall(
    tmp_path, installed_source
) -> None:
    async with _started(tmp_path, source=WallTime()) as (admin, _):
        status = await admin.get_system_status()
        with pytest.raises(StorefrontClientError) as missing:
            await admin.set_time(T)

    assert status.time == {"source": "wall"}
    assert missing.value.status_code == 404


async def test_an_injected_storefront_announces_its_time_and_warns_beside_live_payments(
    tmp_path, installed_source, caplog
) -> None:
    with caplog.at_level(logging.INFO, logger=server.logger.name):
        async with _started(
            tmp_path, source=InjectedTime(start=T), payments_livemode=True
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


def test_a_storefront_started_with_a_misspelled_source_refuses_naming_it() -> None:
    """The composition root itself, started in a process of its own with
    ``[Time] source`` set through the loader's override layer."""
    started = subprocess.run(
        [sys.executable, "-c", "import arkhai_bare_metal_storefront.server"],
        env={**os.environ, "STOREFRONT_TIME__SOURCE": "injectd"},
        capture_output=True,
        text=True,
        timeout=120,
    )

    assert started.returncode != 0
    assert "InvalidTimeSource" in started.stderr
    assert "[Time] source" in started.stderr and "injectd" in started.stderr
