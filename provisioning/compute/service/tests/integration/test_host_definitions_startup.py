"""A site's hosts at startup: the host definitions document, gated on its digest.

Startup reconciles the document ``host_definitions_path`` names only when it
differs from the one last reconciled, and records its digest in the apply's own
transaction, after the pools an entry names exist and are checked. A process
start is not a submission: a restart against an unchanged document leaves every
host as the API last left it. A document that cannot be applied fails the
start whole and records nothing, so the next start retries it.

External boundary: SQLAlchemy against file-backed SQLite, with real pool and
host documents in a temp directory, driven through the service's real startup
entry points and importer. The host authority is composed as the service
composes it, with the real ``ssh`` codec and the relays' host hooks. All of it
is deterministic and does no network I/O.
"""

from __future__ import annotations

import logging
from types import SimpleNamespace

import pytest
import yaml
from bare_metal_provisioning_adapter.services.bare_metal_pool_config_handler import (
    BareMetalPoolConfigHandler,
)
from compute_provisioning.relays import Relay, RelayPortLease
from compute_provisioning_ansible import ssh_connection
from compute_provisioning_contracts import HostCreate
from cryptography.fernet import Fernet
from market_resource_pools import ResourcePoolService
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from vm_provisioning_adapter.services.ansible_pool_config_handler import (
    AnsiblePoolConfigHandler,
)

from compute_provisioning_service import app_runtime
from compute_provisioning_service import container as _container_module
from compute_provisioning_service.config import settings as service_settings
from compute_provisioning_service.db.database import run_migrations
from compute_provisioning_service.db.models import DefinitionDocumentImport
from compute_provisioning_service.services.definition_documents import (
    DefinitionDocumentImporter,
    HostDefinitionsRejected,
)

_HOSTS_KIND = "hosts"

# A development-only Fernet key, generated per run and never used on any
# network; no host here submits key material for it to protect.
_KEY = Fernet.generate_key().decode()

_RELAY_POOL = "relay-pool"
_PLAIN_POOL = "plain-pool"

_POOL_DOCUMENT = f"""
pools:
  - id: {_RELAY_POOL}
    label: Relay pool
    provider: vm.ansible
    policy_tags: {{deliverable_modes: [vm], advertisable_modes: [vm], capacity_backing: backed}}
    provider_config: {{relay_id: site-a}}
  - id: {_PLAIN_POOL}
    label: Plain pool
    provider: vm.ansible
    policy_tags: {{deliverable_modes: [vm], advertisable_modes: [vm], capacity_backing: backed}}
    provider_config: {{}}
"""

_BARE_METAL_POOL_DOCUMENT = """
pools:
  - id: bm-site-pool
    label: Bare-metal site pool
    provider: bare_metal.ansible
    policy_tags: {deliverable_modes: [bare_metal], advertisable_modes: [bare_metal], capacity_backing: backed}
    provider_config: {}
"""


def _entry(host_id: str, *, pool_id: str | None = None, ssh_host: str = "10.0.0.1", **fields) -> dict:
    entry: dict = {"host_id": host_id}
    if pool_id is not None:
        entry["pool_id"] = pool_id
    entry.update(fields)
    entry["connection"] = {
        "kind": "ssh",
        "version": 2,
        "public": {"ssh_host": ssh_host, "ssh_user": "ubuntu", "key_path": "/keys/id"},
    }
    return entry


def _document(*entries: dict) -> str:
    return yaml.safe_dump({"hosts": list(entries)})


