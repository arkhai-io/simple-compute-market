from __future__ import annotations

import asyncio
from typing import Any

import pytest
from market_identity import Identity, IdentityScheme

from market_settlement_runtime import (
    ConditionOutcome,
    EffectOutcome,
    MaterializationOutcome,
    SettlementRuntime,
    SettlementSQLiteRepository,
    StatusOutcome,
)


BUYER = Identity(
    scheme=IdentityScheme.ED25519,
    identifier="ERERERERERERERERERERERERERERERERERERERERERE",
)
SELLER = Identity(
    scheme=IdentityScheme.ED25519,
    identifier="IiIiIiIiIiIiIiIiIiIiIiIiIiIiIiIiIiIiIiIiIiI",
)
EIP191_BUYER = Identity(
    scheme=IdentityScheme.EIP191,
    identifier="0x3333333333333333333333333333333333333333",
)


def obligation(
    *,
    payer: str = "buyer",
    expiration_unix: int = 100,
    payer_principal: Identity | None = None,
    claimant_principal: Identity | None = None,
) -> dict[str, Any]:
    default_payer = BUYER if payer == "buyer" else SELLER
    default_claimant = SELLER if payer == "buyer" else BUYER
    return {
        "payer": payer,
        "claimant": "seller" if payer == "buyer" else "buyer",
        "payer_principal": (
            payer_principal or default_payer
        ).model_dump(mode="json"),
        "claimant_principal": (
            claimant_principal or default_claimant
        ).model_dump(mode="json"),
        "amount": "10",
        "asset": "asset",
        "expiration_unix": expiration_unix,
        "conditions": [],
        "mechanism": "test.v1",
        "params": {},
    }


class Client:
    def __init__(self) -> None:
        self.materialize_refs: list[str] = []
        self.check_states: list[dict[str, Any]] = []
        self.materialize_error: Exception | None = None
        self.decisions = ["ready"]
        self.collect_calls = 0
        self.reclaim_calls = 0

    async def materialize(self, obligation, *, operation_ref):
        self.materialize_refs.append(operation_ref)
        if self.materialize_error is not None:
            error, self.materialize_error = self.materialize_error, None
            raise error
        return MaterializationOutcome(
            mechanism_ref=f"mechanism-{obligation['payer']}",
            status="ready",
            receipt={"created": True},
        )

    async def get_status(
        self, obligation, *, mechanism_ref, operation_ref, mechanism_state
    ):
        return StatusOutcome(
            status="ready",
            mechanism_ref=mechanism_ref,
            mechanism_state=mechanism_state,
        )

    async def check(
        self,
        obligation,
        *,
        mechanism_ref,
        fulfillment_ref,
        operation_ref,
        mechanism_state,
    ):
        self.check_states.append(dict(mechanism_state))
        decision = self.decisions.pop(0) if self.decisions else "ready"
        state = (
            {"request_marker": operation_ref}
            if decision == "pending"
            else dict(mechanism_state)
        )
        return ConditionOutcome(decision=decision, mechanism_state=state)

    async def collect(
        self,
        obligation,
        *,
        mechanism_ref,
        fulfillment_ref,
        operation_ref,
        mechanism_state,
    ):
        self.collect_calls += 1
        return EffectOutcome(
            receipt={"effect": "collected"}, mechanism_state=mechanism_state
        )

    async def reclaim_expired(
        self, obligation, *, mechanism_ref, operation_ref, mechanism_state
    ):
        self.reclaim_calls += 1
        return EffectOutcome(
            receipt={"effect": "reclaimed"}, mechanism_state=mechanism_state
        )


@pytest.fixture
def repository(tmp_path) -> SettlementSQLiteRepository:
    return SettlementSQLiteRepository(str(tmp_path / "settlement.db"))


async def register(runtime: SettlementRuntime, value: dict[str, Any]):
    return (
        await runtime.register_plan(agreement_ref="agreement-1", obligations=[value])
    )[0]


async def test_registration_rejects_role_only_identity_carriers(repository) -> None:
    runtime = SettlementRuntime(repository, {})
    role_only = obligation()
    del role_only["payer_principal"]

    with pytest.raises(ValueError, match="requires payer_principal"):
        await register(runtime, role_only)


async def test_principal_gating_and_aggregate_status(repository) -> None:
    client = Client()
    runtime = SettlementRuntime(repository, {"test.v1": client}, clock=lambda: 50)
    records = await runtime.register_plan(
        agreement_ref="mixed",
        obligations=[obligation(payer="buyer"), obligation(payer="seller")],
    )
    for record, payer, claimant, worker in (
        (records[0], BUYER, SELLER, "buyer"),
        (records[1], SELLER, BUYER, "seller"),
    ):
        await runtime.materialize(
            obligation_ref=record.obligation_ref,
            local_principal=payer,
            worker_id=worker,
        )
        await runtime.bind_fulfillment(
            record.obligation_ref,
            f"fulfillment-{worker}",
            local_principal=claimant,
        )
        await runtime.check(
            obligation_ref=record.obligation_ref,
            local_principal=claimant,
            worker_id=worker,
        )
        await runtime.collect(
            obligation_ref=record.obligation_ref,
            local_principal=claimant,
            worker_id=worker,
        )
    assert (await runtime.get_status("mixed")).status == "complete"
    with pytest.raises(PermissionError, match="payer"):
        await runtime.materialize(
            obligation_ref=records[0].obligation_ref,
            local_principal=EIP191_BUYER,
            worker_id="wrong",
        )
    with pytest.raises(TypeError, match="canonical marketplace identity"):
        await runtime.materialize(
            obligation_ref=records[0].obligation_ref,
            local_principal="buyer",  # type: ignore[arg-type]
            worker_id="legacy-role",
        )


