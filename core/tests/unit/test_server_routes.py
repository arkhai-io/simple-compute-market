from __future__ import annotations

import json
from types import SimpleNamespace

from fastapi import FastAPI
from pydantic import BaseModel
import pytest

from core.agent.app.agent import attach_market_routes
from core.agent.app import server


def _route_paths(app: FastAPI) -> set[str]:
    return {getattr(route, "path", "") for route in app.routes}


def _route_methods_by_path(app: FastAPI) -> dict[str, set[str]]:
    methods_by_path: dict[str, set[str]] = {}
    for route in app.routes:
        path = getattr(route, "path", "")
        methods = set(getattr(route, "methods", []) or [])
        methods_by_path.setdefault(path, set()).update(methods)
    return methods_by_path


def test_attach_market_routes_registers_explicit_market_endpoints() -> None:
    app = FastAPI()

    attach_market_routes(app)
    attach_market_routes(app)

    assert {
        "/alerts/resource",
        "/orders/create",
        "/orders/close",
        "/resources/portfolio",
        "/.well-known/agent-card.json",
        "/.well-known/erc-8004-registration.json",
    }.issubset(_route_paths(app))


def test_build_vertex_app_attaches_market_routes_and_feedback_endpoint() -> None:
    bucket_calls: list[tuple[str, str, str]] = []

    class DummyFeedback(BaseModel):
        message: str

    class DummyLogger:
        def log_struct(self, payload: dict, severity: str) -> None:
            return None

    class DummyLoggingClient:
        def logger(self, name: str) -> DummyLogger:
            return DummyLogger()

    class DummyTracerProvider:
        def add_span_processor(self, processor) -> None:
            return None

    class DummyProcessor:
        def __init__(self, exporter) -> None:
            self.exporter = exporter

    class DummyTraceModule:
        @staticmethod
        def set_tracer_provider(provider) -> None:
            return None

    def fake_get_fast_api_app(**kwargs) -> FastAPI:
        return FastAPI()

    def fake_google_auth_default():
        return object(), "test-project"

    def fake_create_bucket_if_not_exists(*, bucket_name: str, project: str, location: str) -> None:
        bucket_calls.append((bucket_name, project, location))

    app = server.build_vertex_app(
        get_fast_api_app_fn=fake_get_fast_api_app,
        google_auth_default_fn=fake_google_auth_default,
        logging_client_factory=DummyLoggingClient,
        create_bucket_if_not_exists_fn=fake_create_bucket_if_not_exists,
        cloud_trace_exporter_cls=lambda: object(),
        tracer_provider_cls=DummyTracerProvider,
        batch_span_processor_cls=DummyProcessor,
        trace_module=DummyTraceModule,
        feedback_model_cls=DummyFeedback,
    )

    assert {
        "/alerts/resource",
        "/orders/create",
        "/orders/close",
        "/.well-known/agent-card.json",
        "/.well-known/erc-8004-registration.json",
        "/feedback",
    }.issubset(_route_paths(app))
    assert "POST" in _route_methods_by_path(app).get("/", set())
    assert bucket_calls == [("gs://test-project-a2a-agent-logs", "test-project", "asia-southeast1")]


@pytest.mark.asyncio
async def test_build_vertex_app_attaches_a2a_routes_inside_running_event_loop() -> None:
    class DummyFeedback(BaseModel):
        message: str

    class DummyLogger:
        def log_struct(self, payload: dict, severity: str) -> None:
            return None

    class DummyLoggingClient:
        def logger(self, name: str) -> DummyLogger:
            return DummyLogger()

    class DummyTracerProvider:
        def add_span_processor(self, processor) -> None:
            return None

    class DummyProcessor:
        def __init__(self, exporter) -> None:
            self.exporter = exporter

    class DummyTraceModule:
        @staticmethod
        def set_tracer_provider(provider) -> None:
            return None

    def fake_get_fast_api_app(**kwargs) -> FastAPI:
        return FastAPI()

    def fake_google_auth_default():
        return object(), "test-project"

    def fake_create_bucket_if_not_exists(*, bucket_name: str, project: str, location: str) -> None:
        return None

    app = server.build_vertex_app(
        get_fast_api_app_fn=fake_get_fast_api_app,
        google_auth_default_fn=fake_google_auth_default,
        logging_client_factory=DummyLoggingClient,
        create_bucket_if_not_exists_fn=fake_create_bucket_if_not_exists,
        cloud_trace_exporter_cls=lambda: object(),
        tracer_provider_cls=DummyTracerProvider,
        batch_span_processor_cls=DummyProcessor,
        trace_module=DummyTraceModule,
        feedback_model_cls=DummyFeedback,
    )

    assert "POST" in _route_methods_by_path(app).get("/", set())


