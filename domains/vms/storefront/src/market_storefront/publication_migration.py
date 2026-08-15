"""Restrictive migration of legacy publication pricing into typed clauses."""

from __future__ import annotations

import copy
import csv
import io
import json
import os
import re
import stat
from collections.abc import Callable, Mapping, MutableMapping
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Literal

import tomlkit
import tomllib
from market_config import (
    SettlementMigrationError,
    SettlementMigrationValidationError,
    atomic_write_with_backup,
)
from market_settlement_runtime import SettlementPublicationClause

_ALKAHEST = "alkahest.v1"
_STRIPE = "fiat.stripe.v1"
_EVM_ADDRESS = re.compile(r"0x[0-9a-fA-F]{40}")
_ZERO_DECIMAL_CURRENCIES = frozenset(
    {
        "bif",
        "clp",
        "djf",
        "gnf",
        "jpy",
        "kmf",
        "krw",
        "mga",
        "pyg",
        "rwf",
        "ugx",
        "vnd",
        "vuv",
        "xaf",
        "xof",
        "xpf",
    }
)
_THREE_DECIMAL_CURRENCIES = frozenset({"bhd", "jod", "kwd", "omr", "tnd"})


@dataclass(frozen=True, slots=True)
class PublicationMigrationResult:
    path: Path
    kind: Literal["toml", "csv"]
    changed: bool
    written: bool
    actions: tuple[str, ...]
    conflicts: tuple[str, ...]
    backup_path: Path | None = None


def _mode(
    *,
    check: bool,
    write: bool,
    backup: bool,
) -> None:
    if check == write:
        raise SettlementMigrationError("choose exactly one of check or write")
    if check and backup:
        raise SettlementMigrationError("backup is only valid with write mode")
    if write and not backup:
        raise SettlementMigrationError("write mode requires backup")


def _read_regular(path: Path) -> tuple[os.stat_result, bytes]:
    try:
        source_stat = path.lstat()
    except FileNotFoundError as exc:
        raise SettlementMigrationError(
            f"migration input does not exist: {path}"
        ) from exc
    if stat.S_ISLNK(source_stat.st_mode) or not stat.S_ISREG(source_stat.st_mode):
        raise SettlementMigrationError(
            "migration input must be a regular, non-symlink file"
        )
    return source_stat, path.read_bytes()


def _table(document: Mapping[str, Any], canonical: str) -> Mapping[str, Any] | None:
    present = [name for name in (canonical, canonical.lower()) if name in document]
    if len(present) > 1:
        raise SettlementMigrationValidationError(
            f"conflicting configuration tables {present[0]} and {present[1]}"
        )
    if not present:
        return None
    value = document[present[0]]
    if not isinstance(value, Mapping):
        raise SettlementMigrationValidationError(f"{present[0]} must be a table")
    return value


def _mutable_table(
    document: MutableMapping[str, Any], canonical: str
) -> MutableMapping[str, Any]:
    present = [name for name in (canonical, canonical.lower()) if name in document]
    if len(present) > 1:
        raise SettlementMigrationValidationError(
            f"conflicting configuration tables {present[0]} and {present[1]}"
        )
    name = present[0] if present else canonical
    if name not in document:
        document[name] = tomlkit.table()
    value = document[name]
    if not isinstance(value, MutableMapping):
        raise SettlementMigrationValidationError(f"{name} must be a table")
    return value


def _plain(value: Any) -> Any:
    unwrap = getattr(value, "unwrap", None)
    return unwrap() if callable(unwrap) else value


def _currency_exponent(currency: str) -> int | None:
    if len(currency) != 3 or not currency.islower() or not currency.isalpha():
        return None
    if currency in _ZERO_DECIMAL_CURRENCIES:
        return 0
    if currency in _THREE_DECIMAL_CURRENCIES:
        return 3
    return 2


