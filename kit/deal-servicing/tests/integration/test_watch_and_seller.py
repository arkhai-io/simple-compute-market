from unittest.mock import AsyncMock, Mock

from market_arkhai_mediation.adapter import MediationAdapter
from market_arkhai_mediation.client import MediationClient, MediationCredential
from market_arkhai_mediation.fixtures.authority import MediationContractFake
from market_arkhai_mediation.models import Filing
from market_deal_lifecycle.adapters import DisputeAdapterTable, InterfaceRequest, PaymentAdapterTable, PaymentSelector
from market_deal_lifecycle.terms import DisputeAuthority
from market_deal_lifecycle_contracts.models import (
    Accepted, AuthorityView, CaseRecord, DisputeEvent, LifecycleCommand, ListDealsRequest,
    OpenExtension, PaymentEvent, PaymentPartObservation, Pending, Rejected, Unknown,
)
from market_deal_servicing import (
    Classification, DeliveryRecord, EndSession, FinalRequest, PhysicalResult, SellerDeal, SellerServicing,
    SellerSession,
)
from market_deal_servicing.evidence import transaction
from market_deal_servicing.watch import WatchSession
from pydantic import SecretStr


async def test_ruling_applies_once_before_and_after_application_with_authority_actor(rig):
    rig["physical"].apply_end.return_value = PhysicalResult(done=True, progress="released")
    for sequence, applied in ((1, False), (2, True)):
        rig["dispute"].read.return_value = AuthorityView(outcome=Accepted(), disputes=[
            DisputeEvent(
                negotiation_id="deal", commitment_ref="commitment", case_ref="case", kind="ruled",
                actor="opaque-dispute-account", at=150, sequence=seq, record_ref=f"record-{seq}",
                outcome=[{"effect_id": "one-effect", "kind": "delivery_end", "at": 140,
                          "applied": applied if seq == sequence else False}],
            ) for seq in range(1, sequence + 1)
        ])
        watch = rig["watch"]()
        watch.actor = lambda _: rig["seller"].identity
        await watch.poll()
        await rig["end"].drive_physical("deal")
    assert rig["physical"].apply_end.await_count == 1
    with transaction(rig["path"]) as conn:
        end = EndSession(conn)
        assert len(end.requests("deal")) == 1
        selected = end.view("deal").recorded_end
        assert selected.actor == rig["authority_signer"].identity
        assert selected.actor != rig["seller"].identity
        assert selected.source == "record-1" and selected.cause == "ruling"


class AppendAuthority:
    def __init__(self):
        self.view = AuthorityView(outcome=Accepted())
        self.read = AsyncMock(side_effect=lambda: self.view)
        self.submit = AsyncMock(side_effect=[Unknown(reason="lost append"), Accepted()])
        self.build_append = Mock(side_effect=lambda case, items: {"case_ref": case, "items": []})


async def test_journal_before_cursor_and_restart_replays_append_even_after_close(rig):
    adapter = AppendAuthority()
    filed = DisputeEvent(
        negotiation_id="deal", commitment_ref="commitment", case_ref="case", kind="filed",
        actor="buyer-account", at=140, sequence=1, record_ref="filed",
    )
    adapter.view = AuthorityView(outcome=Accepted(), disputes=[filed])
    watch = rig["watch"](dispute=adapter)
    await watch.poll()
    with transaction(rig["path"]) as conn:
        assert WatchSession(conn).cursor("deal", watch.dispute_record) == 1
        intent = next(item for item in EndSession(conn).intents("deal") if item.kind == "append")
        assert intent.state == "pending"
    adapter.view = AuthorityView(outcome=Accepted(), disputes=[filed], cases=[
        CaseRecord(case_ref="case", state="closed", record_ref="closed"),
    ])
    await rig["watch"](dispute=adapter).poll()
    assert adapter.submit.await_count == 2
    first, second = adapter.submit.await_args_list
    assert first.args[0] == second.args[0] and first.args[2] == second.args[2]
    # Cases entirely closed during downtime never send a new append.
    other = filed.model_copy(update={"case_ref": "closed-case", "sequence": 2, "record_ref": "filed-2"})
    adapter.view = AuthorityView(outcome=Accepted(), disputes=[filed, other], cases=[
        CaseRecord(case_ref="closed-case", state="closed", record_ref="closed-2"),
    ])
    await rig["watch"](dispute=adapter).poll()
    assert adapter.submit.await_count == 2


