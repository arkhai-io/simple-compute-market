"""The registry's time: its setting, its administrator time route and status.

Application integration: the running registry, in process, through the canonical
`RegistryClient`, whose administrator calls send the shared bearer key the
registry's `/admin` routes require. The client and the registry read this
process's one time source, so a setting moves both. The registry mounts its time
route only when its source is injected when it is imported, which this suite's
process is not, so an injected test mounts the route on the suite's app as the
registry would; once mounted, the route sets nothing under wall time and answers
404, as the unmounted route's absence does.
"""

from __future__ import annotations

import os
import subprocess
import sys
from datetime import datetime, timezone

import injected_time
import pytest
from injected_time import InjectedTime, WallTime
from registry_client import ListingRequest, RegistryClientError
from starlette.routing import Match

from core_registry.api.admin_routes import make_time_router
from core_registry.config import settings
from core_registry.db.models import Listing
from core_registry.main import api

T = 1794822300
ADMIN_KEY = "admin-token"  # A development fixture; never a deployment's key.


def _mount_time_route() -> None:
    """Mount the time route on the suite's app once, as an injected registry does."""
    scope = {"type": "http", "path": "/admin/time", "method": "POST", "root_path": ""}
    if not any(route.matches(scope)[0] is Match.FULL for route in api.routes):
        api.include_router(make_time_router())


@pytest.fixture(autouse=True)
def admin_key(monkeypatch):
    monkeypatch.setattr(settings, "admin_api_key", ADMIN_KEY)


@pytest.fixture
def installed_source():
    """Restore the process source after a test installs its own."""
    before = injected_time.installed()
    yield
    injected_time.install(before)


@pytest.fixture
def injected_source(installed_source):
    source = InjectedTime(start=T)
    injected_time.install(source)
    _mount_time_route()
    return source


async def test_an_injected_registry_is_set_through_its_route_and_reports_it(
    registry_client, injected_source
):
    before = await registry_client.get_admin_status(admin_key=ADMIN_KEY)
    answer = await registry_client.set_time(T + 1800, admin_key=ADMIN_KEY)
    after = await registry_client.get_admin_status(admin_key=ADMIN_KEY)
    with pytest.raises(RegistryClientError) as backward:
        await registry_client.set_time(T, admin_key=ADMIN_KEY)
    with pytest.raises(RegistryClientError) as invalid:
        await registry_client.set_time(True, admin_key=ADMIN_KEY)  # type: ignore[arg-type]
    held = await registry_client.get_admin_status(admin_key=ADMIN_KEY)

    assert before.time == {"source": "injected", "now": T}
    assert (answer.source, answer.now) == ("injected", T + 1800)
    assert after.time == {"source": "injected", "now": T + 1800}
    assert backward.value.status_code == 409
    assert '"code":"time_moves_forward"' in backward.value.body
    assert invalid.value.status_code == 422
    assert '"code":"invalid_time"' in invalid.value.body
    assert held.time == {"source": "injected", "now": T + 1800}


@pytest.mark.parametrize("key", ("", "wrong-token"))
async def test_a_setting_without_the_administrator_key_is_refused_unchanged(
    registry_client, injected_source, key
):
    with pytest.raises(RegistryClientError) as refused:
        await registry_client.set_time(T + 1800, admin_key=key)
    with pytest.raises(RegistryClientError) as unread:
        await registry_client.get_admin_status(admin_key=key)

    assert refused.value.status_code == 401
    assert unread.value.status_code == 401
    assert injected_source.now() == T


async def test_a_wall_time_registry_sets_no_time_and_reports_wall(
    registry_client, installed_source
):
    injected_time.install(WallTime())

    status = await registry_client.get_admin_status(admin_key=ADMIN_KEY)
    with pytest.raises(RegistryClientError) as missing:
        await registry_client.set_time(T, admin_key=ADMIN_KEY)

    assert status.time == {"source": "wall"}
    assert missing.value.status_code == 404


async def test_a_publication_signed_after_an_advance_is_accepted(
    registry_client, injected_source, db_session
):
    """`registry-discovery`'s "A storefront publishes after an advance": the
    registry and the storefront set to one instant 1800 s on, the storefront's
    publication, signed at that instant, is accepted."""
    await registry_client.set_time(T + 1800, admin_key=ADMIN_KEY)

    await registry_client.publish_listing(
        ListingRequest(
            listing_id="after-advance",
            listing_resource={"gpu_model": "H200", "region": "us-west", "offering_mode": "vm"},
            accepted_escrows=[
                {
                    "chain_name": "anvil",
                    # Development fixture addresses; never used on a public network.
                    "escrow_address": "0x" + "11" * 20,
                    "literal_fields": {"token": "0x" + "22" * 20},
                }
            ],
            storefront_url="http://seller",
        )
    )

    db_session.expire_all()
    listing = db_session.get(Listing, "after-advance")
    # The registry stores times as UTC with no zone.
    assert listing.created_at == datetime.fromtimestamp(T + 1800, timezone.utc).replace(
        tzinfo=None
    )


@pytest.mark.parametrize(("source", "mounted"), (("injected", "True"), ("wall", "False")))
def test_the_composition_mounts_the_time_route_only_under_injected_time(source, mounted):
    """The composition root itself, started in a process of its own with
    ``TIME_SOURCE`` set: its app serves ``POST /admin/time`` only when injected."""
    started = subprocess.run(
        [
            sys.executable,
            "-c",
            "import core_registry.main as m; "
            "print(any(getattr(r, 'path', None) == '/admin/time' for r in m.api.routes))",
        ],
        env={**os.environ, "TIME_SOURCE": source},
        capture_output=True,
        text=True,
        timeout=120,
    )

    assert started.returncode == 0, started.stderr
    assert started.stdout.strip().splitlines()[-1] == mounted


def test_a_registry_started_with_a_misspelled_source_refuses_naming_it():
    """The composition root itself, started in a process of its own with
    ``TIME_SOURCE`` set in its environment."""
    started = subprocess.run(
        [sys.executable, "-c", "import core_registry.main"],
        env={**os.environ, "TIME_SOURCE": "injectd"},
        capture_output=True,
        text=True,
        timeout=120,
    )

    assert started.returncode != 0
    assert "InvalidTimeSource: TIME_SOURCE is \"wall\" or \"injected\", not 'injectd'" in (
        started.stderr
    )
