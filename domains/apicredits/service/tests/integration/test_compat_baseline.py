"""The credits service's compatibility baseline; fixtures are written once with ``--write``."""

from __future__ import annotations

import argparse
import json
import re
import sys
import tomllib
from importlib.metadata import version as installed_version
from pathlib import Path
from typing import Any

import httpx
import pytest
from market_identity import EMPTY_BODY, Identity, TrustedIdentitySet
from starlette.routing import Route

from tests.integration.signed_service import (
    AUTHORITY,
    GATED_SIGNER,
    IMPOSTOR_SIGNER,
    REQUEST_ID_HEADER,
    STOREFRONT_SIGNER,
    load_signed_app,
    signed_headers,
    unload_service_modules,
)

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "baseline"
SOURCE = Path(__file__).resolve().parents[2] / "src" / "apicredits_service"
DISTRIBUTION = "arkhai-apicredits-service"

# Deterministic development principals; never used on any network.
BUYER = Identity(scheme="eip191", identifier="0xabcdef0000000000000000000000000000000001")
STRANGER = Identity(scheme="eip191", identifier="0x9999000000000000000000000000000000000003")

RECORDS = ("routes", "openapi", "route_contracts", "refusals", "version", "configuration")



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


def capture_routes(app) -> list[dict[str, Any]]:
    surface = []
    for prefix, route in _iter_routes(app.routes):
        for method in sorted(route.methods or ()):
            if method in {"HEAD", "OPTIONS"}:
                continue
            surface.append({"method": method, "path": prefix + route.path, "name": route.name})
    return sorted(surface, key=lambda r: (r["path"], r["method"]))


async def capture_openapi(client: httpx.AsyncClient) -> dict[str, Any]:
    response = await client.get("/openapi.json")
    assert response.status_code == 200, response.text
    return response.json()



def capture_route_contracts() -> dict[str, Any]:
    from apicredits_service.main import _UNSIGNED_PATHS, CREDITS_ROUTE_CONTRACTS
    from market_site.auth import CAPACITY_ROUTE_CONTRACTS

    def declare(contract) -> dict[str, Any]:
        return {
            "method": contract.method,
            "pattern": contract.pattern.pattern,
            "operation": contract.operation,
            "allowed_roles": sorted(contract.allowed_roles),
            "path_resource": contract.path_resource,
            "body_resource": contract.body_resource,
            "optional_body_resource": contract.optional_body_resource,
            "exact_retry_safe": contract.exact_retry_safe,
        }

    return {
        "unsigned_paths": sorted(_UNSIGNED_PATHS),
        "credits": [declare(c) for c in CREDITS_ROUTE_CONTRACTS],
        "capacity": [declare(c) for c in CAPACITY_ROUTE_CONTRACTS],
    }



def _normalize_body(body: Any) -> Any:
    # A 422 echoes the input and a documentation URL; neither is the refusal.
    if isinstance(body, dict) and isinstance(body.get("detail"), list):
        return {
            "detail": [
                {key: error[key] for key in ("type", "loc", "msg") if key in error}
                for error in body["detail"]
            ]
        }
    return body


def _recorded(response: httpx.Response) -> dict[str, Any]:
    try:
        body = response.json()
    except ValueError:
        body = response.text
    return {"status": response.status_code, "body": _normalize_body(body)}


def _seller_client(app):
    from apicredits_service.config import ISSUANCE_LABEL
    from arkhai_api_client import AuthorityClient

    return AuthorityClient(
        "http://credits-service",
        label=ISSUANCE_LABEL,
        transport=httpx.ASGITransport(app=app),
        signer=STOREFRONT_SIGNER,
        expected_authorities=TrustedIdentitySet(identities=(AUTHORITY.identity,)),
    )


def _gated_client(app):
    from apicredits_middleware.client import TokensClient
    from apicredits_middleware.signing import AuthoritySigning, build_trusted_authorities

    return TokensClient(
        service_url="http://credits-service",
        http=httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://credits-service"
        ),
        signing=AuthoritySigning(
            signer=GATED_SIGNER,
            expected_authorities=build_trusted_authorities(
                [AUTHORITY.identity.model_dump(mode="json")]
            ),
        ),
    )


def _capacity_admin(app):
    from market_site_client.client import SiteCapacityAdminClient

    return SiteCapacityAdminClient(
        "http://credits-service",
        signer=STOREFRONT_SIGNER,
        expected_authorities=TrustedIdentitySet(identities=(AUTHORITY.identity,)),
        transport=httpx.ASGITransport(app=app),
    )


def _issuance(negotiation_id: str, quantity: int, *, owner=BUYER, existing_key=None):
    from apicredits_service.config import ISSUANCE_LABEL
    from arkhai_api.issuance import KeyDisposition, issuance_request

    key = (
        KeyDisposition(mode="existing", key_id=existing_key)
        if existing_key
        else KeyDisposition(mode="new")
    )
    return issuance_request(
        ISSUANCE_LABEL,
        negotiation_id=negotiation_id,
        owner=owner,
        service="weather-api",
        resource_id="weather-quota",
        quantity=quantity,
        key=key,
    )


