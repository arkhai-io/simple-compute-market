"""A toy authority in either form, over a real SQLite database, and a signing caller.

The toy holds one integer per item. ``POST /items/{item}/set`` sets it outright
and is recorded; ``POST /items/{item}/raise`` raises it to at least the value
sent and re-runs, since an old retry of it changes nothing; ``GET /items/{item}``
reads it. ``POST /fail`` and ``POST /fail-again`` raise after writing, recorded
and re-run. ``POST /slow`` waits for the test before answering. ``POST
/admin/time`` sets the injected time and re-runs. ``GET /health`` is
unauthenticated. Every write counts its dispatches.
"""

from __future__ import annotations

import asyncio
import json
import re
import sqlite3
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx
import injected_time
from fastapi import Depends, FastAPI, Request
from market_identity import (
    Ed25519Signer,
    ExactRetry,
    MarketRequest,
    RequestBinding,
    Signer,
    TrustedIdentitySet,
    sign_market_request,
    verify_market_response,
)
from market_schema_migrations import Chain, Migration, SqliteMigrationConnection, migrate

from market_authenticated_requests import (
    SQLITE_REPLAY_TABLE_MIGRATION,
    AdmissionCore,
    Admitted,
    AuthenticatedRequestsSettings,
    ResourceUnbound,
    RouteAdmission,
    RouteBinding,
    RouteNotServed,
    SignedOutcome,
    Unauthenticated,
    install,
    path_resource,
    sqlite_replay_store,
)

START = 1_800_000_000
SKEW = 300
LEASE = 30
RETENTION = 3_600

# Well-known deterministic development keys, never for a public network.
AUTHORITY_SEED = bytes(range(32))
ROTATED_AUTHORITY_SEED = bytes(range(1, 33))
STRANGER_SEED = bytes(range(2, 34))

SELLER = frozenset({"seller"})
ADMIN = frozenset({"admin"})


def _create_items(connection: sqlite3.Connection) -> None:
    connection.execute("CREATE TABLE items (item TEXT PRIMARY KEY, value INTEGER NOT NULL)")


def migrated_database(path: Path) -> Path:
    """A database built by a chain composing the kit's replay-table migration."""

    chain = Chain(
        service="toy authority",
        command="toy-migrate",
        baselines=(Migration("toy_0001_items", _create_items),),
        migrations=(SQLITE_REPLAY_TABLE_MIGRATION,),
    )
    connection = sqlite3.connect(path)
    try:
        migrate(chain, SqliteMigrationConnection(connection))
    finally:
        connection.close()
    return path


@dataclass
class Toy:
    """The toy's domain: its database, and the test's controls over its handlers."""

    database: Path
    dispatches: dict[str, int] = field(default_factory=dict)
    slow_started: asyncio.Event = field(default_factory=asyncio.Event)
    slow_finish: asyncio.Event = field(default_factory=asyncio.Event)
    retries: list[bool] = field(default_factory=list)

    def count(self, operation: str) -> None:
        self.dispatches[operation] = self.dispatches.get(operation, 0) + 1

    def connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.database)

    def write(self, item: str, value: int, *, at_least: bool) -> int:
        with self.connect() as connection:
            row = connection.execute("SELECT value FROM items WHERE item = ?", (item,)).fetchone()
            current = None if row is None else int(row[0])
            new = max(current or 0, value) if at_least else value
            connection.execute("INSERT OR REPLACE INTO items (item, value) VALUES (?, ?)", (item, new))
        return new

    def read(self, item: str) -> int | None:
        with self.connect() as connection:
            row = connection.execute("SELECT value FROM items WHERE item = ?", (item,)).fetchone()
        return None if row is None else int(row[0])

    def items(self) -> dict[str, int]:
        with self.connect() as connection:
            return {str(item): int(value) for item, value in connection.execute("SELECT item, value FROM items")}


@dataclass(frozen=True)
class Route:
    method: str
    template: str
    operation: str
    roles: frozenset[str]
    exact_retry: ExactRetry
    resource_param: str | None = None

    @property
    def pattern(self) -> re.Pattern[str]:
        return re.compile("^" + re.sub(r"\{(\w+)\}", r"(?P<\1>[^/]+)", self.template) + "$")


