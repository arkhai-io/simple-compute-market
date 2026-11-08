from __future__ import annotations

import pytest
from market_core import SettlementEvidence

from market_settlement_runtime import (
    SettlementAdminRouteError,
    SettlementAdminRouteService,
    SettlementLookup,
)

PAYMENTS = SettlementEvidence(
    negotiation_id="neg-1",
    mechanism="arkhai.payments.v1",
    settlement_ref="txn-1",
    status="verified",
    evidence={},
)
ALKAHEST = SettlementEvidence(
    negotiation_id="neg-2",
    mechanism="alkahest.v1",
    settlement_ref="0xescrow",
    status="verified",
    evidence={},
)


class Clock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


class Evidence:
    """A storefront's evidence store, recording which lookups were consulted."""

    def __init__(self, *records: SettlementEvidence) -> None:
        self.records = list(records)
        self.consulted: list[tuple[str, str]] = []

    async def by_reference(self, key: str) -> SettlementEvidence | None:
        self.consulted.append(("reference", key))
        return next((r for r in self.records if r.settlement_ref == key), None)

    async def by_negotiation(self, key: str) -> SettlementEvidence | None:
        self.consulted.append(("negotiation", key))
        return next((r for r in self.records if r.negotiation_id == key), None)

    def lookup(self) -> SettlementLookup:
        return SettlementLookup(
            by_reference=self.by_reference, by_negotiation=self.by_negotiation
        )


def _service(
    *,
    evidence: Evidence | None = None,
    delivery_status=None,
    verify=None,
    preview=None,
    clock=None,
):
    async def default_status(found):
        return {"status": "ready", "negotiation_id": found.negotiation_id}

    async def default_verify(_uid, request):
        return {"valid": request.get("seller_wallet") == "0xseller"}

    async def default_preview(_uid, request):
        return {"would_submit": True, "host_id": request["listing_id"]}

    return SettlementAdminRouteService(
        verify=verify or default_verify,
        preview_fulfillment=preview or default_preview,
        settlements=(evidence or Evidence(PAYMENTS)).lookup(),
        delivery_status=delivery_status or default_status,
        poll_seconds=0.0,
        clock=clock or Clock(),
    )


def _ticking(clock: Clock, statuses):
    """A delivery status that advances the clock a second per read."""
    statuses = list(statuses)

    async def delivery_status(_evidence):
        clock.now += 1.0
        read = statuses.pop(0) if len(statuses) > 1 else statuses[0]
        if isinstance(read, Exception):
            raise read
        return read

    return delivery_status


async def test_verify_and_evaluate_report_the_domain_result_for_the_escrow() -> None:
    service = _service()

    verified = await service.verify("uid-1", {"seller_wallet": "0xseller"})
    evaluated = await service.evaluate("uid-1", {"listing_id": "listing-1"})

    assert verified == {"valid": True, "escrow_uid": "uid-1"}
    assert evaluated == {
        "would_submit": True,
        "host_id": "listing-1",
        "escrow_uid": "uid-1",
    }


async def test_an_unknown_reference_is_not_found() -> None:
    async def unknown(_uid, _request):
        raise LookupError("listing 'x' not found")

    service = _service(verify=unknown, preview=unknown)

    for call in (service.verify, service.evaluate):
        with pytest.raises(SettlementAdminRouteError) as refused:
            await call("uid-1", {})
        assert refused.value.status_code == 404


async def test_a_reference_some_evidence_records_resolves_without_its_negotiation() -> None:
    evidence = Evidence(PAYMENTS, ALKAHEST)

    for reference, expected in (("txn-1", PAYMENTS), ("0xescrow", ALKAHEST)):
        evidence.consulted.clear()
        assert await evidence.lookup().resolve(reference) is expected
        assert evidence.consulted == [("reference", reference)]


async def test_a_negotiation_resolves_when_no_evidence_records_it_as_a_reference() -> None:
    pending = SettlementEvidence(
        negotiation_id="neg-3",
        mechanism="arkhai.payments.v1",
        settlement_ref=None,
        status="pending",
        evidence={},
    )
    evidence = Evidence(PAYMENTS, pending)

    assert await evidence.lookup().resolve("neg-1") is PAYMENTS
    assert await evidence.lookup().resolve("neg-3") is pending
    assert await evidence.lookup().resolve("no-such-reference") is None


async def test_the_wait_reports_the_delivery_status_of_the_settlement_it_resolved() -> None:
    reported = []

    async def delivery_status(found):
        reported.append(found)
        return {"status": "ready", "fulfillment_id": "f-1"}

    service = _service(evidence=Evidence(PAYMENTS), delivery_status=delivery_status)

    by_transaction = await service.wait("txn-1", timeout=5)
    by_negotiation = await service.wait("neg-1", timeout=5)

    assert reported == [PAYMENTS, PAYMENTS]
    for waited in (by_transaction, by_negotiation):
        assert waited["ready"] is True
        assert waited["status"] == "ready"
        assert waited["fulfillment_id"] == "f-1"


@pytest.mark.parametrize("terminal", ["ready", "failed", "ended"])
async def test_ready_failed_and_ended_end_the_wait(terminal) -> None:
    clock = Clock()
    service = _service(
        delivery_status=_ticking(clock, [{"status": "provisioning"}, {"status": terminal}]),
        clock=clock,
    )

    waited = await service.wait("neg-1", timeout=5)

    assert waited["ready"] is True
    assert waited["status"] == terminal
    assert waited["elapsed_ms"] == 2000


