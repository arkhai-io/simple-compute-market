from __future__ import annotations

import asyncio
import json
from typing import Any

import pytest
from market_identity import Identity, IdentityScheme

from market_settlement_runtime import (
    MANUAL_REASON_KEY,
    ConditionOutcome,
    EffectOutcome,
    MaterializationOutcome,
    SettlementManualRequired,
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
        "payer_principal": (payer_principal or default_payer).model_dump(mode="json"),
        "claimant_principal": (claimant_principal or default_claimant).model_dump(
            mode="json"
        ),
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
        self.materialize_obligations: list[dict[str, Any]] = []
        self.check_states: list[dict[str, Any]] = []
        self.materialize_error: Exception | None = None
        self.decisions = ["ready"]
        self.collect_calls = 0
        self.reclaim_calls = 0
        self.reclaim_options: list[dict | None] = []

    async def materialize(self, obligation, *, operation_ref):
        self.materialize_obligations.append(obligation)
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
        self,
        obligation,
        *,
        mechanism_ref,
        operation_ref,
        mechanism_state,
        mechanism_options=None,
    ):
        self.reclaim_calls += 1
        self.reclaim_options.append(mechanism_options)
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


async def test_status_operation_is_shared_by_both_authorized_participants(
    repository,
) -> None:
    client = Client()
    runtime = SettlementRuntime(repository, {"test.v1": client}, clock=lambda: 50)
    record = await register(runtime, obligation())
    await runtime.materialize(
        obligation_ref=record.obligation_ref,
        local_principal=BUYER,
        worker_id="buyer-materialize",
    )

    payer_status = await runtime.reconcile_status(
        obligation_ref=record.obligation_ref,
        local_principal=BUYER,
        worker_id="payer-status",
    )
    claimant_status = await runtime.reconcile_status(
        obligation_ref=record.obligation_ref,
        local_principal=SELLER,
        worker_id="claimant-status",
    )

    assert payer_status.status == "pending"
    assert claimant_status.status == "pending"


async def test_transient_buyer_action_is_returned_but_only_metadata_is_stored(
    repository,
) -> None:
    class ActionClient(Client):
        async def materialize(self, obligation, *, operation_ref):
            del obligation, operation_ref
            return MaterializationOutcome(
                mechanism_ref="mechanism-action",
                status="requires_action",
                receipt={"state": "awaiting_payment"},
                buyer_action={
                    "kind": "bank_instructions",
                    "expires_at_unix": 999,
                    "url": "https://checkout.example/private",
                    "bank_instructions": {"reference": "provider-secret"},
                },
            )

    runtime = SettlementRuntime(
        repository,
        {"test.v1": ActionClient()},
        clock=lambda: 50,
    )
    record = await register(runtime, obligation())

    outcome = await runtime.materialize(
        obligation_ref=record.obligation_ref,
        local_principal=BUYER,
        worker_id="action",
    )
    stored = await repository.load_settlement_obligation(record.obligation_ref)

    assert outcome.action == {
        "kind": "bank_instructions",
        "expires_at_unix": 999,
        "url": "https://checkout.example/private",
        "bank_instructions": {"reference": "provider-secret"},
    }
    assert stored is not None
    assert stored["buyer_action"] == {
        "kind": "bank_instructions",
        "expires_at_unix": 999,
    }


