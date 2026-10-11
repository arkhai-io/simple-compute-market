"""API-credit market contract and shared-settlement domain injections."""

from __future__ import annotations

import json
import logging
from dataclasses import replace
from typing import Any

from market_settlement_runtime import derive_obligation_ref
from apicredits_storefront.settlement_composition import SELLER_STAGES
from apicredits_storefront.settlement_stages import accepted_agreement

from market_core import (
    DomainCapability,
    ImmutableFulfillmentCapability,
    ImmutablePublicationCapability,
    ImmutableSettlementCapability,
    ImmutableStorefrontCapability,
    MarketDomainContract,
    validate_domain_contract,
)

logger = logging.getLogger(__name__)


def _build_market_domain_contract() -> MarketDomainContract:
    """Build and validate the API-credit contract for the storefront role."""
    from apicredits_storefront.services.fulfillment_service import (
        fulfill_credit_obligation,
    )
    from apicredits_storefront.services.publication_service import (
        publish_order_to_registry,
    )
    from arkhai_apicredits.domain_runtime import market_domain
    from arkhai_apicredits.negotiation.storefront_round import (
        default_seller_round_hook,
    )

    base = market_domain()
    capabilities = {
        DomainCapability.STOREFRONT,
        DomainCapability.PUBLICATION,
        DomainCapability.SETTLEMENT,
        DomainCapability.FULFILLMENT,
    }
    return validate_domain_contract(
        replace(
            base,
            declared_capabilities=base.declared_capabilities | capabilities,
            storefront=ImmutableStorefrontCapability(
                run_negotiation_policy=default_seller_round_hook,
            ),
            publication=ImmutablePublicationCapability(
                publish=publish_order_to_registry,
            ),
            settlement=ImmutableSettlementCapability(
                seller_stages=SELLER_STAGES,
            ),
            fulfillment=ImmutableFulfillmentCapability(
                fulfill=fulfill_credit_obligation,
            ),
        )
    )


#: Installed storefront-domain entry points load concrete validated contracts,
#: not factories. Keeping this immutable object module-local also ensures every
#: service in one process consumes the same composed capability set.
APICREDITS_STOREFRONT_DOMAIN = _build_market_domain_contract()


def get_market_domain_contract() -> MarketDomainContract:
    """Return the validated API-credit contract injected into this storefront."""
    return APICREDITS_STOREFRONT_DOMAIN


async def prepare_api_credit_settlement(**context: Any) -> Any:
    """Resolve only the exact accepted seller stage before verification."""
    thread = await context["sqlite_client"].load_negotiation_thread_row(
        negotiation_id=context["negotiation_id"],
    )
    if thread is None:
        raise ValueError("accepted negotiation is unavailable")
    agreement, _raw = accepted_agreement(thread)
    try:
        stage = SELLER_STAGES[agreement.settlement.mechanism]
    except KeyError as exc:
        raise ValueError("unsupported accepted settlement mechanism") from exc
    return await stage.prepare(**context)


async def reserve_api_credit_settlement(
    sqlite_client: Any,
    prepared: Any,
    escrow_uid: str,
    negotiation_id: str,
    *,
    settlement_runtime: Any,
    wake_servicing: Any,
) -> dict[str, Any] | None:
    """Create, bind, and recover the existing public settlement row."""
    projection = prepared.projection_context
    inserted = await sqlite_client.insert_escrow(
        escrow_uid=escrow_uid,
        negotiation_id=negotiation_id,
        chain_name=projection.chain_name,
        escrow_address=projection.escrow_address,
        is_primary=True,
        status="provisioning",
    )
    obligation_ref = derive_obligation_ref(
        prepared.agreement_ref,
        prepared.selected_obligation_index,
        prepared.obligations[prepared.selected_obligation_index],
    )
    row = await sqlite_client.bind_escrow_obligation(
        escrow_uid=escrow_uid,
        obligation_ref=obligation_ref,
        obligation_index=prepared.selected_obligation_index,
    )
    fulfillment_ref = row.get("fulfillment_uid")
    if (
        not inserted
        and row.get("status") == "ready"
        and isinstance(fulfillment_ref, str)
        and fulfillment_ref
    ):
        await settlement_runtime.bind_fulfillment(
            obligation_ref,
            fulfillment_ref,
            local_principal=prepared.local_principal,
        )
        await wake_servicing(obligation_ref)
    existing = await sqlite_client.load_issuance_progress(reference=escrow_uid)
    if existing is None:
        await sqlite_client.save_issuance_progress(
            negotiation_id=negotiation_id, public_ref=escrow_uid, status="provisioning",
        )
    return row if existing is not None and existing["status"] in {"ready", "failed"} else None