async def test_independent_authority_sequences_and_overlapping_extensions(rig):
    extensions = [
        OpenExtension(part="0", extension_ref="a", case_ref="case-a", until=None),
        OpenExtension(part="0", extension_ref="b", case_ref="case-b", until=300),
    ]
    rig["payment"].read.return_value = AuthorityView(outcome=Accepted(), extensions=extensions)
    rig["dispute"].read.return_value = AuthorityView(outcome=Accepted(), disputes=[DisputeEvent(
        negotiation_id="deal", commitment_ref="commitment", case_ref="case-a", kind="closed",
        actor="authority", at=150, sequence=50, record_ref="record-50",
    )])
    api = rig["service"]()
    assert (await api.read("deal")).authority.extensions == extensions
    watch = rig["watch"]()
    with transaction(rig["path"]) as conn:
        session = WatchSession(conn)
        assert session.cursor("deal", watch.dispute_record) == 50
        assert session.cursor("deal", watch.payment_record) == -1
    rig["payment"].read.return_value = AuthorityView(outcome=Accepted(), extensions=extensions[1:])
    assert (await api.read("deal")).authority.extensions == extensions[1:]


async def test_seller_pages_pinned_authority_repair_and_operator_end_filing(rig):
    api = rig["service"]()
    assert (await api.list()).deals[0].state == "running"
    assert (await api.list(ListDealsRequest(continuation="deal"))).deals == []
    rig["credentials"][0] = False
    assert (await api.list()).deals[0].state == "repair_required"
    assert "credential" in (await api.read("deal")).authority.outcome.reason
    rig["credentials"][0] = True
    adapter = rig["dispute"]
    adapter.supported_commands = {"delivery_end"}
    adapter.supported_intents = {"delivery_end"}
    adapter.build_request = Mock(return_value=InterfaceRequest(interface=rig["authority"].interface, payload={}))
    adapter.validate_request = Mock(return_value=None)
    adapter.submit.side_effect = [Unknown(reason="lost filing"), Accepted()]
    command = LifecycleCommand(negotiation_id="deal", kind="delivery_end", operation_key="operator")
    outcome = await api.submit(command, actor=rig["seller"].identity, reason="maintenance")
    assert isinstance(outcome, Unknown)
    with transaction(rig["path"]) as conn:
        end = EndSession(conn)
        assert end.selected_end("deal").administrator_reason == "maintenance"
        assert len([item for item in end.intents("deal") if item.kind == "filing"]) == 1
    # No payment stop or reverse, and a filing never waits for a ruling to end delivery.
    rig["payment"].submit.assert_not_called()
    assert (await rig["service"]().submit(command, actor=rig["seller"].identity, reason="maintenance")).status == "accepted"
    assert adapter.submit.await_args_list[0].args[0] == adapter.submit.await_args_list[1].args[0]
    assert (await api.read("deal")).delivery.recorded_end is not None
    assert (await api.list()).deals[0].state == "ending"


