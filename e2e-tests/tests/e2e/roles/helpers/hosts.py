"""Registering the hosts a compute scenario's capacity declarations name.

A declaration in a backed pool whose provider needs a host is admitted and
published only while the host it names is registered and enabled, so a
scenario registers each host such a declaration names before declaring it. A
declaration in an unbacked pool needs no registered host. Registration goes
through the provisioning service's family client.
"""

from __future__ import annotations

from typing import Any

from compute_provisioning_client import ComputeProvisioningError
from compute_provisioning_contracts import ConnectionSubmission, HostCreate, HostUpdate

#: The connection a host is registered with when the scenario reaches it through
#: the mock profile, which connects to nothing. A `key_path` connection names a
#: key file without carrying it, so no key material is needed. The service
#: accepts an `ssh` connection only at version 2.
PLACEHOLDER_CONNECTION = ConnectionSubmission(
    kind="ssh",
    version=2,
    public={"ssh_host": "127.0.0.1", "ssh_user": "e2e", "key_path": "/dev/null"},
)


def _connection_differs(stored: Any, wanted: ConnectionSubmission) -> bool:
    """Whether a stored connection is not the one ``wanted`` describes.

    Compared on the fields ``wanted`` states: a stored connection also carries
    the defaults its kind filled in, which a submission need not repeat.
    """
    if stored.kind != wanted.kind or stored.version != wanted.version:
        return True
    return any(stored.public.get(name) != value for name, value in wanted.public.items())


def register_e2e_host(
    provisioning_client: Any,
    *,
    name: str,
    pool_id: str,
    connection: ConnectionSubmission | None = None,
) -> Any:
    """Register one executor host into `pool_id`, idempotently.

    `connection` is how the provisioning service reaches the host. Omitted, the
    host gets a placeholder that nothing connects to: under the mock profile the
    host exists to be an executor identity, not to be reached.

    Reconciles rather than accepting what is there. A host may survive an earlier
    run against the same stack in a different pool, and the contract is that it
    exists *in the pool this scenario needs*. A host registered with a
    connection has that connection replaced when it differs, so a create is
    never sent to the address an earlier run left behind; without one, an
    existing host's connection is left as it is. A host an earlier run left
    disabled is enabled again, since a declaration naming a disabled host is
    neither admitted nor published. What the machine sells is its
    declaration's, never the host's.
    """
    try:
        existing = provisioning_client.get_host(name)
    except ComputeProvisioningError:
        existing = None

    if existing is None:
        provisioning_client.register_host(HostCreate(
            host_id=name,
            connection=connection or PLACEHOLDER_CONNECTION,
            pool_id=pool_id,
        ))
    else:
        replace = connection is not None and _connection_differs(existing.connection, connection)
        if replace or existing.pool_id != pool_id:
            provisioning_client.update_host(name, HostUpdate(
                pool_id=pool_id,
                **({"connection": connection} if replace else {}),
            ))
        if not provisioning_client.get_host(name).enabled:
            provisioning_client.enable_host(name)

    host = provisioning_client.get_host(name)
    assert host is not None, f"host {name!r} absent after registration"
    assert host.pool_id == pool_id, (
        f"host {name!r} is in pool {host.pool_id!r}, not {pool_id!r} — another "
        "scenario may be sharing this executor"
    )
    assert host.enabled, f"host {name!r} is still disabled after registration"
    return host
