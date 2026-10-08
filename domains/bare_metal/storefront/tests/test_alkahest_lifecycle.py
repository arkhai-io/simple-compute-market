"""Delivering an Alkahest-settled deal through the servicing worker.

Each test settles a seeded accepted deal through the storefront's own routes,
then drives the runtime's composed worker. The settlement repository, the
fulfillment service, the evidence store, and the Alkahest publisher are the
production ones; the site and the chain are doubled at their clients.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import replace
from datetime import datetime, timezone

import httpx
import pytest
from market_identity import (
    EMPTY_BODY,
    Eip191Signer,
    RequestEnvelope,
    TrustedIdentitySet,
    canonical_body_hash,
    sign_request,
)
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
from storefront_client import StorefrontClient
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
            settled = await buyer.settle(
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

    await runtime.alkahest_lifecycle.end_service(record, state, None)

    assert site.terminations == (
        [("reservation-a", f"settlement_{state}")] if terminated else []
    )


async def test_a_parked_obligation_does_not_end_the_lease(tmp_path) -> None:
    site = _Site("provisioning")
    runtime, _app_, obligation_ref = await _settled(
        tmp_path, site=site, chain=ChainClient(), escrow=EscrowOnChain()
    )

    await runtime.alkahest_lifecycle.end_service(
        await _record(runtime, obligation_ref), "manual_required", "parked"
    )

    assert site.terminations == []


# -- evidence resolution ------------------------------------------------------


def _signed(signer, role: str, digest: str) -> dict[str, str]:
    signed = sign_request(
        signer=signer,
        envelope=RequestEnvelope(
            role=role,
            principal=signer.identity,
            method="GET",
            operation="resolve_bare_metal_lease_ready_evidence",
            resource=digest,
            request_id=f"test-{uuid.uuid4().hex}",
            timestamp=int(time.time()),
            body_hash=canonical_body_hash(EMPTY_BODY),
        ),
    )
    return {
        "X-Market-Signature-Version": signed.protocol,
        "X-Market-Identity-Scheme": signed.principal.scheme.value,
        "X-Market-Identity-Identifier": signed.principal.identifier,
        "X-Market-Role": signed.role,
        "X-Market-Request-ID": signed.request_id,
        "X-Market-Timestamp": str(signed.timestamp),
        "X-Market-Signature": signed.proof.value,
    }


async def test_alkahest_evidence_is_served_only_to_the_deals_parties(tmp_path) -> None:
    chain = ChainClient(StringObligations(uid=ATTESTATION_UID))
    runtime, app, obligation_ref = await _settled(
        tmp_path, site=_Site("active"), chain=chain, escrow=EscrowOnChain()
    )
    [(data, _ref)] = chain.string_obligation.submitted
    digest = data.removeprefix("sha256:")
    path = f"/api/v1/evidence/bare-metal/{digest}"
    stranger = Eip191Signer(bytes.fromhex("77" * 32))

    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://seller"
        ) as client:
            unsigned = await client.get(path)
            as_buyer = await client.get(path, headers=_signed(BUYER_SIGNER, "buyer", digest))
            as_admin = await client.get(path, headers=_signed(ADMIN_SIGNER, "admin", digest))
            as_stranger = await client.get(
                path, headers=_signed(stranger, "buyer", digest)
            )
            as_authority = await client.get(
                path, headers=_signed(stranger, "authority", digest)
            )

    assert unsigned.status_code == 401
    assert as_buyer.status_code == 200
    assert as_admin.status_code == 200
    body = as_buyer.json()
    assert body["evidence"]["condition_anchor"] == ESCROW_UID
    assert as_stranger.status_code == 403
    # No hosted authority takes part in an Alkahest deal.
    assert as_authority.status_code == 403



def test_hosted_evidence_is_also_readable_by_the_trusted_hosted_authority(
    tmp_path,
) -> None:
    from arkhai_bare_metal import BareMetalLeaseReadyEvidence, CanonicalPrincipal
    from settlement_compositions import hosted_composition

    from arkhai_bare_metal_storefront.api import _evidence_readers
    from arkhai_bare_metal_storefront.domain_runtime import get_market_domain_contract
    from arkhai_bare_metal_storefront.runtime import BareMetalStorefrontRuntime
    from arkhai_bare_metal_storefront.sqlite_client import SQLiteClient

    domain = get_market_domain_contract()
    runtime = BareMetalStorefrontRuntime(
        db=SQLiteClient(str(tmp_path / "storefront.db"), domain=domain),
        domain=domain,
        seller_principal=SELLER_SIGNER.identity,
        admin_principals=TrustedIdentitySet(identities=(ADMIN_SIGNER.identity,)),
        storefront_url="http://seller:8000",
        marketplace_signer=SELLER_SIGNER,
        settlement_composition=hosted_composition(SELLER_SIGNER),
    )
    buyer = CanonicalPrincipal(
        scheme=BUYER_SIGNER.identity.scheme.value,
        identifier=BUYER_SIGNER.identity.identifier,
    )
    # Only the fields the readers depend on; the route validates stored evidence.
    hosted = BareMetalLeaseReadyEvidence.model_construct(
        accepted_binding_kind="bare_metal.accepted-hosted-binding.v1",
        buyer_principal=buyer,
    )
    alkahest = BareMetalLeaseReadyEvidence.model_construct(
        accepted_binding_kind="bare_metal.accepted-alkahest-binding.v1",
        buyer_principal=buyer,
    )

    hosted_readers = _evidence_readers(runtime, hosted)
    alkahest_readers = _evidence_readers(runtime, alkahest)

    assert hosted_readers["authority"] == (SELLER_SIGNER.identity,)
    assert "authority" not in alkahest_readers
    assert hosted_readers["buyer"] == alkahest_readers["buyer"] == (BUYER_SIGNER.identity,)
    assert hosted_readers["admin"] == (ADMIN_SIGNER.identity,)
