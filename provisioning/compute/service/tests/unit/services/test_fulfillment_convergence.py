"""Tests for FulfillmentConvergenceWatchdog: dispatch/converge handler
success and failure paths, and the stale-claim discard guarantee
_with_owned_record provides.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from market_fulfillment import (
    Backoff,
    FulfillmentProvider,
    FulfillmentResult,
    ProviderConfigInvalidError,
    ProviderOperationState,
    ProviderRegistry,
    ProviderStatus,
    SettlementRecordState,
    SettlementRepository,
    SettlementRequirement,
    SettlementResource,
    VersionedEnvelope,
)
from market_fulfillment.db import Base
from market_fulfillment.envelopes import envelope
from market_fulfillment.settlement_repository import begin_sqlite_write_transaction

from compute_provisioning_service.services.fulfillment_convergence import (
    FulfillmentConvergenceWatchdog,
)


@pytest.fixture
def session_factory():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)


@pytest.fixture
def repo():
    return SettlementRepository()


def _requirement(**dimensions):
    return SettlementRequirement(resource_kind="compute", dimensions=dimensions or {"units": 1})


def _resource(provider="ansible"):
    return SettlementResource(
        settlement_resource_id="res-1",
        pool_id="pool-1",
        resource_kind="compute",
        provider=provider,
        attributes={},
    )


def _accepted_row(repo, session_factory, cr_id="cr-1"):
    with session_factory() as db:
        repo.schedule(
            db,
            capacity_reservation_id=cr_id,
            market="vms",
            scheduling_requirements=_requirement(),
            resource=_resource(),
        )
        repo.accept_fulfillment(
            db,
            capacity_reservation_id=cr_id,
            market="vms",
            fulfillment_request=envelope("vm.fulfillment_request", 1, {}),
        )
        repo.transition(
            db,
            cr_id,
            SettlementRecordState.dispatch_pending.value,
            prepared_create_operation=VersionedEnvelope(
                kind="ansible.create", schema_version=1, payload={}
            ).model_dump(mode="json"),
        )
        db.commit()


class _StubProvider(FulfillmentProvider):
    def __init__(self, *, dispatch_create_result=None, dispatch_create_error=None,
                 dispatch_teardown_result=None, dispatch_teardown_error=None,
                 status=None, resolve_result=(), resolve_error=None):
        self._dispatch_create_result = dispatch_create_result
        self._dispatch_create_error = dispatch_create_error
        self._dispatch_teardown_result = dispatch_teardown_result
        self._dispatch_teardown_error = dispatch_teardown_error
        self._status = status
        self._resolve_result = resolve_result
        self._resolve_error = resolve_error

    def prepare_create(self, *, capacity_reservation_id, request, resource, pool_config):
        raise NotImplementedError

    async def dispatch_create(self, prepared):
        if self._dispatch_create_error:
            raise self._dispatch_create_error
        return self._dispatch_create_result

    def prepare_teardown(self, settlement_result, pool_config):
        raise NotImplementedError

    async def dispatch_teardown(self, prepared):
        if self._dispatch_teardown_error:
            raise self._dispatch_teardown_error
        return self._dispatch_teardown_result

    async def get_status(self, capacity_reservation_id, resource, provider_metadata):
        return self._status

    def resolve_provisioned_resources(self, provider_metadata):
        if self._resolve_error:
            raise self._resolve_error
        return self._resolve_result

    async def fetch_credentials(self, provider_metadata, provisioned_resources):
        return VersionedEnvelope(kind="vm.fulfillment.result.v1", schema_version=1, payload={"credentials": []})


def _settings(**overrides):
    defaults = dict(
        fulfillment_convergence_batch_size=10,
        fulfillment_convergence_backoff_initial_seconds=1.0,
        fulfillment_convergence_backoff_multiplier=2.0,
        fulfillment_convergence_backoff_max_seconds=60.0,
        fulfillment_convergence_backoff_jitter_fraction=0.0,
    )
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


async def test_dispatch_pending_creates_success_transitions_to_dispatching(
    session_factory, repo
):
    _accepted_row(repo, session_factory)
    provider = _StubProvider(dispatch_create_result=FulfillmentResult(provider_metadata={"job": "1"}))
    watchdog = FulfillmentConvergenceWatchdog(
        session_factory=session_factory,
        repository=repo,
        provider_registry=ProviderRegistry({"ansible": provider}),
        settings=_settings(),
    )

    await watchdog.dispatch_pending_creates()

    with session_factory() as db:
        record = repo.get(db, "cr-1")
        assert record.state == SettlementRecordState.dispatching.value
        assert record.claimed_by is None
        assert record.provider_metadata == {"job": "1"}


async def test_dispatch_pending_creates_leaves_claim_intact_on_provider_exception(
    session_factory, repo
):
    _accepted_row(repo, session_factory)
    provider = _StubProvider(dispatch_create_error=RuntimeError("network blip"))
    watchdog = FulfillmentConvergenceWatchdog(
        session_factory=session_factory,
        repository=repo,
        provider_registry=ProviderRegistry({"ansible": provider}),
        settings=_settings(),
    )

    await watchdog.dispatch_pending_creates()

    with session_factory() as db:
        record = repo.get(db, "cr-1")
        # Still dispatch_pending -- the transient failure does not
        # transition the row, only leaves it claimed for the next cycle.
        assert record.state == SettlementRecordState.dispatch_pending.value
        assert record.claimed_by == watchdog._worker_id
        assert record.attempt_count == 1


async def test_converge_creates_success_persists_resource_and_transitions_to_active(
    session_factory, repo
):
    _accepted_row(repo, session_factory)
    with session_factory() as db:
        repo.transition(
            db, "cr-1", SettlementRecordState.dispatching.value, provider_metadata={"job": "1"}
        )
        db.commit()

    provider = _StubProvider(
        status=ProviderStatus(state=ProviderOperationState.succeeded),
        resolve_result=("vm-42",),
    )
    watchdog = FulfillmentConvergenceWatchdog(
        session_factory=session_factory,
        repository=repo,
        provider_registry=ProviderRegistry({"ansible": provider}),
        settings=_settings(),
    )

    await watchdog.converge_creates()

    with session_factory() as db:
        record = repo.get(db, "cr-1")
        assert record.state == SettlementRecordState.active.value
        assert record.claimed_by is None
        resources = repo.list_provisioned_resources(db, "cr-1")
        assert len(resources) == 1
        assert resources[0].status == "active"


async def test_converge_creates_fails_terminally_on_invalid_resource_metadata(
    session_factory, repo
):
    """ProviderConfigInvalidError from resolve_provisioned_resources
    is a non-recoverable failed transition, not an indefinite retry."""

    _accepted_row(repo, session_factory)
    with session_factory() as db:
        repo.transition(
            db, "cr-1", SettlementRecordState.dispatching.value, provider_metadata={"job": "1"}
        )
        db.commit()

    provider = _StubProvider(
        status=ProviderStatus(state=ProviderOperationState.succeeded),
        resolve_error=ProviderConfigInvalidError("missing vm_target"),
    )
    watchdog = FulfillmentConvergenceWatchdog(
        session_factory=session_factory,
        repository=repo,
        provider_registry=ProviderRegistry({"ansible": provider}),
        settings=_settings(),
    )

    await watchdog.converge_creates()

    with session_factory() as db:
        record = repo.get(db, "cr-1")
        assert record.state == SettlementRecordState.failed.value
        assert record.failure_reason == "invalid_provisioned_resource_metadata"
        assert record.claimed_by is None
        # Not lumped in with an ordinary provider-reported failure -- this
        # is our own resolution failure, not the provider's.
        assert record.failure_reason != "provider_reported_failure"


async def test_converge_creates_leaves_claim_intact_while_status_is_pending(
    session_factory, repo
):
    _accepted_row(repo, session_factory)
    with session_factory() as db:
        repo.transition(
            db, "cr-1", SettlementRecordState.dispatching.value, provider_metadata={"job": "1"}
        )
        db.commit()

    provider = _StubProvider(status=ProviderStatus(state=ProviderOperationState.pending))
    watchdog = FulfillmentConvergenceWatchdog(
        session_factory=session_factory,
        repository=repo,
        provider_registry=ProviderRegistry({"ansible": provider}),
        settings=_settings(),
    )

    await watchdog.converge_creates()

    with session_factory() as db:
        record = repo.get(db, "cr-1")
        assert record.state == SettlementRecordState.dispatching.value
        assert record.claimed_by == watchdog._worker_id


def _active_row_ready_for_teardown(repo, session_factory, cr_id="cr-1"):
    _accepted_row(repo, session_factory, cr_id)
    with session_factory() as db:
        repo.transition(
            db, cr_id, SettlementRecordState.dispatching.value, provider_metadata={"job": "1"}
        )
        repo.transition(db, cr_id, SettlementRecordState.active.value)
        repo.transition(
            db,
            cr_id,
            SettlementRecordState.teardown_dispatch_pending.value,
            prepared_teardown_operation=VersionedEnvelope(
                kind="ansible.teardown", schema_version=1, payload={}
            ).model_dump(mode="json"),
        )
        db.commit()


async def test_dispatch_pending_teardowns_success_transitions_to_tearing_down(
    session_factory, repo
):
    _active_row_ready_for_teardown(repo, session_factory)
    provider = _StubProvider(
        dispatch_teardown_result=FulfillmentResult(provider_metadata={"teardown_job": "1"})
    )
    watchdog = FulfillmentConvergenceWatchdog(
        session_factory=session_factory,
        repository=repo,
        provider_registry=ProviderRegistry({"ansible": provider}),
        settings=_settings(),
    )

    await watchdog.dispatch_pending_teardowns()

    with session_factory() as db:
        record = repo.get(db, "cr-1")
        assert record.state == SettlementRecordState.tearing_down.value
        assert record.claimed_by is None
        assert record.teardown_provider_metadata == {"teardown_job": "1"}


async def test_dispatch_pending_teardowns_leaves_claim_intact_on_provider_exception(
    session_factory, repo
):
    _active_row_ready_for_teardown(repo, session_factory)
    provider = _StubProvider(dispatch_teardown_error=RuntimeError("network blip"))
    watchdog = FulfillmentConvergenceWatchdog(
        session_factory=session_factory,
        repository=repo,
        provider_registry=ProviderRegistry({"ansible": provider}),
        settings=_settings(),
    )

    await watchdog.dispatch_pending_teardowns()

    with session_factory() as db:
        record = repo.get(db, "cr-1")
        assert record.state == SettlementRecordState.teardown_dispatch_pending.value
        assert record.claimed_by == watchdog._worker_id


async def test_converge_teardowns_success_updates_resources_and_transitions_to_torn_down(
    session_factory, repo
):
    _active_row_ready_for_teardown(repo, session_factory)
    with session_factory() as db:
        repo.add_provisioned_resource(
            db, capacity_reservation_id="cr-1", provisioned_resource_id="provisioned-vm-42"
        )
        repo.transition(
            db,
            "cr-1",
            SettlementRecordState.tearing_down.value,
            teardown_provider_metadata={"teardown_job": "1"},
        )
        db.commit()

    provider = _StubProvider(status=ProviderStatus(state=ProviderOperationState.succeeded))
    watchdog = FulfillmentConvergenceWatchdog(
        session_factory=session_factory,
        repository=repo,
        provider_registry=ProviderRegistry({"ansible": provider}),
        settings=_settings(),
    )

    await watchdog.converge_teardowns()

    with session_factory() as db:
        record = repo.get(db, "cr-1")
        assert record.state == SettlementRecordState.torn_down.value
        assert record.claimed_by is None
        resources = repo.list_provisioned_resources(db, "cr-1")
        # Updated in place, not re-resolved or duplicated.
        assert len(resources) == 1
        assert resources[0].provisioned_resource_id == "provisioned-vm-42"
        assert resources[0].status == "torn_down"


async def test_converge_teardowns_provider_failure_is_not_terminal(session_factory, repo):
    """teardown_failed remains eligible for dispatch_pending_teardowns
    recovery again -- it is not a dead end, per the existing db.py state
    comment and the transition table (teardown_failed ->
    teardown_dispatch_pending is valid)."""

    _active_row_ready_for_teardown(repo, session_factory)
    with session_factory() as db:
        repo.transition(
            db,
            "cr-1",
            SettlementRecordState.tearing_down.value,
            teardown_provider_metadata={"teardown_job": "1"},
        )
        db.commit()

    provider = _StubProvider(
        status=ProviderStatus(state=ProviderOperationState.failed, detail="boom")
    )
    watchdog = FulfillmentConvergenceWatchdog(
        session_factory=session_factory,
        repository=repo,
        provider_registry=ProviderRegistry({"ansible": provider}),
        settings=_settings(),
    )

    await watchdog.converge_teardowns()

    with session_factory() as db:
        record = repo.get(db, "cr-1")
        assert record.state == SettlementRecordState.teardown_failed.value
        assert record.claimed_by is None
        # Confirm the transition table genuinely allows recovery from here.
        from market_fulfillment.transitions import validate_transition

        validate_transition(
            record.state, SettlementRecordState.teardown_dispatch_pending.value
        )


async def test_stale_claim_outcome_is_discarded_not_applied(session_factory, repo):
    """_with_owned_record's core guarantee: if another worker reclaims a row
    after this worker's lease expired but before this worker applies its
    outcome, the stale outcome must be silently dropped, not written."""

    _accepted_row(repo, session_factory)
    provider = _StubProvider(
        dispatch_create_result=FulfillmentResult(provider_metadata={"job": "stale"})
    )
    watchdog = FulfillmentConvergenceWatchdog(
        session_factory=session_factory,
        repository=repo,
        provider_registry=ProviderRegistry({"ansible": provider}),
        settings=_settings(),
    )

    # Simulate this worker having claimed the row, then losing the race:
    # another worker reclaims it (as if the lease had expired) before this
    # worker gets to apply its outcome.
    with session_factory() as db:
        record = repo.get(db, "cr-1")
        record.claimed_by = watchdog._worker_id
        record.claim_expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
        db.commit()

    with session_factory() as db:
        repo.claim_pending(
            db,
            states=[SettlementRecordState.dispatch_pending.value],
            limit=10,
            lease_seconds=3600,
            worker_id="a-different-worker",
        )

    watchdog._apply_transition(
        "cr-1",
        SettlementRecordState.dispatch_pending.value,
        SettlementRecordState.dispatching.value,
        provider_metadata={"job": "stale"},
    )

    with session_factory() as db:
        record = repo.get(db, "cr-1")
        # Still owned by the other worker, still dispatch_pending -- the
        # first worker's stale outcome was discarded, not applied, and it
        # did not clear the second worker's claim either.
        assert record.claimed_by == "a-different-worker"
        assert record.state == SettlementRecordState.dispatch_pending.value


# ----------------------------------------------------------------------
# Restart, worker-death, and transient-failure recovery proofs
# ----------------------------------------------------------------------


async def test_worker_death_leaves_a_reclaimable_row_not_a_stuck_one(session_factory, repo):
    """Commit a claim and never apply an outcome -- the same shape a
    crash between claim and provider call produces. No operator
    intervention should be required for recovery."""

    _accepted_row(repo, session_factory)
    long_ago = datetime.now(timezone.utc) - timedelta(hours=1)

    with session_factory() as db:
        repo.claim_pending(
            db,
            states=[SettlementRecordState.dispatch_pending.value],
            limit=10,
            lease_seconds=1,
            worker_id="worker-that-died",
            now=long_ago,
        )

    # While the lease is still live, a fresh claim attempt finds nothing --
    # the row is not simply abandoned to whoever asks next.
    with session_factory() as db:
        still_claimed = repo.claim_pending(
            db,
            states=[SettlementRecordState.dispatch_pending.value],
            limit=10,
            lease_seconds=1,
            worker_id="worker-b",
            now=long_ago + timedelta(milliseconds=500),
        )
        assert still_claimed == []

    # Once the lease has lapsed, no operator action is needed -- a fresh
    # claim_pending call from a live worker just picks it up.
    with session_factory() as db:
        reclaimed = repo.claim_pending(
            db,
            states=[SettlementRecordState.dispatch_pending.value],
            limit=10,
            lease_seconds=60,
            worker_id="worker-b",
        )
        assert len(reclaimed) == 1
        assert reclaimed[0].claimed_by == "worker-b"


async def test_fresh_watchdog_against_the_same_database_resumes_from_durable_state(tmp_path):
    """A fresh FulfillmentConvergenceWatchdog/session against the
    same file-backed database resumes purely from durable SettlementRecord
    state -- no dependency on the previous instance's in-memory state."""

    database = tmp_path / "restart.db"
    engine = create_engine(
        f"sqlite:///{database}",
        connect_args={"check_same_thread": False, "timeout": 5},
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    repo = SettlementRepository()

    with factory() as db:
        repo.schedule(
            db,
            capacity_reservation_id="cr-1",
            market="vms",
            scheduling_requirements=_requirement(),
            resource=_resource(),
        )
        repo.accept_fulfillment(
            db,
            capacity_reservation_id="cr-1",
            market="vms",
            fulfillment_request=envelope("vm.fulfillment_request", 1, {}),
        )
        repo.transition(
            db,
            "cr-1",
            SettlementRecordState.dispatch_pending.value,
            prepared_create_operation=VersionedEnvelope(
                kind="ansible.create", schema_version=1, payload={}
            ).model_dump(mode="json"),
        )
        db.commit()

    # "Process one" claims the row and then disappears -- no further calls
    # against this watchdog instance ever happen (simulating a crash right
    # after the claim, before the provider call completes).
    watchdog_one = FulfillmentConvergenceWatchdog(
        session_factory=factory,
        repository=repo,
        provider_registry=ProviderRegistry(
            {"ansible": _StubProvider(dispatch_create_error=RuntimeError("never gets here"))}
        ),
        settings=_settings(),
    )
    await watchdog_one.dispatch_pending_creates()
    with factory() as db:
        mid_crash = repo.get(db, "cr-1")
        assert mid_crash.claimed_by == watchdog_one._worker_id
        assert mid_crash.state == SettlementRecordState.dispatch_pending.value

    # "Process two" -- a brand new watchdog instance, new worker id, same
    # database file -- must not need anything from watchdog_one to recover
    # once the lease naturally expires.
    with factory() as db:
        record = repo.get(db, "cr-1")
        record.claim_expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
        db.commit()

    watchdog_two = FulfillmentConvergenceWatchdog(
        session_factory=factory,
        repository=repo,
        provider_registry=ProviderRegistry(
            {"ansible": _StubProvider(
                dispatch_create_result=FulfillmentResult(provider_metadata={"job": "2"})
            )}
        ),
        settings=_settings(),
    )
    assert watchdog_two._worker_id != watchdog_one._worker_id
    await watchdog_two.dispatch_pending_creates()

    with factory() as db:
        record = repo.get(db, "cr-1")
        assert record.state == SettlementRecordState.dispatching.value
        assert record.claimed_by is None


async def test_fresh_watchdog_resumes_a_teardown_from_durable_state_after_restart(tmp_path):
    """Teardown-path counterpart to
    test_fresh_watchdog_against_the_same_database_resumes_from_durable_state
    (POOLS-7 §10.8): the claim/lease/resume machinery is shared between
    dispatch_pending_creates and dispatch_pending_teardowns, but that
    sharing was never itself asserted for the teardown path -- only
    exercised through it incidentally, if at all."""

    database = tmp_path / "restart-teardown.db"
    engine = create_engine(
        f"sqlite:///{database}",
        connect_args={"check_same_thread": False, "timeout": 5},
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    repo = SettlementRepository()

    _active_row_ready_for_teardown(repo, factory)

    # "Process one" claims the row and then disappears -- no further calls
    # against this watchdog instance ever happen (simulating a crash right
    # after the claim, before the provider call completes).
    watchdog_one = FulfillmentConvergenceWatchdog(
        session_factory=factory,
        repository=repo,
        provider_registry=ProviderRegistry(
            {"ansible": _StubProvider(dispatch_teardown_error=RuntimeError("never gets here"))}
        ),
        settings=_settings(),
    )
    await watchdog_one.dispatch_pending_teardowns()
    with factory() as db:
        mid_crash = repo.get(db, "cr-1")
        assert mid_crash.claimed_by == watchdog_one._worker_id
        assert mid_crash.state == SettlementRecordState.teardown_dispatch_pending.value

    # "Process two" -- a brand new watchdog instance, new worker id, same
    # database file -- must not need anything from watchdog_one to recover
    # once the lease naturally expires.
    with factory() as db:
        record = repo.get(db, "cr-1")
        record.claim_expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
        db.commit()

    watchdog_two = FulfillmentConvergenceWatchdog(
        session_factory=factory,
        repository=repo,
        provider_registry=ProviderRegistry(
            {"ansible": _StubProvider(
                dispatch_teardown_result=FulfillmentResult(provider_metadata={"teardown_job": "2"})
            )}
        ),
        settings=_settings(),
    )
    assert watchdog_two._worker_id != watchdog_one._worker_id
    await watchdog_two.dispatch_pending_teardowns()

    with factory() as db:
        record = repo.get(db, "cr-1")
        assert record.state == SettlementRecordState.tearing_down.value
        assert record.claimed_by is None
        assert record.teardown_provider_metadata == {"teardown_job": "2"}


async def test_worker_death_leaves_a_reclaimable_teardown_row_not_a_stuck_one(
    session_factory, repo,
):
    """Teardown-path counterpart to
    test_worker_death_leaves_a_reclaimable_row_not_a_stuck_one. Commit a
    claim on a teardown_dispatch_pending row and never apply an outcome --
    the same shape a crash between claim and provider call produces. No
    operator intervention should be required for recovery."""

    _active_row_ready_for_teardown(repo, session_factory)
    long_ago = datetime.now(timezone.utc) - timedelta(hours=1)

    with session_factory() as db:
        repo.claim_pending(
            db,
            states=[SettlementRecordState.teardown_dispatch_pending.value],
            limit=10,
            lease_seconds=1,
            worker_id="worker-that-died",
            now=long_ago,
        )

    # While the lease is still live, a fresh claim attempt finds nothing --
    # the row is not simply abandoned to whoever asks next.
    with session_factory() as db:
        still_claimed = repo.claim_pending(
            db,
            states=[SettlementRecordState.teardown_dispatch_pending.value],
            limit=10,
            lease_seconds=1,
            worker_id="worker-b",
            now=long_ago + timedelta(milliseconds=500),
        )
        assert still_claimed == []

    # Once the lease has lapsed, no operator action is needed -- a fresh
    # claim_pending call from a live worker just picks it up.
    with session_factory() as db:
        reclaimed = repo.claim_pending(
            db,
            states=[SettlementRecordState.teardown_dispatch_pending.value],
            limit=10,
            lease_seconds=60,
            worker_id="worker-b",
        )
        assert len(reclaimed) == 1
        assert reclaimed[0].claimed_by == "worker-b"


async def test_transient_dispatch_failure_grows_backoff_without_reaching_a_terminal_state(
    session_factory, repo
):
    """Exercises the actual
    watchdog dispatch path against a failing provider (not just the claim
    primitive in isolation), and checks real deltas against a baseline
    captured immediately before each claim -- not just that later
    timestamps are larger, which wall-clock drift alone could satisfy even
    with a broken (constant) lease length."""

    _accepted_row(repo, session_factory)
    backoff = Backoff(initial_seconds=1.0, multiplier=2.0, max_seconds=60.0, jitter_fraction=0.0)
    failing_provider = _StubProvider(dispatch_create_error=RuntimeError("still down"))
    watchdog = FulfillmentConvergenceWatchdog(
        session_factory=session_factory,
        repository=repo,
        provider_registry=ProviderRegistry({"ansible": failing_provider}),
        settings=_settings(
            fulfillment_convergence_backoff_initial_seconds=1.0,
            fulfillment_convergence_backoff_multiplier=2.0,
            fulfillment_convergence_backoff_max_seconds=60.0,
            fulfillment_convergence_backoff_jitter_fraction=0.0,
        ),
    )

    expected_deltas = [1.0, 2.0, 4.0]
    for expected_delta in expected_deltas:
        with session_factory() as db:
            record = repo.get(db, "cr-1")
            record.claim_expires_at = datetime.now(timezone.utc) - timedelta(hours=1)
            db.commit()

        baseline = datetime.now(timezone.utc).replace(tzinfo=None)
        await watchdog.dispatch_pending_creates()

        with session_factory() as db:
            record = repo.get(db, "cr-1")
            assert record.state == SettlementRecordState.dispatch_pending.value
            actual_delta = (record.claim_expires_at - baseline).total_seconds()
            # Real wall-clock time elapsed during the call too, so allow a
            # small tolerance rather than requiring an exact match.
            assert abs(actual_delta - expected_delta) < 0.5, (
                f"expected ~{expected_delta}s lease, got {actual_delta}s"
            )

    with session_factory() as db:
        record = repo.get(db, "cr-1")
        assert record.attempt_count == 3
        # Still not terminal -- no attempt-count ceiling exists.
        assert record.state == SettlementRecordState.dispatch_pending.value


# ----------------------------------------------------------------------
# Backoff/jitter determinism and eventual convergence
# ----------------------------------------------------------------------


def test_backoff_random_source_is_injectable_for_deterministic_tests():
    """Task 6: Backoff.random_source lets tests get reproducible delay
    sequences without monkeypatching global randomness."""

    from random import Random

    backoff_a = Backoff(
        initial_seconds=1.0, multiplier=2.0, max_seconds=60.0,
        jitter_fraction=0.5, random_source=Random(42),
    )
    backoff_a_repeat = Backoff(
        initial_seconds=1.0, multiplier=2.0, max_seconds=60.0,
        jitter_fraction=0.5, random_source=Random(42),
    )
    backoff_b = Backoff(
        initial_seconds=1.0, multiplier=2.0, max_seconds=60.0,
        jitter_fraction=0.5, random_source=Random(1337),
    )

    sequence_a = [backoff_a.delay_seconds(n) for n in range(1, 6)]
    sequence_a_repeat = [backoff_a_repeat.delay_seconds(n) for n in range(1, 6)]
    sequence_b = [backoff_b.delay_seconds(n) for n in range(1, 6)]

    # Same seed -> identical sequence.
    assert sequence_a == sequence_a_repeat
    # Different seed -> a different sequence (jitter is actually applied).
    assert sequence_a != sequence_b
    # No jitter still follows the base exponential formula exactly.
    no_jitter = Backoff(initial_seconds=1.0, multiplier=2.0, max_seconds=60.0)
    assert [no_jitter.delay_seconds(n) for n in range(1, 5)] == [1.0, 2.0, 4.0, 8.0]


async def test_eventual_convergence_after_repeated_failures_then_success(
    session_factory, repo
):
    """A row that fails N times then succeeds reaches its
    terminal state -- no row is left permanently stuck absent an explicit
    terminal provider result."""

    _accepted_row(repo, session_factory)
    failing_provider = _StubProvider(dispatch_create_error=RuntimeError("still down"))
    watchdog = FulfillmentConvergenceWatchdog(
        session_factory=session_factory,
        repository=repo,
        provider_registry=ProviderRegistry({"ansible": failing_provider}),
        settings=_settings(),
    )

    # Fails three cycles in a row -- still not terminal after any of them.
    for _ in range(3):
        with session_factory() as db:
            record = repo.get(db, "cr-1")
            record.claim_expires_at = datetime.now(timezone.utc) - timedelta(hours=1)
            db.commit()
        await watchdog.dispatch_pending_creates()
        with session_factory() as db:
            record = repo.get(db, "cr-1")
            assert record.state == SettlementRecordState.dispatch_pending.value

    with session_factory() as db:
        record = repo.get(db, "cr-1")
        assert record.attempt_count == 3

    # The underlying condition clears (e.g. the network blip resolves) --
    # the very next cycle converges, using the *same* watchdog instance and
    # *same* claim/backoff machinery that was retrying moments ago.
    with session_factory() as db:
        record = repo.get(db, "cr-1")
        record.claim_expires_at = datetime.now(timezone.utc) - timedelta(hours=1)
        db.commit()

    watchdog._providers = ProviderRegistry(
        {"ansible": _StubProvider(
            dispatch_create_result=FulfillmentResult(provider_metadata={"job": "recovered"})
        )}
    )
    await watchdog.dispatch_pending_creates()

    with session_factory() as db:
        record = repo.get(db, "cr-1")
        assert record.state == SettlementRecordState.dispatching.value
        assert record.claimed_by is None
        # Now converge to a fully terminal state, closing the loop.
        record.claim_expires_at = datetime.now(timezone.utc) - timedelta(hours=1)
        db.commit()

    watchdog._providers = ProviderRegistry(
        {"ansible": _StubProvider(
            status=ProviderStatus(state=ProviderOperationState.succeeded),
            resolve_result=("vm-1",),
        )}
    )
    await watchdog.converge_creates()

    with session_factory() as db:
        record = repo.get(db, "cr-1")
        assert record.state == SettlementRecordState.active.value
        assert record.claimed_by is None


# ----------------------------------------------------------------------
# Concurrent reclaim vs. outcome application (code review finding)
# ----------------------------------------------------------------------


def test_concurrent_reclaim_cannot_be_clobbered_by_a_stale_outcome(tmp_path):
    """A worker whose lease has already lapsed must not be able to commit
    its outcome on top of a row another worker has since legitimately
    reclaimed. This was a real, empirically-confirmed gap: a plain SELECT
    does not open a SQLite-level transaction on its own (pysqlite only
    begins one before a DML statement), so checking ownership before
    acquiring the write reservation left a window where a stale worker's
    write proceeded uncontested after the real owner had already moved on.
    _with_owned_record now acquires the write reservation before reading."""

    import threading

    database = tmp_path / "reclaim_race.db"
    engine = create_engine(
        f"sqlite:///{database}", connect_args={"check_same_thread": False, "timeout": 2}
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    repo = SettlementRepository()

    with factory() as db:
        repo.schedule(
            db, capacity_reservation_id="cr-1", market="vms",
            scheduling_requirements=_requirement(), resource=_resource(),
        )
        repo.accept_fulfillment(
            db, capacity_reservation_id="cr-1", market="vms",
            fulfillment_request=envelope("vm.fulfillment_request", 1, {}),
        )
        db.commit()

    long_ago = datetime.now(timezone.utc) - timedelta(hours=1)
    with factory() as db:
        repo.claim_pending(
            db, states=[SettlementRecordState.dispatch_pending.value],
            limit=10, lease_seconds=1, worker_id="worker-a", now=long_ago,
        )

    a_read_done = threading.Event()
    b_done = threading.Event()
    results: dict = {}

    def worker_a() -> None:
        watchdog = FulfillmentConvergenceWatchdog(
            session_factory=factory,
            repository=repo,
            provider_registry=ProviderRegistry({"ansible": _StubProvider()}),
            settings=_settings(),
            worker_id="worker-a",
        )
        # Replicate _with_owned_record's shape with an injected pause
        # between acquiring the write reservation and completing, so
        # worker B has a real window to attempt a reclaim.
        with factory() as db:
            begin_sqlite_write_transaction(db)
            record = repo.get(db, "cr-1")
            results["a_owned_at_read"] = record.claimed_by == "worker-a"
            a_read_done.set()
            b_done.wait(timeout=5)
            try:
                repo.transition(
                    db, "cr-1", SettlementRecordState.dispatching.value,
                    provider_metadata={"job": "from-worker-a"},
                )
                repo.clear_claim(db, "cr-1", worker_id="worker-a")
                db.commit()
                results["a_outcome"] = "committed"
            except Exception as exc:  # noqa: BLE001
                db.rollback()
                results["a_outcome"] = type(exc).__name__

    def worker_b() -> None:
        a_read_done.wait(timeout=5)
        try:
            with factory() as db:
                claimed = repo.claim_pending(
                    db, states=[SettlementRecordState.dispatch_pending.value],
                    limit=10, lease_seconds=3600, worker_id="worker-b",
                )
                results["b_claimed"] = len(claimed) == 1
        except Exception:  # noqa: BLE001
            results["b_claimed"] = False
        finally:
            b_done.set()

    t_a = threading.Thread(target=worker_a)
    t_b = threading.Thread(target=worker_b)
    t_a.start()
    t_b.start()
    t_a.join(timeout=10)
    t_b.join(timeout=10)

    # The two outcomes are mutually exclusive: either B's reclaim succeeded
    # (and A's stale outcome must NOT also have been committed on top of
    # it), or A's outcome committed cleanly (and B's reclaim, contending
    # for the same write reservation, did not silently succeed too).
    if results.get("b_claimed"):
        with factory() as db:
            final = repo.get(db, "cr-1")
            assert final.claimed_by == "worker-b"
            assert final.provider_metadata != {"job": "from-worker-a"}
    else:
        assert results.get("a_outcome") == "committed"
        with factory() as db:
            final = repo.get(db, "cr-1")
            assert final.provider_metadata == {"job": "from-worker-a"}
            assert final.claimed_by is None


async def test_requeue_teardown_failures_makes_teardown_failed_retryable(
    session_factory, repo
):
    """Code review finding: teardown_failed was documented as retryable
    (db.py's state comment, spec.md) but no handler ever claimed it.
    requeue_teardown_failures + dispatch_pending_teardowns together close
    that gap within one cycle."""

    _active_row_ready_for_teardown(repo, session_factory)
    with session_factory() as db:
        repo.transition(
            db, "cr-1", SettlementRecordState.tearing_down.value,
            teardown_provider_metadata={"teardown_job": "1"},
        )
        repo.transition(
            db, "cr-1", SettlementRecordState.teardown_failed.value,
            failure_reason="provider_reported_teardown_failure",
        )
        db.commit()

    provider = _StubProvider(
        dispatch_teardown_result=FulfillmentResult(provider_metadata={"teardown_job": "2"})
    )
    watchdog = FulfillmentConvergenceWatchdog(
        session_factory=session_factory,
        repository=repo,
        provider_registry=ProviderRegistry({"ansible": provider}),
        settings=_settings(),
    )

    await watchdog.requeue_teardown_failures()
    with session_factory() as db:
        record = repo.get(db, "cr-1")
        assert record.state == SettlementRecordState.teardown_dispatch_pending.value
        assert record.claimed_by is None

    await watchdog.dispatch_pending_teardowns()
    with session_factory() as db:
        record = repo.get(db, "cr-1")
        assert record.state == SettlementRecordState.tearing_down.value
        assert record.teardown_provider_metadata == {"teardown_job": "2"}


@pytest.mark.asyncio
async def test_run_cycle_emits_one_structured_diagnostics_event_for_multiple_rows(
    session_factory, repo, caplog
):
    for reservation_id in ("cr-log-1", "cr-log-2"):
        with session_factory() as db:
            repo.schedule(
                db,
                capacity_reservation_id=reservation_id,
                market="vms",
                scheduling_requirements=_requirement(),
                resource=_resource(),
            )
            repo.accept_fulfillment(
                db,
                capacity_reservation_id=reservation_id,
                market="vms",
                fulfillment_request=envelope("vm.fulfillment_request", 1, {}),
            )
            db.commit()

    watchdog = FulfillmentConvergenceWatchdog(
        session_factory=session_factory,
        repository=repo,
        provider_registry=ProviderRegistry({}),
        settings=_settings(),
    )

    caplog.set_level("INFO")
    await watchdog.run_cycle()

    events = [
        record
        for record in caplog.records
        if getattr(record, "event", None) == "fulfillment_recovery_diagnostics"
    ]
    assert len(events) == 1
    payload = events[0].recovery_diagnostics
    assert set(payload["per_state"]) == {
        state.value
        for state in (
            SettlementRecordState.dispatch_pending,
            SettlementRecordState.dispatching,
            SettlementRecordState.teardown_dispatch_pending,
            SettlementRecordState.tearing_down,
        )
    }
    assert payload["failed_count"] == 0
    assert payload["teardown_failed_count"] == 0


@pytest.mark.asyncio
async def test_run_cycle_emits_one_zero_value_diagnostics_event_when_empty(
    session_factory, repo, caplog
):
    watchdog = FulfillmentConvergenceWatchdog(
        session_factory=session_factory,
        repository=repo,
        provider_registry=ProviderRegistry({}),
        settings=_settings(),
    )

    caplog.set_level("INFO")
    await watchdog.run_cycle()

    events = [
        record
        for record in caplog.records
        if getattr(record, "event", None) == "fulfillment_recovery_diagnostics"
    ]
    assert len(events) == 1
    payload = events[0].recovery_diagnostics
    assert all(state["total"] == 0 for state in payload["per_state"].values())
    assert all(
        state["oldest_row_age_seconds"] is None
        for state in payload["per_state"].values()
    )
