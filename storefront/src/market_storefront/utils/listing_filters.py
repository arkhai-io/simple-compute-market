"""In-memory listing filter helper — mirrors the registry-service's
``matches_resource_filters`` semantics so the storefront's local
``GET /api/v1/listings`` endpoint exposes the same query surface as the
registry. Buyers and ops-tooling can use the same flag set against the
seller's local listing book.

Equality filters (region, gpu_model, sla, cpu_type, host_disk_type,
motherboard, gpu_interconnect, virtualization_type, static_ip,
datacenter_grade): the named field on offer or demand must equal the
provided value (matches in either direction).

Numeric ``_min`` filters (gpu_count_min, vcpu_count_min, ram_gb_min,
disk_gb_min, host_cpu_cores_min, host_ram_gb_min, host_disk_gb_min,
total_gpu_count_min, nic_speed_gbps_min, internet_download_mbps_min,
internet_upload_mbps_min, open_ports_count_min): the offer's value must
be ``>=`` the floor. Offers missing the field are rejected — an unknown
spec can't be assumed to satisfy a stated requirement.
"""
from __future__ import annotations

import json
from typing import Any


_BIDIR_EQUALITY_FIELDS: tuple[str, ...] = (
    "region",
    "gpu_model",
    "cpu_type",
    "host_disk_type",
    "motherboard",
    "gpu_interconnect",
    "virtualization_type",
    "static_ip",
    "datacenter_grade",
)

_OFFER_MIN_FIELDS: tuple[str, ...] = (
    "gpu_count",
    "vcpu_count",
    "ram_gb",
    "disk_gb",
    "host_cpu_cores",
    "host_ram_gb",
    "host_disk_gb",
    "total_gpu_count",
    "nic_speed_gbps",
    "internet_download_mbps",
    "internet_upload_mbps",
    "open_ports_count",
)


def _ensure_dict(raw: Any) -> dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str) and raw.strip():
        try:
            parsed = json.loads(raw)
            return parsed if isinstance(parsed, dict) else {}
        except json.JSONDecodeError:
            return {}
    return {}


def matches_listing_filters(
    listing: dict[str, Any],
    *,
    region: str | None = None,
    gpu_model: str | None = None,
    sla: float | None = None,
    cpu_type: str | None = None,
    host_disk_type: str | None = None,
    motherboard: str | None = None,
    gpu_interconnect: str | None = None,
    virtualization_type: str | None = None,
    static_ip: bool | None = None,
    datacenter_grade: bool | None = None,
    gpu_count_min: int | None = None,
    vcpu_count_min: int | None = None,
    ram_gb_min: int | None = None,
    disk_gb_min: int | None = None,
    host_cpu_cores_min: int | None = None,
    host_ram_gb_min: int | None = None,
    host_disk_gb_min: int | None = None,
    total_gpu_count_min: int | None = None,
    nic_speed_gbps_min: int | None = None,
    internet_download_mbps_min: int | None = None,
    internet_upload_mbps_min: int | None = None,
    open_ports_count_min: int | None = None,
) -> bool:
    """Return True if ``listing`` matches all provided filter constraints.

    ``listing`` is a dict with ``offer_resource`` and ``demand_resource``
    keys (as returned by ``SQLiteClient.list_listings``). Either of those
    may be a dict or a JSON-encoded string.
    """
    offer = _ensure_dict(listing.get("offer_resource"))
    demand = _ensure_dict(listing.get("demand_resource"))

    # SLA preserves legacy exact-equality semantics for compat with
    # registry-service.
    if sla is not None:
        if offer.get("sla") != sla and demand.get("sla") != sla:
            return False

    bidir_values = {
        "region": region,
        "gpu_model": gpu_model,
        "cpu_type": cpu_type,
        "host_disk_type": host_disk_type,
        "motherboard": motherboard,
        "gpu_interconnect": gpu_interconnect,
        "virtualization_type": virtualization_type,
        "static_ip": static_ip,
        "datacenter_grade": datacenter_grade,
    }
    for field in _BIDIR_EQUALITY_FIELDS:
        val = bidir_values[field]
        if val is None:
            continue
        if offer.get(field) != val and demand.get(field) != val:
            return False

    min_values = {
        "gpu_count": gpu_count_min,
        "vcpu_count": vcpu_count_min,
        "ram_gb": ram_gb_min,
        "disk_gb": disk_gb_min,
        "host_cpu_cores": host_cpu_cores_min,
        "host_ram_gb": host_ram_gb_min,
        "host_disk_gb": host_disk_gb_min,
        "total_gpu_count": total_gpu_count_min,
        "nic_speed_gbps": nic_speed_gbps_min,
        "internet_download_mbps": internet_download_mbps_min,
        "internet_upload_mbps": internet_upload_mbps_min,
        "open_ports_count": open_ports_count_min,
    }
    for field in _OFFER_MIN_FIELDS:
        floor = min_values[field]
        if floor is None:
            continue
        offered = offer.get(field)
        if offered is None:
            return False
        try:
            if float(offered) < float(floor):
                return False
        except (TypeError, ValueError):
            return False

    return True
