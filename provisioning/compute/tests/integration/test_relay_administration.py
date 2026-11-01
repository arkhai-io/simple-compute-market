"""A relay is an administered resource, and its credentials are not readable.

Three properties are pinned here:

* A relay's rendezvous, window, token, and grant keys are stated once, on a row
  that pools reference. Held per pool, two pools sharing a relay could allocate
  from one listening namespace under disagreeing windows.
* No read path that serves a response, an export, or a reconciliation
  comparison yields an admission token or a private grant key. Only an
  explicitly named execution read yields the token.
* A grant key belongs to one relay: it is supplied from the secrets profile or
  generated, staged and activated, and never shared or reused.

That reconciling a relay definition document follows a change to the document,
not a process start, is the service importer's, and its suite tests it. How a
domain's pool configuration reads and writes its relay reference is that
domain's, and its suite tests it.

External boundary: SQLAlchemy against file-backed SQLite, over a schema built
from the family's own models. The database is deterministic and does no network
I/O, so the real engine is used rather than a mock.
"""

from __future__ import annotations

import base64
import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from pydantic import BaseModel, ConfigDict
import yaml
from cryptography.exceptions import InvalidSignature
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import serialization
from market_resource_pools import ResourcePool
from sqlalchemy.orm import Session

from compute_provisioning.hosts import ConnectionCodecs, ConnectionEnvelope
from compute_provisioning.hosts.db import Host
from compute_provisioning.hosts.service import PoolChangeRefusedError
from compute_provisioning.relays import (
    GrantKey,
    ManagementRouteRefused,
    PoolRelay,
    Relay,
    RelayDefinitionError,
    RelayEndpointConflictError,
    RelayExecutionResolver,
    RelayGrantKeyNotStagedError,
    RelayNotFoundError,
    RelayPortAllocator,
    RelayPortLease,
    RelayRebindingRefused,
    RelayService,
    RelayUnusableAtExecutionError,
    RelayValidationError,
    import_relay_definitions,
    parse_relay_definitions,
    relay_host_pool_change_hooks,
)

# A development-only Fernet key. Generated for this fixture, never used on any
# network, and safe to read here precisely because it protects nothing.
_KEY = Fernet.generate_key().decode()
# A development-only grant key, generated per run and never used on a network.
_GRANT_KEY = GrantKey.generate()


@pytest.fixture
def settings():
    return SimpleNamespace(
        ssh_decryption_key=_KEY,
        relay_token="bootstrap-token",
        relay_grant_key=_GRANT_KEY.profile_form() + "\n",
    )


class _AddressCodec:
    """A connection kind whose address is its one public field."""

    kind = "fake"
    version = 1

    def build(self, public, secrets, *, previous=None):
        return ConnectionEnvelope(kind=self.kind, version=self.version, public=dict(public))

    def validate(self, envelope):
        return envelope

    def address(self, envelope):
        return envelope.public.get("address")


_CODECS = ConnectionCodecs([_AddressCodec()])


@pytest.fixture
def relays(session_factory, settings):
    return RelayService(
        session_factory=session_factory, settings=settings, connection_codecs=_CODECS
    )


def _make_relay(relays, **overrides):
    fields = {
        "relay_id": "site-a",
        "relay_addr": "10.0.0.9",
        "relay_port": 7000,
        "vm_port_range_start": 6100,
        "vm_port_range_count": 100,
    }
    fields.update(overrides)
    return relays.create_relay(**fields)


class TestRelayAdministration:
    def test_a_relay_is_created_and_read_back(self, relays):
        created = _make_relay(relays, label="Site A")
        fetched = relays.get_relay(created.id)
        assert (fetched.relay_addr, fetched.relay_port) == ("10.0.0.9", 7000)
        assert fetched.vm_port_range_count == 100
        assert fetched.enabled is True

    def test_an_address_is_normalized_on_write(self, relays):
        created = _make_relay(relays, relay_addr="  Relay.Local  ")
        assert created.relay_addr == "relay.local"

    def test_a_duplicate_rendezvous_is_refused_with_both_named(self, relays):
        _make_relay(relays, relay_id="first")
        with pytest.raises(RelayEndpointConflictError) as excinfo:
            _make_relay(relays, relay_id="second")
        assert "first" in str(excinfo.value)
        assert "10.0.0.9:7000" in str(excinfo.value)

    def test_a_differently_spelled_duplicate_is_still_a_duplicate(self, relays):
        _make_relay(relays, relay_id="first", relay_addr="relay.local")
        with pytest.raises(RelayEndpointConflictError):
            _make_relay(relays, relay_id="second", relay_addr="RELAY.LOCAL")

    def test_an_update_onto_another_relays_rendezvous_is_refused(self, relays):
        _make_relay(relays, relay_id="first")
        _make_relay(relays, relay_id="second", relay_addr="10.0.0.10")
        with pytest.raises(RelayEndpointConflictError):
            relays.update_relay("second", relay_addr="10.0.0.9", relay_port=7000)

    def test_an_update_keeping_its_own_rendezvous_is_allowed(self, relays):
        """The conflict check must exclude the row being updated, or every
        edit that leaves the address alone would collide with itself."""
        _make_relay(relays, relay_id="only")
        updated = relays.update_relay("only", label="renamed")
        assert updated.label == "renamed"
        assert updated.relay_addr == "10.0.0.9"

    def test_an_omitted_field_is_unchanged(self, relays):
        _make_relay(relays, label="original")
        updated = relays.update_relay("site-a", vm_port_range_count=50)
        assert updated.label == "original"
        assert updated.vm_port_range_count == 50

    def test_a_relay_can_be_disabled_and_enabled(self, relays):
        _make_relay(relays)
        assert relays.set_enabled("site-a", False).enabled is False
        assert relays.set_enabled("site-a", True).enabled is True

    def test_an_unknown_relay_is_reported_as_missing(self, relays):
        with pytest.raises(RelayNotFoundError):
            relays.get_relay("absent")

    @pytest.mark.parametrize(
        "window", [{"vm_port_range_start": 0}, {"vm_port_range_count": -1}]
    )
    def test_an_unusable_window_is_refused(self, relays, window):
        with pytest.raises(RelayValidationError):
            _make_relay(relays, **window)

    def test_a_window_running_past_the_port_space_is_refused(self, relays):
        with pytest.raises(RelayValidationError):
            _make_relay(relays, vm_port_range_start=65500, vm_port_range_count=100)


