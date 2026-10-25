"""Delivery of an escrow deal against real storefront persistence and the real settlement journal.

Issuance whose outcome is unknown stays open and is re-driven under the same
fulfillment identity; the attestation is submitted at most once, and an
attestation whose outcome is unknown, or a submission an attempt finds with no
reference, waits for an operator with the delivered credential kept privately.
"""

from __future__ import annotations

import asyncio
import sqlite3
from types import SimpleNamespace

import httpx
import pytest
from arkhai_api.issuance import IssuanceRequest, issuance_result_model
from arkhai_api_client import AuthorityError
from arkhai_api_selling.evidence_store import IssuanceEvidenceRepository, IssuanceEvidenceService
from arkhai_api_selling.issuance import fulfill_from_hold, project_progress
from arkhai_api_selling.persistence import StorefrontSQLiteClient
from arkhai_api_selling.settlement_composition import persist_settlement_outcome
from market_alkahest import RECIPIENT_RELEASE
from market_identity import TrustedIdentitySet
from market_settlement_runtime import (
    MANUAL_REASON_KEY,
    PreparedSettlement,
    SettlementRuntime,
    SettlementSQLiteRepository,
)

from arkhai_api_selling_alkahest.stage import (
    OUTCOME_UNKNOWN,
    AlkahestFulfillmentInput,
    AlkahestSellerStage,
)
from tests.bundles import BUYER, ESCROW_UID, EXAMPLE, LISTING, NEGOTIATION, SELLER, accepted_deal, obligation

IssuanceResult = issuance_result_model(EXAMPLE.label)


class Authority:
    """The authority as the stage's client sees it: each scripted answer once, then a grant.

    A replay of a new-key grant rotates its secret, as the authority's does.
    """

    def __init__(self, *answers) -> None:
        self._answers = list(answers)
        self.requests: list[IssuanceRequest] = []
        self.committed: set[str] = set()
        self.rollbacks: list[dict] = []

    async def submit_issuance(self, request: IssuanceRequest) -> IssuanceResult:
        self.requests.append(request)
        answer = self._answers.pop(0) if self._answers else "grant"
        if answer == "commit_then_lose":
            self.committed.add(request.fulfillment_id)
            raise httpx.RemoteProtocolError("server disconnected without sending a response")
        if isinstance(answer, BaseException):
            raise answer
        already = request.fulfillment_id in self.committed
        self.committed.add(request.fulfillment_id)
        return IssuanceResult(
            fulfillment_id=request.fulfillment_id, grant_id=request.fulfillment_id,
            negotiation_id=request.negotiation_id, owner=request.owner, service=request.service,
            resource_id=request.resource_id, quantity=request.quantity, key_mode=request.key.mode,
            key_id="ak_new", balance=request.quantity, request_digest=request.request_digest,
            committed_at_unix=1_790_000_000, capacity_reservation_id=request.capacity_reservation_id,
            already_issued=already, secret=f"ak_new.s3cret-{len(self.requests)}",
        )

    async def rollback_issuance(self, **kwargs):
        self.rollbacks.append(kwargs)
        return {"rolled_back": True}


class Chain:
    """The chain client's string obligation, scripted per call."""

    def __init__(self, *answers) -> None:
        self._answers = list(answers)
        self.submissions: list[tuple[str, str]] = []
        self.string_obligation = SimpleNamespace(do_obligation=self._submit)

    async def _submit(self, data: str, anchor: str) -> str:
        self.submissions.append((data, anchor))
        answer = self._answers.pop(0) if self._answers else "0xattestation"
        if isinstance(answer, BaseException):
            raise answer
        return answer


