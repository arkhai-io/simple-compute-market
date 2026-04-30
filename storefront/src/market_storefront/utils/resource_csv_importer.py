from __future__ import annotations

import csv
import json
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, TYPE_CHECKING

from market_storefront.resources import get_resource_adapter

if TYPE_CHECKING:
    from market_storefront.utils.sqlite_client import SQLiteClient


CORE_COLUMNS = {
    "resource_id",
    "resource_type",
    "resource_subtype",
    "unit",
    "value",
    "state",
    "min_price",
    "token",
}

ATTRIBUTE_PREFIX = "attribute."


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


def _build_db_resource_from_csv_row(row: dict[str, Any]) -> dict[str, Any]:
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

    value: int | float | None = None
    if value_raw:
        value = _parse_numeric(value_raw)

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
    }


async def upsert_resources_from_csv(
    *,
    csv_path: str,
    sqlite_client: "SQLiteClient",
    dry_run: bool = False,
) -> ImportReport:
    path = Path(csv_path)
    if not path.exists():
        raise FileNotFoundError(f"CSV not found: {csv_path}")

    report = ImportReport(csv_path=str(path), dry_run=dry_run)

    with path.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
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
                db_resource = _build_db_resource_from_csv_row(raw_row)
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
