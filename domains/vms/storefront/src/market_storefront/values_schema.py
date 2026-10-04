"""Generate the Helm values-schema definition for a storefront agent's ``config``.

A chart passes an agent's ``config`` through to the storefront unchanged, so the
values schema is where a secret placed there is stopped before it reaches a
ConfigMap. The typed configuration models already say which fields are secret
(``json_schema_extra={"secret": True}``) and which roles a field applies to
(``"roles"``); this module turns their JSON Schema into one definition that:

* refuses every secret-marked field, and every field that does not apply to the
  seller role, in any spelling of its name;
* accepts every other field in any spelling, as the storefront's loader does;
* closes each typed section, so a field its model does not have — hosted payer
  data, say — is refused too;
* carries no defaults and no required fields, and leaves ``config`` and every
  untyped section open;
* types ``[Delivery]``: each sink instance by the installed sink it
  instantiates -- its ``sink`` value, or its own name when it states none -- so
  a secret sink setting is refused like any other. The sinks typed are those
  installed here that declare their settings model, found by discovery; no sink
  is named in this module, and an instance of any other sink stays open.

The definition is generated in this storefront's locked environment, so the
sinks it types are the sinks this storefront's image installs.

The definition is written into the umbrella and storefront chart schemas under
:data:`DEFINITION`. See openspec/specs/deployment-state/spec.md, "Generated
configuration has one source of truth".
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from market_delivery import SINK_KEY, discover_sink_settings_models
from pydantic import BaseModel

from market_storefront.settlement_composition import (
    build_storefront_settlement_registry,
)
from market_storefront.utils.config import (
    IdentityConfigDeclaration,
    RegistryConfigDeclaration,
    WalletConfigDeclaration,
)

DEFINITION = "storefrontServiceConfig"
ROLE = "seller"

# Annotation keywords that describe a value rather than constrain it. Defaults
# are dropped because the storefront, not the chart, owns them.
_ANNOTATIONS = frozenset(
    {"default", "title", "description", "examples", "roles", "secret", "never_published"}
)


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


def _any_case_fields(fields: Mapping[str, Any]) -> dict[str, Any]:
    """Key ``fields`` by :func:`any_case` patterns, refusing case-only collisions."""
    patterns: dict[str, Any] = {}
    seen: dict[str, str] = {}
    for name, schema in fields.items():
        folded = name.lower()
        if folded in seen:
            raise ValueError(
                f"fields {seen[folded]!r} and {name!r} differ only by case; "
                "the storefront's loader cannot tell them apart"
            )
        seen[folded] = name
        patterns[any_case(name)] = schema
    return patterns


def _publicize(node: Any, role: str) -> Any:
    """Refuse withheld fields, match the rest in any spelling, recursively.

    Every field becomes an :func:`any_case` pattern, allowed or refused, because
    the storefront's loader reads ``Priority`` as ``priority``; a closed section
    keeps ``additionalProperties: false``, so a field the model lacks is still
    refused in any spelling. ``required`` is dropped: whether a field is present
    is the storefront's startup check, and an exact-name requirement would
    refuse a correctly spelled-differently key.
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
            **_any_case_fields(fields),
        }
    return result


def model_fragment(model: type[BaseModel], *, role: str = ROLE) -> dict[str, Any]:
    """Return ``model``'s values-schema fragment for ``role``."""
    schema = model.model_json_schema(mode="validation")
    defs = schema.pop("$defs", {})
    return _publicize(_inline(schema, defs, ()), role)


def _settlement_fragment(role: str) -> dict[str, Any]:
    """The ``Settlement`` root, closed to the mechanisms the storefront registers.

    The settlement runtime refuses any other root key, so closing it here
    refuses nothing the storefront would accept.
    """
    fields: dict[str, Any] = {
        "schema_version": {"type": "integer"},
        "priority": {"type": "array", "items": {"type": "string"}},
    }
    for registration in build_storefront_settlement_registry().registrations:
        fields[registration.config_key] = (
            model_fragment(registration.config_model, role=role)
            if role in registration.roles
            else False
        )
    return {
        "type": "object",
        "additionalProperties": False,
        "patternProperties": _any_case_fields(fields),
    }


def _other_spellings(name: str) -> str:
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


