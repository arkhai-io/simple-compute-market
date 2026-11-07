"""Consumer replay of producer rulings with the shared, independent payments peer."""

import asyncio
import json
import hashlib
from copy import deepcopy

import pytest
from market_deal_lifecycle.adapters import (
    DeliveryEndIntent, DisputeAdapterTable, DisputeBinding, InterfaceRequest, submit_dispute,
)
from market_deal_lifecycle.operations import OperationKeys
from market_deal_lifecycle.terms import DisputeAuthority
from market_deal_lifecycle_contracts.models import Accepted, LifecycleCommand, Rejected, Unknown
from market_identity import Ed25519Signer, Identity, canonical_json
from market_arkhai_payments.fixtures.authority import PaymentsAuthority
from pydantic import SecretStr

from market_arkhai_mediation.adapter import MediationAdapter
from market_arkhai_mediation.claims import sign_claim, verify_claim
from market_arkhai_mediation.client import MediationClient, MediationCredential
from market_arkhai_mediation.contract import INTERFACE, vectors, wire
from market_arkhai_mediation.fixtures.traces import RulingTraceFake
from market_arkhai_mediation.models import Append, DeliveryEndClaim, Filing, ReadAfter, SignedDeliveryEndClaim

from test_adapter import Operations


DATA = vectors()
TRACES = DATA["ruling_traces"]


def identical(actual, expected):
    assert canonical_json(actual) == canonical_json(expected)


class PaymentsReplay:
    def __init__(self, trace):
        self.trace = trace
        self.at = trace["approvedAt"]
        self.transaction = trace["receipt"]["receipt"]["transaction"]
        self.engine = PaymentsAuthority(
            signer=Ed25519Signer(bytes.fromhex(DATA["keys"]["payments_seed_hex"])),
            clock=lambda: self.at, ledger="trace-approval",
        )
        self.engine.fund(trace["mandate"]["from"], "USD/6", 100000)
        self.engine.fund(trace["mandate"]["to"], "USD/6", 1)
        receipt = self.engine.approve(trace["mandate"], account=trace["mandate"]["from"])
        identical(receipt.model_dump(mode="json", by_alias=True, exclude_none=True), trace["receipt"])
        identical(self.engine.submit(self.transaction, trace["setup"]["request"]), trace["setup"]["response"])
        identical(self.snapshot(), trace["setup"]["snapshot"])
        self.lost = {}

    def snapshot(self):
        return self.engine.snapshot(self.transaction).model_dump(mode="json", by_alias=True, exclude_unset=True)

    def __call__(self, call):
        self.at = call["at"]
        assert call["transaction"] == self.transaction
        if call["operation"] == "event":
            request = {"account": call["account"], "requestId": call["idempotency_key"], "event": call["event"]}
            response = self.engine.submit(self.transaction, request)
            key = call["account"], call["idempotency_key"]
            if "uncertain" in call:
                self.lost[key] = (deepcopy(request), deepcopy(response))
            else:
                identical(response, call["response"])
                if key in self.lost:
                    original, answer = self.lost.pop(key)
                    identical(request, original)
                    identical(response, answer)
        elif call["operation"] == "read":
            identical(self.trace["mandate"], call["response"]["mandate"])
            identical(self.snapshot()["snapshot"], call["response"]["snapshot"])
        else:
            assert call["operation"] == "snapshot"
            identical(self.snapshot(), call["response"])
        identical(self.snapshot(), call["snapshot"])


