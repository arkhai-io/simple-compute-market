"""Explicit, comment-preserving migration of legacy settlement configuration."""

from __future__ import annotations

import copy
import os
import stat
import tempfile
from collections.abc import Callable, Mapping, MutableMapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

import tomlkit
import tomllib
from market_settlement_runtime import (
    SETTLEMENT_CONFIG_SCHEMA_VERSION,
    SettlementRole,
)
from tomlkit.items import Table

ConfigValidator = Callable[[Mapping[str, Any], SettlementRole], None]

ALKAHEST_MECHANISM = "alkahest.v1"
STRIPE_MECHANISM = "fiat.stripe.v1"
KNOWN_MECHANISMS = frozenset({ALKAHEST_MECHANISM, STRIPE_MECHANISM})

BUYER_MIGRATION_COMMAND = "market config migrate --scope settlement --write --backup"
STOREFRONT_MIGRATION_COMMAND = (
    "market-storefront config migrate --scope settlement --write --backup"
)

_LEGACY_HOSTED_TABLES = (
    ("HostedSettlement",),
    ("hosted_settlement",),
    ("settlement", "hosted"),
)
_LEGACY_ALKAHEST_FIELDS: dict[str, tuple[str, Callable[[Any], Any] | None]] = {
    "oracle_gated_listings": ("oracle_gated", None),
    "trusted_oracle_address": (
        "trusted_oracle_addresses",
        lambda value: _address_list(value),
    ),
    "interruptible_listings": ("interruptible", None),
    "interruptible_oracle_address": (
        "interruptible_oracle_addresses",
        lambda value: _address_list(value),
    ),
}
_HOSTED_FIELD_RENAMES = {
    "contract_version": "expected_api_version",
    "timeout_seconds": "request_timeout_seconds",
}
_REMOVED_EMPTY_HOSTED_PATHS = frozenset(
    {
        ("account_ref",),
        ("authority_id",),
        ("authority", "principals"),
        ("base_url",),
        ("condition_profile",),
        ("environment",),
        ("expected_manifest_digest",),
    }
)
_ALKAHEST_FIELDS = frozenset(
    {
        "address_config_path",
        "enabled",
        "interruptible",
        "interruptible_oracle_addresses",
        "oracle_gated",
        "trusted_oracle_addresses",
    }
)
_STRIPE_FIELDS = frozenset(
    {
        "account_ref",
        "allow_insecure_loopback",
        "authority",
        "authority_id",
        "base_url",
        "condition_profile",
        "condition_profiles",
        "currency",
        "enabled",
        "environment",
        "expected_api_version",
        "expected_manifest_digest",
        "expected_schema_version",
        "preflight_timeout_seconds",
        "request_timeout_seconds",
        "required_capabilities",
        "resolvers",
    }
)
_FORBIDDEN_STRIPE_KEY_PARTS = frozenset(
    {
        "access_token",
        "admin",
        "administrator",
        "api_key",
        "credential",
        "database",
        "db_url",
        "dsn",
        "migration",
        "private_key",
        "provider",
        "secret",
        "stripe_key",
        "webhook",
    }
)


class SettlementMigrationError(RuntimeError):
    """A safe-to-display migration failure that never embeds configuration values."""


class SettlementMigrationConflict(SettlementMigrationError):
    """Raised when legacy and canonical configuration disagree."""

    def __init__(self, source: str, destination: str) -> None:
        self.source = source
        self.destination = destination
        super().__init__(f"conflicting settlement paths: {source} and {destination}")


class SettlementMigrationValidationError(SettlementMigrationError):
    """Raised when the complete candidate document is invalid."""


@dataclass(frozen=True, slots=True)
class MigrationAction:
    """One redacted migration operation; values are deliberately not represented."""

    kind: Literal["move", "remove"]
    source: str
    destination: str | None = None


