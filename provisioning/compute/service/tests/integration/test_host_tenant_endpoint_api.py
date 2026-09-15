"""A host's tenant-facing endpoint through the typed host API.

Set, leave untouched, clear, read back, and render: the buyer-facing endpoint
must return to the management fallback when an operator removes it, and must
not change when an update omits it.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from compute_provisioning_service import container as _container_module
from vm_provisioning_operator.models import HostCreate, HostUpdate


async def test_tenant_endpoint_set_clear_readback_and_render(client_and_queue):
    client, _ = client_and_queue
    await client.register_host(HostCreate(
        name="bm-endpoint",
        kvm_host="10.0.0.5",
        ssh_port=6001,
        public_host="192.0.2.50",
        public_port=2222,
        ssh_user="svc",
        ssh_key_type="path",
        ssh_key_value="/k",
    ))

    untouched = await client.update_host("bm-endpoint", HostUpdate(ssh_port=6005))
    assert (untouched.public_host, untouched.public_port) == ("192.0.2.50", 2222)

    port_cleared = await client.update_host("bm-endpoint", HostUpdate(public_port=None))
    assert (port_cleared.public_host, port_cleared.public_port) == ("192.0.2.50", None)

    host_cleared = await client.update_host("bm-endpoint", HostUpdate(public_host=None))
    assert (host_cleared.public_host, host_cleared.public_port) == (None, None)

    readback = await client.get_host("bm-endpoint")
    assert (readback.public_host, readback.public_port) == (None, None)
    assert (readback.kvm_host, readback.ssh_port) == ("10.0.0.5", 6005)

    host_service = _container_module.resolved_host_service
    ini = host_service.render_inventory_ini([host_service.get_host("bm-endpoint")])
    assert "public_host=" not in ini
    assert "public_port=" not in ini
    assert "ansible_host=10.0.0.5" in ini
    assert "ansible_port=6005" in ini

    reconfigured = await client.update_host("bm-endpoint", HostUpdate(public_port=2200))
    assert reconfigured.public_port == 2200


@pytest.mark.parametrize("bad_port", [0, 65536])
def test_out_of_range_tenant_ports_are_rejected_before_sending(bad_port):
    with pytest.raises(ValidationError):
        HostUpdate(public_port=bad_port)
    with pytest.raises(ValidationError):
        HostCreate(name="bm", kvm_host="10.0.0.5", ssh_key_value="/k", public_port=bad_port)
