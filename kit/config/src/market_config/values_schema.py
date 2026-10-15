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
* refuses each retired key the service names, in any spelling.

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


def _retire(node: dict[str, Any], path: Sequence[str], dotted: str) -> None:
    """Refuse ``path`` under ``node``, opening an untyped section on the way."""
    head, *rest = path
    patterns = node.setdefault("patternProperties", {})
    pattern = any_case(head)
    existing = patterns.get(pattern)
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


def config_definition(
    sections: Mapping[str, Any], *, retired: Iterable[str] = ()
) -> dict[str, Any]:
    """Return the definition for a service's ``config``.

    ``sections`` maps each typed section's name to its fragment; every other
    key stays open. ``retired`` names keys the service no longer reads, each a
    dotted path such as ``"capacity.old_setting"``: each is refused in any
    spelling, so a deployment still stating one fails at render instead of
    being silently ignored. A retired key may not be a field a typed section
    still has.
    """
    any_case_fields(sections)
    definition: dict[str, Any] = {
        "type": "object",
        "patternProperties": {
            any_case(name): copy.deepcopy(fragment)
            for name, fragment in sorted(sections.items())
        },
    }
    for dotted in retired:
        path = dotted.split(".")
        if not all(path):
            raise ValueError(f"retired key {dotted!r} is not a dotted key path")
        _retire(definition, path, dotted)
    return definition


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