async def test_post_collection_monitoring_preserves_collection_on_late_loss(
    repository,
) -> None:
    class MonitoringClient(Client):
        status_value = "collected"

        async def collect(
            self,
            obligation,
            *,
            mechanism_ref,
            fulfillment_ref,
            operation_ref,
            mechanism_state,
        ):
            result = await super().collect(
                obligation,
                mechanism_ref=mechanism_ref,
                fulfillment_ref=fulfillment_ref,
                operation_ref=operation_ref,
                mechanism_state=mechanism_state,
            )
            return result.model_copy(
                update={"mechanism_state": {"terminal_risk_monitoring": True}}
            )

        async def get_status(
            self, obligation, *, mechanism_ref, operation_ref, mechanism_state
        ):
            del obligation, operation_ref, mechanism_state
            return StatusOutcome(
                status=self.status_value,
                mechanism_ref=mechanism_ref,
                mechanism_state={"terminal_risk_monitoring": True},
                receipt={"funding_reason": "late_return"}
                if self.status_value == "failed"
                else {"funding_reason": "settled"},
            )

    client = MonitoringClient()
    runtime = SettlementRuntime(
        repository,
        {"test.v1": client},
        clock=lambda: 50,
    )
    record = await register(runtime, obligation())
    await runtime.materialize(
        obligation_ref=record.obligation_ref,
        local_principal=BUYER,
        worker_id="materialize",
    )
    await runtime.bind_fulfillment(
        record.obligation_ref,
        "fulfillment-1",
        local_principal=SELLER,
    )
    await runtime.check(
        obligation_ref=record.obligation_ref,
        local_principal=SELLER,
        worker_id="check",
    )
    await runtime.collect(
        obligation_ref=record.obligation_ref,
        local_principal=SELLER,
        worker_id="collect",
    )
    await runtime.reconcile_status(
        obligation_ref=record.obligation_ref,
        local_principal=SELLER,
        worker_id="monitor-collected",
    )

    due = await repository.list_due_settlement_obligations(now_unix=50)
    assert [row["obligation_ref"] for row in due] == [record.obligation_ref]

    client.status_value = "failed"
    await runtime.reconcile_status(
        obligation_ref=record.obligation_ref,
        local_principal=SELLER,
        worker_id="monitor-loss",
    )
    stored = await repository.load_settlement_obligation(record.obligation_ref)

    assert stored is not None
    assert stored["collection_state"] == "succeeded"
    assert stored["mechanism_status"] == "failed"
    assert stored["status_receipt"]["funding_reason"] == "late_return"


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
    assert not {"address", "wallet", "private_key"}.intersection(stored["obligation"])


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


async def test_returned_funding_reclaim_waits_for_vm_cleanup(repository) -> None:
    client = Client()
    runtime = SettlementRuntime(repository, {"test.v1": client}, clock=lambda: 200)
    record = await register(runtime, obligation())
    materialized = await runtime.materialize(
        obligation_ref=record.obligation_ref,
        local_principal=BUYER,
        worker_id="payer",
    )
    assert materialized.status == "succeeded"
    fulfilled = await runtime.bind_fulfillment(
        record.obligation_ref,
        "portable-fulfillment-ref",
        local_principal=SELLER,
    )
    returned = fulfilled.model_copy(update={"mechanism_status": "failed"})
    assert await repository.save_settlement_obligation(
        returned.model_dump(),
        expected_version=returned.version,
    )
    with pytest.raises(ValueError, match="cleanup must complete"):
        await runtime.reclaim(
            obligation_ref=record.obligation_ref,
            local_principal=BUYER,
            worker_id="payer-before-cleanup",
        )
    assert client.reclaim_calls == 0

    reserved = await runtime.reserve_cleanup(
        record.obligation_ref,
        local_principal=SELLER,
        worker_id="seller-cleanup",
    )
    assert reserved.status == "pending"
    await runtime.complete_cleanup(
        record.obligation_ref,
        local_principal=SELLER,
        worker_id="seller-cleanup",
    )
    reclaimed = await runtime.reclaim(
        obligation_ref=record.obligation_ref,
        local_principal=BUYER,
        worker_id="payer-after-cleanup",
    )

    assert reclaimed.status == "succeeded"
    assert client.reclaim_calls == 1


