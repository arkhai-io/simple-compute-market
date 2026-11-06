"""The lifecycle API against the published, in-process mediation contract peer."""

import asyncio
from copy import deepcopy

import httpx
import pytest
from pydantic import SecretStr

from market_deal_lifecycle.adapters import (
    DeliveryEndIntent, DisputeAdapterTable, DisputeBinding, InterfaceRequest, submit_dispute,
)
from market_deal_lifecycle.terms import DisputeAuthority
from market_deal_lifecycle_contracts.models import LifecycleCommand

from market_arkhai_mediation.adapter import MediationAdapter
from market_arkhai_mediation.client import MediationClient, MediationCredential
from market_arkhai_mediation.contract import INTERFACE, wire
from market_arkhai_mediation.fixtures.authority import MediationContractFake
from market_arkhai_mediation.fixtures import market_signer


class Operations:
    def __init__(self):
        self.commands = {}

    async def check_and_record(self, negotiation_id, operation_key, digest):
        key = negotiation_id, operation_key
        return self.commands.setdefault(key, digest) == digest


class Scenario:
    def __init__(self, peer=None, transport=None):
        self.peer = peer or MediationContractFake()
        self.authority = DisputeAuthority.model_validate(self.peer.authority)
        filing = self.peer.data["filing"]["request"]
        self.binding = DisputeBinding("negotiation-fixture", filing["transaction"], self.authority)
        self.captured = []
        self.client = MediationClient(
            self.authority,
            MediationCredential(self.authority.identity, token=SecretStr("fixture-payee")),
            transport=transport or self.peer.transport(), capture=self.captured.append,
        )
        self.adapter = MediationAdapter(
            self.binding, filing["agreement"], self.client, clock=lambda: 1800001800,
        )
        self.table = DisputeAdapterTable([(INTERFACE, lambda binding: self.adapter)])
        self.operations = Operations()

    async def file(self, key="filing", request=None):
        request = request or self.adapter.effects_request(
            [{"kind": "reverse", "part": 0, "amount": "1"}], claim="Operator review requested.",
            items=self.peer.data["filing"]["request"]["items"],
        )
        return await self.submit("dispute", key, request.model_dump(mode="json"))

    async def submit(self, kind, key, payload):
        return await submit_dispute(
            LifecycleCommand(
                negotiation_id=self.binding.negotiation_id, kind=kind,
                operation_key=key, payload=payload,
            ), self.binding, self.table, self.operations,
        )


def run(scenario):
    asyncio.run(scenario())


def test_an_unmigrated_positional_credential_fails_at_construction():
    authority = DisputeAuthority.model_validate(MediationContractFake().authority)
    with pytest.raises(TypeError):
        MediationCredential(authority.identity, "DEMO_PAYEE")  # type: ignore[misc]


@pytest.mark.parametrize("token", ["fixture-payee", b"fixture-payee"], ids=["str", "bytes"])
def test_a_token_that_is_not_a_secret_value_is_refused(token):
    authority = DisputeAuthority.model_validate(MediationContractFake().authority)
    with pytest.raises(TypeError, match="SecretStr"):
        MediationCredential(authority.identity, token=token)


@pytest.mark.parametrize(
    "token", ["", " fixture-payee", "fixture-payee ", "fixture\r\npayee", "fixture\npayee"],
    ids=["empty", "leading-space", "trailing-space", "crlf", "lf"],
)
def test_an_unusable_token_is_refused_without_quoting_it(token):
    authority = DisputeAuthority.model_validate(MediationContractFake().authority)
    with pytest.raises(ValueError) as refused:
        MediationCredential(authority.identity, token=SecretStr(token))
    if token.strip():
        assert token.strip() not in str(refused.value)


def test_a_credential_bound_to_another_authority_is_refused():
    authority = DisputeAuthority.model_validate(MediationContractFake().authority)
    other = (*authority.identity[:3], "another-record-key")
    with pytest.raises(ValueError, match="another authority"):
        MediationClient(authority, MediationCredential(other, token=SecretStr("fixture-payee")))


def test_the_client_authenticates_with_exactly_the_credentials_token():
    peer = MediationContractFake()
    seen: list[str] = []
    inner = peer.transport()

    class Recording(httpx.AsyncBaseTransport):
        async def handle_async_request(self, request):
            seen.append(request.headers["Authorization"])
            return await inner.handle_async_request(request)

    async def scenario():
        s = Scenario(peer=peer, transport=Recording())
        try:
            assert (await s.file()).status == "accepted"
        finally:
            await s.client.close()
    run(scenario)
    assert seen and set(seen) == {"Bearer fixture-payee"}


@pytest.mark.parametrize("scheme", ["ed25519", "eip191"])
def test_receipt_claim_adapter_needs_no_online_credential(scheme):
    peer = MediationContractFake()
    signer = market_signer(scheme)
    filing = peer.data["filing"]["request"]
    authority = DisputeAuthority.model_validate(peer.authority)
    binding = DisputeBinding("deal", filing["transaction"], authority)
    agreement = {**filing["agreement"], "seller": signer.identity.model_dump(mode="json")}
    adapter = MediationAdapter(binding, agreement)
    intent = DeliveryEndIntent(ended_at=1800000000, delivered=True, cause="payer")
    signed = adapter.sign_delivery_end(intent, signer)
    assert adapter.verify_delivery_end(signed, intent)
    assert asyncio.run(adapter.read()).outcome.status == "rejected"