@pytest.mark.asyncio
async def test_get_resource_portfolio_endpoint_returns_available_resources(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    expected = {
        "resources": [
            {
                "resource_id": "compute-h200-canary-001",
                "resource_type": "compute.gpu",
                "gpu_model": "H200",
                "region": "California, US",
                "quantity": 1,
            }
        ]
    }

    async def fake_get_resource_portfolio() -> dict:
        return expected

    monkeypatch.setattr(
        "core.agent.app.agent.root_agent",
        SimpleNamespace(get_resource_portfolio=fake_get_resource_portfolio),
    )

    response = await __import__("core.agent.app.agent", fromlist=[""]).get_resource_portfolio_endpoint(
        SimpleNamespace()
    )

    assert response.status_code == 200
    assert response.body == (
        b'{"resources":[{"resource_id":"compute-h200-canary-001","resource_type":"compute.gpu",'
        b'"gpu_model":"H200","region":"California, US","quantity":1}]}'
    )


@pytest.mark.asyncio
async def test_registration_file_endpoint_includes_canonical_persisted_onchain_agent_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    agent_module = __import__("core.agent.app.agent", fromlist=[""])
    registry = "0x8004AA63C570C570EBF15376C0DB199918BFE9FB"

    monkeypatch.setattr(
        agent_module,
        "agent_card_data",
        {
            "name": "SMS Canary Seller",
            "description": "A helpful AI assistant designed to trade compute resources with others.",
            "url": "http://10.243.0.68:8000",
            "version": "0.1.0",
            "capabilities": {"streaming": True},
        },
    )
    monkeypatch.setattr(
        agent_module,
        "CONFIG",
        SimpleNamespace(
            chain_rpc_url=None,
            onchain_agent_id=f"eip155:84532:{registry}:2517",
            identity_registry_address=None,
        ),
    )

    response = await agent_module.serve_erc8004_registration_file(SimpleNamespace())
    payload = json.loads(response.body)

    assert response.status_code == 200
    assert payload["registrations"] == [
        {
            "agentId": 2517,
            "agentRegistry": f"eip155:84532:{registry.lower()}",
        }
    ]


def test_attach_a2a_routes_bootstraps_from_handler_closure_without_asyncio_run(monkeypatch) -> None:
    fake_a2a_app = FastAPI()
    request_handler = object()
    provided_agent_card = object()
    app = fake_a2a_app

    async def setup_a2a():
        if provided_agent_card is not None:
            final_agent_card = provided_agent_card
        else:  # pragma: no cover - defensive branch to preserve handler shape
            final_agent_card = await card_builder.build()
        fake_runtime_app = server.A2AStarletteApplication(
            agent_card=final_agent_card,
            http_handler=request_handler,
        )
        fake_runtime_app.add_routes_to_app(app)

    class FakeA2AStarletteApplication:
        def __init__(self, *, agent_card, http_handler) -> None:
            self.agent_card = agent_card
            self.http_handler = http_handler

        def add_routes_to_app(self, app: FastAPI) -> None:
            @app.post("/")
            def root() -> dict[str, str]:
                return {"status": "ok"}

    monkeypatch.setattr(server, "a2a_app", fake_a2a_app)
    monkeypatch.setattr(server, "A2AStarletteApplication", FakeA2AStarletteApplication)
    monkeypatch.setattr(
        server.asyncio,
        "run",
        lambda coro: (_ for _ in ()).throw(AssertionError("asyncio.run should not be used")),
    )

    fake_a2a_app.router.on_startup = [setup_a2a]
    target_app = FastAPI()
    server._attach_a2a_routes(target_app)

    assert server.a2a_app is fake_a2a_app
    assert "POST" in _route_methods_by_path(target_app).get("/", set())