async def test_eip191_principal_remains_opaque_to_the_mechanism(repository) -> None:
    client = Client()
    runtime = SettlementRuntime(repository, {"test.v1": client}, clock=lambda: 50)
    record = await register(
        runtime,
        obligation(payer_principal=EIP191_BUYER),
    )

    await runtime.materialize(
        obligation_ref=record.obligation_ref,
        local_principal=EIP191_BUYER,
        worker_id="eip191-payer",
    )

    stored = await repository.load_settlement_obligation(record.obligation_ref)
    assert stored is not None
    assert stored["obligation"]["payer_principal"] == {
        "scheme": "eip191",
        "identifier": "0x3333333333333333333333333333333333333333",
    }
    assert not {"address", "wallet", "private_key"}.intersection(
        stored["obligation"]
    )


async def test_uncertain_retry_reuses_operation_identity(repository) -> None:
    client = Client()
    client.materialize_error = TimeoutError("unknown acknowledgement")
    runtime = SettlementRuntime(repository, {"test.v1": client}, clock=lambda: 50)
    record = await register(runtime, obligation())
    with pytest.raises(TimeoutError):
        await runtime.materialize(
            obligation_ref=record.obligation_ref,
            local_principal=BUYER,
            worker_id="first",
        )
    operation = await repository.load_settlement_operation(
        record.obligation_ref, "materialize"
    )
    assert operation is not None
    assert operation["uncertain_acknowledgement"] is True
    await runtime.materialize(
        obligation_ref=record.obligation_ref,
        local_principal=BUYER,
        worker_id="second",
    )
    assert client.materialize_refs[0] == client.materialize_refs[1]


async def test_pending_check_round_trips_mechanism_state(repository) -> None:
    client = Client()
    client.decisions = ["pending", "ready"]
    runtime = SettlementRuntime(repository, {"test.v1": client}, clock=lambda: 50)
    record = await register(runtime, obligation())
    await runtime.materialize(
        obligation_ref=record.obligation_ref,
        local_principal=BUYER,
        worker_id="payer",
    )
    await runtime.bind_fulfillment(
        record.obligation_ref, "fulfillment", local_principal=SELLER
    )
    pending = await runtime.check(
        obligation_ref=record.obligation_ref,
        local_principal=SELLER,
        worker_id="claimant",
    )
    ready = await runtime.check(
        obligation_ref=record.obligation_ref,
        local_principal=SELLER,
        worker_id="claimant",
    )
    assert pending.status == "pending"
    assert ready.status == "succeeded"
    assert client.check_states[0] == {}
    assert "request_marker" in client.check_states[1]


async def test_adoption_binds_principal_and_request(
    repository,
) -> None:
    runtime = SettlementRuntime(repository, {})
    record = await register(runtime, obligation())
    outcome = await runtime.adopt(
        record.obligation_ref,
        local_principal=SELLER,
        mechanism_ref="escrow-1",
        receipt={"verified": True},
    )
    assert outcome.status == "succeeded"
    with pytest.raises(ValueError, match="different request"):
        await runtime.adopt(
            record.obligation_ref,
            local_principal=BUYER,
            mechanism_ref="escrow-1",
            receipt={"verified": True},
        )
    with pytest.raises(ValueError, match="different request"):
        await runtime.adopt(
            record.obligation_ref,
            local_principal=SELLER,
            mechanism_ref="different",
        )


async def test_collect_and_reclaim_share_atomic_winner(repository) -> None:
    client = Client()
    runtime = SettlementRuntime(repository, {"test.v1": client}, clock=lambda: 200)
    record = await register(runtime, obligation())
    await runtime.materialize(
        obligation_ref=record.obligation_ref,
        local_principal=BUYER,
        worker_id="payer",
    )
    await runtime.bind_fulfillment(
        record.obligation_ref, "fulfillment", local_principal=SELLER
    )
    await runtime.check(
        obligation_ref=record.obligation_ref,
        local_principal=SELLER,
        worker_id="claimant",
    )
    collect, reclaim = await asyncio.gather(
        runtime.collect(
            obligation_ref=record.obligation_ref,
            local_principal=SELLER,
            worker_id="collect",
        ),
        runtime.reclaim(
            obligation_ref=record.obligation_ref,
            local_principal=BUYER,
            worker_id="reclaim",
        ),
    )
    assert {collect.status, reclaim.status} == {"succeeded", "busy"}
    assert client.collect_calls + client.reclaim_calls == 1
