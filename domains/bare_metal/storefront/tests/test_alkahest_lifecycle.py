"""Delivering an Alkahest-settled deal through the servicing worker.

Each test settles a seeded accepted deal through the storefront's own routes,
then drives the runtime's composed worker. The settlement repository, the
fulfillment service, the evidence store, and the Alkahest publisher are the
production ones; the site and the chain are doubled at their clients.
"""

from __future__ import annotations

import json
import logging
from dataclasses import replace
from datetime import datetime, timezone

import httpx
import pytest
from market_identity import Eip191Signer, TrustedIdentitySet
from market_settlement_runtime import (
    FULFILLMENT_REFERENCE_KEY,
    MANUAL_REASON_KEY,
    SettlementObligationRecord,
)
from settlement_compositions import (
    ChainClient,
    EscrowOnChain,
    StringObligations,
    alkahest_composition,
)
from loopback import serving
from storefront_client import StorefrontClient
from arkhai_bare_metal.evidence_routes import BareMetalEvidenceClient, evidence_path
from storefront_client.client import StorefrontClientError
from test_http_settlement import (
    ADMIN_SIGNER,
    BUYER,
    BUYER_SIGNER,
    ESCROW_UID,
    SELLER_SIGNER,
    _accepted_runtime,
    _app,
    _buyer,
    _CapacityClient,
    _fulfillment_client,
    _ProvisioningClient,
)

from arkhai_bare_metal_storefront.alkahest_lifecycle import (
    OUTCOME_UNKNOWN,
    REJECTED,
    REJECTION_BOUND,
)

ATTESTATION_UID = "0x" + "cd" * 32


class _Site(_ProvisioningClient):
    """The site's provisioning client, with the states it reports in turn and a
    lease that can be ended."""

    def __init__(self, *states: str) -> None:
        super().__init__()
        self.states = list(states) or ["active"]
        self.terminations: list[tuple[str, str | None]] = []
        # Access became ready now, inside the lease the deal is about to commit;
        # the site reports the same moment on every read.
        self.ready_at = datetime.now(timezone.utc).isoformat()

    async def get_fulfillment_status(self, fulfillment_id, **request):
        state = self.states.pop(0) if len(self.states) > 1 else self.states[0]
        return type(
            "Status", (), {"state": state, "failure_reason": None, "failure_message": None}
        )()

    async def get_fulfillment_result(self, fulfillment_id, **request):
        envelope = await super().get_fulfillment_result(fulfillment_id, **request)
        envelope.payload["domain_result"]["payload"]["ready_at"] = self.ready_at
        return envelope

    async def terminate_lease(self, capacity_reservation_id, *, reason=None):
        self.terminations.append((capacity_reservation_id, reason))
        return {"capacity_reservation_id": capacity_reservation_id, "state": "terminating"}


async def _settled(tmp_path, *, site: _Site, chain: ChainClient, escrow: EscrowOnChain):
    """A deal settled through the routes, on a runtime over the given doubles."""

    async def verifier(**_kwargs):
        return 1

    runtime, negotiation_id = await _accepted_runtime(
        str(tmp_path / "storefront.db"), verifier
    )
    runtime = replace(
        runtime,
        capacity_client=_CapacityClient(),
        fulfillment_client=site,
        settlement_composition=alkahest_composition(
            SELLER_SIGNER,
            wallet="0x3333333333333333333333333333333333333333",
            chain_clients={"anvil": chain},
            escrow=escrow,
        ),
    )
    app = _app(runtime)
    async with app.router.lifespan_context(app):
        async with _buyer(app) as buyer:
            settled = await buyer.settle_evm(
                ESCROW_UID, negotiation_id=negotiation_id, buyer_evm_address=BUYER
            )
    return runtime, app, settled.extra["obligation_ref"]


async def _record(runtime, obligation_ref) -> SettlementObligationRecord:
    return SettlementObligationRecord.model_validate(
        await runtime.settlement_repository.load_settlement_obligation(obligation_ref)
    )


async def _fulfill_operation(runtime, obligation_ref) -> dict:
    return await runtime.settlement_repository.load_settlement_operation(
        obligation_ref, "fulfill"
    )


