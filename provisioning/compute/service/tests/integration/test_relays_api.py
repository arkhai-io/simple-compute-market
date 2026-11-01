"""Relay administration over the real API, through the canonical client.

Level 2, per `docs/development/TESTING.md`: the real in-process application, a
real database, and the client production code actually uses. Not a helper built
inside the test — a private wrapper and the shipped client drift independently,
and the test stays green while they do.

What this covers that the library tests cannot: that the binding, its routes,
its status codes, and the client's serialization agree. The relay service
behind them, the holdings read included, is covered by the family kit's
`tests/integration/test_relay_administration.py`.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from httpx import ASGITransport

from compute_provisioning.relays import RelayPortLease
from compute_provisioning_client import (
    ComputeProvisioningAuthenticationError,
    ComputeProvisioningClient,
    ComputeProvisioningError,
)
from compute_provisioning_contracts import RelayCreate, RelayTokenRotate, RelayUpdate

from compute_provisioning_service import container as _container_module
from compute_provisioning_service.main import app
from .conftest import ADMIN_SIGNER, SERVICE_AUTHORITIES, STOREFRONT_SIGNER

pytestmark = pytest.mark.anyio


def _client(transport):
    """The operator's client: relay administration is the administrator's alone."""
    return ComputeProvisioningClient(
        "http://testserver",
        signer=ADMIN_SIGNER,
        caller_role="admin",
        expected_authorities=SERVICE_AUTHORITIES,
        transport=transport,
    )


def _relay(**overrides) -> RelayCreate:
    fields = {
        "id": "site-a",
        "relay_addr": "203.0.113.9",
        "relay_port": 7000,
        "vm_port_range_start": 6100,
        "vm_port_range_count": 100,
    }
    fields.update(overrides)
    return RelayCreate(**fields)


@pytest.fixture
async def relays(client_and_queue):
    """A client over the real app. `client_and_queue` builds the application
    and its container; this borrows that setup rather than rebuilding it."""
    async with _client(ASGITransport(app=app)) as client:
        yield client


class TestRelayAdministrationOverTheApi:
    async def test_a_relay_is_created_and_read_back(self, relays):
        created = await relays.create_relay(_relay(label="Site A"))
        assert created.id == "site-a"

        fetched = await relays.get_relay("site-a")
        assert (fetched.relay_addr, fetched.relay_port) == ("203.0.113.9", 7000)
        assert fetched.vm_port_range_count == 100
        assert fetched.enabled is True

    async def test_a_relay_appears_in_the_listing(self, relays):
        await relays.create_relay(_relay())
        listing = await relays.list_relays()
        assert [r.id for r in listing.relays] == ["site-a"]

    async def test_no_response_carries_a_token(self, relays):
        """Asserted across create, get, list, and rotate, because each is a
        separate serialization."""
        await relays.create_relay(_relay(token="admission-token"))
        rotated = await relays.rotate_relay_token(
            "site-a", RelayTokenRotate(token="rotated-token")
        )
        listing = await relays.list_relays()
        fetched = await relays.get_relay("site-a")

        for response in (rotated, fetched, *listing.relays):
            dumped = response.model_dump_json()
            assert "admission-token" not in dumped
            assert "rotated-token" not in dumped
            assert response.token_configured is True

    async def test_a_relay_without_a_token_says_so(self, relays):
        created = await relays.create_relay(_relay())
        assert created.token_configured is False

    async def test_a_relay_is_updated_in_place(self, relays):
        await relays.create_relay(_relay(label="original"))
        updated = await relays.update_relay(
            "site-a", RelayUpdate(vm_port_range_count=50)
        )
        assert updated.vm_port_range_count == 50
        assert updated.label == "original"

    async def test_a_relay_is_disabled_and_enabled(self, relays):
        await relays.create_relay(_relay())
        assert (await relays.set_relay_enabled("site-a", False)).enabled is False
        assert (await relays.set_relay_enabled("site-a", True)).enabled is True

    async def test_a_duplicate_rendezvous_is_refused(self, relays):
        await relays.create_relay(_relay(id="first"))
        with pytest.raises(ComputeProvisioningError):
            await relays.create_relay(_relay(id="second"))

    async def test_an_unknown_relay_is_not_found(self, relays):
        with pytest.raises(ComputeProvisioningError):
            await relays.get_relay("never-created")

    async def test_an_unusable_window_is_refused(self, relays):
        with pytest.raises(ComputeProvisioningError):
            await relays.create_relay(_relay(vm_port_range_count=0))


class TestHoldingsOverTheApi:
    """The administrator reads what a relay holds; nobody else may."""

    def _lease(self, port: int, owner_id: str, *, released: bool = False) -> None:
        with _container_module.resolved_session_factory() as db, db.begin():
            db.add(
                RelayPortLease(
                    id=f"lease-{owner_id}",
                    relay_id="site-a",
                    remote_port=port,
                    host_id="kvm1",
                    pool_id="gpu-pool",
                    owner_kind="fulfillment",
                    owner_id=owner_id,
                    released_at=datetime.now(timezone.utc) if released else None,
                )
            )

    async def test_held_and_released_leases_are_read_by_port(self, relays):
        await relays.create_relay(_relay())
        self._lease(6101, "cr-held")
        self._lease(6100, "cr-done", released=True)

        holdings = await relays.list_relay_leases("site-a")

        assert holdings.relay_id == "site-a"
        assert [(lease.remote_port, lease.owner_id) for lease in holdings.leases] == [
            (6100, "cr-done"),
            (6101, "cr-held"),
        ]
        assert holdings.leases[0].released_at is not None
        assert holdings.leases[1].released_at is None
        assert (holdings.leases[1].host_id, holdings.leases[1].pool_id) == ("kvm1", "gpu-pool")

    async def test_an_unknown_relay_has_no_holdings(self, relays):
        with pytest.raises(ComputeProvisioningError) as refused:
            await relays.list_relay_leases("never-created")
        assert refused.value.status_code == 404

    async def test_a_seller_may_not_read_holdings(self, relays):
        """The route admits only the administrator, so the canonical client
        refuses to sign it as the seller."""
        await relays.create_relay(_relay())
        async with ComputeProvisioningClient(
            "http://testserver",
            signer=STOREFRONT_SIGNER,
            caller_role="seller",
            expected_authorities=SERVICE_AUTHORITIES,
            transport=ASGITransport(app=app),
        ) as seller:
            with pytest.raises(
                ComputeProvisioningAuthenticationError, match="permits caller roles"
            ) as refused:
                await seller.list_relay_leases("site-a")
            assert refused.value.status_code is None


class TestRebindingOverTheApi:
    """A relay carrying tunnels cannot move, and the refusal says what to do.

    The rule itself is asserted at the service level. What this adds is that it
    survives the controller: an operator hitting it gets a rejection rather
    than a 500 from a constraint, and the message names what is holding the
    relay open.
    """

    def _lease_on(self, relay_id: str, *, port: int = 6100, host: str = "kvm1"):
        session_factory = _container_module.resolved_session_factory
        with session_factory() as db, db.begin():
            db.add(
                RelayPortLease(
                    id=f"lease-{relay_id}",
                    relay_id=relay_id,
                    remote_port=port,
                    host_id=host,
                    pool_id="gpu-pool",
                    owner_kind="fulfillment",
                    owner_id=f"cr-{relay_id}",
                )
            )

    def _release_all(self):
        session_factory = _container_module.resolved_session_factory
        with session_factory() as db, db.begin():
            for lease in db.query(RelayPortLease).all():
                lease.released_at = datetime.now(timezone.utc)

    async def test_a_carrying_relay_cannot_be_repointed(self, relays):
        await relays.create_relay(_relay())
        self._lease_on("site-a")

        with pytest.raises(ComputeProvisioningError) as excinfo:
            await relays.update_relay(
                "site-a", RelayUpdate(relay_addr="203.0.113.20")
            )

        message = str(excinfo.value)
        assert "kvm1:6100" in message
        assert "Disable the pool" in message

    async def test_the_same_relay_moves_once_drained(self, relays):
        await relays.create_relay(_relay())
        self._lease_on("site-a")
        self._release_all()

        moved = await relays.update_relay(
            "site-a", RelayUpdate(relay_addr="203.0.113.20")
        )

        assert moved.relay_addr == "203.0.113.20"

    async def test_a_carrying_relay_still_accepts_unrelated_edits(self, relays):
        """Only the endpoint is protected. A window change touches nothing a
        buyer holds, so refusing it would be an obstacle without a reason."""
        await relays.create_relay(_relay())
        self._lease_on("site-a")

        updated = await relays.update_relay(
            "site-a", RelayUpdate(label="renamed", vm_port_range_count=50)
        )

        assert updated.label == "renamed"
        assert updated.vm_port_range_count == 50

    async def test_a_carrying_relay_can_still_be_disabled(self, relays):
        """Disabling is how an operator drains toward a rebinding, so it must
        not be blocked by the rule the drain exists to satisfy."""
        await relays.create_relay(_relay())
        self._lease_on("site-a")

        assert (await relays.set_relay_enabled("site-a", False)).enabled is False

    async def test_a_carrying_relay_refuses_a_token_rotation_with_the_drain_hint(
        self, relays
    ):
        """Rotation joins the drain rule; its refusal reaches the operator as a
        conflict naming what holds the relay, not as a server error."""
        await relays.create_relay(_relay(token="admission-token"))
        self._lease_on("site-a")

        with pytest.raises(ComputeProvisioningError) as excinfo:
            await relays.rotate_relay_token("site-a", RelayTokenRotate(token="rotated"))

        assert excinfo.value.status_code == 409
        assert "kvm1:6100" in str(excinfo.value)