@dataclass(frozen=True, slots=True)
class EnvironmentRename:
    """One public environment-name cutover, without its value."""

    source: str
    destination: str


@dataclass(frozen=True, slots=True)
class SettlementMigrationResult:
    """Sanitized result of checking or writing one configuration file."""

    path: Path
    changed: bool
    written: bool
    actions: tuple[MigrationAction, ...]
    backup_path: Path | None = None
    environment_renames: tuple[EnvironmentRename, ...] = ()


def _address_list(value: Any) -> list[str]:
    raw = _plain(value)
    if not isinstance(raw, str):
        raise SettlementMigrationValidationError(
            "legacy oracle address must be a string (value redacted)"
        )
    return [raw] if raw else []


def _plain(value: Any) -> Any:
    unwrap = getattr(value, "unwrap", None)
    return unwrap() if callable(unwrap) else value


def _copy_trivia(source: Any, destination: Any) -> None:
    source_trivia = getattr(source, "trivia", None)
    destination_trivia = getattr(destination, "trivia", None)
    if source_trivia is None or destination_trivia is None:
        return
    for name in ("indent", "comment_ws", "comment", "trail"):
        setattr(destination_trivia, name, getattr(source_trivia, name))


def _path_text(parts: tuple[str, ...]) -> str:
    return ".".join(parts)


def _lookup(container: Mapping[str, Any], parts: tuple[str, ...]) -> Any | None:
    current: Any = container
    for index, part in enumerate(parts):
        if not isinstance(current, Mapping) or part not in current:
            return None
        if index == len(parts) - 1 and callable(getattr(current, "item", None)):
            return current.item(part)
        current = current[part]
    return current


def _ensure_table(
    document: MutableMapping[str, Any], parts: tuple[str, ...]
) -> MutableMapping[str, Any]:
    current = document
    walked: list[str] = []
    for part in parts:
        walked.append(part)
        existing = current.get(part)
        if existing is None:
            existing = tomlkit.table()
            current[part] = existing
        if not isinstance(existing, MutableMapping):
            raise SettlementMigrationValidationError(
                f"configuration path {_path_text(tuple(walked))} must be a table"
            )
        current = existing
    return current


def _delete_path(document: MutableMapping[str, Any], parts: tuple[str, ...]) -> None:
    parents: list[tuple[MutableMapping[str, Any], str]] = []
    current = document
    for part in parts[:-1]:
        child = current.get(part)
        if not isinstance(child, MutableMapping):
            return
        parents.append((current, part))
        current = child
    current.pop(parts[-1], None)
    for parent, key in reversed(parents):
        child = parent.get(key)
        if isinstance(child, Mapping) and not child:
            parent.pop(key, None)
        else:
            break


def _iter_table_leaves(
    table: Mapping[str, Any], prefix: tuple[str, ...] = ()
) -> list[tuple[tuple[str, ...], Any]]:
    leaves: list[tuple[tuple[str, ...], Any]] = []
    for key, value in table.items():
        path = (*prefix, str(key))
        if isinstance(value, Table):
            leaves.extend(_iter_table_leaves(value, path))
        else:
            leaves.append((path, value))
    return leaves


def _normalized_mechanism(value: Any) -> str:
    if not isinstance(value, str):
        raise SettlementMigrationValidationError(
            "legacy settlement priority entries must be strings (values redacted)"
        )
    aliases = {
        "alkahest": ALKAHEST_MECHANISM,
        "stripe": STRIPE_MECHANISM,
        "hosted": STRIPE_MECHANISM,
        "hosted.stripe": STRIPE_MECHANISM,
    }
    return aliases.get(value, value)