ROUTES = (
    Route("POST", "/items/{item}/set", "item_set", SELLER | ADMIN, ExactRetry.RECORDED, "item"),
    Route("POST", "/items/{item}/raise", "item_raise", SELLER, ExactRetry.RERUN, "item"),
    Route("GET", "/items/{item}", "item_read", SELLER, ExactRetry.RERUN, "item"),
    Route("POST", "/fail", "fail_recorded", SELLER, ExactRetry.RECORDED),
    Route("POST", "/fail-again", "fail_rerun", SELLER, ExactRetry.RERUN),
    Route("POST", "/slow", "slow_recorded", SELLER, ExactRetry.RECORDED),
    Route("POST", "/admin/time", "time_set", ADMIN, ExactRetry.RERUN),
)


class Table:
    """The middleware form's contract table over :data:`ROUTES`."""

    def __init__(self, routes: tuple[Route, ...] = ROUTES) -> None:
        self._routes = routes

    def resolve(self, method: str, path: str, body: bytes) -> RouteBinding:
        allowed = set()
        for route in self._routes:
            match = route.pattern.fullmatch(path)
            if match is None:
                continue
            if route.method != method:
                allowed.add(route.method)
                continue
            if route.operation == "time_set" and "now" not in json.loads(body or b"{}"):
                raise ResourceUnbound("now is required")
            resource = match.group(route.resource_param) if route.resource_param else ""
            return RouteBinding(route.operation, resource, route.roles, route.exact_retry)
        raise RouteNotServed(allowed_methods=allowed)

    def declares(self, method: str, path_template: str) -> bool:
        return any(r.method == method and r.template == path_template for r in self._routes)


def time_document_resource(path_params: dict[str, str], body: bytes) -> str:
    """The time route binds no resource, but refuses a body that carries no instant."""

    if "now" not in json.loads(body or b"{}"):
        raise ResourceUnbound("now is required")
    return ""


def build_app(toy: Toy, core: AdmissionCore, *, form: str, extra: list[Route] | None = None) -> Any:
    """The toy's FastAPI application, wrapped by the core in ``form``."""

    app = FastAPI()

    def admitted(route: Route) -> Any:
        if form != "dependency":
            # The middleware form leaves the admitted request in the request's state.
            async def from_state(request: Request) -> Admitted:
                return request.state.authenticated_request

            return Depends(from_state)
        resource = path_resource(route.resource_param) if route.resource_param else None
        if route.operation == "time_set":
            resource = time_document_resource
        return Depends(
            RouteAdmission(
                core, operation=route.operation, roles=route.roles, exact_retry=route.exact_retry, resource=resource
            )
        )

    set_route, raise_route, read_route, fail_route, fail_again_route, slow_route, time_route = ROUTES

    @app.post("/items/{item}/set")
    async def item_set(item: str, request: Request, admission: Admitted = admitted(set_route)) -> dict[str, Any]:
        toy.count("item_set")
        value = json.loads(await request.body())["value"]
        return {"item": item, "value": toy.write(item, value, at_least=False)}

    @app.post("/items/{item}/raise")
    async def item_raise(item: str, request: Request, admission: Admitted = admitted(raise_route)) -> dict[str, Any]:
        toy.count("item_raise")
        toy.retries.append(admission.exact_retry)
        value = json.loads(await request.body())["value"]
        return {"item": item, "value": toy.write(item, value, at_least=True)}

    @app.get("/items/{item}")
    async def item_read(item: str, admission: Admitted = admitted(read_route)) -> dict[str, Any]:
        return {"item": item, "value": toy.read(item)}

    @app.post("/fail")
    async def fail(admission: Admitted = admitted(fail_route)) -> dict[str, Any]:
        toy.count("fail_recorded")
        toy.write("failed", 1, at_least=True)
        raise LookupError("a secret detail of the failure")

    @app.post("/fail-again")
    async def fail_again(admission: Admitted = admitted(fail_again_route)) -> dict[str, Any]:
        toy.count("fail_rerun")
        raise LookupError("a secret detail of the failure")

    @app.post("/slow")
    async def slow(admission: Admitted = admitted(slow_route)) -> dict[str, Any]:
        toy.count("slow_recorded")
        toy.slow_started.set()
        await toy.slow_finish.wait()
        return {"slow": "done"}

    @app.post("/admin/time")
    async def set_time(request: Request, admission: Admitted = admitted(time_route)) -> dict[str, Any]:
        toy.count("time_set")
        return injected_time.TimeRouteService(injected_time.installed()).set_time(await request.body())

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    for route in extra or []:
        app.add_api_route(route.template, health, methods=[route.method])

    return install(
        app,
        core,
        routes=Table() if form == "middleware" else None,
        unauthenticated=Unauthenticated.of("/health"),
    )


