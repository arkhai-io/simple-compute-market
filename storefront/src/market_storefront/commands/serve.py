"""Run the storefront HTTP server in-process via uvicorn."""

from __future__ import annotations


def run_serve(host: str = "0.0.0.0", port: int | None = None) -> None:
    import uvicorn

    from market_storefront.server import app
    from market_storefront.utils.config import CONFIG

    uvicorn.run(app, host=host, port=port if port is not None else CONFIG.port)
