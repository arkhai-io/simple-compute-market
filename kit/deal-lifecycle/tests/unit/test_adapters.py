"""Neutral dispatch refuses before I/O and derives stable authority operation keys."""

import asyncio
from dataclasses import replace

import pytest

from market_deal_lifecycle_contracts.models import Accepted, LifecycleCommand, Rejected
from market_deal_lifecycle.adapters import (
    DeliveryEndIntent, DisputeAdapterTable, DisputeBinding, InterfaceRequest,
    PaymentAdapterTable, PaymentBinding, PaymentSelector, submit_dispute, submit_payment,
)
from market_deal_lifecycle.authorities import derive_stop_authorities, entitled_stop
from market_deal_lifecycle.delivery import (
    ActivatedDeliveryRef, DeliveryEvidence, DeliveryPhase, OnceDeliveryPolicy,
)
from market_deal_lifecycle.operations import OperationKeys
from market_deal_lifecycle.terms import DisputeAuthority, decode_terms
from test_terms import AUTHORITY, terms


class Store:
    def __init__(self):
        self.values = {}

    async def check_and_record(self, negotiation_id, operation_key, digest):
        key = negotiation_id, operation_key
        return self.values.setdefault(key, digest) == digest


class Adapter:
    supported_commands = frozenset({"reverse", "dispute", "delivery_end", "append"})
    supported_intents = frozenset({"delivery_end"})

    def __init__(self):
        self.calls = []

    def validate(self, command):
        return None

    def build_request(self, intent):
        assert isinstance(intent, DeliveryEndIntent)
        return InterfaceRequest(interface=AUTHORITY["interface"], payload=intent.model_dump())

    def validate_request(self, request):
        return None

    async def submit(self, *args):
        self.calls.append(args)
        return Accepted()


def command(kind="reverse", **changes):
    return LifecycleCommand(**dict(dict(negotiation_id="n", operation_key="op", kind=kind, at=100), **changes))


def test_no_payment_adapter_for_a_command_and_exact_arbiter_resolution():
    adapter = Adapter()
    selector = PaymentSelector("example.payment", "arbiter", "oracle", "oracle.schema")
    bindings = []
    def factory(binding):
        bindings.append(binding)
        return adapter
    table = PaymentAdapterTable([(selector, factory)])
    binding = PaymentBinding("n", selector)
    result = asyncio.run(submit_payment(command("stop"), binding, table, Store()))
    assert result.status == "rejected" and "stop" in result.reason
    assert not adapter.calls
    assert bindings == [binding]
    assert table.resolve(replace(binding, selector=replace(selector, oracle="other"))) is None


def test_a_retry_changes_content_before_authority_io():
    adapter, store = Adapter(), Store()
    binding = PaymentBinding("n", PaymentSelector("example.payment"))
    table = PaymentAdapterTable([(binding.selector, lambda _: adapter)])
    async def drive():
        assert (await submit_payment(command(), binding, table, store)).status == "accepted"
        assert (await submit_payment(command(), binding, table, store)).status == "accepted"
        result = await submit_payment(command(at=101), binding, table, store)
        assert result.status == "rejected" and "changes content" in result.reason
    asyncio.run(drive())
    assert len(adapter.calls) == 2
    assert adapter.calls[0][1] == adapter.calls[1][1]


def test_no_dispute_adapter_and_unsupported_intent():
    binding = DisputeBinding("n", "c", DisputeAuthority(**AUTHORITY))
    cmd = command("delivery_end", payload={"ended_at": 100, "delivered": True, "cause": "payer"})
    result = asyncio.run(submit_dispute(cmd, binding, DisputeAdapterTable([]), Store()))
    assert result.status == "rejected" and AUTHORITY["interface"] in result.reason
    adapter = Adapter()
    adapter.supported_intents = frozenset()
    table = DisputeAdapterTable([(AUTHORITY["interface"], lambda _: adapter)])
    result = asyncio.run(submit_dispute(cmd, binding, table, Store()))
    assert result.status == "rejected" and "delivery_end" in result.reason
    assert adapter.calls == []


@pytest.mark.parametrize("cause", ["payer", "payee"])
def test_either_delivery_end_cause_is_an_intent_never_a_payment_event(cause):
    adapter, store = Adapter(), Store()
    binding = DisputeBinding("n", "c", DisputeAuthority(**AUTHORITY))
    table = DisputeAdapterTable([(AUTHORITY["interface"], lambda _: adapter)])
    cmd = command("delivery_end", payload={"ended_at": 100, "delivered": False, "cause": cause})
    assert asyncio.run(submit_dispute(cmd, binding, table, store)).status == "accepted"
    assert adapter.calls[0][1].payload["cause"] == cause
    payment = PaymentBinding("n", PaymentSelector("example.payment"))
    result = asyncio.run(submit_payment(cmd, payment, PaymentAdapterTable([]), Store()))
    assert result.status == "rejected" and "not a payment command" in result.reason


def test_operation_keys_separate_records_and_return_identically_on_retry():
    keys = OperationKeys("n", "op")
    assert keys == OperationKeys("n", "op")
    assert len({keys.part_event("p1", "stop"), keys.part_event("p2", "stop"),
                keys.part_event("p1", "reverse"), keys.filing(), keys.append("case")}) == 5


def test_on_demand_stop_authorities_come_only_from_entitlements():
    early = decode_terms(terms()).early_termination
    entries = derive_stop_authorities(early, payer="buyer", payee="seller", dispute="authority",
                                      stoppable=True, supported_partial_periods=frozenset({"charged", "returned", "chosen"}))
    assert [(e.account, e.notice_seconds, e.partial_period) for e in entries] == [
        ("buyer", 0, "charged"), ("authority", 0, "chosen"),
    ]
    assert entitled_stop("buyer", entries, notice_seconds=0, partial_period="charged") == entries[0]
    for account, notice, treatment in [("seller", 0, "charged"), ("buyer", 0, "returned"),
                                       ("buyer", 1, "charged"), ("authority", 0, "chosen")]:
        with pytest.raises(ValueError):
            entitled_stop(account, entries, notice_seconds=notice, partial_period=treatment)
    with pytest.raises(ValueError, match="installed payment contract"):
        derive_stop_authorities(early, payer="buyer", payee="seller", dispute="authority", stoppable=True)
    assert derive_stop_authorities(None, payer="buyer", payee="seller", dispute="authority", stoppable=False) == ()


def test_once_delivery_requires_validated_commitment_and_activation_for_noop_start():
    async def valid(evidence):
        return evidence.commitment_ref == "verified"
    policy = OnceDeliveryPolicy(valid)
    evidence = DeliveryEvidence(negotiation_id="n", commitment_ref="verified")
    async def drive():
        assert (await policy.authorize(DeliveryPhase.COMMIT, evidence)).status == "allow"
        assert (await policy.authorize(DeliveryPhase.COMMIT,
                evidence.model_copy(update={"commitment_ref": "unverified"}))).status == "refuse"
        assert (await policy.start_billing("op", evidence)).outcome.status == "rejected"
        activated = evidence.model_copy(update={"activated_delivery": ActivatedDeliveryRef(record_ref="a", activated_at=100)})
        result = await policy.start_billing("op", activated)
        assert result.outcome.status == "accepted" and result.no_op
    asyncio.run(drive())