@dataclass
class Caller:
    """A signing caller of the toy, verifying every signed answer it receives."""

    client: httpx.AsyncClient
    signer: Signer
    authority: TrustedIdentitySet

    async def send(
        self,
        method: str,
        path: str,
        *,
        operation: str,
        resource: str | None = None,
        body: Any = None,
        request_id: str = "request-1",
        origin: int | None = None,
        created: int | None = None,
        role: str = "seller",
        audience: TrustedIdentitySet | None = None,
        signer: Signer | None = None,
        raw_body: bytes | None = None,
    ) -> httpx.Response:
        payload = raw_body if raw_body is not None else (b"" if body is None else json.dumps(body).encode())
        now = injected_time.now()
        headers = sign_market_request(
            signer=signer or self.signer,
            request=MarketRequest(
                method=method,
                operation=operation,
                resource=resource,
                request_id=request_id,
                role=role,
                origin=now if origin is None else origin,
            ),
            body=payload,
            created=now if created is None else created,
            audience=audience or self.authority,
        ).headers
        return await self.client.request(method, path, content=payload, headers=headers)

    def verified(
        self, response: httpx.Response, *, method: str, operation: str, resource: str | None = None,
        request_id: str = "request-1",
    ) -> bool:
        return verify_market_response(
            status=response.status_code,
            headers=response.headers,
            body=response.content,
            request=RequestBinding(method=method, operation=operation, resource=resource, request_id=request_id),
            expected_principals=self.authority,
            now=injected_time.now(),
            max_skew=SKEW,
        ).verified


def make_core(
    toy: Toy,
    *,
    caller: Signer,
    authority: Signer,
    outcomes: list[SignedOutcome] | None = None,
    sleep: Any = asyncio.sleep,
    wrap_store: Any = lambda store: store,
) -> AdmissionCore:
    trusted = {
        "seller": TrustedIdentitySet(identities=(caller.identity,)),
        "admin": TrustedIdentitySet(identities=(caller.identity,)),
    }
    return AdmissionCore(
        signer=lambda: authority,
        trust=lambda role: trusted[role],
        store=wrap_store(sqlite_replay_store(toy.connect)),
        settings=AuthenticatedRequestsSettings(recorded_outcome_retention_seconds=RETENTION),
        max_skew_seconds=SKEW,
        lease_seconds=LEASE,
        time_setting_operation="time_set",
        sleep=sleep,
        on_signed_outcome=outcomes.append if outcomes is not None else None,
    )


def authority_signer() -> Ed25519Signer:
    return Ed25519Signer(AUTHORITY_SEED)


def advance(seconds: int) -> None:
    source = injected_time.installed()
    assert isinstance(source, injected_time.InjectedTime)
    source.set(source.now() + seconds)


@dataclass
class World:
    """The toy authority in one form, and how a test talks to it."""

    toy: Toy
    core: AdmissionCore
    app: Any
    caller_signer: Signer
    authority: Signer
    outcomes: list[SignedOutcome] = field(default_factory=list)

    def run(self, scenario: Callable[[Caller], Awaitable[None]]) -> None:
        async def main() -> None:
            transport = httpx.ASGITransport(app=self.app)
            async with httpx.AsyncClient(transport=transport, base_url="http://authority.test") as client:
                await scenario(
                    Caller(
                        client=client,
                        signer=self.caller_signer,
                        authority=TrustedIdentitySet(identities=(self.authority.identity,)),
                    )
                )

        asyncio.run(main())


def make_world(
    tmp_path: Path,
    form: str,
    caller_signer: Signer,
    *,
    authority: Signer | None = None,
    sleep: Any = asyncio.sleep,
    wrap_store: Callable[[Any], Any] = lambda store: store,
) -> World:
    toy = Toy(migrated_database(tmp_path / f"{form}.sqlite3"))
    signer = authority or authority_signer()
    outcomes: list[SignedOutcome] = []
    core = make_core(
        toy, caller=caller_signer, authority=signer, outcomes=outcomes, sleep=sleep, wrap_store=wrap_store
    )
    return World(toy=toy, core=core, app=build_app(toy, core, form=form), caller_signer=caller_signer, authority=signer, outcomes=outcomes)
