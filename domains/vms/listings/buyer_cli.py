"""VM-domain buyer/listing CLI helpers.

The compatibility ``buyer/`` package still owns Typer command wiring for
now. VM listing semantics live here: named filter flags and rendering of
VM offer resources, accepted escrows, and demands.
"""

from __future__ import annotations

import json
from typing import Any


def build_vm_filter_params(
    *,
    gpu_model: str | None = None,
    gpu_count_min: int | float | None = None,
    vcpu_count_min: int | float | None = None,
    ram_gb_min: int | float | None = None,
    disk_gb_min: int | float | None = None,
    region: str | None = None,
    virtualization_type: str | None = None,
    cpu_type: str | None = None,
    host_cpu_cores_min: int | float | None = None,
    host_ram_gb_min: int | float | None = None,
    gpu_interconnect: str | None = None,
    datacenter_grade: bool | None = None,
    static_ip: bool | None = None,
) -> dict[str, str | int | float]:
    """Build registry filter params from VM named filter options."""
    spec_filters: dict[str, object] = {
        "gpu_model": gpu_model,
        "gpu_count_min": gpu_count_min,
        "vcpu_count_min": vcpu_count_min,
        "ram_gb_min": ram_gb_min,
        "disk_gb_min": disk_gb_min,
        "region": region,
        "virtualization_type": virtualization_type,
        "cpu_type": cpu_type,
        "host_cpu_cores_min": host_cpu_cores_min,
        "host_ram_gb_min": host_ram_gb_min,
        "gpu_interconnect": gpu_interconnect,
        "datacenter_grade": datacenter_grade,
        "static_ip": static_ip,
    }
    out: dict[str, str | int | float] = {}
    for key, val in spec_filters.items():
        if val is None:
            continue
        out[key] = str(val).lower() if isinstance(val, bool) else val
    return out


def short_contract_address(value: str) -> str:
    if not value:
        return "-"
    if len(value) <= 12:
        return value
    return f"{value[:6]}...{value[-4:]}"


def format_resource(resource: dict) -> str:
    if not resource:
        return "-"
    if not isinstance(resource, dict):
        return str(resource)
    is_compute = resource.get("type") == "compute" or "gpu_model" in resource
    if is_compute:
        ordered_keys = (
            "type",
            "gpu_model",
            "gpu_count",
            "sla",
            "region",
            "vcpu_count",
            "ram_gb",
            "disk_gb",
            "virtualization_type",
            "cpu_type",
            "host_cpu_cores",
            "host_ram_gb",
            "gpu_interconnect",
        )
        lines = [f"{key}={resource[key]}" for key in ordered_keys if key in resource]
        extra_keys = sorted(k for k in resource.keys() if k not in ordered_keys)
        lines.extend(f"{key}={resource[key]}" for key in extra_keys)
        return "\n".join(lines) if lines else "-"
    if "token" in resource:
        token = resource.get("token", {})
        amount = resource.get("amount")
        lines = []
        if isinstance(token, dict):
            symbol = token.get("symbol")
            contract = token.get("contract_address")
            if symbol:
                lines.append(f"symbol={symbol}")
            if contract:
                lines.append(f"contract_address={short_contract_address(str(contract))}")
        if amount is not None:
            lines.append(f"amount={amount}")
        return "\n".join(lines) if lines else "-"
    return json.dumps(resource, separators=(",", ":"), sort_keys=True)


def format_accepted_escrows(entries: list) -> str:
    if not entries:
        return "-"
    if not isinstance(entries, list):
        return str(entries)
    lines: list[str] = []
    for i, entry in enumerate(entries):
        if not isinstance(entry, dict):
            lines.append(f"[{i}] {entry}")
            continue
        from service.schemas import accepted_token_address, primary_rate_value

        chain = entry.get("chain_name") or "-"
        addr = short_contract_address(str(entry.get("escrow_address") or "-"))
        price = primary_rate_value(entry)
        token = accepted_token_address(entry)
        parts = [f"chain={chain}", f"escrow={addr}"]
        if token:
            parts.append(f"token={short_contract_address(str(token))}")
        if price is not None:
            parts.append(f"price/hr={price}")
        lines.append(" ".join(parts))
    return "\n".join(lines)


def format_demands(demands: list) -> str:
    if not demands:
        return "-"
    if not isinstance(demands, list):
        return str(demands)
    lines: list[str] = []
    for i, demand in enumerate(demands):
        if not isinstance(demand, dict):
            lines.append(f"[{i}] {demand}")
            continue
        chain = demand.get("chain_name") or "-"
        arbiter = short_contract_address(str(demand.get("arbiter") or "-"))
        data = demand.get("demand_data") or {}
        if isinstance(data, dict) and data:
            rendered_data = ",".join(
                f"{k}={short_contract_address(str(v)) if isinstance(v, str) and v.startswith('0x') else v}"
                for k, v in sorted(data.items())
            )
        else:
            rendered_data = "-"
        lines.append(f"[{i}] chain={chain} arbiter={arbiter} data={rendered_data}")
    return "\n".join(lines)


def shorten(text: str, width: int = 36) -> str:
    if len(text) <= width:
        return text
    return text[: width - 1] + "..."


def short_ts(value: str | None) -> str:
    if not value:
        return "-"
    return value.split(".")[0].replace("T", " ")