@pytest.mark.parametrize("status", ["provisioning", "verified", "refunded"])
async def test_another_status_polls_to_the_deadline(status) -> None:
    clock = Clock()
    service = _service(delivery_status=_ticking(clock, [{"status": status}]), clock=clock)

    waited = await service.wait("neg-1", timeout=2)

    assert waited["ready"] is False
    assert waited["status"] == status


async def test_an_unresolved_reference_polls_to_the_deadline() -> None:
    clock = Clock()
    evidence = Evidence(PAYMENTS)

    async def by_reference(key):
        clock.now += 1.0
        return await evidence.by_reference(key)

    async def delivery_status(_found):
        raise AssertionError("an unresolved reference has no delivery status")

    service = SettlementAdminRouteService(
        settlements=SettlementLookup(
            by_reference=by_reference, by_negotiation=evidence.by_negotiation
        ),
        delivery_status=delivery_status,
        poll_seconds=0.0,
        clock=clock,
    )

    waited = await service.wait("no-such-reference", timeout=2)

    assert waited["ready"] is False
    assert waited["status"] == "unknown"
    assert "last_error" not in waited
    assert evidence.consulted.count(("negotiation", "no-such-reference")) == 2


async def test_evidence_recorded_while_the_wait_runs_is_resolved() -> None:
    clock = Clock()
    evidence = Evidence()

    async def by_negotiation(key):
        # Recorded once the wait has polled for a second.
        clock.now += 1.0
        return PAYMENTS if clock.now >= 2.0 and key == PAYMENTS.negotiation_id else None

    service = SettlementAdminRouteService(
        settlements=SettlementLookup(
            by_reference=evidence.by_reference, by_negotiation=by_negotiation
        ),
        delivery_status=_ready,
        poll_seconds=0.0,
        clock=clock,
    )

    waited = await service.wait("neg-1", timeout=5)

    assert waited["ready"] is True
    assert waited["elapsed_ms"] == 2000


async def _ready(_found):
    return {"status": "ready"}


async def test_wait_polls_through_a_failed_delivery_status_read() -> None:
    clock = Clock()
    service = _service(
        delivery_status=_ticking(
            clock, [ConnectionError("site unreachable"), {"status": "ready"}]
        ),
        clock=clock,
    )

    waited = await service.wait("neg-1", timeout=5)

    assert waited["ready"] is True
    assert waited["status"] == "ready"
    assert "last_error" not in waited


async def test_a_failing_lookup_is_polled_through_and_reported_at_the_deadline() -> None:
    clock = Clock()
    failures = iter(("first outage", "second outage"))

    async def by_reference(_key):
        clock.now += 1.0
        raise ConnectionError(next(failures))

    service = SettlementAdminRouteService(
        settlements=SettlementLookup(
            by_reference=by_reference, by_negotiation=Evidence().by_negotiation
        ),
        delivery_status=_ready,
        poll_seconds=0.0,
        clock=clock,
    )

    waited = await service.wait("neg-1", timeout=2)

    assert waited["ready"] is False
    assert waited["status"] == "unknown"
    assert waited["last_error"] == "ConnectionError: second outage"


async def test_wait_reports_the_last_error_when_every_delivery_status_read_fails() -> None:
    clock = Clock()
    service = _service(
        delivery_status=_ticking(clock, [ConnectionError("outage")]), clock=clock
    )

    waited = await service.wait("neg-1", timeout=2)

    assert waited["ready"] is False
    assert waited["status"] == "unknown"
    assert waited["last_error"] == "ConnectionError: outage"


@pytest.mark.parametrize(
    "refusal",
    [LookupError("settled negotiation not found"), SettlementAdminRouteError(409, "conflict")],
    ids=["lookup", "route-error"],
)
async def test_a_refusal_the_delivery_status_raises_ends_the_wait(refusal) -> None:
    async def delivery_status(_found):
        raise refusal

    service = _service(delivery_status=delivery_status)

    with pytest.raises(type(refusal)):
        await service.wait("neg-1", timeout=5)


@pytest.mark.parametrize(
    "refusal",
    [LookupError("evidence is not this storefront's"), SettlementAdminRouteError(404, "gone")],
    ids=["lookup", "route-error"],
)
async def test_a_refusal_a_lookup_raises_ends_the_wait(refusal) -> None:
    async def by_reference(_key):
        raise refusal

    service = SettlementAdminRouteService(
        settlements=SettlementLookup(
            by_reference=by_reference, by_negotiation=Evidence().by_negotiation
        ),
        delivery_status=_ready,
        poll_seconds=0.0,
        clock=Clock(),
    )

    with pytest.raises(type(refusal)):
        await service.wait("neg-1", timeout=5)


async def test_a_read_that_recovers_clears_the_error_it_followed() -> None:
    clock = Clock()
    service = _service(
        delivery_status=_ticking(
            clock, [ConnectionError("site unreachable"), {"status": "provisioning"}]
        ),
        clock=clock,
    )

    waited = await service.wait("neg-1", timeout=3)

    assert waited["ready"] is False
    assert waited["status"] == "provisioning"
    assert "last_error" not in waited


async def test_a_storefront_without_dry_runs_refuses_them() -> None:
    service = SettlementAdminRouteService(
        settlements=Evidence().lookup(), delivery_status=_ready
    )

    for call in (service.verify, service.evaluate):
        with pytest.raises(SettlementAdminRouteError) as refused:
            await call("uid-1", {})
        assert refused.value.status_code == 404