class TestHoldings:
    """What a relay holds and has released, as the administrator reads it."""

    def _lease(self, session_factory, port, owner_id, *, released=False):
        with session_factory() as db, db.begin():
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

    def test_held_and_released_leases_are_read_by_port(self, relays, session_factory):
        _make_relay(relays)
        _make_relay(relays, relay_id="site-b", relay_addr="10.0.0.10")
        self._lease(session_factory, 6102, "cr-held")
        self._lease(session_factory, 6100, "cr-done", released=True)
        with session_factory() as db, db.begin():
            db.add(
                RelayPortLease(
                    id="lease-elsewhere",
                    relay_id="site-b",
                    remote_port=6101,
                    owner_kind="fulfillment",
                    owner_id="cr-elsewhere",
                )
            )

        holdings = relays.list_leases("site-a")

        assert [(record.remote_port, record.owner_id) for record in holdings] == [
            (6100, "cr-done"),
            (6102, "cr-held"),
        ]
        assert holdings[0].released_at is not None
        assert holdings[1].released_at is None
        assert holdings[1].allocated_at is not None

    def test_a_relay_with_no_lease_holds_nothing(self, relays):
        _make_relay(relays)
        assert relays.list_leases("site-a") == []

    def test_an_unknown_relay_is_reported_as_missing(self, relays):
        with pytest.raises(RelayNotFoundError):
            relays.list_leases("absent")


class TestTokenConfidentiality:
    def test_a_stored_token_is_ciphertext(self, relays, session_factory):
        _make_relay(relays, token="admission-secret")
        with Session(session_factory.kw["bind"]) as db:
            stored = db.get(Relay, "site-a").relay_token_encrypted
        assert stored is not None
        assert "admission-secret" not in stored

    def test_the_stored_token_needs_the_profile_key_to_recover(self, relays, session_factory):
        _make_relay(relays, token="admission-secret")
        with Session(session_factory.kw["bind"]) as db:
            stored = db.get(Relay, "site-a").relay_token_encrypted
        assert Fernet(_KEY.encode()).decrypt(stored.encode()).decode() == "admission-secret"
        with pytest.raises(Exception):
            Fernet(Fernet.generate_key()).decrypt(stored.encode())

    def test_no_relay_view_carries_the_token(self, relays):
        view = _make_relay(relays, token="admission-secret")
        assert "admission-secret" not in repr(view)
        assert not hasattr(view, "relay_token_encrypted")

    def test_a_view_reports_whether_a_token_is_configured(self, relays):
        assert _make_relay(relays, relay_id="bare").token_configured is False
        assert (
            _make_relay(
                relays, relay_id="ready", relay_addr="10.0.0.10", token="t"
            ).token_configured
            is True
        )

    def test_rotation_replaces_the_token(self, relays, session_factory):
        _make_relay(relays, token="first")
        relays.rotate_token("site-a", "second")
        with Session(session_factory.kw["bind"]) as db:
            stored = db.get(Relay, "site-a").relay_token_encrypted
        assert Fernet(_KEY.encode()).decrypt(stored.encode()).decode() == "second"

    def test_a_token_cannot_be_cleared_by_rotation(self, relays):
        """Clearing one disables every buyer path on that relay, so it is not
        something an empty value should be able to express."""
        _make_relay(relays, token="first")
        with pytest.raises(RelayValidationError):
            relays.rotate_token("site-a", "")


