"""The storefront's compatibility baseline; fixtures are written once with ``--write``.

Each authenticated route binds its signed operation and resource before trust
is decided, so an unsigned probe observes them.
"""

from __future__ import annotations

import argparse
import difflib
import json
import re
import sys
import time
import tomllib
import uuid
from pathlib import Path
from typing import Any

import httpx
import pytest
from core_storefront.services.negotiation_service import NegotiationService
from core_storefront.stage_log import stage_event
from fastapi import Request
from market_identity import (
    EMPTY_BODY,
    Ed25519Signer,
    RequestEnvelope,
    TrustedIdentitySet,
    canonical_body_hash,
    sign_request,
)
from starlette.routing import Route
from storefront_client.settlement_routes import SETTLE_STATUS

import apicredits_storefront.container as container
import apicredits_storefront.server as server
from apicredits_storefront.domain_runtime import get_market_domain_contract
from arkhai_api_selling.lifecycle import (
    loop_controller,
)
from apicredits_storefront.container import storefront_sqlite_client
from apicredits_storefront.utils import config as storefront_config
from tests._settings_overrides import settings_overrides

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "baseline"
SOURCE = Path(__file__).resolve().parents[2] / "src" / "apicredits_storefront"

# Deterministic development keys for this test only; never used on any network.
ADMIN_SIGNER = Ed25519Signer(bytes.fromhex("44" * 32))
STOREFRONT_SIGNER = Ed25519Signer(bytes.fromhex("77" * 32))
STRANGER_SIGNER = Ed25519Signer(bytes.fromhex("66" * 32))
BUYER_SIGNER = Ed25519Signer(bytes.fromhex("33" * 32))
BUYER = BUYER_SIGNER.identity
SIGNERS = {"admin": ADMIN_SIGNER, "seller": STOREFRONT_SIGNER, "buyer": BUYER_SIGNER}

RECORDS = ("routes", "openapi", "authentication", "refusals", "health", "configuration")

SEGMENTS = {
    "listing_id": "L-baseline",
    "neg_id": "N-baseline",
    "negotiation_id": "N-baseline",
    "escrow_uid": "0xbaseline",
    "loop": "settlement-servicing",
}

ROLES: dict[tuple[str, str], str] = {
    ("GET", "/health"): "public",
    ("GET", "/docs"): "public",
    ("GET", "/docs/oauth2-redirect"): "public",
    ("GET", "/openapi.json"): "public",
    ("GET", "/redoc"): "public",
    ("GET", "/api/v1/system/health"): "public",
    ("GET", "/api/v1/system/status"): "admin",
    ("GET", "/api/v1/system/events"): "admin",
    ("GET", "/api/v1/listings"): "public",
    ("GET", "/api/v1/listings/{listing_id}"): "public",
    ("POST", "/api/v1/listings/{listing_id}/pause"): "admin",
    ("POST", "/api/v1/listings/{listing_id}/resume"): "admin",
    ("POST", "/api/v1/listings/publish-from-quota"): "seller",
    ("POST", "/api/v1/listings/{listing_id}/close"): "seller",
    ("GET", "/api/v1/listings/{listing_id}/negotiations"): "public",
    ("GET", "/api/v1/listings/{listing_id}/negotiations/{neg_id}"): "public",
    ("POST", "/api/v1/listings/{listing_id}/negotiations/{neg_id}/advance"): "admin",
    ("POST", "/api/v1/listings/{listing_id}/negotiations/{neg_id}/force-accept"): "admin",
    ("POST", "/api/v1/negotiate/new"): "buyer",
    ("POST", "/api/v1/negotiate/{neg_id}"): "buyer",
    ("POST", "/api/v1/settle/{escrow_uid}"): "buyer",
    ("GET", "/api/v1/settle/{escrow_uid}/status"): "buyer",
    ("GET", "/api/v1/admin/settle/{escrow_uid}/wait"): "admin",
    ("POST", "/api/v1/settlements/{negotiation_id}/refund"): "seller",
    ("POST", "/api/v1/admin/lifecycle/pause"): "admin",
    ("POST", "/api/v1/admin/lifecycle/resume"): "admin",
    ("POST", "/api/v1/admin/lifecycle/{loop}/run-cycle"): "admin",
    ("POST", "/api/v1/admin/lifecycle/{loop}/dry-run"): "admin",
    ("POST", "/api/v1/admin/pause"): "admin",
    ("POST", "/api/v1/admin/resume"): "admin",
}

