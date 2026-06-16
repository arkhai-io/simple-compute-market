"""A minimal gated service for the e2e topology.

Stands in for "any HTTP API a seller sells metered access to": one
trivial business endpoint (``GET /api/forecast``) behind the
:class:`TokenGateMiddleware`, plus an ungated ``/health``. Every call
to ``/api/*`` spends one credit; a drained key gets a 402 whose body
points back at the listing. The gate config comes entirely from
``APITOKENS_MIDDLEWARE_*`` env vars so the container is configured the
same way the storefront and service are.
"""

from __future__ import annotations

from fastapi import FastAPI

from apitokens_middleware import GateConfig, TokenGate, TokenGateMiddleware


def create_app(
    config: GateConfig | None = None, *, gate: TokenGate | None = None,
) -> FastAPI:
    """Build the gated app.

    ``config`` (default: from ``APITOKENS_MIDDLEWARE_*`` env) configures
    the gate. Tests pass a pre-built ``gate`` wired to a scripted tokens
    service so they exercise the real app without a live service.
    """
    config = config or GateConfig.from_env()
    app = FastAPI(title="apitokens-sample-app")

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/api/forecast")
    def forecast() -> dict[str, str]:
        """The metered endpoint — one credit per call."""
        return {"forecast": "sunny", "high_c": "24", "low_c": "13"}

    # Gate everything except the excluded paths. Added last so it wraps
    # the routes above.
    kwargs = {"gate": gate} if gate is not None else {"config": config}
    app.add_middleware(
        TokenGateMiddleware,
        exclude_paths=("/health", "/docs", "/openapi.json", "/redoc"),
        **kwargs,
    )
    return app


app = create_app()


def main() -> None:
    """Console-script entry point: serve under uvicorn."""
    import os

    import uvicorn

    uvicorn.run(
        "apitokens_sample_app.app:app",
        host=os.environ.get("APITOKENS_SAMPLE_APP_HOST", "0.0.0.0"),
        port=int(os.environ.get("APITOKENS_SAMPLE_APP_PORT", "8085")),
        log_level=os.environ.get("APITOKENS_SAMPLE_APP_LOG_LEVEL", "info"),
    )


if __name__ == "__main__":
    main()