def _normalized_priority(value: Any) -> list[str]:
    raw = _plain(value)
    entries = raw.split(",") if isinstance(raw, str) else raw
    if not isinstance(entries, (list, tuple)):
        raise SettlementMigrationValidationError(
            "legacy settlement priority must be a list (values redacted)"
        )
    priority = [
        _normalized_mechanism(entry.strip() if isinstance(entry, str) else entry)
        for entry in entries
    ]
    if any(mechanism not in KNOWN_MECHANISMS for mechanism in priority):
        raise SettlementMigrationValidationError(
            "legacy settlement priority contains an unknown mechanism (value redacted)"
        )
    if len(set(priority)) != len(priority):
        raise SettlementMigrationValidationError(
            "legacy settlement priority contains a duplicate mechanism (value redacted)"
        )
    return priority


def _same_value(left: Any, right: Any) -> bool:
    return _plain(left) == _plain(right)


class _Planner:
    def __init__(self, document: MutableMapping[str, Any], role: SettlementRole) -> None:
        self.document = document
        self.role = role
        self.actions: list[MigrationAction] = []
        self.alkahest_seen = False
        self.stripe_enabled = False
        self.legacy_priority: list[str] | None = None
        self.legacy_priority_item: Any | None = None
        self.enablement_sources: dict[str, str] = {}

    def move(
        self,
        source: tuple[str, ...],
        destination: tuple[str, ...],
        *,
        value: Any | None = None,
    ) -> None:
        source_item = _lookup(self.document, source)
        if source_item is None:
            return
        moved_item = copy.deepcopy(
            source_item if value is None else tomlkit.item(value)
        )
        if value is not None:
            _copy_trivia(source_item, moved_item)
        destination_item = _lookup(self.document, destination)
        if destination_item is not None and not _same_value(destination_item, moved_item):
            raise SettlementMigrationConflict(_path_text(source), _path_text(destination))
        if destination_item is None:
            parent = _ensure_table(self.document, destination[:-1])
            parent[destination[-1]] = moved_item
        _delete_path(self.document, source)
        self.actions.append(
            MigrationAction("move", _path_text(source), _path_text(destination))
        )

    def remove(self, source: tuple[str, ...]) -> None:
        if _lookup(self.document, source) is None:
            return
        _delete_path(self.document, source)
        self.actions.append(MigrationAction("remove", _path_text(source)))

    def migrate_hosted(self) -> None:
        present = [
            path
            for path in _LEGACY_HOSTED_TABLES
            if _lookup(self.document, path) is not None
        ]
        if len(present) > 1:
            raise SettlementMigrationConflict(
                _path_text(present[0]), _path_text(present[1])
            )
        if not present:
            return
        source_table_path = present[0]
        source_table = _lookup(self.document, source_table_path)
        if not isinstance(source_table, Mapping):
            raise SettlementMigrationValidationError(
                f"legacy settlement path {_path_text(source_table_path)} must be a table"
            )
        self._reject_forbidden_stripe_keys(source_table, source_table_path)
        enabled = source_table.get("enabled")
        self.stripe_enabled = _plain(enabled) is True
        if self.stripe_enabled:
            self.enablement_sources["stripe"] = (
                f"{_path_text(source_table_path)}.enabled"
            )
        leaves = _iter_table_leaves(source_table)
        for relative, _item in leaves:
            source = (*source_table_path, *relative)
            if relative in _REMOVED_EMPTY_HOSTED_PATHS and _plain(_item) in (
                "",
                [],
            ):
                self.remove(source)
                continue
            renamed = (
                _HOSTED_FIELD_RENAMES.get(relative[0], relative[0]),
                *relative[1:],
            )
            self.move(source, ("Settlement", "stripe", *renamed))
        self.remove(source_table_path)

    def _reject_forbidden_stripe_keys(
        self, table: Mapping[str, Any], prefix: tuple[str, ...]
    ) -> None:
        for relative, _value in _iter_table_leaves(table):
            for part in relative:
                lowered = part.lower()
                if any(token in lowered for token in _FORBIDDEN_STRIPE_KEY_PARTS):
                    raise SettlementMigrationValidationError(
                        f"forbidden hosted settlement path {_path_text((*prefix, *relative))} (value redacted)"
                    )

    def migrate_alkahest_policy(self) -> None:
        for source_name, (
            destination_name,
            transform,
        ) in _LEGACY_ALKAHEST_FIELDS.items():
            source = (source_name,)
            item = _lookup(self.document, source)
            if item is None:
                continue
            self.alkahest_seen = True
            self.enablement_sources.setdefault("alkahest", _path_text(source))
            moved_value = transform(item) if transform is not None else None
            self.move(
                source,
                ("Settlement", "alkahest", destination_name),
                value=moved_value,
            )

    def migrate_address_books(self) -> None:
        occurrences: list[tuple[tuple[str, ...], Any]] = []
        for chains_name in ("Chains", "chains"):
            chains = self.document.get(chains_name)
            if not isinstance(chains, Mapping):
                continue
            for chain_name, chain in chains.items():
                if not isinstance(chain, Mapping):
                    continue
                field = "alkahest_address_config_path"
                if field in chain:
                    occurrences.append(
                        ((chains_name, str(chain_name), field), chain[field])
                    )
        if not occurrences:
            return
        self.alkahest_seen = True
        self.enablement_sources.setdefault(
            "alkahest", _path_text(occurrences[0][0])
        )
        nonempty = [
            entry for entry in occurrences if str(_plain(entry[1]) or "").strip()
        ]
        if nonempty:
            first_path, first_item = nonempty[0]
            conflicting = next(
                (
                    entry
                    for entry in nonempty[1:]
                    if str(_plain(entry[1])).strip()
                    != str(_plain(first_item)).strip()
                ),
                None,
            )
            if conflicting is not None:
                raise SettlementMigrationConflict(
                    _path_text(first_path), _path_text(conflicting[0])
                )
        destination = ("Settlement", "alkahest", "address_config_path")
        if nonempty:
            first_path, first_item = nonempty[0]
            destination_item = _lookup(self.document, destination)
            if destination_item is not None and not _same_value(destination_item, first_item):
                raise SettlementMigrationConflict(
                    _path_text(first_path), _path_text(destination)
                )
            if destination_item is None:
                parent = _ensure_table(self.document, destination[:-1])
                parent[destination[-1]] = copy.deepcopy(first_item)
            for source, _item in occurrences:
                _delete_path(self.document, source)
                self.actions.append(
                    MigrationAction("move", _path_text(source), _path_text(destination))
                )
        else:
            for source, _item in occurrences:
                self.remove(source)

    def migrate_priority(self) -> None:
        source = ("settlement", "mechanism_priority")
        legacy_item = _lookup(self.document, source)
        if legacy_item is not None:
            self.legacy_priority = _normalized_priority(legacy_item)
            self.legacy_priority_item = copy.deepcopy(legacy_item)
            for mechanism in self.legacy_priority:
                key = "alkahest" if mechanism == ALKAHEST_MECHANISM else "stripe"
                self.enablement_sources[key] = _path_text(source)
            _delete_path(self.document, source)
            self.actions.append(
                MigrationAction("move", _path_text(source), "Settlement.priority")
            )

        destination = ("Settlement", "priority")
        current_item = _lookup(self.document, destination)
        current = _normalized_priority(current_item) if current_item is not None else None
        derived = list(self.legacy_priority or current or [])
        if self.alkahest_seen and ALKAHEST_MECHANISM not in derived:
            derived.append(ALKAHEST_MECHANISM)
        if self.stripe_enabled and STRIPE_MECHANISM not in derived:
            derived.append(STRIPE_MECHANISM)

        if self.legacy_priority is not None and current is not None and current != derived:
            raise SettlementMigrationConflict("settlement.mechanism_priority", "Settlement.priority")
        if derived and current is None:
            parent = _ensure_table(self.document, ("Settlement",))
            if (
                self.legacy_priority_item is not None
                and _plain(self.legacy_priority_item) == derived
            ):
                parent["priority"] = self.legacy_priority_item
            else:
                priority = tomlkit.array()
                priority.extend(derived)
                parent["priority"] = priority
        elif current is not None and current != derived:
            conflict_source = next(
                iter(self.enablement_sources.values()),
                "settlement.mechanism_priority",
            )
            raise SettlementMigrationConflict(
                conflict_source, "Settlement.priority"
            )

        if self.actions and derived:
            self._set_enabled("alkahest", ALKAHEST_MECHANISM in derived)
            self._set_enabled("stripe", STRIPE_MECHANISM in derived)

    def _set_enabled(self, key: str, enabled: bool) -> None:
        section = _lookup(self.document, ("Settlement", key))
        if section is None and not enabled:
            return
        parent = _ensure_table(self.document, ("Settlement", key))
        current = parent.get("enabled")
        if current is not None and _plain(current) is not enabled:
            raise SettlementMigrationConflict(
                self.enablement_sources.get(key, f"Settlement.{key}.enabled"),
                f"Settlement.{key}.enabled",
            )
        if current is None:
            parent["enabled"] = enabled

    def run(self) -> tuple[MigrationAction, ...]:
        self.migrate_hosted()
        self.migrate_alkahest_policy()
        self.migrate_address_books()
        self.migrate_priority()
        return tuple(self.actions)