class TestRelayDefinitionDocuments:
    def _document(self, **overrides):
        entry = {
            "id": "site-a",
            "relay_addr": "10.0.0.9",
            "relay_port": 7000,
            "vm_port_range_start": 6100,
            "vm_port_range_count": 100,
            "token_secret_key": "relay_token",
            "grant_key_secret_key": "relay_grant_key",
        }
        entry.update(overrides)
        return {"relays": [entry]}

    def _yaml(self, **overrides):
        return yaml.safe_dump(self._document(**overrides))

    def test_a_named_profile_key_supplies_the_token(self, relays, settings, session_factory):
        import_relay_definitions(
            self._yaml(), relay_service=relays, settings=settings
        )
        with Session(session_factory.kw["bind"]) as db:
            stored = db.get(Relay, "site-a").relay_token_encrypted
        assert Fernet(_KEY.encode()).decrypt(stored.encode()).decode() == "bootstrap-token"

    def test_a_missing_profile_key_fails_naming_it(self, relays, settings):
        with pytest.raises(RelayDefinitionError) as excinfo:
            import_relay_definitions(
                self._yaml(token_secret_key="absent_key"),
                relay_service=relays,
                settings=settings,
            )
        assert "absent_key" in str(excinfo.value)

    def test_a_relay_is_not_created_when_its_key_is_missing(self, relays, settings):
        with pytest.raises(RelayDefinitionError):
            import_relay_definitions(
                self._yaml(token_secret_key="absent_key"),
                relay_service=relays,
                settings=settings,
            )
        assert relays.list_relays() == []

    def test_a_rotated_token_survives_a_reconciliation(
        self, relays, settings, session_factory
    ):
        """The one field a reconciliation must never revert.

        The document still names the profile key holding the bootstrap value.
        Re-reading it would silently undo an operator's rotation on any edit to
        an unrelated field.
        """
        import_relay_definitions(self._yaml(), relay_service=relays, settings=settings)
        relays.rotate_token("site-a", "rotated-by-operator")

        import_relay_definitions(
            self._yaml(vm_port_range_count=50),
            relay_service=relays,
            settings=settings,
        )

        with Session(session_factory.kw["bind"]) as db:
            row = db.get(Relay, "site-a")
        assert row.vm_port_range_count == 50
        assert (
            Fernet(_KEY.encode()).decrypt(row.relay_token_encrypted.encode()).decode()
            == "rotated-by-operator"
        )

    def test_an_unchanged_document_reports_everything_unchanged(self, relays, settings):
        import_relay_definitions(self._yaml(), relay_service=relays, settings=settings)
        diff = import_relay_definitions(
            self._yaml(), relay_service=relays, settings=settings
        )
        assert diff.unchanged == ("site-a",)
        assert diff.created == ()
        assert diff.updated == ()

    def test_an_edited_document_updates_the_relay(self, relays, settings):
        import_relay_definitions(self._yaml(), relay_service=relays, settings=settings)
        diff = import_relay_definitions(
            self._yaml(vm_port_range_start=7100),
            relay_service=relays,
            settings=settings,
        )
        assert diff.updated == ("site-a",)
        assert relays.get_relay("site-a").vm_port_range_start == 7100

    def test_an_unknown_field_is_refused(self):
        document = self._document()
        document["relays"][0]["token_secret_kye"] = "relay_token"
        with pytest.raises(RelayDefinitionError) as excinfo:
            parse_relay_definitions(yaml.safe_dump(document))
        assert "token_secret_kye" in str(excinfo.value)

    def test_two_entries_on_one_rendezvous_are_refused(self):
        document = self._document()
        second = dict(document["relays"][0])
        second["id"] = "site-b"
        document["relays"].append(second)
        with pytest.raises(RelayDefinitionError):
            parse_relay_definitions(yaml.safe_dump(document))

    def test_a_missing_required_field_names_it(self):
        document = self._document()
        del document["relays"][0]["vm_port_range_count"]
        with pytest.raises(RelayDefinitionError) as excinfo:
            parse_relay_definitions(yaml.safe_dump(document))
        assert "vm_port_range_count" in str(excinfo.value)

    def test_the_named_profile_key_supplies_the_grant_key(self, relays, settings):
        import_relay_definitions(self._yaml(), relay_service=relays, settings=settings)
        active = relays.get_relay("site-a").grant_keys.active
        assert (active.kid, active.public_key) == (_GRANT_KEY.kid, _GRANT_KEY.public_key)

    def test_an_entry_naming_no_grant_key_fails_naming_the_entry(self, relays, settings):
        document = self._document()
        del document["relays"][0]["grant_key_secret_key"]
        with pytest.raises(RelayDefinitionError) as excinfo:
            import_relay_definitions(
                yaml.safe_dump(document), relay_service=relays, settings=settings
            )
        assert "'site-a'" in str(excinfo.value)
        assert "grant_key_secret_key" in str(excinfo.value)
        assert relays.list_relays() == []

    @pytest.mark.parametrize(
        "value",
        [None, "  \n", "bm90IGEga2V5", GrantKey.generate().profile_form()[:-8]],
        ids=["absent", "blank", "not-a-key", "truncated"],
    )
    def test_an_unusable_grant_key_fails_naming_relay_and_profile_key(
        self, relays, settings, value
    ):
        """Checked for every new entry before any is written: the first entry
        here is sound, and is not created either."""
        if value is not None:
            settings.broken_grant_key = value
        document = self._document()
        sound = dict(document["relays"][0], id="site-sound", relay_addr="10.0.0.10")
        document["relays"].insert(0, sound)
        document["relays"][1]["grant_key_secret_key"] = "broken_grant_key"

        with pytest.raises(RelayDefinitionError) as excinfo:
            import_relay_definitions(
                yaml.safe_dump(document), relay_service=relays, settings=settings
            )

        message = str(excinfo.value)
        assert "'site-a'" in message
        assert "'broken_grant_key'" in message
        if value is not None and value.strip():
            assert value.strip() not in message
        assert relays.list_relays() == []

    def test_two_entries_naming_one_grant_key_create_nothing(self, relays, settings):
        document = self._document()
        document["relays"].append(
            dict(document["relays"][0], id="site-b", relay_addr="10.0.0.10")
        )
        with pytest.raises(RelayDefinitionError) as excinfo:
            import_relay_definitions(
                yaml.safe_dump(document), relay_service=relays, settings=settings
            )
        assert "'site-a'" in str(excinfo.value) and "'site-b'" in str(excinfo.value)
        assert relays.list_relays() == []

    def test_an_entry_naming_a_key_another_relay_holds_creates_nothing(
        self, relays, settings
    ):
        """Refused before any entry is written, though each write of this
        import would commit on its own."""
        _make_relay(relays, relay_id="held", relay_addr="10.0.0.20", grant_key=_GRANT_KEY)
        document = self._document()
        sound = dict(
            document["relays"][0],
            id="site-sound",
            relay_addr="10.0.0.10",
            grant_key_secret_key="sound_grant_key",
        )
        settings.sound_grant_key = GrantKey.generate().profile_form()
        document["relays"].insert(0, sound)

        with pytest.raises(RelayDefinitionError) as excinfo:
            import_relay_definitions(
                yaml.safe_dump(document), relay_service=relays, settings=settings
            )

        message = str(excinfo.value)
        assert "'site-a'" in message and "'relay_grant_key'" in message
        assert "'held'" in message
        assert [view.id for view in relays.list_relays()] == ["held"]

    def test_a_reconciliation_never_rewrites_a_key(self, relays, settings):
        """The document names the profile key holding the bootstrap key; an
        operator's rotation since is what the relay signs with afterwards."""
        import_relay_definitions(self._yaml(), relay_service=relays, settings=settings)
        staged = relays.stage_grant_key("site-a")
        relays.activate_grant_key("site-a")

        import_relay_definitions(
            self._yaml(vm_port_range_count=50), relay_service=relays, settings=settings
        )

        view = relays.get_relay("site-a")
        assert view.vm_port_range_count == 50
        assert view.grant_keys.active.kid == staged.kid
        assert [key.kid for key in view.grant_keys.retired] == [_GRANT_KEY.kid]


