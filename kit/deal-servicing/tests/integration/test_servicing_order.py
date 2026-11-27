"""The kit's servicing cycle drives every deal's physical end first, then runs
each deal's steps in one order, each isolated.

Library integration: a real ``ServicingCycle`` over the rig's SQLite, with the
domain's physical port, recovery step and site-report correction injected. The
seller half and end service are the real ones, the seller half over one payment
and one dispute adapter per deal where a case needs authorities that hang or do
not answer, but in two cases: the order case wraps the seller half and doubles
end service to record when each step runs, and the leading pass's failure case
stubs the seller half to record when each deal's authorities are read.
"""

import asyncio
import contextlib
import logging
from unittest.mock import AsyncMock

from market_deal_lifecycle.adapters import DisputeAdapterTable, PaymentAdapterTable
from market_deal_lifecycle_contracts.models import Accepted, AuthorityView, PaymentEvent, PaymentPartObservation

from market_deal_servicing import (
    Classification, EndService, EndSession, FinalRequest, PhysicalResult, SellerServicing, SellerSession,
    ServicingCycle,
)
from market_deal_servicing.evidence import transaction


class NoDiscovery:
    """A respondent port leaving every deal out of discovery, which these
    cases do not exercise (``test_respondent.py`` does)."""

    def __init__(self):
        self.adapters = []

    def credential_available(self, authority):
        return False

    def dispute_adapter(self, binding):
        self.adapters.append(binding)


class UnreachableSite:
    """A physical port whose site cannot be reached."""

    def __init__(self):
        self.calls = 0

    async def apply_end(self, negotiation_id, *, terminate, at, operation_key):
        self.calls += 1
        raise ConnectionError("site unreachable")


def _update_record(rig, **fields):
    with transaction(rig["path"]) as conn:
        record = EndSession(conn).read("deal").model_copy(update=fields)
        conn.execute("UPDATE servicing_delivery SET record=? WHERE negotiation_id='deal'", (record.model_dump_json(),))


def _rate_deal(rig):
    with transaction(rig["path"]) as conn:
        deal = rig["deal"].model_copy(update={"once_only": False})
        conn.execute("UPDATE servicing_seller_deals SET deal=? WHERE negotiation_id='deal'", (deal.model_dump_json(),))


def _cycle(rig, *, seller=None, end=None, recovery=(), corrections=lambda *_: None, loop="deal-servicing"):
    rig["physical"].apply_end.return_value = PhysicalResult(progress="tearing_down", done=False)
    return ServicingCycle(
        rig["path"], domain="fixture", loop=loop, seller=seller or rig["service"](),
        end=end or rig["end"], respondents=NoDiscovery(), signer=rig["seller"], clock=lambda: rig["clock"][0],
        recovery=recovery, resolve_site_corrections=corrections,
    )


def _requests(rig):
    with transaction(rig["path"]) as conn:
        return {request.source_ref: request for request in EndSession(conn).requests("deal")}


async def test_each_deal_s_steps_run_in_the_kit_s_order(rig):
    """The leading physical end, then the authorities read, recovery, physical
    end, reconciliation, correction, filing dispatch and the physical end again,
    each seeing what the steps before it recorded."""
    order = []
    _update_record(rig, available_at=120, progress="active")
    rig["clock"][0] = 1000

    class Seller:
        def __init__(self, real):
            self.real = real

        async def read(self, negotiation_id):
            order.append("authorities read")
            return await self.real.read(negotiation_id)

        async def dispatch_filings(self, negotiation_id):
            order.append(("filing dispatch", "term-end" in _requests(rig)))
            return await self.real.dispatch_filings(negotiation_id)

    class End:
        async def drive_physical(self, negotiation_id):
            order.append(("physical end", "term-end" in _requests(rig)))
            return []

    async def recover(deal):
        order.append(("recovery", deal.negotiation_id))

    def correct(session, negotiation_id, now):
        order.append(("site-report correction", any(
            request.source_ref == "term-end" for request in session.requests(negotiation_id)
        ), now))

    cycle = _cycle(
        rig, seller=Seller(rig["service"]()), end=End(), recovery=[("site recovery", recover)], corrections=correct,
    )
    assert await cycle.cycle() == 1
    assert order == [
        ("physical end", False),
        "authorities read",
        ("recovery", "deal"),
        ("physical end", False),
        ("site-report correction", True, 1000),
        ("filing dispatch", True),
        ("physical end", True),
    ]


