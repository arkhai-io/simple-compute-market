from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from compute_provisioning_service.db.models import Base, CapacityReleaseCallbackOutbox
from compute_provisioning_service.services.deal_event_sink import (
    SqlAlchemyCapacityReleaseOutbox,
)


def test_failure_survives_restart_then_ack_is_terminal_and_duplicate_safe():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    first_process = SqlAlchemyCapacityReleaseOutbox(factory)
    first_process.reserve("reservation-1")
    first_process.record_failure("reservation-1", "signed acknowledgement failed")

    restarted = SqlAlchemyCapacityReleaseOutbox(factory)
    assert restarted.pending() == ("reservation-1",)
    restarted.mark_delivered("reservation-1")
    restarted.reserve("reservation-1")

    assert restarted.pending() == ()
    with factory() as session:
        row = session.get(CapacityReleaseCallbackOutbox, "reservation-1")
        assert row.attempt_count == 2
        assert row.delivered_at is not None
        assert row.last_error is None