def is_legacy_settlement_path(path: str) -> bool:
    """Return whether a dotted config-edit path belongs to the retired hierarchy."""

    normalized = path.strip().lower()
    if normalized in {
        "hostedsettlement",
        "hosted_settlement",
        "oracle_gated_listings",
        "trusted_oracle_address",
        "interruptible_listings",
        "interruptible_oracle_address",
        "settlement.hosted",
        "settlement.mechanism_priority",
    }:
        return True
    if normalized.startswith(
        ("hostedsettlement.", "hosted_settlement.", "settlement.hosted.")
    ):
        return True
    parts = normalized.split(".")
    return (
        len(parts) >= 3
        and parts[0] == "chains"
        and parts[-1] == "alkahest_address_config_path"
    )


def reject_legacy_settlement_path(path: str, *, command: str) -> None:
    """Reject editing a retired key with the exact role migration command."""

    if is_legacy_settlement_path(path):
        raise SettlementMigrationError(
            f"legacy settlement path {path!r} is not supported; run `{command}`"
        )


def environment_renames(
    environ: Mapping[str, str], *, role: SettlementRole
) -> tuple[EnvironmentRename, ...]:
    """Project legacy marketplace environment names without reading their values.

    Hosted-service-owned ``HOSTED_SETTLEMENT_*`` variables are intentionally not
    marketplace aliases and are therefore never returned.
    """

    renames: list[EnvironmentRename] = []
    if role == "seller":
        exact = {
            "STOREFRONT_ORACLE_GATED_LISTINGS": (
                "STOREFRONT_SETTLEMENT__ALKAHEST__ORACLE_GATED"
            ),
            "STOREFRONT_TRUSTED_ORACLE_ADDRESS": (
                "STOREFRONT_SETTLEMENT__ALKAHEST__TRUSTED_ORACLE_ADDRESSES"
            ),
            "STOREFRONT_INTERRUPTIBLE_LISTINGS": (
                "STOREFRONT_SETTLEMENT__ALKAHEST__INTERRUPTIBLE"
            ),
            "STOREFRONT_INTERRUPTIBLE_ORACLE_ADDRESS": (
                "STOREFRONT_SETTLEMENT__ALKAHEST__INTERRUPTIBLE_ORACLE_ADDRESSES"
            ),
        }
        hosted_suffixes = {
            "CONTRACT_VERSION": "EXPECTED_API_VERSION",
            "TIMEOUT_SECONDS": "REQUEST_TIMEOUT_SECONDS",
        }
        for name in environ:
            destination = exact.get(name)
            hosted_prefix = "STOREFRONT_SETTLEMENT__HOSTED__"
            if name.startswith(hosted_prefix):
                suffix = name[len(hosted_prefix) :]
                suffix = hosted_suffixes.get(suffix, suffix)
                destination = f"STOREFRONT_SETTLEMENT__STRIPE__{suffix}"
            if destination is not None:
                renames.append(EnvironmentRename(name, destination))
    else:
        old = "MARKET_SETTLEMENT__MECHANISM_PRIORITY"
        if old in environ:
            renames.append(EnvironmentRename(old, "MARKET_SETTLEMENT__PRIORITY"))
    return tuple(sorted(renames, key=lambda item: item.source))


