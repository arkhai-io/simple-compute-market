"""The values-schema generator over a small set of models.

Each service's own definition, and its drift against the schema files it
writes, is tested by that service; these tests cover the generator's rules.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass

import pytest
from market_config import values_schema
from market_config.values_schema import any_case
from pydantic import BaseModel, ConfigDict, Field

ROLE = "seller"
NAME = "serviceConfig"


def _field(node: dict, name: str):
    """A field's schema, keyed by the any-case pattern for ``name``."""
    return node["patternProperties"][any_case(name)]


def _allowed(node: dict, *names: str) -> bool:
    patterns = {p for p, schema in node["patternProperties"].items() if schema is not False}
    return patterns == {any_case(n) for n in names}


def _withheld(node: dict, *names: str) -> bool:
    return all(_field(node, n) is False for n in names)


class Wallet(BaseModel):
    model_config = ConfigDict(extra="forbid")
    address: str = ""
    private_key: str = Field(default="", json_schema_extra={"secret": True})
    payer: str = Field(default="", json_schema_extra={"roles": ["buyer"]})


class FileSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")
    path: str


class HookSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")
    url: str = Field(json_schema_extra={"secret": True})
    sign: bool = False


@dataclass(frozen=True)
class Mechanism:
    config_key: str
    config_model: type[BaseModel]
    roles: frozenset[str]


class Escrow(BaseModel):
    model_config = ConfigDict(extra="forbid")
    enabled: bool = False
    api_key: str = Field(default="", json_schema_extra={"secret": True})


_SECTION_SETTINGS = {"enabled": {"type": "array", "items": {"type": "string"}}}


def _sinks() -> dict:
    return values_schema.sink_typed_section(
        {"file": FileSettings, "hook": HookSettings},
        sink_key="sink",
        section_fields=_SECTION_SETTINGS,
        role=ROLE,
    )


# --- publicizing -----------------------------------------------------------


def test_any_case_matches_every_spelling_and_nothing_else() -> None:
    pattern = re.compile(any_case("private_key"))
    for spelling in ("private_key", "Private_Key", "PRIVATE_KEY"):
        assert pattern.match(spelling)
    for other in ("private_keys", "privatekey", "x_private_key"):
        assert not pattern.match(other)


def test_other_spellings_matches_every_spelling_but_the_exact_one() -> None:
    pattern = re.compile(values_schema.other_spellings("sink"))
    for spelling in ("Sink", "SINK", "sInK"):
        assert pattern.match(spelling)
    assert not pattern.match("sink")
    assert not pattern.match("sinks")


def test_a_typed_section_is_closed_and_keys_its_fields_by_any_case_pattern() -> None:
    fragment = values_schema.model_fragment(Wallet, role=ROLE)

    assert fragment["additionalProperties"] is False
    assert _field(fragment, "address") == {"type": "string"}


def test_the_fragment_carries_no_defaults_references_markers_or_exact_names() -> None:
    class Outer(BaseModel):
        wallet: Wallet = Field(default_factory=Wallet)
        required_label: str

    forbidden = {"default", "$ref", "$defs", "secret", "roles", "properties", "required"}

    def walk(node):
        yield node
        if isinstance(node, dict):
            for value in node.values():
                yield from walk(value)
        elif isinstance(node, list):
            for item in node:
                yield from walk(item)

    for node in walk(values_schema.model_fragment(Outer, role=ROLE)):
        if isinstance(node, dict):
            assert not forbidden & set(node), node


def test_fields_differing_only_by_case_are_refused_at_generation() -> None:
    class Ambiguous(BaseModel):
        name: str = ""
        Name: str = ""

    with pytest.raises(ValueError, match="differ only by case"):
        values_schema.model_fragment(Ambiguous, role=ROLE)


def test_recursive_references_become_unconstrained() -> None:
    class Node(BaseModel):
        children: list[Node] = Field(default_factory=list)

    fragment = values_schema.model_fragment(Node, role=ROLE)

    assert _field(fragment, "children")["items"] == {}


# --- secret refusal ---------------------------------------------------------