async def test_a_physical_failure_does_not_skip_reconciliation_correction_or_filing(rig, caplog):
    """A deal with a journaled filing whose site cannot be reached still has its
    term end reconciled, its site reports corrected and its filing dispatched,
    and its physical end attempted again after them: in the leading pass, in
    its own steps, and after its filing."""
    _update_record(rig, available_at=120, progress="active")
    with transaction(rig["path"]) as conn:
        end = EndSession(conn)
        request = FinalRequest(
            negotiation_id="deal", source_ref="operator:failure", actor=rig["seller"].identity,
            ended_at=150, observed_at=150, cause="operator_end", source="administrator",
            evidence_refs=["operator:failure"],
        )
        end.record_end(
            request, now=150,
            classification=Classification(kind="unentitled_withdrawal", evidence_refs=request.evidence_refs),
            filing_intent=end.failure_filing(request, now=150, delivered=True),
        )
    rig["clock"][0] = 1000
    site = UnreachableSite()
    corrected = []
    cycle = _cycle(
        rig, end=EndService(rig["path"], site, clock=lambda: rig["clock"][0]),
        corrections=lambda session, negotiation_id, now: corrected.append(negotiation_id),
    )
    with caplog.at_level(logging.ERROR):
        await cycle.cycle()

    assert site.calls == 3
    assert "term-end" in _requests(rig)
    assert corrected == ["deal"]
    with transaction(rig["path"]) as conn:
        filing = next(intent for intent in EndSession(conn).intents("deal") if intent.kind == "filing")
    assert filing.result is not None
    failures = [record.getMessage() for record in caplog.records]
    assert failures == ["fixture servicing step physical end awaits recovery for deal"] * 3


async def test_the_term_end_is_recorded_once_at_the_agreement_s_end_classified_terms(rig, caplog):
    _rate_deal(rig)
    _update_record(rig, available_at=120, progress="active")
    rig["clock"][0] = 999
    await _cycle(rig).cycle()
    assert "term-end" not in _requests(rig)

    rig["clock"][0] = 1005
    await _cycle(rig).cycle()
    # A later cycle records no second term end: one observed later would
    # change the recorded request, which end service refuses.
    rig["clock"][0] = 1010
    with caplog.at_level(logging.ERROR):
        await _cycle(rig).cycle()
    assert caplog.records == []
    term_end = _requests(rig)["term-end"]
    assert (term_end.ended_at, term_end.observed_at, term_end.cause) == (1000, 1005, "terms")
    assert term_end.actor == rig["seller"].identity
    with transaction(rig["path"]) as conn:
        end = EndSession(conn)
        assert end.classification("deal", "term-end") == Classification(kind="terms", evidence_refs=["commitment"])
        assert end.selected_end("deal").source_ref == "term-end"
        assert [intent.kind for intent in end.intents("deal") if intent.kind == "filing"] == []


async def test_the_term_end_waits_while_admission_awaits_a_payment_observation(rig):
    """An undelivered rate deal past its deadline and its term end, whose payment
    authority cannot be read, records neither; once a read after the deadline
    succeeds, both are recorded and the earlier deadline is the deal's end."""
    _rate_deal(rig)
    rig["payment"].read.side_effect = ConnectionError("payments unavailable")
    rig["clock"][0] = 1005
    await _cycle(rig).cycle()
    assert _requests(rig) == {}

    rig["payment"].read.side_effect = None
    await _cycle(rig).cycle()
    requests = _requests(rig)
    assert set(requests) == {"delivery-deadline", "term-end"}
    with transaction(rig["path"]) as conn:
        end = EndSession(conn)
        assert end.payment_observed_at("deal", "commitment") == 1005
        assert end.selected_end("deal").source_ref == "delivery-deadline"


async def test_an_uncommitted_deal_is_paged_and_driven_but_its_authorities_are_not_read(rig):
    _update_record(rig, committed_at=None)
    with transaction(rig["path"]) as conn:
        EndSession(conn).record_end(FinalRequest(
            negotiation_id="deal", source_ref="surrender", actor=rig["buyer"].identity,
            ended_at=140, observed_at=140, cause="buyer_surrender", source="end_delivery",
            evidence_refs=["surrender"],
        ), now=140, classification=Classification(kind="buyer_surrender", evidence_refs=["surrender"]))
    rig["physical"].apply_end.return_value = PhysicalResult(progress="tearing_down", done=False)
    assert await _cycle(rig).cycle() == 1
    assert rig["physical"].apply_end.await_count == 3
    rig["payment"].read.assert_not_called()
    rig["dispute"].read.assert_not_called()


