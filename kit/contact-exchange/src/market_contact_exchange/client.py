"""Conditional-escrow client for a mechanism with nothing to escrow."""

from __future__ import annotations

from typing import Any

from market_settlement_runtime import (
    ConditionOutcome,
    EffectOutcome,
    MaterializationOutcome,
    StatusOutcome,
)


class ContactExchangeClient:
    """Every operation completes locally: there is no funding, no external
    system, and no condition to converge. The mechanism reference is derived
    from the runtime's deterministic materialize operation reference, so
    repeated materialization of one obligation is idempotent by construction.
    """

    async def materialize(
        self,
        obligation: dict[str, Any],
        *,
        operation_ref: str,
    ) -> MaterializationOutcome:
        return MaterializationOutcome(
            mechanism_ref=f"introduction:{operation_ref}",
            status="ready",
            receipt={"kind": "contact_exchange.materialized"},
        )

    async def get_status(
        self,
        obligation: dict[str, Any],
        *,
        mechanism_ref: str,
        operation_ref: str,
        mechanism_state: dict[str, Any],
    ) -> StatusOutcome:
        return StatusOutcome(status="ready", mechanism_ref=mechanism_ref)

    async def check(
        self,
        obligation: dict[str, Any],
        *,
        mechanism_ref: str,
        fulfillment_ref: str,
        operation_ref: str,
        mechanism_state: dict[str, Any],
    ) -> ConditionOutcome:
        return ConditionOutcome(
            decision="ready",
            receipt={
                "kind": "contact_exchange.condition",
                "fulfillment_ref": fulfillment_ref,
            },
        )

    async def collect(
        self,
        obligation: dict[str, Any],
        *,
        mechanism_ref: str,
        fulfillment_ref: str,
        operation_ref: str,
        mechanism_state: dict[str, Any],
    ) -> EffectOutcome:
        return EffectOutcome(
            receipt={
                "kind": "contact_exchange.introduction",
                "mechanism_ref": mechanism_ref,
                "fulfillment_ref": fulfillment_ref,
            }
        )

    async def reclaim_expired(
        self,
        obligation: dict[str, Any],
        *,
        mechanism_ref: str,
        operation_ref: str,
        mechanism_state: dict[str, Any],
    ) -> EffectOutcome:
        return EffectOutcome(
            receipt={
                "kind": "contact_exchange.reclaim_noop",
                "mechanism_ref": mechanism_ref,
            }
        )


__all__ = ["ContactExchangeClient"]