PROBE_BODIES: dict[tuple[str, str], Any] = {
    ("POST", "/api/v1/negotiate/new"): {
        "listing_id": SEGMENTS["listing_id"],
        "buyer_principal": BUYER.model_dump(mode="json"),
        "provision_terms": {
            "kind": "api_credits.v1",
            "version": 1,
            "payload": {"quantity": 1, "key": {"mode": "new"}},
        },
    },
    ("POST", "/api/v1/negotiate/{neg_id}"): {
        "action": "exit",
        "buyer_principal": BUYER.model_dump(mode="json"),
    },
    ("POST", "/api/v1/settle/{escrow_uid}"): {
        "negotiation_id": SEGMENTS["negotiation_id"],
        "buyer_principal": BUYER.model_dump(mode="json"),
    },
    ("POST", "/api/v1/listings/{listing_id}/negotiations/{neg_id}/force-accept"): {
        "amount": 1,
    },
}
PROBE_QUERIES: dict[tuple[str, str], str] = {
    ("GET", "/api/v1/admin/settle/{escrow_uid}/wait"): "timeout=5",
}

# Routes that resolve state before authenticating; recorded from their contract.
UNPROBED: dict[tuple[str, str], dict[str, Any]] = {
    ("GET", "/api/v1/settle/{escrow_uid}/status"): {
        "operation": SETTLE_STATUS.operation,
        "resource": SEGMENTS["escrow_uid"],
    },
}



class Probe:

    def __init__(self, db_path: Path, monkeypatch) -> None:
        db = storefront_sqlite_client(db_path=str(db_path))
        monkeypatch.setattr(container, "resolved_sqlite_client", db)
        monkeypatch.setattr(container, "resolved_marketplace_signer", STOREFRONT_SIGNER)
        monkeypatch.setattr(container, "resolved_negotiation_runtime", object())
        monkeypatch.setattr(
            container,
            "resolved_negotiation_service",
            NegotiationService(
                sqlite_client=db, continue_negotiation=_unused, stage_event=stage_event
            ),
        )
        monkeypatch.setattr(container, "resolved_system_service", server.build_system_service(db))
        self.loops = loop_controller()
        container.STOREFRONT_LOOPS.register_steps(self.loops)
        monkeypatch.setattr(container, "resolved_loop_controller", self.loops)
        monkeypatch.setattr(
            storefront_config,
            "resolve_admin_identities",
            lambda: TrustedIdentitySet(identities=(ADMIN_SIGNER.identity,)),
        )
        self.observed: dict[str, dict[str, str] | None] = {}
        self.app = server.build_api_credits_storefront_app(
            registry=server.build_api_credits_storefront_registry(
                domain=get_market_domain_contract()
            )
        )

        observed = self.observed

        @self.app.middleware("http")
        async def observe(request: Request, call_next):
            response = await call_next(request)
            context = getattr(request.state, "marketplace_response_auth", None)
            observed[request.headers.get("x-baseline-probe", "")] = (
                {"operation": context.operation, "resource": context.resource}
                if context is not None
                else None
            )
            return response

    def client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            transport=httpx.ASGITransport(app=self.app, raise_app_exceptions=False),
            base_url="http://seller",
        )


async def _unused(**_kwargs):
    raise AssertionError("no probe continues a negotiation")



def _iter_routes(routes, prefix: str = "") -> list[tuple[str, Route]]:
    flattened: list[tuple[str, Route]] = []
    for route in routes:
        if isinstance(route, Route):
            flattened.append((prefix, route))
            continue
        original = getattr(route, "original_router", None)
        if original is None or not getattr(original, "routes", None):
            continue
        context = getattr(route, "include_context", None)
        child_prefix = prefix + (getattr(context, "prefix", "") or "")
        flattened.extend(_iter_routes(original.routes, child_prefix))
    return flattened


def _mounted(app) -> list[dict[str, Any]]:
    surface = []
    for prefix, route in _iter_routes(app.routes):
        for method in sorted(route.methods or ()):
            if method in {"HEAD", "OPTIONS"}:
                continue
            surface.append({"method": method, "path": prefix + route.path, "name": route.name})
    return sorted(surface, key=lambda r: (r["path"], r["method"]))


def capture_routes(app) -> list[dict[str, Any]]:
    return _mounted(app)


async def capture_openapi(client: httpx.AsyncClient) -> dict[str, Any]:
    response = await client.get("/openapi.json")
    assert response.status_code == 200, response.text
    return response.json()



def _concrete(path: str) -> str:
    return re.sub(r"\{(\w+)\}", lambda m: SEGMENTS[m.group(1)], path)


async def capture_authentication(probe: Probe, client: httpx.AsyncClient) -> list[dict[str, Any]]:
    records = []
    try:
        return await _probe_routes(probe, client, records)
    finally:
        container.trading_pause.resume()
        probe.loops.request_pause(False)


