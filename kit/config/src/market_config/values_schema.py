"""Generate a Helm values-schema definition for a service's pass-through ``config``.

A chart that passes a service's configuration through unchanged has its values
schema as the one place a secret placed there is stopped before it reaches a
ConfigMap. The service's typed configuration models already say which fields
are secret (``json_schema_extra={"secret": True}``) and which roles a field
applies to (``"roles"``); this module turns their JSON Schema into one
definition that:

* refuses every secret-marked field, and every field that does not apply to the
  role, in any spelling of its name;
* accepts every other field in any spelling, as a Dynaconf loader does;
* closes each typed section, so a field its model does not have is refused too;
* carries no defaults and no required fields, and leaves the configuration and
  every untyped section open;
* types a plugin section, such as ``[Delivery]``, instance by instance from the
  settings models the service passes in, so a secret plugin setting is refused
  like any other;
* refuses each retired key the service names, in any spelling;
* once the service passes it through :func:`accepting_null`, accepts ``null``
  wherever it accepts a key, at any depth, because a values file's ``null``
  removes the key it names, while a refused key stays refused as ``null`` and a
  ``null`` list element stays refused.

A service keeps only what is its own: the sections it types, the plugins it
installs, the keys it has retired, and the schema files it writes: those of the
charts that deploy it, never another service's. See
openspec/specs/deployment-state/spec.md, "Generated configuration has one source
of truth".
"""

from __future__ import annotations

import argparse
import copy
import json
import re
import sys
from collections.abc import Callable, Collection, Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any, Protocol

from pydantic import BaseModel

# Annotation keywords that describe a value rather than constrain it. Defaults
# are dropped because the service, not the chart, owns them.
_ANNOTATIONS = frozenset(
    {"default", "title", "description", "examples", "roles", "secret", "never_published"}
)


class SettlementSection(Protocol):
    """What the generator reads of one registered settlement mechanism."""

    @property
    def config_key(self) -> str: ...

    @property
    def config_model(self) -> type[BaseModel]: ...

    @property
    def roles(self) -> Collection[str]: ...


def any_case(name: str) -> str:
    """Return an anchored pattern matching ``name`` in any letter case.

    Dynaconf matches configuration keys case-insensitively, so a refusal keyed
    by one spelling would let another through. Character classes are used
    rather than an inline flag so the pattern means the same to every JSON
    Schema validator Helm has shipped.
    """
    parts = [
        f"[{char.lower()}{char.upper()}]" if char.isalpha() else re.escape(char)
        for char in name
    ]
    return "^" + "".join(parts) + "$"


def other_spellings(name: str) -> str:
    """An anchored pattern for every letter-case spelling of ``name`` but itself.

    Written out because the validators Helm ships use Go regular expressions,
    which have no look-ahead to say "any case except this one".
    """
    spellings = {""}
    for char in name:
        spellings = {
            prefix + variant
            for prefix in spellings
            for variant in {char.lower(), char.upper()}
        }
    spellings.discard(name)
    return "^(?:" + "|".join(sorted(spellings)) + ")$"


def any_case_fields(fields: Mapping[str, Any]) -> dict[str, Any]:
    """Key ``fields`` by :func:`any_case` patterns, refusing case-only collisions."""
    patterns: dict[str, Any] = {}
    seen: dict[str, str] = {}
    for name, schema in fields.items():
        folded = name.lower()
        if folded in seen:
            raise ValueError(
                f"fields {seen[folded]!r} and {name!r} differ only by case; "
                "a case-insensitive loader cannot tell them apart"
            )
        seen[folded] = name
        patterns[any_case(name)] = schema
    return patterns


