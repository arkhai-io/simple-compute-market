"""The kit's servicing cycle runs each deal's steps in one order, each isolated.

Library integration: a real ``ServicingCycle`` over the rig's SQLite, with the
domain's physical port, recovery step and site-report correction injected. The
seller half and end service are the real ones but in the order case, which
wraps the seller half and doubles end service to record when each step runs.
"""

import logging

from market_deal_servicing import (
    Classification, EndService, EndSession, FinalRequest, PhysicalResult, ServicingCycle,
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
    """The authorities read, recovery, physical end, reconciliation, correction,
    filing dispatch and the physical end again, each seeing what the steps
    before it recorded."""
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
    and its physical end attempted again after them."""
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

    assert site.calls == 2
    assert "term-end" in _requests(rig)
    assert corrected == ["deal"]
    with transaction(rig["path"]) as conn:
        filing = next(intent for intent in EndSession(conn).intents("deal") if intent.kind == "filing")
    assert filing.result is not None
    failures = [record.getMessage() for record in caplog.records]
    assert failures == ["fixture servicing step physical end awaits recovery for deal"] * 2


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
    assert rig["physical"].apply_end.await_count == 2
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
