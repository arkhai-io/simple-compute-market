from __future__ import annotations

import csv
import json
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping, Protocol

from domains.vms.listings.resources import get_resource_adapter


class ResourceStore(Protocol):
    async def upsert_resource(self, **kwargs: Any) -> Any:
        ...


class EscrowTemplateRateSlot(Protocol):
    field: str
    per: str


class EscrowTemplateLike(Protocol):
    chain: str
    escrow_address: str
    literal_fields: Mapping[str, Any]
    rate_slots: Mapping[str, EscrowTemplateRateSlot]


CORE_COLUMNS = {
    "resource_id",
    "resource_type",
    "resource_subtype",
    "unit",
    "value",
    "state",
    "min_price",
    "token",
    "max_duration_seconds",
    "accepted_escrows",
}

ATTRIBUTE_PREFIX = "attribute."


def parse_accepted_escrows_cell(
    cell: str,
    templates: Mapping[str, EscrowTemplateLike],
) -> list[dict[str, Any]]:
    """Parse one ``accepted_escrows`` CSV cell into materialized entries.

    Grammar (whitespace tolerant)::

        cell  = entry (";" entry)*
        entry = name [":" slot ("," slot)* | "=" value]
        slot  = slot_name "=" value

    Three reference forms map onto template rate-slot counts:

    - ``name:s1=v1,s2=v2``  — explicit named slots (any slot count)
    - ``name=v``            — single-slot ergonomic sugar
                              (template must have exactly one rate slot)
    - ``name``              — zero-slot attestation form
                              (template must have zero rate slots)

    Each parsed entry expands into the same wire shape ``cli_publish`` /
    ``synthesize_accepted_escrows_from_demand`` emit: ``chain_name``,
    ``escrow_address``, ``literal_fields``, ``rates``. Errors mean the
    cell is rejected wholesale (the CSV row marks invalid); we don't
    half-publish a row with one good entry and one bad.
    """
    out: list[dict[str, Any]] = []
    raw = (cell or "").strip()
    if not raw:
        return out
    for piece in raw.split(";"):
        entry = piece.strip()
        if not entry:
            continue
        out.append(_materialize_entry(entry, templates))
    return out


def _materialize_entry(
    entry: str,
    templates: Mapping[str, EscrowTemplateLike],
) -> dict[str, Any]:
    colon = entry.find(":")
    equals = entry.find("=")
    has_colon = colon != -1 and (equals == -1 or colon < equals)
    if has_colon:
        name = entry[:colon].strip()
        slot_blob = entry[colon + 1 :].strip()
        slot_values = _parse_slot_list(name, slot_blob)
    elif equals != -1:
        name = entry[:equals].strip()
        value = entry[equals + 1 :].strip()
        slot_values = {"__sugar__": value}
    else:
        name = entry.strip()
        slot_values = {}

    if not name:
        raise ValueError(f"accepted_escrows entry missing template name: {entry!r}")
    template = templates.get(name)
    if template is None:
        raise ValueError(
            f"accepted_escrows: unknown template {name!r}; "
            f"known templates: {sorted(templates)}"
        )

    rate_slots = template.rate_slots
    if "__sugar__" in slot_values:
        if len(rate_slots) != 1:
            raise ValueError(
                f"accepted_escrows: bare value form '{name}=...' requires "
                f"the template to have exactly one rate slot "
                f"(template {name!r} has {len(rate_slots)})"
            )
        sole_slot = next(iter(rate_slots))
        slot_values = {sole_slot: slot_values["__sugar__"]}
    elif not slot_values and rate_slots:
        raise ValueError(
            f"accepted_escrows: bare template form {name!r} requires zero "
            f"rate slots (template {name!r} has {len(rate_slots)}: "
            f"{sorted(rate_slots)})"
        )

    extra = set(slot_values) - set(rate_slots)
    if extra:
        raise ValueError(
            f"accepted_escrows: template {name!r} got unknown slot(s) "
            f"{sorted(extra)}; expected {sorted(rate_slots)}"
        )
    missing = set(rate_slots) - set(slot_values)
    if missing:
        raise ValueError(
            f"accepted_escrows: template {name!r} missing slot(s) "
            f"{sorted(missing)}; expected {sorted(rate_slots)}"
        )

    rates: list[dict[str, Any]] = []
    for slot_name, slot in rate_slots.items():
        rates.append({
            "field": slot.field,
            "per": slot.per,
            "value": slot_values[slot_name],
        })
    return {
        "chain_name": template.chain,
        "escrow_address": template.escrow_address.lower(),
        "literal_fields": dict(template.literal_fields),
        "rates": rates,
    }


