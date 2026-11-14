"""Rate authorization, stable money-operation keys and verified authority reads."""

import asyncio
from copy import deepcopy

import pytest
from market_deal_lifecycle.delivery import BillingStartResult, DeliveryPhase
from market_deal_lifecycle.operations import OperationKeys
from market_deal_lifecycle_contracts.models import LifecycleCommand, Rejected
from market_arkhai_payments.errors import PaymentsAPIError, PaymentsTransportError
from market_arkhai_payments.fixtures import FakePaymentsClient
from market_arkhai_payments.fixtures.authority import sign_snapshot
from market_arkhai_payments.operations import operations_digest
from market_arkhai_payments.rate_adapter import RatePaymentAdapter
from market_arkhai_payments.seller import PaymentSellerStage

from payment_terms import BUYER, PAYEE, config
from rate_terms import NOW, approved


class ControlledPayments(FakePaymentsClient):
    lose = False
    error = None
    snapshot_change = None

    def submit_event(self, transaction, event, *, request_id):
        if self.error is not None:
            raise PaymentsAPIError(*self.error)
        result = super().submit_event(transaction, event, request_id=request_id)
        if self.lose:
            self.lose = False
            raise PaymentsTransportError("lost after recording")
        return result

    def _snapshot(self, transaction):
        signed = super()._snapshot(transaction)
        if self.snapshot_change is not None:
            snapshot = deepcopy(signed.snapshot)
            self.snapshot_change(snapshot)
            return sign_snapshot(self.signer, snapshot.model_dump(mode="json", by_alias=True, exclude_none=True))
        return signed


async def start(adapter, evidence, key="billing"):
    operations = adapter.billing_operations(key, evidence)
    return await adapter.start_billing(key, evidence, journaled_digest=operations_digest(operations))


async def send(adapter, kind, *, key="operation", **payload):
    command = LifecycleCommand(
        negotiation_id=adapter.negotiation_id, kind=kind, operation_key=key, payload=payload,
    )
    keys = OperationKeys(command.negotiation_id, key)
    return await adapter.submit(command, keys, journaled_digest=adapter.describe(command, keys).digest)


@pytest.mark.parametrize("phase,state,expected", [
    (DeliveryPhase.COMMIT, "approved", "allow"),
    (DeliveryPhase.COMMIT, "approval_expired", "allow"),
    (DeliveryPhase.DISPATCH, "approved", "allow"),
    (DeliveryPhase.START, "approved", "allow"),
    (DeliveryPhase.START, "unreserved", "pending"),
    (DeliveryPhase.START, "future_stop", "allow"),
    (DeliveryPhase.START, "effective_stop", "refuse"),
    (DeliveryPhase.START, "end", "refuse"),
    (DeliveryPhase.START, "stale", "pending"),
    (DeliveryPhase.START, "unavailable", "pending"),
    (DeliveryPhase.START, "unverified", "pending"),
    (DeliveryPhase.START, "regressing", "pending"),
    (DeliveryPhase.START, "cross_deal", "refuse"),
    (DeliveryPhase.DISCLOSE, "approved", "pending"),
    (DeliveryPhase.DISCLOSE, "started", "allow"),
    (DeliveryPhase.DISCLOSE, "wrong_intent", "pending"),
    (DeliveryPhase.DISCLOSE, "refused_start", "refuse"),
    (DeliveryPhase.DISCLOSE, "exhausted", "refuse"),
    ("unknown_phase", "approved", "refuse"),
])
def test_authorization_phase_table_is_pure_and_uses_verified_current_bounds(phase, state, expected):
    async def drive():
        raw, data, fake, adapter, evidence = approved(client_type=ControlledPayments)
        kwargs = {}
        if state in {"started", "wrong_intent", "refused_start", "exhausted"}:
            assert (await start(adapter, evidence)).outcome.status == "accepted"
            kwargs["billing_operation_key"] = "other" if state == "wrong_intent" else "billing"
        if state == "refused_start":
            kwargs["billing_start_result"] = BillingStartResult(outcome=Rejected(reason="transaction_stopped"))
        if state == "exhausted":
            fake.snapshot_change = lambda snapshot: setattr(snapshot, "fundedThrough", NOW)
        if state in {"future_stop", "effective_stop"}:
            assert (await send(adapter, "stop", part="1")).status == "accepted"
            if state == "effective_stop":
                fake.observed_at += 30
        if state == "end":
            fake.observed_at += 3600
        if state == "unreserved":
            fake.snapshot_change = lambda snapshot: setattr(snapshot.parts[1], "reserved", None)
        if state == "approval_expired":
            fake.observed_at += 61
        if state == "stale":
            adapter._clock = lambda: NOW + 6
        if state == "unavailable":
            fake.unavailable = True
        if state == "unverified":
            adapter._verify = lambda signed, floor: False
        if state == "regressing":
            adapter._minimum_sequence = 100
        if state == "cross_deal":
            evidence = evidence.model_copy(update={"commitment_ref": "other"})
        count = fake.count("submit_event")
        answer = await adapter.authorize(phase, evidence, **kwargs)
        assert answer.status == expected, answer
        assert answer.operation_id and answer.evidence_refs
        assert fake.count("submit_event") == count
    asyncio.run(drive())


