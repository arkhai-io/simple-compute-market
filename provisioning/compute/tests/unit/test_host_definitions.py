"""A host definitions document's structural validation, and its rendering.

Structural validation reads nothing stored, so it is proved here, one problem
at a time and several together, each reported at its location.
"""

from __future__ import annotations

import pytest
import yaml
from compute_provisioning_contracts import HostDefinition

from compute_provisioning.hosts.definitions import parse_host_definitions, render_host_definitions

_CONNECTION = "{kind: ssh, version: 2, public: {ssh_host: 192.0.2.5, key_path: /keys/id}}"


def _problems(yaml_text: str) -> list[tuple[str, str]]:
    _, problems = parse_host_definitions(yaml_text)
    return [(problem.path, problem.code) for problem in problems]


def test_a_valid_document_yields_its_entries_in_order() -> None:
    definitions, problems = parse_host_definitions(
        f"hosts:\n"
        f"  - {{host_id: kvm2, pool_id: vm-default, enabled: false, connection: {_CONNECTION}}}\n"
        f"  - {{host_id: kvm1, connection: {_CONNECTION}}}\n"
    )

    assert problems == ()
    assert [(d.host_id, d.pool_id, d.enabled) for d in definitions] == [
        ("kvm2", "vm-default", False),
        ("kvm1", None, True),
    ]


def test_an_empty_hosts_list_is_valid_and_a_null_pool_is_an_omitted_one() -> None:
    assert parse_host_definitions("hosts: []\n") == ((), ())
    definitions, problems = parse_host_definitions(
        f"hosts: [{{host_id: kvm1, pool_id: null, connection: {_CONNECTION}}}]\n"
    )
    assert problems == ()
    assert definitions[0].pool_id is None


@pytest.mark.parametrize(
    ("document", "expected"),
    [
        ("hosts: [unclosed\n", [("$", "invalid_yaml")]),
        ("", [("$", "invalid_type")]),
        ("- host_id: kvm1\n", [("$", "invalid_type")]),
        ("other: 1\n", [("other", "unknown_field"), ("hosts", "required_field")]),
        ("hosts: {host_id: kvm1}\n", [("hosts", "invalid_type")]),
        ("hosts: [kvm1]\n", [("hosts[0]", "invalid_type")]),
        (f"hosts: [{{connection: {_CONNECTION}}}]\n", [("hosts[0].host_id", "required_field")]),
        ("hosts: [{host_id: kvm1}]\n", [("hosts[0].connection", "required_field")]),
        (
            "hosts: [{host_id: kvm1, connection: {version: 2}}]\n",
            [("hosts[0].connection.kind", "required_field")],
        ),
        (
            "hosts: [{host_id: kvm1, connection: {kind: ssh}}]\n",
            [("hosts[0].connection.version", "required_field")],
        ),
        (
            "hosts: [{host_id: kvm1, connection: {kind: ssh, version: '2'}}]\n",
            [("hosts[0].connection.version", "invalid_type")],
        ),
        (
            "hosts: [{host_id: kvm1, connection: {kind: ssh, version: 0}}]\n",
            [("hosts[0].connection.version", "invalid_value")],
        ),
        (
            f"hosts: [{{host_id: kvm1, enabled: null, connection: {_CONNECTION}}}]\n",
            [("hosts[0].enabled", "invalid_type")],
        ),
        (
            f"hosts: [{{host_id: kvm1, enabled: 'true', connection: {_CONNECTION}}}]\n",
            [("hosts[0].enabled", "invalid_type")],
        ),
        (
            f"hosts: [{{host_id: 7, connection: {_CONNECTION}}}]\n",
            [("hosts[0].host_id", "invalid_type")],
        ),
        (
            f"hosts: [{{host_id: kvm1, rack: r1, connection: {_CONNECTION}}}]\n",
            [("hosts[0].rack", "unknown_field")],
        ),
        (
            "hosts: [{host_id: kvm1, connection: {kind: ssh, version: 2, port: 22}}]\n",
            [("hosts[0].connection.port", "unknown_field")],
        ),
        (
            f"hosts:\n  - {{host_id: kvm1, connection: {_CONNECTION}}}\n"
            f"  - {{host_id: kvm1, connection: {_CONNECTION}}}\n",
            [("hosts[1].host_id", "duplicate_host_id")],
        ),
    ],
)
def test_each_structural_problem_is_reported_at_its_location(document, expected) -> None:
    assert _problems(document) == expected


def test_an_entry_carrying_key_material_is_refused_at_its_location() -> None:
    """The physical-provisioning scenario "An entry carries key material": the
    document names a key and never carries one."""
    document = (
        "hosts:\n"
        "  - host_id: kvm1\n"
        "    connection:\n"
        "      kind: ssh\n"
        "      version: 2\n"
        "      public: {ssh_host: 192.0.2.5}\n"
        "      secrets: {private_key: not-a-real-key}\n"
    )

    definitions, problems = parse_host_definitions(document)

    assert definitions == ()
    assert [(p.path, p.code) for p in problems] == [("hosts[0].connection.secrets", "connection_secrets")]
    assert "not-a-real-key" not in problems[0].message


def test_a_document_with_no_hosts_list_is_refused() -> None:
    """The physical-provisioning scenario "A document has no hosts list":
    empty, or no ``hosts`` key."""
    for document in ("", "# nothing here\n", "{}\n"):
        definitions, problems = parse_host_definitions(document)
        assert definitions == ()
        assert problems


def test_several_structural_problems_are_all_reported() -> None:
    """The physical-provisioning scenario "A document has several structural
    problems": an unknown
    field, an entry with no connection, and two entries naming one host."""
    document = (
        "hosts:\n"
        f"  - {{host_id: kvm1, rack: r1, connection: {_CONNECTION}}}\n"
        "  - {host_id: kvm2}\n"
        f"  - {{host_id: kvm1, connection: {_CONNECTION}}}\n"
    )

    assert _problems(document) == [
        ("hosts[0].rack", "unknown_field"),
        ("hosts[1].connection", "required_field"),
        ("hosts[2].host_id", "duplicate_host_id"),
    ]


def test_a_rendered_document_states_pool_and_enabled_and_parses_back() -> None:
    definitions = (
        HostDefinition.model_validate(
            {
                "host_id": "bm1",
                "enabled": False,
                "connection": {
                    "kind": "ssh",
                    "version": 2,
                    "public": {"ssh_host": "192.0.2.7", "key_path": None, "ssh_port": 22},
                },
            }
        ),
        HostDefinition.model_validate(
            {
                "host_id": "kvm1",
                "pool_id": "vm-default",
                "connection": {"kind": "ssh", "version": 2, "public": {"ssh_host": "192.0.2.5"}},
            }
        ),
    )

    rendered = render_host_definitions(definitions)

    assert yaml.safe_load(rendered) == {
        "hosts": [
            {
                "host_id": "bm1",
                "pool_id": None,
                "enabled": False,
                "connection": {"kind": "ssh", "version": 2, "public": {"ssh_host": "192.0.2.7", "ssh_port": 22}},
            },
            {
                "host_id": "kvm1",
                "pool_id": "vm-default",
                "enabled": True,
                "connection": {"kind": "ssh", "version": 2, "public": {"ssh_host": "192.0.2.5"}},
            },
        ]
    }
    reparsed, problems = parse_host_definitions(rendered)
    assert problems == ()
    assert [d.host_id for d in reparsed] == ["bm1", "kvm1"]