async def test_a_deal_whose_mechanism_has_no_adapter_composed_is_repair_required_until_released(rig):
    # The storefront installs the deal's mechanism, but its configuration
    # composed no adapter for it.
    api = SellerServicing(
        rig["path"], payments=PaymentAdapterTable([]),
        disputes=DisputeAdapterTable([(rig["authority"].interface, lambda _: rig["dispute"])]),
        credential_available=lambda _: False, watch_factory=rig["watch"], clock=lambda: rig["clock"][0],
        missing_adapters={"fixture.payment.v1": "[Settlement].fixture"},
    )
    reason = "repair required: fixture.payment.v1 has no lifecycle adapter; configure [Settlement].fixture"

    [summary] = (await api.list()).deals
    assert summary.state == "repair_required"
    # It is the repair reason before the deal's missing dispute credential.
    assert (await api.read("deal")).authority.outcome.reason == reason
    assert api.unserviceable() == [("deal", reason)]
    # A storefront that names the mechanism yet composes its adapter has no
    # unserviceable deal, and lists it by its authority's state.
    composed = SellerServicing(
        rig["path"], payments=PaymentAdapterTable([(rig["deal"].payment, lambda _: rig["payment"])]),
        disputes=DisputeAdapterTable([(rig["authority"].interface, lambda _: rig["dispute"])]),
        credential_available=lambda _: True, watch_factory=rig["watch"], clock=lambda: rig["clock"][0],
        missing_adapters={"fixture.payment.v1": "[Settlement].fixture"},
    )
    assert composed.unserviceable() == []
    assert (await composed.list()).deals[0].state == "running"
    # Nor does one naming no missing configuration for the mechanism.
    unnamed = SellerServicing(
        rig["path"], payments=PaymentAdapterTable([]), disputes=DisputeAdapterTable([]),
        credential_available=lambda _: True, watch_factory=rig["watch"], clock=lambda: rig["clock"][0],
    )
    assert unnamed.unserviceable() == []

    # A deal ended and released whose dispute authority was never observed
    # still has no case verified closed, so it stays open.
    record_buyer_end(rig, "deal", progress="released")
    assert api.unserviceable() == [("deal", reason)]

    # Once one read of its dispute authority, showing no case, is saved, it is
    # not open.
    await rig["watch"]().poll()
    assert api.unserviceable() == []


def record_buyer_end(rig, negotiation_id, *, progress):
    """The buyer's lawful end at 140, its resource at ``progress``."""
    with transaction(rig["path"]) as conn:
        end = EndSession(conn)
        end.record_end(FinalRequest(
            negotiation_id=negotiation_id, source_ref="buyer-end", ended_at=140, observed_at=140,
            actor=rig["buyer"].identity, cause="buyer_surrender", source="buyer", evidence_refs=["buyer-end"],
        ), now=150, classification=Classification(kind="buyer_surrender", evidence_refs=["buyer-end"]))
        end.physical_progress(negotiation_id, progress)


async def listed(rig, negotiation_id):
    [summary] = [deal for deal in (await rig["service"]().list()).deals if deal.negotiation_id == negotiation_id]
    return summary.state, summary.ending


def register_rate(rig) -> SellerDeal:
    """A committed rate deal, ``rate``, beside the rig's once-only ``deal``."""
    rate = SellerDeal(
        negotiation_id="rate", commitment_ref="rate-commitment", domain="fixture",
        buyer=rig["buyer"].identity, payment=PaymentSelector("fixture.payment.v1"), dispute=rig["authority"],
        once_only=False,
    )
    with transaction(rig["path"]) as conn:
        EndSession(conn).register(DeliveryRecord(
            negotiation_id="rate", commitment_ref="rate-commitment", seller=rig["seller"].identity,
            start_at=100, term_end=1000, committed_at=100, delivery_deadline_seconds=500,
        ))
        SellerSession(conn).register(rate)
    return rate


async def test_a_released_rate_deal_is_ended_only_once_every_part_has_stopped(rig):
    rate = register_rate(rig)
    running = PaymentPartObservation(part="0", started_at=100, evidence_ref="rate-commitment:snapshot:1:140")
    rig["payment"].read.return_value = AuthorityView(outcome=Accepted(), state="running", parts=[running])
    await rig["watch"](deal=rate).poll()
    # The buyer ended delivery at the storefront and the resource is released,
    # while the buyer's stop has not reached the payment authority.
    record_buyer_end(rig, "rate", progress="released")

    assert await listed(rig, "rate") == ("ending", ["payment_running"])

    # One part stops at the authority, the other reaches its end by now.
    stop = PaymentEvent(
        negotiation_id="rate", commitment_ref="rate-commitment", part="0", kind="stop", actor="payer-account",
        at=145, cause="payer", sequence=1, authority_record_ref="rate-commitment:events:1:part:0",
        settles_through="started_period",
    )
    rig["payment"].read.return_value = AuthorityView(outcome=Accepted(), state="ended", parts=[
        running.model_copy(update={"final_stop": stop}),
        PaymentPartObservation(part="1", started_at=100, end_at=150, evidence_ref="rate-commitment:snapshot:2:150"),
    ])
    await rig["watch"](deal=rate).poll()

    assert await listed(rig, "rate") == ("ended", [])