async def test_completed_collection_replay_does_not_repeat_transfer(repository) -> None:
    client = Client()
    runtime = SettlementRuntime(repository, {"test.v1": client}, clock=lambda: 200)
    record = await register(runtime, obligation())
    await runtime.materialize(
        obligation_ref=record.obligation_ref,
        local_principal=BUYER,
        worker_id="payer",
    )
    await runtime.bind_fulfillment(
        record.obligation_ref,
        "fulfillment",
        local_principal=SELLER,
    )
    await runtime.check(
        obligation_ref=record.obligation_ref,
        local_principal=SELLER,
        worker_id="claimant",
    )

    first = await runtime.collect(
        obligation_ref=record.obligation_ref,
        local_principal=SELLER,
        worker_id="collector-a",
    )
    replayed = await runtime.collect(
        obligation_ref=record.obligation_ref,
        local_principal=SELLER,
        worker_id="collector-b",
    )

    assert first.status == replayed.status == "succeeded"
    assert client.collect_calls == 1


async def test_fulfillment_lease_excludes_duplicate_vm_provisioning(repository) -> None:
    runtime = SettlementRuntime(repository, {}, clock=lambda: 50)
    record = await register(runtime, obligation())

    first = await runtime.reserve_fulfillment(
        record.obligation_ref,
        local_principal=SELLER,
        worker_id="vm-a",
    )
    duplicate = await runtime.reserve_fulfillment(
        record.obligation_ref,
        local_principal=SELLER,
        worker_id="vm-b",
    )
    assert first.status == "pending"
    assert duplicate.status == "busy"
    await runtime.defer_fulfillment(
        record.obligation_ref,
        local_principal=SELLER,
        worker_id="vm-a",
    )
    resumed = await runtime.reserve_fulfillment(
        record.obligation_ref,
        local_principal=SELLER,
        worker_id="vm-b",
    )
    assert resumed.status == "pending"

    completed = await runtime.complete_fulfillment(
        record.obligation_ref,
        "portable-fulfillment-ref",
        local_principal=SELLER,
        worker_id="vm-b",
    )
    replayed = await runtime.reserve_fulfillment(
        record.obligation_ref,
        local_principal=SELLER,
        worker_id="vm-c",
    )

    assert completed.fulfillment_ref == "portable-fulfillment-ref"
    assert replayed.status == "succeeded"


async def test_fulfillment_restart_repairs_commit_before_acknowledgement(
    repository,
) -> None:
    now = [50.0]
    runtime = SettlementRuntime(
        repository,
        {},
        clock=lambda: now[0],
        lease_seconds=10,
    )
    record = await register(runtime, obligation())
    reserved = await runtime.reserve_fulfillment(
        record.obligation_ref,
        local_principal=SELLER,
        worker_id="vm-crashed",
    )
    assert reserved.status == "pending"
    await runtime.bind_fulfillment(
        record.obligation_ref,
        "portable-fulfillment-ref",
        local_principal=SELLER,
    )

    now[0] = 61.0
    recovered = await runtime.reserve_fulfillment(
        record.obligation_ref,
        local_principal=SELLER,
        worker_id="vm-recovery",
    )
    operation = await repository.load_settlement_operation(
        record.obligation_ref,
        "fulfill",
    )

    assert recovered.status == "succeeded"
    assert operation is not None
    assert operation["state"] == "succeeded"
    assert operation["receipt"] == {"fulfillment_ref": "portable-fulfillment-ref"}