class TestGrantKeys:
    """Each relay signs with its own key, held as ciphertext and shown only by
    its id and public half."""

    def _stored(self, session_factory, relay_id="site-a") -> Relay:
        with Session(session_factory.kw["bind"]) as db:
            row = db.get(Relay, relay_id)
            db.expunge(row)
            return row

    def test_a_relay_created_with_no_key_gets_an_active_one(self, relays):
        active = _make_relay(relays).grant_keys.active
        assert active is not None
        assert active.activated_at is not None
        assert relays.get_relay("site-a").grant_keys.active.kid == active.kid

    def test_a_supplied_key_is_the_active_one(self, relays):
        key = GrantKey.generate()
        active = _make_relay(relays, grant_key=key).grant_keys.active
        assert (active.kid, active.public_key) == (key.kid, key.public_key)

    def test_a_stored_key_is_ciphertext(self, relays, session_factory):
        key = GrantKey.generate()
        _make_relay(relays, grant_key=key)
        stored = self._stored(session_factory)
        assert key.profile_form() not in stored.grant_key_encrypted
        recovered = Fernet(_KEY.encode()).decrypt(stored.grant_key_encrypted.encode())
        assert GrantKey.from_profile_form(recovered.decode()).kid == key.kid

    def test_no_view_carries_a_private_key(self, relays):
        key = GrantKey.generate()
        view = _make_relay(relays, grant_key=key)
        staged_key = GrantKey.generate()
        relays.stage_grant_key("site-a", staged_key.profile_form())
        for shown in (repr(view), repr(relays.get_relay("site-a")), repr(relays.list_relays())):
            assert key.profile_form() not in shown
            assert staged_key.profile_form() not in shown

    def test_staging_leaves_the_active_key_signing(self, relays, session_factory):
        active = _make_relay(relays).grant_keys.active
        supplied = GrantKey.generate()

        staged = relays.stage_grant_key("site-a", supplied.profile_form())

        assert (staged.kid, staged.public_key) == (supplied.kid, supplied.public_key)
        view = relays.get_relay("site-a")
        assert view.grant_keys.active == active
        assert view.grant_keys.staged.kid == supplied.kid
        assert supplied.profile_form() not in self._stored(session_factory).staged_grant_key_encrypted

    def test_staging_with_no_key_generates_one(self, relays):
        active = _make_relay(relays).grant_keys.active
        staged = relays.stage_grant_key("site-a")
        assert staged.kid != active.kid
        assert relays.get_relay("site-a").grant_keys.staged.kid == staged.kid

    def test_a_malformed_supplied_key_is_refused_without_the_value(self, relays):
        _make_relay(relays)
        value = GrantKey.generate().profile_form()[:-8]
        with pytest.raises(RelayValidationError) as refused:
            relays.stage_grant_key("site-a", value)
        assert value not in str(refused.value)
        assert relays.get_relay("site-a").grant_keys.staged is None

    def test_a_key_that_has_signed_for_the_relay_is_not_staged_again(self, relays):
        first = GrantKey.generate()
        _make_relay(relays, grant_key=first)
        with pytest.raises(RelayValidationError):
            relays.stage_grant_key("site-a", first.profile_form())
        relays.stage_grant_key("site-a")
        relays.activate_grant_key("site-a")
        with pytest.raises(RelayValidationError):
            relays.stage_grant_key("site-a", first.profile_form())

    def test_a_key_another_relay_holds_or_retired_is_refused(self, relays):
        """A key signs for one relay: one leak never opens two."""
        first = GrantKey.generate()
        _make_relay(relays, grant_key=first)
        _make_relay(relays, relay_id="site-b", relay_addr="10.0.0.10")

        with pytest.raises(RelayValidationError) as refused:
            relays.stage_grant_key("site-b", first.profile_form())
        assert "'site-a'" in str(refused.value)
        with pytest.raises(RelayValidationError):
            _make_relay(relays, relay_id="site-c", relay_addr="10.0.0.11", grant_key=first)

        staged = GrantKey.generate()
        relays.stage_grant_key("site-a", staged.profile_form())
        with pytest.raises(RelayValidationError) as refused:
            relays.stage_grant_key("site-b", staged.profile_form())
        assert "'site-a'" in str(refused.value)

        relays.activate_grant_key("site-a")
        with pytest.raises(RelayValidationError) as refused:
            relays.stage_grant_key("site-b", first.profile_form())
        assert "retired" in str(refused.value)
        with pytest.raises(RelayValidationError) as refused:
            _make_relay(relays, relay_id="site-c", relay_addr="10.0.0.11", grant_key=first)
        assert "retired" in str(refused.value)

    def test_activation_retires_the_previous_key_with_its_time(self, relays):
        first = _make_relay(relays).grant_keys.active
        staged = relays.stage_grant_key("site-a")

        activated = relays.activate_grant_key("site-a").grant_keys

        assert activated.active.kid == staged.kid
        assert activated.active.public_key == staged.public_key
        assert activated.staged is None
        assert [key.kid for key in activated.retired] == [first.kid]
        assert activated.retired[0].retired_at == activated.active.activated_at
        assert activated.retired[0].retired_at >= first.activated_at
        listed = relays.list_relays()[0].grant_keys
        assert listed == activated

    def test_activation_needs_a_staged_key(self, relays):
        _make_relay(relays)
        with pytest.raises(RelayGrantKeyNotStagedError):
            relays.activate_grant_key("site-a")

    def test_an_unknown_relay_stages_nothing(self, relays):
        with pytest.raises(RelayNotFoundError):
            relays.stage_grant_key("absent")


