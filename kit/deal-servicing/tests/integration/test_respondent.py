import base64
import json

import pytest

from market_arkhai_mediation.adapter import MediationAdapter
from market_arkhai_mediation.client import MediationClient, MediationCredential
from market_arkhai_mediation.fixtures import record_signer
from market_arkhai_mediation.fixtures.authority import MediationContractFake
from market_arkhai_mediation.models import Filing
from market_deal_lifecycle.adapters import DisputeBinding
from market_deal_lifecycle.terms import DisputeAuthority
from market_deal_servicing import Classification, DealWatch, EndSession, FinalRequest, RespondentPoller
from market_deal_servicing.evidence import transaction
from pydantic import SecretStr


@pytest.fixture
async def respondent(rig):
    peer = MediationContractFake()
    authority = DisputeAuthority.model_validate(peer.authority)
    seller = record_signer()
    fixture = peer.data["filing"]["request"]
    agreement = {**fixture["agreement"], "seller": seller.identity.model_dump(mode="json")}
    binding = DisputeBinding("deal", fixture["transaction"], authority)
    now = peer._clock
    with transaction(rig["path"]) as conn:
        deal = rig["deal"].model_copy(update={"dispute": authority, "commitment_ref": binding.commitment_ref})
        conn.execute("UPDATE servicing_seller_deals SET deal=? WHERE negotiation_id='deal'", (deal.model_dump_json(),))
        end = EndSession(conn)
        record = end.read("deal").model_copy(update={
            "seller": seller.identity, "commitment_ref": binding.commitment_ref,
            "start_at": now - 100, "term_end": now + 1000, "committed_at": now - 100,
            "available_at": now - 50,
        })
        conn.execute("UPDATE servicing_delivery SET record=? WHERE negotiation_id='deal'", (record.model_dump_json(),))
        end.record_end(FinalRequest(
            negotiation_id="deal", source_ref="surrender", actor=rig["buyer"].identity,
            ended_at=now, observed_at=now, cause="buyer_surrender", source="end_delivery",
        ), now=now, classification=Classification(kind="buyer_surrender", evidence_refs=["surrender"]))
    # Public deterministic contract-fake credentials; never use on a public network.
    async with MediationClient(
        authority, MediationCredential(authority.identity, token=SecretStr("fixture-payer")),
        transport=peer.transport(),
    ) as payer, MediationClient(
        authority, MediationCredential(authority.identity, token=SecretStr("fixture-payee")),
        transport=peer.transport(),
    ) as payee:
        adapter = MediationAdapter(binding, agreement, payee, clock=lambda: now)
        for key, ended_at in (("match", now), ("contest", now - 1)):
            await payer.file(Filing.model_validate({
                "transaction": binding.commitment_ref, "agreement": agreement,
                "request": {"kind": "delivery_end", "ended_at": ended_at, "delivered": True, "cause": "payer"},
                "claim": "End delivery.", "items": [],
            }), idempotency_key=key)

        def poller(resolve=lambda _: ("deal", adapter)):
            return RespondentPoller(
                rig["path"], authority=authority, account=peer.payee, read=adapter.respondent,
                resolve=resolve, signer=seller, clock=lambda: now,
            )
        yield locals()


@pytest.mark.parametrize("unresolved", ["missing", "mismatch"])
async def test_unresolvable_case_does_not_block_later_cases_and_is_repairable(respondent, unresolved):
    env = respondent
    first = next(iter(env["peer"].cases))

    def resolve(case):
        if case.case_ref == first:
            if unresolved == "mismatch":
                raise ValueError("Agreement digest mismatch")
            return None
        return "deal", env["adapter"]

    poller = env["poller"](resolve)
    result = await poller.poll()
    assert result["answered"] == 1 and result["skipped"] == 1 and result["pending"] == 0
    assert result["cursor"]
    repairs = await poller.repairs()
    assert len(repairs) == 1 and repairs[0]["case"].case_ref == first
    # Rebuilding discovery cannot strand the skipped case behind the cursor.
    repaired = env["poller"]()
    assert (await repaired.poll())["answered"] == 1
    assert await repaired.repairs() == []


async def test_watch_before_respondent_cannot_preempt_signed_concurrence(respondent, rig):
    env = respondent
    watch = DealWatch(
        rig["path"], negotiation_id="deal", commitment_ref=env["binding"].commitment_ref,
        payment=None, dispute=env["adapter"], dispute_binding=env["binding"],
        seller_account=env["peer"].payee, actor=lambda _: rig["seller"].identity, clock=lambda: env["now"],
    )
    await watch.poll()
    with transaction(rig["path"]) as conn:
        assert not [intent for intent in EndSession(conn).intents("deal") if intent.kind == "append"]
    assert (await env["poller"]().poll())["answered"] == 2
    appended = [record["entry"] for record in env["peer"].entries if record["entry"]["kind"] == "appended"]
    assert len(appended) == 2
    assert "concurrence" in appended[0] and "concurrence" not in appended[1]
    exported = appended[1]["items"][-1]["bytes"]
    assert json.loads(base64.urlsafe_b64decode(exported + "=" * (-len(exported) % 4)))["kind"] == "respondent_contest"


async def test_respondent_contests_a_surrender_superseded_by_an_earlier_seller_end(respondent, rig):
    env = respondent
    with transaction(rig["path"]) as conn:
        end = EndSession(conn)
        earlier = FinalRequest(
            negotiation_id="deal", source_ref="operator:earlier", actor=env["seller"].identity,
            ended_at=env["now"] - 10, observed_at=env["now"], cause="operator_end",
            source="administrator", evidence_refs=["operator:earlier"],
        )
        end.record_end(
            earlier, now=env["now"],
            classification=Classification(kind="unentitled_withdrawal", evidence_refs=earlier.evidence_refs),
            filing_intent=end.failure_filing(earlier, now=env["now"], delivered=True),
        )
    assert (await env["poller"]().poll())["answered"] == 2
    appended = [r["entry"] for r in env["peer"].entries if r["entry"]["kind"] == "appended"]
    assert len(appended) == 2 and all("concurrence" not in entry for entry in appended)
    exported = appended[0]["items"][-1]["bytes"]
    contest = json.loads(base64.urlsafe_b64decode(exported + "=" * (-len(exported) % 4)))
    assert "operator:earlier" in base64.b64decode(contest["body"]).decode()


async def test_lost_append_replays_exact_answer_after_restart_and_close(respondent):
    env = respondent
    env["peer"].lose_next_response = True
    first = await env["poller"]().poll()
    assert first["pending"] == 2 and first["cursor"] == ""
    env["peer"].decide(next(iter(env["peer"].cases)), [])
    assert (await env["poller"]().poll())["answered"] == 2
    appended = [record["entry"] for record in env["peer"].entries if record["entry"]["kind"] == "appended"]
    assert len(appended) == 2 and "concurrence" in appended[0]
