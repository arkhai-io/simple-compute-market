"""The gate's local spelling of the routes it calls equals the contracts' declarations.

The gate depends on httpx alone, so it cannot read `arkhai_api_contracts`; it
spells the three routes it calls itself. Each test names the route whose
spelling drifted. Request bodies are captured from the real client and gate,
and response bodies are built from the contracts' models, so a field either
side renames fails here rather than at a deployment.
"""

from __future__ import annotations

import dataclasses
import json
import re
import tomllib
from pathlib import Path

import httpx
import pytest

from arkhai_api_contracts import models, refusals
from arkhai_api_contracts.routes import SERVICE_ROLE, route
from arkhai_api_gate import client, signing
from arkhai_api_gate.config import GateConfig
from arkhai_api_gate.gate import TokenGate

PYPROJECT = Path(__file__).resolve().parents[1] / "pyproject.toml"

GATE_ROUTES = (
    ("verify", client.VERIFY_OPERATION, client.VERIFY_PATH, "key_id"),
    ("consume", client.CONSUME_OPERATION, client.CONSUME_PATH, "key_id"),
    ("consume-batch", client.CONSUME_BATCH_OPERATION, client.CONSUME_BATCH_PATH, None),
)


def _declaration(name: str, operation: str) -> dict:
    try:
        return route(operation)
    except KeyError:
        pytest.fail(f"[{name}] the gate's operation {operation!r} is not declared")


@pytest.mark.parametrize(("name", "operation", "path", "resource"), GATE_ROUTES, ids=[r[0] for r in GATE_ROUTES])
def test_each_route_is_spelled_as_declared(name, operation, path, resource):
    declaration = _declaration(name, operation)

    assert declaration["method"] == "POST", f"[{name}] method"
    assert re.fullmatch(declaration["path"], path.format(key_id="ak_x")), f"[{name}] path {path!r}"
    assert signing.GATED_APP_ROLE == SERVICE_ROLE, f"[{name}] the gate's role"
    assert SERVICE_ROLE in declaration["roles"], f"[{name}] roles"
    assert declaration.get("path_resource") == resource, f"[{name}] signed resource"
    assert declaration.get("body_resource") is None, f"[{name}] signed resource"
    if resource is None:
        assert client.BATCH_RESOURCE == "", f"[{name}] signed resource"


def test_the_refusal_reasons_are_the_declared_ones():
    assert (
        client.KEY_NOT_FOUND,
        client.KEY_REVOKED,
        client.INSUFFICIENT_CREDITS,
    ) == refusals.CONSUME_REFUSALS, "[consume] refusal reasons"


def test_the_parsed_results_carry_the_declared_response_fields():
    assert {f.name for f in dataclasses.fields(client.VerifyResult)} == set(
        models.VerifyResponse.model_fields
    ), "[verify] response fields"
    assert {f.name for f in dataclasses.fields(client.ConsumeResult)} == set(
        models.ConsumeOutcome.model_fields
    ), "[consume] response fields"


class _Authority:
    """Answers with bodies built from the contracts' models and records what was sent."""

    def __init__(self) -> None:
        self.sent: dict[str, dict] = {}
        self.methods: dict[str, str] = {}

    def handle(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        name = request.url.path.rsplit("/", 1)[-1]
        self.methods[name] = request.method
        if name == "verify":
            self.sent["verify"] = body
            answer = models.VerifyResponse(valid=True, status="active", balance=9)
        elif name == "consume-batch":
            self.sent["consume-batch"] = body
            answer = models.ConsumeBatchResponse(
                results=[models.ConsumeOutcome(ok=True, consumed=1, balance=7).model_dump()]
            )
        else:
            self.sent["consume"] = body
            if body["amount"] > 5:
                refusal = models.ConsumeRefusal(error=refusals.INSUFFICIENT_CREDITS, balance=2)
                return httpx.Response(402, json=refusal.model_dump())
            answer = models.ConsumeOutcome(ok=True, consumed=body["amount"], balance=8, duplicate=True)
        return httpx.Response(200, json=answer.model_dump())


async def test_requests_are_the_declared_bodies_and_responses_parse_from_the_declared_models():
    authority = _Authority()
    async with httpx.AsyncClient(transport=httpx.MockTransport(authority.handle)) as http:
        tokens = client.TokensClient(service_url="http://authority", http=http)

        verified = await tokens.verify(key_id="ak_x", secret="ak_x.s")
        consumed = await tokens.consume(key_id="ak_x", amount=1, idempotency_key="idem-1")
        refused = await tokens.consume(key_id="ak_x", amount=6, idempotency_key="idem-2")

        gate = TokenGate(
            GateConfig(
                service_url="http://authority",
                authority_label="test-authority",
                flush_interval_seconds=60.0,
                low_balance_threshold=1,
            ),
            tokens,
        )
        assert (await gate.authorize("Bearer ak_y.s")).allowed
        await gate.flush()
        batched = await tokens.consume_batch([{"key_id": "ak_x", "amount": 1, "idempotency_key": "idem-3"}])

    for name, _operation, _path, _resource in GATE_ROUTES:
        assert authority.methods[name] == route(_operation)["method"], f"[{name}] method sent"

    assert models.VerifyRequest.model_validate(authority.sent["verify"])
    assert set(authority.sent["verify"]) == set(models.VerifyRequest.model_fields), "[verify] request fields"
    assert models.ConsumeRequest.model_validate(authority.sent["consume"])
    assert set(authority.sent["consume"]) == set(models.ConsumeRequest.model_fields), "[consume] request fields"
    batch = models.ConsumeBatchRequest.model_validate(authority.sent["consume-batch"])
    assert set(authority.sent["consume-batch"]) == set(models.ConsumeBatchRequest.model_fields), (
        "[consume-batch] request fields"
    )
    assert [set(item) for item in authority.sent["consume-batch"]["items"]] == [
        set(models.ConsumeBatchItem.model_fields)
    ] * len(batch.items), "[consume-batch] item fields"

    assert verified == client.VerifyResult(valid=True, status="active", balance=9)
    assert consumed == client.ConsumeResult(ok=True, balance=8, consumed=1, duplicate=True)
    assert refused == client.ConsumeResult(ok=False, balance=2, reason=refusals.INSUFFICIENT_CREDITS)
    assert batched == [client.ConsumeResult(ok=True, balance=7, consumed=1)]


def test_the_runtime_dependencies_are_httpx_alone():
    project = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))["project"]

    def names(requirements: list[str]) -> set[str]:
        return {re.split(r"[\s<>=!~;\[]", requirement, maxsplit=1)[0] for requirement in requirements}

    assert names(project["dependencies"]) == {"httpx"}
    assert {extra: names(reqs) for extra, reqs in project["optional-dependencies"].items()} == {
        "signed": {"arkhai-kit-identity"}
    }