class TestRebinding:
    """A relay binding is fixed for a lease's life.

    The buyer holds a rendezvous address and a port. Both are delivered, and a
    remote port is not portable between relays — 6142 on one says nothing about
    6142 on another, which may already be leased. So a rebinding that moved
    existing deliveries would strand every buyer on the affected hosts, and
    these rules refuse it rather than accept it and reissue connection strings
    the system has no way to deliver.
    """

    def _make_lease(self, session_factory, *, relay_id="site-a",
                    pool_id="gpu-pool", host="kvm1"):
        with session_factory() as db, db.begin():
            db.add(
                RelayPortLease(
                    id=f"lease-{relay_id}",
                    relay_id=relay_id,
                    remote_port=6100,
                    host_id=host,
                    pool_id=pool_id,
                    owner_kind="fulfillment",
                    owner_id=f"cr-{relay_id}",
                )
            )

    def _relay_with_lease(self, session_factory, relays, *, relay_id="site-a",
                          addr="10.0.0.9", pool_id="gpu-pool", host="kvm1"):
        _make_relay(relays, relay_id=relay_id, relay_addr=addr)
        self._make_lease(
            session_factory, relay_id=relay_id, pool_id=pool_id, host=host
        )

    def test_a_relay_cannot_move_while_it_carries_tunnels(
        self, session_factory, relays
    ):
        self._relay_with_lease(session_factory, relays)
        with pytest.raises(RelayRebindingRefused) as excinfo:
            relays.update_relay("site-a", relay_addr="10.0.0.20")
        message = str(excinfo.value)
        assert "kvm1:6100" in message
        assert "Disable the pool" in message

    def test_a_relay_can_move_once_drained(self, session_factory, relays):
        self._relay_with_lease(session_factory, relays)
        with session_factory() as db, db.begin():
            db.query(RelayPortLease).one().released_at = datetime.now(timezone.utc)

        assert relays.update_relay("site-a", relay_addr="10.0.0.20").relay_addr == "10.0.0.20"

    def test_a_relay_edit_that_does_not_move_it_is_unaffected(
        self, session_factory, relays
    ):
        """Only the endpoint is protected. A window or label change touches
        nothing a buyer holds."""
        self._relay_with_lease(session_factory, relays)
        assert relays.update_relay("site-a", label="renamed").label == "renamed"
        assert relays.update_relay("site-a", vm_port_range_count=50).vm_port_range_count == 50

    def test_a_carrying_relay_cannot_have_its_token_rotated(
        self, session_factory, relays
    ):
        """Rotation joins the drain rule, for a different reason than the
        endpoint does.

        It does not change the address or port a buyer holds — but a host
        adopts a new token only by restarting its tunnel client, since `auth`
        is not reloadable, and that restart drops every proxy the client
        registered. `frps` also admits on one token, so a rotation invalidates
        every client still holding the old one.
        """
        self._relay_with_lease(session_factory, relays)

        with pytest.raises(RelayRebindingRefused) as excinfo:
            relays.rotate_token("site-a", "rotated")

        assert "kvm1:6100" in str(excinfo.value)

    def test_a_token_can_be_set_before_any_host_dials(self, relays):
        """The ordinary case is unaffected: a relay with no leases has nothing
        to disturb."""
        _make_relay(relays)

        assert relays.rotate_token("site-a", "first-token").token_configured is True

    def test_a_token_can_be_rotated_once_drained(self, session_factory, relays):
        self._relay_with_lease(session_factory, relays)
        with session_factory() as db, db.begin():
            db.query(RelayPortLease).one().released_at = datetime.now(timezone.utc)

        assert relays.rotate_token("site-a", "rotated").token_configured is True