def _inline(node: Any, defs: Mapping[str, Any], expanding: tuple[str, ...]) -> Any:
    """Replace local ``$ref`` pointers with their targets.

    Inlining keeps the definition free of draft-specific ``$defs`` handling. A
    reference back into a definition already being expanded is recursive
    (``JsonValue``) and becomes an unconstrained schema.
    """
    if isinstance(node, Mapping):
        ref = node.get("$ref")
        if isinstance(ref, str) and ref.startswith("#/$defs/"):
            name = ref.removeprefix("#/$defs/")
            if name in expanding:
                return {}
            target = _inline(defs[name], defs, (*expanding, name))
            siblings = {k: v for k, v in node.items() if k != "$ref"}
            return {**target, **_inline(siblings, defs, expanding)}
        return {key: _inline(value, defs, expanding) for key, value in node.items()}
    if isinstance(node, list):
        return [_inline(item, defs, expanding) for item in node]
    return node


def _is_withheld(field: Any, role: str) -> bool:
    if not isinstance(field, Mapping):
        return False
    if field.get("secret") is True:
        return True
    roles = field.get("roles")
    return isinstance(roles, list) and role not in roles


def _publicize(node: Any, role: str) -> Any:
    """Refuse withheld fields, match the rest in any spelling, recursively.

    Every field becomes an :func:`any_case` pattern, allowed or refused, because
    a Dynaconf loader reads ``Priority`` as ``priority``; a closed section keeps
    ``additionalProperties: false``, so a field the model lacks is still refused
    in any spelling. ``required`` is dropped: whether a field is present is the
    service's startup check, and an exact-name requirement would refuse a
    correctly spelled-differently key.
    """
    if isinstance(node, list):
        return [_publicize(item, role) for item in node]
    if not isinstance(node, Mapping):
        return node
    result: dict[str, Any] = {}
    fields: dict[str, Any] = {}
    for key, value in node.items():
        if key in _ANNOTATIONS or key == "required":
            continue
        if key == "properties" and isinstance(value, Mapping):
            for name, field in value.items():
                fields[name] = False if _is_withheld(field, role) else _publicize(field, role)
        else:
            result[key] = _publicize(value, role)
    if fields:
        result["patternProperties"] = {
            **dict(result.get("patternProperties", {})),
            **any_case_fields(fields),
        }
    return result


def model_fragment(model: type[BaseModel], *, role: str) -> dict[str, Any]:
    """Return ``model``'s values-schema fragment for ``role``."""
    schema = model.model_json_schema(mode="validation")
    defs = schema.pop("$defs", {})
    return _publicize(_inline(schema, defs, ()), role)


def settlement_fragment(
    mechanisms: Iterable[SettlementSection], *, role: str
) -> dict[str, Any]:
    """The ``Settlement`` root, closed to the mechanisms the service registers.

    The settlement runtime refuses any other root key, so closing it here
    refuses nothing the service would accept. A mechanism that does not apply
    to ``role`` is refused whole.
    """
    fields: dict[str, Any] = {
        "schema_version": {"type": "integer"},
        "priority": {"type": "array", "items": {"type": "string"}},
    }
    for mechanism in mechanisms:
        fields[mechanism.config_key] = (
            model_fragment(mechanism.config_model, role=role)
            if role in mechanism.roles
            else False
        )
    return {
        "type": "object",
        "additionalProperties": False,
        "patternProperties": any_case_fields(fields),
    }