class _Site:
    """One database, its mounted pool and host documents, and the services the
    startup steps read, composed as the service composes them.

    ``start`` runs the startup steps that decide a site's pools and hosts, in
    the service's order, against this site's configuration.
    """

    def __init__(self, tmp_path, monkeypatch, *, pool_document=_POOL_DOCUMENT, seed=None):
        self.engine = create_engine(f"sqlite:///{tmp_path / 'provisioning.db'}")
        run_migrations(self.engine)
        self.session_factory = sessionmaker(bind=self.engine)
        with self.session_factory() as db, db.begin():
            # Service-internal state setup: the relay the relay pool dials. A
            # relay row is the precondition the relays' hook reads, and no host
            # document can create one.
            db.add(Relay(
                id="site-a", relay_addr="203.0.113.9", relay_port=7000,
                vm_port_range_start=6100, vm_port_range_count=100,
            ))
        self.pool_service = ResourcePoolService(
            session_factory=self.session_factory,
            handlers={
                "vm.ansible": AnsiblePoolConfigHandler(),
                "bare_metal.ansible": BareMetalPoolConfigHandler(),
            },
        )
        self.hosts = _container_module._make_host_authority(
            self.session_factory,
            _container_module._make_connection_codecs(SimpleNamespace(ssh_decryption_key=_KEY)),
        )
        self.pool_path = tmp_path / "pools.yaml"
        self.host_path = tmp_path / "host-definitions.yaml"
        if pool_document is not None:
            self.pool_path.write_text(pool_document, encoding="utf-8")
        self.settings = SimpleNamespace(
            resolved_pool_definitions_path=self.pool_path if pool_document is not None else None,
            resolved_pool_seed_path=seed,
            resolved_host_definitions_path=None,
        )
        monkeypatch.setattr(app_runtime, "settings", self.settings)
        for name, value in (
            ("resolved_resource_pool_service", self.pool_service),
            ("resolved_session_factory", self.session_factory),
            ("resolved_capacity_ledger_service", None),
            ("resolved_host_authority", self.hosts),
        ):
            monkeypatch.setattr(_container_module, name, value, raising=False)

    def mount(self, document: str) -> None:
        """Mount ``document`` at the configured host definitions path."""
        self.host_path.write_text(document, encoding="utf-8")
        self.settings.resolved_host_definitions_path = self.host_path

    def start(self) -> None:
        app_runtime.import_pool_definitions_if_configured()
        app_runtime.seed_initial_pools_if_fresh()
        app_runtime.verify_pool_declarations()
        app_runtime.import_host_definitions_if_configured()

    def registered(self) -> dict:
        return {host.host_id: host for host in self.hosts.list_hosts(enabled_only=False)}

    def recorded_digest(self) -> str | None:
        with self.session_factory() as db:
            row = db.get(DefinitionDocumentImport, _HOSTS_KIND)
            return None if row is None else row.digest

    def register(self, host_id: str, *, pool_id: str | None = None) -> None:
        """Register a host through the host API's own write."""
        self.hosts.register_host(HostCreate(
            host_id=host_id,
            pool_id=pool_id,
            connection=ssh_connection(ssh_host="10.9.9.9", ssh_user="root", key_path="/keys/api"),
        ))

    def bind_tunnel(self, host_id: str) -> None:
        """Seed a VM tunnel a buyer holds through ``host_id``, as fulfillment
        would leave it: driving a fulfillment here would test fulfillment."""
        with self.session_factory() as db, db.begin():
            db.add(RelayPortLease(
                id=f"lease-{host_id}", relay_id="site-a", remote_port=6100,
                host_id=host_id, pool_id=_RELAY_POOL,
                owner_kind="fulfillment", owner_id=f"cr-{host_id}",
            ))


@pytest.fixture
def site(tmp_path, monkeypatch):
    return _Site(tmp_path, monkeypatch)


def test_an_operator_adds_a_host_to_the_document_and_restarts(site):
    first = _document(_entry("kvm1", pool_id=_PLAIN_POOL))
    site.mount(first)
    site.start()

    site.mount(_document(
        _entry("kvm1", pool_id=_PLAIN_POOL),
        _entry("kvm2", pool_id=_RELAY_POOL, ssh_host="10.0.0.2", enabled=False),
    ))
    site.start()

    kvm2 = site.registered()["kvm2"]
    assert (kvm2.pool_id, kvm2.enabled) == (_RELAY_POOL, False)
    assert kvm2.connection.public["ssh_host"] == "10.0.0.2"
    # Dispatch reads the host through this lookup immediately before running.
    execution = site.hosts.lookup("kvm2")
    assert execution is not None and execution.connection.public["ssh_host"] == "10.0.0.2"
    assert site.recorded_digest() == DefinitionDocumentImporter.digest_of(site.host_path.read_text())


def test_an_unchanged_document_at_restart_leaves_an_api_change_alone(site, caplog):
    site.mount(_document(_entry("kvm1", pool_id=_PLAIN_POOL)))
    site.start()
    site.hosts.disable_host("kvm1")
    disabled = site.registered()["kvm1"]

    with caplog.at_level(logging.INFO):
        site.start()

    after = site.registered()["kvm1"]
    assert after.enabled is False
    assert after.updated_at == disabled.updated_at
    assert "unchanged since the last reconciliation" in caplog.text


def test_the_document_names_a_pool_the_pool_document_creates(site):
    """A fresh site: the pools come from the pool document in the same start."""
    site.mount(_document(_entry("kvm1", pool_id=_RELAY_POOL)))

    site.start()

    assert site.registered()["kvm1"].pool_id == _RELAY_POOL


def test_the_document_names_a_pool_the_fresh_site_seed_creates(tmp_path, monkeypatch):
    site = _Site(
        tmp_path, monkeypatch, pool_document=None,
        seed=service_settings.resolved_pool_seed_path,
    )
    site.mount(_document(_entry("kvm1", pool_id="vm-default")))

    site.start()

    assert site.registered()["kvm1"].pool_id == "vm-default"