def test_secret_and_role_inapplicable_fields_are_refused() -> None:
    fragment = values_schema.model_fragment(Wallet, role=ROLE)

    assert _allowed(fragment, "address")
    assert _withheld(fragment, "private_key", "payer")


def test_a_field_applies_to_the_roles_it_names() -> None:
    fragment = values_schema.model_fragment(Wallet, role="buyer")

    assert _allowed(fragment, "address", "payer")
    assert _withheld(fragment, "private_key")


def test_a_secret_marked_field_is_refused_wherever_it_nests() -> None:
    class Inner(BaseModel):
        model_config = ConfigDict(extra="forbid")
        token: str = Field(default="", json_schema_extra={"secret": True})
        label: str = ""

    class Outer(BaseModel):
        model_config = ConfigDict(extra="forbid")
        sinks: dict[str, Inner] = Field(default_factory=dict)

    fragment = values_schema.model_fragment(Outer, role=ROLE)

    inner = _field(fragment, "sinks")["additionalProperties"]
    assert _field(inner, "label") == {"type": "string"}
    assert _withheld(inner, "token")


def test_settlement_is_closed_to_registered_mechanisms_for_the_role() -> None:
    fragment = values_schema.settlement_fragment(
        [
            Mechanism("escrow", Escrow, frozenset({"seller", "buyer"})),
            Mechanism("payer_only", Escrow, frozenset({"buyer"})),
        ],
        role=ROLE,
    )

    assert fragment["additionalProperties"] is False
    assert _allowed(fragment, "schema_version", "priority", "escrow")
    assert _withheld(fragment, "payer_only")
    assert _withheld(_field(fragment, "escrow"), "api_key")


# --- sink typing --------------------------------------------------------------


def test_the_section_keeps_its_own_settings_and_types_each_sink_passed_in() -> None:
    section = _sinks()

    assert _field(section, "enabled") == _SECTION_SETTINGS["enabled"]
    for sink in ("file", "hook"):
        assert _field(section, sink)["additionalProperties"] is False
    assert _withheld(_field(section, "hook"), "url")


def test_a_table_named_for_a_sink_may_state_no_other() -> None:
    hook = _field(_sinks(), "hook")

    assert hook["patternProperties"]["^sink$"] == {"const": "hook"}


def test_a_named_instance_is_typed_by_the_sink_it_selects() -> None:
    (choices,) = _sinks()["additionalProperties"]["dependencies"].values()
    hook = next(
        choice
        for choice in choices["anyOf"]
        if choice["patternProperties"].get("^sink$") == {"const": "hook"}
    )

    assert _withheld(hook, "url")


def test_an_instance_of_an_untyped_sink_stays_open() -> None:
    (choices,) = _sinks()["additionalProperties"]["dependencies"].values()
    (pattern,) = choices["anyOf"][-1]["patternProperties"].values()

    assert pattern["not"]["enum"] == ["file", "hook"]
    assert any_case("pager") not in _sinks()["patternProperties"]


def test_the_sink_key_misspelled_is_refused_in_every_instance_table() -> None:
    section = _sinks()
    misspelled = values_schema.other_spellings("sink")

    assert section["additionalProperties"]["patternProperties"] == {misspelled: False}
    assert _field(section, "file")["patternProperties"][misspelled] is False


# --- retired keys -------------------------------------------------------------


def test_a_retired_key_is_refused_under_its_any_case_pattern() -> None:
    definition = values_schema.config_definition(
        {"wallet": values_schema.model_fragment(Wallet, role=ROLE)},
        retired=["old_interval"],
    )

    assert _field(definition, "old_interval") is False
    assert _field(definition, "wallet")["additionalProperties"] is False


def test_a_retired_key_in_an_untyped_section_leaves_the_rest_of_it_open() -> None:
    definition = values_schema.config_definition({}, retired=["capacity.old_setting"])

    capacity = _field(definition, "capacity")
    assert capacity == {
        "type": "object",
        "patternProperties": {any_case("old_setting"): False},
    }