@dataclass(frozen=True)
class _JobParams:
    """The relay fields a domain's job parameters carry."""

    host_id: str = "kvm1"
    relay_id: str | None = None
    relay_addr: str | None = None
    relay_port: int | None = None
    relay_token: str | None = None
    relay_grant: str | None = None


class TestExecutionTimeTokenResolution:
    """The token is resolved here and nowhere earlier.

    An accepted operation is persisted in a JSON column and returned by the job
    endpoints, so a credential in it would be neither encrypted at rest nor
    withheld from a read. Resolving at execution also means a rotation reaches
    a retry of a job accepted before it.
    """

    def _resolver(self, session_factory, settings):
        return RelayExecutionResolver(session_factory=session_factory, settings=settings)

    def _params(self, **overrides):
        return _JobParams(**overrides)

    def test_a_job_with_no_relay_passes_through(self, session_factory, settings):
        params = self._params()
        assert self._resolver(session_factory, settings).resolve_into(params) is params

    def test_the_address_and_token_are_filled_in(self, relays, session_factory, settings):
        _make_relay(relays, token="admission-token")
        resolved = self._resolver(session_factory, settings).resolve_into(
            self._params(relay_id="site-a")
        )
        assert resolved.relay_addr == "10.0.0.9"
        assert resolved.relay_port == 7000
        assert resolved.relay_token == "admission-token"

    def test_a_rotation_reaches_a_job_accepted_before_it(
        self, relays, session_factory, settings
    ):
        """The second reason for late binding. A snapshot would pin the value
        that was correct at acceptance, which after a rotation is exactly the
        value that no longer works."""
        _make_relay(relays, token="original")
        params = self._params(relay_id="site-a")
        relays.rotate_token("site-a", "rotated")

        resolved = self._resolver(session_factory, settings).resolve_into(params)

        assert resolved.relay_token == "rotated"

    @pytest.mark.parametrize(
        "break_it, expected",
        [
            (lambda r: r.set_enabled("site-a", False), "disabled"),
            (lambda r: None, "no admission token"),
        ],
    )
    def test_an_unusable_relay_fails_the_job(
        self, relays, session_factory, settings, break_it, expected
    ):
        _make_relay(relays, token="admission-token" if expected == "disabled" else None)
        break_it(relays)
        with pytest.raises(RelayUnusableAtExecutionError) as excinfo:
            self._resolver(session_factory, settings).resolve_into(
                self._params(relay_id="site-a")
            )
        assert expected in str(excinfo.value)

    def test_a_vanished_relay_fails_the_job(self, session_factory, settings):
        with pytest.raises(RelayUnusableAtExecutionError):
            self._resolver(session_factory, settings).resolve_into(
                self._params(relay_id="never-created")
            )


def _decoded(part: str) -> bytes:
    return base64.urlsafe_b64decode(part + "=" * (-len(part) % 4))


def _segments(token: str) -> tuple[dict, dict]:
    header, claims, _ = token.split(".")
    return json.loads(_decoded(header)), json.loads(_decoded(claims))


def _verifies(token: str, public_key: str) -> bool:
    signing_input, _, signature = token.rpartition(".")
    key = serialization.load_der_public_key(base64.b64decode(public_key))
    try:
        key.verify(_decoded(signature), signing_input.encode("ascii"))
    except InvalidSignature:
        return False
    return True


