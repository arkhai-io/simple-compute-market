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


def test_assign_settlement_resource_in_session_shares_caller_transaction(tmp_path):
    """A caller can fold the rebind into its own open session and commit once."""
    ledger, engine = _ledger(tmp_path)
    ledger.register_resource(resource_id="a", total_units=4)
    ledger.register_resource(resource_id="b", total_units=4)
    reserved = ledger.reserve(claim={"units": 4}, deal_ref={})

    session_factory = sessionmaker(bind=engine)
    with session_factory() as db:
        result = ledger.assign_settlement_resource_in_session(
            db,
            capacity_reservation_id=reserved["capacity_reservation_id"],
            settlement_resource_id="b",
        )
        assert result["settlement_resource_id"] == "b"
        # Not yet committed: a session-scoped core leaves the transaction
        # boundary to the caller.
        db.commit()

    by_id = {row["resource_id"]: row for row in ledger.snapshot()}
    assert by_id["a"]["available_units"] == 4
    assert by_id["b"]["available_units"] == 0


def test_assign_settlement_resource_in_session_rolls_back_with_caller(tmp_path):
    """A caller's rollback undoes the rebind, proving no implicit commit happens."""
    ledger, engine = _ledger(tmp_path)
    ledger.register_resource(resource_id="a", total_units=4)
    ledger.register_resource(resource_id="b", total_units=4)
    reserved = ledger.reserve(claim={"units": 4}, deal_ref={})

    session_factory = sessionmaker(bind=engine)
    with session_factory() as db:
        ledger.assign_settlement_resource_in_session(
            db,
            capacity_reservation_id=reserved["capacity_reservation_id"],
            settlement_resource_id="b",
        )
        db.rollback()

    by_id = {row["resource_id"]: row for row in ledger.snapshot()}
    assert by_id["a"]["available_units"] == 0
    assert by_id["b"]["available_units"] == 4


def test_lock_reservation_returns_row_for_update(tmp_path):
    ledger, engine = _ledger(tmp_path)
    ledger.register_resource(resource_id="a", total_units=1)
    reserved = ledger.reserve(claim={"units": 1}, deal_ref={})

    session_factory = sessionmaker(bind=engine)
    with session_factory() as db:
        row = ledger.lock_reservation(db, reserved["capacity_reservation_id"])
        assert row is not None
        assert row.capacity_reservation_id == reserved["capacity_reservation_id"]


def test_lock_reservation_missing_returns_none(tmp_path):
    ledger, engine = _ledger(tmp_path)
    session_factory = sessionmaker(bind=engine)
    with session_factory() as db:
        assert ledger.lock_reservation(db, "does-not-exist") is None


def test_backing_resource_id_in_session_matches_public_lookup(tmp_path):
    ledger, engine = _ledger(tmp_path)
    ledger.register_resource(resource_id="a", total_units=1)
    reserved = ledger.reserve(claim={"units": 1}, deal_ref={})

    session_factory = sessionmaker(bind=engine)
    with session_factory() as db:
        in_session = ledger.backing_resource_id_in_session(
            db, reserved["capacity_reservation_id"]
        )
    assert in_session == "a"
    assert in_session == ledger.get_reservation_backing_resource_id(
        reserved["capacity_reservation_id"]
    )