def test_two_cases_on_one_deal():
    async def scenario():
        s = Scenario()
        try:
            first = await s.file("first")
            s.peer.decide(first.filing.case_ref, [{
                "id": "effect-fixture", "state": "applied",
                "effect": {"kind": "reverse", "part": 0, "amount": "1"},
            }])
            second = await s.file("second")
            view = await s.adapter.read()
            assert first.filing.case_ref != second.filing.case_ref
            assert len(view.cases) == 2
            assert [event.sequence for event in view.disputes] == [1, 2, 3, 4]
            assert view.cases[0].outcome[0].amount == "1"
            assert view.cases[1].outcome == []
            assert view.extensions == []  # A case's protection is not a payments extension read.
        finally:
            await s.client.close()
    run(scenario)


@pytest.mark.parametrize("parts", [
    [{"part": 0, "status": "held", "extension_ref": 1},
     {"part": 1, "status": "not_held", "reason": "paid_out"}],
    [{"part": 0, "status": "not_held", "reason": "reversed"}],
    [{"part": 0, "status": "not_held", "reason": "paid_out"}],
])
def test_parts_differ_wholly_reversed_or_payout_wins(parts):
    async def scenario():
        s = Scenario()
        s.peer.parts = parts
        try:
            answer = await s.file()
            assert answer.status == "accepted"
            assert [(part.part, part.status) for part in answer.filing.parts] == [
                (str(part["part"]), part["status"]) for part in parts
            ]
            for actual, expected in zip(answer.filing.parts, parts):
                if expected["status"] == "not_held":
                    assert actual.reason == expected["reason"]
                else:
                    assert actual.extension_ref
            # Even an entirely paid-out deal has an accepted filing, not a local refusal.
            view = await s.adapter.read()
            assert view.outcome.status == "accepted"
        finally:
            await s.client.close()
    run(scenario)


def test_late_case_ends_delivery_filing_half():
    async def scenario():
        s = Scenario()
        s.peer.parts = [{"part": 0, "status": "not_held", "reason": "paid_out"}]
        try:
            answer = await s.file(request=s.adapter.effects_request(
                [{"kind": "end_delivery", "at": 1800001800}], claim="End remaining delivery.",
            ))
            assert answer.status == "accepted"
            assert answer.filing.parts[0].reason == "paid_out"
            submitted = s.peer.entries[0]["entry"]["filing"]
            assert submitted["request"]["effects"] == [{"kind": "end_delivery", "at": 1800001800}]
            assert all(event.outcome == [] for event in (await s.adapter.read()).disputes)
        finally:
            await s.client.close()
    run(scenario)


def test_filings_lost_response_same_key_and_changed_retry():
    async def scenario():
        s = Scenario()
        try:
            s.peer.lose_next_response = True
            assert (await s.file()).status == "unknown"
            assert len((await s.adapter.read()).cases) == 1
            replay = await s.file()
            assert replay.status == "accepted"
            assert len(s.peer.cases) == 1
            changed = await s.file(request=s.adapter.effects_request(
                [{"kind": "reverse", "part": 0, "amount": "2"}], claim="Changed.",
            ))
            assert changed.status == "rejected"
            assert len(s.peer.cases) == 1
        finally:
            await s.client.close()
    run(scenario)


def test_case_closes_during_append_keeps_original_acknowledgement():
    async def scenario():
        s = Scenario()
        try:
            filed = await s.file()
            payload = deepcopy(s.peer.data["append"]["request"])
            payload["case_ref"] = filed.filing.case_ref
            s.peer.close_after_append = True
            s.peer.lose_next_response = True
            assert (await s.submit("append", "append", payload)).status == "unknown"
            replay = await s.submit("append", "append", payload)
            assert replay.status == "accepted"
            assert replay.records[0].sequence == 2
            assert sum(entry["entry"]["kind"] == "appended" for entry in s.peer.entries) == 1
            late = await s.submit("append", "late-append", payload)
            assert late.status == "rejected" and "case_closed" in late.reason
        finally:
            await s.client.close()
    run(scenario)


def test_claimant_adds_evidence_as_payee():
    async def scenario():
        s = Scenario()
        try:
            filed = await s.file()
            payload = deepcopy(s.peer.data["append"]["request"])
            payload["case_ref"] = filed.filing.case_ref
            answer = await s.submit("append", "append", payload)
            assert answer.status == "accepted"
            view = await s.adapter.read()
            assert [event.actor for event in view.disputes] == [s.peer.payee, s.peer.payee]
            assert [entry["entry"]["kind"] for entry in s.peer.entries] == ["filed", "appended"]
            assert s.peer.entries[1]["entry"]["items"] == payload["items"]
            assert s.captured
        finally:
            await s.client.close()
    run(scenario)


@pytest.mark.parametrize("answer,status", [
    ({"status": "pending", "case_ref": "pending-fixture"}, "pending"),
    ({"status": "error", "code": "protection_incomplete", "message": "Not protected."}, "pending"),
    ({"status": "rejected", "reason": "agreement_hash_mismatch", "message": "Wrong deal."}, "rejected"),
])
def test_authority_pending_error_and_refusal_are_not_payment_answers(answer, status):
    async def scenario():
        s = Scenario()
        s.peer.next_filing_answer = answer
        try:
            result = await s.file()
            assert result.status == status
            assert not s.peer.entries
        finally:
            await s.client.close()
    run(scenario)


def test_record_verification_rejects_tampering_and_sequence_gaps():
    async def scenario():
        s = Scenario()
        try:
            await s.file()
            entry = s.peer.entries[0]["entry"]
            entry["actor"] = s.peer.payer
            assert (await s.adapter.read()).outcome.status == "rejected"
            entry["actor"] = s.peer.payee
            entry["sequence"] = 2
            assert (await s.adapter.read()).outcome.status == "rejected"
        finally:
            await s.client.close()
    run(scenario)