async def test_a_released_rate_deal_never_observed_at_the_payment_authority_is_ending(rig):
    rate = register_rate(rig)
    # The buyer ended at the storefront and the resource is released before
    # any watch has read the payment authority, so no part's stop is verified,
    # nor, with no read of the dispute authority, is any case verified closed.
    record_buyer_end(rig, "rate", progress="released")

    assert await listed(rig, "rate") == ("ending", ["payment_running", "case_unobserved"])

    # A view that lists no part verifies no stop either.
    rig["payment"].read.return_value = AuthorityView(outcome=Accepted(), state="running", parts=[])
    await rig["watch"](deal=rate).poll()

    assert await listed(rig, "rate") == ("ending", ["payment_running"])


async def test_a_released_once_only_deal_is_ended_only_once_its_dispute_authority_is_observed(rig):
    # A once-only deal has no rate part to stop, but it names a dispute
    # authority, and before any read of it is saved no case is verified closed.
    record_buyer_end(rig, "deal", progress="released")

    assert await listed(rig, "deal") == ("ending", ["case_unobserved"])

    # Without the authority's credential it shows repair required first.
    rig["credentials"][0] = False
    assert await listed(rig, "deal") == ("repair_required", [])
    rig["credentials"][0] = True

    # A failed read saves no view, so the authority is still unobserved.
    rig["dispute"].read.return_value = AuthorityView(outcome=Unknown(reason="authority unreachable"))
    await rig["watch"]().poll()

    assert await listed(rig, "deal") == ("ending", ["case_unobserved"])

    # One verified read showing no case ends it.
    rig["dispute"].read.return_value = AuthorityView(outcome=Accepted())
    await rig["watch"]().poll()

    assert await listed(rig, "deal") == ("ended", [])