class Harness:
    def __init__(self, tmp_path, authority: Authority) -> None:
        self.db = StorefrontSQLiteClient(str(tmp_path / "storefront.db"), EXAMPLE)
        self.repository = SettlementSQLiteRepository(self.db.db_path, apply_migrations=False)
        self.runtime = SettlementRuntime(self.repository, {})
        self.authority = authority
        self.events: list[tuple[str, str]] = []
        self.failures: list[dict] = []
        evidence_service = IssuanceEvidenceService(
            IssuanceEvidenceRepository(self.db.db_path, EXAMPLE),
            contributions=EXAMPLE, signer=SELLER,
            trusted_issuers=TrustedIdentitySet(identities=(SELLER.identity,)),
            clock=lambda: 2_000_000_000,
        )

        async def fulfill(*, evidence, retry_uncertain, db, credits_client):
            return await fulfill_from_hold(
                EXAMPLE, evidence=evidence, db=db, credits_client=credits_client,
                stage_event=self._event, apply_failure_policy=self._failure,
                retry_uncertain=retry_uncertain,
            )

        self.composition = SimpleNamespace(
            contributions=EXAMPLE, domain=SimpleNamespace(fulfillment=SimpleNamespace(fulfill=fulfill)),
            credits_client=authority, evidence_service=evidence_service, runtime=self.runtime,
            repository=self.repository,
            local_principal=SELLER.identity,
        )

    def _event(self, stage, event, **_fields) -> None:
        self.events.append((stage, event))

    async def _failure(self, **fields) -> None:
        self.failures.append(fields)

    def stage(self) -> AlkahestSellerStage:
        """A fresh stage, as a restarted process composes one."""
        return AlkahestSellerStage(
            EXAMPLE, fulfils_through_capacity=True, release_models=frozenset({RECIPIENT_RELEASE}),
            chains=lambda: {}, seller_wallet=lambda: "", composition=lambda: self.composition,
            sqlite_client=lambda: self.db, backfill_escrows=None, stage_event=self._event,
        )

    async def accept(self) -> str:
        record = (await self.runtime.register_plan(agreement_ref=NEGOTIATION, obligations=[obligation()]))[0]
        await self.runtime.adopt(record.obligation_ref, local_principal=SELLER.identity, mechanism_ref=ESCROW_UID)
        await accepted_deal(self.db, obligation_ref=record.obligation_ref)
        self.obligation_ref = record.obligation_ref
        return record.obligation_ref

    def prepared(self) -> PreparedSettlement:
        return PreparedSettlement(
            agreement_ref=NEGOTIATION, obligations=(obligation(),), selected_obligation_index=0,
            local_principal=SELLER.identity, mechanism_ref=ESCROW_UID, mechanism_receipt=None,
            fulfillment_input=AlkahestFulfillmentInput(
                chain_name="anvil", order={"listing_resource": LISTING}, quantity=3, key_mode="new",
                key_id=None, buyer_principal=BUYER, listing_id="L-1", negotiation_id=NEGOTIATION,
                sqlite_client=self.db, composition=self.composition,
            ),
        )

    async def deliver(self, chain: Chain, stage: AlkahestSellerStage | None = None):
        return await (stage or self.stage()).deliver_prepared(self.prepared(), mechanism_client=chain)

    async def fulfill_operation(self):
        return await self.repository.load_settlement_operation(self.obligation_ref, "fulfill")

    async def obligation_record(self):
        return (await self.runtime.get_status(NEGOTIATION)).obligations[0]


@pytest.mark.parametrize(
    "uncertain",
    [httpx.ReadTimeout("issuance timed out"), AuthorityError("unavailable", status_code=503), "commit_then_lose"],
    ids=["timeout", "retryable-5xx", "lost-response-after-commit"],
)
async def test_an_uncertain_issuance_stays_open_and_is_redriven_under_its_identity(tmp_path, uncertain):
    h = Harness(tmp_path, Authority(uncertain))
    await h.accept()
    await h.db.save_capacity_hold(
        negotiation_id=NEGOTIATION, listing_id="L-1", capacity_reservation_id="hold-1",
        payload={"capacity_reservation_id": "hold-1"},
    )
    chain = Chain()

    first = await h.deliver(chain)

    assert first.status == "deferred"
    assert (await h.db.load_issuance_progress(reference=ESCROW_UID))["status"] == "provisioning"
    assert await h.db.load_capacity_hold(negotiation_id=NEGOTIATION) is not None
    assert h.failures == [] and h.authority.rollbacks == [] and chain.submissions == []

    again = await h.deliver(chain)

    assert again.status == "fulfilled" and again.fulfillment_ref == "0xattestation"
    first_request, second_request = h.authority.requests
    assert first_request.fulfillment_id == second_request.fulfillment_id
    assert first_request.request_digest == second_request.request_digest
    assert h.authority.rollbacks == [] and len(chain.submissions) == 1
    assert await h.db.load_capacity_hold(negotiation_id=NEGOTIATION) is None
    progress = await h.db.load_issuance_progress(reference=ESCROW_UID)
    projected = await project_progress(EXAMPLE, h.db, progress, owner=BUYER)
    assert projected["tenant_credentials"]["secret"] == f"ak_new.s3cret-{len(h.authority.requests)}"