def _parse_slot_list(template_name: str, slot_blob: str) -> dict[str, str]:
    if not slot_blob:
        raise ValueError(
            f"accepted_escrows: template {template_name!r} has ':' but no "
            f"slot assignments"
        )
    out: dict[str, str] = {}
    for piece in slot_blob.split(","):
        slot = piece.strip()
        if not slot:
            continue
        if "=" not in slot:
            raise ValueError(
                f"accepted_escrows: template {template_name!r} slot {slot!r} "
                f"is missing '='"
            )
        key, value = slot.split("=", 1)
        key = key.strip()
        value = value.strip()
        if not key:
            raise ValueError(
                f"accepted_escrows: template {template_name!r} has empty "
                f"slot name in {piece!r}"
            )
        if key in out:
            raise ValueError(
                f"accepted_escrows: template {template_name!r} slot {key!r} "
                f"specified more than once"
            )
        out[key] = value
    return out


@dataclass
class ImportRowResult:
    row_number: int
    resource_id: str | None
    resource_type: str | None
    imported: bool
    schema_status: str  # matched | unrecognized | invalid
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "row_number": self.row_number,
            "resource_id": self.resource_id,
            "resource_type": self.resource_type,
            "imported": self.imported,
            "schema_status": self.schema_status,
            "errors": self.errors,
            "warnings": self.warnings,
        }


@dataclass
class ImportReport:
    csv_path: str
    dry_run: bool
    total_rows: int = 0
    imported_count: int = 0
    failed_count: int = 0
    matched_count: int = 0
    unrecognized_count: int = 0
    invalid_count: int = 0
    rows: list[ImportRowResult] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "csv_path": self.csv_path,
            "dry_run": self.dry_run,
            "total_rows": self.total_rows,
            "imported_count": self.imported_count,
            "failed_count": self.failed_count,
            "matched_count": self.matched_count,
            "unrecognized_count": self.unrecognized_count,
            "invalid_count": self.invalid_count,
            "rows": [row.to_dict() for row in self.rows],
        }