def test_a_retired_key_in_a_typed_section_leaves_the_caller_fragment_unchanged() -> None:
    wallet = values_schema.model_fragment(Wallet, role=ROLE)
    before = json.loads(json.dumps(wallet))

    definition = values_schema.config_definition(
        {"wallet": wallet}, retired=["wallet.legacy"]
    )

    assert _withheld(_field(definition, "wallet"), "legacy")
    assert wallet == before


def test_a_retired_key_a_typed_section_still_has_is_refused_at_generation() -> None:
    with pytest.raises(ValueError, match="still a typed field"):
        values_schema.config_definition(
            {"wallet": values_schema.model_fragment(Wallet, role=ROLE)},
            retired=["wallet.address"],
        )


def test_a_retired_key_must_be_a_dotted_key_path() -> None:
    with pytest.raises(ValueError, match="not a dotted key path"):
        values_schema.config_definition({}, retired=["capacity..x"])


def test_a_retired_key_among_entries_typed_by_additional_properties_is_refused() -> None:
    """A pattern for the key would bypass the ``additionalProperties`` schema
    typing the entry, reopening the secret settings that typing refuses."""
    with pytest.raises(ValueError, match="additionalProperties"):
        values_schema.config_definition(
            {"delivery": _sinks()}, retired=["delivery.west.legacy"]
        )


def test_a_retired_key_in_a_typed_mapping_is_refused() -> None:
    class Inner(BaseModel):
        model_config = ConfigDict(extra="forbid")
        token: str = Field(default="", json_schema_extra={"secret": True})

    class Outer(BaseModel):
        model_config = ConfigDict(extra="forbid")
        entries: dict[str, Inner] = Field(default_factory=dict)

    with pytest.raises(ValueError, match="additionalProperties"):
        values_schema.config_definition(
            {"outer": values_schema.model_fragment(Outer, role=ROLE)},
            retired=["outer.entries.legacy"],
        )


def test_a_retired_key_under_a_combinator_is_refused() -> None:
    """An optional model is an ``anyOf``: its fields are out of a pattern's
    sight, so a retirement there could refuse a field the model still has."""

    class Inner(BaseModel):
        model_config = ConfigDict(extra="forbid")
        label: str = ""

    class Outer(BaseModel):
        model_config = ConfigDict(extra="forbid")
        inner: Inner | None = None

    with pytest.raises(ValueError, match="anyOf"):
        values_schema.config_definition(
            {"outer": values_schema.model_fragment(Outer, role=ROLE)},
            retired=["outer.inner.label"],
        )


@pytest.mark.parametrize(
    "retired", [["capacity.a", "capacity"], ["Capacity", "capacity.a"]]
)
def test_a_retired_key_under_another_retired_key_is_refused(retired) -> None:
    with pytest.raises(ValueError, match="lies under retired key"):
        values_schema.config_definition({}, retired=retired)


def test_without_retired_keys_the_definition_holds_only_its_sections() -> None:
    wallet = values_schema.model_fragment(Wallet, role=ROLE)

    assert values_schema.config_definition({"wallet": wallet}) == {
        "type": "object",
        "patternProperties": {any_case("wallet"): wallet},
    }


# --- null removal -------------------------------------------------------------


class Labelled(BaseModel):
    model_config = ConfigDict(extra="forbid")
    label: str | None = None


class Listed(BaseModel):
    model_config = ConfigDict(extra="forbid")
    entries: list[Wallet] = Field(default_factory=list)


def _removable() -> dict:
    """A definition with a typed section, an optional field, a list of models,
    a plugin section, settlement, and a retired key in an open section."""
    return values_schema.config_definition(
        {
            "wallet": values_schema.model_fragment(Wallet, role=ROLE),
            "labelled": values_schema.model_fragment(Labelled, role=ROLE),
            "listed": values_schema.model_fragment(Listed, role=ROLE),
            "delivery": _sinks(),
            "settlement": values_schema.settlement_fragment(
                [Mechanism("escrow", Escrow, frozenset({"seller"}))], role=ROLE
            ),
        },
        retired=["old_interval", "capacity.old_setting"],
    )


