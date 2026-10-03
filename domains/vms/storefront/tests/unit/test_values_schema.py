"""The Helm values schemas carry the definition the typed models generate.

The definition keeps secret-marked and role-inapplicable fields out of an
agent's pass-through config and closes typed sections. These tests fail when
the committed schemas are stale, so a model or registration change cannot
reach a chart without regenerating them (``make helm-values-schema``).
"""

from __future__ import annotations

import json
import re
import tomllib
from pathlib import Path

import pytest
import yaml
from pydantic import BaseModel, ConfigDict, Field

from market_storefront import values_schema
from market_storefront.utils.config import IdentityConfigDeclaration

REPO = Path(__file__).resolve().parents[5]
SCHEMAS = (
    REPO / "helm" / "values.schema.json",
    REPO / "helm" / "charts" / "storefront" / "values.schema.json",
)


@pytest.fixture(scope="module")
def definition() -> dict:
    return values_schema.storefront_config_definition()


def _field(node: dict, name: str):
    """A field's schema, keyed by the any-case pattern for ``name``."""
    return node["patternProperties"][values_schema.any_case(name)]


def _section(definition: dict, name: str) -> dict:
    return _field(definition, name)


def _allowed(node: dict, *names: str) -> bool:
    patterns = {p for p, schema in node["patternProperties"].items() if schema is not False}
    return patterns == {values_schema.any_case(n) for n in names}


def _withheld(node: dict, *names: str) -> bool:
    return all(_field(node, n) is False for n in names)


def _walk(node):
    yield node
    if isinstance(node, dict):
        for value in node.values():
            yield from _walk(value)
    elif isinstance(node, list):
        for item in node:
            yield from _walk(item)


def test_committed_values_schemas_carry_the_generated_definition(definition) -> None:
    stale = values_schema.stale_files(SCHEMAS, definition)
    assert not stale, (
        f"regenerate with `make helm-values-schema`: {[str(p) for p in stale]}"
    )


def test_any_case_matches_every_spelling_and_nothing_else() -> None:
    pattern = re.compile(values_schema.any_case("private_key"))
    for spelling in ("private_key", "Private_Key", "PRIVATE_KEY"):
        assert pattern.match(spelling)
    for other in ("private_keys", "privatekey", "x_private_key"):
        assert not pattern.match(other)


def test_wallet_private_key_is_refused_and_the_section_closed(definition) -> None:
    wallet = _section(definition, "Wallet")
    assert wallet["additionalProperties"] is False
    assert _allowed(wallet, "address", "ssh_public_key")
    assert _withheld(wallet, "private_key")


def test_identity_is_closed_to_its_public_keys_at_every_level(definition) -> None:
    """Private identity material arrives only through the credential Secret,
    so every key the declaration does not name is refused, in any spelling."""
    identity = _section(definition, "Identity")
    assert identity["additionalProperties"] is False
    assert _allowed(identity, "principal", "administrators", "service_peers")
    administrator = _field(identity, "administrators")["additionalProperties"]
    peer = _field(identity, "service_peers")["additionalProperties"]
    assert administrator["additionalProperties"] is False
    assert _allowed(administrator, "principals")
    assert peer["additionalProperties"] is False
    assert _allowed(peer, "role", "site_id", "principals")
    for principal in (
        _field(administrator, "principals")["items"],
        _field(peer, "principals")["items"],
    ):
        assert principal["additionalProperties"] is False
        assert _allowed(principal, "scheme", "identifier")


def _shipped_identity_tables():
    """Every operator-written storefront ``[Identity]`` table this repository ships.

    The packaged ``settings.toml`` is left out: its empty principal is a
    placeholder the storefront refuses until an operator states one.
    """
    toml_files = (
        "config.stripe-fiat-ed25519.toml",
        "domains/vms/storefront/storefront.alice.toml",
        "domains/vms/storefront/storefront.bob.toml",
        "e2e-tests/config/hosted-storefront.toml",
    )
    for name in toml_files:
        document = tomllib.loads((REPO / name).read_text())
        for key, value in document.items():
            if key.lower() == "identity":
                yield name, value
    values_files = [
        REPO / "helm" / "values.yaml",
        REPO / "helm" / "charts" / "storefront" / "values.yaml",
        *sorted((REPO / "helm" / "fixtures").glob("*-values.yaml")),
    ]
    for path in values_files:
        document = yaml.safe_load(path.read_text())
        if not isinstance(document, dict):
            continue
        agents = (document.get("storefront") or {}).get("agents") or document.get("agents") or []
        for agent in agents:
            for key, value in (agent.get("config") or {}).items():
                if key.lower() == "identity":
                    yield f"{path.relative_to(REPO)}:{agent.get('name')}", value


def test_identity_declaration_accepts_every_shipped_identity_table() -> None:
    tables = list(_shipped_identity_tables())
    assert len(tables) >= 8
    for source, table in tables:
        # Configuration is text, so validate as JSON: strict models take enum
        # values as their string form there, as the storefront's parsers do.
        try:
            IdentityConfigDeclaration.model_validate_json(json.dumps(table))
        except ValueError as exc:
            pytest.fail(f"{source}: {exc}")


