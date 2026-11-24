"""Connectivity and credential-free key discovery for SSH host records."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from typing import Any

from compute_provisioning.hosts import ExecutionHost
from compute_provisioning.hosts.route_service import HostKeyProbeResult
from compute_provisioning.hosts.service import ConnectionChangeRefusedError, HostNotFoundError
from compute_provisioning_contracts import ConnectivityHostKey, ConnectivityResult, HostKeyCaptureResponse

from .connection import ProtectedKeyUnreadableError
from .host_keys import HostKeyRefusal, key_fingerprint, observe_host_key
from .runner import AnsibleRunner, inventory_target

PROBE_INVENTORY_GROUP = "connectivity_probe"


def describe_host_pins(host: ExecutionHost) -> HostKeyCaptureResponse:
    target = inventory_target(host)
    return HostKeyCaptureResponse(
        endpoint=f"[{target.ssh_host}]:{target.ssh_port}",
        pinned_fingerprints=[key_fingerprint(pin) for pin in target.host_keys],
    )


async def scan_host_key(host: ExecutionHost) -> HostKeyProbeResult:
    target = inventory_target(host)
    try:
        discovery = await observe_host_key(target, pins=None, timeout_seconds=10)
    except HostKeyRefusal as exc:
        return HostKeyProbeResult(describe_host_pins(host).endpoint, reason=str(exc))
    if not discovery.verified or discovery.key is None:
        return HostKeyProbeResult(
            discovery.endpoint, reason=str(HostKeyRefusal(target, discovery.presented, discovery.reason))
        )
    return HostKeyProbeResult(
        discovery.endpoint, presented=discovery.presented, key=discovery.key
    )


async def probe_connectivity(
    runner: Any,
    host: ExecutionHost,
    *,
    adopt_host_key: Callable[[ExecutionHost, str], ExecutionHost] | None = None,
) -> ConnectivityResult:
    """Observe the host's identity before pinging it through a strict inventory."""
    real = issubclass(type(runner), AnsibleRunner)
    target = inventory_target(host, include_host_keys=real)
    status: ConnectivityHostKey | None = None
    if real:
        try:
            runner.validate_authentication_key(target)
        except ProtectedKeyUnreadableError as exc:
            return ConnectivityResult(
                host=host.host_id, reachable=False, detail=str(exc), host_key=None
            )
        try:
            discovery = await observe_host_key(
                target, pins=target.host_keys or None, timeout_seconds=10
            )
            if (
                host.host_key_adoption_pending and discovery.verified
                and discovery.key and adopt_host_key is not None
            ):
                try:
                    committed = adopt_host_key(host, discovery.key)
                except (ConnectionChangeRefusedError, HostNotFoundError):
                    raise HostKeyRefusal(target, discovery.presented, discovery.reason) from None
                current = inventory_target(committed)
                if (target.ssh_host, target.ssh_port) != (current.ssh_host, current.ssh_port):
                    raise HostKeyRefusal(current, discovery.presented)
                target = current
                if discovery.presented in {key_fingerprint(key) for key in target.host_keys}:
                    discovery = await observe_host_key(
                        target, pins=target.host_keys, timeout_seconds=10
                    )
                else:
                    discovery = replace(discovery, verified=False)
            if discovery.presented is not None:
                status = ConnectivityHostKey(
                    endpoint=discovery.endpoint,
                    pinned=bool(target.host_keys),
                    presented=discovery.presented,
                    matched=discovery.verified if target.host_keys else None,
                    pinned_fingerprints=[
                        key_fingerprint(key) for key in target.host_keys
                    ] if target.host_keys else None,
                )
            if not discovery.verified:
                raise HostKeyRefusal(target, discovery.presented, discovery.reason)
            if discovery.key is not None and not target.host_keys:
                target = replace(target, host_keys=(discovery.key,))
        except HostKeyRefusal as exc:
            return ConnectivityResult(
                host=host.host_id, reachable=False, detail=str(exc), host_key=status
            )

    try:
        inventory = runner.write_inventory([target], group=PROBE_INVENTORY_GROUP)
    except ProtectedKeyUnreadableError as exc:
        result = ConnectivityResult(host=host.host_id, reachable=False, detail=str(exc))
    else:
        with inventory:
            result = await runner.check_connectivity_with_inventory(host.host_id, inventory.path)
    return result.model_copy(update={"host_key": status}) if real else result


__all__ = ["PROBE_INVENTORY_GROUP", "describe_host_pins", "probe_connectivity", "scan_host_key"]
