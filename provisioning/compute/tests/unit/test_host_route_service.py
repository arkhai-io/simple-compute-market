"""The host routes' refusals, and connectivity through each kind's probe."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from compute_provisioning_contracts import ConnectivityResult, HostCreate, HostUpdate
from sqlalchemy.exc import IntegrityError

from compute_provisioning.hosts import ConnectionEnvelope, ExecutionHost
from compute_provisioning.hosts.route_service import HostRouteService
from compute_provisioning.hosts.service import HostNotFoundError, PoolChangeRefusedError
from compute_provisioning.route_errors import ProvisioningRouteError

_CREATE = HostCreate(host_id="node-1", connection={"kind": "ssh", "public": {"ssh_host": "192.0.2.1"}})


def _execution_host(kind: str = "ssh") -> ExecutionHost:
    return ExecutionHost(
        host_id="node-1", pool_id="default", connection=ConnectionEnvelope(kind=kind, version=1)
    )


def _refusal(call) -> ProvisioningRouteError:
    with pytest.raises(ProvisioningRouteError) as refused:
        call()
    return refused.value


def test_a_duplicate_host_is_a_conflict_naming_the_host():
    hosts = MagicMock()
    hosts.register_host.side_effect = IntegrityError("INSERT", {}, Exception("UNIQUE"))

    refusal = _refusal(lambda: HostRouteService(hosts, {}).register_host(_CREATE))

    assert refusal.status_code == 409
    assert "node-1" in refusal.detail


def test_a_connection_its_codec_refuses_is_a_bad_request():
    hosts = MagicMock()
    hosts.register_host.side_effect = ValueError("ssh_host is required")

    assert _refusal(lambda: HostRouteService(hosts, {}).register_host(_CREATE)).status_code == 400


def test_a_refused_pool_move_is_a_conflict_carrying_the_subscriber_s_reason():
    """The move is well formed and may succeed once what the subscriber protects
    is gone, so it conflicts with current state rather than being a bad request."""
    hosts = MagicMock()
    hosts.update_host.side_effect = PoolChangeRefusedError("drain the relay first")

    refusal = _refusal(
        lambda: HostRouteService(hosts, {}).update_host("node-1", HostUpdate(pool_id="gpu"))
    )

    assert (refusal.status_code, refusal.detail) == (409, "drain the relay first")


def test_an_unknown_host_is_not_found_on_every_read_and_write():
    hosts = MagicMock()
    hosts.get_host.return_value = None
    hosts.update_host.side_effect = HostNotFoundError("node-1")
    hosts.enable_host.side_effect = HostNotFoundError("node-1")
    hosts.disable_host.side_effect = HostNotFoundError("node-1")
    service = HostRouteService(hosts, {})

    for call in (
        lambda: service.get_host("node-1"),
        lambda: service.update_host("node-1", HostUpdate(gpu_count=1)),
        lambda: service.set_enabled("node-1", True),
        lambda: service.set_enabled("node-1", False),
    ):
        assert _refusal(call).status_code == 404


def test_a_listing_includes_disabled_hosts_only_when_asked():
    hosts = MagicMock()
    hosts.list_hosts.return_value = []
    service = HostRouteService(hosts, {})

    service.list_hosts()
    service.list_hosts(search="node", include_disabled=True)

    assert [call.kwargs for call in hosts.list_hosts.call_args_list] == [
        {"search": None, "enabled_only": True},
        {"search": "node", "enabled_only": False},
    ]


@pytest.mark.asyncio
async def test_connectivity_probes_through_the_host_s_kind():
    hosts = MagicMock()
    hosts.lookup.return_value = _execution_host("ssh")
    probed: list[ExecutionHost] = []

    async def probe(host: ExecutionHost) -> ConnectivityResult:
        probed.append(host)
        return ConnectivityResult(host=host.host_id, reachable=False, detail="no route")

    result = await HostRouteService(hosts, {"ssh": probe}).check_connectivity("node-1")

    assert (result.reachable, probed) == (False, [hosts.lookup.return_value])


@pytest.mark.asyncio
async def test_a_kind_without_a_probe_is_refused_not_probed_another_way():
    hosts = MagicMock()
    hosts.lookup.return_value = _execution_host("redfish")

    async def ssh_probe(host):  # pragma: no cover - must not be called
        raise AssertionError("probed a redfish host over ssh")

    with pytest.raises(ProvisioningRouteError) as refused:
        await HostRouteService(hosts, {"ssh": ssh_probe}).check_connectivity("node-1")

    assert refused.value.status_code == 422


@pytest.mark.asyncio
async def test_connectivity_to_an_unknown_host_is_not_found():
    hosts = MagicMock()
    hosts.lookup.return_value = None

    with pytest.raises(ProvisioningRouteError) as refused:
        await HostRouteService(hosts, {}).check_connectivity("node-1")

    assert refused.value.status_code == 404