def _clean_cell(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _parse_numeric(value: str) -> int | float:
    try:
        if any(ch in value for ch in (".", "e", "E")):
            return float(value)
        return int(value)
    except Exception as exc:
        raise ValueError(f"Invalid numeric value '{value}'") from exc


def _parse_attribute_value(raw: str) -> Any:
    # Try JSON first for booleans, numbers, objects, arrays, null.
    try:
        return json.loads(raw)
    except Exception:
        return raw


def _build_db_resource_from_csv_row(
    row: dict[str, Any],
    templates: Mapping[str, EscrowTemplateLike] | None = None,
) -> dict[str, Any]:
    resource_id = _clean_cell(row.get("resource_id"))
    resource_type = _clean_cell(row.get("resource_type"))
    if not resource_id:
        resource_id = str(uuid.uuid4())
    if not resource_type:
        raise ValueError("Missing required column value: resource_type")

    resource_subtype_raw = _clean_cell(row.get("resource_subtype"))
    unit_raw = _clean_cell(row.get("unit"))
    value_raw = _clean_cell(row.get("value"))
    state_raw = _clean_cell(row.get("state"))
    min_price_raw = _clean_cell(row.get("min_price"))
    token_raw = _clean_cell(row.get("token"))
    if token_raw:
        if not token_raw.startswith("0x") or len(token_raw) != 42:
            raise ValueError(
                f"Invalid token {token_raw!r} — the `token` column must be "
                f"a 0x ERC-20 address. Symbol shorthand (e.g. 'USDC') is "
                f"no longer supported."
            )
    max_duration_seconds_raw = _clean_cell(row.get("max_duration_seconds"))

    value: int | float | None = None
    if value_raw:
        value = _parse_numeric(value_raw)

    max_duration_seconds: int | None = None
    if max_duration_seconds_raw:
        try:
            max_duration_seconds = int(max_duration_seconds_raw)
        except ValueError as exc:
            raise ValueError(
                f"Invalid max_duration_seconds '{max_duration_seconds_raw}' (must be an integer)"
            ) from exc

    attributes: dict[str, Any] = {}
    for key, raw in row.items():
        if not isinstance(key, str):
            continue
        if not key.startswith(ATTRIBUTE_PREFIX):
            continue
        attr_key = key[len(ATTRIBUTE_PREFIX) :].strip()
        if not attr_key:
            continue
        cell = _clean_cell(raw)
        if not cell:
            continue
        attributes[attr_key] = _parse_attribute_value(cell)

    accepted_escrows_raw = _clean_cell(row.get("accepted_escrows"))
    accepted_escrows: list[dict[str, Any]] | None = None
    if accepted_escrows_raw:
        if templates is None:
            raise ValueError(
                "accepted_escrows column present but no escrow_templates "
                "configured; add [escrow_templates.<name>] entries to the "
                "storefront config or drop the column"
            )
        accepted_escrows = parse_accepted_escrows_cell(
            accepted_escrows_raw, templates,
        )

    return {
        "resource_id": resource_id,
        "resource_type": resource_type,
        "resource_subtype": resource_subtype_raw or None,
        "unit": unit_raw or None,
        "value": value,
        "state": state_raw or None,
        "attributes": attributes or None,
        "min_price": min_price_raw or None,
        "token": token_raw or None,
        "max_duration_seconds": max_duration_seconds,
        "accepted_escrows": accepted_escrows,
    }


async def upsert_resources_from_csv(
    *,
    csv_path: str,
    sqlite_client: ResourceStore,
    dry_run: bool = False,
    templates: Mapping[str, EscrowTemplateLike] | None = None,
) -> ImportReport:
    path = Path(csv_path)
    if not path.exists():
        raise FileNotFoundError(f"CSV not found: {csv_path}")

    with path.open("r", encoding="utf-8", newline="") as f:
        content = f.read()

    return await upsert_resources_from_csv_content(
        csv_content=content,
        source_label=str(path),
        sqlite_client=sqlite_client,
        dry_run=dry_run,
        templates=templates,
    )


async def upsert_resources_from_csv_content(
    *,
    csv_content: str,
    source_label: str = "<inline>",
    sqlite_client: ResourceStore,
    dry_run: bool = False,
    templates: Mapping[str, EscrowTemplateLike] | None = None,
) -> ImportReport:
    """Import resources from a CSV string and upsert rows into the resources table.

    Counterpart to ``upsert_resources_from_csv`` for content delivered via
    config injection (e.g. the Helm ``resources_csv_inline`` setting) rather
    than a file path baked into the container image.
    """
    import io

    report = ImportReport(csv_path=source_label, dry_run=dry_run)

    reader = csv.DictReader(io.StringIO(csv_content))
    fieldnames = set(reader.fieldnames or [])
    missing = {"resource_type"} - fieldnames
    if missing:
        raise ValueError(f"CSV missing required columns: {sorted(missing)}")

    for i, raw_row in enumerate(reader, start=2):
        report.total_rows += 1
        row_result = ImportRowResult(
            row_number=i,
            resource_id=None,
            resource_type=None,
            imported=False,
            schema_status="invalid",
        )
        try:
            db_resource = _build_db_resource_from_csv_row(raw_row, templates)
            row_result.resource_id = str(db_resource["resource_id"])
            row_result.resource_type = str(db_resource["resource_type"])

            adapter = get_resource_adapter(str(db_resource["resource_type"]))
            if adapter is not None:
                # Schema recognized: validate by adapting into domain model.
                adapter.to_domain_resource(db_resource)
                row_result.schema_status = "matched"
                report.matched_count += 1
            else:
                # Schema unrecognized: permissive import.
                row_result.schema_status = "unrecognized"
                row_result.warnings.append(
                    f"Unrecognized schema for resource_type '{db_resource['resource_type']}'. Imported permissively."
                )
                report.unrecognized_count += 1

            if not dry_run:
                await sqlite_client.upsert_resource(
                    resource_id=str(db_resource["resource_id"]),
                    resource_type=str(db_resource["resource_type"]),
                    resource_subtype=db_resource.get("resource_subtype"),
                    unit=db_resource.get("unit"),
                    value=db_resource.get("value"),
                    state=db_resource.get("state"),
                    attributes=db_resource.get("attributes"),
                    min_price=db_resource.get("min_price"),
                    token=db_resource.get("token"),
                    max_duration_seconds=db_resource.get("max_duration_seconds"),
                    accepted_escrows=db_resource.get("accepted_escrows"),
                )
            else:
                row_result.warnings.append("Dry-run mode: row validated but not persisted.")
            row_result.imported = True
            report.imported_count += 1
        except Exception as exc:
            row_result.imported = False
            row_result.schema_status = "invalid"
            row_result.errors.append(str(exc))
            report.failed_count += 1
            report.invalid_count += 1
        report.rows.append(row_result)

    return report