async def test_a_released_stopped_deal_nobody_filed_on_is_ended_until_a_party_files(rig):
    # The mediation contract's peer holds no record of an Agreement nobody has
    # filed on, and answers its first record page 404 invalid_request.
    peer = MediationContractFake()
    authority = DisputeAuthority.model_validate(peer.authority)
    fixture = peer.data["filing"]["request"]
    unfiled = SellerDeal(
        negotiation_id="unfiled", commitment_ref=fixture["transaction"], domain="fixture",
        buyer=rig["buyer"].identity, payment=PaymentSelector("fixture.payment.v1"), dispute=authority,
        once_only=False,
    )
    with transaction(rig["path"]) as conn:
        EndSession(conn).register(DeliveryRecord(
            negotiation_id="unfiled", commitment_ref=fixture["transaction"], seller=rig["seller"].identity,
            start_at=100, term_end=1000, committed_at=100, delivery_deadline_seconds=500,
        ))
        SellerSession(conn).register(unfiled)
    stop = PaymentEvent(
        negotiation_id="unfiled", commitment_ref=fixture["transaction"], part="0", kind="stop",
        actor="payer-account", at=145, cause="payer", sequence=1,
        authority_record_ref=fixture["transaction"] + ":events:1:part:0", settles_through="started_period",
    )
    payment = AsyncMock()
    payment.read.return_value = AuthorityView(outcome=Accepted(), state="ended", parts=[PaymentPartObservation(
        part="0", started_at=100, final_stop=stop, evidence_ref=fixture["transaction"] + ":snapshot:2:145",
    )])
    record_buyer_end(rig, "unfiled", progress="released")
    # Public deterministic contract-fake credentials; never use on a public network.
    async with MediationClient(
        authority, MediationCredential(authority.identity, token=SecretStr("fixture-payee")),
        transport=peer.transport(),
    ) as payee, MediationClient(
        authority, MediationCredential(authority.identity, token=SecretStr("fixture-payer")),
        transport=peer.transport(),
    ) as payer:
        adapter = MediationAdapter(
            unfiled.dispute_binding, fixture["agreement"], payee, clock=lambda: rig["clock"][0],
        )
        service = SellerServicing(
            rig["path"], payments=PaymentAdapterTable([(unfiled.payment, lambda _: payment)]),
            disputes=DisputeAdapterTable([(authority.interface, lambda _: adapter)]),
            credential_available=lambda _: True, watch_factory=rig["watch"], clock=lambda: rig["clock"][0],
        )

        async def listed_unfiled():
            [summary] = [deal for deal in (await service.list()).deals if deal.negotiation_id == "unfiled"]
            return summary.state, summary.ending

        # Before any watch, neither authority has been read.
        assert await listed_unfiled() == ("ending", ["payment_running", "case_unobserved"])

        watch = rig["watch"](deal=unfiled, payment=payment, dispute=adapter)
        await watch.poll()
        with transaction(rig["path"]) as conn:
            saved = WatchSession(conn).view("unfiled", watch.dispute_record)
        assert saved is not None and saved.outcome.status == "accepted"
        assert saved.cases == [] and saved.disputes == []
        assert await listed_unfiled() == ("ended", [])
        read = await service.read("unfiled")
        assert read.authority.outcome.status == "accepted" and read.authority.cases == []

        await payer.file(Filing.model_validate({
            "transaction": fixture["transaction"], "agreement": fixture["agreement"],
            "request": {"kind": "effects", "effects": [{"kind": "reverse", "part": 0, "amount": "1"}]},
            "claim": "Operator review requested.", "items": [],
        }), idempotency_key="payer-filing")
        await rig["watch"](deal=unfiled, payment=payment, dispute=adapter).poll()

        assert await listed_unfiled() == ("ending", ["case_open"])


async def test_a_released_deal_naming_no_dispute_authority_needs_no_dispute_read(rig):
    plain = SellerDeal(
        negotiation_id="plain", commitment_ref="plain-commitment", domain="fixture",
        buyer=rig["buyer"].identity, payment=PaymentSelector("fixture.payment.v1"), once_only=True,
    )
    with transaction(rig["path"]) as conn:
        EndSession(conn).register(DeliveryRecord(
            negotiation_id="plain", commitment_ref="plain-commitment", seller=rig["seller"].identity,
            start_at=100, term_end=1000, committed_at=100, delivery_deadline_seconds=500,
        ))
        SellerSession(conn).register(plain)
    record_buyer_end(rig, "plain", progress="released")

    assert await listed(rig, "plain") == ("ended", [])


async def test_a_released_rate_deal_still_billing_stays_unserviceable_until_its_part_stops(rig):
    rate = register_rate(rig)
    running = PaymentPartObservation(part="0", started_at=100, evidence_ref="rate-commitment:snapshot:1:140")
    rig["payment"].read.return_value = AuthorityView(outcome=Accepted(), state="running", parts=[running])
    await rig["watch"](deal=rate).poll()
    record_buyer_end(rig, "rate", progress="released")
    # The storefront restarts with no adapter composed for the deals' mechanism.
    api = SellerServicing(
        rig["path"], payments=PaymentAdapterTable([]),
        disputes=DisputeAdapterTable([(rig["authority"].interface, lambda _: rig["dispute"])]),
        credential_available=lambda _: True, watch_factory=rig["watch"], clock=lambda: rig["clock"][0],
        missing_adapters={"fixture.payment.v1": "[Settlement].fixture"},
    )
    reason = "repair required: fixture.payment.v1 has no lifecycle adapter; configure [Settlement].fixture"

    # Released, but its part last showed no stop: still open, so still reported
    # beside the once-only deal that has no end.
    assert sorted(api.unserviceable()) == [("deal", reason), ("rate", reason)]

    # A part's stop observed while its adapter was composed closes the deal.
    stop = PaymentEvent(
        negotiation_id="rate", commitment_ref="rate-commitment", part="0", kind="stop", actor="payer-account",
        at=145, cause="payer", sequence=1, authority_record_ref="rate-commitment:events:1:part:0",
        settles_through="started_period",
    )
    rig["payment"].read.return_value = AuthorityView(
        outcome=Accepted(), state="ended", parts=[running.model_copy(update={"final_stop": stop})],
    )
    await rig["watch"](deal=rate).poll()

    assert api.unserviceable() == [("deal", reason)]