def _validate_candidate(
    text: str,
    *,
    role: SettlementRole,
    validator: ConfigValidator | None,
) -> Mapping[str, Any]:
    try:
        parsed = tomllib.loads(text)
    except (tomllib.TOMLDecodeError, UnicodeError) as exc:
        raise SettlementMigrationValidationError(
            "migrated configuration is not valid TOML (values redacted)"
        ) from exc

    settlement = parsed.get("Settlement")
    if settlement is not None:
        if not isinstance(settlement, dict):
            raise SettlementMigrationValidationError("Settlement must be a table")
        unknown_sections = set(settlement) - {
            "schema_version",
            "priority",
            "alkahest",
            "stripe",
        }
        if unknown_sections:
            raise SettlementMigrationValidationError(
                "Settlement contains an unknown key (value redacted)"
            )
        schema_version = settlement.get(
            "schema_version", SETTLEMENT_CONFIG_SCHEMA_VERSION
        )
        if (
            type(schema_version) is not int
            or schema_version != SETTLEMENT_CONFIG_SCHEMA_VERSION
        ):
            raise SettlementMigrationValidationError(
                "Settlement.schema_version must match the installed schema"
            )
        priority = settlement.get("priority", [])
        normalized = _normalized_priority(priority)
        if normalized != priority:
            raise SettlementMigrationValidationError(
                "Settlement.priority must use canonical mechanism identifiers"
            )
        for key in ("alkahest", "stripe"):
            section = settlement.get(key)
            if section is not None and not isinstance(section, dict):
                raise SettlementMigrationValidationError(
                    f"Settlement.{key} must be a table"
                )
            if isinstance(section, dict):
                allowed = _ALKAHEST_FIELDS if key == "alkahest" else _STRIPE_FIELDS
                if set(section) - allowed:
                    raise SettlementMigrationValidationError(
                        f"Settlement.{key} contains an unknown key (value redacted)"
                    )
            if isinstance(section, dict) and "enabled" in section and not isinstance(
                section["enabled"], bool
            ):
                raise SettlementMigrationValidationError(
                    f"Settlement.{key}.enabled must be a boolean"
                )
        stripe = settlement.get("stripe")
        if isinstance(stripe, dict) and "authority" in stripe:
            authority = stripe["authority"]
            if not isinstance(authority, dict) or set(authority) - {"principals"}:
                raise SettlementMigrationValidationError(
                    "Settlement.stripe.authority contains an unknown key "
                    "(value redacted)"
                )
        if isinstance(stripe, dict):
            for relative, _value in _plain_leaves(stripe):
                if any(
                    token in part.lower()
                    for part in relative
                    for token in _FORBIDDEN_STRIPE_KEY_PARTS
                ):
                    raise SettlementMigrationValidationError(
                        "Settlement.stripe contains a forbidden provider or secret key (value redacted)"
                    )

    _reject_remaining_legacy(parsed)
    if validator is not None:
        try:
            validator(parsed, role)
        except SettlementMigrationError:
            raise
        except Exception as exc:
            raise SettlementMigrationValidationError(
                "migrated configuration failed typed validation (values redacted)"
            ) from exc
    return parsed