def sink_typed_section(
    sinks: Mapping[str, type[BaseModel]],
    *,
    sink_key: str,
    section_fields: Mapping[str, Any],
    role: str,
) -> dict[str, Any]:
    """A plugin section whose instance tables are typed by the plugin they use.

    ``sinks`` maps each typed plugin's name to its settings model, as the
    service discovers them among those it installs; ``sink_key`` is the
    instance-table key naming the plugin an instance uses, and an instance
    naming none uses the plugin of its own name. ``section_fields`` are the
    section's own settings, by name, as schema fragments.

    A table named for a typed plugin is that plugin, and may state no other.
    Any other table is an instance whose ``sink_key`` selects its settings; one
    naming a plugin with no declared model is left open, since its settings are
    not known here. ``sink_key`` spelled any way but exactly is refused in every
    instance table: the plugin's loader reads no other spelling, so such an
    instance selects nothing and, unrefused, would escape the typing that keeps
    its secret settings out of public configuration.
    """
    misspelled = {other_spellings(sink_key): False}

    def instance(name: str, model: type[BaseModel]) -> dict[str, Any]:
        fragment = model_fragment(model, role=role)
        patterns = dict(fragment.get("patternProperties", {}))
        patterns.pop(any_case(sink_key), None)
        patterns[f"^{re.escape(sink_key)}$"] = {"const": name}
        patterns.update(misspelled)
        fragment["patternProperties"] = patterns
        return fragment

    instances = {name: instance(name, model) for name, model in sorted(sinks.items())}
    # Each typed instance fragment already pins the sink key to its own name.
    selected = list(instances.values())
    untyped = {
        "patternProperties": {
            f"^{re.escape(sink_key)}$": {"not": {"enum": sorted(sinks)}}
        }
    }
    return {
        "type": "object",
        "patternProperties": {
            **any_case_fields(section_fields),
            **{any_case(name): fragment for name, fragment in instances.items()},
        },
        "additionalProperties": {
            "type": "object",
            "patternProperties": dict(misspelled),
            "dependencies": {sink_key: {"anyOf": [*selected, untyped]}},
        },
    }


# Keywords whose subschemas a key is also validated against. A field reached
# through one is invisible to a pattern added beside it, so a retirement there
# could neither see a typed field it would refuse nor know what it overrides.
_COMBINATORS = ("allOf", "anyOf", "oneOf", "not", "if", "then", "else", "dependencies")


def _retire(node: dict[str, Any], path: Sequence[str], dotted: str) -> None:
    """Refuse ``path`` under ``node``, declaring each section on the way an object.

    A key matching a ``patternProperties`` entry is not checked against the
    node's ``additionalProperties``, and a pattern beside a combinator cannot
    see the fields its subschemas type. A retired key among entries an
    ``additionalProperties`` schema types, or under a combinator, is therefore
    refused at generation, to be retired in the model that types it instead.
    """
    head, *rest = path
    combinators = sorted(key for key in _COMBINATORS if key in node)
    if combinators:
        raise ValueError(
            f"retired key {dotted!r} lies under {', '.join(combinators)}, whose "
            "subschemas may type it; retire it in the model instead"
        )
    patterns = node.setdefault("patternProperties", {})
    pattern = any_case(head)
    existing = patterns.get(pattern)
    if existing is None and isinstance(node.get("additionalProperties"), Mapping):
        raise ValueError(
            f"retired key {dotted!r} lies among entries typed by "
            "additionalProperties, which a pattern for it would bypass; "
            "retire it in the model instead"
        )
    if not rest:
        if existing is not None and existing is not False:
            raise ValueError(f"retired key {dotted!r} is still a typed field")
        patterns[pattern] = False
        return
    if existing is False:
        raise ValueError(f"retired key {dotted!r} lies under a refused key")
    if existing is None:
        existing = {"type": "object"}
        patterns[pattern] = existing
    _retire(existing, rest, dotted)


def _nested_retirements(retired: Sequence[str]) -> list[tuple[str, str]]:
    """Each pair of retired keys where the first lies under the second."""
    folded = [(dotted, tuple(dotted.lower().split("."))) for dotted in retired]
    return [
        (inner, outer)
        for inner, inner_path in folded
        for outer, outer_path in folded
        if len(outer_path) < len(inner_path)
        and inner_path[: len(outer_path)] == outer_path
    ]


