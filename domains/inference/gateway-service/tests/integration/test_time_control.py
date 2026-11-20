"""The gateway's time control, and the gate signing at the time it sets.

The gateway is driven in process: its control through the lane doubles' typed
``ControlClient``, a completion through httpx. The inference service is the real
one in the same process, so it reads the source the control sets; the instant is
years from the wall clock, so a gate signing by the wall clock would be refused
for its skew.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import AsyncIterator, Iterator

import httpx
import injected_time
import pytest
from arkhai_api_gate import GateConfig, TokensClient
from injected_time import InjectedTime, InvalidTimeSource, WallTime
from lane_double_controls import ControlClient, ControlError, TimeView

from inference_gateway_service.config import AUTHORITY_LABEL
from inference_gateway_service.main import GatewayService, configured_app, create_app
from tests.cards import QUOTA, SERVED_MODEL, STOREFRONT_URL, UPSTREAM_URL, Storefront, listing, settings
from tests.integration.test_gateway_against_authority import (  # noqa: F401 — `authority` is a fixture
    Upstream,
    _balance,
    _completion,
    _issue,
    _tokens,
    authority,
)

T = 2_000_000_000
HOUR = 3_600
# A public test value, never for a public network.
CONTROL_TOKEN = "inference-gateway-suite-control-token"


@pytest.fixture
def source() -> Iterator[InjectedTime]:
    """The process's source, injected at ``T``: the gate signs by the installed source."""
    before = injected_time.installed()
    held = injected_time.install(InjectedTime(start=T))
    assert isinstance(held, InjectedTime)
    yield held
    injected_time.install(before)


@pytest.fixture
def wall() -> Iterator[WallTime]:
    before = injected_time.installed()
    held = injected_time.install(WallTime())
    assert isinstance(held, WallTime)
    yield held
    injected_time.install(before)


def _unlisted(**fields: str) -> GatewayService:
    """A gateway whose storefront has published no listing, so it never loads."""
    return create_app(
        settings(listing_retry_seconds=0.01, **fields),
        GateConfig(service_url="http://authority.test", authority_label=AUTHORITY_LABEL),
        storefront_transport=httpx.MockTransport(Storefront([]).handle),
        authority=TokensClient(service_url="http://authority.test"),
    )


def _listed(authority_app: object, upstream: Upstream, **fields: str) -> GatewayService:
    """A gateway fronting one listing, charging the inference service ``authority_app``."""
    return create_app(
        settings(listing_retry_seconds=0.01, **fields),
        GateConfig(service_url="http://inference-service", authority_label=AUTHORITY_LABEL),
        storefront_transport=httpx.MockTransport(Storefront([listing("lst-1")]).handle),
        authority=_tokens(httpx.ASGITransport(app=authority_app)),
        http=httpx.AsyncClient(transport=httpx.MockTransport(upstream.handle)),
    )


class Served:
    """A started gateway: its HTTP client, and its control over the same transport."""

    def __init__(self, http: httpx.AsyncClient) -> None:
        self.http = http
        self._loop = asyncio.get_running_loop()

    def _forward(self, request: httpx.Request) -> httpx.Response:
        answer = asyncio.run_coroutine_threadsafe(
            self.http.request(request.method, str(request.url), headers=request.headers, content=request.content),
            self._loop,
        ).result(5)
        return httpx.Response(answer.status_code, headers=answer.headers, content=answer.content)

    async def control(self, call: str, *args: object, token: str = CONTROL_TOKEN) -> TimeView:
        """One call of the typed control client, which is synchronous, off the loop."""

        def run() -> TimeView:
            with ControlClient("http://gateway", token=token, transport=httpx.MockTransport(self._forward)) as client:
                answer = getattr(client, call)(*args)
                return answer.time if call == "status" else answer

        return await asyncio.to_thread(run)


@contextlib.asynccontextmanager
async def _started(service: GatewayService, *, loaded: bool) -> AsyncIterator[Served]:
    inbox: asyncio.Queue[dict] = asyncio.Queue()
    outbox: asyncio.Queue[dict] = asyncio.Queue()
    lifespan = asyncio.ensure_future(service({"type": "lifespan"}, inbox.get, outbox.put))
    await inbox.put({"type": "lifespan.startup"})
    assert (await outbox.get())["type"] == "lifespan.startup.complete"
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=service), base_url="http://gateway") as http:
            await asyncio.wait_for((service.loaded if loaded else service.refused).wait(), 5)
            yield Served(http)
    finally:
        await inbox.put({"type": "lifespan.shutdown"})
        assert (await outbox.get())["type"] == "lifespan.shutdown.complete"
        await lifespan


async def test_the_control_sets_the_gateway_s_time_before_its_listing_loads(source: InjectedTime):
    async with _started(_unlisted(control_token=CONTROL_TOKEN), loaded=False) as served:
        assert (await served.http.get("/health")).status_code == 503
        assert await served.control("status") == TimeView(source="injected", now=T)

        assert await served.control("set_time", T + HOUR) == TimeView(source="injected", now=T + HOUR)

        assert await served.control("status") == TimeView(source="injected", now=T + HOUR)
    assert source.now() == T + HOUR