@pytest.mark.parametrize("trace", TRACES, ids=lambda t: t["name"])
@pytest.mark.parametrize("surface", ["client", "adapter"])
def test_published_ruling_trace(trace, surface):
    async def replay():
        payments = PaymentsReplay(trace)
        input_keys = {}
        if surface == "adapter":
            for i, item in enumerate(trace["inputs"]):
                keys = OperationKeys(trace["name"], str(i))
                identity = hashlib.sha256(canonical_json({
                    "commitment": payments.transaction, "agreement": trace["mandate"]["deal"],
                    "authority": trace["agreement"]["settlement"]["lifecycle"]["adjudication"]["dispute"],
                })).hexdigest()
                input_keys[item["idempotency_key"]] = (
                    hashlib.sha256(canonical_json([identity, item["request"]["request"]])).hexdigest()
                    if item["operation"] == "file" else keys.append(item["request"]["case_ref"]))
        peer = RulingTraceFake(trace, payments, input_keys=input_keys)
        authority = DisputeAuthority.model_validate(peer.authority)
        binding = DisputeBinding(trace["name"], payments.transaction, authority)
        captured = []
        operations = Operations()
        clients = {}
        adapters = {}
        for actor, token in [(peer.payer, "fixture-payer"), (peer.payee, "fixture-payee")]:
            client = MediationClient(
                authority, MediationCredential(authority.identity, token=SecretStr(token)),
                transport=peer.transport(), capture=captured.append,
            )
            clients[actor] = client
            adapters[actor] = MediationAdapter(binding, trace["agreement"], client, clock=lambda: payments.at)
        try:
            for step in trace["timeline"]:
                payments.at = step["at"]
                if "input" in step:
                    i = step["input"]
                    item = trace["inputs"][i]
                    client = clients[item["actor"]]
                    adapter = adapters[item["actor"]]
                    concurrence = item["request"].get("concurrence")
                    if concurrence:
                        signed = SignedDeliveryEndClaim.model_validate(concurrence)
                        seller = Identity.model_validate(trace["agreement"]["seller"])
                        exact_claim = (item["request"].get("request")
                            or trace["inputs"][0]["request"]["request"])
                        assert verify_claim(signed, agreement=trace["mandate"]["deal"], seller=seller,
                            claim=DeliveryEndClaim.model_validate(exact_claim)) == (trace.get("guard") not in {
                                "bad_signature", "wrong_agreement", "different_claim"})
                        if trace.get("guard") != "bad_signature":
                            reproduced = sign_claim(agreement=concurrence["agreement"], claim=signed.claim,
                                signer=Ed25519Signer(bytes.fromhex(DATA["keys"]["market_ed25519_seed_hex"])))
                            identical(wire(reproduced), concurrence)
                    if surface == "client":
                        if item["operation"] == "file":
                            answer = await client.file(Filing.model_validate(item["request"]),
                                                       idempotency_key=item["idempotency_key"])
                        else:
                            answer = await client.append(Append.model_validate(item["request"]),
                                idempotency_key=item["idempotency_key"], agreement=trace["mandate"]["deal"],
                                transaction=payments.transaction)
                        identical(wire(answer), item["response"])
                    else:
                        payload = item["request"]
                        if item["operation"] == "file":
                            intent = DeliveryEndIntent.model_validate(payload["request"])
                            adapter = MediationAdapter(binding, trace["agreement"], client,
                                clock=lambda: payments.at, concurrence=(
                                    SignedDeliveryEndClaim.model_validate(concurrence) if concurrence else None))
                            mapped = adapter.build_request(intent)
                            kind = "delivery_end"
                            command_payload = intent.model_dump(mode="json")
                            if trace.get("guard") in {"bad_signature", "wrong_agreement", "different_claim"}:
                                assert isinstance(mapped, Rejected)
                                # Raw evidence remains admissible to the operator even when it
                                # cannot be adopted as a verified receipt by the intent mapper.
                                mapped = InterfaceRequest(interface=INTERFACE, payload={
                                    k: v for k, v in payload.items() if k not in {"transaction", "agreement"}})
                                kind = "dispute"
                                command_payload = mapped.model_dump(mode="json")
                            assert not isinstance(mapped, Rejected)
                        else:
                            kind, command_payload = "append", payload
                        command = LifecycleCommand(negotiation_id=binding.negotiation_id, kind=kind,
                                                   operation_key=str(i), payload=command_payload)
                        table = DisputeAdapterTable([(INTERFACE, lambda _: adapter)])
                        if item["operation"] == "file" and any(
                            prior["operation"] == "file" for prior in trace["inputs"][:i]
                        ):
                            # Lifecycle cannot map linked revisions safely. The raw
                            # client still replays the producer's operator workflow.
                            refused = await submit_dispute(command, binding, table, operations)
                            assert isinstance(refused, Rejected) and "repair required" in refused.reason
                            answer = await client.file(Filing.model_validate(payload),
                                idempotency_key=input_keys[item["idempotency_key"]])
                            identical(wire(answer), item["response"])
                            continue
                        peer.lose_next_response = True
                        unknown = await submit_dispute(command, binding, table, operations)
                        assert isinstance(unknown, Unknown), unknown
                        calls = len(peer.payments_calls)
                        result = await submit_dispute(command, binding, table, operations)
                        assert isinstance(result, Accepted), result
                        # A replay must adopt the original filing/append, not extend or rule again.
                        again = await submit_dispute(command, binding, table, operations)
                        identical(again.model_dump(mode="json"), result.model_dump(mode="json"))
                        assert len(peer.payments_calls) == calls
                        changed = command.model_copy(update={"payload": {**command.payload, "extra": True}})
                        count = len(peer.requests)
                        assert isinstance(await submit_dispute(changed, binding, table, operations), Rejected)
                        assert len(peer.requests) == count
                        if item["operation"] == "append":
                            identical(json.loads(captured[-1]), item["response"])
                        else:
                            identical(json.loads(captured[-1])["entries"], peer.entries)
                else:
                    identical(peer.checkpoint(step["operation"]), trace["checkpoints"][step["checkpoint"]]["response"])
                view = await adapters[peer.payee].read()
                assert isinstance(view.outcome, Accepted), view.outcome
                identical([json.loads(e.items[0].body) for e in view.disputes],
                          peer.entries)
                page = await clients[peer.payee].read_record(ReadAfter.model_validate({
                    "agreement": trace["mandate"]["deal"], "after": 0, "limit": 1000,
                }), transaction=payments.transaction)
                identical(wire(page)["entries"], peer.entries)
            identical(peer.entries, trace["records"])
            identical(peer.payments_calls, trace["payments_calls"])
            identical(payments.snapshot(), trace["final_snapshot"])
            assert not payments.lost
            for final in trace["final_cases"]:
                case = final["answer"]["case"]
                actual = await clients[peer.payee].case(case["case_ref"],
                    agreement=trace["mandate"]["deal"], transaction=payments.transaction)
                identical(wire(actual), final["answer"])
        finally:
            for client in clients.values():
                await client.close()
    asyncio.run(replay())
