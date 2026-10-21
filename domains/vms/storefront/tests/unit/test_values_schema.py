"""The Helm values schemas carry the definition the typed models generate.

The definition keeps secret-marked and role-inapplicable fields out of an
agent's pass-through config and closes typed sections. These tests fail when
the committed schemas are stale, so a model or registration change cannot
reach a chart without regenerating them (``make helm-values-schema``). The
generator's own rules are tested with ``market_config.values_schema``; these
tests cover the definition the VM storefront's sections produce.
"""

from __future__ import annotations

import ast
import json
from pathlib import Path

import market_storefront.values_schema as module
import pytest
import tomllib
import yaml
from jsonschema import Draft7Validator
from market_config.values_schema import any_case, stale_files
from market_delivery import RESERVED_SECTION_KEYS
from market_storefront import values_schema
from market_storefront.utils.config import IdentityConfigDeclaration

REPO = Path(__file__).resolve().parents[5]
SCHEMAS = tuple(REPO / relative for relative in values_schema.SCHEMA_FILES)


@pytest.fixture(scope="module")
def definition() -> dict:
    return values_schema.storefront_config_definition()


def _field(node: dict, name: str):
    """A field's schema, keyed by the any-case pattern for ``name``."""
    return node["patternProperties"][any_case(name)]


def _section(definition: dict, name: str) -> dict:
    return _field(definition, name)


def _allowed(node: dict, *names: str) -> bool:
    patterns = {p for p, schema in node["patternProperties"].items() if schema is not False}
    return patterns == {any_case(n) for n in names}


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
    stale = stale_files(SCHEMAS, definition, name=values_schema.DEFINITION)
    assert not stale, (
        f"regenerate with `make helm-values-schema`: {[str(p) for p in stale]}"
    )


def test_the_command_checks_the_schema_files_the_storefront_names() -> None:
    """The command ``make helm-values-schema`` runs finds the files the
    storefront names under the repository root it is given."""
    assert values_schema.main(["check", "--root", str(REPO)]) == 0


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


def _overlaid(base, overlay):
    """``overlay`` merged into ``base`` as Helm merges values files: mappings
    key by key, a ``None`` removing the key, and anything else replaced."""
    if not isinstance(base, dict) or not isinstance(overlay, dict):
        return overlay
    merged = dict(base)
    for key, value in overlay.items():
        if value is None:
            merged.pop(key, None)
        else:
            merged[key] = _overlaid(base.get(key), value)
    return merged


def _shipped_identity_tables():
    """Every operator-written storefront ``[Identity]`` table this repository ships.

    The packaged ``settings.toml`` is left out: its empty principal is a
    placeholder the storefront refuses until an operator states one. Each Helm
    overlay's agents are read as the release renders them, merged into the
    umbrella's default agents, since an overlay states only what it changes.
    """
    toml_files = (
        "domains/vms/storefront/storefront.alice.toml",
        "domains/vms/storefront/storefront.bob.toml",
    )
    for name in toml_files:
        document = tomllib.loads((REPO / name).read_text())
        for key, value in document.items():
            if key.lower() == "identity":
                yield name, value
    umbrella = REPO / "helm" / "values.yaml"
    defaults = yaml.safe_load(umbrella.read_text())["storefront"]["agents"]
    releases = [(umbrella, defaults)]
    for path in [REPO / "helm" / "local-values.yaml", *sorted((REPO / "helm" / "fixtures").glob("*-values.yaml"))]:
        overlay = ((yaml.safe_load(path.read_text()) or {}).get("storefront") or {}).get("agents")
        if overlay:
            releases.append((path, _overlaid(defaults, overlay)))
    for path, agents in releases:
        for name, agent in agents.items():
            for key, value in (agent.get("config") or {}).items():
                if key.lower() == "identity":
                    yield f"{path.relative_to(REPO)}:{name}", value


def test_identity_declaration_accepts_every_shipped_identity_table() -> None:
    tables = list(_shipped_identity_tables())
    assert len(tables) >= 8, [source for source, _ in tables]
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
    assert registry["patternProperties"] == {any_case("auth"): False}


def test_settlement_is_closed_to_registered_mechanisms(definition) -> None:
    settlement = _section(definition, "Settlement")
    assert settlement["additionalProperties"] is False
    assert _allowed(
        settlement, "schema_version", "priority", "alkahest", "arkhai_payments", "contact"
    )


def test_payment_settings_are_closed_to_unknown_fields(definition) -> None:
    payments = _field(_section(definition, "Settlement"), "arkhai_payments")
    assert payments["additionalProperties"] is False
    assert _field(payments, "service_url") is not False


def test_definition_carries_no_defaults_references_markers_or_exact_names(definition) -> None:
    """Every field is an any-case pattern and nothing is required: the loader
    reads keys in any spelling, and presence is the storefront's startup check."""
    forbidden = {"default", "$ref", "$defs", "secret", "roles", "properties", "required"}
    for node in _walk(definition):
        if isinstance(node, dict):
            assert not forbidden & set(node), node


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