async def capture_refusals(app, client: httpx.AsyncClient) -> dict[str, Any]:
    # Rejection paths, signed by hand.
    refusals: dict[str, Any] = {}

    def seller(method, operation, resource, body=EMPTY_BODY, request_id=None):
        return signed_headers(
            signer=STOREFRONT_SIGNER, role="seller", method=method,
            operation=operation, resource=resource, body=body, request_id=request_id,
        )

    def gated(method, operation, resource, body=EMPTY_BODY):
        return signed_headers(
            signer=GATED_SIGNER, role="service", method=method,
            operation=operation, resource=resource, body=body,
        )

    refusals["unauthenticated"] = _recorded(await client.get("/api/v1/keys"))
    refusals["unknown_route"] = _recorded(await client.get("/api/v1/no-such-route"))
    refusals["role_not_authorized"] = _recorded(
        await client.post(
            "/api/v1/issuance",
            json={"fulfillment_id": "f-1"},
            headers=gated("POST", "credits_issue", "f-1", {"fulfillment_id": "f-1"}),
        )
    )
    refusals["no_trusted_principal_for_role"] = _recorded(
        await client.get(
            "/api/v1/keys",
            headers=signed_headers(
                signer=IMPOSTOR_SIGNER, role="admin", method="GET",
                operation="credits_keys_list", resource="",
            ),
        )
    )
    refusals["untrusted_principal"] = _recorded(
        await client.get(
            "/api/v1/keys",
            headers=signed_headers(
                signer=IMPOSTOR_SIGNER, role="seller", method="GET",
                operation="credits_keys_list", resource="",
            ),
        )
    )
    reused = "baseline-reused-request-id"
    assert (
        await client.get("/api/v1/keys", headers=seller("GET", "credits_keys_list", "", request_id=reused))
    ).status_code == 200
    refusals["changed_reuse"] = _recorded(
        await client.get(
            "/api/v1/keys/ak_missing",
            headers=seller("GET", "credits_key_get", "ak_missing", request_id=reused),
        )
    )

    await _capacity_admin(app).register_resource(
        "weather-quota",
        total_units=10,
        resource_type="api.credits",
        attributes={"service": "weather-api"},
        pool_id="default",
    )
    issued = await _seller_client(app).submit_issuance(_issuance("neg-baseline-1", 3))
    tampered = {**_issuance("neg-baseline-2", 1).model_dump(mode="json"), "quantity": 2}
    refusals["issuance_invalid"] = _recorded(
        await client.post(
            "/api/v1/issuance",
            json=tampered,
            headers=seller("POST", "credits_issue", tampered["fulfillment_id"], tampered),
        )
    )

    async def issue(request):
        payload = request.model_dump(mode="json", exclude_none=True)
        return await client.post(
            "/api/v1/issuance",
            json=payload,
            headers=seller("POST", "credits_issue", payload["fulfillment_id"], payload),
        )

    refusals["issuance_key_not_found"] = _recorded(
        await issue(_issuance("neg-baseline-3", 1, existing_key="ak_missing"))
    )
    refusals["issuance_key_not_owned"] = _recorded(
        await issue(_issuance("neg-baseline-4", 1, owner=STRANGER, existing_key=issued.key_id))
    )
    refusals["issuance_fulfillment_conflict"] = _recorded(
        await issue(_issuance("neg-baseline-1", 4))
    )
    refusals["issuance_quota_exhausted"] = _recorded(
        await issue(_issuance("neg-baseline-5", 100))
    )
    refusals["issuance_not_found"] = _recorded(
        await client.get(
            "/api/v1/issuance/no-such-fulfillment",
            headers=seller("GET", "credits_issuance_get", "no-such-fulfillment"),
        )
    )

    refusals["key_not_found"] = _recorded(
        await client.get("/api/v1/keys/ak_missing", headers=seller("GET", "credits_key_get", "ak_missing"))
    )
    refusals["revoke_key_not_found"] = _recorded(
        await client.post(
            "/api/v1/keys/ak_missing/revoke", headers=seller("POST", "credits_key_revoke", "ak_missing")
        )
    )
    below_zero = {"delta": -999, "reason": "baseline"}
    refusals["adjust_below_zero"] = _recorded(
        await client.post(
            f"/api/v1/keys/{issued.key_id}/adjust",
            json=below_zero,
            headers=seller("POST", "credits_key_adjust", issued.key_id, below_zero),
        )
    )
    adjust = {"delta": 1, "reason": "baseline"}
    retried = "baseline-retried-adjust"
    assert (
        await client.post(
            f"/api/v1/keys/{issued.key_id}/adjust",
            json=adjust,
            headers=seller("POST", "credits_key_adjust", issued.key_id, adjust, request_id=retried),
        )
    ).status_code == 200
    refusals["exact_retry_refused"] = _recorded(
        await client.post(
            f"/api/v1/keys/{issued.key_id}/adjust",
            json=adjust,
            headers=seller("POST", "credits_key_adjust", issued.key_id, adjust, request_id=retried),
        )
    )
    consume = {"amount": 1}
    refusals["consume_key_not_found"] = _recorded(
        await client.post(
            "/api/v1/keys/ak_missing/consume",
            json=consume,
            headers=gated("POST", "credits_key_consume", "ak_missing", consume),
        )
    )
    spent = await _gated_client(app).consume(key_id=issued.key_id, amount=4)
    assert spent.ok is True, spent
    refusals["consume_insufficient_credits"] = _recorded(
        await client.post(
            f"/api/v1/keys/{issued.key_id}/consume",
            json=consume,
            headers=gated("POST", "credits_key_consume", issued.key_id, consume),
        )
    )
    await _seller_client(app).revoke_key(issued.key_id)
    refusals["consume_key_revoked"] = _recorded(
        await client.post(
            f"/api/v1/keys/{issued.key_id}/consume",
            json=consume,
            headers=gated("POST", "credits_key_consume", issued.key_id, consume),
        )
    )
    return refusals



