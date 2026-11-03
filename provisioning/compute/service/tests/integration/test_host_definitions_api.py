"""The host definitions export and import, over the real API, through the canonical client.

Every import goes through ``ComputeProvisioningClient.import_host_definitions``
and every export through ``export_hosts``, so a route, body, or response-shape
change breaks these tests through the client. The typed import reads a 422 and
a 200 alike, so where a scenario names the status, the client is built on a
transport that records each response it carries, and the status and content
type are read there. Connections are the real ``ssh`` codec's, composed by the
service.

A refused move is the relays' pool-change hook refusing to move a host whose VM tunnel
a buyer holds, seeded as a port-lease row as the pool-move tests seed it.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

import httpx
import pytest
import pytest_asyncio
import yaml
from compute_provisioning_ansible import ssh_connection
from compute_provisioning_client import ComputeProvisioningAuthenticationError, ComputeProvisioningClient
from compute_provisioning_contracts import SIGNATURE_HEADER, HostCreate, HostUpdate
from httpx import ASGITransport

from compute_provisioning_service import container as _container_module
from compute_provisioning_service.db.models import DefinitionDocumentImport
from compute_provisioning_service.main import app
from compute_provisioning_service.services.definition_documents import DefinitionDocumentImporter

from .conftest import ADMIN_SIGNER, SERVICE_AUTHORITIES, STOREFRONT_SIGNER
from .test_host_pool_moves_api import _PLAIN_POOL, _RELAY_POOL, _bind_tunnel, _relay_and_pools


class _Recording(httpx.AsyncBaseTransport):
    """The in-process transport, recording each response's status and content type."""

    def __init__(self) -> None:
        self._inner = ASGITransport(app=app)
        self.responses: list[tuple[int, str]] = []

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        response = await self._inner.handle_async_request(request)
        self.responses.append((response.status_code, response.headers.get("content-type", "")))
        return response


@pytest_asyncio.fixture
async def recorded(client_and_queue) -> AsyncIterator[tuple[ComputeProvisioningClient, _Recording]]:
    """The administrator's typed client over a recording transport."""
    transport = _Recording()
    async with ComputeProvisioningClient(
        "http://test",
        signer=ADMIN_SIGNER,
        caller_role="admin",
        expected_authorities=SERVICE_AUTHORITIES,
        transport=transport,
    ) as client:
        yield client, transport


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


async def test_a_document_registers_its_hosts_and_a_reimport_changes_nothing(client_and_queue):
    clients, _ = client_and_queue
    await _relay_and_pools(clients)
    document = _document(_entry("kvm1", pool_id=_PLAIN_POOL), _entry("kvm2", ssh_host="10.0.0.2", enabled=False))

    first = await clients.family.import_host_definitions(document)
    second = await clients.family.import_host_definitions(document)

    assert (first.applied, first.diff.created) == (True, ["kvm1", "kvm2"])
    assert (second.applied, second.diff.unchanged, second.diff.updated) == (True, ["kvm1", "kvm2"], [])
    kvm1 = await clients.family.get_host("kvm1")
    kvm2 = await clients.family.get_host("kvm2")
    assert (kvm1.pool_id, kvm1.enabled, kvm1.connection.public["ssh_host"]) == (_PLAIN_POOL, True, "10.0.0.1")
    assert (kvm2.pool_id, kvm2.enabled) == (None, False)


async def test_an_explicit_import_reconciles_an_unchanged_document_and_records_no_digest(
    client_and_queue,
):
    """The scenario "An operator explicitly imports an unchanged document": the
    startup digest names this very document, and the import reconciles anyway,
    restoring what the API changed since, and leaves that digest as it was."""
    clients, _ = client_and_queue
    document = _document(_entry("kvm1"))
    await clients.family.import_host_definitions(document)
    await clients.family.update_host("kvm1", HostUpdate(enabled=False))
    digest = DefinitionDocumentImporter.digest_of(document)
    with _container_module.resolved_session_factory() as db, db.begin():
        db.add(DefinitionDocumentImport(document_kind="hosts", digest=digest))

    reconciled = await clients.family.import_host_definitions(document)

    assert (reconciled.applied, reconciled.diff.updated) == (True, ["kvm1"])
    assert (await clients.family.get_host("kvm1")).enabled is True
    with _container_module.resolved_session_factory() as db:
        assert db.get(DefinitionDocumentImport, "hosts").digest == digest


