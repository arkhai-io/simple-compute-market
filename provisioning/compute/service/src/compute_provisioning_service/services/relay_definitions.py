"""Establishing relays from a mounted definition document.

The deployment path applies a chart; there is no operator API call in it, and
secret material must not pass through an operator's workstation to get there.
So a relay has to be establishable from configuration alone.

The document carries a rendezvous address, a port, a window, and the *name* of
the secrets-profile key holding that relay's admission token. It carries no
credential, so it needs no Secret and can be an ordinary mounted file.

The named key is read only when a relay is created. A relay that already exists
keeps whatever token it holds, so a rotation performed through the relay
controller is not reverted by a later reconciliation of a document that still
names the key holding the old value. That is the one field a reconciliation
must never touch; everything else the document declares, it may correct.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

import yaml


class RelayDefinitionError(ValueError):
    """The relay definition document cannot be applied as written."""


@dataclass(frozen=True)
class RelayDefinitionDiff:
    created: tuple[str, ...] = ()
    updated: tuple[str, ...] = ()
    unchanged: tuple[str, ...] = ()


@dataclass(frozen=True)
class RelayDefinition:
    id: str
    relay_addr: str
    relay_port: int
    vm_port_range_start: int
    vm_port_range_count: int
    label: str | None = None
    token_secret_key: str | None = None
    enabled: bool = True


_REQUIRED = ("id", "relay_addr", "relay_port", "vm_port_range_start", "vm_port_range_count")
_ALLOWED = frozenset(_REQUIRED) | {"label", "token_secret_key", "enabled"}


def parse_relay_definitions(yaml_text: str) -> tuple[RelayDefinition, ...]:
    """Validate the whole document before anything is applied.

    Rejecting unknown fields matters more here than it looks: a misspelled
    ``token_secret_key`` would otherwise produce a relay with no token, which
    fails at admission rather than at configuration — the asynchronous,
    hard-to-diagnose failure this whole change exists to eliminate.
    """
    try:
        document = yaml.safe_load(yaml_text) or {}
    except yaml.YAMLError as exc:
        raise RelayDefinitionError(f"relay definitions are not valid YAML: {exc}") from exc
    if not isinstance(document, dict):
        raise RelayDefinitionError("relay definitions must be a mapping with a 'relays' key")

    entries = document.get("relays", [])
    if not isinstance(entries, list):
        raise RelayDefinitionError("'relays' must be a list")

    definitions: list[RelayDefinition] = []
    seen_ids: set[str] = set()
    seen_endpoints: set[tuple[str, int]] = set()
    for index, entry in enumerate(entries):
        if not isinstance(entry, dict):
            raise RelayDefinitionError(f"relays[{index}] must be a mapping")
        unknown = sorted(set(entry) - _ALLOWED)
        if unknown:
            raise RelayDefinitionError(
                f"relays[{index}] has unknown field(s): {', '.join(unknown)}"
            )
        missing = [key for key in _REQUIRED if entry.get(key) in (None, "")]
        if missing:
            raise RelayDefinitionError(
                f"relays[{index}] is missing required field(s): {', '.join(missing)}"
            )
        relay_id = str(entry["id"])
        if relay_id in seen_ids:
            raise RelayDefinitionError(f"relays declares '{relay_id}' more than once")
        seen_ids.add(relay_id)

        addr = str(entry["relay_addr"]).strip().lower()
        try:
            port = int(entry["relay_port"])
            start = int(entry["vm_port_range_start"])
            count = int(entry["vm_port_range_count"])
        except (TypeError, ValueError) as exc:
            raise RelayDefinitionError(
                f"relays[{index}] has a non-integer port or window value"
            ) from exc

        endpoint = (addr, port)
        if endpoint in seen_endpoints:
            raise RelayDefinitionError(
                f"relays declares rendezvous {addr}:{port} more than once; "
                "one rendezvous is one relay"
            )
        seen_endpoints.add(endpoint)

        definitions.append(
            RelayDefinition(
                id=relay_id,
                relay_addr=addr,
                relay_port=port,
                vm_port_range_start=start,
                vm_port_range_count=count,
                label=entry.get("label"),
                token_secret_key=entry.get("token_secret_key"),
                enabled=bool(entry.get("enabled", True)),
            )
        )
    return tuple(definitions)


def import_relay_definitions(
    yaml_text: str,
    *,
    relay_service: Any,
    settings: Any,
) -> RelayDefinitionDiff:
    """Reconcile relays, each write in its own transaction.

    Kept for callers with nothing to compose with. A startup importer, which
    must land the digest with the apply, uses the session-scoped form below.
    """
    return _reconcile(yaml_text, relay_service=relay_service, settings=settings)


def import_relay_definitions_in_session(
    db: Any,
    yaml_text: str,
    *,
    relay_service: Any,
    settings: Any,
) -> RelayDefinitionDiff:
    """Reconcile relays inside the caller's transaction, without committing."""
    return _reconcile(
        yaml_text, relay_service=relay_service.joining(db), settings=settings
    )