def test_a_first_document_applies_on_a_site_that_already_registers_hosts(site, caplog):
    """No digest is recorded yet, so the first document is a change like any
    other: it replaces the hosts it names, and keeps and reports the rest."""
    site.start()
    site.register("kvm1", pool_id=_RELAY_POOL)
    site.register("api-only")
    site.hosts.disable_host("api-only")
    assert site.recorded_digest() is None

    site.mount(_document(
        _entry("kvm1", pool_id=_PLAIN_POOL, ssh_host="10.0.0.1"),
        _entry("kvm2", ssh_host="10.0.0.2"),
    ))
    with caplog.at_level(logging.INFO):
        site.start()

    hosts = site.registered()
    assert (hosts["kvm1"].pool_id, hosts["kvm1"].connection.public["ssh_host"]) == (
        _PLAIN_POOL, "10.0.0.1",
    )
    assert hosts["kvm2"].pool_id is None
    assert (hosts["api-only"].enabled, hosts["api-only"].pool_id) == (False, None)
    assert "created=1 updated=1 unchanged=0" in caplog.text
    assert "registered and not named, left as they are: api-only" in caplog.text
    assert site.recorded_digest() is not None


def test_a_configured_document_that_is_missing_fails_startup(site):
    site.settings.resolved_host_definitions_path = site.host_path

    with pytest.raises(FileNotFoundError, match="host-definitions"):
        site.start()

    assert site.recorded_digest() is None


def test_no_configured_document_leaves_the_registered_hosts_as_they_are(site):
    site.start()
    site.register("kvm1", pool_id=_PLAIN_POOL)
    before = site.registered()

    site.start()

    assert site.registered() == before
    assert site.recorded_digest() is None


def test_a_structurally_invalid_document_fails_startup_and_the_next_start_retries(site):
    site.mount(
        "hosts:\n"
        "  - host_id: kvm1\n"
        "    colour: blue\n"
        "    connection: {kind: ssh, version: 2, public: {ssh_host: 10.0.0.1, key_path: /keys/id}}\n"
        "  - host_id: kvm2\n"
        "    connection: {kind: ssh, version: 2, public: {ssh_host: 10.0.0.2, key_path: /keys/id}}\n"
    )

    for _ in range(2):
        with pytest.raises(HostDefinitionsRejected) as refused:
            site.start()
        assert "hosts[0].colour (unknown_field)" in str(refused.value)
        assert site.registered() == {}
        assert site.recorded_digest() is None

    site.mount(_document(_entry("kvm1"), _entry("kvm2", ssh_host="10.0.0.2")))
    site.start()

    assert sorted(site.registered()) == ["kvm1", "kvm2"]
    assert site.recorded_digest() is not None


def test_a_hook_refusing_a_move_fails_startup_naming_the_host(site):
    """The relays' hook refuses moving a host whose VM tunnel a buyer holds to a pool
    dialling another relay. The new host the document names first was written
    before the refusal, and only the rollback takes it away."""
    first = _document(_entry("kvm1", pool_id=_RELAY_POOL))
    site.mount(first)
    site.start()
    site.bind_tunnel("kvm1")

    site.mount(_document(
        _entry("kvm2", pool_id=_PLAIN_POOL, ssh_host="10.0.0.2"),
        _entry("kvm1", pool_id=_PLAIN_POOL),
    ))
    with pytest.raises(HostDefinitionsRejected) as refused:
        site.start()

    message = str(refused.value)
    assert "hosts[1].pool_id (pool_change_refused): host 'kvm1'" in message
    hosts = site.registered()
    assert sorted(hosts) == ["kvm1"]
    assert hosts["kvm1"].pool_id == _RELAY_POOL
    assert site.recorded_digest() == DefinitionDocumentImporter.digest_of(first)


def test_a_fresh_site_binds_its_host_to_a_bare_metal_pool(tmp_path, monkeypatch):
    site = _Site(tmp_path, monkeypatch, pool_document=_BARE_METAL_POOL_DOCUMENT)
    site.mount(_document(_entry("node1", pool_id="bm-site-pool")))

    site.start()

    # Read back from the stored row, through a session of its own.
    assert site.registered()["node1"].pool_id == "bm-site-pool"
    assert site.recorded_digest() is not None


def test_a_fresh_site_host_naming_an_unknown_pool_fails_startup(tmp_path, monkeypatch):
    """Neither left unplaced nor assigned another pool: the start fails."""
    site = _Site(tmp_path, monkeypatch, pool_document=_BARE_METAL_POOL_DOCUMENT)
    site.mount(_document(_entry("node1", pool_id="bm-missing")))

    with pytest.raises(HostDefinitionsRejected) as refused:
        site.start()

    assert "hosts[0].pool_id (unknown_pool): host 'node1'" in str(refused.value)
    assert site.registered() == {}
    assert site.recorded_digest() is None