async def test_a_move_a_hook_refuses_answers_422_and_changes_no_host(client_and_queue, recorded):
    """The scenario "A pool-change hook refuses a move on import"."""
    clients, _ = client_and_queue
    admin, transport = recorded
    await _relay_and_pools(clients)
    await clients.family.import_host_definitions(_document(_entry("kvm1", pool_id=_RELAY_POOL)))
    _bind_tunnel()

    refused = await admin.import_host_definitions(
        _document(_entry("kvm2", ssh_host="10.0.0.2"), _entry("kvm1", pool_id=_PLAIN_POOL, ssh_host="10.0.0.99"))
    )

    assert transport.responses[-1][0] == 422
    assert refused.applied is False
    assert [(p.path, p.code) for p in refused.problems] == [("hosts[1].pool_id", "pool_change_refused")]
    assert "kvm1" in refused.problems[0].message
    kvm1 = await clients.family.get_host("kvm1")
    assert (kvm1.pool_id, kvm1.connection.public["ssh_host"]) == (_RELAY_POOL, "10.0.0.1")
    assert "kvm2" not in {host.host_id for host in (await clients.family.list_hosts(include_disabled=True)).hosts}


async def test_a_document_cannot_reach_a_host_through_its_pools_buyer_relay(client_and_queue, recorded):
    """The management-route rule holds for a document as for the host API: an
    entry placing a new host reached at its pool's relay's address, and one
    moving a placed host's connection onto it, are refused, and nothing applies."""
    clients, _ = client_and_queue
    admin, transport = recorded
    await _relay_and_pools(clients)
    await clients.family.import_host_definitions(_document(_entry("kvm1", pool_id=_RELAY_POOL)))

    refused = await admin.import_host_definitions(
        _document(
            _entry("kvm2", pool_id=_RELAY_POOL, ssh_host="203.0.113.9"),
            _entry("kvm1", pool_id=_RELAY_POOL, ssh_host="203.0.113.9"),
        )
    )

    assert transport.responses[-1][0] == 422
    assert refused.applied is False
    assert [(p.path, p.code) for p in refused.problems] == [
        ("hosts[0].pool_id", "pool_change_refused"),
        ("hosts[1].pool_id", "pool_change_refused"),
    ]
    assert all("site-a" in problem.message for problem in refused.problems)
    assert (await clients.family.get_host("kvm1")).connection.public["ssh_host"] == "10.0.0.1"
    assert "kvm2" not in {host.host_id for host in (await clients.family.list_hosts(include_disabled=True)).hosts}


async def test_a_hook_refusal_and_another_stored_state_problem_are_both_reported(
    client_and_queue, recorded
):
    """The scenario "A document has a hook refusal and another stored-state problem"."""
    clients, _ = client_and_queue
    admin, transport = recorded
    await _relay_and_pools(clients)
    await clients.family.import_host_definitions(_document(_entry("kvm1", pool_id=_RELAY_POOL)))
    _bind_tunnel()

    refused = await admin.import_host_definitions(
        _document(_entry("kvm2", pool_id="no-such-pool"), _entry("kvm1", pool_id=_PLAIN_POOL))
    )

    assert transport.responses[-1][0] == 422
    assert refused.applied is False
    assert [(p.path, p.code) for p in refused.problems] == [
        ("hosts[0].pool_id", "unknown_pool"),
        ("hosts[1].pool_id", "pool_change_refused"),
    ]
    assert (await clients.family.get_host("kvm1")).pool_id == _RELAY_POOL


async def test_a_quoted_port_refuses_the_whole_document(client_and_queue, recorded):
    """Validation is strict for the connection's own fields too: a quoted
    ``ssh_port`` is refused by the ``ssh`` codec at its entry's connection, and
    the document's valid entry is not applied either."""
    clients, _ = client_and_queue
    admin, transport = recorded
    quoted = _entry("kvm2", ssh_host="10.0.0.2")
    quoted["connection"]["public"]["ssh_port"] = "2222"

    refused = await admin.import_host_definitions(_document(_entry("kvm1"), quoted))

    assert transport.responses[-1][0] == 422
    assert refused.applied is False
    assert [(p.path, p.code) for p in refused.problems] == [("hosts[1].connection", "invalid_connection")]
    assert "ssh_port" in refused.problems[0].message
    hosts = {host.host_id for host in (await clients.family.list_hosts(include_disabled=True)).hosts}
    assert hosts.isdisjoint({"kvm1", "kvm2"})