async def test_each_outstanding_condition_is_named_and_a_later_case_returns_a_deal_to_ending(rig):
    filed = CaseRecord(case_ref="case", state="filed", record_ref="case-filed")
    rig["dispute"].read.return_value = AuthorityView(outcome=Accepted(), cases=[filed])
    await rig["watch"]().poll()
    record_buyer_end(rig, "deal", progress="tearing_down")

    assert await listed(rig, "deal") == ("ending", ["release_pending", "case_open"])

    closed = filed.model_copy(update={"state": "closed", "record_ref": "case-closed"})
    rig["dispute"].read.return_value = AuthorityView(outcome=Accepted(), cases=[closed])
    await rig["watch"]().poll()
    with transaction(rig["path"]) as conn:
        EndSession(conn).physical_progress("deal", "released")

    assert await listed(rig, "deal") == ("ended", [])

    later = CaseRecord(case_ref="later-case", state="filed", record_ref="later-filed")
    rig["dispute"].read.return_value = AuthorityView(outcome=Accepted(), cases=[closed, later])
    await rig["watch"]().poll()

    assert await listed(rig, "deal") == ("ending", ["case_open"])


def filing_authority(rig, *outcomes):
    """The rig's dispute authority answering each ``delivery_end`` filing in
    turn with ``outcomes``, and every read with ``cases``."""
    adapter = rig["dispute"]
    adapter.supported_commands = {"delivery_end"}
    adapter.supported_intents = {"delivery_end"}
    adapter.build_request = Mock(return_value=InterfaceRequest(interface=rig["authority"].interface, payload={}))
    adapter.validate_request = Mock(return_value=None)
    adapter.submit.side_effect = list(outcomes)
    return adapter


def record_seller_failure(rig, negotiation_id, *, progress):
    """An administrator's failure end at the rig's clock, journaling the
    seller's ``delivery_end`` filing, its resource at ``progress``."""
    now = rig["clock"][0]
    with transaction(rig["path"]) as conn:
        end = EndSession(conn)
        request = FinalRequest(
            negotiation_id=negotiation_id, source_ref="operator:failure", actor=rig["seller"].identity,
            ended_at=now, observed_at=now, cause="operator_end", source="administrator",
            evidence_refs=["operator:failure"],
        )
        end.record_end(
            request, now=now,
            classification=Classification(kind="unentitled_withdrawal", evidence_refs=request.evidence_refs),
            filing_intent=end.failure_filing(request, now=now, delivered=False),
        )
        end.physical_progress(negotiation_id, progress)


def register_unstarted(rig) -> SellerDeal:
    """A committed once-only deal, ``early``, whose Agreement starts at 300."""
    early = rig["deal"].model_copy(update={"negotiation_id": "early", "commitment_ref": "early-commitment"})
    with transaction(rig["path"]) as conn:
        EndSession(conn).register(DeliveryRecord(
            negotiation_id="early", commitment_ref="early-commitment", seller=rig["seller"].identity,
            start_at=300, term_end=1000, committed_at=100, delivery_deadline_seconds=500,
        ))
        SellerSession(conn).register(early)
    return early


def no_case_view():
    return AuthorityView(outcome=Accepted())


def closed_case_view():
    return AuthorityView(outcome=Accepted(), cases=[CaseRecord(case_ref="case", state="closed", record_ref="closed")])