def _plain_leaves(
    table: Mapping[str, Any], prefix: tuple[str, ...] = ()
) -> list[tuple[tuple[str, ...], Any]]:
    leaves: list[tuple[tuple[str, ...], Any]] = []
    for key, value in table.items():
        path = (*prefix, str(key))
        if isinstance(value, Mapping):
            leaves.extend(_plain_leaves(value, path))
        else:
            leaves.append((path, value))
    return leaves


def _reject_remaining_legacy(parsed: Mapping[str, Any]) -> None:
    for path in _LEGACY_HOSTED_TABLES:
        if _lookup(parsed, path) is not None:
            raise SettlementMigrationValidationError(
                f"legacy settlement path {_path_text(path)} remains"
            )
    for name in _LEGACY_ALKAHEST_FIELDS:
        if name in parsed:
            raise SettlementMigrationValidationError(f"legacy settlement path {name} remains")
    if "settlement" in parsed:
        raise SettlementMigrationValidationError(
            "legacy settlement path settlement remains"
        )
    for chains_name in ("Chains", "chains"):
        chains = parsed.get(chains_name)
        if not isinstance(chains, Mapping):
            continue
        for chain_name, chain in chains.items():
            if isinstance(chain, Mapping) and "alkahest_address_config_path" in chain:
                raise SettlementMigrationValidationError(
                    "legacy settlement path "
                    f"{chains_name}.{chain_name}.alkahest_address_config_path remains"
                )