async def fulfill_api_credit_settlement(prepared: Any, *, mechanism_client: Any) -> Any:
    """Reconstruct the selected continuation from the accepted Agreement."""
    db = prepared.fulfillment_input.sqlite_client
    thread = await db.load_negotiation_thread_row(negotiation_id=prepared.agreement_ref)
    agreement, _raw = accepted_agreement(thread)
    return await SELLER_STAGES[agreement.settlement.mechanism].deliver_prepared(
        prepared, mechanism_client=mechanism_client,
    )


async def persist_api_credit_settlement_outcome(
    sqlite_client: Any,
    prepared: Any,
    outcome: Any,
) -> None:
    """Project generic completion into the unchanged settle-status row."""
    if outcome.status == "fulfilled":
        await sqlite_client.update_escrow(
            escrow_uid=prepared.mechanism_ref,
            status="ready",
            fulfillment_uid=outcome.fulfillment_ref,
            connection_details=outcome.public_result.get("connection_details"),
            tenant_credentials=None,
        )
        return
    reason = outcome.reason or "fulfillment failed"
    # Logged as well as persisted. The reason reaches the buyer in the
    # settle-status body, and nowhere else: a settlement that fails before
    # its first call to the credits service left no trace in this
    # storefront's own output, so an operator holding only the container
    # log saw a `202` and then silence. `issuance_error:` prefixes carry a
    # caught exception, which is the one case where the reason is the only
    # record that it happened at all.
    logger.warning(
        "[SETTLE] settlement failed for %s: %s",
        prepared.mechanism_ref,
        reason,
    )
    await sqlite_client.save_issuance_progress(
        negotiation_id=prepared.agreement_ref, public_ref=prepared.mechanism_ref,
        status="failed", reason=reason,
    )
    await sqlite_client.update_escrow(
        escrow_uid=prepared.mechanism_ref,
        status="failed",
        reason=reason,
    )


def serialize_api_credit_settlement_start(
    row: dict[str, Any],
) -> dict[str, Any]:
    """Keep the established initial 202 response free of runtime identity."""
    return {
        "escrow_uid": row.get("escrow_uid"),
        "negotiation_id": row.get("negotiation_id"),
        "status": row.get("status"),
    }


def serialize_api_credit_settlement(row: dict[str, Any]) -> dict[str, Any]:
    """Keep the established API-credit settle/status JSON projection."""
    out: dict[str, Any] = {
        "escrow_uid": row.get("escrow_uid"),
        "negotiation_id": row.get("negotiation_id"),
        "status": row.get("status"),
        "created_at": row.get("created_at"),
        "updated_at": row.get("updated_at"),
    }
    for field in (
        "obligation_ref",
        "fulfillment_uid",
        "chain_name",
        "escrow_address",
        "connection_details",
        "reason",
    ):
        value = row.get(field)
        if value is not None:
            out[field] = value
    if row.get("is_primary") is not None:
        out["is_primary"] = bool(row["is_primary"])
    credentials = row.get("tenant_credentials")
    if credentials:
        try:
            out["tenant_credentials"] = json.loads(credentials)
        except (TypeError, ValueError):
            out["tenant_credentials"] = credentials
    return out
