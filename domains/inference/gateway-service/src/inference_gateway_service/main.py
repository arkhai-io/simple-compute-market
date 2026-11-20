"""The inference gateway's entry point: not ready until its listing loads, then the family gateway.

The process reads the time of the world from one source, installed by
``configured_app`` from ``INFERENCE_GATEWAY_TIME_SOURCE``: ``"wall"`` by default,
``"injected"`` in a lane whose every party shares one time a scenario sets. The
gate signs every call to the inference authority at that source's instant.
Under injected time the gateway serves a time control and status
(``inference_gateway_service.time_control``) behind the bearer token
``INFERENCE_GATEWAY_CONTROL_TOKEN``, ahead of the gate and whether or not the
listing has loaded; a wall-time gateway serves neither.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import Awaitable, Callable
from typing import Any

import httpx
import injected_time
from arkhai_api_gate import GateConfig, PurchasePointer, TokensClient
from arkhai_api_gateway import GatewayOffering, admit_all, create_gateway_app, read_upstream_credential
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from storefront_client.client import StorefrontClient

from inference_gateway_service.config import (
    CONTROL_TOKEN_SETTING,
    TIME_SOURCE_SETTING,
    GatewaySettings,
    gate_config,
)
from inference_gateway_service.offering import OfferingUnavailable, load_offering
from inference_gateway_service.time_control import CONTROL_PATHS, control_app

logger = logging.getLogger(__name__)

Scope = dict[str, Any]
Receive = Callable[[], Awaitable[dict[str, Any]]]
Send = Callable[[dict[str, Any]], Awaitable[None]]


class GatewayService:
    """Answers ``503`` until ``load`` builds the gateway, then serves the gateway.

    The gateway can start before the storefront has published its listing, so
    ``OfferingUnavailable`` is reported by ``/health`` and retried. Any other
    error ends the loading: it is not one waiting can cure.

    ``control`` answers ``control_paths`` whatever the loading's state, so a
    gateway on injected time can be set before its listing is published.
    """

    def __init__(
        self,
        load: Callable[[], Awaitable[FastAPI]],
        *,
        retry_seconds: float,
        control: FastAPI | None = None,
        control_paths: frozenset[str] = frozenset(),
    ) -> None:
        self._load = load
        self._control = control
        self._control_paths = control_paths
        self._retry_seconds = retry_seconds
        self._app: FastAPI | None = None
        self._reason = "the listing has not loaded yet"
        self._loader: asyncio.Task[None] | None = None
        self._running: contextlib.AbstractAsyncContextManager[Any] | None = None
        #: Set once the gateway serves, and once any load is refused.
        self.loaded = asyncio.Event()
        self.refused = asyncio.Event()

    @property
    def ready(self) -> bool:
        return self._app is not None

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "lifespan":
            await self._lifespan(receive, send)
        elif self._control is not None and scope["type"] == "http" and scope["path"] in self._control_paths:
            await self._control(scope, receive, send)
        elif self._app is not None:
            await self._app(scope, receive, send)
        elif scope["type"] == "http":
            response = JSONResponse({"status": "not_ready", "reason": self._reason}, status_code=503)
            await response(scope, receive, send)

    async def _lifespan(self, receive: Receive, send: Send) -> None:
        while True:
            message = await receive()
            if message["type"] == "lifespan.startup":
                self._loader = asyncio.ensure_future(self._load_until_ready())
                await send({"type": "lifespan.startup.complete"})
            elif message["type"] == "lifespan.shutdown":
                try:
                    await self._stop()
                except Exception as error:  # noqa: BLE001 — reported as the shutdown's failure
                    await send({"type": "lifespan.shutdown.failed", "message": repr(error)})
                else:
                    await send({"type": "lifespan.shutdown.complete"})
                return

    async def _load_until_ready(self) -> None:
        while True:
            try:
                app = await self._load()
            except OfferingUnavailable as error:
                self._reason = str(error)
                self.refused.set()
                await asyncio.sleep(self._retry_seconds)
                continue
            except Exception as error:  # noqa: BLE001 — reported by /health, not retried
                logger.exception("the gateway failed to load and will not retry")
                self._reason = f"failed: {error!r}"
                self.refused.set()
                return
            running = app.router.lifespan_context(app)
            await running.__aenter__()
            self._running = running
            self._app = app
            self.loaded.set()
            return

    async def _stop(self) -> None:
        if self._loader is not None and not self._loader.done():
            self._loader.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._loader
        if self._running is not None:
            running, self._running = self._running, None
            await running.__aexit__(None, None, None)


def create_app(
    settings: GatewaySettings | None = None,
    gate: GateConfig | None = None,
    *,
    storefront_transport: httpx.AsyncBaseTransport | None = None,
    authority: TokensClient | None = None,
    http: httpx.AsyncClient | None = None,
    source: injected_time.TimeSource | None = None,
) -> GatewayService:
    """The gateway for the listing ``settings`` names, signing toward its authority as ``service``.

    ``source`` is the time the gateway reads, the process's installed source
    unless given; when it is injected the time control is served, and
    ``settings.control_token`` is required.
    """
    settings = settings or GatewaySettings.from_env()
    gate = gate or gate_config()
    control, control_paths = _time_control(source or injected_time.installed(), settings.control_token)
    # Everything the listing does not supply is checked here, before serving,
    # so a configuration error stops startup rather than every retry.
    if authority is None:
        if not gate.signing_enabled:
            raise ValueError("the gateway signs toward its authority: no identity credential is configured")
        authority = TokensClient(
            service_url=gate.service_url,
            admin_key=gate.admin_key,
            timeout=gate.request_timeout_seconds,
            signing=gate.build_signing(),
        )
    GatewayOffering(
        service=settings.served_model_name,
        scope_service=settings.served_model_name,
        scope_resource_id=settings.resource_id,
        default_charge=0,
        purchase=PurchasePointer(),
        upstream_base_url=settings.upstream_base_url,
    )
    if settings.upstream_credential_file is not None:
        read_upstream_credential(settings.upstream_credential_file)

    async def load() -> FastAPI:
        storefront = StorefrontClient(settings.storefront_url, transport=storefront_transport)
        try:
            offering = await load_offering(settings, storefront)
        finally:
            await storefront.close()
        return create_gateway_app(offering, gate, authority=authority, verification=admit_all, http=http)

    return GatewayService(
        load, retry_seconds=settings.listing_retry_seconds, control=control, control_paths=control_paths,
    )


def _time_control(source: injected_time.TimeSource, token: str | None) -> tuple[FastAPI | None, frozenset[str]]:
    """The time control over an injected ``source`` and the paths it serves; none on wall time."""
    if not injected_time.TimeRouteService(source).settable:
        return None, frozenset()
    if not token:
        raise ValueError(
            f"{CONTROL_TOKEN_SETTING} is required when {TIME_SOURCE_SETTING} is "
            '"injected": the time control is served behind it'
        )
    return control_app(source, token), CONTROL_PATHS


def configured_app() -> GatewayService:
    """The gateway as its environment configures it, its time source installed first.

    Any time source but ``"wall"`` or ``"injected"`` refuses the start, naming
    the setting; an injected source is announced.
    """
    settings = GatewaySettings.from_env()
    source = injected_time.install(injected_time.source_for(settings.time_source, setting=TIME_SOURCE_SETTING))
    if source.name != injected_time.WALL:
        # A warning, so it is shown under the server's default logging.
        logger.warning(
            "%s is %s: the gateway holds %s until its time control sets it",
            TIME_SOURCE_SETTING, source.name, source.now(),
        )
    return create_app(settings, source=source)
