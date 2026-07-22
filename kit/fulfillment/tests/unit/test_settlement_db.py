"""Schema-level tests for the settlement/fulfillment aggregate mappings."""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from market_fulfillment.db import Base, ProvisionedResource, SettlementRecord, SettlementRecordState


@pytest.fixture
def session_factory():
    engine = create_engine("sqlite:///:memory:")

    @event.listens_for(engine, "connect")
    def _enable_foreign_keys(dbapi_connection, _):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)


def test_settlement_record_defaults_to_assigned(session_factory):
    with session_factory() as db:
        record = SettlementRecord(
            capacity_reservation_id="cr-1",
            market="vms",
            scheduling_requirements={"resource_kind": "compute.gpu", "dimensions": {"gpu_count": 1}},
        )
        db.add(record)
        db.commit()

        fetched = db.get(SettlementRecord, "cr-1")
        assert fetched.state == SettlementRecordState.assigned.value
        assert fetched.fulfillment_id is None
        assert fetched.provider_metadata == {}
        assert fetched.attempt_count == 0


def test_fulfillment_id_uniqueness_is_enforced(session_factory):
    with session_factory() as db:
        db.add(SettlementRecord(
            capacity_reservation_id="cr-1",
            market="vms",
            scheduling_requirements={},
            fulfillment_id="dupe",
        ))
        db.commit()

    with session_factory() as db:
        db.add(SettlementRecord(
            capacity_reservation_id="cr-2",
            market="vms",
            scheduling_requirements={},
            fulfillment_id="dupe",
        ))
        with pytest.raises(IntegrityError):
            db.commit()


def test_provisioned_resource_requires_owning_settlement_record(session_factory):
    with session_factory() as db:
        db.add(ProvisionedResource(
            capacity_reservation_id="does-not-exist",
            fulfillment_id="f-1",
        ))
        with pytest.raises(IntegrityError):
            db.commit()


def test_provisioned_resources_cascade_delete_with_settlement_record(session_factory):
    with session_factory() as db:
        record = SettlementRecord(
            capacity_reservation_id="cr-1",
            market="vms",
            scheduling_requirements={},
            fulfillment_id="f-1",
        )
        db.add(record)
        db.flush()
        db.add(ProvisionedResource(capacity_reservation_id="cr-1", fulfillment_id="f-1"))
        db.commit()

    with session_factory() as db:
        db.delete(db.get(SettlementRecord, "cr-1"))
        db.commit()

    with session_factory() as db:
        remaining = (
            db.query(ProvisionedResource)
            .filter(ProvisionedResource.capacity_reservation_id == "cr-1")
            .all()
        )
        assert remaining == []


def test_provisioned_resource_id_is_generated(session_factory):
    with session_factory() as db:
        record = SettlementRecord(
            capacity_reservation_id="cr-1", market="vms", scheduling_requirements={}, fulfillment_id="f-1"
        )
        db.add(record)
        db.flush()
        provisioned = ProvisionedResource(capacity_reservation_id="cr-1", fulfillment_id="f-1")
        db.add(provisioned)
        db.commit()
        assert provisioned.provisioned_resource_id
