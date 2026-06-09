"""CSV importer for hosts.csv — parses host hardware metadata into the
storefront's ``hosts`` table.

A ``hosts.csv`` row defines one physical host the seller owns. Bare columns
map to typed columns on the hosts table; ``attribute.*`` columns become
free-form key/value entries in the host's ``attributes`` JSON, with the
``tag.*`` namespace reserved for provider-specific filterable metadata.

Operator workflow (mirrors provisioning-service's two-step flow):

  1. ``POST /hosts/`` registers the host with the provisioning-service.
  2. Import ``hosts.csv`` into the storefront so listings can reference the
     host by name and the buyer-facing wire format gets the full host
     context denormalized at publish time.
"""
from __future__ import annotations

import csv
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol


class HostStore(Protocol):
    async def upsert_host(self, **kwargs: Any) -> Any:
        ...


CORE_COLUMNS = {
    "name",
    "enabled",
    "cpu_type",
    "host_cpu_cores",
    "host_ram_gb",
    "host_disk_gb",
    "host_disk_type",
    "motherboard",
    "total_gpu_count",
    "gpu_model",
    "gpu_interconnect",
    "nic_speed_gbps",
    "internet_download_mbps",
    "internet_upload_mbps",
    "static_ip",
    "open_ports_count",
    "region",
    "datacenter_grade",
}

INT_COLUMNS = {
    "host_cpu_cores",
    "host_ram_gb",
    "host_disk_gb",
    "total_gpu_count",
    "nic_speed_gbps",
    "internet_download_mbps",
    "internet_upload_mbps",
    "open_ports_count",
}

BOOL_COLUMNS = {
    "static_ip",
    "datacenter_grade",
    "enabled",
}

ATTRIBUTE_PREFIX = "attribute."


@dataclass
class HostImportRowResult:
    row_number: int
    name: str | None
    imported: bool
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "row_number": self.row_number,
            "name": self.name,
            "imported": self.imported,
            "errors": self.errors,
            "warnings": self.warnings,
        }


@dataclass
class HostImportReport:
    csv_path: str
    dry_run: bool
    total_rows: int = 0
    imported_count: int = 0
    failed_count: int = 0
    rows: list[HostImportRowResult] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "csv_path": self.csv_path,
            "dry_run": self.dry_run,
            "total_rows": self.total_rows,
            "imported_count": self.imported_count,
            "failed_count": self.failed_count,
            "rows": [r.to_dict() for r in self.rows],
        }


def _clean(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _parse_bool(raw: str) -> bool:
    lowered = raw.lower()
    if lowered in ("true", "1", "yes", "y", "t"):
        return True
    if lowered in ("false", "0", "no", "n", "f"):
        return False
    raise ValueError(f"Cannot parse boolean value '{raw}'")


def _parse_attribute_value(raw: str) -> Any:
    try:
        return json.loads(raw)
    except Exception:
        return raw


def _build_host_kwargs(row: dict[str, Any]) -> dict[str, Any]:
    name = _clean(row.get("name"))
    if not name:
        raise ValueError("Missing required column: name")

    kwargs: dict[str, Any] = {"name": name}

    for col in CORE_COLUMNS:
        if col == "name":
            continue
        raw = _clean(row.get(col))
        if not raw:
            continue
        try:
            if col in INT_COLUMNS:
                kwargs[col] = int(raw)
            elif col in BOOL_COLUMNS:
                kwargs[col] = _parse_bool(raw)
            else:
                kwargs[col] = raw
        except ValueError as exc:
            raise ValueError(f"Invalid value for '{col}': {exc}") from exc

    attributes: dict[str, Any] = {}
    for key, raw_val in row.items():
        if not isinstance(key, str) or not key.startswith(ATTRIBUTE_PREFIX):
            continue
        attr_key = key[len(ATTRIBUTE_PREFIX):].strip()
        if not attr_key:
            continue
        cell = _clean(raw_val)
        if not cell:
            continue
        attributes[attr_key] = _parse_attribute_value(cell)
    if attributes:
        kwargs["attributes"] = attributes

    return kwargs


async def upsert_hosts_from_csv(
    *,
    csv_path: str,
    sqlite_client: HostStore,
    dry_run: bool = False,
) -> HostImportReport:
    """Import host rows from CSV into the storefront's hosts table.

    Idempotent — re-importing the same CSV updates existing rows by name.
    """
    path = Path(csv_path)
    if not path.exists():
        raise FileNotFoundError(f"CSV not found: {csv_path}")

    report = HostImportReport(csv_path=str(path), dry_run=dry_run)

    with path.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        fieldnames = set(reader.fieldnames or [])
        if "name" not in fieldnames:
            raise ValueError("hosts CSV missing required column: name")

        for i, raw_row in enumerate(reader, start=2):
            report.total_rows += 1
            row_result = HostImportRowResult(row_number=i, name=None, imported=False)
            try:
                kwargs = _build_host_kwargs(raw_row)
                row_result.name = kwargs["name"]
                if not dry_run:
                    await sqlite_client.upsert_host(**kwargs)
                else:
                    row_result.warnings.append("Dry-run: row validated but not persisted.")
                row_result.imported = True
                report.imported_count += 1
            except Exception as exc:
                row_result.errors.append(str(exc))
                report.failed_count += 1
            report.rows.append(row_result)

    return report