def test_a_key_accepts_null_wherever_it_is_accepted() -> None:
    definition = values_schema.accepting_null(_removable())
    wallet = _field(definition, "wallet")
    delivery = _field(definition, "delivery")

    # A typed section and a typed field keep their shape, with null among their types.
    assert wallet["type"] == ["object", "null"]
    assert wallet["additionalProperties"] is False
    assert _field(wallet, "address") == {"type": ["string", "null"]}
    # An open section, and a typed settlement mechanism within a closed root.
    assert _field(definition, "capacity")["type"] == ["object", "null"]
    assert _field(_field(definition, "settlement"), "escrow")["type"] == ["object", "null"]
    assert _field(_field(definition, "settlement"), "priority")["type"] == ["array", "null"]
    # A delivery instance named for its sink, and one typed by additionalProperties.
    assert _field(delivery, "hook")["type"] == ["object", "null"]
    assert delivery["additionalProperties"]["type"] == ["object", "null"]
    # A key whose schema accepts no type by name accepts null beside it.
    assert _field(delivery, "hook")["patternProperties"]["^sink$"] == {
        "anyOf": [{"const": "hook"}, {"type": "null"}]
    }


def test_a_key_inside_a_combinator_accepts_null() -> None:
    """A typed instance selected through ``dependencies`` reads null as absence,
    as the same instance named for its sink does."""
    definition = values_schema.accepting_null(_removable())
    (choices,) = _field(definition, "delivery")["additionalProperties"]["dependencies"].values()
    hook = next(
        choice
        for choice in choices["anyOf"]
        if {"const": "hook"} in choice["patternProperties"]["^sink$"].get("anyOf", ())
    )

    # The branch is the instance itself, not a key's value, so it is not widened.
    assert hook["type"] == "object"
    assert _field(hook, "sign") == {"type": ["boolean", "null"]}


def test_a_refused_key_stays_refused() -> None:
    definition = values_schema.accepting_null(_removable())
    delivery = _field(definition, "delivery")
    misspelled = values_schema.other_spellings("sink")

    assert _withheld(_field(definition, "wallet"), "private_key", "payer")
    assert _withheld(_field(delivery, "hook"), "url")
    assert _withheld(definition, "old_interval")
    assert _withheld(_field(definition, "capacity"), "old_setting")
    assert _withheld(_field(_field(definition, "settlement"), "escrow"), "api_key")
    assert delivery["additionalProperties"]["patternProperties"] == {misspelled: False}
    assert _field(delivery, "file")["patternProperties"][misspelled] is False


def test_a_field_already_accepting_null_is_unchanged() -> None:
    before = _field(_field(_removable(), "labelled"), "label")
    after = _field(_field(values_schema.accepting_null(_removable()), "labelled"), "label")

    assert before == {"anyOf": [{"type": "string"}, {"type": "null"}]}
    assert after == before


def test_a_list_element_stays_refused_as_null_while_its_keys_accept_it() -> None:
    after = values_schema.accepting_null(_removable())
    entries = _field(_field(after, "listed"), "entries")

    assert entries["type"] == ["array", "null"]
    assert entries["items"]["type"] == "object"
    assert entries["items"]["additionalProperties"] is False
    assert _field(entries["items"], "address") == {"type": ["string", "null"]}
    assert _withheld(entries["items"], "private_key")
    assert _field(_field(after, "delivery"), "enabled") == {
        "type": ["array", "null"],
        "items": {"type": "string"},
    }


def _keyed(**fields) -> dict:
    return {"type": "object", "patternProperties": dict(fields)}


@pytest.mark.parametrize(
    ("schema", "widened"),
    [
        (
            {"anyOf": [{"type": "string"}, {"type": "integer"}]},
            {"anyOf": [{"type": "string"}, {"type": "integer"}, {"type": "null"}]},
        ),
        (
            {"type": "string", "enum": ["a", "b"]},
            {"anyOf": [{"type": "string", "enum": ["a", "b"]}, {"type": "null"}]},
        ),
        (
            {"oneOf": [{"type": "string"}, {"type": "integer"}]},
            {"anyOf": [{"oneOf": [{"type": "string"}, {"type": "integer"}]}, {"type": "null"}]},
        ),
        (
            {"$ref": "#/definitions/other", "type": "object"},
            {"anyOf": [{"$ref": "#/definitions/other", "type": "object"}, {"type": "null"}]},
        ),
        ({"enum": ["a", None]}, {"enum": ["a", None]}),
        ({"not": {"type": "null"}}, {"anyOf": [{"not": {"type": "null"}}, {"type": "null"}]}),
        ({}, {}),
    ],
)
def test_a_key_schema_is_widened_in_the_form_its_keywords_allow(schema, widened) -> None:
    definition = values_schema.accepting_null({"type": "object", "properties": {"k": schema}})

    assert definition["properties"]["k"] == widened


