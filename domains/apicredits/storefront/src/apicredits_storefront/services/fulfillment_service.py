"""This storefront's binding of the selling library's issuance and failure policy.

Supplies the process's parts: settings, the capacity runtime and listing
reopen pass a released hold needs, the settlement composition a refund reads,
and the composed authority client.
"""

from __future__ import annotations

from typing import Any

from arkhai_api_selling.failure_policy import DEFAULT_FAILURE_ACTIONS, build_failure_policy
from arkhai_api_selling.issuance import fulfill_from_hold
from core_storefront.stage_log import stage_event
from market_core import SettlementEvidence
from market_settlement_runtime import FailurePolicy

import apicredits_storefront.container as _container
from apicredits_storefront.container import get_sqlite_client
from apicredits_storefront.services.credits_service_client import (
    get_credits_service_client,
)
from apicredits_storefront.settlement_composition import SELLER_STAGES
from apicredits_storefront.utils.config import settings


def _configured_failure_actions() -> Any:
    raw = settings.get("fulfillment.failure_policy.actions")
    return DEFAULT_FAILURE_ACTIONS if raw is None else raw


def _failure_webhook_target() -> tuple[str, float]:
    url = str(settings.get("fulfillment.failure_policy.webhook_url", "") or "").strip()
    try:
        timeout = float(
            settings.get("fulfillment.failure_policy.webhook_timeout", 5.0) or 5.0
        )
    except (TypeError, ValueError):
        timeout = 5.0
    return url, timeout


def build_api_credit_failure_policy() -> FailurePolicy:
    """Compose the family's failure actions over this storefront's collaborators."""
    return build_failure_policy(
        actions_provider=_configured_failure_actions,
        capacity_runtime=lambda db: _container.QUOTA_CAPACITY.runtime(lambda: db),
        reopen_listings=_container.QUOTA_PUBLICATION.reopen_after_capacity_change,
        webhook_target=_failure_webhook_target,
        stages=SELLER_STAGES,
        composition=lambda: _container.resolved_settlement_composition,
        stage_event=stage_event,
    )


async def _apply_fulfillment_failure_policy_adapter(
    *,
    capacity_reservation_id: str | None,
    settlement_ref: str | None,
    negotiation_id: str,
    listing_id: str | None,
    resource_id: str | None,
    reason: str,
    message: str,
    source: str,
) -> None:
    policy = _container.resolved_failure_policy
    if policy is None:
        raise RuntimeError("API-credit failure policy is not initialized")
    await policy.apply(
        get_sqlite_client(),
        {
            "capacity_reservation_id": capacity_reservation_id,
            "settlement_ref": settlement_ref,
            "negotiation_id": negotiation_id,
            "listing_id": listing_id,
            "resource_id": resource_id,
            "reason": reason,
            "message": message,
            "source": source,
            "state": None,
            "reopened_listing_ids": [],
        },
    )


async def fulfill_credit_obligation(
    *, evidence: SettlementEvidence, retry_uncertain: bool = False,
    db: Any | None = None, credits_client: Any | None = None,
) -> dict[str, Any]:
    """Issue from verified delivery inputs, independently of their source mechanism."""
    return await fulfill_from_hold(
        _container.SELLING_CONTRIBUTIONS,
        evidence=evidence,
        db=db if db is not None else get_sqlite_client(),
        credits_client=credits_client or get_credits_service_client(),
        stage_event=stage_event,
        apply_failure_policy=_apply_fulfillment_failure_policy_adapter,
        retry_uncertain=retry_uncertain,
    )
