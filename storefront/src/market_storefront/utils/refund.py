"""Pure helpers for the provider-initiated refund flow.

These live separately from the HTTP endpoint so they can be unit-tested
without bootstrapping the full agent (which is expensive to import).

`derive_refund_params` takes a loaded order row + the request payload
and returns either:
  - `("ok", {<transfer args>})` — safe to hand to transfer_erc20; or
  - `("error", status_code, {"error": "..."})` — caller should respond accordingly.
"""

from __future__ import annotations

import json
from decimal import Decimal, InvalidOperation
from typing import Any


ValidationResult = tuple  # ("ok", dict) | ("error", int, dict)


def _validate_body(payload: dict, *, fallback_buyer: str | None = None) -> tuple[str, str]:
    """Raise ValueError on bad body; otherwise return (listing_id, buyer_address).

    ``fallback_buyer`` is the buyer address recorded on the listing — used
    when the request body omits ``buyer_address``.
    """
    listing_id = payload.get("listing_id")
    if not isinstance(listing_id, str) or not listing_id.strip():
        raise ValueError("Request must include non-empty listing_id")

    buyer_address = payload.get("buyer_address") or fallback_buyer
    if not isinstance(buyer_address, str) or not buyer_address.strip():
        raise ValueError(
            "Request must include 'buyer_address' (0x-prefixed hex), or the "
            "listing must have a recorded buyer."
        )
    buyer_address = buyer_address.strip()
    if not (buyer_address.startswith("0x") and len(buyer_address) == 42):
        raise ValueError("'buyer_address' must be a 0x-prefixed 20-byte hex address")

    return listing_id.strip(), buyer_address


def derive_refund_params(
    *,
    order: dict[str, Any] | None,
    payload: dict[str, Any],
    resolve_token: callable,
) -> ValidationResult:
    """Build the ERC-20 transfer args from an order + request body.

    `resolve_token(symbol_or_address)` must return a dict with
    contract_address, decimals, and symbol (or raise on unknown token).
    Injected so the unit tests don't need the real TokenRegistry.

    Returns either ("ok", {params dict}) or ("error", status_code, body).

    Params dict contains:
      listing_id, buyer_address, token_address, amount_raw, token_meta,
      decimals, escrow_uid.

    Raises ValueError for inputs the caller should surface as HTTP 400.
    """
    fallback_buyer = (order or {}).get("buyer")
    listing_id, buyer_address = _validate_body(payload, fallback_buyer=fallback_buyer)

    if not order:
        return ("error", 404, {"error": f"Listing {listing_id} not found on this agent"})

    if order.get("status") == "refunded":
        return (
            "error",
            409,
            {"error": "Listing already refunded", "listing_id": listing_id, "status": "refunded"},
        )

    demand_raw = order.get("demand_resource") or "{}"
    try:
        demand = json.loads(demand_raw) if isinstance(demand_raw, str) else demand_raw
    except json.JSONDecodeError:
        demand = {}

    token_override = payload.get("token")
    amount_override = payload.get("amount")

    if token_override:
        token_meta = resolve_token(token_override)
    else:
        demand_token = demand.get("token") if isinstance(demand, dict) else None
        if isinstance(demand_token, dict):
            token_meta = dict(demand_token)
        elif isinstance(demand_token, str):
            token_meta = resolve_token(demand_token)
        else:
            return (
                "error",
                400,
                {"error": "Order demand has no resolvable token; pass explicit 'token'"},
            )

    decimals = int(token_meta.get("decimals", 0))
    token_address = token_meta.get("contract_address")
    if not token_address:
        return ("error", 400, {"error": "Token metadata missing contract_address"})

    if amount_override is not None:
        try:
            amount_dec = Decimal(str(amount_override))
        except (InvalidOperation, TypeError) as exc:
            raise ValueError(f"Invalid 'amount': {amount_override}") from exc
        scaled = amount_dec * (Decimal(10) ** decimals)
        if scaled != scaled.to_integral_value():
            raise ValueError(f"Amount {amount_override} has more decimals than {decimals}")
        amount_raw = int(scaled)
    else:
        if not isinstance(demand, dict) or "amount" not in demand:
            return (
                "error",
                400,
                {"error": "Order demand has no amount; pass explicit 'amount'"},
            )
        amount_raw_in = demand.get("amount")
        if amount_raw_in is None:
            # Hidden-reserve listing: refund total can't be derived from
            # the listing alone. Caller must pass an explicit --amount.
            return (
                "error",
                400,
                {"error": "Listing was published with hidden reserve "
                          "(amount=None); pass explicit 'amount' to refund"},
            )
        try:
            base_raw = int(amount_raw_in)
        except (TypeError, ValueError):
            return (
                "error",
                400,
                {"error": "Order demand amount is not an integer; pass explicit 'amount'"},
            )
        # Refund uses the agreed duration from the negotiation thread when
        # available (Slice C), else falls back to the listing's max ceiling,
        # else 1h equivalent.
        agreed_seconds = order.get("agreed_duration_seconds")
        if not agreed_seconds:
            agreed_seconds = order.get("max_duration_seconds") or 3600
        amount_raw = base_raw * max(int(agreed_seconds), 1) // 3600

    if amount_raw <= 0:
        return ("error", 400, {"error": f"Refund amount must be positive (got {amount_raw})"})

    return (
        "ok",
        {
            "listing_id": listing_id,
            "buyer_address": buyer_address,
            "token_address": token_address,
            "token_meta": token_meta,
            "decimals": decimals,
            "amount_raw": amount_raw,
            "escrow_uid": order.get("escrow_uid"),
        },
    )