def _decimal_text(value: Decimal) -> str:
    text = format(value, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text


def _legacy_context(
    config: Mapping[str, Any],
) -> tuple[str | None, dict[str, Any], tuple[str, ...]]:
    settlement = _table(config, "Settlement") or {}
    enabled: list[str] = []
    for key, mechanism in (("alkahest", _ALKAHEST), ("stripe", _STRIPE)):
        section = settlement.get(key)
        if isinstance(section, Mapping) and _plain(section.get("enabled")) is True:
            enabled.append(mechanism)
    if len(enabled) > 1:
        return None, {}, ("dual-mechanism publication requires manual clauses",)
    if not enabled:
        return (
            None,
            {},
            ("no enabled settlement mechanism can interpret legacy pricing",),
        )

    mechanism = enabled[0]
    if mechanism == _STRIPE:
        stripe = settlement.get("stripe")
        currency = (
            _plain(stripe.get("currency")) if isinstance(stripe, Mapping) else None
        )
        exponent = _currency_exponent(currency) if isinstance(currency, str) else None
        if exponent is None:
            return None, {}, ("Stripe currency scale is missing or unsupported",)
        return mechanism, {"asset": currency, "exponent": exponent}, ()

    chains = _table(config, "Chains") or {}
    chain_names = [
        str(name) for name, value in chains.items() if isinstance(value, Mapping)
    ]
    if len(chain_names) != 1:
        return None, {}, ("Alkahest migration requires exactly one configured chain",)
    return mechanism, {"chain": chain_names[0]}, ()


def _per_model_legacy_conflicts(
    pricing: Mapping[str, Any],
) -> tuple[str, ...]:
    defaults = _table(pricing, "Defaults")
    if defaults is None:
        return ()
    gpu = _table(defaults, "GPU")
    if not gpu:
        return ()
    models = sorted(str(model) for model in gpu)
    return (
        "per-model legacy pricing requires manual clauses: "
        + ", ".join(f"Pricing.defaults.gpu.{model}" for model in models),
    )


def _clause_for_legacy_price(
    *,
    mechanism: str,
    context: Mapping[str, Any],
    min_price: Any,
    token: Any,
) -> SettlementPublicationClause:
    raw_price = _plain(min_price)
    if raw_price is None or str(raw_price).strip() == "":
        raise ValueError("hidden-reserve pricing has no explicit rate")
    try:
        amount = Decimal(str(raw_price))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError("legacy price is not decimal text") from exc
    if not amount.is_finite() or amount <= 0:
        raise ValueError("legacy price must be positive")

    if mechanism == _STRIPE:
        exponent = int(context["exponent"])
        if amount != amount.to_integral_value():
            raise ValueError("legacy Stripe price is not an integer minor-unit amount")
        return SettlementPublicationClause(
            mechanism=mechanism,
            asset=str(context["asset"]),
            rate=_decimal_text(amount / (Decimal(10) ** exponent)),
            per="hour",
            mechanism_input={
                "funding_profile": "card.v1",
                "interaction": "interactive",
                "funds_flow": "separate_charges_transfers",
            },
        )

    asset = _plain(token)
    if not isinstance(asset, str) or not _EVM_ADDRESS.fullmatch(asset):
        raise ValueError(
            "Alkahest token address must be a canonical 20-byte hexadecimal address"
        )
    asset = asset.lower()
    return SettlementPublicationClause(
        mechanism=mechanism,
        asset=asset,
        rate=_decimal_text(amount),
        per="hour",
        mechanism_input={
            "chain": str(context["chain"]),
            "escrow_kind": "erc20_escrow_obligation_default",
        },
    )


def migrate_publication_config(
    path: str | os.PathLike[str],
    *,
    check: bool = False,
    write: bool = False,
    backup: bool = False,
    validator: Callable[[Mapping[str, Any], str], None] | None = None,
) -> PublicationMigrationResult:
    """Migrate one unambiguous storefront pricing default without guessing."""

    _mode(check=check, write=write, backup=backup)
    config_path = Path(path)
    source_stat, original = _read_regular(config_path)
    try:
        text = original.decode("utf-8")
        document = tomlkit.parse(text)
    except (UnicodeError, tomlkit.exceptions.ParseError) as exc:
        raise SettlementMigrationValidationError(
            "configuration is not valid UTF-8 TOML"
        ) from exc

    pricing = _table(document, "Pricing") or {}
    per_model_conflicts = _per_model_legacy_conflicts(pricing)
    if per_model_conflicts:
        if write:
            raise SettlementMigrationValidationError("; ".join(per_model_conflicts))
        return PublicationMigrationResult(
            config_path, "toml", False, False, (), per_model_conflicts
        )
    existing = _plain(pricing.get("settlements"))
    if isinstance(existing, list) and existing:
        return PublicationMigrationResult(config_path, "toml", False, False, (), ())
    has_legacy = (
        any(
            _plain(pricing.get(name)) not in (None, "")
            for name in ("default_min_price", "default_token_address")
        )
        or _plain(pricing.get("publish_priceless")) is True
    )
    if not has_legacy:
        return PublicationMigrationResult(config_path, "toml", False, False, (), ())

    mechanism, context, conflicts = _legacy_context(document)
    clause: SettlementPublicationClause | None = None
    if not conflicts and mechanism is not None:
        try:
            clause = _clause_for_legacy_price(
                mechanism=mechanism,
                context=context,
                min_price=pricing.get("default_min_price"),
                token=pricing.get("default_token_address"),
            )
        except ValueError as exc:
            conflicts = (str(exc),)
    if conflicts:
        if write:
            raise SettlementMigrationValidationError("; ".join(conflicts))
        return PublicationMigrationResult(
            config_path, "toml", False, False, (), conflicts
        )
    assert clause is not None

    planned = copy.deepcopy(document)
    planned_pricing = _mutable_table(planned, "Pricing")
    planned_pricing["settlements"] = [
        clause.model_dump(mode="json", exclude_defaults=True)
    ]
    candidate_text = tomlkit.dumps(planned)
    parsed_candidate = tomllib.loads(candidate_text)
    if validator is not None:
        validator(parsed_candidate, "seller")
    candidate = candidate_text.encode("utf-8")
    action = f"Pricing.settlements <- {mechanism}"
    if check:
        return PublicationMigrationResult(
            config_path, "toml", True, False, (action,), ()
        )
    if validator is None:
        raise SettlementMigrationValidationError(
            "write mode requires a typed storefront candidate validator"
        )
    backup_path = atomic_write_with_backup(
        config_path,
        original=original,
        candidate=candidate,
        original_stat=source_stat,
    )
    return PublicationMigrationResult(
        config_path, "toml", True, True, (action,), (), backup_path
    )


def migrate_publication_csv(
    path: str | os.PathLike[str],
    *,
    storefront_config: Mapping[str, Any],
    check: bool = False,
    write: bool = False,
    backup: bool = False,
    clause_compiler: Callable[[Mapping[str, Any]], SettlementPublicationClause]
    | None = None,
) -> PublicationMigrationResult:
    """Migrate only rows whose legacy pricing has one exact interpretation."""

    _mode(check=check, write=write, backup=backup)
    csv_path = Path(path)
    source_stat, original = _read_regular(csv_path)
    try:
        text = original.decode("utf-8")
    except UnicodeError as exc:
        raise SettlementMigrationValidationError("inventory CSV is not UTF-8") from exc
    reader = csv.DictReader(io.StringIO(text, newline=""))
    if reader.fieldnames is None:
        raise SettlementMigrationValidationError("inventory CSV has no header")
    rows = list(reader)
    fieldnames = list(reader.fieldnames)
    if "settlements" not in fieldnames:
        fieldnames.append("settlements")

    mechanism, context, context_conflicts = _legacy_context(storefront_config)
    actions: list[str] = []
    conflicts: list[str] = []
    for index, row in enumerate(rows, start=2):
        existing = (row.get("settlements") or "").strip()
        legacy_accepted_escrows = (row.get("accepted_escrows") or "").strip()
        if legacy_accepted_escrows:
            conflicts.append(
                f"row {index}: accepted_escrows requires manual settlement clauses"
            )
        if existing:
            try:
                parsed = json.loads(existing)
                if not isinstance(parsed, list):
                    raise ValueError("settlements must be an array")
                if clause_compiler is None:
                    raise ValueError("a resolved seller clause compiler is required")
                for value in parsed:
                    if not isinstance(value, Mapping):
                        raise ValueError("each settlement clause must be an object")
                    compiled = clause_compiler(value)
                    if not isinstance(compiled, SettlementPublicationClause):
                        raise TypeError(
                            "seller clause compiler returned an invalid clause"
                        )
            except (ValueError, TypeError) as exc:
                conflicts.append(f"row {index}: settlements is invalid: {exc}")
            continue
        if legacy_accepted_escrows:
            continue
        if (
            not (row.get("min_price") or "").strip()
            and not (row.get("token") or "").strip()
        ):
            continue
        if context_conflicts or mechanism is None:
            conflicts.append(f"row {index}: {context_conflicts[0]}")
            continue
        try:
            clause = _clause_for_legacy_price(
                mechanism=mechanism,
                context=context,
                min_price=row.get("min_price"),
                token=row.get("token"),
            )
            if clause_compiler is None:
                raise ValueError("a resolved seller clause compiler is required")
            clause = clause_compiler(clause.model_dump(mode="json"))
            if not isinstance(clause, SettlementPublicationClause):
                raise TypeError("seller clause compiler returned an invalid clause")
        except (ValueError, TypeError) as exc:
            conflicts.append(f"row {index}: {exc}")
            continue
        row["settlements"] = json.dumps(
            [clause.model_dump(mode="json", exclude_defaults=True)],
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        actions.append(f"row {index}: settlements <- {mechanism}")

    if conflicts:
        if write:
            raise SettlementMigrationValidationError("; ".join(conflicts))
        return PublicationMigrationResult(
            csv_path, "csv", bool(actions), False, tuple(actions), tuple(conflicts)
        )
    if not actions:
        return PublicationMigrationResult(csv_path, "csv", False, False, (), ())

    output = io.StringIO(newline="")
    writer = csv.DictWriter(
        output,
        fieldnames=fieldnames,
        lineterminator="\r\n" if "\r\n" in text else "\n",
    )
    writer.writeheader()
    writer.writerows(rows)
    candidate = output.getvalue().encode("utf-8")
    if check:
        return PublicationMigrationResult(
            csv_path, "csv", True, False, tuple(actions), ()
        )
    backup_path = atomic_write_with_backup(
        csv_path,
        original=original,
        candidate=candidate,
        original_stat=source_stat,
    )
    return PublicationMigrationResult(
        csv_path, "csv", True, True, tuple(actions), (), backup_path
    )


def format_publication_migration_result(
    result: PublicationMigrationResult,
) -> tuple[str, ...]:
    lines = [*result.actions, *(f"CONFLICT: {item}" for item in result.conflicts)]
    if result.written:
        lines.append(f"Migrated {result.path} atomically.")
        lines.append(f"Backup: {result.backup_path}")
    elif result.changed and not result.conflicts:
        lines.append(f"Publication migration required for {result.path}.")
    elif not result.changed and not result.conflicts:
        lines.append(f"No publication migration required for {result.path}.")
    return tuple(lines)
