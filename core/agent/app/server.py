# Copyright 2025 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import asyncio
import inspect
import os
import threading
from contextlib import asynccontextmanager

from a2a.server.apps import A2AStarletteApplication
from fastapi import FastAPI

# Import the use_vertex_ai flag and a2a_app from agent.py
from core.agent.app.agent import a2a_app, _startup_tasks, attach_market_routes
from core.agent.app.utils.config import CONFIG


def _route_signature(route) -> tuple[str | None, tuple[str, ...]]:
    return getattr(route, "path", None), tuple(sorted(getattr(route, "methods", []) or ()))


async def _ensure_a2a_routes_bootstrapped() -> None:
    has_root_post = any(
        getattr(route, "path", None) == "/" and "POST" in (getattr(route, "methods", []) or ())
        for route in a2a_app.routes
    )
    if has_root_post:
        return

    for handler in list(getattr(a2a_app.router, "on_startup", ())):
        result = handler()
        if inspect.isawaitable(result):
            await result
        has_root_post = any(
            getattr(route, "path", None) == "/" and "POST" in (getattr(route, "methods", []) or ())
            for route in a2a_app.routes
        )
        if has_root_post:
            return


def _bootstrap_a2a_routes_from_handler_closure() -> bool:
    for handler in list(getattr(a2a_app.router, "on_startup", ())):
        closure = {
            name: cell.cell_contents
            for name, cell in zip(handler.__code__.co_freevars, handler.__closure__ or ())
        }
        setup_app = closure.get("app")
        provided_agent_card = closure.get("provided_agent_card")
        request_handler = closure.get("request_handler")
        if setup_app is not a2a_app or provided_agent_card is None or request_handler is None:
            continue

        A2AStarletteApplication(
            agent_card=provided_agent_card,
            http_handler=request_handler,
        ).add_routes_to_app(setup_app)
        return any(
            getattr(route, "path", None) == "/" and "POST" in (getattr(route, "methods", []) or ())
            for route in a2a_app.routes
        )

    return False


def _run_coro_sync(coro) -> None:
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        asyncio.run(coro)
        return

    error: list[BaseException] = []

    def _runner() -> None:
        try:
            asyncio.run(coro)
        except BaseException as exc:  # pragma: no cover - surfaced synchronously below
            error.append(exc)

    thread = threading.Thread(target=_runner, daemon=True)
    thread.start()
    thread.join()
    if error:
        raise error[0]


def _attach_a2a_routes(app: FastAPI) -> None:
    if not _bootstrap_a2a_routes_from_handler_closure():
        _run_coro_sync(_ensure_a2a_routes_bootstrapped())
    existing = {_route_signature(route) for route in app.routes}
    for route in a2a_app.routes:
        signature = _route_signature(route)
        if signature not in existing:
            app.routes.append(route)
            existing.add(signature)


def _register_startup_hook(app: FastAPI) -> None:
    if getattr(app.state, "_sms_startup_lifespan_registered", False):
        return

    existing_lifespan = app.router.lifespan_context

    @asynccontextmanager
    async def startup_lifespan(app_instance: FastAPI):
        async with existing_lifespan(app_instance):
            await _startup_tasks()
            yield

    app.router.lifespan_context = startup_lifespan
    app.state._sms_startup_lifespan_registered = True


def build_vertex_app(
    *,
    get_fast_api_app_fn,
    google_auth_default_fn,
    logging_client_factory,
    create_bucket_if_not_exists_fn,
    cloud_trace_exporter_cls,
    tracer_provider_cls,
    batch_span_processor_cls,
    trace_module,
    feedback_model_cls,
) -> FastAPI:
    _, project_id = google_auth_default_fn()
    logging_client = logging_client_factory()
    logger = logging_client.logger(__name__)
    allow_origins = (
        os.getenv("ALLOW_ORIGINS", "").split(",")
        if os.getenv("ALLOW_ORIGINS")
        else None
    )

    bucket_name = f"gs://{project_id}-a2a-agent-logs"
    create_bucket_if_not_exists_fn(
        bucket_name=bucket_name, project=project_id, location="asia-southeast1"
    )

    provider = tracer_provider_cls()
    processor = batch_span_processor_cls(cloud_trace_exporter_cls())
    provider.add_span_processor(processor)
    trace_module.set_tracer_provider(provider)

    AGENT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    app: FastAPI = get_fast_api_app_fn(
        agents_dir=AGENT_DIR,
        web=True,
        artifact_service_uri=bucket_name,
        allow_origins=allow_origins,
        session_service_uri=None,
    )
    app.title = "a2a-agent"
    app.description = "API for interacting with the Agent a2a-agent"
    _attach_a2a_routes(app)
    attach_market_routes(app)
    _register_startup_hook(app)

    @app.post("/feedback")
    def collect_feedback(feedback: feedback_model_cls) -> dict[str, str]:
        """Collect and log feedback.

        Args:
            feedback: The feedback data to log

        Returns:
            Success message
        """
        logger.log_struct(feedback.model_dump(), severity="INFO")
        return {"status": "success"}

    return app


def build_local_app() -> FastAPI:
    attach_market_routes(a2a_app)
    _register_startup_hook(a2a_app)
    print("Running in local mode with A2A app (Vertex AI disabled)")
    return a2a_app


# Conditional imports based on use_vertex_ai flag
if CONFIG.use_vertex_ai:
    import google.auth
    from google.adk.cli.fast_api import get_fast_api_app
    from google.cloud import logging as google_cloud_logging
    from opentelemetry import trace
    from opentelemetry.sdk.trace import TracerProvider, export

    from core.agent.app.utils.gcs import create_bucket_if_not_exists
    from core.agent.app.utils.tracing import CloudTraceLoggingSpanExporter
    from core.agent.app.utils.typing import Feedback

    app = build_vertex_app(
        get_fast_api_app_fn=get_fast_api_app,
        google_auth_default_fn=google.auth.default,
        logging_client_factory=google_cloud_logging.Client,
        create_bucket_if_not_exists_fn=create_bucket_if_not_exists,
        cloud_trace_exporter_cls=CloudTraceLoggingSpanExporter,
        tracer_provider_cls=TracerProvider,
        batch_span_processor_cls=export.BatchSpanProcessor,
        trace_module=trace,
        feedback_model_cls=Feedback,
    )
else:
    app = build_local_app()


# Main execution
if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