def config_definition(
    sections: Mapping[str, Any], *, retired: Iterable[str] = ()
) -> dict[str, Any]:
    """Return the definition for a service's ``config``.

    ``sections`` maps each typed section's name to its fragment; every other
    key stays open. ``retired`` names keys the service no longer reads, each a
    dotted path such as ``"capacity.old_setting"``: each is refused in any
    spelling, so a deployment still stating one fails at render instead of
    being silently ignored. A retired key may not be a field a typed section
    still has, lie under another retired key, or lie where a pattern for it
    would bypass or miss the typing of its section (see :func:`_retire`).
    """
    # Sections are matched in any spelling, so two names differing only by case
    # would claim the same keys; this refuses them before anything is built.
    any_case_fields(sections)
    definition: dict[str, Any] = {
        "type": "object",
        "patternProperties": {
            any_case(name): copy.deepcopy(fragment)
            for name, fragment in sorted(sections.items())
        },
    }
    retired_keys = list(retired)
    for dotted in retired_keys:
        if not all(dotted.split(".")):
            raise ValueError(f"retired key {dotted!r} is not a dotted key path")
    nested = _nested_retirements(retired_keys)
    if nested:
        inner, outer = nested[0]
        raise ValueError(
            f"retired key {inner!r} lies under retired key {outer!r}, "
            "which refuses it already"
        )
    for dotted in retired_keys:
        _retire(definition, dotted.split("."), dotted)
    return definition


# Keywords whose value maps keys to the schema each key's value meets;
# ``additionalProperties`` is one schema for every other key.
_KEYED = ("properties", "patternProperties")
# Keywords that constrain a value whatever its type, so a schema stating one
# cannot accept ``null`` by naming it among its types. Beside ``$ref`` every
# other keyword is ignored, so a type extended there would change nothing.
_ANY_TYPE = (
    "const", "enum", "allOf", "anyOf", "oneOf", "not", "if", "then", "else", "$ref"
)


def _null() -> dict[str, Any]:
    return {"type": "null"}


def _accepts_null(schema: Any) -> bool:
    """Whether ``null`` meets ``schema``, read through the keywords that test it.

    A reference is not followed, so a schema making one is taken not to accept
    ``null``; widening it then adds a branch that may be redundant, never one
    that refuses.
    """
    if isinstance(schema, bool):
        return schema
    if not isinstance(schema, Mapping) or "$ref" in schema:
        return False
    stated = schema.get("type")
    if stated is not None and "null" not in ([stated] if isinstance(stated, str) else stated):
        return False
    if "const" in schema and schema["const"] is not None:
        return False
    if "enum" in schema and None not in schema["enum"]:
        return False
    if not all(_accepts_null(branch) for branch in schema.get("allOf", ())):
        return False
    if "anyOf" in schema and not any(_accepts_null(b) for b in schema["anyOf"]):
        return False
    if "oneOf" in schema and sum(_accepts_null(b) for b in schema["oneOf"]) != 1:
        return False
    if "not" in schema and _accepts_null(schema["not"]):
        return False
    if "if" in schema:
        branch = "then" if _accepts_null(schema["if"]) else "else"
        return _accepts_null(schema.get(branch, True))
    return True


def _or_null(schema: Any) -> Any:
    """``schema`` accepting ``null`` too, in the form that keeps it readable."""
    if _accepts_null(schema):
        return schema
    if not isinstance(schema, Mapping):
        return {"anyOf": [schema, _null()]}
    if "type" in schema and not any(key in schema for key in _ANY_TYPE):
        stated = schema["type"]
        types = [stated] if isinstance(stated, str) else list(stated)
        return {**schema, "type": [*types, "null"]}
    if set(schema) == {"anyOf"}:
        return {"anyOf": [*schema["anyOf"], _null()]}
    return {"anyOf": [schema, _null()]}


