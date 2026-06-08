"""VM compute lease materialization helpers."""

from __future__ import annotations

import json
import logging
from decimal import Decimal
from typing import Any

from market_storefront.models.domain_models import (
    ComputeResource,
    TokenResource,
)

logger = logging.getLogger(__name__)


def token_resource_from_accepted_escrow(
    accepted_escrow: dict[str, Any] | Any,
    *,
    chain_configs: dict[str, Any] | None = None,
) -> TokenResource | None:
    """Build a payment ``TokenResource`` from an accepted-escrow entry."""
    from service.schemas import accepted_token_address, primary_rate_value

    if not isinstance(accepted_escrow, dict):
        return None
    amount = primary_rate_value(accepted_escrow) or 0
    token = accepted_token_address(accepted_escrow)
    try:
        from service.clients.token import ERC20TokenMetadata, resolve_token_cached
    except Exception:
        return None

    if not isinstance(token, str) or not token:
        try:
            from service.clients.alkahest import get_escrow_codec_for

            chain_name = accepted_escrow.get("chain_name", "")
            chain_config = (chain_configs or {}).get(chain_name)
            codec = get_escrow_codec_for(
                chain_name,
                accepted_escrow.get("escrow_address", ""),
                config_path=getattr(
                    chain_config,
                    "alkahest_address_config_path",
                    None,
                ),
            )
        except Exception:
            codec = None
        if codec is None or not str(codec.kind).startswith("native_token_"):
            return None
        meta = ERC20TokenMetadata(
            symbol="NATIVE",
            name="Native token",
            contract_address="native",
            decimals=18,
        )
        return TokenResource(token=meta, amount=amount)

    meta = resolve_token_cached(token)
    if meta is None:
        meta = ERC20TokenMetadata(
            symbol="UNKNOWN",
            contract_address=token,
            decimals=0,
        )
    return TokenResource(token=meta, amount=amount)


def encode_compute_lease(
    compute_resource: ComputeResource | dict[str, Any],
    token_resource: TokenResource | dict[str, Any],
    duration_seconds: int,
) -> bytes:
    """Encode a compute-for-token lease as JSON bytes for Alkahest demand data."""
    compute = compute_resource
    if isinstance(compute_resource, dict):
        compute = ComputeResource.model_validate(compute_resource)
    if not isinstance(compute, ComputeResource):
        raise ValueError("encode_compute_lease expects a ComputeResource")

    hourly_rate = token_resource
    if isinstance(token_resource, dict):
        hourly_rate = TokenResource.model_validate(token_resource)
    if not isinstance(hourly_rate, TokenResource):
        raise ValueError("encode_compute_lease expects a TokenResource")

    if duration_seconds < 1:
        raise ValueError("duration_seconds must be >= 1")

    token_meta = hourly_rate.token
    total_price = hourly_rate.amount * duration_seconds // 3600
    total_payment_resource = TokenResource(token=token_meta, amount=total_price)

    human_total_payment = (
        Decimal(total_payment_resource.amount) / Decimal(10**token_meta.decimals)
    )
    human_price_per_hour = Decimal(hourly_rate.amount) / (10**token_meta.decimals)

    lease_terms = {
        "gpu_model": (
            compute.gpu_model.value
            if hasattr(compute.gpu_model, "value")
            else str(compute.gpu_model)
        ),
        "region": (
            compute.region.value
            if hasattr(compute.region, "value")
            else str(compute.region)
        ),
        "gpu_count": compute.gpu_count,
        "sla": compute.sla,
        "duration_seconds": duration_seconds,
        "token_symbol": token_meta.symbol,
        "token_address": token_meta.contract_address,
        "price_per_hour_decimal": float(human_price_per_hour),
        "total_price_decimal": float(human_total_payment),
        "total_price_int": total_payment_resource.amount,
    }

    logger.info("[ALKAHEST] Encoding compute lease terms: %s", lease_terms)
    return json.dumps(lease_terms).encode("utf-8")