@pytest.mark.parametrize("storefront_skew,expected", [
    (-3600, "allow"), (-1, "allow"), (0, "allow"), (5, "allow"), (6, "pending"), (3600, "pending"),
])
def test_a_snapshot_decides_a_phase_only_within_the_freshness_window(storefront_skew, expected):
    # The authority's observedAt and the storefront's clock are independent
    # claims. A view observed ahead of the storefront's clock is as fresh as it
    # gets; one lagging it by more than the window must be refreshed first.
    async def drive():
        _, _, _, adapter, evidence = approved(client_type=ControlledPayments)
        adapter._clock = lambda: NOW + storefront_skew
        assert (await adapter.authorize(DeliveryPhase.START, evidence)).status == expected
    asyncio.run(drive())


def test_bounds_are_checked_at_the_storefronts_clock_inside_the_window():
    # The authority observed the pending stop before it took effect, but by the
    # storefront's clock it already has: the phase is refused, not allowed on
    # the authority's older view of time.
    async def drive():
        _, _, fake, adapter, evidence = approved(client_type=ControlledPayments)
        assert (await send(adapter, "stop", part="1")).status == "accepted"
        stop_at = NOW + 30
        fake.observed_at = stop_at - 2
        adapter._clock = lambda: stop_at + 1
        assert (await adapter.authorize(DeliveryPhase.START, evidence)).status == "refuse"
    asyncio.run(drive())


def test_the_seller_stage_decides_with_the_configured_freshness_window():
    # A storefront eight seconds ahead of the authority is outside the default
    # window but inside a configured ten-second one.
    raw, data, fake, _, evidence = approved(client_type=ControlledPayments)

    def answer(**settings):
        stage = PaymentSellerStage(config(**settings), client_for_owner=fake)
        adapter = stage.payment_adapter(raw, data)
        adapter._clock = lambda: NOW + 8
        return asyncio.run(adapter.authorize(DeliveryPhase.START, evidence)).status

    assert answer() == "pending"
    assert answer(snapshot_freshness_seconds=10) == "allow"


@pytest.mark.parametrize("window", [0, 301])
def test_the_configured_freshness_window_is_bounded(window):
    with pytest.raises(ValueError, match="snapshot_freshness_seconds"):
        config(snapshot_freshness_seconds=window)


def test_the_freshness_window_is_positive_whole_seconds():
    raw, data, fake, _, _ = approved(client_type=ControlledPayments)
    for window in (0, -1, 1.5):
        with pytest.raises(ValueError, match="freshness"):
            RatePaymentAdapter(raw, data, account=PAYEE, client_for_owner=fake,
                               verify_snapshot=lambda signed, floor: True, snapshot_freshness_seconds=window)


