"""The synchronous capacity-admin client, and its parity with the async one.

The sync client exists so callers outside an event loop — operator scripts and
the end-to-end scenarios, which drive every other service through synchronous
typed clients — reach the site authority the same way production does rather than
through an `asyncio.run` wrapper.

Parity is asserted rather than assumed: `TESTING.md` expects it where both clients
exist, and a divergence would stay invisible until a caller of one hit behaviour
only the other had.
"""

from __future__ import annotations

import inspect

import httpx
import pytest
from market_site_client import (
    SiteCapacityAdminClient,
    SiteCapacityAdminClientError,
    SyncSiteCapacityAdminClient,
)


def test_the_two_clients_share_a_constructor_signature() -> None:
    assert (
        list(inspect.signature(SiteCapacityAdminClient.__init__).parameters)
        == list(inspect.signature(SyncSiteCapacityAdminClient.__init__).parameters)
    )


def test_the_two_clients_share_a_register_resource_signature() -> None:
    assert (
        list(inspect.signature(SiteCapacityAdminClient.register_resource).parameters)
        == list(inspect.signature(SyncSiteCapacityAdminClient.register_resource).parameters)
    )


def test_only_the_async_one_is_a_coroutine() -> None:
    assert inspect.iscoroutinefunction(SiteCapacityAdminClient.register_resource)
    assert not inspect.iscoroutinefunction(
        SyncSiteCapacityAdminClient.register_resource
    )


def test_register_resource_puts_the_registration_body() -> None:
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        import json

        seen["url"] = str(request.url)
        seen["method"] = request.method
        seen["body"] = json.loads(request.content)
        seen["admin_key"] = request.headers.get("X-Admin-Key")
        return httpx.Response(200, json={"resource_id": "kvm1"})

    client = SyncSiteCapacityAdminClient(
        "http://site:8081/", "k", transport=httpx.MockTransport(handler),
    )

    result = client.register_resource(
        "kvm1",
        total_units=4,
        attributes={"region": "California, US", "gpu_model": "RTX 4090"},
        capacity={"gpu_count": 4},
    )

    assert result == {"resource_id": "kvm1"}
    assert seen["method"] == "PUT"
    assert seen["url"] == "http://site:8081/api/v1/capacity/resources/kvm1"
    assert seen["admin_key"] == "k"
    assert seen["body"]["total_units"] == 4
    assert seen["body"]["attributes"]["region"] == "California, US"


def test_an_omitted_admin_key_sends_no_header() -> None:
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["admin_key"] = request.headers.get("X-Admin-Key")
        return httpx.Response(200, json={})

    SyncSiteCapacityAdminClient(
        "http://site:8081", transport=httpx.MockTransport(handler),
    ).register_resource("kvm1", total_units=1)

    assert seen["admin_key"] is None


def test_a_non_2xx_raises_the_shared_error_with_its_status() -> None:
    client = SyncSiteCapacityAdminClient(
        "http://site:8081",
        transport=httpx.MockTransport(lambda _: httpx.Response(403, text="nope")),
    )

    with pytest.raises(SiteCapacityAdminClientError) as caught:
        client.register_resource("kvm1", total_units=1)

    assert caught.value.status_code == 403
    assert "kvm1" in str(caught.value)


def test_a_transport_failure_raises_the_shared_error_not_httpx() -> None:
    """Every caller sees one error shape, whichever operation failed."""

    def boom(_: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("unreachable")

    client = SyncSiteCapacityAdminClient(
        "http://site:8081", transport=httpx.MockTransport(boom),
    )

    with pytest.raises(SiteCapacityAdminClientError) as caught:
        client.register_resource("kvm1", total_units=1)

    assert "http://site:8081" in str(caught.value)