async def test_the_deal_waits_for_its_lease_then_publishes_its_digest_and_is_collected(
    tmp_path,
) -> None:
    chain = ChainClient(StringObligations(uid=ATTESTATION_UID))
    escrow = EscrowOnChain()
    runtime, _app_, obligation_ref = await _settled(
        tmp_path, site=_Site("provisioning", "active"), chain=chain, escrow=escrow
    )

    # Verification stepped the worker once: delivery began, the lease is not
    # yet active, and nothing was published.
    assert chain.string_obligation.submitted == []
    assert (await _record(runtime, obligation_ref)).fulfillment_ref is None
    assert (await _fulfill_operation(runtime, obligation_ref))["state"] == "pending"

    for _ in range(3):
        await runtime.settlement_worker.service_obligation(obligation_ref)

    record = await _record(runtime, obligation_ref)
    assert record.fulfillment_ref == ATTESTATION_UID
    assert ("check", ATTESTATION_UID) in escrow.calls
    assert ("collect", ATTESTATION_UID) in escrow.calls
    assert record.collection_state == "succeeded"
    # Only the digest went on chain, against the escrow; the body stays here.
    [(data, ref_uid)] = chain.string_obligation.submitted
    assert ref_uid == ESCROW_UID
    assert data.startswith("sha256:") and len(data) == len("sha256:") + 64
    evidence = await runtime.db.load_bare_metal_lease_ready_evidence(evidence_digest=data)
    assert evidence is not None
    assert evidence.accepted_binding_kind == "bare_metal.accepted-alkahest-binding.v1"
    assert evidence.condition_anchor == ESCROW_UID
    assert evidence.buyer_principal.identifier == BUYER_SIGNER.identity.identifier


async def test_a_submission_that_never_left_is_withdrawn_and_retried(tmp_path) -> None:
    class Unsendable:
        string_obligation = None

    runtime, _app_, obligation_ref = await _settled(
        tmp_path, site=_Site("active"), chain=Unsendable(), escrow=EscrowOnChain()
    )

    operation = await _fulfill_operation(runtime, obligation_ref)
    assert operation["state"] == "pending"
    assert operation["receipt"] is None
    assert "not_submitted" in operation["last_error"]
    assert await runtime.settlement_runtime.manual_required_count() == 0


async def test_a_rejected_submission_is_retried_then_left_to_an_operator(tmp_path) -> None:
    chain = ChainClient(StringObligations(raises=RuntimeError("execution reverted")))
    runtime, _app_, obligation_ref = await _settled(
        tmp_path, site=_Site("active"), chain=chain, escrow=EscrowOnChain()
    )

    for _ in range(REJECTION_BOUND):
        await runtime.settlement_worker.service_obligation(obligation_ref)

    assert len(chain.string_obligation.submitted) == REJECTION_BOUND
    operation = await _fulfill_operation(runtime, obligation_ref)
    assert operation["state"] == "manual_required"
    record = await _record(runtime, obligation_ref)
    assert record.mechanism_state[MANUAL_REASON_KEY] == REJECTED
    assert await runtime.settlement_runtime.manual_required_count() == 1


async def test_an_unknown_outcome_parks_and_is_never_submitted_again(tmp_path) -> None:
    chain = ChainClient(StringObligations(raises=TimeoutError("receipt not received")))
    runtime, app, obligation_ref = await _settled(
        tmp_path, site=_Site("active"), chain=chain, escrow=EscrowOnChain()
    )
    await runtime.settlement_worker.service_obligation(obligation_ref)

    assert len(chain.string_obligation.submitted) == 1
    record = await _record(runtime, obligation_ref)
    assert record.mechanism_state[MANUAL_REASON_KEY] == OUTCOME_UNKNOWN
    assert record.fulfillment_ref is None

    async with app.router.lifespan_context(app):
        async with StorefrontClient(
            "http://seller",
            signer=ADMIN_SIGNER,
            caller_role="admin",
            expected_publishers=TrustedIdentitySet(identities=(SELLER_SIGNER.identity,)),
            transport=httpx.ASGITransport(app=app),
        ) as admin:
            status = await admin.get_system_status()
    assert status.settlement_manual_required == 1