async def test_mechanism_params_bind_after_acceptance_without_changing_identity(
    repository,
) -> None:
    client = Client()
    runtime = SettlementRuntime(repository, {"test.v1": client}, clock=lambda: 50)
    record = await register(runtime, obligation())
    accepted_ref = record.obligation_ref
    accepted_hash = record.obligation_hash
    params = {
        "funding_profile": "card.v1",
        "funding_authorization_ref": "funding-authorization-1",
    }

    bound = await runtime.bind_mechanism_params(
        record.obligation_ref,
        params,
        local_principal=BUYER,
    )
    retried = await runtime.bind_mechanism_params(
        record.obligation_ref,
        params,
        local_principal=BUYER,
    )
    with pytest.raises(ValueError, match="immutable"):
        await runtime.bind_mechanism_params(
            record.obligation_ref,
            {**params, "funding_authorization_ref": "changed"},
            local_principal=BUYER,
        )

    assert bound.obligation_ref == retried.obligation_ref == accepted_ref
    assert bound.obligation_hash == retried.obligation_hash == accepted_hash
    assert "funding_authorization_ref" not in bound.obligation["params"]
    await runtime.materialize(
        obligation_ref=record.obligation_ref,
        local_principal=BUYER,
        worker_id="materialize",
    )
    assert client.materialize_obligations == [
        {
            **record.obligation,
            "params": {
                **record.obligation["params"],
                **params,
            },
        }
    ]


async def test_mechanism_params_require_exact_payer_and_pre_materialization_binding(
    repository,
) -> None:
    client = Client()
    runtime = SettlementRuntime(repository, {"test.v1": client}, clock=lambda: 50)
    record = await register(runtime, obligation())
    with pytest.raises(PermissionError, match="payer"):
        await runtime.bind_mechanism_params(
            record.obligation_ref,
            {"authorization": "ref"},
            local_principal=SELLER,
        )
    await runtime.materialize(
        obligation_ref=record.obligation_ref,
        local_principal=BUYER,
        worker_id="materialize",
    )
    with pytest.raises(ValueError, match="after materialization starts"):
        await runtime.bind_mechanism_params(
            record.obligation_ref,
            {"authorization": "ref"},
            local_principal=BUYER,
        )


async def test_fulfillment_lease_outlives_a_domain_provisioning_attempt(
    repository,
) -> None:
    """A slow domain fulfillment must not be handed to a second worker.

    Every other operation is a bounded call to the authority, so they share the
    short lease. Fulfillment provisions real capacity: at the default 30s a VM
    attempt lost its lease mid-flight and a second worker re-provisioned behind
    it, racing the first for the same reservation.
    """

    clock = {"now": 50.0}
    runtime = SettlementRuntime(
        repository,
        {},
        clock=lambda: clock["now"],
        lease_seconds=30.0,
        fulfillment_lease_seconds=3600.0,
    )
    record = await register(runtime, obligation())

    assert (
        await runtime.reserve_fulfillment(
            record.obligation_ref,
            local_principal=SELLER,
            worker_id="vm-a",
        )
    ).status == "pending"

    clock["now"] += 120.0
    taken_over = await runtime.reserve_fulfillment(
        record.obligation_ref,
        local_principal=SELLER,
        worker_id="vm-b",
    )

    assert taken_over.status == "busy"


