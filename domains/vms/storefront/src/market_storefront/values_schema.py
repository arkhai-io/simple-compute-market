"""Generate the Helm values-schema definition for a storefront agent's ``config``.

A chart passes an agent's ``config`` through to the storefront unchanged, so the
values schema is where a secret placed there is stopped before it reaches a
ConfigMap. The typed configuration models already say which fields are secret
(``json_schema_extra={"secret": True}``) and which roles a field applies to
(``"roles"``); this module turns their JSON Schema into one definition that:

* refuses every secret-marked field, and every field that does not apply to the
  seller role, in any spelling of its name;
* closes each typed section, so a field its model does not have — hosted payer
  data, say — is refused too;
* carries no defaults, and leaves ``config`` and every untyped section open.

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

from core_storefront.identity_config import IdentityConfig
from pydantic import BaseModel

from market_storefront.settlement_composition import (
    build_storefront_settlement_registry,
)
from market_storefront.utils.config import (
    RegistryConfigDeclaration,
    WalletConfigDeclaration,
)

DEFINITION = "storefrontServiceConfig"
ROLE = "seller"

# Annotation keywords that describe a value rather than constrain it. Defaults
# are dropped because the storefront, not the chart, owns them.
_ANNOTATIONS = frozenset({"default", "title", "description", "examples", "roles", "secret"})


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


def _publicize(node: Any, role: str) -> Any:
    """Refuse withheld fields and drop annotations, recursively."""
    if isinstance(node, list):
        return [_publicize(item, role) for item in node]
    if not isinstance(node, Mapping):
        return node
    result: dict[str, Any] = {}
    withheld: dict[str, Any] = {}
    for key, value in node.items():
        if key in _ANNOTATIONS:
            continue
        if key == "properties" and isinstance(value, Mapping):
            kept: dict[str, Any] = {}
            for name, field in value.items():
                if _is_withheld(field, role):
                    withheld[any_case(name)] = False
                else:
                    kept[name] = _publicize(field, role)
            result[key] = kept
        else:
            result[key] = _publicize(value, role)
    if withheld:
        result["patternProperties"] = {
            **dict(result.get("patternProperties", {})),
            **withheld,
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
    properties: dict[str, Any] = {
        "schema_version": {"type": "integer"},
        "priority": {"type": "array", "items": {"type": "string"}},
    }
    withheld: dict[str, Any] = {}
    for registration in build_storefront_settlement_registry().registrations:
        if role in registration.roles:
            properties[registration.config_key] = model_fragment(
                registration.config_model, role=role
            )
        else:
            withheld[any_case(registration.config_key)] = False
    fragment: dict[str, Any] = {
        "type": "object",
        "additionalProperties": False,
        "properties": properties,
    }
    if withheld:
        fragment["patternProperties"] = withheld
    return fragment


def storefront_config_definition(role: str = ROLE) -> dict[str, Any]:
    """Return the generated definition for an agent's ``config``."""
    sections: dict[str, Any] = {
        "identity": {
            "type": "object",
            "properties": {"principal": model_fragment(IdentityConfig, role=role)},
        },
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