async def test_the_page_position_is_kept_per_loop_and_survives_a_new_cycle_object(rig):
    with transaction(rig["path"]) as conn:
        for name in ("deal-b", "deal-c"):
            end = EndSession(conn)
            end.register(EndSession(conn).read("deal").model_copy(update={"negotiation_id": name}))
            conn.execute(
                "INSERT INTO servicing_seller_deals VALUES (?,?)",
                (name, rig["deal"].model_copy(update={"negotiation_id": name}).model_dump_json()),
            )
    seen = []

    async def recover(deal):
        seen.append(deal.negotiation_id)

    assert await _cycle(rig, recovery=[("recovery", recover)]).cycle(limit=2) == 2
    # A storefront restarted between cycles builds a new cycle over the same file.
    assert await _cycle(rig, recovery=[("recovery", recover)]).cycle(limit=2) == 1
    assert await _cycle(rig, recovery=[("recovery", recover)]).cycle(limit=2) == 2
    # Another loop keeps its own position, starting from the first deal.
    assert await _cycle(rig, recovery=[("recovery", recover)], loop="other-loop").cycle(limit=1) == 1
    assert seen == ["deal", "deal-b", "deal-c", "deal", "deal-b", "deal"]
    with transaction(rig["path"]) as conn:
        assert sorted(conn.execute("SELECT loop, continuation FROM servicing_page_position").fetchall()) == [
            ("deal-servicing", "deal-b"), ("other-loop", "deal"),
        ]


def _add_deal(rig, name):
    """Register another committed deal under the rig's dispute authority."""
    with transaction(rig["path"]) as conn:
        end = EndSession(conn)
        end.register(end.read("deal").model_copy(update={"negotiation_id": name, "commitment_ref": "c-" + name}))
        SellerSession(conn).register(rig["deal"].model_copy(update={"negotiation_id": name, "commitment_ref": "c-" + name}))


def _surrender(rig, name):
    """Record the buyer's end of ``name`` at the rig's clock, before any cycle."""
    with transaction(rig["path"]) as conn:
        EndSession(conn).record_end(FinalRequest(
            negotiation_id=name, source_ref="surrender", actor=rig["buyer"].identity,
            ended_at=rig["clock"][0], observed_at=rig["clock"][0], cause="buyer_surrender", source="end_delivery",
            evidence_refs=["surrender"],
        ), now=rig["clock"][0], classification=Classification(kind="buyer_surrender", evidence_refs=["surrender"]))


def _seller(rig, payments, disputes):
    """The seller half over one payment and one dispute adapter per deal."""
    return SellerServicing(
        rig["path"],
        payments=PaymentAdapterTable([(rig["deal"].payment, lambda binding: payments[binding.negotiation_id])]),
        disputes=DisputeAdapterTable([(rig["authority"].interface, lambda binding: disputes[binding.negotiation_id])]),
        credential_available=lambda _: True, watch_factory=rig["watch"], clock=lambda: rig["clock"][0],
    )


class OrderedSite:
    """A physical port recording each deal it is asked to end, failing for
    the deals named in ``failing``."""

    def __init__(self, order, failing=()):
        self.order = order
        self.failing = set(failing)
        self.called = asyncio.Event()

    async def apply_end(self, negotiation_id, *, terminate, at, operation_key):
        self.order.append(("physical end", negotiation_id))
        self.called.set()
        if negotiation_id in self.failing:
            raise ConnectionError("site unreachable")
        return PhysicalResult(progress="tearing_down", done=False)


class ListingRespondent:
    """A respondent port whose every listing records itself, signals
    ``waiting`` and never answers."""

    agreement_digest = "agreement"

    def __init__(self, order):
        self.order = order
        self.waiting = asyncio.Event()

    def credential_available(self, authority):
        return True

    def dispute_adapter(self, binding):
        self.binding = binding
        return self

    async def respondent(self, after="", limit=100):
        self.order.append("respondent listing")
        self.waiting.set()
        await asyncio.Event().wait()

    def build_answer(self, case, *, matching, items, signer):
        raise AssertionError("no case is listed")