async def test_a_parked_obligation_keeps_its_reason_across_later_status_polls(
    repository,
) -> None:
    """A park that loses its reason is a park nobody can repair.

    The reason is written once, by the operation that parked the deal. Every
    later status poll writes a fresh mechanism state, and a buyer polls
    continuously, so a reason that is not carried forward survives for about
    one poll interval and is then gone for good.
    """

    class ParkingClient(Client):
        async def collect(self, obligation, **kwargs):
            raise SettlementManualRequired(
                "hosted settlement collection rejected: authority_refused_409",
                code="authority_refused_409",
            )

        async def get_status(
            self, obligation, *, mechanism_ref, operation_ref, mechanism_state
        ):
            # What a real adapter returns: the state it derives from the
            # authority's current answer, not the state it was handed. The
            # hosted adapter builds exactly this and never merges.
            return StatusOutcome(
                status="ready",
                mechanism_ref=mechanism_ref,
                mechanism_state={"financial_state": "funded"},
            )

    client = ParkingClient()
    runtime = SettlementRuntime(repository, {"test.v1": client}, clock=lambda: 50)
    record = await register(runtime, obligation())
    await runtime.materialize(
        obligation_ref=record.obligation_ref,
        local_principal=BUYER,
        worker_id="worker",
    )
    await runtime.bind_fulfillment(
        record.obligation_ref, "fulfillment-1", local_principal=SELLER
    )
    await runtime.check(
        obligation_ref=record.obligation_ref,
        local_principal=SELLER,
        worker_id="worker",
    )
    await runtime.collect(
        obligation_ref=record.obligation_ref,
        local_principal=SELLER,
        worker_id="worker",
    )

    parked = await repository.load_settlement_obligation(record.obligation_ref)
    assert parked["collection_state"] == "manual_required"
    assert parked["mechanism_state"].get(MANUAL_REASON_KEY) == "authority_refused_409"

    # The buyer polls. The authority is answering normally now — the refusal was
    # of the collection, not of the status — so this poll names no reason.
    await runtime.reconcile_status(
        obligation_ref=record.obligation_ref,
        local_principal=BUYER,
        worker_id="worker",
    )

    after = await repository.load_settlement_obligation(record.obligation_ref)
    assert after["collection_state"] == "manual_required", "still parked"
    assert after["mechanism_state"].get(MANUAL_REASON_KEY) == "authority_refused_409"


async def test_a_newer_parking_reason_replaces_the_one_being_carried(
    repository,
) -> None:
    """The reason a mechanism names describes a park it knows about."""

    class ParkingClient(Client):
        async def collect(self, obligation, **kwargs):
            raise SettlementManualRequired("collect refused", code="first_reason")

        async def get_status(
            self, obligation, *, mechanism_ref, operation_ref, mechanism_state
        ):
            return StatusOutcome(
                status="ready",
                mechanism_ref=mechanism_ref,
                mechanism_state={MANUAL_REASON_KEY: "second_reason"},
            )

    runtime = SettlementRuntime(repository, {"test.v1": ParkingClient()}, clock=lambda: 50)
    record = await register(runtime, obligation())
    await runtime.materialize(
        obligation_ref=record.obligation_ref, local_principal=BUYER, worker_id="w"
    )
    await runtime.bind_fulfillment(
        record.obligation_ref, "fulfillment-1", local_principal=SELLER
    )
    await runtime.check(
        obligation_ref=record.obligation_ref, local_principal=SELLER, worker_id="w"
    )
    await runtime.collect(
        obligation_ref=record.obligation_ref, local_principal=SELLER, worker_id="w"
    )
    await runtime.reconcile_status(
        obligation_ref=record.obligation_ref, local_principal=BUYER, worker_id="w"
    )

    after = await repository.load_settlement_obligation(record.obligation_ref)
    assert after["mechanism_state"][MANUAL_REASON_KEY] == "second_reason"


async def test_an_obligation_that_was_never_parked_carries_no_reason(
    repository,
) -> None:
    """Nothing is manufactured: only a recorded reason is preserved."""

    class PlainClient(Client):
        async def get_status(
            self, obligation, *, mechanism_ref, operation_ref, mechanism_state
        ):
            return StatusOutcome(
                status="ready",
                mechanism_ref=mechanism_ref,
                mechanism_state={"financial_state": "funded"},
            )

    runtime = SettlementRuntime(repository, {"test.v1": PlainClient()}, clock=lambda: 50)
    record = await register(runtime, obligation())
    await runtime.materialize(
        obligation_ref=record.obligation_ref, local_principal=BUYER, worker_id="w"
    )
    await runtime.reconcile_status(
        obligation_ref=record.obligation_ref, local_principal=BUYER, worker_id="w"
    )

    after = await repository.load_settlement_obligation(record.obligation_ref)
    assert after["collection_state"] != "manual_required"
    assert MANUAL_REASON_KEY not in after["mechanism_state"]