async def test_a_validate_only_import_answers_200_with_its_plan_and_applies_nothing(
    client_and_queue, recorded
):
    """The scenario "An operator validates a document": the problems and the
    planned creations, updates, and unchanged hosts."""
    clients, _ = client_and_queue
    admin, transport = recorded
    await clients.family.import_host_definitions(_document(_entry("kvm1"), _entry("kvm4", ssh_host="10.0.0.4")))

    planned = await admin.import_host_definitions(
        _document(
            _entry("kvm1", enabled=False),
            _entry("kvm2", ssh_host="10.0.0.2"),
            _entry("kvm3", pool_id="none"),
            _entry("kvm4", ssh_host="10.0.0.4"),
        ),
        validate_only=True,
    )

    assert transport.responses[-1][0] == 200
    assert planned.applied is False
    assert (planned.diff.created, planned.diff.updated, planned.diff.unchanged) == (["kvm2"], ["kvm1"], ["kvm4"])
    assert [(p.path, p.code) for p in planned.problems] == [("hosts[2].pool_id", "unknown_pool")]
    assert (await clients.family.get_host("kvm1")).enabled is True
    hosts = {host.host_id for host in (await clients.family.list_hosts(include_disabled=True)).hosts}
    assert hosts == {"kvm1", "kvm4"}


async def test_the_export_answers_yaml(client_and_queue, recorded):
    admin, transport = recorded

    exported = await admin.export_hosts()

    assert isinstance(yaml.safe_load(exported)["hosts"], list)
    status, content_type = transport.responses[-1]
    assert (status, content_type.split(";")[0]) == (200, "application/yaml")


async def test_an_unedited_export_imports_as_every_host_unchanged(client_and_queue):
    """The scenario "An operator exports the registry and imports it unedited",
    with hosts registered through the API: their codec-filled defaults, a
    disabled host, a placed one, and one naming no pool."""
    clients, _ = client_and_queue
    await _relay_and_pools(clients)
    await clients.family.register_host(
        HostCreate(host_id="kvm1", pool_id=_PLAIN_POOL, connection=ssh_connection(ssh_host="10.0.0.1", key_path="/keys/id"))
    )
    await clients.family.register_host(
        HostCreate(
            host_id="bm1",
            enabled=False,
            connection=ssh_connection(ssh_host="10.0.0.5", ssh_port=2222, public_host="203.0.113.5", key_path="/keys/bm"),
        )
    )
    before = {host.host_id: host.updated_at for host in (await clients.family.list_hosts(include_disabled=True)).hosts}

    exported = await clients.family.export_hosts()
    reimported = await clients.family.import_host_definitions(exported)

    assert [entry["host_id"] for entry in yaml.safe_load(exported)["hosts"]] == ["bm1", "kvm1"]
    assert (reimported.applied, reimported.diff.unchanged) == (True, ["bm1", "kvm1"])
    assert (reimported.diff.created, reimported.diff.updated, reimported.not_named) == ([], [], [])
    after = {host.host_id: host.updated_at for host in (await clients.family.list_hosts(include_disabled=True)).hosts}
    assert after == before


async def test_neither_route_is_served_to_a_seller(client_and_queue):
    """Both routes are the administrator's: the typed client will not sign
    either for a seller."""
    async with ComputeProvisioningClient(
        "http://test",
        signer=STOREFRONT_SIGNER,
        caller_role="seller",
        expected_authorities=SERVICE_AUTHORITIES,
        transport=ASGITransport(app=app),
    ) as seller:
        with pytest.raises(ComputeProvisioningAuthenticationError):
            await seller.export_hosts()
        with pytest.raises(ComputeProvisioningAuthenticationError):
            await seller.import_host_definitions("hosts: []\n")


@pytest.mark.parametrize(
    ("method", "path", "body"),
    [
        ("GET", "/api/v1/hosts/definitions/export", None),
        ("POST", "/api/v1/hosts/definitions/import", {"yaml_text": "hosts: []\n", "validate_only": True}),
    ],
)
async def test_an_unauthenticated_request_to_either_route_is_refused(client_and_queue, method, path, body):
    """Rejection path: a request carrying no valid proof, built by hand since the
    typed client always signs. The placeholder header makes the harness's
    signing transport pass it through unsigned. Only the status is asserted."""
    async with httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as raw:
        response = await raw.request(method, path, json=body, headers={SIGNATURE_HEADER: "placeholder"})

    assert response.status_code == 401