async def test_a_definite_refusal_fails_the_deal_and_runs_its_failure_policy(tmp_path):
    h = Harness(tmp_path, Authority(AuthorityError("quota_exhausted", "no units", status_code=409)))
    await h.accept()

    outcome = await h.deliver(Chain())

    assert outcome.status == "failed"
    assert [failure["reason"] for failure in h.failures] == ["quota_exhausted"]


async def test_a_published_attestation_is_recorded_and_completes_the_fulfillment(tmp_path):
    h = Harness(tmp_path, Authority())
    await h.accept()
    chain = Chain()

    outcome = await h.deliver(chain)

    assert outcome.status == "fulfilled" and outcome.fulfillment_ref == "0xattestation"
    operation = await h.fulfill_operation()
    assert operation["state"] == "succeeded"
    assert operation["receipt"] == {"fulfillment_ref": "0xattestation"}
    assert (await h.obligation_record()).fulfillment_ref == "0xattestation"
    assert len(chain.submissions) == 1 and chain.submissions[0][1] == ESCROW_UID


async def test_an_unknown_attestation_outcome_parks_the_deal_with_its_credential_kept(tmp_path):
    h = Harness(tmp_path, Authority())
    await h.accept()
    chain = Chain(RuntimeError("rpc down"))

    outcome = await h.deliver(chain)

    assert outcome.status == "deferred" and "operator" in outcome.reason
    assert h.authority.rollbacks == []
    operation = await h.fulfill_operation()
    assert operation["state"] == "manual_required"
    assert (await h.obligation_record()).mechanism_state[MANUAL_REASON_KEY] == OUTCOME_UNKNOWN
    assert await h.runtime.manual_required_count() == 1
    progress = await h.db.load_issuance_progress(reference=ESCROW_UID)
    assert progress["status"] == "provisioning"
    assert progress["fulfillment_uid"] is None
    projected = await project_progress(EXAMPLE, h.db, progress, owner=BUYER)
    assert projected["tenant_credentials"]["secret"] == "ak_new.s3cret-1"

    again = await h.deliver(chain)

    assert again.status == "deferred"
    assert len(chain.submissions) == 1 and h.authority.rollbacks == []
    assert len(h.authority.requests) == 1
    progress = await h.db.load_issuance_progress(reference=ESCROW_UID)
    projected = await project_progress(EXAMPLE, h.db, progress, owner=BUYER)
    assert projected["tenant_credentials"]["secret"] == "ak_new.s3cret-1"
    resolved = await h.db.save_issuance_progress(
        negotiation_id=NEGOTIATION, public_ref=ESCROW_UID, status="ready", fulfillment_uid="0xresolved",
    )
    assert resolved["fulfillment_uid"] == "0xresolved"


async def test_a_process_stopped_after_submitting_never_submits_again(tmp_path):
    h = Harness(tmp_path, Authority())
    await h.accept()
    stopped = Chain(asyncio.CancelledError())

    with pytest.raises(asyncio.CancelledError):
        await h.deliver(stopped)
    assert (await h.fulfill_operation())["receipt"]["submission"]["evidence_digest"]

    restarted = Chain()
    outcome = await h.deliver(restarted, stage=h.stage())

    assert outcome.status == "deferred"
    assert restarted.submissions == [] and h.authority.rollbacks == []
    assert (await h.fulfill_operation())["state"] == "manual_required"
    assert (await h.obligation_record()).mechanism_state[MANUAL_REASON_KEY] == OUTCOME_UNKNOWN
    progress = await h.db.load_issuance_progress(reference=ESCROW_UID)
    assert progress["status"] == "provisioning"
    # The restart's issuance rotated the secret; the kept credential is the live one.
    projected = await project_progress(EXAMPLE, h.db, progress, owner=BUYER)
    assert projected["tenant_credentials"]["secret"] == f"ak_new.s3cret-{len(h.authority.requests)}"


