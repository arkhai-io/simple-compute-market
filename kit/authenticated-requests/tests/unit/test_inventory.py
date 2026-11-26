"""The route inventory and the wrapper's guards, over applications whose routes
never reach a store."""

from __future__ import annotations

import asyncio
import re
from typing import Any

import httpx
import pytest
from fastapi import Depends, FastAPI
from market_identity import Ed25519Signer, ExactRetry, TrustedIdentitySet

from market_authenticated_requests import (
    AdmissionCore,
    AuthenticatedApplication,
    RouteAdmission,
    RouteBinding,
    RouteInventoryError,
    RouteNotServed,
    Unauthenticated,
    install,
    undeclared_routes,
)

# A well-known deterministic development key, never for a public network.
SIGNER = Ed25519Signer(bytes(range(32)))


class UnusedStore:
    """A replay store no test here reaches."""

    def __getattr__(self, name: str) -> Any:
        raise AssertionError(f"the store was used: {name}")


def core() -> AdmissionCore:
    return AdmissionCore(
        signer=lambda: SIGNER,
        trust=lambda role: TrustedIdentitySet(identities=(SIGNER.identity,)),
        store=UnusedStore(),  # type: ignore[arg-type]
    )


class OneRouteTable:
    """A middleware-form table binding ``POST /items/{item}/set`` alone."""

    _pattern = re.compile(r"^/items/(?P<item>[^/]+)/set$")

    def resolve(self, method: str, path: str, body: bytes) -> RouteBinding:
        match = self._pattern.fullmatch(path)
        if match is None or method != "POST":
            raise RouteNotServed()
        return RouteBinding("item_set", match["item"], frozenset({"seller"}), ExactRetry.RECORDED)

    def declares(self, method: str, path_template: str) -> bool:
        return (method, path_template) == ("POST", "/items/{item}/set")


def admitted_app(core: AdmissionCore) -> FastAPI:
    app = FastAPI()
    admission = RouteAdmission(core, operation="item_set", roles={"seller"}, exact_retry=ExactRetry.RECORDED)

    @app.post("/items/{item}/set")
    async def item_set(item: str, admitted: object = Depends(admission)) -> None: ...

    return app


def test_a_dependency_form_route_without_a_declaration_refuses_startup_naming_it() -> None:
    app = admitted_app(core())

    @app.post("/forgotten")
    async def forgotten() -> None: ...

    with pytest.raises(RouteInventoryError, match="POST /forgotten") as refused:
        install(app, core())

    assert refused.value.routes == ["POST /forgotten"]


def test_the_middleware_form_table_must_bind_every_application_route() -> None:
    app = FastAPI()

    @app.post("/items/{item}/set")
    async def item_set() -> None: ...

    @app.get("/unbound")
    async def unbound() -> None: ...

    assert undeclared_routes(app, routes=OneRouteTable(), unauthenticated=Unauthenticated.of()) == ["GET /unbound"]
    with pytest.raises(RouteInventoryError, match="GET /unbound"):
        install(app, core(), routes=OneRouteTable())


def test_an_unsigned_time_route_is_marked_and_a_signed_one_declared() -> None:
    authority = core()
    unsigned = FastAPI()

    @unsigned.post("/admin/time")
    async def set_unsigned_time() -> None: ...

    signed = FastAPI()
    admission = RouteAdmission(authority, operation="time_set", roles={"admin"}, exact_retry=ExactRetry.RERUN)

    @signed.post("/admin/time")
    async def set_signed_time(admitted: object = Depends(admission)) -> None: ...

    assert undeclared_routes(unsigned, routes=None, unauthenticated=Unauthenticated.of()) == ["POST /admin/time"]
    install(unsigned, authority, unauthenticated=Unauthenticated.of("/admin/time"))
    install(signed, authority)


def test_a_declaration_without_a_resolution_fails_where_it_is_declared() -> None:
    with pytest.raises(TypeError, match="item_set declares no exact-retry resolution"):
        RouteAdmission(core(), operation="item_set", roles={"seller"}, exact_retry="recorded")  # type: ignore[arg-type]


def test_a_route_admitting_through_a_core_it_is_not_wrapped_in_refuses_to_serve() -> None:
    app = admitted_app(core())

    async def call() -> None:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://authority.test") as client:
            await client.post("/items/a/set")

    with pytest.raises(RuntimeError, match="application wrapper is not installed"):
        asyncio.run(call())


def test_a_caller_leaving_before_its_body_is_whole_is_answered_nothing() -> None:
    reached: list[str] = []
    sent: list[dict[str, Any]] = []

    async def application(scope: Any, receive: Any, send: Any) -> None:
        reached.append(scope["path"])

    wrapped = AuthenticatedApplication(application, core(), routes=None, unauthenticated=Unauthenticated.of())
    messages = [{"type": "http.request", "body": b"{", "more_body": True}, {"type": "http.disconnect"}]

    async def receive() -> dict[str, Any]:
        return messages.pop(0)

    async def send(message: dict[str, Any]) -> None:
        sent.append(message)

    asyncio.run(wrapped({"type": "http", "method": "POST", "path": "/items/a/set", "headers": []}, receive, send))

    assert (reached, sent) == ([], [])


def test_a_route_admitting_through_a_dependency_in_the_middleware_form_is_refused() -> None:
    app = admitted_app(core())

    with pytest.raises(RouteInventoryError, match=r"POST /items/\{item\}/set \(admits through a dependency"):
        install(app, core(), routes=OneRouteTable())