async def _stopped_after(runtime, obligation_ref, *, reference: str | None) -> None:
    """Leave the journal as a process that stopped mid-publication would:
    the submission recorded, the reference recorded or not, the lease freed."""
    record = await _record(runtime, obligation_ref)
    principal = record.claimant_principal
    reserved = await runtime.settlement_runtime.reserve_fulfillment(
        obligation_ref, local_principal=principal, worker_id="stopped"
    )
    assert reserved.status == "pending"
    await runtime.settlement_runtime.record_fulfillment_submission(
        obligation_ref,
        {"evidence_digest": "sha256:" + "ee" * 32},
        local_principal=principal,
        worker_id="stopped",
    )
    if reference is not None:
        await runtime.settlement_runtime.record_fulfillment_publication(
            obligation_ref, reference, local_principal=principal, worker_id="stopped"
        )
    await runtime.settlement_runtime.retry_fulfillment(
        obligation_ref,
        RuntimeError("process stopped"),
        local_principal=principal,
        worker_id="stopped",
    )


async def test_a_restart_after_an_unrecorded_submission_parks_without_submitting(
    tmp_path,
) -> None:
    chain = ChainClient(StringObligations(uid=ATTESTATION_UID))
    # The site is not yet active, so verification's own step submits nothing.
    runtime, _app_, obligation_ref = await _settled(
        tmp_path, site=_Site("provisioning", "active"), chain=chain, escrow=EscrowOnChain()
    )
    await _stopped_after(runtime, obligation_ref, reference=None)

    await runtime.settlement_worker.service_obligation(obligation_ref)

    assert chain.string_obligation.submitted == []
    record = await _record(runtime, obligation_ref)
    assert record.mechanism_state[MANUAL_REASON_KEY] == OUTCOME_UNKNOWN
    assert record.fulfillment_ref is None


async def test_a_restart_after_a_recorded_publication_completes_without_submitting(
    tmp_path,
) -> None:
    chain = ChainClient(StringObligations(uid="0x" + "99" * 32))
    runtime, _app_, obligation_ref = await _settled(
        tmp_path, site=_Site("provisioning", "active"), chain=chain, escrow=EscrowOnChain()
    )
    await _stopped_after(runtime, obligation_ref, reference=ATTESTATION_UID)

    await runtime.settlement_worker.service_obligation(obligation_ref)

    assert chain.string_obligation.submitted == []
    record = await _record(runtime, obligation_ref)
    assert record.fulfillment_ref == ATTESTATION_UID
    operation = await _fulfill_operation(runtime, obligation_ref)
    assert operation["receipt"] == {"fulfillment_ref": ATTESTATION_UID}
    assert FULFILLMENT_REFERENCE_KEY not in operation["receipt"]


@pytest.mark.parametrize(
    ("state", "terminated"),
    [("reclaimed", True), ("expired", True), ("failed", True), ("collected", False)],
)
async def test_an_uncollected_settlement_ends_the_lease_once_delivery_began(
    tmp_path, state, terminated
) -> None:
    site = _Site("provisioning")
    runtime, _app_, obligation_ref = await _settled(
        tmp_path, site=site, chain=ChainClient(), escrow=EscrowOnChain()
    )
    record = await _record(runtime, obligation_ref)

    await runtime.obligation_servicing["alkahest.v1"].terminal(record, state, None)

    assert site.terminations == (
        [("reservation-a", f"settlement_{state}")] if terminated else []
    )


async def test_a_parked_obligation_does_not_end_the_lease(tmp_path) -> None:
    site = _Site("provisioning")
    runtime, _app_, obligation_ref = await _settled(
        tmp_path, site=site, chain=ChainClient(), escrow=EscrowOnChain()
    )

    await runtime.obligation_servicing["alkahest.v1"].terminal(
        await _record(runtime, obligation_ref), "manual_required", "parked"
    )

    assert site.terminations == []


