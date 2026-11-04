"""Establishing relays from a mounted definition document.

The deployment path applies a chart; there is no operator API call in it, and
secret material must not pass through an operator's workstation to get there.
So a relay has to be establishable from configuration alone.

The document carries a rendezvous address, a port, a window, and the *names*
of the secrets-profile keys holding that relay's admission token and its
grant-signing key. It carries no credential, so it needs no Secret and can be
an ordinary mounted file. Every entry names a grant key, which the operator
supplies rather than letting the service generate one, so that a deployment
reinstalled from an empty database recreates the relay with the key its
admission plugin already holds.

The named keys are read only when a relay is created. A relay that already
exists keeps whatever token and keys it holds, so a rotation performed through
the relay routes is not reverted by a later reconciliation of a document that
still names the key holding the old value. Those are the fields a
reconciliation must never touch; everything else the document declares, it may
correct.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import yaml

from ..definition_documents import DefinitionDocumentContribution
from .keys import GrantKey, GrantKeyError


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
    grant_key_secret_key: str
    label: str | None = None
    token_secret_key: str | None = None
    enabled: bool = True


_REQUIRED = (
    "id",
    "relay_addr",
    "relay_port",
    "vm_port_range_start",
    "vm_port_range_count",
    "grant_key_secret_key",
)
_ALLOWED = frozenset(_REQUIRED) | {"label", "token_secret_key", "enabled"}


def parse_relay_definitions(yaml_text: str) -> tuple[RelayDefinition, ...]:
    """Validate the whole document before anything is applied.

    Rejecting unknown fields matters more here than it looks: a misspelled
    ``token_secret_key`` would otherwise produce a relay with no token, which
    fails at admission rather than at configuration, as a relay refusing a
    proxy in a tunnel client's log.
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
            named = f" ('{entry['id']}')" if entry.get("id") not in (None, "") else ""
            raise RelayDefinitionError(
                f"relays[{index}]{named} is missing required field(s): "
                f"{', '.join(missing)}"
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
                grant_key_secret_key=str(entry["grant_key_secret_key"]),
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

    # Every credential a new relay needs is resolved before any relay is
    # written, so a profile key missing or malformed on a later entry fails the
    # import with nothing created, whether or not the caller's transaction
    # would have rolled the earlier entries back.
    credentials = {
        definition.id: (
            _resolve_token(definition, settings),
            _resolve_grant_key(definition, settings),
        )
        for definition in definitions
        if definition.id not in existing
    }
    # A key belongs to one relay, so a key two new entries name, or one an
    # existing relay holds or retired, is refused here, before any is written.
    signing_for: dict[str, str] = {}
    for definition in definitions:
        if definition.id not in credentials:
            continue
        kid = credentials[definition.id][1].kid
        other = signing_for.setdefault(kid, definition.id)
        if other != definition.id:
            raise RelayDefinitionError(
                f"relays '{other}' and '{definition.id}' name the same grant key; "
                "each relay holds its own"
            )
        conflict = relay_service.grant_key_conflict(kid)
        if conflict is not None:
            raise RelayDefinitionError(
                f"relay '{definition.id}' names grant_key_secret_key "
                f"'{definition.grant_key_secret_key}': {conflict}"
            )

    created: list[str] = []
    updated: list[str] = []
    unchanged: list[str] = []

    for definition in definitions:
        current = existing.get(definition.id)
        if current is None:
            token, grant_key = credentials[definition.id]
            relay_service.create_relay(
                relay_id=definition.id,
                label=definition.label,
                relay_addr=definition.relay_addr,
                relay_port=definition.relay_port,
                vm_port_range_start=definition.vm_port_range_start,
                vm_port_range_count=definition.vm_port_range_count,
                token=token,
                enabled=definition.enabled,
                grant_key=grant_key,
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
        # The token and the grant key are absent from this call deliberately:
        # an existing relay's credentials are owned by whoever last rotated
        # them, and the document has no standing to restate them.
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


def _resolve_grant_key(definition: RelayDefinition, settings: Any) -> GrantKey:
    """Load the grant key from the profile key this relay's entry names.

    A profile key with no value, or a value that is not a key in the profile's
    form, fails the import naming the relay and the profile key. The value is
    a private key, so no refusal quotes it.
    """
    key = definition.grant_key_secret_key
    value = getattr(settings, key, None)
    if value is None or not str(value).strip():
        raise RelayDefinitionError(
            f"relay '{definition.id}' names grant_key_secret_key '{key}', "
            "which the secrets profile does not carry a value for"
        )
    try:
        return GrantKey.from_profile_form(str(value))
    except GrantKeyError as exc:
        raise RelayDefinitionError(
            f"relay '{definition.id}' names grant_key_secret_key '{key}', "
            f"whose value is unusable: {exc}"
        ) from None


#: The relay document's kind, which names its recorded digest. It must not
#: change: a renamed kind makes the next startup reapply the document over any
#: administration done since.
RELAY_DOCUMENT_KIND = "relays"


def relay_definitions_document(
    *, relay_service: Any, settings: Any, path: Any
) -> DefinitionDocumentContribution:
    """The relay definitions document, imported before pools reference relays."""

    def apply(db: Any, yaml_text: str) -> str:
        diff = import_relay_definitions_in_session(
            db, yaml_text, relay_service=relay_service, settings=settings
        )
        # No "disabled" count: a relay the document stops naming is retained.
        # Disabling one would break every pool referencing it and every live
        # tunnel on it, which is not what an operator editing an unrelated
        # entry is asking for.
        return (
            f"created={len(diff.created)} updated={len(diff.updated)} "
            f"unchanged={len(diff.unchanged)}"
        )

    return DefinitionDocumentContribution(
        kind=RELAY_DOCUMENT_KIND,
        label="Relay-definitions",
        path=path,
        apply=apply,
    )


__all__ = [
    "RELAY_DOCUMENT_KIND",
    "RelayDefinition",
    "RelayDefinitionDiff",
    "RelayDefinitionError",
    "import_relay_definitions",
    "import_relay_definitions_in_session",
    "parse_relay_definitions",
    "relay_definitions_document",
]
