"""The servicing worker's hooks follow the seller entry the Agreement selected.

The runtime composes each seller entry's obligation servicing and resolves the
one an obligation's accepted Agreement selected. These tests replace the
composed servicing with a recorder to show that routing, and that every refusal
happens before any servicing acts.
"""

from __future__ import annotations

import pytest
from settlement_compositions import ChainClient, EscrowOnChain
from test_alkahest_lifecycle import _record, _settled, _Site

from arkhai_bare_metal_storefront.settlement_stages import DeclinedServicing


class _Recorder:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    async def ready(self, record, worker_id):
        self.calls.append(("ready", record.obligation_ref))

    async def terminal(self, record, state, reason):
        self.calls.append(("terminal", state))


async def _runtime_with(tmp_path, servicing):
    runtime, _app, obligation_ref = await _settled(
        tmp_path, site=_Site("provisioning"), chain=ChainClient(), escrow=EscrowOnChain()
    )
    object.__setattr__(runtime, "obligation_servicing", servicing)
    return runtime, await _record(runtime, obligation_ref)


async def test_the_hooks_use_the_servicing_of_the_agreements_entry(tmp_path) -> None:
    alkahest, contact = _Recorder(), _Recorder()
    runtime, record = await _runtime_with(
        tmp_path, {"alkahest.v1": alkahest, "contact-exchange.v1": contact}
    )

    servicing = await runtime._accepted_servicing(record)
    await servicing.ready(record, "worker")
    await servicing.terminal(record, "expired", None)

    assert alkahest.calls == [("ready", record.obligation_ref), ("terminal", "expired")]
    assert contact.calls == []


async def test_an_entry_without_servicing_is_refused(tmp_path) -> None:
    contact = _Recorder()
    runtime, record = await _runtime_with(tmp_path, {"contact-exchange.v1": contact})

    with pytest.raises(RuntimeError, match="no bare-metal obligation servicing"):
        await runtime._accepted_servicing(record)
    assert contact.calls == []


async def test_an_obligation_naming_another_mechanism_is_refused(tmp_path) -> None:
    alkahest, contact = _Recorder(), _Recorder()
    runtime, record = await _runtime_with(
        tmp_path, {"alkahest.v1": alkahest, "contact-exchange.v1": contact}
    )
    relabelled = record.model_copy(
        update={"obligation": {**record.obligation, "mechanism": "contact-exchange.v1"}}
    )

    with pytest.raises(RuntimeError, match="another mechanism than its Agreement"):
        await runtime._accepted_servicing(relabelled)
    assert alkahest.calls == [] and contact.calls == []


async def test_a_declined_obligation_has_no_effect() -> None:
    declined = DeclinedServicing()

    assert await declined.ready(object(), "worker") is None
    assert await declined.terminal(object(), "expired", None) is None
