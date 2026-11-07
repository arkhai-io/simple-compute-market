"""Library integration tests for fulfillment job handles in real ledger transactions."""

from unittest.mock import MagicMock

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from market_fulfillment.fulfillment_persistence import SqlAlchemyFulfillmentTransaction
from market_fulfillment.settlement_repository import begin_sqlite_write_transaction
from market_resource_pools import ResourcePoolService
from market_resource_pools.db import Base as PoolsBase
from market_resource_pools_contracts import PoolCreate
from market_site.db import Base as SiteBase, CapacityReservation
from market_site.ledger import CapacityLedgerService


@pytest.fixture
def ledger_services(tmp_path):

    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    PoolsBase.metadata.create_all(bind=engine)
    SiteBase.metadata.create_all(bind=engine)
    factory = sessionmaker(bind=engine)
    ledger = CapacityLedgerService(
        factory, unit_claim_keys=("units", "gpu_count"), mirror_dimension="gpu_count"
    )

    class _Handler:
        provider = "ansible"

        def validate_config(self, config):
            return dict(config)

        def validate_config_problems(self, config):
            return dict(config), ()

        def read_config(self, db, pool_id):
            return {}

        def read_config_for_execution(self, db, pool_id):
            return {}

        def replace_config(self, db, pool_id, config):
            pass

    pools = ResourcePoolService(factory, {"ansible": _Handler()})
    # Declared, because admission refuses a claim whose offering mode no
    # matching pool delivers -- the reservation this test attaches to has to
    # be one the ledger would really have created.
    pools.create_pool(PoolCreate(
        id="pool-a",
        label="pool-a",
        provider="ansible",
        enabled=True,
        policy_tags={"advertisable_modes": ["vm"], "capacity_backing": "backed", "deliverable_modes": ["vm"]},
        provider_config={},
    ))
    return ledger, factory


def _reserved(ledger):
    ledger.register_resource(
        resource_id="resource-1",
        resource_type="compute.gpu",
        total_units=4,
        pool_id="pool-a",
    )
    reservation = ledger.reserve(
        claim={"offering_mode": "vm", "gpu_count": 1},
        deal_ref={"escrow_uid": "0xabc"},
    )
    assert reservation is not None
    return reservation["capacity_reservation_id"]


def test_attach_executor_job_lands_on_the_reservation(ledger_services):
    """The job handle is readable from the ledger after the caller commits.

    Reads the value back off the ledger rather than trusting the call: the
    ledger is a duck-typed collaborator, so a test that only checks a call
    happened cannot tell that the method called is one the ledger has.

    The session is real because the write goes through it. A ``MagicMock``
    here would absorb the write silently and this assertion would fail, which
    is the correct signal: with the write inside the caller's transaction,
    there is no such thing as exercising it without a session.
    """
    ledger, factory = ledger_services
    capacity_reservation_id = _reserved(ledger)

    with factory() as db:
        tx = SqlAlchemyFulfillmentTransaction(
            db, MagicMock(), MagicMock(), ledger
        )

        tx.attach_executor_job(capacity_reservation_id, "ansible-job-7")

        db.commit()

    reservation = ledger.get_reservation(capacity_reservation_id)
    assert reservation["create_job_id"] == "ansible-job-7"






@pytest.fixture
def contended_ledger_services(tmp_path):
    """Like ``ledger_services``, but able to reproduce writer-slot contention.

    File-backed so each session gets its own connection, and a 1s busy
    timeout so a self-deadlock fails this test in about a second instead of
    the 30s the provisioning service is configured for.
    """

    engine = create_engine(
        f"sqlite:///{tmp_path / 'ledger.db'}",
        connect_args={"check_same_thread": False, "timeout": 1},
    )
    PoolsBase.metadata.create_all(bind=engine)
    SiteBase.metadata.create_all(bind=engine)
    factory = sessionmaker(bind=engine)
    ledger = CapacityLedgerService(factory, unit_claim_keys=("units", "gpu_count"), mirror_dimension="gpu_count")

    class _Handler:
        provider = "ansible"

        def validate_config(self, config):
            return dict(config)

        def validate_config_problems(self, config):
            return dict(config), ()

        def read_config(self, db, pool_id):
            return {}

        def read_config_for_execution(self, db, pool_id):
            return {}

        def replace_config(self, db, pool_id, config):
            pass

    pools = ResourcePoolService(factory, {"ansible": _Handler()})
    pools.create_pool(PoolCreate(
        id="pool-a",
        label="pool-a",
        provider="ansible",
        enabled=True,
        policy_tags={"advertisable_modes": ["vm"], "capacity_backing": "backed", "deliverable_modes": ["vm"]},
        provider_config={},
    ))
    return ledger, factory


def test_attach_executor_job_lands_while_the_caller_holds_the_writer_slot(
    contended_ledger_services,
):
    """The handle must land from inside the acknowledging transaction.

    `begin_fulfillment` attaches the job handle in the same transaction as
    `acknowledge_create`, by design, so that a reservation never references a
    create the settlement row does not also record. This asserts the write
    actually survives that placement rather than being swallowed -- reading
    the value back off the ledger, because the failure mode here logs a
    warning and returns normally.
    """
    ledger, factory = contended_ledger_services
    capacity_reservation_id = _reserved(ledger)

    with factory() as db:
        # What acknowledge_create's flush leaves behind: this session owns
        # SQLite's writer slot for the rest of the block.
        begin_sqlite_write_transaction(db)
        tx = SqlAlchemyFulfillmentTransaction(
            db, MagicMock(), MagicMock(), ledger
        )

        tx.attach_executor_job(capacity_reservation_id, "ansible-job-7")

        db.commit()

    reservation = ledger.get_reservation(capacity_reservation_id)
    assert reservation["create_job_id"] == "ansible-job-7"


def test_attach_executor_job_does_not_commit_the_callers_transaction(
    contended_ledger_services,
):
    """The ledger write joins the caller's transaction, it does not escape it.

    If the handle were still written through a session of the ledger's own it
    would commit independently, and a caller that rolled back would leave a
    reservation pointing at a create no settlement row records -- the exact
    inconsistency same-transaction placement exists to prevent.
    """

    ledger, factory = contended_ledger_services
    capacity_reservation_id = _reserved(ledger)

    with factory() as db:
        begin_sqlite_write_transaction(db)
        tx = SqlAlchemyFulfillmentTransaction(
            db, MagicMock(), MagicMock(), ledger
        )
        tx.attach_executor_job(capacity_reservation_id, "ansible-job-7")

        # Visible here, or the write never happened and the assertion after
        # the rollback would hold for the wrong reason.
        pending = db.get(CapacityReservation, capacity_reservation_id)
        assert pending.create_job_id == "ansible-job-7"

        db.rollback()

    reservation = ledger.get_reservation(capacity_reservation_id)
    assert reservation["create_job_id"] is None
