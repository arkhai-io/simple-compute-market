from __future__ import annotations

import asyncio

from market_identity import Identity, IdentityScheme

from market_settlement_runtime import (
    FailurePolicy,
    FulfillmentOutcome,
    PreparedSettlement,
    SettlementJobCoordinator,
    SettlementRuntime,
    SettlementSQLiteRepository,
)

BUYER = Identity(
    scheme=IdentityScheme.ED25519,
    identifier="ERERERERERERERERERERERERERERERERERERERERERE",
)
SELLER = Identity(
    scheme=IdentityScheme.ED25519,
    identifier="IiIiIiIiIiIiIiIiIiIiIiIiIiIiIiIiIiIiIiIiIiI",
)


def obligation(*, payer: str = "buyer") -> dict:
    return {
        "payer": payer,
        "claimant": "seller" if payer == "buyer" else "buyer",
        "payer_principal": (
            BUYER if payer == "buyer" else SELLER
        ).model_dump(mode="json"),
        "claimant_principal": (
            SELLER if payer == "buyer" else BUYER
        ).model_dump(mode="json"),
        "mechanism": "test.v1",
        "expiration_unix": 100,
    }


async def test_existing_job_still_registers_and_adopts_exact_seller_funded_obligation(
    tmp_path,
) -> None:
    repository = SettlementSQLiteRepository(str(tmp_path / "jobs.db"))
    runtime = SettlementRuntime(repository, {})
    prepared = PreparedSettlement(
        agreement_ref="agreement",
        obligations=(obligation(), obligation(payer="seller")),
        selected_obligation_index=1,
        local_principal=SELLER,
        mechanism_ref="escrow-bond",
        mechanism_receipt={"verified": True},
        fulfillment_input=None,
    )
    calls: list[str] = []

    async def prepare(**kwargs):
        calls.append("prepare")
        return prepared

    async def reserve(value, escrow_uid, negotiation_id):
        calls.append("reserve")
        aggregate = await runtime.get_status("agreement")
        assert aggregate.obligations[1].mechanism_ref == "escrow-bond"
        return {"escrow_uid": escrow_uid, "status": "ready"}

    async def forbidden(*args, **kwargs):
        raise AssertionError("existing job must not be fulfilled again")

    coordinator = SettlementJobCoordinator(
        runtime,
        prepare=prepare,
        reserve_start=reserve,
        fulfill=forbidden,
        persist_outcome=forbidden,
        wake_servicing=forbidden,
    )
    result = await coordinator.start(
        escrow_uid="escrow-bond",
        negotiation_id="agreement",
        mechanism_client=None,
        chain_name="chain",
    )
    assert result == {"escrow_uid": "escrow-bond", "status": "ready"}
    assert calls == ["prepare", "reserve"]


async def test_new_job_binds_then_persists_and_wakes(tmp_path) -> None:
    repository = SettlementSQLiteRepository(str(tmp_path / "new-job.db"))
    runtime = SettlementRuntime(repository, {})
    prepared = PreparedSettlement(
        agreement_ref="agreement",
        obligations=(obligation(),),
        selected_obligation_index=0,
        local_principal=SELLER,
        mechanism_ref="escrow",
        mechanism_receipt=None,
        fulfillment_input={"private": "input"},
    )
    persisted: list[FulfillmentOutcome] = []
    woken: list[str] = []
    complete = asyncio.Event()

    async def prepare(**kwargs):
        return prepared

    async def reserve(value, escrow_uid, negotiation_id):
        return None

    async def fulfill(value, *, mechanism_client):
        return FulfillmentOutcome(
            status="fulfilled",
            fulfillment_ref="fulfillment",
            public_result={"status": "ready"},
            private_result={"credential": "private"},
        )

    async def persist(value, outcome):
        persisted.append(outcome)

    async def wake(obligation_ref):
        woken.append(obligation_ref)
        complete.set()

    coordinator = SettlementJobCoordinator(
        runtime,
        prepare=prepare,
        reserve_start=reserve,
        fulfill=fulfill,
        persist_outcome=persist,
        wake_servicing=wake,
    )
    started = await coordinator.start(
        escrow_uid="escrow",
        negotiation_id="agreement",
        mechanism_client=object(),
        chain_name="chain",
    )
    await asyncio.wait_for(complete.wait(), timeout=1)
    assert started["status"] == "provisioning"
    assert persisted[0].private_result == {"credential": "private"}
    assert len(woken) == 1
    stored = await repository.load_settlement_obligation(woken[0])
    assert stored is not None
    assert stored["fulfillment_ref"] == "fulfillment"


async def test_failure_policy_preserves_order_duplicates_and_isolation() -> None:
    original = {"deal": "one"}
    seen: list[str] = []

    async def success(store, context):
        seen.append("success")
        context["mutated"] = True
        return {"status": "released", "detail": store}

    async def boom(store, context):
        seen.append("boom")
        raise RuntimeError("broken")

    policy = FailurePolicy(
        lambda: [" success ", "", "missing", "boom", "success"],
        {"success": success, "boom": boom},
    )
    result = await policy.apply("store", original)
    assert policy.configured_actions() == (
        "success",
        "missing",
        "boom",
        "success",
    )
    assert seen == ["success", "boom", "success"]
    assert result.context == {"deal": "one"}
    assert original == {"deal": "one"}
    assert [item["action"] for item in result.actions] == [
        "success",
        "missing",
        "boom",
        "success",
    ]
    assert result.actions[0]["status"] == "released"
    assert result.actions[1]["status"] == "failed"
    assert result.actions[2]["error"] == "broken"
