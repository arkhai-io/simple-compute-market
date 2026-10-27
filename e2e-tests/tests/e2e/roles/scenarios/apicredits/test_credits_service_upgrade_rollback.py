"""Upgrade and rollback of the API-credits service against a retained database.

Probe services run behind the shared-secret gate, started through the engine
socket the lane mounts; a missing prerequisite fails the scenario.
"""

from __future__ import annotations

import logging
import time
import uuid
from collections.abc import Iterator
from typing import Any

import httpx
import pytest
from arkhai_api.issuance import KeyDisposition, issuance_request
from arkhai_api_client import AuthorityClient
from arkhai_apicredits.label import API_CREDITS_LABEL
from market_identity import Identity

from tests.e2e.roles.scenarios.apicredits.conftest import lane_setting

log = logging.getLogger(__name__)

pytestmark = pytest.mark.e2e_credits_service_rollback

_DATA_DIR = "/app/data"
_APP_UID = "1000"
_SERVICE_PORT = 8082
_HEALTH_TIMEOUT = 90.0

# Deterministic development principal; never used on any network.
BUYER = Identity(scheme="eip191", identifier="0xabcdef0000000000000000000000000000000001")



@pytest.fixture(scope="module")
def engine():
    try:
        import docker
        from docker.errors import DockerException
    except ImportError:  # pragma: no cover - the e2e image installs it
        pytest.fail("the docker SDK is not installed in the test image")
    try:
        client = docker.from_env()
        client.ping()
    except DockerException as exc:
        pytest.fail(f"the Docker engine is not reachable from the test container: {exc}")
    return client


@pytest.fixture(scope="module")
def images(engine) -> dict[str, str]:
    from docker.errors import ImageNotFound

    tags = {
        "current": lane_setting("API_CREDITS.SERVICE_IMAGE"),
        "prekit": lane_setting("API_CREDITS.SERVICE_PREKIT_IMAGE"),
    }
    for name, tag in tags.items():
        try:
            engine.images.get(tag)
        except ImageNotFound:
            pytest.fail(
                f"the {name} API-credits service image {tag!r} is not built; "
                "the lane builds it with `make build-e2e-apicredits`"
            )
    return tags


@pytest.fixture(scope="module")
def lane(engine) -> dict[str, str]:
    from docker.errors import NotFound

    network = lane_setting("API_CREDITS.LANE_NETWORK")
    volume = lane_setting("API_CREDITS.SERVICE_VOLUME")
    try:
        engine.networks.get(network)
        engine.volumes.get(volume)
    except NotFound as exc:
        pytest.fail(f"the API-credit lane is not up as configured: {exc}")
    return {"network": network, "volume": volume}


class Probes:

    def __init__(self, engine, images: dict[str, str], lane: dict[str, str]) -> None:
        self._engine = engine
        self._images = images
        self._lane = lane
        self._run = uuid.uuid4().hex[:8]
        self._volumes: list[Any] = []
        self._containers: list[Any] = []

    def fresh_volume(self) -> str:
        volume = self._engine.volumes.create(name=f"e2e-credits-rollback-{self._run}-{len(self._volumes)}")
        self._volumes.append(volume)
        return volume.name

    def copy_of(self, source_volume: str) -> str:
        target = self.fresh_volume()
        backup = (
            "import sqlite3; "
            "src = sqlite3.connect('file:/src/apicredits.db?mode=ro', uri=True); "
            "dst = sqlite3.connect('/dst/apicredits.db'); "
            "src.backup(dst); dst.close(); src.close()"
        )
        self._engine.containers.run(
            self._images["current"],
            command=["sh", "-c", f"python -c \"{backup}\" && chown -R {_APP_UID}:{_APP_UID} /dst"],
            user="root",
            entrypoint=[],
            volumes={
                source_volume: {"bind": "/src", "mode": "ro"},
                target: {"bind": "/dst", "mode": "rw"},
            },
            remove=True,
        )
        return target

    def start(self, image_key: str, volume: str) -> "Service":
        name = f"e2e-credits-{image_key}-{self._run}-{len(self._containers)}"
        admin_key = lane_setting("API_CREDITS.ADMIN_KEY")
        container = self._engine.containers.run(
            self._images[image_key],
            name=name,
            detach=True,
            network=self._lane["network"],
            environment={
                "APICREDITS_STOREFRONT_ADMIN_KEY": admin_key,
                "APICREDITS_DATABASE_URL": f"sqlite:///{_DATA_DIR}/apicredits.db",
            },
            volumes={volume: {"bind": _DATA_DIR, "mode": "rw"}},
        )
        self._containers.append(container)
        service = Service(container, f"http://{name}:{_SERVICE_PORT}", admin_key)
        service.wait_until_serving()
        return service

    def stop(self, service: "Service") -> None:
        service.container.stop(timeout=20)

    def close(self) -> None:
        for container in self._containers:
            try:
                container.remove(force=True)
            except Exception as exc:  # noqa: BLE001 - best-effort cleanup
                log.warning("could not remove %s: %s", container.name, exc)
        for volume in self._volumes:
            try:
                volume.remove(force=True)
            except Exception as exc:  # noqa: BLE001 - best-effort cleanup
                log.warning("could not remove volume %s: %s", volume.name, exc)