def _hanging(order, name):
    """An authority adapter whose every read records itself and never answers."""

    async def read():
        order.append(("authority read", name))
        await asyncio.Event().wait()

    return AsyncMock(read=AsyncMock(side_effect=read))


async def test_a_recorded_end_waits_behind_no_authority_read(rig):
    """A later deal's end recorded before the cycle is dispatched to the site
    before any authority is read or any counterparty case listed, while every
    authority hangs."""
    order = []
    _add_deal(rig, "deal-b")
    _surrender(rig, "deal-b")
    site = OrderedSite(order)
    payments = {name: _hanging(order, name) for name in ("deal", "deal-b")}
    disputes = {name: _hanging(order, name) for name in ("deal", "deal-b")}
    respondents = ListingRespondent(order)
    cycle = ServicingCycle(
        rig["path"], domain="fixture", loop="deal-servicing", seller=_seller(rig, payments, disputes),
        end=EndService(rig["path"], site, clock=lambda: rig["clock"][0]), respondents=respondents,
        signer=rig["seller"], clock=lambda: rig["clock"][0], resolve_site_corrections=lambda *_: None,
    )
    running = asyncio.create_task(cycle.cycle())
    try:
        # Discovery is the first authority call after the leading pass, and it hangs.
        await asyncio.wait_for(respondents.waiting.wait(), timeout=5)
    finally:
        running.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await running
    assert order == [("physical end", "deal-b"), "respondent listing"]


def _stop_view():
    stop = PaymentEvent(
        negotiation_id="deal", commitment_ref="commitment", part="1", kind="stop", actor="payer-account",
        at=140, cause="payer", sequence=1, authority_record_ref="commitment:events:1:part:1",
        settles_through="started_period",
    )
    return AuthorityView(outcome=Accepted(), state="ended", events=[stop], parts=[
        PaymentPartObservation(part="1", final_stop=stop, evidence_ref="snapshot"),
    ])


async def test_an_end_a_deal_s_own_read_discovers_is_torn_down_after_its_steps(rig):
    """A deal whose payment read records a stop has its physical end driven in
    its own steps, before the later deal's authorities are read."""
    order = []
    _add_deal(rig, "deal-b")
    payment = AsyncMock()
    payment.read.return_value = _stop_view()
    dispute = AsyncMock()
    dispute.read.return_value = AuthorityView(outcome=Accepted())

    async def unanswered():
        order.append(("authority read", "deal-b"))
        raise TimeoutError("dispute authority did not answer")

    later = AsyncMock(read=AsyncMock(side_effect=unanswered))
    site = OrderedSite(order)
    cycle = ServicingCycle(
        rig["path"], domain="fixture", loop="deal-servicing",
        seller=_seller(rig, {"deal": payment, "deal-b": later}, {"deal": dispute, "deal-b": later}),
        end=EndService(rig["path"], site, clock=lambda: rig["clock"][0]), respondents=NoDiscovery(),
        signer=rig["seller"], clock=lambda: rig["clock"][0], resolve_site_corrections=lambda *_: None,
    )
    assert await cycle.cycle() == 2
    # Nothing was pending in the leading pass; the stop the deal's own read
    # recorded is driven by both of its steps' physical ends, before the later
    # deal, which has no end, is read.
    assert order == [("physical end", "deal"), ("physical end", "deal"), ("authority read", "deal-b")]
    assert [request.cause for request in _requests(rig).values()] == ["payer"]


async def test_a_failed_physical_end_in_the_leading_pass_skips_no_other_deal_s(rig, caplog):
    order = []
    _add_deal(rig, "deal-b")
    _surrender(rig, "deal")
    _surrender(rig, "deal-b")
    site = OrderedSite(order, failing={"deal"})

    class Seller:
        async def read(self, negotiation_id):
            order.append(("authorities read", negotiation_id))

        async def dispatch_filings(self, negotiation_id):
            return []

    cycle = _cycle(rig, seller=Seller(), end=EndService(rig["path"], site, clock=lambda: rig["clock"][0]))
    with caplog.at_level(logging.ERROR):
        assert await cycle.cycle() == 2
    assert order[:3] == [("physical end", "deal"), ("physical end", "deal-b"), ("authorities read", "deal")]
    assert caplog.records[0].getMessage() == "fixture servicing step physical end awaits recovery for deal"
