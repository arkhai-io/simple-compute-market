import base64
import json
import logging

import pytest

from market_arkhai_mediation.adapter import MediationAdapter
from market_arkhai_mediation.client import MediationClient, MediationCredential
from market_arkhai_mediation.fixtures import record_signer
from market_arkhai_mediation.fixtures.authority import MediationContractFake
from market_arkhai_mediation.models import Filing
from market_deal_lifecycle.adapters import DisputeBinding, PaymentSelector
from market_deal_lifecycle.respondent import RespondentPage
from market_deal_lifecycle.terms import DisputeAuthority
from market_deal_servicing import (
    Classification, DealWatch, EndSession, FinalRequest, PhysicalResult, RespondentPoller, SellerSession,
    ServicingCycle,
)
from market_deal_servicing.evidence import transaction
from market_deal_servicing.journal import stable_ref
from market_identity import canonical_json
from pydantic import SecretStr

#: An Alkahest deal's mechanism. Discovery reads no deal's mechanism or payment
#: account, so a page whose first deal is an Alkahest deal still discovers its
#: authority.
ALKAHEST_MECHANISM_ID = "alkahest.v1"


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
                rig["path"], authority=authority, read=adapter.respondent,
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


class ListingRespondent:
    """A respondent adapter listing no case, recording its listings in ``order``."""

    def __init__(self, binding, order, *, fail=False):
        self.binding = binding
        self.order = order
        self.fail = fail
        self.agreement_digest = "digest"

    async def respondent(self, after="", limit=100):
        self.order.append(("listing", self.binding.authority.account))
        if self.fail:
            raise ConnectionError("respondent listing unavailable")
        return RespondentPage(next_after=after, has_more=False)

    def build_answer(self, case, *, matching, items, signer):
        self.order.append(("answer", case.case_ref))


class Port:
    """The respondent port: credentials by authority account, one listing adapter per deal.

    An account in ``plain`` names an authority whose adapter offers no
    respondent discovery.
    """

    def __init__(self, *, unusable=(), failing=(), plain=()):
        self.unusable = set(unusable)
        self.failing = set(failing)
        self.plain = set(plain)
        self.order = []
        self.credential_checks = []

    @property
    def listings(self):
        return [account for kind, account in self.order if kind == "listing"]

    def credential_available(self, authority):
        self.credential_checks.append(authority.account)
        return authority.account not in self.unusable

    def dispute_adapter(self, binding):
        if binding.authority.account in self.plain:
            return object()
        return ListingRespondent(binding, self.order, fail=binding.authority.account in self.failing)


def _register(rig, negotiation_id, *, authority, mechanism="fixture.payment.v1"):
    with transaction(rig["path"]) as conn:
        end = EndSession(conn)
        end.register(end.read("deal").model_copy(update={
            "negotiation_id": negotiation_id, "commitment_ref": "commitment-" + negotiation_id,
        }))
        SellerSession(conn).register(rig["deal"].model_copy(update={
            "negotiation_id": negotiation_id, "commitment_ref": "commitment-" + negotiation_id,
            "dispute": authority, "payment": PaymentSelector(mechanism),
        }))


def _cycle(rig, port, *, recovery=(), signer=None):
    rig["physical"].apply_end.return_value = PhysicalResult(progress="tearing_down", done=False)
    return ServicingCycle(
        rig["path"], domain="fixture", loop="deal-servicing", seller=rig["service"](), end=rig["end"],
        respondents=port, signer=signer or rig["seller"], clock=lambda: rig["clock"][0],
        recovery=recovery, resolve_site_corrections=lambda *_: None,
    )


def _other(rig):
    return rig["authority"].model_copy(update={"account": "other-authority"})


async def test_discovery_runs_once_per_authority_before_any_deal_s_steps(rig, caplog):
    """The first deal on the page is an Alkahest deal; a deal with no dispute
    authority and one whose authority offers no respondent discovery are left
    out."""
    _register(rig, "a-alkahest", authority=rig["authority"], mechanism=ALKAHEST_MECHANISM_ID)
    _register(rig, "b-payments", authority=rig["authority"])
    _register(rig, "c-other", authority=_other(rig))
    _register(rig, "d-undisputed", authority=None)
    _register(rig, "e-plain", authority=rig["authority"].model_copy(update={"account": "plain-authority"}))
    port = Port(plain={"plain-authority"})

    async def recover(deal):
        port.order.append(("recovery", deal.negotiation_id))

    with caplog.at_level(logging.ERROR):
        assert await _cycle(rig, port, recovery=[("recovery", recover)]).cycle() == 6
    assert port.order == [
        ("listing", "authority"), ("listing", "other-authority"),
        *(("recovery", deal) for deal in ("a-alkahest", "b-payments", "c-other", "d-undisputed", "deal", "e-plain")),
    ]
    assert port.credential_checks == ["authority", "other-authority", "plain-authority"]
    assert [record for record in caplog.records if "respondent discovery" in record.getMessage()] == []