def test_start_stop_and_reverse_have_distinct_stable_keys_and_recover_lost_answers():
    async def drive():
        _, _, fake, adapter, evidence = approved(client_type=ControlledPayments)
        ops = adapter.billing_operations("shared", evidence)
        assert (await adapter.start_billing("shared", evidence)).outcome.status == "rejected"
        assert fake.count("submit_event") == 0
        fake.lose = True
        assert (await start(adapter, evidence, "shared")).outcome.status == "unknown"
        assert (await start(adapter, evidence, "shared")).outcome.status == "accepted"
        assert fake.count("submit_event") == 1
        assert (await send(adapter, "stop", key="shared", part="1")).status == "accepted"
        pending = await adapter.read()
        assert pending.state == "ending"
        assert pending.parts[0].pending_stop.at == NOW + 30
        assert pending.parts[0].pending_stop.kind == "stop_request"
        # Earning advances through the authority clock, without a wall-time wait.
        fake.observed_at = NOW + 30
        settled = fake.get_transaction(adapter.commitment_ref).snapshot.parts[1].stop
        # A different event under the same outer operation uses a distinct key.
        fake.lose = True
        reversed_once = await send(adapter, "reverse", key="shared", part="1", amount="1")
        assert reversed_once.status == "unknown", reversed_once
        assert (await send(adapter, "reverse", key="shared", part="1", amount="1")).status == "accepted"
        changed = await send(adapter, "reverse", key="shared", part="1", amount="2")
        assert changed.status == "rejected" and "changes content" in changed.reason
        snapshot = fake.get_transaction(adapter.commitment_ref).snapshot
        stored = [wrapped.root for wrapped in snapshot.events
                  if hasattr(wrapped.root, "requestId") and wrapped.root.event.part == 1]
        ids = [item.requestId.root for item in stored]
        assert len(ids) == len(set(ids)) == 3
        assert ops[0].request_id in ids
        ended = await adapter.read()
        final = ended.parts[0].final_stop
        assert final.at == NOW + 30 and final.actor != BUYER
        assert final.settles_through == "started_period"
        # Post-stop held reversal does not rewrite stop settlement evidence.
        assert (await send(adapter, "reverse", key="after-stop", part="1", amount="1")).status == "accepted"
        assert (await adapter.read()).parts[0].final_stop == final
        assert fake.get_transaction(adapter.commitment_ref).snapshot.parts[1].stop == settled
    asyncio.run(drive())


@pytest.mark.parametrize("invalid", ["missing_activation", "other_deal", "before_start", "future", "term_end", "digest"])
def test_billing_requires_journaled_deal_bound_activation_before_any_effect(invalid):
    async def drive():
        _, _, fake, adapter, evidence = approved()
        if invalid == "missing_activation":
            evidence = evidence.model_copy(update={"activated_delivery": None})
        elif invalid == "other_deal":
            evidence = evidence.model_copy(update={"negotiation_id": "another-deal"})
        elif invalid in {"before_start", "future", "term_end"}:
            at = {"before_start": NOW - 1, "future": NOW + 1, "term_end": NOW + 3600}[invalid]
            evidence = evidence.model_copy(update={"activated_delivery": evidence.activated_delivery.model_copy(update={"activated_at": at})})
            if invalid == "term_end":
                fake.observed_at = at
        result = await adapter.start_billing("billing", evidence, journaled_digest="different")
        expected = {
            "missing_activation": "verified activation", "other_deal": "another deal",
            "before_start": "outside the accepted service interval", "future": "outside the accepted service interval",
            "term_end": "at or beyond", "digest": "journaled descriptor digest",
        }[invalid]
        assert result.outcome.status == "rejected" and expected in result.outcome.reason
        assert fake.count("submit_event") == 0
    asyncio.run(drive())


@pytest.mark.parametrize("code,status,kind,expected,reason", [
    ("transaction_stopped", 409, "start", "rejected", "delivery must end"),
    ("request_id_reused", 409, "reverse", "rejected", "repair required"),
    ("request_id_reused", 503, "reverse", "unknown", "request_id_reused"),
    ("hold_not_reversible", 409, "reverse", "rejected", "repair required"),
    ("hold_not_reversible", 503, "reverse", "unknown", "hold_not_reversible"),
    ("insufficient_held_funds", 409, "reverse", "rejected", "reconcile recorded reversals"),
    ("hold_matured", 409, "reverse", "rejected", "case path"),
    ("unavailable", 503, "reverse", "unknown", "unavailable"),
    ("rate_limited", 429, "reverse", "unknown", "rate_limited"),
])
def test_refusals_preserve_repair_case_and_retry_classification(code, status, kind, expected, reason):
    async def drive():
        _, _, fake, adapter, evidence = approved(client_type=ControlledPayments)
        fake.error = (status, code)
        before = fake.count("get_transaction")
        if kind == "start":
            result = (await start(adapter, evidence)).outcome
        else:
            result = await send(adapter, "reverse", part="1", amount="1")
        assert result.status == expected and reason in result.reason
        if code == "insufficient_held_funds":
            assert fake.count("get_transaction") >= before + 2
    asyncio.run(drive())