class TestGrantsAtExecution:
    """A job adding a proxy has its grant signed as it runs, on every attempt,
    with the relay's then-active key, and the lease records which key."""

    _LEASE_END = datetime(2031, 6, 1, 12, 0, tzinfo=timezone.utc)

    def _relay_with_lease(self, relays, session_factory, *, owner="cr-1", host="kvm1"):
        _make_relay(relays, token="admission-token")
        return RelayPortAllocator(session_factory).allocate(
            relay_id="site-a",
            owner_kind="fulfillment",
            owner_id=owner,
            lease_ends_at=self._LEASE_END,
            host_id=host,
        )

    def _resolve(self, session_factory, settings, port, owner="cr-1"):
        return RelayExecutionResolver(
            session_factory=session_factory, settings=settings
        ).resolve_into(_JobParams(relay_id="site-a"), remote_port=port, owner_id=owner)

    def _lease_row(self, session_factory) -> RelayPortLease:
        with Session(session_factory.kw["bind"]) as db:
            row = db.query(RelayPortLease).one()
            db.expunge(row)
            return row

    def test_the_grant_is_signed_for_the_lease_with_the_active_key(
        self, relays, session_factory, settings
    ):
        lease = self._relay_with_lease(relays, session_factory)
        active = relays.get_relay("site-a").grant_keys.active

        params = _JobParams(relay_id="site-a")
        resolved = RelayExecutionResolver(
            session_factory=session_factory, settings=settings
        ).resolve_into(params, remote_port=lease.remote_port, owner_id="cr-1")

        assert params.relay_grant is None
        header, claims = _segments(resolved.relay_grant)
        assert header == {"alg": "EdDSA", "kid": active.kid, "typ": "frp-grant+jwt"}
        assert claims == {
            "aud": "site-a",
            "port": lease.remote_port,
            "exp": int((self._LEASE_END + timedelta(hours=1)).timestamp()),
            "sub": "kvm1",
            "jti": "cr-1",
        }
        assert _verifies(resolved.relay_grant, active.public_key)
        assert self._lease_row(session_factory).grant_key_id == active.kid

    def test_a_retry_after_a_rotation_signs_with_the_new_key(
        self, relays, session_factory, settings
    ):
        lease = self._relay_with_lease(relays, session_factory)
        first = relays.get_relay("site-a").grant_keys.active
        self._resolve(session_factory, settings, lease.remote_port)
        staged = relays.stage_grant_key("site-a")
        relays.activate_grant_key("site-a")

        retried = self._resolve(session_factory, settings, lease.remote_port)

        header, claims = _segments(retried.relay_grant)
        assert header["kid"] == staged.kid
        assert _verifies(retried.relay_grant, staged.public_key)
        assert claims["jti"] == "cr-1"
        row = self._lease_row(session_factory)
        assert row.grant_key_id == staged.kid
        # The retired key may still have a grant installed on the host, so it
        # stays valid until the lease's grant expiry while the lease is held.
        (retired,) = relays.get_relay("site-a").grant_keys.retired
        assert retired.kid == first.kid
        assert retired.grants_valid_until == row.grant_expires_at
        assert relays.list_relays()[0].grant_keys.retired[0].grants_valid_until == (
            row.grant_expires_at
        )

        RelayPortAllocator(session_factory).release(owner_kind="fulfillment", owner_id="cr-1")
        assert relays.get_relay("site-a").grant_keys.retired[0].grants_valid_until is None

    def test_a_lease_allocated_after_a_retirement_does_not_extend_it(
        self, relays, session_factory, settings
    ):
        _make_relay(relays, token="admission-token")
        relays.stage_grant_key("site-a")
        relays.activate_grant_key("site-a")
        RelayPortAllocator(session_factory).allocate(
            relay_id="site-a",
            owner_kind="fulfillment",
            owner_id="cr-later",
            lease_ends_at=self._LEASE_END,
        )

        (retired,) = relays.get_relay("site-a").grant_keys.retired
        assert retired.grants_valid_until is None

    def test_a_lease_with_no_host_carries_no_subject(self, relays, session_factory, settings):
        lease = self._relay_with_lease(relays, session_factory, host=None)
        _, claims = _segments(self._resolve(session_factory, settings, lease.remote_port).relay_grant)
        assert "sub" not in claims
        assert claims["jti"] == "cr-1"
        assert isinstance(claims["exp"], int)

    def test_a_retenancy_names_the_new_reservation(self, relays, session_factory, settings):
        _make_relay(relays, token="admission-token", vm_port_range_count=1)
        allocator = RelayPortAllocator(session_factory)
        ended = datetime(2020, 1, 1, tzinfo=timezone.utc)
        allocator.allocate(
            relay_id="site-a", owner_kind="fulfillment", owner_id="cr-old", lease_ends_at=ended
        )
        allocator.release(owner_kind="fulfillment", owner_id="cr-old")
        lease = allocator.allocate(
            relay_id="site-a",
            owner_kind="fulfillment",
            owner_id="cr-new",
            lease_ends_at=self._LEASE_END,
        )

        _, claims = _segments(
            self._resolve(session_factory, settings, lease.remote_port, owner="cr-new").relay_grant
        )

        assert claims["jti"] == "cr-new"

    def test_a_relay_with_no_active_key_fails_the_job(self, relays, session_factory, settings):
        lease = self._relay_with_lease(relays, session_factory)
        with session_factory() as db, db.begin():
            row = db.get(Relay, "site-a")
            row.grant_key_encrypted = row.grant_key_id = row.grant_key_public = None

        with pytest.raises(RelayUnusableAtExecutionError, match="no active grant key"):
            self._resolve(session_factory, settings, lease.remote_port)

    def test_a_port_with_no_held_lease_fails_the_job(self, relays, session_factory, settings):
        _make_relay(relays, token="admission-token")
        with pytest.raises(RelayUnusableAtExecutionError, match="holds no lease"):
            self._resolve(session_factory, settings, 6150)

    @pytest.mark.parametrize("owner", ["cr-another", None])
    def test_a_port_another_reservation_holds_gets_no_grant(
        self, relays, session_factory, settings, owner
    ):
        """A grant authorizes its port alone, so a job naming another
        tenancy's port, or no reservation at all, is refused one."""
        lease = self._relay_with_lease(relays, session_factory)
        with pytest.raises(RelayUnusableAtExecutionError, match="for this job's reservation"):
            self._resolve(session_factory, settings, lease.remote_port, owner=owner)
        assert self._lease_row(session_factory).grant_key_id is None

    def test_a_removal_needs_no_grant(self, relays, session_factory, settings):
        _make_relay(relays, token="admission-token")
        resolved = RelayExecutionResolver(
            session_factory=session_factory, settings=settings
        ).resolve_into(_JobParams(relay_id="site-a"))
        assert resolved.relay_grant is None
        assert resolved.relay_token == "admission-token"

    def test_the_holdings_read_shows_the_grant_expiry_and_signing_key(
        self, relays, session_factory, settings
    ):
        lease = self._relay_with_lease(relays, session_factory)
        self._resolve(session_factory, settings, lease.remote_port)

        (record,) = relays.list_leases("site-a")

        assert record.grant_expires_at == datetime(2031, 6, 1, 13, 0)
        assert record.grant_key_id == relays.get_relay("site-a").grant_keys.active.kid


