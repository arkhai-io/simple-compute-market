"""The Ansible implementation's connectivity probe.

``probe_connectivity`` runs ``ansible -m ping`` against one registered host,
rendered from its connection the way a job's inventory is. The composition root
registers it as the ``ssh`` connection kind's probe.
"""

from __future__ import annotations

from typing import Any

from compute_provisioning.hosts import ExecutionHost

from compute_provisioning_contracts import ConnectivityResult

from .connection import ProtectedKeyUnreadableError
from .runner import inventory_target

#: The inventory group a connectivity probe lists its one host under. A ping
#: names the host itself, so the group only has to exist.
PROBE_INVENTORY_GROUP = "connectivity_probe"


async def probe_connectivity(runner: Any, host: ExecutionHost) -> ConnectivityResult:
    """Ping one registered host through an inventory rendered from its connection.

    The inventory, and any key decrypted for it, is removed when the probe ends.
    A host whose protected key cannot be decrypted is answered unreachable, with
    the error's message as the detail, and no ping runs: a host's state is a
    result, not a refusal.
    """
    target = inventory_target(host)
    try:
        inventory = runner.write_inventory([target], group=PROBE_INVENTORY_GROUP)
    except ProtectedKeyUnreadableError as exc:
        return ConnectivityResult(host=host.host_id, reachable=False, detail=str(exc))
    with inventory:
        return await runner.check_connectivity_with_inventory(host.host_id, inventory.path)


__all__ = [
    "PROBE_INVENTORY_GROUP",
    "probe_connectivity",
]