async def _probe_routes(probe: Probe, client: httpx.AsyncClient, records: list) -> list[dict[str, Any]]:
    with settings_overrides(
        identity__scheme=STOREFRONT_SIGNER.identity.scheme.value,
        identity__identifier=STOREFRONT_SIGNER.identity.identifier,
    ):
        for route in _mounted(probe.app):
            key = (route["method"], route["path"])
            assert key in ROLES, f"{key} is mounted but has no stated caller role"
            record: dict[str, Any] = {**route, "role": ROLES[key]}
            if key in UNPROBED:
                record.update(UNPROBED[key])
                record["probe"] = "state resolved before authentication; recorded from the contract"
                records.append(record)
                continue
            token = f"{route['method']} {route['path']}"
            url = _concrete(route["path"])
            if key in PROBE_QUERIES:
                url += "?" + PROBE_QUERIES[key]
            body = PROBE_BODIES.get(key)
            response = await client.request(
                route["method"], url, json=body, headers={"x-baseline-probe": token}
            )
            bound = probe.observed.get(token)
            record.update(
                {
                    "operation": bound["operation"] if bound else None,
                    "resource": bound["resource"] if bound else None,
                    "probe": f"unsigned request answered {response.status_code}",
                }
            )
            if bound is not None:
                admitted = []
                for role, signer in SIGNERS.items():
                    signed = await client.request(
                        route["method"],
                        url,
                        json=body,
                        headers=_headers(
                            signer,
                            role=role,
                            method=route["method"],
                            operation=bound["operation"],
                            resource=bound["resource"],
                            body=EMPTY_BODY if body is None else body,
                        ),
                    )
                    if signed.status_code not in (401, 403):
                        admitted.append(role)
                record["admitted_roles"] = admitted
                assert admitted == [ROLES[key]], (key, admitted)
            records.append(record)
    unknown = sorted(set(ROLES) - {(r["method"], r["path"]) for r in records})
    assert not unknown, f"roles stated for routes that are not mounted: {unknown}"
    return records



def _headers(
    signer: Ed25519Signer,
    *,
    role: str = "admin",
    method: str = "GET",
    operation: str = "admin_system_status",
    resource: str = "system/status",
    request_id: str | None = None,
    body: Any = EMPTY_BODY,
) -> dict[str, str]:
    signed = sign_request(
        signer=signer,
        envelope=RequestEnvelope(
            role=role,
            principal=signer.identity,
            method=method,
            operation=operation,
            resource=resource,
            request_id=request_id or str(uuid.uuid4()),
            timestamp=int(time.time()),
            body_hash=canonical_body_hash(body),
        ),
    )
    return {
        "X-Market-Signature-Version": signed.protocol,
        "X-Market-Identity-Scheme": signed.principal.scheme.value,
        "X-Market-Identity-Identifier": signed.principal.identifier,
        "X-Market-Role": signed.role,
        "X-Market-Request-ID": signed.request_id,
        "X-Market-Timestamp": str(signed.timestamp),
        "X-Market-Signature": signed.proof.value,
    }


def _recorded(response: httpx.Response) -> dict[str, Any]:
    try:
        body = response.json()
    except ValueError:
        body = response.text
    return {"status": response.status_code, "body": body}


async def capture_refusals(client: httpx.AsyncClient) -> dict[str, Any]:
    # Rejection paths, signed by hand.
    refusals: dict[str, Any] = {}
    status = "/api/v1/system/status"
    refusals["unauthenticated"] = _recorded(await client.get(status))
    refusals["untrusted_principal"] = _recorded(
        await client.get(status, headers=_headers(STRANGER_SIGNER))
    )
    refusals["role_not_authorized"] = _recorded(
        await client.get(status, headers=_headers(ADMIN_SIGNER, role="buyer"))
    )
    tampered = _headers(ADMIN_SIGNER)
    tampered["X-Market-Signature"] = tampered["X-Market-Signature"][:-4] + "AAAA"
    refusals["invalid_signature"] = _recorded(await client.get(status, headers=tampered))

    reused = "baseline-reused-request-id"
    pause = _headers(ADMIN_SIGNER, method="POST", operation="admin_pause", resource="", request_id=reused)
    try:
        first = await client.post("/api/v1/admin/pause", headers=pause)
        assert first.status_code == 200, first.text
        refusals["exact_retry"] = _recorded(await client.post("/api/v1/admin/pause", headers=pause))
        refusals["changed_reuse"] = _recorded(
            await client.post(
                "/api/v1/admin/resume",
                headers=_headers(
                    ADMIN_SIGNER, method="POST", operation="admin_resume", resource="", request_id=reused
                ),
            )
        )
    finally:
        container.trading_pause.resume()
    refusals["unknown_lifecycle_loop"] = _recorded(
        await client.post(
            "/api/v1/admin/lifecycle/no-such-loop/run-cycle",
            headers=_headers(
                ADMIN_SIGNER,
                method="POST",
                operation="admin_run_lifecycle_cycle",
                resource="no-such-loop",
            ),
        )
    )
    return refusals