def test_delivery_states_the_settings_the_bare_metal_chart_does(definition) -> None:
    """``[Delivery]``'s own settings are stated by each storefront's generator,
    the delivery kit naming them only; they must agree. Read from the bare-metal
    chart's committed definition, which that storefront's own drift test holds to
    its code, so neither storefront imports the other."""
    assert set(module._DELIVERY_SETTINGS) == RESERVED_SECTION_KEYS
    bare_metal = json.loads(
        (REPO / "helm" / "charts" / "bare-metal-storefront" / "values.schema.json").read_text()
    )["definitions"][values_schema.DEFINITION]
    for name in RESERVED_SECTION_KEYS:
        assert _field(_delivery(definition), name) == _field(_section(bare_metal, "Delivery"), name), name


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
        if choice["patternProperties"].get("^sink$") == {"const": "webhook"}
    )
    assert _withheld(webhook, "url")


def test_a_table_named_for_a_sink_may_state_no_other(definition) -> None:
    webhook = _field(_delivery(definition), "webhook")
    assert webhook["patternProperties"]["^sink$"] == {"const": "webhook"}


def test_an_instance_of_an_unshipped_sink_stays_open(definition) -> None:
    (choices,) = _delivery(definition)["additionalProperties"]["dependencies"].values()
    unshipped = choices["anyOf"][-1]
    (pattern,) = unshipped["patternProperties"].values()
    assert set(pattern["not"]["enum"]) == {"apprise", "command", "file", "smtp", "webhook"}


def test_the_generator_names_no_sink() -> None:
    """Sinks reach the schema by discovery; importing one by name would make an
    optional plugin a hard dependency of the storefront."""

    tree = ast.parse(Path(module.__file__).read_text(encoding="utf-8"))
    imported = {
        node.module
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module
    } | {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    }
    assert not {name for name in imported if name.startswith("market_delivery.")}
    assert not {name for name in imported if name.startswith("market_delivery_apprise")}


def _committed_definition() -> dict:
    """The storefront configuration definition as the chart actually validates it."""
    schema = json.loads(SCHEMAS[1].read_text(encoding="utf-8"))
    return schema["definitions"][values_schema.DEFINITION]


def _accepts(delivery: dict) -> bool:

    validator = Draft7Validator(_committed_definition())
    return not list(validator.iter_errors({"Delivery": delivery}))


_SECRET_URL = "https://hooks.invalid/token-in-the-path"


@pytest.mark.parametrize(
    "instance",
    [
        {"sink": "webhook", "url": _SECRET_URL},
        {"sink": "webhook", "URL": _SECRET_URL},
        {"Sink": "webhook", "URL": _SECRET_URL},
        {"SINK": "webhook", "url": _SECRET_URL},
        {"sInK": "webhook", "Url": _SECRET_URL},
        {"sink": "smtp", "host": "mail", "sender": "s@x.invalid",
         "recipients": ["r@x.invalid"], "Password": "p"},
        {"Sink": "smtp", "host": "mail", "sender": "s@x.invalid",
         "recipients": ["r@x.invalid"], "password": "p"},
        {"sink": "apprise", "URLS": ["mailto://user:pass@mail.invalid"]},
        {"SINK": "apprise", "urls": ["mailto://user:pass@mail.invalid"]},
    ],
)
def test_a_secret_sink_setting_is_refused_however_either_key_is_spelled(instance) -> None:
    """A named instance's secret settings never reach the ConfigMap, whatever the
    spelling of ``sink`` or of the secret field."""
    assert not _accepts({"enabled": ["west"], "west": instance})


@pytest.mark.parametrize("spelling", ["Sink", "SINK", "sINK"])
def test_any_spelling_of_sink_but_its_own_is_refused(spelling) -> None:
    """The delivery kit reads only ``sink``; another spelling selects nothing and
    would escape typing, so the chart refuses it even with no secret beside it."""
    assert not _accepts({"enabled": ["audit"], "audit": {spelling: "file", "path": "/x"}})
    assert not _accepts({"enabled": ["file"], "file": {spelling: "file", "path": "/x"}})


def test_public_delivery_settings_are_accepted() -> None:
    assert _accepts(
        {
            "enabled": ["seller-mail", "audit"],
            "seller-mail": {
                "sink": "smtp",
                "host": "mailpit",
                "port": 1025,
                "sender": "storefront@seller.invalid",
                "recipients": ["sales@seller.invalid"],
            },
            "audit": {"sink": "file", "path": "/var/log/introductions.jsonl"},
            "origins": {"default": ["seller-mail", "audit"]},
        }
    )


def test_an_instance_of_an_unshipped_sink_stays_open_when_spelled_correctly() -> None:
    assert _accepts({"enabled": ["pager"], "pager": {"sink": "pager", "anything": 1}})

