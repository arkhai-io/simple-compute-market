"""Alkahest scalar-price buyer aggregation policies.

These policies inspect Alkahest listing/payment shapes, so they live with the
Alkahest settlement codec rather than in the schema-opaque buyer core.
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Awaitable, Callable
from typing import Any

from market_alkahest.schemas import primary_rate_value

logger = logging.getLogger(__name__)

NegotiationLike = Any
NegotiateFn = Callable[[dict[str, Any]], Awaitable[NegotiationLike]]


def extract_advertised_scalar_price(match: dict[str, Any]) -> float | None:
    """Pull the advertised scalar unit rate from the first accepted escrow."""
    accepted = match.get("accepted_escrows") or []
    if isinstance(accepted, str):
        try:
            accepted = json.loads(accepted)
        except (ValueError, TypeError):
            return None
    if not isinstance(accepted, list) or not accepted:
        return None
    first = accepted[0]
    if not isinstance(first, dict):
        return None
    amount = primary_rate_value(first)
    if amount is None or amount <= 0:
        return None
    return float(amount)


def pick_lowest_agreed_scalar_result(
    results: list[tuple[dict[str, Any], NegotiationLike | BaseException]],
) -> tuple[dict[str, Any], NegotiationLike] | None:
    """Pick the agreed outcome with the lowest scalar agreed_amount."""
    agreed: list[tuple[dict[str, Any], NegotiationLike]] = []
    for candidate, result in results:
        if (
            not isinstance(result, BaseException)
            and getattr(result, "status", None) == "agreed"
            and getattr(result, "agreed_amount", None) is not None
        ):
            agreed.append((candidate, result))
    if not agreed:
        return None
    return min(agreed, key=lambda pair: getattr(pair[1], "agreed_amount") or 0)


async def _gather_outcomes(
    negotiate: NegotiateFn,
    candidates: list[dict[str, Any]],
) -> list[tuple[dict[str, Any], NegotiationLike | BaseException]]:
    async def _one(
        candidate: dict[str, Any],
    ) -> tuple[dict[str, Any], NegotiationLike | BaseException]:
        try:
            return (candidate, await negotiate(candidate))
        except BaseException as exc:  # noqa: BLE001 - policy-author convenience
            return (candidate, exc)

    return await asyncio.gather(*(_one(candidate) for candidate in candidates))


async def _sequential_first_agreed(
    candidates: list[dict[str, Any]],
    negotiate: NegotiateFn,
) -> tuple[dict[str, Any], NegotiationLike] | None:
    for candidate in candidates:
        outcome = await negotiate(candidate)
        if (
            getattr(outcome, "status", None) == "agreed"
            and getattr(outcome, "agreed_amount", None) is not None
        ):
            return (candidate, outcome)
    return None


async def cheapest_first(
    candidates: list[dict[str, Any]],
    negotiate: NegotiateFn,
) -> tuple[dict[str, Any], NegotiationLike] | None:
    """Sort by advertised scalar price, then negotiate until one agrees."""

    def _key(match: dict[str, Any]) -> tuple[int, float]:
        price = extract_advertised_scalar_price(match)
        if price is None:
            return (1, 0.0)
        return (0, price)

    return await _sequential_first_agreed(sorted(candidates, key=_key), negotiate)


async def priceless_last(
    candidates: list[dict[str, Any]],
    negotiate: NegotiateFn,
) -> tuple[dict[str, Any], NegotiationLike] | None:
    """Negotiate priced candidates cheapest first, then hidden-reserve ones."""
    priced: list[tuple[float, int, dict[str, Any]]] = []
    priceless: list[tuple[int, dict[str, Any]]] = []
    for idx, match in enumerate(candidates):
        price = extract_advertised_scalar_price(match)
        if price is None:
            priceless.append((idx, match))
        else:
            priced.append((price, idx, match))
    priced.sort(key=lambda item: (item[0], item[1]))
    priceless.sort(key=lambda item: item[0])
    ordered = [match for _, _, match in priced] + [
        match for _, match in priceless
    ]
    return await _sequential_first_agreed(ordered, negotiate)


async def best_price(
    candidates: list[dict[str, Any]],
    negotiate: NegotiateFn,
    *,
    timeout: float | None = None,
) -> tuple[dict[str, Any], NegotiationLike] | None:
    """Negotiate all candidates and pick the lowest scalar agreed amount."""
    if timeout is None:
        return pick_lowest_agreed_scalar_result(
            await _gather_outcomes(negotiate, candidates)
        )

    async def _one(
        candidate: dict[str, Any],
    ) -> tuple[dict[str, Any], NegotiationLike | BaseException]:
        try:
            return (candidate, await negotiate(candidate))
        except BaseException as exc:  # noqa: BLE001 - comparison skips per-task
            return (candidate, exc)

    tasks = [asyncio.create_task(_one(candidate)) for candidate in candidates]
    try:
        done, _pending = await asyncio.wait(
            tasks,
            timeout=timeout,
            return_when=asyncio.ALL_COMPLETED,
        )
        if len(done) < len(tasks):
            logger.info(
                "[ALK-Aggregation] best_price timeout fired at %.2fs; "
                "settling on %d/%d completed candidates",
                timeout,
                len(done),
                len(tasks),
            )
        return pick_lowest_agreed_scalar_result([task.result() for task in done])
    finally:
        pending_now = [task for task in tasks if not task.done()]
        for task in pending_now:
            task.cancel()
        if pending_now:
            await asyncio.gather(*pending_now, return_exceptions=True)


def resolve_best_price_timeout() -> float | None:
    """Resolve optional `[aggregation].best_price_timeout` from buyer config."""
    try:
        from market_config.config_loader import get_dotted, load_user_config
    except Exception:
        return None
    try:
        raw = get_dotted(load_user_config() or {}, "aggregation.best_price_timeout")
    except Exception:
        return None
    if raw is None:
        return None
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return None
    return value if value > 0 else None


async def best_price_from_config(
    candidates: list[dict[str, Any]],
    negotiate: NegotiateFn,
) -> tuple[dict[str, Any], NegotiationLike] | None:
    """Entry-point policy: Alkahest scalar best price with config timeout."""
    return await best_price(
        candidates,
        negotiate,
        timeout=resolve_best_price_timeout(),
    )