def test_the_keys_a_not_or_if_types_accept_null_as_their_absence() -> None:
    """Under ``not`` and ``if`` a key's schema is checked only when the key is
    present, so widening it makes a ``null`` key read as an absent one there too."""
    definition = values_schema.accepting_null(
        {
            "type": "object",
            "not": _keyed(a={"const": 1}),
            "if": _keyed(b={"type": "string"}),
            "then": _keyed(c={"type": "integer"}),
        }
    )

    assert definition["not"]["patternProperties"]["a"] == {"anyOf": [{"const": 1}, {"type": "null"}]}
    assert definition["if"]["patternProperties"]["b"] == {"type": ["string", "null"]}
    assert definition["then"]["patternProperties"]["c"] == {"type": ["integer", "null"]}
    assert definition["not"]["type"] == "object"


def test_the_root_and_the_input_are_left_as_they_are() -> None:
    definition = _removable()
    before = json.loads(json.dumps(definition))

    accepted = values_schema.accepting_null(definition)

    assert definition == before
    assert accepted["type"] == "object"


def test_the_result_shares_nothing_with_its_input_or_another_result() -> None:
    definition = {
        "type": "object",
        "properties": {"k": {"const": 1}},
        "dependencies": {"a": ["b"]},
    }
    first = values_schema.accepting_null(definition)
    second = values_schema.accepting_null(definition)

    first["properties"]["k"]["anyOf"][1]["type"] = "string"
    first["dependencies"]["a"].append("c")

    assert second["properties"]["k"] == {"anyOf": [{"const": 1}, {"type": "null"}]}
    assert definition["dependencies"] == {"a": ["b"]}


# --- drift detection ----------------------------------------------------------


def _definition() -> dict:
    return values_schema.config_definition(
        {"wallet": values_schema.model_fragment(Wallet, role=ROLE)}
    )


def test_render_replaces_only_its_own_definition() -> None:
    schema = {"type": "object", "definitions": {"other": {"type": "string"}}}

    rendered = json.loads(values_schema.render(schema, _definition(), name=NAME))

    assert rendered["definitions"] == {"other": {"type": "string"}, NAME: _definition()}


def test_stale_files_names_each_file_whose_definition_differs(tmp_path) -> None:
    current = tmp_path / "current.json"
    stale = tmp_path / "stale.json"
    current.write_text(values_schema.render({"type": "object"}, _definition(), name=NAME))
    stale.write_text(json.dumps({"definitions": {NAME: {}}}))

    assert values_schema.stale_files([current, stale], _definition(), name=NAME) == [stale]


def _main(root, action: str) -> int:
    return values_schema.main(
        [action, "--root", str(root)],
        build_definition=_definition,
        name=NAME,
        schema_files=("charts/a/values.schema.json", "values.schema.json"),
        description="test",
    )


def test_write_then_check_round_trips_the_schema_files_under_the_root(tmp_path) -> None:
    for relative in ("charts/a/values.schema.json", "values.schema.json"):
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"type": "object", "definitions": {NAME: {}}}))

    assert _main(tmp_path, "check") == 1
    assert _main(tmp_path, "write") == 0
    assert _main(tmp_path, "check") == 0
    written = json.loads((tmp_path / "values.schema.json").read_text())
    assert written["definitions"][NAME] == _definition()


def test_a_missing_schema_file_is_named_with_the_root(tmp_path, capsys) -> None:
    assert _main(tmp_path, "check") == 2
    assert _main(tmp_path, "write") == 2

    error = capsys.readouterr().err
    assert str(tmp_path / "values.schema.json") in error
    assert f"under the root {tmp_path}" in error
