"""The gateway application: an OpenAI version-1 style front for one model.

A gated request runs model check, key verification, hook, charge, forward: the
model is checked before anything is charged, and the hook runs before the
charge so a refusal costs the buyer nothing.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response

from arkhai_api_gate import GateConfig, GateDecision, TokenGate, TokensClient

from .offering import GatewayOffering, read_upstream_credential
from .proxy import forward
from .verification import VerificationHook, admit_all

INVALID_REQUEST = "invalid_request"
MODEL_NOT_FOUND = "model_not_found"

# Generation can pause between tokens for longer than a connect or write
# should take, so only the read is given long.
_UPSTREAM_TIMEOUT = httpx.Timeout(10.0, read=300.0)


def create_gateway_app(
    offering: GatewayOffering,
    gate_config: GateConfig,
    *,
    authority: TokensClient | None = None,
    verification: VerificationHook = admit_all,
    http: httpx.AsyncClient | None = None,
) -> FastAPI:
    """The gateway for ``offering``, gated at the authority ``gate_config`` names.

    The gate is built here from ``offering.gate_config(gate_config)``, so its
    scope, default charge, and purchase pointer are always the offering's.
    ``authority`` defaults to a signed client built from that configuration.
    The upstream credential and the signing context are resolved here, so a
    missing secret or a missing or unusable signing credential fails at startup.
    """
    config = offering.gate_config(gate_config)
    if authority is None:
        if not config.signing_enabled:
            raise ValueError("a gateway signs toward its authority: no signing credential is configured")
        authority = TokensClient(
            service_url=config.service_url,
            admin_key=config.admin_key,
            timeout=config.request_timeout_seconds,
            signing=config.build_signing(),
        )
    gate = TokenGate(config, authority)
    credential = (
        read_upstream_credential(offering.upstream_credential_file)
        if offering.upstream_credential_file is not None
        else None
    )
    owns_http = http is None
    upstream = http or httpx.AsyncClient(timeout=_UPSTREAM_TIMEOUT)
    base_url = offering.upstream_base_url.rstrip("/")

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        gate.start()
        try:
            yield
        finally:
            try:
                await gate.aclose()
            finally:
                if owns_http:
                    await upstream.aclose()

    app = FastAPI(title="api-gateway", lifespan=lifespan)

    async def gated(request: Request, path: str) -> Response:
        body = await request.body()
        refused = _model_refusal(body, offering.service)
        if refused is not None:
            return refused
        verified = await gate.verify(request.headers.get("authorization"))
        if isinstance(verified, GateDecision):
            return _decision_response(verified)
        refusal = await verification(
            offering.current_terms, verified.accepted_terms, verified.terms_digest,
        )
        if refusal is not None:
            return JSONResponse({"error": refusal.error}, status_code=refusal.status)
        decision = await gate.charge(verified)
        if not decision.allowed:
            return _decision_response(decision)
        return await forward(
            upstream, base_url + path, body, httpx.Headers(request.headers.raw), credential,
        )

    @app.post("/v1/chat/completions")
    async def chat_completions(request: Request) -> Response:
        return await gated(request, "/chat/completions")

    @app.post("/v1/completions")
    async def completions(request: Request) -> Response:
        return await gated(request, "/completions")

    @app.get("/v1/models")
    async def models() -> dict[str, Any]:
        # Ungated: the listing already publishes what is for sale.
        return {"object": "list", "data": [{"id": offering.service, "object": "model"}]}

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    return app


def _model_refusal(body: bytes, service: str) -> Response | None:
    """A refusal for a body that is not a JSON object naming ``service`` as its model."""
    try:
        payload = json.loads(body)
    except ValueError:
        payload = None
    if not isinstance(payload, dict) or not isinstance(payload.get("model"), str):
        return JSONResponse({"error": INVALID_REQUEST}, status_code=400)
    if payload["model"] != service:
        return JSONResponse({"error": MODEL_NOT_FOUND}, status_code=404)
    return None


def _decision_response(decision: GateDecision) -> Response:
    return JSONResponse(decision.body or {}, status_code=decision.status)
