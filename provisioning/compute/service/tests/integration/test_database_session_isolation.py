"""Request and worker sessions own independent database transactions."""

from datetime import datetime, timezone

from sqlalchemy import select

from compute_provisioning_service.db.models import ProvisioningReplayReservation

from .conftest import ADMIN_SIGNER


def test_closing_a_reader_cannot_erase_another_sessions_replay_reservation(
    session_factory,
) -> None:
    principal = ADMIN_SIGNER.identity
    key = (principal.scheme.value, principal.identifier, "isolated-request")
    with session_factory() as writer:
        writer.add(
            ProvisioningReplayReservation(
                principal_scheme=key[0],
                principal_identifier=key[1],
                request_id=key[2],
                request_hash="isolated-request-hash",
                dispatch_lease_expires_at=datetime(2030, 1, 1, tzinfo=timezone.utc),
            )
        )
        writer.flush()
        # Closing the reader rolls back its own transaction while the writer's
        # reservation is still pending. A shared connection would lose the write.
        with session_factory() as reader:
            observed = reader.scalar(select(ProvisioningReplayReservation.request_hash))
        writer.commit()

    with session_factory() as reader:
        committed = reader.get(ProvisioningReplayReservation, key)
        assert committed is not None
        assert committed.request_hash == "isolated-request-hash"
    assert observed is None
