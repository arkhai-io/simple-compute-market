"""VM-domain buyer/listing rendering helpers."""

from __future__ import annotations

import json




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
        from market_alkahest.schemas import accepted_token_address, primary_rate_value

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