def _keys_accept_null(node: Any) -> Any:
    """Make every schema ``node`` reaches as a key's value accept ``null``.

    Under ``properties``, ``patternProperties``, and ``additionalProperties`` a
    key's value is checked only when the key is present, so a schema widened to
    accept ``null`` reads a ``null`` key as an absent one, inside ``not`` and
    ``if`` as much as outside them. A combinator's branches and an array's item
    schemas describe a value rather than a key's: they are not widened, so a
    ``null`` list element stays refused, but the keys they type are. A refused
    key (``false``) is not widened.
    """
    if isinstance(node, list):
        return [_keys_accept_null(item) for item in node]
    if not isinstance(node, Mapping):
        return copy.deepcopy(node)
    result: dict[str, Any] = {}
    for keyword, value in node.items():
        if keyword in _KEYED and isinstance(value, Mapping):
            result[keyword] = {
                key: _or_null(_keys_accept_null(schema)) if schema is not False else False
                for key, schema in value.items()
            }
        elif keyword == "additionalProperties" and isinstance(value, Mapping):
            result[keyword] = _or_null(_keys_accept_null(value))
        elif keyword in (*_COMBINATORS, "items"):
            # A ``dependencies`` list names the keys another key requires and is
            # copied as it is; its schemas, like every combinator's, apply to the
            # same object, whose own keys they type.
            result[keyword] = (
                {key: _keys_accept_null(entry) for key, entry in value.items()}
                if keyword == "dependencies" and isinstance(value, Mapping)
                else _keys_accept_null(value)
            )
        else:
            result[keyword] = copy.deepcopy(value)
    return result


def accepting_null(definition: Mapping[str, Any]) -> dict[str, Any]:
    """Return a copy of ``definition`` that accepts ``null`` wherever it accepts a key.

    A values file's ``null`` removes the key it names; the schema has to let the
    ``null`` through for the chart to remove it. Every schema reached as a key's
    value, at any depth, inside every combinator and every list element's keys,
    also accepts ``null``: a type is extended where one is stated, so each field
    reads as it did. A key
    the definition refuses stays refused, so refusing a secret or retired key
    never depends on the value a values file gives it. The definition's own
    root is left as it is: whether the whole configuration may be ``null`` is
    the chart's to say.
    """
    return _keys_accept_null(definition)


def render(schema: Mapping[str, Any], definition: Mapping[str, Any], *, name: str) -> str:
    """Return ``schema`` with its definition ``name`` replaced, as file text."""
    updated = dict(schema)
    definitions = dict(updated.get("definitions", {}))
    definitions[name] = definition
    updated["definitions"] = definitions
    return json.dumps(updated, indent=2) + "\n"


def stale_files(
    paths: Sequence[Path], definition: Mapping[str, Any], *, name: str
) -> list[Path]:
    """Return each schema file whose committed definition ``name`` differs."""
    stale: list[Path] = []
    for path in paths:
        committed = json.loads(path.read_text(encoding="utf-8"))
        if committed.get("definitions", {}).get(name) != definition:
            stale.append(path)
    return stale


def main(
    argv: Sequence[str] | None,
    *,
    build_definition: Callable[[], Mapping[str, Any]],
    name: str,
    schema_files: Sequence[str],
    description: str,
) -> int:
    """Write or check the service's generated definition in its schema files.

    ``schema_files`` are paths relative to the repository root, which the
    command takes as ``--root`` (the working directory by default). ``check``
    exits non-zero, naming each stale file, when a committed definition differs
    from the generated one.
    """
    parser = argparse.ArgumentParser(description=description)
    parser.add_argument("action", choices=("write", "check"))
    parser.add_argument(
        "--root", type=Path, default=Path.cwd(), help="the repository root"
    )
    args = parser.parse_args(argv)
    paths = [args.root / relative for relative in schema_files]
    missing = [path for path in paths if not path.is_file()]
    if missing:
        for path in missing:
            print(f"no schema file {path} under the root {args.root}", file=sys.stderr)
        return 2
    definition = build_definition()
    if args.action == "check":
        stale = stale_files(paths, definition, name=name)
        for path in stale:
            print(f"stale generated {name} in {path}", file=sys.stderr)
        return 1 if stale else 0
    for path in paths:
        schema = json.loads(path.read_text(encoding="utf-8"))
        path.write_text(render(schema, definition, name=name), encoding="utf-8")
    return 0