class TestManagementRoute:
    """A host is not reached through the relay its pool sells buyers on."""

    def _pool(self, session_factory, pool_id, relay_id=None):
        with session_factory() as db, db.begin():
            db.add(ResourcePool(id=pool_id, label=pool_id, provider="test", policy_tags={}))
            if relay_id is not None:
                db.add(PoolRelay(pool_id=pool_id, relay_id=relay_id))

    def _host(self, session_factory, host_id, address, pool_id=None):
        with session_factory() as db, db.begin():
            host = Host(host_id=host_id, enabled=True, pool_id=pool_id)
            host.set_connection(
                ConnectionEnvelope(kind="fake", version=1, public={"address": address})
            )
            db.add(host)

    def _move(self, session_factory, host_id, new_pool):
        hooks = relay_host_pool_change_hooks(_CODECS)
        with session_factory() as db, db.begin():
            current = db.get(Host, host_id).pool_id
            for hook in hooks:
                hook(db, host_id, current, new_pool)

    def test_a_host_reached_at_its_pools_relay_address_is_refused(
        self, relays, session_factory
    ):
        _make_relay(relays, relay_addr="10.0.0.9")
        self._pool(session_factory, "relayed", "site-a")
        self._host(session_factory, "kvm1", " 10.0.0.9 ")

        with pytest.raises(PoolChangeRefusedError) as refused:
            self._move(session_factory, "kvm1", "relayed")

        assert "kvm1" in str(refused.value) and "site-a" in str(refused.value)

    def test_a_host_reached_another_way_is_placed(self, relays, session_factory):
        _make_relay(relays, relay_addr="10.0.0.9")
        self._pool(session_factory, "relayed", "site-a")
        self._pool(session_factory, "direct")
        self._host(session_factory, "kvm1", "10.0.0.50")
        self._host(session_factory, "kvm2", "10.0.0.9")

        self._move(session_factory, "kvm1", "relayed")
        self._move(session_factory, "kvm2", "direct")

    def test_a_relay_is_not_moved_onto_a_placed_hosts_address(self, relays, session_factory):
        _make_relay(relays, relay_addr="10.0.0.9")
        self._pool(session_factory, "relayed", "site-a")
        self._host(session_factory, "kvm1", "10.0.0.50", pool_id="relayed")

        with pytest.raises(ManagementRouteRefused) as refused:
            relays.update_relay("site-a", relay_addr="10.0.0.50")

        assert "kvm1" in str(refused.value) and "site-a" in str(refused.value)
        assert relays.get_relay("site-a").relay_addr == "10.0.0.9"
        assert relays.update_relay("site-a", relay_addr="10.0.0.60").relay_addr == "10.0.0.60"


class _FrozenJobParams(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    relay_id: str | None = None
    relay_addr: str | None = None
    relay_port: int | None = None
    relay_token: str | None = None
    relay_grant: str | None = None


@pytest.mark.parametrize("params_type", [_JobParams, _FrozenJobParams])
def test_resolver_copies_supported_parameters_without_mutating_the_accepted_snapshot(
    params_type, relays, session_factory, settings
):
    lease = TestGrantsAtExecution()._relay_with_lease(relays, session_factory)
    params = params_type(relay_id="site-a")
    resolved = RelayExecutionResolver(session_factory, settings).resolve_into(
        params, remote_port=lease.remote_port, owner_id="cr-1"
    )
    assert type(resolved) is params_type
    assert resolved.relay_addr == "10.0.0.9"
    assert resolved.relay_token == "admission-token"
    assert _segments(resolved.relay_grant)[1]["jti"] == "cr-1"
    assert params.relay_token is None and params.relay_grant is None


def test_resolver_refuses_unsupported_parameter_objects(session_factory, settings):
    resolver = RelayExecutionResolver(session_factory, settings)
    with pytest.raises(TypeError, match="dataclass or frozen Pydantic"):
        resolver.resolve_into(SimpleNamespace(relay_id=None))