def _write_all(fd: int, content: bytes) -> None:
    view = memoryview(content)
    while view:
        written = os.write(fd, view)
        if written <= 0:
            raise OSError("short configuration write")
        view = view[written:]


def _fsync_directory(directory: Path) -> None:
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
    fd = os.open(directory, flags)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _create_file(path: Path, content: bytes, mode: int) -> None:
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(path, flags, mode)
    try:
        os.fchmod(fd, mode)
        _write_all(fd, content)
        os.fsync(fd)
    except BaseException:
        os.close(fd)
        path.unlink(missing_ok=True)
        raise
    os.close(fd)


def _write_temp(directory: Path, name: str, content: bytes, mode: int) -> Path:
    fd, raw_path = tempfile.mkstemp(prefix=f".{name}.", suffix=".tmp", dir=directory)
    path = Path(raw_path)
    try:
        os.fchmod(fd, mode)
        _write_all(fd, content)
        os.fsync(fd)
    except BaseException:
        os.close(fd)
        path.unlink(missing_ok=True)
        raise
    os.close(fd)
    return path


def _source_is_unchanged(
    path: Path, original: bytes, original_stat: os.stat_result
) -> bool:
    current = path.lstat()
    signature = (current.st_dev, current.st_ino, current.st_size, current.st_mtime_ns)
    expected = (
        original_stat.st_dev,
        original_stat.st_ino,
        original_stat.st_size,
        original_stat.st_mtime_ns,
    )
    return signature == expected and path.read_bytes() == original


def _atomic_write_with_backup(
    path: Path,
    *,
    original: bytes,
    candidate: bytes,
    original_stat: os.stat_result,
) -> Path:
    source_mode = stat.S_IMODE(original_stat.st_mode)
    mode = source_mode if source_mode & 0o077 == 0 else source_mode & ~0o077
    backup_path = path.with_name(f"{path.name}.bak")
    temporary = _write_temp(path.parent, path.name, candidate, mode)
    backup_created = False
    replaced = False
    try:
        if not _source_is_unchanged(path, original, original_stat):
            raise SettlementMigrationError(
                "configuration changed while migration was being prepared; retry"
            )
        _create_file(backup_path, original, mode)
        backup_created = True
        _fsync_directory(path.parent)
        if not _source_is_unchanged(path, original, original_stat):
            raise SettlementMigrationError(
                "configuration changed while migration was being prepared; retry"
            )
        os.replace(temporary, path)
        replaced = True
        _fsync_directory(path.parent)
        return backup_path
    except BaseException:
        temporary.unlink(missing_ok=True)
        if replaced:
            rollback = _write_temp(path.parent, path.name, original, mode)
            try:
                os.replace(rollback, path)
                _fsync_directory(path.parent)
            finally:
                rollback.unlink(missing_ok=True)
        if backup_created:
            backup_path.unlink(missing_ok=True)
            _fsync_directory(path.parent)
        raise