#: ``sink`` spelled any way but exactly. The delivery kit reads only ``sink``, so
#: an instance spelling it differently selects no sink at the storefront -- and,
#: unrefused here, would escape the typing that keeps a sink's secret settings
#: out of public configuration. It is refused in every instance table.
_MISSPELLED_SINK = {_other_spellings(SINK_KEY): False}


def _sink_instance(sink: str, model: type[BaseModel], role: str) -> dict[str, Any]:
    """An instance of ``sink``: its settings, plus ``sink`` naming only it."""
    fragment = model_fragment(model, role=role)
    patterns = dict(fragment.get("patternProperties", {}))
    patterns.pop(any_case(SINK_KEY), None)
    patterns[f"^{SINK_KEY}$"] = {"const": sink}
    patterns.update(_MISSPELLED_SINK)
    fragment["patternProperties"] = patterns
    return fragment


def _delivery_fragment(
    role: str, sinks: Mapping[str, type[BaseModel]] | None = None
) -> dict[str, Any]:
    """The ``Delivery`` section, each instance typed by the sink it uses.

    ``sinks`` maps each typed sink's name to its settings model; by default,
    every installed sink that declares one. A table named for a typed sink is
    that sink, and may state no other. Any other table is an instance whose
    ``sink`` selects its settings; one naming a sink with no declared model is
    left open, since its settings are not known here.
    """
    if sinks is None:
        sinks, _warnings = discover_sink_settings_models()
    instances = {
        name: _sink_instance(name, model, role) for name, model in sorted(sinks.items())
    }
    # Each typed instance fragment already pins ``sink`` to its own name.
    selected = list(instances.values())
    untyped = {
        "patternProperties": {f"^{SINK_KEY}$": {"not": {"enum": sorted(sinks)}}}
    }
    # One entry per key in RESERVED_SECTION_KEYS: the section's own settings.
    root: dict[str, Any] = {
        "enabled": {"type": "array", "items": {"type": "string"}},
        "timeout_seconds": {"type": "number"},
        "origins": {
            "type": "object",
            "additionalProperties": {"type": "array", "items": {"type": "string"}},
        },
    }
    return {
        "type": "object",
        "patternProperties": {
            **_any_case_fields(root),
            **{any_case(name): instance for name, instance in instances.items()},
        },
        "additionalProperties": {
            "type": "object",
            "patternProperties": dict(_MISSPELLED_SINK),
            "dependencies": {SINK_KEY: {"anyOf": [*selected, untyped]}},
        },
    }


def storefront_config_definition(role: str = ROLE) -> dict[str, Any]:
    """Return the generated definition for an agent's ``config``."""
    sections: dict[str, Any] = {
        "delivery": _delivery_fragment(role),
        "identity": model_fragment(IdentityConfigDeclaration, role=role),
        "registry": model_fragment(RegistryConfigDeclaration, role=role),
        "settlement": _settlement_fragment(role),
        "wallet": model_fragment(WalletConfigDeclaration, role=role),
    }
    return {
        "type": "object",
        "patternProperties": {
            any_case(name): fragment for name, fragment in sorted(sections.items())
        },
    }


def render(schema: Mapping[str, Any], definition: Mapping[str, Any]) -> str:
    """Return ``schema`` with its generated definition replaced, as file text."""
    updated = dict(schema)
    definitions = dict(updated.get("definitions", {}))
    definitions[DEFINITION] = definition
    updated["definitions"] = definitions
    return json.dumps(updated, indent=2) + "\n"


def stale_files(paths: Sequence[Path], definition: Mapping[str, Any]) -> list[Path]:
    """Return each schema file whose committed definition differs from ``definition``."""
    stale: list[Path] = []
    for path in paths:
        committed = json.loads(path.read_text(encoding="utf-8"))
        if committed.get("definitions", {}).get(DEFINITION) != definition:
            stale.append(path)
    return stale


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("action", choices=("write", "check"))
    parser.add_argument("schemas", nargs="+", type=Path, help="values.schema.json files")
    args = parser.parse_args(argv)
    definition = storefront_config_definition()
    if args.action == "check":
        stale = stale_files(args.schemas, definition)
        for path in stale:
            print(f"stale generated {DEFINITION} in {path}", file=sys.stderr)
        return 1 if stale else 0
    for path in args.schemas:
        schema = json.loads(path.read_text(encoding="utf-8"))
        path.write_text(render(schema, definition), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
