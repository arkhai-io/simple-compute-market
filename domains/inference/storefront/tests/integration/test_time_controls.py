"""The inference storefront's time: its time route and its status's time section.

The process's source is installed before the application is built, as the
composition root installs it: an injected source mounts the time-setting route,
a wall source mounts none. Every request goes through the canonical storefront
client, which shares this process's source, so a setting moves both.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager
from typing import Any

import httpx
import injected_time
import pytest
from arkhai_api_selling.migrations import migrate_storefront_database
from injected_time import InjectedTime, TimeSource, WallTime
from market_identity import TrustedIdentitySet
from storefront_client import StorefrontClient
from storefront_client.client import StorefrontClientError

from inference_storefront import server
from inference_storefront.migrate import CHAIN
from tests.integration.conftest import ADMIN_SIGNER, SELLER_SIGNER, app

T = 1794822300


@pytest.fixture
def installed_source() -> Iterator[None]:
    """Restore the process's source after a test installs one."""
    before = injected_time.installed()
    yield
    injected_time.install(before)


@asynccontextmanager
async def _started(
    monkeypatch: pytest.MonkeyPatch, db_path: Any, source: TimeSource
) -> AsyncIterator[StorefrontClient]:
    """The composed storefront, started over ``source``, and its administrator."""

    async def no_startup_tasks(*, domain: Any) -> None:
        return None

    monkeypatch.setattr(server, "_startup_tasks", no_startup_tasks)
    injected_time.install(source)
    migrate_storefront_database(CHAIN, db_path)
    served = app()
    async with served.router.lifespan_context(served):
        async with StorefrontClient(
            "http://seller",
            signer=ADMIN_SIGNER,
            caller_role="admin",
            expected_publishers=TrustedIdentitySet(identities=(SELLER_SIGNER.identity,)),
            transport=httpx.ASGITransport(app=served),
        ) as admin:
            yield admin


async def test_an_injected_storefront_is_set_through_its_route_and_reports_it(
    storefront, registries, monkeypatch, installed_source
):
    async with _started(monkeypatch, storefront, InjectedTime(start=T)) as admin:
        before = await admin.get_system_status()
        answer = await admin.set_time(T + 900)
        after = await admin.get_system_status()
        with pytest.raises(StorefrontClientError) as backward:
            await admin.set_time(T)

    assert before.time == {"source": "injected", "now": T}
    assert (answer.source, answer.now) == ("injected", T + 900)
    assert after.time == {"source": "injected", "now": T + 900}
    assert backward.value.status_code == 409


async def test_a_wall_time_storefront_serves_no_time_route_and_reports_wall(
    storefront, registries, monkeypatch, installed_source
):
    async with _started(monkeypatch, storefront, WallTime()) as admin:
        status = await admin.get_system_status()
        with pytest.raises(StorefrontClientError) as missing:
            await admin.set_time(T)

    assert status.time == {"source": "wall"}
    assert missing.value.status_code == 404