@pytest.mark.parametrize("chain_error", ["execution reverted", "insufficient funds for gas"])
async def test_a_rejected_attestation_withdraws_its_submission_and_compensates_the_grant(tmp_path, chain_error):
    h = Harness(tmp_path, Authority())
    await h.accept()

    outcome = await h.deliver(Chain(RuntimeError(chain_error)))

    assert outcome.status == "failed"
    assert [rollback["settlement_ref"] for rollback in h.authority.rollbacks] == [ESCROW_UID]
    operation = await h.fulfill_operation()
    assert "submission" not in (operation["receipt"] or {})
    assert operation["state"] != "manual_required"
    await persist_settlement_outcome(h.db, h.prepared(), outcome)
    progress = await h.db.load_issuance_progress(reference=ESCROW_UID)
    projected = await project_progress(EXAMPLE, h.db, progress, owner=BUYER)
    assert "tenant_credentials" not in projected


async def test_no_credential_is_readable_while_the_attestation_is_in_flight(tmp_path):
    h = Harness(tmp_path, Authority())
    await h.accept()
    seen = []

    class Observing(Chain):
        async def _submit(self, data, anchor):
            progress = await h.db.load_issuance_progress(reference=ESCROW_UID)
            seen.append(await project_progress(EXAMPLE, h.db, progress, owner=BUYER))
            return await super()._submit(data, anchor)

    chain = Observing()
    chain.string_obligation = SimpleNamespace(do_obligation=chain._submit)

    assert (await h.deliver(chain)).status == "fulfilled"
    assert "tenant_credentials" not in seen[0]


async def test_a_recorded_reference_completes_without_publishing_again(tmp_path):
    h = Harness(tmp_path, Authority())
    obligation_ref = await h.accept()
    journal = {"local_principal": SELLER.identity, "worker_id": "alkahest-attestation"}
    await h.runtime.reserve_fulfillment(obligation_ref, **journal)
    await h.runtime.record_fulfillment_submission(obligation_ref, {"evidence_digest": "d"}, **journal)
    await h.runtime.record_fulfillment_publication(obligation_ref, "0xearlier", **journal)
    chain = Chain()

    outcome = await h.deliver(chain)

    assert outcome.status == "fulfilled" and outcome.fulfillment_ref == "0xearlier"
    assert chain.submissions == []
    assert (await h.obligation_record()).fulfillment_ref == "0xearlier"

    again = await h.deliver(chain)
    assert again.status == "fulfilled" and chain.submissions == []


async def test_an_attestation_another_attempt_holds_is_deferred(tmp_path):
    h = Harness(tmp_path, Authority())
    obligation_ref = await h.accept()
    await h.runtime.reserve_fulfillment(
        obligation_ref, local_principal=SELLER.identity, worker_id="another-process"
    )
    chain = Chain()

    outcome = await h.deliver(chain)

    assert outcome.status == "deferred" and chain.submissions == []
    assert h.authority.rollbacks == []


class StopsAfterParking:
    """The journal, with the process stopping the moment a park commits."""

    def __init__(self, runtime: SettlementRuntime) -> None:
        self._runtime = runtime

    def __getattr__(self, name):
        return getattr(self._runtime, name)

    async def park_fulfillment(self, *args, **kwargs):
        await self._runtime.park_fulfillment(*args, **kwargs)
        raise asyncio.CancelledError()


async def test_a_process_stopped_right_after_parking_keeps_the_buyers_credential(tmp_path):
    h = Harness(tmp_path, Authority())
    await h.accept()
    h.composition.runtime = StopsAfterParking(h.runtime)

    with pytest.raises(asyncio.CancelledError):
        await h.deliver(Chain(RuntimeError("rpc down")))

    h.composition.runtime = h.runtime
    outcome = await h.deliver(Chain(), stage=h.stage())

    assert outcome.status == "deferred"
    assert len(h.authority.requests) == 1
    progress = await h.db.load_issuance_progress(reference=ESCROW_UID)
    projected = await project_progress(EXAMPLE, h.db, progress, owner=BUYER)
    assert projected["tenant_credentials"]["secret"] == "ak_new.s3cret-1"


class UnreadableJournal:
    async def load_settlement_operation(self, *_args):
        raise sqlite3.OperationalError("database is locked")


async def test_a_journal_that_cannot_be_read_defers_the_deal_and_fails_nothing(tmp_path):
    h = Harness(tmp_path, Authority())
    await h.accept()
    h.composition.repository = UnreadableJournal()

    outcome = await h.deliver(Chain())
    await persist_settlement_outcome(h.db, h.prepared(), outcome)

    assert outcome.status == "deferred" and h.authority.requests == []
    assert (await h.db.load_issuance_progress(reference=ESCROW_UID))["status"] == "provisioning"
