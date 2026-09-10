"""Acceptance-owned capture from immutable unbacked declaration provenance."""

from __future__ import annotations

import hashlib
import json
from typing import Any, Literal

from arkhai_bare_metal import BareMetalListing, BareMetalMessage
from arkhai_bare_metal.contact_contract import (
    AcceptedContactContext,
    ContactAcceptedTerms,
    ContactDeclaration,
    Identifier,
)
from core_storefront.domain_registry import StorefrontListingBinding
from market_contact_exchange.delivery_contract import StrictCarrier
from market_contact_exchange.source_contract import CONTEXT_CONTRACT, ContextContactOption
from market_core.schemas import SettlementOption, SettlementPlan
from market_identity import canonical_json
from pydantic import Field, model_validator


class ContactPublicationIntent(StrictCarrier):
    schema_version: Literal[3]
    declaration: ContactDeclaration
    settlement_options: list[ContextContactOption] = Field(min_length=1, max_length=32)

    @model_validator(mode="after")
    def unique_options(self) -> ContactPublicationIntent:
        ids = [option.option_id for option in self.settlement_options]
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate context option")
        return self


class ContactDeclarationSource(StrictCarrier):
    kind: Literal["bare_metal.introduction-declaration.v1"]
    schema_version: Literal[1]
    site_id: None
    pool_id: None
    physical_resource_id: None
    declaration_id: Identifier
    publication_intent: ContactPublicationIntent


def context_digest(value: Any) -> str:
    return hashlib.sha256(canonical_json(value)).hexdigest()


def declaration_listing(declaration: ContactDeclaration) -> BareMetalListing:
    details = declaration.machine_details
    return BareMetalListing(
        declaration_id=declaration.declaration_id,
        access_methods=["none"],
        site={"region": details.region},
        capabilities=details.model_dump(mode="json", exclude={"region"}),
    )


def validate_declaration_intent(
    value: Any, listing_id: str, listing: BareMetalListing, options: list[dict[str, Any]],
) -> ContactPublicationIntent:
    try:
        intent = ContactPublicationIntent.model_validate(value)
        if (
            intent.declaration.listing_id != listing_id
            or declaration_listing(intent.declaration) != listing
            or [option.model_dump(mode="json") for option in intent.settlement_options] != options
        ):
            raise ValueError("mismatch")
        return intent
    except (TypeError, ValueError):
        raise ValueError("invalid_contact_provenance") from None


def listing_binding_digest(binding: StorefrontListingBinding) -> str:
    # Reconciliation time is mutable bookkeeping, not listing identity.
    identity = binding.as_record()
    identity.pop("last_reconciled_at")
    identity.pop("source_envelope_json")
    return context_digest(identity)


def capture_contact_context(
    *, binding: StorefrontListingBinding | None, listing: BareMetalListing,
    selected_option: SettlementOption, message: BareMetalMessage,
) -> dict[str, Any] | None:
    if "context_contract" not in selected_option.params:
        return None
    try:
        selected = ContextContactOption.model_validate(selected_option.model_dump(mode="json"))
        if binding is None or any(value is not None for value in (
            binding.site_id, binding.pool_id, binding.physical_resource_id,
        )) or binding.binding.offering_mode != "bare_metal":
            raise ValueError("unbacked binding required")
        source = ContactDeclarationSource.model_validate_json(binding.source_envelope_json)
        intent = validate_declaration_intent(
            source.publication_intent, binding.listing_id, listing,
            [option.model_dump(mode="json") for option in source.publication_intent.settlement_options],
        )
        if (
            source.declaration_id != intent.declaration.declaration_id
            or selected not in intent.settlement_options
            or message.ssh_public_key is not None or message.access_ref is not None
        ):
            raise ValueError("mismatch")
        context = AcceptedContactContext(
            schema_version=1, discovery_schema="vms.compute", negotiation_schema="bare_metal.v1",
            declaration=intent.declaration,
            accepted_terms=ContactAcceptedTerms(
                duration_seconds=message.duration_seconds, access_method=message.access_method,
            ),
            option_id=selected.option_id,
            publication_intent_digest=context_digest(intent.model_dump(mode="json")),
            source_envelope_digest=context_digest(json.loads(binding.source_envelope_json)),
            listing_binding_digest=listing_binding_digest(binding),
        ).model_dump(mode="json")
        return context
    except (KeyError, TypeError, ValueError):
        raise ValueError("invalid_contact_provenance") from None


def validate_accepted_contact_context(plan: SettlementPlan) -> None:
    """Verify new persisted context against its obligation, never current listings."""
    try:
        obligation = plan.obligations[0]
        package = plan.service_terms.get("contact-exchange.v1")
        params = obligation.params
        if "context_contract" not in params:
            if isinstance(package, dict) and ("context_contract" in package or "accepted_context" in package):
                raise ValueError("unexpected context")
            return
        if not isinstance(package, dict) or set(package) != {
            "option_id", "profile", "channel", "terms", "delivery_policy", "context_contract",
            "listing_id", "accepted_context",
        }:
            raise ValueError("invalid package")
        context = AcceptedContactContext.model_validate(package["accepted_context"])
        option_params = dict(params)
        digest = option_params.pop("accepted_context_digest")
        payer = option_params.pop("payer_principal")
        option = ContextContactOption.model_validate({
            "option_id": package["option_id"], "mechanism": obligation.mechanism,
            "asset": obligation.asset, "rates": [], "params": option_params,
        })
        if (
            package["context_contract"] != CONTEXT_CONTRACT
            or digest != context_digest(context.model_dump(mode="json"))
            or context.option_id != option.option_id
            or context.declaration.listing_id != package["listing_id"]
            or payer != obligation.payer_principal or payer != plan.buyer_principal
            or option_params["claimant_principal"] != obligation.claimant_principal
            or obligation.claimant_principal != plan.seller_principal
            or any(package[key] != option_params[key] for key in (
                "profile", "channel", "terms", "delivery_policy", "context_contract",
            ))
        ):
            raise ValueError("mismatch")
    except (IndexError, KeyError, TypeError, ValueError):
        raise ValueError("invalid_contact_provenance") from None
