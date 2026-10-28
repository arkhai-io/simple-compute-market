"""Rejection path: the service answers a request that resolves to no route.

The typed clients resolve their own route table before sending, so they never
send an unknown path, an unserved method, or a body missing its resource;
these requests are built by hand against the composed application. Each
carries a placeholder signature header, which the harness's signing transport
passes through unchanged and which the service never reaches, since it
answers before authentication. Only the status and ``Allow`` are asserted.
"""

from __future__ import annotations

import httpx
import pytest
import pytest_asyncio
from httpx import ASGITransport

from compute_provisioning_contracts import SIGNATURE_HEADER
from compute_provisioning_service.main import app

pytestmark = pytest.mark.asyncio

_UNSIGNED = {SIGNATURE_HEADER: "placeholder"}


@pytest_asyncio.fixture
async def raw(client_and_queue):
    async with httpx.AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as http:
        yield http


async def test_an_unknown_path_answers_404(raw) -> None:
    response = await raw.get("/api/v1/nowhere", headers=_UNSIGNED)

    assert response.status_code == 404


@pytest.mark.parametrize(
    ("path", "allow"),
    [
        ("/api/v1/fulfillment/schedule", "POST"),
        ("/api/v1/hosts/", "GET, POST"),
        ("/api/v1/capacity/snapshot", "GET"),
    ],
    ids=["family", "family-two-methods", "site"],
)
async def test_a_known_path_under_another_method_answers_405_with_allow(
    raw, path, allow
) -> None:
    response = await raw.delete(path, headers=_UNSIGNED)

    assert response.status_code == 405
    assert response.headers["Allow"] == allow


async def test_a_route_whose_body_resource_is_missing_answers_400(raw) -> None:
    response = await raw.post(
        "/api/v1/fulfillment/schedule", json={}, headers=_UNSIGNED
    )

    assert response.status_code == 400