def migrate_settlement_config(
    path: str | os.PathLike[str],
    *,
    role: SettlementRole,
    check: bool = False,
    write: bool = False,
    backup: bool = False,
    validator: ConfigValidator | None = None,
    environ: Mapping[str, str] | None = None,
) -> SettlementMigrationResult:
    """Check or atomically migrate one role TOML document.

    Exactly one of ``check`` and ``write`` is required. Write mode requires an
    explicit backup opt-in. Candidate validation and all conflict checks happen
    before the first filesystem mutation.
    """

    if check == write:
        raise SettlementMigrationError("choose exactly one of check or write")
    if check and backup:
        raise SettlementMigrationError("backup is only valid with write mode")
    if write and not backup:
        raise SettlementMigrationError("write mode requires backup")
    if role not in ("buyer", "seller"):
        raise SettlementMigrationError("role must be buyer or seller")

    config_path = Path(path)
    try:
        source_stat = config_path.lstat()
    except FileNotFoundError as exc:
        raise SettlementMigrationError(
            f"configuration file does not exist: {config_path}"
        ) from exc
    if stat.S_ISLNK(source_stat.st_mode) or not stat.S_ISREG(source_stat.st_mode):
        raise SettlementMigrationError(
            "configuration path must be a regular, non-symlink file"
        )
    original = config_path.read_bytes()
    try:
        text = original.decode("utf-8")
        document = tomlkit.parse(text)
    except (UnicodeError, tomlkit.exceptions.ParseError) as exc:
        raise SettlementMigrationValidationError(
            "configuration is not valid UTF-8 TOML (values redacted)"
        ) from exc

    planned = copy.deepcopy(document)
    actions = _Planner(planned, role).run()
    candidate_text = tomlkit.dumps(planned)
    _validate_candidate(candidate_text, role=role, validator=validator)
    candidate = candidate_text.encode("utf-8")
    changed = bool(actions)
    renames = environment_renames(environ or {}, role=role)

    if check or not changed:
        return SettlementMigrationResult(
            path=config_path,
            changed=changed,
            written=False,
            actions=actions,
            environment_renames=renames,
        )
    if validator is None:
        raise SettlementMigrationValidationError(
            "write mode requires a typed settlement candidate validator"
        )

    backup_path = _atomic_write_with_backup(
        config_path,
        original=original,
        candidate=candidate,
        original_stat=source_stat,
    )
    return SettlementMigrationResult(
        path=config_path,
        changed=True,
        written=True,
        actions=actions,
        backup_path=backup_path,
        environment_renames=renames,
    )


def format_migration_result(result: SettlementMigrationResult) -> tuple[str, ...]:
    """Render a sanitized, deterministic CLI report."""

    lines: list[str] = []
    for action in result.actions:
        if action.destination is None:
            lines.append(f"remove {action.source} (value redacted)")
        else:
            lines.append(
                f"move {action.source} -> {action.destination} (value redacted)"
            )
    for rename in result.environment_renames:
        lines.append(
            f"rename environment {rename.source} -> {rename.destination} (value redacted)"
        )
    if not result.changed:
        lines.append("No settlement configuration migration changes.")
    elif result.written:
        lines.append(f"Migrated {result.path} atomically.")
        if result.backup_path is not None:
            lines.append(f"Backup: {result.backup_path}")
    else:
        lines.append(f"Settlement configuration migration required for {result.path}.")
    return tuple(lines)