async def test_passes_spent_waiting_for_the_lease_do_not_count_as_rejections(
    tmp_path,
) -> None:
    chain = ChainClient(StringObligations(raises=RuntimeError("execution reverted")))
    runtime, _app_, obligation_ref = await _settled(
        tmp_path,
        site=_Site("provisioning", "provisioning", "provisioning", "active"),
        chain=chain,
        escrow=EscrowOnChain(),
    )
    # Verification's step and two more passes find the lease not yet active.
    for _ in range(2):
        await runtime.settlement_worker.service_obligation(obligation_ref)
    assert chain.string_obligation.submitted == []

    # The first refusal, on the fourth pass, is one rejection, not a fourth.
    await runtime.settlement_worker.service_obligation(obligation_ref)

    assert len(chain.string_obligation.submitted) == 1
    assert (await _fulfill_operation(runtime, obligation_ref))["state"] == "pending"
    assert await runtime.settlement_runtime.manual_required_count() == 0

    for _ in range(REJECTION_BOUND - 1):
        await runtime.settlement_worker.service_obligation(obligation_ref)

    assert len(chain.string_obligation.submitted) == REJECTION_BOUND
    record = await _record(runtime, obligation_ref)
    assert record.mechanism_state[MANUAL_REASON_KEY] == REJECTED


# -- servicing cadence and reporting, through the storefront's routes ---------


async def test_a_deal_awaiting_its_lease_is_due_on_each_servicing_cycle(
    tmp_path,
) -> None:
    """A deal whose lease is not yet active is rechecked by the next cycle the
    administrator steps, not backed off, and publishes once the lease is."""
    chain = ChainClient(StringObligations(uid=ATTESTATION_UID))
    runtime, app, obligation_ref = await _settled(
        tmp_path,
        site=_Site("provisioning", "provisioning", "active"),
        chain=chain,
        escrow=EscrowOnChain(),
    )
    assert chain.string_obligation.submitted == []

    async with app.router.lifespan_context(app):
        async with _storefront_client(app, ADMIN_SIGNER, "admin") as admin:
            await admin.admin_pause_lifecycle_loops()
            cycles = [
                await admin.admin_run_lifecycle_cycle("settlement-servicing")
                for _ in range(2)
            ]

    assert [cycle["processed"] for cycle in cycles] == [1, 1]
    assert len(chain.string_obligation.submitted) == 1
    assert (await _record(runtime, obligation_ref)).fulfillment_ref == ATTESTATION_UID


async def test_a_failing_servicing_step_writes_a_claims_stage_event(
    tmp_path, caplog
) -> None:
    chain = ChainClient(StringObligations(raises=RuntimeError("execution reverted")))

    with caplog.at_level(logging.INFO, logger="stage"):
        _runtime, _app_, obligation_ref = await _settled(
            tmp_path, site=_Site("active"), chain=chain, escrow=EscrowOnChain()
        )

    events = [json.loads(r.getMessage()) for r in caplog.records if r.name == "stage"]
    retries = [
        e for e in events if e["stage"] == "claims" and e["event"] == "settlement_retry"
    ]
    assert [(e["obligation_ref"], e["operation"]) for e in retries] == [
        (obligation_ref, "fulfill")
    ]


class _FlakySite(_Site):
    """A site whose next ``failing_reads`` status reads fail, when the test
    sets them."""

    def __init__(self, *states: str) -> None:
        super().__init__(*states)
        self.failing_reads = 0

    async def get_fulfillment_status(self, fulfillment_id, **request):
        if self.failing_reads:
            self.failing_reads -= 1
            raise ConnectionError("site unreachable")
        return await super().get_fulfillment_status(fulfillment_id, **request)


async def _waited(tmp_path, *, failing_reads: int, timeout: float):
    site = _FlakySite("active")
    _runtime, app, _obligation_ref = await _settled(
        tmp_path, site=site, chain=ChainClient(StringObligations(uid=ATTESTATION_UID)),
        escrow=EscrowOnChain(),
    )
    site.failing_reads = failing_reads

    async with app.router.lifespan_context(app):
        async with _storefront_client(app, ADMIN_SIGNER, "admin") as admin:
            await admin.admin_pause_lifecycle_loops()
            waited = await admin.wait_for_settlement(ESCROW_UID, timeout=timeout)
    return site, waited


async def test_the_settle_wait_reports_ready_through_one_failed_status_read(
    tmp_path,
) -> None:
    site, waited = await _waited(tmp_path, failing_reads=1, timeout=5.0)

    assert site.failing_reads == 0
    assert waited.ready is True
    assert waited.last_error is None


async def test_a_settle_wait_whose_every_read_fails_reports_the_last_error(
    tmp_path,
) -> None:
    _site, waited = await _waited(tmp_path, failing_reads=10**6, timeout=1.5)

    assert waited.ready is False
    assert "site unreachable" in (waited.last_error or "")