async def capture_health(client: httpx.AsyncClient) -> dict[str, Any]:
    response = await client.get("/health")
    assert response.status_code == 200, response.text
    return response.json()



def _flatten(table: dict[str, Any], prefix: str = "") -> list[str]:
    keys: list[str] = []
    for name, value in table.items():
        key = f"{prefix}{name}"
        keys.append(key)
        if isinstance(value, dict):
            keys.extend(_flatten(value, key + "."))
    return keys


_SETTINGS_GET = re.compile(r'settings\.get\(\s*"([A-Za-z_][A-Za-z0-9_.]*)"')
_SETTINGS_ATTR = re.compile(r"settings\.([a-z_][a-z0-9_]*(?:\.[a-z_][a-z0-9_]*)*)")
_ENVIRON = re.compile(
    r'environ\)?(?:\.get)?\(\s*"([A-Z_][A-Z0-9_]*)"|environ\["([A-Z_][A-Z0-9_]*)"\]'
)
_SETTINGS_METHODS = {"get", "set", "unset", "toml"}


def capture_configuration() -> dict[str, Any]:
    declared = _flatten(tomllib.loads((SOURCE / "settings.toml").read_text(encoding="utf-8")))
    read: set[str] = set()
    environment: set[str] = set()
    for module in sorted(SOURCE.rglob("*.py")):
        text = module.read_text(encoding="utf-8")
        read.update(_SETTINGS_GET.findall(text))
        for attribute in _SETTINGS_ATTR.findall(text):
            if attribute.split(".")[0] not in _SETTINGS_METHODS:
                read.add(attribute)
        for first, second in _ENVIRON.findall(text):
            environment.add(first or second)
    keys = sorted({key.lower() for key in declared} | {key.lower() for key in read})
    return {
        "envvar_prefix": "APICREDITS_STOREFRONT",
        "envvar_separator": "__",
        "settings_keys": keys,
        "environment_variables": sorted(
            {f"APICREDITS_STOREFRONT_{key.upper().replace('.', '__')}" for key in keys}
            | environment
        ),
    }



async def capture_all(probe: Probe) -> dict[str, Any]:
    async with probe.client() as client:
        return {
            "routes": capture_routes(probe.app),
            "openapi": await capture_openapi(client),
            "authentication": await capture_authentication(probe, client),
            "refusals": await capture_refusals(client),
            "health": await capture_health(client),
            "configuration": capture_configuration(),
        }


def load_record(name: str) -> Any:
    path = FIXTURES / f"{name}.json"
    if not path.exists():
        raise AssertionError(
            f"{path} is missing; the baseline is written once by "
            "`python -m tests.integration.test_compat_baseline --write`"
        )
    return json.loads(path.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def captured(tmp_path_factory: pytest.TempPathFactory):
    import asyncio

    monkeypatch = pytest.MonkeyPatch()
    try:
        probe = Probe(tmp_path_factory.mktemp("baseline") / "baseline.db", monkeypatch)
        yield asyncio.run(capture_all(probe))
    finally:
        monkeypatch.undo()


@pytest.mark.parametrize("record", RECORDS)
def test_the_baseline_diffs_to_zero(captured, record):
    expected = load_record(record)
    actual = captured[record]
    assert actual == expected, _diff(record, expected, actual)


def _diff(record: str, expected: Any, actual: Any) -> str:
    before = json.dumps(expected, indent=2, sort_keys=True).splitlines()
    after = json.dumps(actual, indent=2, sort_keys=True).splitlines()
    return f"{record} changed:\n" + "\n".join(
        difflib.unified_diff(before, after, "recorded", "served", lineterm="", n=2)
    )


def main(argv: list[str]) -> int:
    import asyncio
    from tempfile import TemporaryDirectory

    from pytest import MonkeyPatch

    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--write", action="store_true", help="write the fixtures; refuses to overwrite")
    args = parser.parse_args(argv)
    if not args.write:
        parser.error("nothing to do without --write")
    existing = [name for name in RECORDS if (FIXTURES / f"{name}.json").exists()]
    if existing:
        print(f"{FIXTURES} already holds {existing}; fixtures are never rewritten", file=sys.stderr)
        return 1
    monkeypatch = MonkeyPatch()
    with TemporaryDirectory() as directory:
        try:
            records = asyncio.run(capture_all(Probe(Path(directory) / "baseline.db", monkeypatch)))
        finally:
            monkeypatch.undo()
    FIXTURES.mkdir(parents=True, exist_ok=True)
    for name, value in records.items():
        (FIXTURES / f"{name}.json").write_text(
            json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        print(f"wrote {FIXTURES / f'{name}.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