@pytest.mark.parametrize(("now", "expected"), [
    (T - 1, (409, "time_moves_forward")),
    (True, (422, "invalid_time")),
])
async def test_a_refused_setting_changes_nothing(source: InjectedTime, now: int, expected: tuple[int, str]):
    async with _started(_unlisted(control_token=CONTROL_TOKEN), loaded=False) as served:
        with pytest.raises(ControlError) as refused:
            await served.control("set_time", now)

    assert (refused.value.status, refused.value.code) == expected
    assert source.now() == T


async def test_a_control_call_with_a_wrong_control_token_is_refused(source: InjectedTime):
    async with _started(_unlisted(control_token=CONTROL_TOKEN), loaded=False) as served:
        with pytest.raises(ControlError) as refused:
            await served.control("set_time", T + HOUR, token="not-the-control-token")

    assert (refused.value.status, refused.value.code) == (401, "authentication_required")
    assert source.now() == T


async def test_a_request_is_charged_at_the_instant_the_control_set(authority, source: InjectedTime):  # noqa: F811
    issued = await _issue(authority, quantity=100)
    upstream = Upstream()
    service = _listed(authority, upstream, control_token=CONTROL_TOKEN)

    async with _started(service, loaded=True) as served:
        # The control is not metered: it reaches neither the gate nor the model server.
        await served.control("set_time", T + HOUR)
        response = await served.http.post("/v1/chat/completions", **_completion(issued.secret))

    assert response.status_code == 200
    assert len(upstream.forwarded) == 1
    assert await _balance(authority, issued) == 97


async def test_a_wall_time_gateway_serves_no_time_control(authority, wall: WallTime):  # noqa: F811
    upstream = Upstream()
    service = _listed(authority, upstream)

    async with _started(service, loaded=True) as served:
        with pytest.raises(ControlError) as refused:
            await served.control("set_time", T)

    # The gateway, not a control, answered: it serves no such path.
    assert (refused.value.status, refused.value.code) == (404, "unexpected_response")
    assert upstream.forwarded == []


def test_an_injected_gateway_without_a_control_token_refuses_to_start(source: InjectedTime):
    with pytest.raises(ValueError, match="INFERENCE_GATEWAY_CONTROL_TOKEN"):
        _unlisted()


def _environment(monkeypatch: pytest.MonkeyPatch, **extra: str) -> None:
    for name, value in {
        "STOREFRONT_URL": STOREFRONT_URL, "RESOURCE_ID": QUOTA, "SERVED_MODEL_NAME": SERVED_MODEL,
        "UPSTREAM_BASE_URL": UPSTREAM_URL, "SERVICE_URL": "http://authority.test",
        # A public test seed, never for a public network.
        "IDENTITY_CREDENTIAL": "aW5mZXJlbmNlLWdhdGV3YXktc2VlZC0zMi1ieXRlcyE",
        "AUTHORITY_PRINCIPALS": '[{"scheme":"ed25519","identifier":"nS5GC-Q7uZtXKg2sep2iHsmiDYQEx6KdmME6c4-ah6A"}]',
        **extra,
    }.items():
        monkeypatch.setenv(f"INFERENCE_GATEWAY_{name}", value)


def test_the_configured_gateway_installs_and_announces_injected_time(
    source: InjectedTime, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture,
):
    _environment(monkeypatch, TIME_SOURCE="injected", CONTROL_TOKEN=CONTROL_TOKEN)

    with caplog.at_level(logging.INFO):
        service = configured_app()

    installed = injected_time.installed()
    assert isinstance(installed, InjectedTime) and installed is not source
    assert [record.getMessage() for record in caplog.records] == [
        f"INFERENCE_GATEWAY_TIME_SOURCE is injected: the gateway holds {installed.now()} "
        "until its time control sets it"]
    assert service._control_paths == {"/test/time", "/test/status"}


def test_the_configured_gateway_on_wall_time_serves_no_time_control(
    source: InjectedTime, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture,
):
    _environment(monkeypatch)
    monkeypatch.delenv("INFERENCE_GATEWAY_TIME_SOURCE", raising=False)
    monkeypatch.delenv("INFERENCE_GATEWAY_CONTROL_TOKEN", raising=False)

    with caplog.at_level(logging.INFO):
        service = configured_app()

    assert isinstance(injected_time.installed(), WallTime)
    assert caplog.records == []
    assert (service._control, service._control_paths) == (None, frozenset())


def test_a_misspelled_time_source_refuses_the_start_naming_the_setting(
    source: InjectedTime, monkeypatch: pytest.MonkeyPatch,
):
    _environment(monkeypatch, TIME_SOURCE="injectd")

    with pytest.raises(InvalidTimeSource) as refused:
        configured_app()

    assert str(refused.value) == "INFERENCE_GATEWAY_TIME_SOURCE is \"wall\" or \"injected\", not 'injectd'"
    assert injected_time.installed() is source