async def test_a_filing_waiting_for_the_agreement_s_start_keeps_a_deal_ending(rig):
    """A once-only deal ended as a seller failure before its Agreement's start,
    nothing dispatched, its authority read showing no case, is ending with its
    filing unanswered until the filing is accepted and its case closes."""
    early = register_unstarted(rig)
    adapter = filing_authority(rig, Accepted())
    adapter.read.return_value = no_case_view()
    record_seller_failure(rig, "early", progress="released")
    await rig["watch"](deal=early).poll()
    api = rig["service"]()
    [waiting] = await api.dispatch_filings("early")
    assert waiting.outcome == Pending(reason="delivery-end filing waits for Agreement start")

    assert await listed(rig, "early") == ("ending", ["filing_unanswered"])
    [summary] = [deal for deal in (await api.list()).deals if deal.negotiation_id == "early"]
    assert summary.filings[0].outcome == Pending(reason="delivery-end filing has not been attempted")

    rig["clock"][0] = 300
    [filed] = await api.dispatch_filings("early")
    assert filed.outcome.status == "accepted"
    adapter.read.return_value = closed_case_view()
    await rig["watch"](deal=early).poll()

    assert await listed(rig, "early") == ("ended", [])


async def test_a_filing_whose_answer_was_lost_keeps_a_released_deal_ending(rig):
    adapter = filing_authority(rig, Unknown(reason="lost filing"), Accepted())
    adapter.read.return_value = no_case_view()
    record_seller_failure(rig, "deal", progress="released")
    await rig["watch"]().poll()
    api = rig["service"]()
    [lost] = await api.dispatch_filings("deal")
    assert lost.outcome.status == "unknown"

    assert await listed(rig, "deal") == ("ending", ["filing_unanswered"])

    # Resolved under its operation key, its case open and then closed.
    [resolved] = await api.dispatch_filings("deal")
    assert resolved.outcome.status == "accepted"
    first, second = adapter.submit.await_args_list
    assert first.args[2] == second.args[2]
    adapter.read.return_value = AuthorityView(outcome=Accepted(), cases=[
        CaseRecord(case_ref="case", state="filed", record_ref="filed"),
    ])
    await rig["watch"]().poll()
    assert await listed(rig, "deal") == ("ending", ["case_open"])
    adapter.read.return_value = closed_case_view()
    await rig["watch"]().poll()
    assert await listed(rig, "deal") == ("ended", [])


async def test_a_filing_the_authority_holds_pending_keeps_a_deal_ending(rig):
    adapter = filing_authority(rig, Pending(reason="authority is still deciding"))
    adapter.read.return_value = closed_case_view()
    record_seller_failure(rig, "deal", progress="released")
    await rig["watch"]().poll()
    await rig["service"]().dispatch_filings("deal")

    assert await listed(rig, "deal") == ("ending", ["filing_unanswered"])


async def test_a_rejected_filing_is_repair_required_not_unanswered(rig):
    adapter = filing_authority(rig, Rejected(reason="claim refused"))
    adapter.read.return_value = no_case_view()
    record_seller_failure(rig, "deal", progress="released")
    await rig["watch"]().poll()
    await rig["service"]().dispatch_filings("deal")

    assert await listed(rig, "deal") == ("repair_required", [])


async def test_an_unserviceable_deal_with_an_unanswered_filing_stays_reported(rig):
    rig["dispute"].read.return_value = no_case_view()
    record_seller_failure(rig, "deal", progress="released")
    await rig["watch"]().poll()
    api = SellerServicing(
        rig["path"], payments=PaymentAdapterTable([]),
        disputes=DisputeAdapterTable([(rig["authority"].interface, lambda _: rig["dispute"])]),
        credential_available=lambda _: True, watch_factory=rig["watch"], clock=lambda: rig["clock"][0],
        missing_adapters={"fixture.payment.v1": "[Settlement].fixture"},
    )
    reason = "repair required: fixture.payment.v1 has no lifecycle adapter; configure [Settlement].fixture"

    # Released and observed with no case, but its own filing was never sent.
    assert api.unserviceable() == [("deal", reason)]

    filing_authority(rig, Accepted())
    await rig["service"]().dispatch_filings("deal")
    assert api.unserviceable() == []