async def test_reclaim_options_reach_the_mechanism_unread(repository) -> None:
    """The runtime is the wrong place to know what an option means.

    It relays the payer's mapping to the mechanism that gave the keys meaning
    and keeps none of it, so the durable row a later worker reads names no
    option and no projection can leak one.
    """

    client = Client()
    runtime = SettlementRuntime(repository, {"test.v1": client}, clock=lambda: 200)
    record = await register(runtime, obligation())
    await runtime.materialize(
        obligation_ref=record.obligation_ref,
        local_principal=BUYER,
        worker_id="payer",
    )

    outcome = await runtime.reclaim(
        obligation_ref=record.obligation_ref,
        local_principal=BUYER,
        worker_id="payer-reclaim",
        mechanism_options={"return_instructions_email": "payer@example.test"},
    )

    assert outcome.status == "succeeded"
    assert client.reclaim_options == [
        {"return_instructions_email": "payer@example.test"}
    ]

    stored = await repository.load_settlement_obligation(record.obligation_ref)
    operation = await repository.load_settlement_operation(
        record.obligation_ref, "reclaim"
    )
    assert "payer@example.test" not in json.dumps(stored)
    assert "payer@example.test" not in json.dumps(operation)


async def test_a_reclaim_naming_different_options_is_refused(repository) -> None:
    """Two reclaims naming different options are two different requests.

    Reusing the first reservation for the second would send the mechanism an
    address its caller never asked for, so the reservation binds what it was
    given and the second is refused here rather than at the provider.
    """

    client = Client()
    runtime = SettlementRuntime(repository, {"test.v1": client}, clock=lambda: 200)
    record = await register(runtime, obligation())
    await runtime.materialize(
        obligation_ref=record.obligation_ref,
        local_principal=BUYER,
        worker_id="payer",
    )
    await runtime.reclaim(
        obligation_ref=record.obligation_ref,
        local_principal=BUYER,
        worker_id="payer-reclaim",
        mechanism_options={"return_instructions_email": "first@example.test"},
    )

    with pytest.raises(ValueError, match="different request"):
        await runtime.reclaim(
            obligation_ref=record.obligation_ref,
            local_principal=BUYER,
            worker_id="payer-reclaim",
            mechanism_options={"return_instructions_email": "second@example.test"},
        )

    assert client.reclaim_calls == 1


async def test_repeating_a_reclaim_with_the_same_options_replays(repository) -> None:
    """A retry the payer resends unchanged is the same request, not a new one."""

    client = Client()
    runtime = SettlementRuntime(repository, {"test.v1": client}, clock=lambda: 200)
    record = await register(runtime, obligation())
    await runtime.materialize(
        obligation_ref=record.obligation_ref,
        local_principal=BUYER,
        worker_id="payer",
    )
    options = {"return_instructions_email": "payer@example.test"}
    first = await runtime.reclaim(
        obligation_ref=record.obligation_ref,
        local_principal=BUYER,
        worker_id="payer-reclaim",
        mechanism_options=options,
    )

    second = await runtime.reclaim(
        obligation_ref=record.obligation_ref,
        local_principal=BUYER,
        worker_id="payer-reclaim",
        mechanism_options=dict(options),
    )

    assert (first.status, second.status) == ("succeeded", "succeeded")
    assert client.reclaim_calls == 1


async def test_a_reclaim_without_options_is_unchanged(repository) -> None:
    """A mechanism that needs no caller input sees exactly what it saw before."""

    client = Client()
    runtime = SettlementRuntime(repository, {"test.v1": client}, clock=lambda: 200)
    record = await register(runtime, obligation())
    await runtime.materialize(
        obligation_ref=record.obligation_ref,
        local_principal=BUYER,
        worker_id="payer",
    )

    outcome = await runtime.reclaim(
        obligation_ref=record.obligation_ref,
        local_principal=BUYER,
        worker_id="payer-reclaim",
    )

    assert outcome.status == "succeeded"
    assert client.reclaim_options == [{}]