class Service:

    def __init__(self, container: Any, url: str, admin_key: str) -> None:
        self.container = container
        self.url = url
        self._admin_key = admin_key

    def wait_until_serving(self) -> None:
        deadline = time.monotonic() + _HEALTH_TIMEOUT
        last = "no answer"
        while time.monotonic() < deadline:
            self.container.reload()
            if self.container.status == "exited":
                break
            try:
                response = httpx.get(f"{self.url}/health", timeout=5.0)
                if response.status_code == 200:
                    return
                last = f"HTTP {response.status_code}"
            except httpx.HTTPError as exc:
                last = f"{type(exc).__name__}: {exc}"
            time.sleep(1.0)
        logs = self.container.logs(tail=80).decode("utf-8", "replace")
        pytest.fail(
            f"{self.container.name} ({self.container.image.tags}) did not serve within "
            f"{_HEALTH_TIMEOUT}s ({last}); its last log lines:\n{logs}"
        )

    def client(self):
        return AuthorityClient(self.url, self._admin_key, label=API_CREDITS_LABEL)

    def route_surface(self) -> dict[str, list[str]]:
        document = httpx.get(f"{self.url}/openapi.json", timeout=10.0)
        assert document.status_code == 200, document.text
        return {
            path: sorted(method.upper() for method in operations)
            for path, operations in document.json()["paths"].items()
        }

    def register_quota(self, resource_id: str, units: int) -> None:
        # Raw call: the typed capacity client only signs.
        response = httpx.put(
            f"{self.url}/api/v1/capacity/resources/{resource_id}",
            json={"total_units": units, "resource_type": "api.credits", "pool_id": "default"},
            headers={"X-Admin-Key": self._admin_key},
            timeout=10.0,
        )
        assert response.status_code < 400, response.text

    async def grants(self) -> dict[str, Any]:
        client = self.client()
        keys = (await client.list_keys())["keys"]
        recorded: dict[str, Any] = {}
        for key in sorted(keys, key=lambda k: k["key_id"]):
            grants = (await client.list_key_grants(key["key_id"]))["grants"]
            issuances = {}
            for grant in grants:
                fulfillment_id = grant.get("fulfillment_id")
                if fulfillment_id:
                    issuance = await client.get_issuance(fulfillment_id)
                    assert issuance is not None, fulfillment_id
                    issuances[fulfillment_id] = issuance.model_dump(mode="json")
            recorded[key["key_id"]] = {"key": key, "grants": grants, "issuances": issuances}
        return recorded


@pytest.fixture(scope="module")
def probes(engine, images, lane) -> Iterator[Probes]:
    started = Probes(engine, images, lane)
    try:
        yield started
    finally:
        started.close()


def _issuance(negotiation_id: str, quantity: int, *, existing_key: str | None = None):
    return issuance_request(
        API_CREDITS_LABEL,
        negotiation_id=negotiation_id,
        owner=BUYER,
        service="weather-api",
        resource_id="rollback-quota",
        quantity=quantity,
        key=(
            KeyDisposition(mode="existing", key_id=existing_key)
            if existing_key
            else KeyDisposition(mode="new")
        ),
    )



@pytest.fixture(scope="module")
def live_route_surface() -> dict[str, list[str]]:
    url = lane_setting("API_CREDITS.SERVICE_URL").rstrip("/")
    document = httpx.get(f"{url}/openapi.json", timeout=10.0)
    assert document.status_code == 200, document.text
    return {
        path: sorted(method.upper() for method in operations)
        for path, operations in document.json()["paths"].items()
    }


async def test_rollback_the_prekit_image_reads_what_the_current_image_wrote(
    probes: Probes, lane: dict[str, str], live_route_surface
):
    copied = probes.copy_of(lane["volume"])

    current = probes.start("current", copied)
    written = await current.grants()
    assert written, "the lane's database holds no key; the deal scenarios wrote none"
    assert current.route_surface() == live_route_surface
    probes.stop(current)

    prekit = probes.start("prekit", copied)
    assert prekit.route_surface() == live_route_surface
    assert await prekit.grants() == written
    probes.stop(prekit)


async def test_upgrade_the_current_image_reads_what_the_prekit_image_wrote(
    probes: Probes, live_route_surface
):
    volume = probes.fresh_volume()

    prekit = probes.start("prekit", volume)
    prekit.register_quota("rollback-quota", units=100)
    first = _issuance("neg-rollback-1", 5)
    issued = await prekit.client().submit_issuance(first)
    topped = await prekit.client().submit_issuance(
        _issuance("neg-rollback-2", 3, existing_key=issued.key_id)
    )
    assert (issued.balance, topped.balance) == (5, 8)
    written = await prekit.grants()
    assert prekit.route_surface() == live_route_surface
    probes.stop(prekit)

    current = probes.start("current", volume)
    assert current.route_surface() == live_route_surface
    assert await current.grants() == written

    retried = await current.client().submit_issuance(first)
    assert retried.already_issued is True
    assert retried.key_id == issued.key_id
    assert retried.fulfillment_id == issued.fulfillment_id
    assert retried.request_digest == issued.request_digest
    assert (await current.client().get_key(issued.key_id))["balance"] == 8
    assert (await current.client().list_key_grants(issued.key_id))["total"] == 2
    probes.stop(current)