def _reconcile(
    yaml_text: str,
    *,
    relay_service: Any,
    settings: Any,
) -> RelayDefinitionDiff:
    """Apply every entry through one relay service view.

    The caller decides whether that view owns transactions or joins theirs; this
    function does not branch on it, so there is one reconciliation and not two
    that could drift.
    """
    definitions = parse_relay_definitions(yaml_text)
    existing = {view.id: view for view in relay_service.list_relays()}

    created: list[str] = []
    updated: list[str] = []
    unchanged: list[str] = []

    for definition in definitions:
        current = existing.get(definition.id)
        if current is None:
            token = _resolve_token(definition, settings)
            relay_service.create_relay(
                relay_id=definition.id,
                label=definition.label,
                relay_addr=definition.relay_addr,
                relay_port=definition.relay_port,
                vm_port_range_start=definition.vm_port_range_start,
                vm_port_range_count=definition.vm_port_range_count,
                token=token,
                enabled=definition.enabled,
            )
            created.append(definition.id)
            continue

        same = (
            current.relay_addr == definition.relay_addr
            and current.relay_port == definition.relay_port
            and current.vm_port_range_start == definition.vm_port_range_start
            and current.vm_port_range_count == definition.vm_port_range_count
            and current.label == definition.label
            and current.enabled == definition.enabled
        )
        if same:
            unchanged.append(definition.id)
            continue
        # The token is absent from this call deliberately: an existing relay's
        # credential is owned by whoever last rotated it, and the document has
        # no standing to restate it.
        # ``label`` is passed even when the document omits it, so an omitted
        # label clears a stored one. The document declares the relay's whole
        # non-secret shape; a field it cannot reach would compare unequal on
        # every import and report the same relay changed forever.
        relay_service.update_relay(
            definition.id,
            label=definition.label,
            relay_addr=definition.relay_addr,
            relay_port=definition.relay_port,
            vm_port_range_start=definition.vm_port_range_start,
            vm_port_range_count=definition.vm_port_range_count,
            enabled=definition.enabled,
        )
        updated.append(definition.id)

    return RelayDefinitionDiff(
        created=tuple(created), updated=tuple(updated), unchanged=tuple(unchanged)
    )


def _resolve_token(definition: RelayDefinition, settings: Any) -> str | None:
    """Read the profile key this relay's entry names, if it names one.

    A missing key fails the import naming it. Creating the relay with no token
    instead would defer the failure to admission, where it appears as a relay
    refusing a proxy in a tunnel client's log rather than as a configuration
    error at the point the configuration is wrong.
    """
    key = definition.token_secret_key
    if not key:
        return None
    value = getattr(settings, key, None)
    if value is None or not str(value).strip():
        raise RelayDefinitionError(
            f"relay '{definition.id}' names token_secret_key '{key}', "
            "which the secrets profile does not carry a value for"
        )
    return str(value)