async def test_one_authority_s_failed_discovery_skips_neither_another_nor_any_deal(rig, caplog):
    """The failing authority's deal is first on the page."""
    _register(rig, "a-other", authority=_other(rig))
    port = Port(failing={"other-authority"})

    async def recover(deal):
        port.order.append(("recovery", deal.negotiation_id))

    with caplog.at_level(logging.ERROR):
        await _cycle(rig, port, recovery=[("recovery", recover)]).cycle()
    assert port.order == [
        ("listing", "other-authority"), ("listing", "authority"), ("recovery", "a-other"), ("recovery", "deal"),
    ]
    failures = [record.getMessage() for record in caplog.records if "respondent discovery" in record.getMessage()]
    assert failures == [
        f"fixture servicing step respondent discovery awaits recovery for authority {_other(rig).identity}",
    ]


async def test_an_unusable_credential_leaves_its_deal_out_of_discovery_and_its_steps_run(rig):
    port = Port(unusable={"authority"})
    rig["credentials"][0] = False

    async def recover(deal):
        port.order.append(("recovery", deal.negotiation_id))

    await _cycle(rig, port, recovery=[("recovery", recover)]).cycle()
    assert port.order == [("recovery", "deal")]
    page = await rig["service"]().list()
    assert page.deals[0].state == "repair_required"
    with transaction(rig["path"]) as conn:
        assert EndSession(conn).payment_observed_at("deal", "commitment") == rig["clock"][0]


async def test_a_listed_case_under_another_agreement_lands_in_the_repairs(respondent, rig, caplog):
    """The kit's resolution: the deal's adapter is bound to another Agreement
    than the one the case was filed under."""
    env = respondent

    class MismatchedPort:
        def credential_available(self, authority):
            return True

        def dispute_adapter(self, binding):
            return MediationAdapter(binding, {**env["agreement"], "nonce": "another"}, env["payee"], clock=lambda: env["now"])

    with caplog.at_level(logging.ERROR):
        await _cycle(rig, MismatchedPort(), signer=env["seller"]).cycle()
    assert [record for record in caplog.records if "respondent discovery" in record.getMessage()] == []
    repairs = await env["poller"]().repairs()
    assert len(repairs) == 2
    assert {repair["reason"] for repair in repairs} == {"respondent case differs from accepted Agreement"}
    assert [record for record in env["peer"].entries if record["entry"]["kind"] == "appended"] == []

    class MatchingPort(MismatchedPort):
        def dispute_adapter(self, binding):
            return env["adapter"]

    # Once the deal's adapter names the case's Agreement, both cases resolve and
    # their repairs clear.
    await _cycle(rig, MatchingPort(), signer=env["seller"]).cycle()
    assert await env["poller"]().repairs() == []
    assert len([record for record in env["peer"].entries if record["entry"]["kind"] == "appended"]) == 2


async def test_a_resolved_case_clears_its_repair_kept_under_an_account_derived_record(respondent):
    """A database may hold a repair under a record derived from the authority
    and a payee account, which no poller reads; resolving the case clears it."""
    env = respondent
    case = (await env["adapter"].respondent()).cases[0]
    earlier = stable_ref(env["peer"].payee, "respondent", canonical_json(env["authority"].identity).decode())
    assert earlier != env["poller"]().record
    with transaction(env["rig"]["path"]) as conn:
        conn.execute(
            "INSERT INTO servicing_respondent_repairs VALUES (?,?,?,?,?)",
            (earlier, case.case_ref, case.commitment_ref, case.model_dump_json(), "temporarily unavailable"),
        )
    assert (await env["poller"]().poll())["answered"] == 2
    with transaction(env["rig"]["path"]) as conn:
        assert conn.execute("SELECT * FROM servicing_respondent_repairs").fetchall() == []


async def test_lost_append_replays_exact_answer_after_restart_and_close(respondent):
    env = respondent
    env["peer"].lose_next_response = True
    first = await env["poller"]().poll()
    assert first["pending"] == 2 and first["cursor"] == ""
    env["peer"].decide(next(iter(env["peer"].cases)), [])
    assert (await env["poller"]().poll())["answered"] == 2
    appended = [record["entry"] for record in env["peer"].entries if record["entry"]["kind"] == "appended"]
    assert len(appended) == 2 and "concurrence" in appended[0]