def test_registry_auth_is_refused_and_the_section_left_open(definition) -> None:
    registry = _section(definition, "registry")
    assert registry["additionalProperties"] is True
    assert registry["patternProperties"] == {values_schema.any_case("auth"): False}


def test_settlement_is_closed_to_registered_mechanisms(definition) -> None:
    settlement = _section(definition, "Settlement")
    assert settlement["additionalProperties"] is False
    assert _allowed(
        settlement, "schema_version", "priority", "alkahest", "stripe", "contact"
    )


def test_buyer_only_stripe_fields_are_refused_for_the_seller(definition) -> None:
    stripe = _field(_section(definition, "Settlement"), "stripe")
    assert stripe["additionalProperties"] is False
    assert _withheld(stripe, "off_session_policy", "authorization_journal_path")
    assert _field(stripe, "account_ref") is not False


def test_definition_carries_no_defaults_references_markers_or_exact_names(definition) -> None:
    """Every field is an any-case pattern and nothing is required: the loader
    reads keys in any spelling, and presence is the storefront's startup check."""
    forbidden = {"default", "$ref", "$defs", "secret", "roles", "properties", "required"}
    for node in _walk(definition):
        if isinstance(node, dict):
            assert not forbidden & set(node), node


def test_fields_differing_only_by_case_are_refused_at_generation() -> None:
    class Ambiguous(BaseModel):
        name: str = ""
        Name: str = ""

    with pytest.raises(ValueError, match="differ only by case"):
        values_schema.model_fragment(Ambiguous)


def test_a_secret_marked_field_is_refused_wherever_it_nests() -> None:
    class Inner(BaseModel):
        model_config = ConfigDict(extra="forbid")
        token: str = Field(default="", json_schema_extra={"secret": True})
        label: str = ""

    class Outer(BaseModel):
        model_config = ConfigDict(extra="forbid")
        sinks: dict[str, Inner] = Field(default_factory=dict)
        buyer_only: str = Field(default="", json_schema_extra={"roles": ["buyer"]})

    fragment = values_schema.model_fragment(Outer)

    assert _withheld(fragment, "buyer_only")
    inner = _field(fragment, "sinks")["additionalProperties"]
    assert _field(inner, "label") == {"type": "string"}
    assert _withheld(inner, "token")


def test_recursive_references_become_unconstrained() -> None:
    class Node(BaseModel):
        children: list[Node] = Field(default_factory=list)

    fragment = values_schema.model_fragment(Node)

    assert _field(fragment, "children")["items"] == {}


def test_check_reports_a_stale_schema(tmp_path, definition) -> None:
    current = tmp_path / "current.json"
    stale = tmp_path / "stale.json"
    current.write_text(values_schema.render({"type": "object"}, definition))
    stale.write_text(json.dumps({"definitions": {values_schema.DEFINITION: {}}}))

    assert values_schema.main(["check", str(current)]) == 0
    assert values_schema.main(["check", str(current), str(stale)]) == 1


def test_contact_fields_are_public_configuration(definition) -> None:
    contact = _field(_section(definition, "Settlement"), "contact")
    payload = _field(contact, "contact_payload")
    assert payload is not False
    origins = _field(contact, "origins")
    keyed = origins["additionalProperties"]
    assert _field(keyed, "contact_payload") is not False


def _delivery(definition: dict) -> dict:
    return _section(definition, "Delivery")


def test_delivery_keeps_its_own_settings_and_types_shipped_sinks(definition) -> None:
    delivery = _delivery(definition)
    for name in ("enabled", "timeout_seconds", "origins"):
        assert _field(delivery, name) is not False
    for sink in ("apprise", "command", "file", "smtp", "webhook"):
        assert _field(delivery, sink)["additionalProperties"] is False


def test_secret_sink_settings_are_refused_however_the_instance_is_named(definition) -> None:
    delivery = _delivery(definition)
    assert _withheld(_field(delivery, "webhook"), "url", "headers")
    assert _withheld(_field(delivery, "smtp"), "password")
    assert _withheld(_field(delivery, "apprise"), "urls")
    assert _field(_field(delivery, "smtp"), "host") is not False
    (choices,) = delivery["additionalProperties"]["dependencies"].values()
    webhook = next(
        choice
        for choice in choices["anyOf"]
        if _field(choice, "sink") == {"const": "webhook"}
    )
    assert _withheld(webhook, "url")


def test_a_table_named_for_a_sink_may_state_no_other(definition) -> None:
    assert _field(_field(_delivery(definition), "webhook"), "sink") == {"const": "webhook"}


def test_an_instance_of_an_unshipped_sink_stays_open(definition) -> None:
    (choices,) = _delivery(definition)["additionalProperties"]["dependencies"].values()
    unshipped = choices["anyOf"][-1]
    (pattern,) = unshipped["patternProperties"].values()
    assert set(pattern["not"]["enum"]) == {"apprise", "command", "file", "smtp", "webhook"}