async def capture_version(client: httpx.AsyncClient) -> dict[str, Any]:
    response = await client.get("/api/v1/system/version")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["version"] == installed_version(DISTRIBUTION)
    return {**body, "version": "<installed distribution version>"}


def _flatten(table: dict[str, Any], prefix: str = "") -> list[str]:
    keys: list[str] = []
    for name, value in table.items():
        key = f"{prefix}{name}"
        if isinstance(value, dict):
            keys.append(key)
            keys.extend(_flatten(value, key + "."))
        else:
            keys.append(key)
    return keys


_SETTINGS_GET = re.compile(r'settings\.get\(\s*"([A-Za-z_][A-Za-z0-9_.]*)"')
_SETTINGS_ATTR = re.compile(r"settings\.([a-z_][a-z0-9_]*(?:\.[a-z_][a-z0-9_]*)*)")
_ENVIRON = re.compile(r'environ(?:\.get)?\(\s*"([A-Z_][A-Z0-9_]*)"|environ\["([A-Z_][A-Z0-9_]*)"\]')
_SETTINGS_METHODS = {"get", "set", "unset", "toml", "is_sqlite"}


def capture_configuration() -> dict[str, Any]:
    declared = _flatten(tomllib.loads((SOURCE / "settings.toml").read_text(encoding="utf-8")))
    read: set[str] = set()
    environment: set[str] = set()
    for module in sorted(SOURCE.rglob("*.py")):
        text = module.read_text(encoding="utf-8")
        read.update(_SETTINGS_GET.findall(text))
        for attribute in _SETTINGS_ATTR.findall(text):
            head = attribute.split(".")[0]
            if head not in _SETTINGS_METHODS:
                read.add(head)
        for first, second in _ENVIRON.findall(text):
            environment.add(first or second)
    keys = sorted(set(declared) | read)
    return {
        "envvar_prefix": "APICREDITS",
        "envvar_separator": "__",
        "settings_keys": keys,
        "environment_variables": sorted(
            {f"APICREDITS_{key.upper().replace('.', '__')}" for key in keys} | environment
        ),
    }



async def capture_all(app) -> dict[str, Any]:
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://credits-service"
    ) as client:
        return {
            "routes": capture_routes(app),
            "openapi": await capture_openapi(client),
            "route_contracts": capture_route_contracts(),
            "refusals": await capture_refusals(app, client),
            "version": await capture_version(client),
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


@pytest.fixture
async def captured(tmp_path: Path, monkeypatch):
    app = load_signed_app(tmp_path, monkeypatch)
    try:
        yield await capture_all(app)
    finally:
        unload_service_modules()


@pytest.mark.parametrize("record", RECORDS)
async def test_the_baseline_diffs_to_zero(captured, record):
    expected = load_record(record)
    actual = captured[record]
    assert actual == expected, _diff(record, expected, actual)


def _diff(record: str, expected: Any, actual: Any) -> str:
    before = json.dumps(expected, indent=2, sort_keys=True).splitlines()
    after = json.dumps(actual, indent=2, sort_keys=True).splitlines()
    import difflib

    return f"{record} changed:\n" + "\n".join(
        difflib.unified_diff(before, after, "recorded", "served", lineterm="", n=2)
    )


def main(argv: list[str]) -> int:
    import asyncio
    from pytest import MonkeyPatch
    from tempfile import TemporaryDirectory

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
        app = load_signed_app(Path(directory), monkeypatch)
        try:
            records = asyncio.run(capture_all(app))
        finally:
            unload_service_modules()
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
