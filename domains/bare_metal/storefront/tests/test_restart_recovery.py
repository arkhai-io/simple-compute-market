"""A storefront restarted over the same database converges without repeating.

Each test runs the production application, stops it at one point of a deal, and
builds a new application over the same database file, as a restarted process
would. The site and the chain are the same doubles across the restart, so what
they record counts every effect either process caused: one reservation, one
fulfillment, one evidence submission, one lease termination.
"""

from __future__ import annotations

from dataclasses import replace

from settlement_compositions import ChainClient, EscrowOnChain, StringObligations
from loopback import serving
from test_alkahest_lifecycle import (
    ATTESTATION_UID,
    _record,
    _settled,
    _Site,
    _stopped_after,
)
from test_http_settlement import BUYER, ESCROW_UID, _app, _buyer, _fulfillment_client

from arkhai_bare_metal_storefront.sqlite_client import SQLiteClient


def _restarted(runtime):
    """A new process's runtime: the same database file and authorities."""
    return replace(runtime, db=SQLiteClient(runtime.db.db_path, domain=runtime.domain))


async def test_a_restart_after_verification_delivers_once(tmp_path) -> None:
    site = _Site("provisioning", "provisioning", "active")
    chain = ChainClient(StringObligations(uid=ATTESTATION_UID))
    escrow = EscrowOnChain()
    runtime, _app_, obligation_ref = await _settled(
        tmp_path, site=site, chain=chain, escrow=escrow
    )
    capacity = runtime.capacity_client

    restarted = _restarted(runtime)
    app = _app(restarted)
    async with app.router.lifespan_context(app):
        # The buyer's retried settlement finds the same obligation.
        async with _buyer(app) as buyer:
            retried = await buyer.settle(
                ESCROW_UID, negotiation_id="neg-accepted", buyer_evm_address=BUYER
            )
        for _ in range(3):
            await restarted.settlement_worker.service_obligation(obligation_ref)

    assert retried.extra["obligation_ref"] == obligation_ref
    aggregate = await restarted.settlement_runtime.get_status("neg-accepted")
    assert [item.obligation_ref for item in aggregate.obligations if item.mechanism_ref] == [
        obligation_ref
    ]
    assert len(capacity.reserve_calls) == 1
    assert len(site.begin_calls) == 1
    assert len(chain.string_obligation.submitted) == 1
    record = await _record(restarted, obligation_ref)
    assert record.fulfillment_ref == ATTESTATION_UID
    assert record.collection_state == "succeeded"


async def test_a_restart_after_a_recorded_publication_never_publishes_again(
    tmp_path,
) -> None:
    site = _Site("provisioning", "active")
    chain = ChainClient(StringObligations(uid="0x" + "99" * 32))
    runtime, _app_, obligation_ref = await _settled(
        tmp_path, site=site, chain=chain, escrow=EscrowOnChain()
    )
    await _stopped_after(runtime, obligation_ref, reference=ATTESTATION_UID)

    restarted = _restarted(runtime)
    app = _app(restarted)
    async with app.router.lifespan_context(app):
        await restarted.settlement_worker.service_obligation(obligation_ref)

    assert chain.string_obligation.submitted == []
    assert (await _record(restarted, obligation_ref)).fulfillment_ref == ATTESTATION_UID


async def test_a_restart_after_teardown_ends_the_lease_once(tmp_path) -> None:
    site = _Site("active")
    runtime, _app_, _obligation_ref = await _settled(
        tmp_path,
        site=site,
        chain=ChainClient(StringObligations(uid=ATTESTATION_UID)),
        escrow=EscrowOnChain(),
    )
    with serving(_app(runtime)) as base_url:
        first = _fulfillment_client(base_url).teardown("neg-accepted")

    restarted = _restarted(runtime)
    with serving(_app(restarted)) as base_url:
        retried = _fulfillment_client(base_url).teardown("neg-accepted")

    assert first["state"] == "terminating"
    assert retried["negotiation_id"] == "neg-accepted"
    assert site.terminations == [("reservation-a", "buyer_teardown")]
