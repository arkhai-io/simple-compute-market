from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from market_site.db import Base, CapacityReservationDebit
from market_site.ledger import CapacityLedgerService


def _ledger(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path/'ledger.db'}")
    Base.metadata.create_all(engine)
    return CapacityLedgerService(session_factory=sessionmaker(bind=engine)), engine


def test_assignment_moves_existing_capacity_without_double_counting(tmp_path):
    ledger, engine = _ledger(tmp_path)
    ledger.register_resource(resource_id="a", total_units=4)
    ledger.register_resource(resource_id="b", total_units=4)
    reserved = ledger.reserve(claim={"units": 4}, deal_ref={})

    ledger.assign_settlement_resource(
        capacity_reservation_id=reserved["capacity_reservation_id"],
        settlement_resource_id="b",
    )

    by_id = {row["resource_id"]: row for row in ledger.snapshot()}
    assert by_id["a"]["available_units"] == 4
    assert by_id["b"]["available_units"] == 0
    with sessionmaker(bind=engine)() as db:
        debit = db.get(CapacityReservationDebit, reserved["capacity_reservation_id"])
        assert debit is not None


def test_assignment_rejects_destination_without_capacity(tmp_path):
    ledger, _ = _ledger(tmp_path)
    ledger.register_resource(resource_id="a", total_units=4)
    ledger.register_resource(resource_id="b", total_units=2)
    reserved = ledger.reserve(claim={"units": 4}, deal_ref={})

    import pytest
    from market_site.ledger import CapacityConflictError

    with pytest.raises(CapacityConflictError):
        ledger.assign_settlement_resource(
            capacity_reservation_id=reserved["capacity_reservation_id"],
            settlement_resource_id="b",
        )


def test_settlement_resource_id_set_without_reassignment(tmp_path):
    ledger, _ = _ledger(tmp_path)
    ledger.register_resource(resource_id="a", total_units=4)
    reserved = ledger.reserve(claim={"units": 1}, deal_ref={})
    result = ledger.assign_settlement_resource(
        capacity_reservation_id=reserved["capacity_reservation_id"],
        settlement_resource_id="a",
    )
    assert "resource_id" not in result
    assert result["settlement_resource_id"] == "a"