# -- evidence resolution ------------------------------------------------------


def _storefront_client(app, signer, role: str) -> StorefrontClient:
    return StorefrontClient(
        "http://seller",
        signer=signer,
        caller_role=role,
        expected_publishers=TrustedIdentitySet(identities=(SELLER_SIGNER.identity,)),
        transport=httpx.ASGITransport(app=app),
    )


async def _resolve(app, signer, role: str, digest: str):
    async with _storefront_client(app, signer, role) as client:
        return await BareMetalEvidenceClient(client, role=role).lease_ready_evidence(
            digest
        )


async def test_alkahest_evidence_is_served_only_to_the_deals_parties(tmp_path) -> None:
    chain = ChainClient(StringObligations(uid=ATTESTATION_UID))
    runtime, app, _obligation_ref = await _settled(
        tmp_path, site=_Site("active"), chain=chain, escrow=EscrowOnChain()
    )
    [(digest, _ref)] = chain.string_obligation.submitted
    stranger = Eip191Signer(bytes.fromhex("77" * 32))
    refused: dict[str, int] = {}

    async with app.router.lifespan_context(app):
        as_buyer = await _resolve(app, BUYER_SIGNER, "buyer", digest)
        as_claimant = await _resolve(app, SELLER_SIGNER, "seller", digest)
        as_admin = await _resolve(app, ADMIN_SIGNER, "admin", digest)
        for name, signer, role in (
            ("stranger", stranger, "buyer"),
        ):
            with pytest.raises(StorefrontClientError) as raised:
                await _resolve(app, signer, role, digest)
            refused[name] = raised.value.status_code
        with pytest.raises(StorefrontClientError) as missing:
            await _resolve(app, BUYER_SIGNER, "buyer", "sha256:" + "00" * 32)
        # Malformed authentication stays on raw HTTP: an unsigned request.
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://seller"
        ) as raw:
            unsigned = await raw.get(evidence_path(digest))

    assert as_buyer == as_claimant == as_admin
    assert as_buyer.evidence.condition_anchor == ESCROW_UID
    assert as_buyer.evidence.evidence_digest == digest
    assert as_buyer.evidence.accepted_binding_kind == (
        "bare_metal.accepted-alkahest-binding.v1"
    )
    assert refused == {"stranger": 403}
    assert missing.value.status_code == 404
    assert unsigned.status_code == 401


async def test_the_buyers_fulfillment_status_names_the_published_evidence(
    tmp_path,
) -> None:
    chain = ChainClient(StringObligations(uid=ATTESTATION_UID))
    runtime, _app_, obligation_ref = await _settled(
        tmp_path, site=_Site("provisioning", "active"), chain=chain, escrow=EscrowOnChain()
    )
    with serving(_app(runtime)) as base_url:
        before = _fulfillment_client(base_url).status("neg-accepted")
    for _ in range(3):
        await runtime.settlement_worker.service_obligation(obligation_ref)
    with serving(_app(runtime)) as base_url:
        after = _fulfillment_client(base_url).status("neg-accepted")

    [(published, _ref_uid)] = chain.string_obligation.submitted
    assert before["evidence_digest"] is None
    assert after["evidence_digest"] == published
    assert before["evidence_attestation_uid"] is None
    assert after["evidence_attestation_uid"] == ATTESTATION_UID


async def test_a_rejected_publication_reports_its_digest_but_no_attestation(
    tmp_path,
) -> None:
    """The stored digest is not publication: only the chain's acceptance names one."""
    chain = ChainClient(StringObligations(raises=RuntimeError("execution reverted")))
    runtime, _app_, obligation_ref = await _settled(
        tmp_path, site=_Site("active"), chain=chain, escrow=EscrowOnChain()
    )
    await runtime.settlement_worker.service_obligation(obligation_ref)
    with serving(_app(runtime)) as base_url:
        status = _fulfillment_client(base_url).status("neg-accepted")

    assert chain.string_obligation.submitted
    assert status["evidence_digest"] is not None
    assert status["evidence_attestation_uid"] is None
    assert await runtime.settlement_runtime.manual_required_count() == 0
