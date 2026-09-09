"""Opt-in synthetic contact offers with immutable local publication intent."""

from __future__ import annotations

import asyncio
import json
import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Literal

import httpx
from arkhai_bare_metal import BareMetalListing
from jsonschema import Draft202012Validator
from market_contact_exchange import (
    MECHANISM,
    ContactSettlementConfig,
    contains_contact_value,
)
from market_contact_exchange.delivery_contract import (
    ContactDeliveryConfig,
    DeliveryPolicy,
)
from market_identity import Identity, TrustedIdentitySet
from market_settlement_runtime import SettlementPublicationClause
from pydantic import BaseModel, ConfigDict, Field, model_validator
from referencing import Registry
from registry_client import ListingRequest, RegistryClientError, SyncRegistryClient

from .runtime import BareMetalStorefrontRuntime, build_runtime_from_environment

NOTICE = "SYNTHETIC TEST OFFER: no supply, payment, or provisioning."
OFFERS_PATH_ENV = "BARE_METAL_STOREFRONT_CONTACT_OFFERS_PATH"


class ContactOffer(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    listing_id: str = Field(pattern=r"^synthetic-contact-[a-z0-9-]+$", max_length=128)
    name: str = Field(pattern=r"^SYNTHETIC TEST ", max_length=160)
    machine_id: str = Field(pattern=r"^synthetic-[a-z0-9-]+$", max_length=128)
    physical_host_id: str = Field(pattern=r"^synthetic-[a-z0-9-]+$", max_length=128)
    profile: str = Field(min_length=1, max_length=128)
    gpu_model: str = Field(min_length=1, max_length=128)
    gpu_count: int = Field(gt=0)
    region: str = Field(min_length=1, max_length=128)
    vcpu_count: int = Field(gt=0)
    ram_gb: int = Field(gt=0)
    disk_gb: int = Field(gt=0)

    def listing(self) -> BareMetalListing:
        return BareMetalListing(
            machine_id=self.machine_id,
            physical_host_id=self.physical_host_id,
            access_methods=["none"],
            site={"region": self.region},
            capabilities=self.model_dump(include={
                "gpu_model", "gpu_count", "vcpu_count", "ram_gb", "disk_gb",
            }),
        )

    def registry_offer(self) -> dict[str, Any]:
        listing = self.listing()
        return {
            **listing.model_dump(mode="json", exclude_none=True),
            **listing.capabilities,
            "region": self.region,
            "name": self.name,
            "description": NOTICE,
        }


class ContactOffers(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    schema_version: Literal[1]
    offers: list[ContactOffer] = Field(min_length=1, max_length=5)

    @model_validator(mode="after")
    def unique_ids(self) -> "ContactOffers":
        ids = [offer.listing_id for offer in self.offers]
        if len(set(ids)) != len(ids):
            raise ValueError("contact offer listing IDs must be unique")
        return self


class ContactDeliveryOffers(ContactOffers):
    schema_version: Literal[2]
    delivery_policy: DeliveryPolicy

    @model_validator(mode="after")
    def delivery_ids(self) -> "ContactDeliveryOffers":
        if any(not offer.listing_id.startswith("synthetic-contact-delivery-") or offer.listing_id == "synthetic-contact-delivery-" for offer in self.offers):
            raise ValueError("invalid delivery listing ID")
        return self


def load_contact_offers(path: str | Path) -> ContactOffers:
    try:
        with Path(path).open("rb") as stream:
            data = stream.read(131073)
        if len(data) > 131072:
            raise ValueError("offer file exceeds 128 KiB")
        raw = json.loads(data)
        model = ContactDeliveryOffers if isinstance(raw, dict) and type(raw.get("schema_version")) is int and raw["schema_version"] == 2 else ContactOffers
        return model.model_validate(raw)
    except (OSError, ValueError):
        # Validation exceptions can include operator-supplied field values.
        raise RuntimeError("contact publication: invalid offer file") from None


@dataclass(frozen=True)
class PreparedContactOffer:
    offer: ContactOffer
    request: ListingRequest
    intent: dict[str, Any]


class ContactPublicationError(RuntimeError):
    def __init__(self, stage: str, *, confirmed: int = 0, listing_id: str | None = None):
        self.stage = stage
        self.confirmed = confirmed
        self.listing_id = None
        super().__init__(
            f"contact publication failed at {stage}; confirmed={confirmed}; "
            "remote outcome may be uncertain"
        )


def contact_registry(
    runtime: BareMetalStorefrontRuntime, *, transport: httpx.BaseTransport | None = None,
) -> SyncRegistryClient:
    try:
        principals = json.loads(os.environ["BARE_METAL_STOREFRONT_REGISTRY_PRINCIPALS"])
        trust = TrustedIdentitySet(identities=tuple(
            Identity.model_validate(value) for value in principals
        ))
        key_path = os.environ["BARE_METAL_STOREFRONT_REGISTRY_API_KEY_FILE"]
        key = Path(key_path).read_text().strip()
        if not key:
            raise ValueError("empty registry API key")
        return SyncRegistryClient(
            os.environ["BARE_METAL_STOREFRONT_REGISTRY_URL"],
            signer=runtime.marketplace_signer,
            caller_role="seller",
            expected_registries=trust,
            registry_authority=os.environ["BARE_METAL_STOREFRONT_REGISTRY_AUTHORITY"],
            api_key=key,
            transport=transport,
            timeout=10,
        )
    except (KeyError, OSError, TypeError, ValueError):
        raise ContactPublicationError("registry_configuration") from None


async def prepare_contact_offers(
    runtime: BareMetalStorefrontRuntime, document: ContactOffers,
) -> tuple[PreparedContactOffer, ...]:
    composition = runtime.settlement_composition
    if not runtime.introduction_only or composition is None:
        raise ContactPublicationError("introduction_only_composition_required")
    if runtime.introduction_delivery is not None:
        raise ContactPublicationError("delivery_must_be_absent")
    delivery_mode = isinstance(document, ContactDeliveryOffers)
    if delivery_mode:
        try:
            ContactDeliveryConfig.model_validate(runtime.contact_delivery_config)
        except ValueError:
            raise ContactPublicationError("delivery_configuration_unavailable") from None
    section = ContactSettlementConfig.model_validate(composition.config.mechanisms["contact"])
    if not section.contact_payload:
        raise ContactPublicationError("contact_configuration_incomplete")
    prepared = []
    now = datetime.now(timezone.utc)
    for offer in document.offers:
        profile = section.profiles.get(offer.profile)
        if profile is None or NOTICE not in profile.terms:
            raise ContactPublicationError("synthetic_profile_notice_required", listing_id=offer.listing_id)
        if delivery_mode and profile.delivery_policy != document.delivery_policy:
            raise ContactPublicationError("delivery_policy_required")
        if not delivery_mode and profile.delivery_policy is not None:
            raise ContactPublicationError("delivery_policy_not_admitted")
        payload = await composition.publication_payload(
            candidate=offer.registry_offer(),
            clauses=[SettlementPublicationClause(
                mechanism=MECHANISM, asset="introduction",
                mechanism_input={"profile": offer.profile},
            )],
            offer_expires_at=now + timedelta(hours=1), funding_deadlines={},
            fulfillment_deadline=now + timedelta(hours=1),
        )
        if payload.accepted_escrows or len(payload.settlement_options) != 1:
            raise ContactPublicationError("contact_option_unavailable", listing_id=offer.listing_id)
        request = ListingRequest(
            listing_id=offer.listing_id, storefront_url=runtime.storefront_url,
            offer=offer.registry_offer(), accepted_escrows=[],
            settlement_options=list(payload.settlement_options),
        )
        private_values = list(section.contact_payload.values())
        if delivery_mode:
            config = runtime.contact_delivery_config
            private_values.extend([config.seller_route.address, config.smtp.username, config.smtp.password, config.smtp.host, config.smtp.sender])
        if any(
            contains_contact_value(request.to_dict(), value)
            for value in private_values
        ):
            raise ContactPublicationError("private_contact_in_public_offer", listing_id=offer.listing_id)
        intent = {"offer": request.offer, "settlement_options": request.settlement_options}
        if delivery_mode:
            intent["schema_version"] = 2
            intent["delivery_policy"] = document.delivery_policy.model_dump(mode="json")
        prepared.append(PreparedContactOffer(offer, request, intent))
    return tuple(prepared)


async def _check_existing(runtime: BareMetalStorefrontRuntime, item: PreparedContactOffer) -> bool:
    row = await runtime.db.load_listing(listing_id=item.offer.listing_id)
    if row is None:
        return False
    binding = await runtime.db.load_listing_binding(listing_id=item.offer.listing_id)
    local_offer = await runtime.db.load_bare_metal_listing_payload(listing_id=item.offer.listing_id)
    if (
        binding is None or binding.site_id is not None
        or json.loads(binding.source_envelope_json).get("publication_intent") != item.intent
        or Identity.model_validate(row["seller_principal"]) != runtime.seller_principal
        or local_offer != item.offer.listing()
        or row.get("accepted_escrows")
        or row.get("settlement_options") != item.request.settlement_options
    ):
        raise ContactPublicationError("immutable_intent_conflict", listing_id=item.offer.listing_id)
    if row.get("status") != "open" or row.get("paused"):
        raise ContactPublicationError("local_offer_inactive", listing_id=item.offer.listing_id)
    return True


async def reconcile_contact_offers(
    runtime: BareMetalStorefrontRuntime, document: ContactOffers, registry: SyncRegistryClient,
) -> dict[str, Any]:
    """Validate all inputs, persist local intent, then retry stable registry upserts."""
    prepared = await prepare_contact_offers(runtime, document)
    try:
        spec = await asyncio.to_thread(registry.get_filter_spec)
        if (spec.schema_id, spec.schema_version) != ("vms.compute", 1):
            raise ValueError("wrong registry schema")
        validator = Draft202012Validator(spec.listing_shape, registry=Registry())
        for item in prepared:
            validator.validate(item.request.to_dict())
    except Exception:
        raise ContactPublicationError("registry_schema") from None

    existing = [await _check_existing(runtime, item) for item in prepared]
    now = datetime.now(timezone.utc).isoformat()
    for item, present in zip(prepared, existing, strict=True):
        if not present:
            await runtime.db.upsert_bare_metal_listing(
                listing_id=item.offer.listing_id, status="open", created_at=now, updated_at=now,
                seller_principal=runtime.seller_principal, storefront_url=runtime.storefront_url,
                listing=item.offer.listing(), accepted_escrows=[],
                settlement_options=item.request.settlement_options,
                site_id=None, pool_id=None, physical_resource_id=None,
                publication_intent=item.intent,
            )
    confirmed = 0
    for item in prepared:
        try:
            await _check_existing(runtime, item)
        except ContactPublicationError as exc:
            raise ContactPublicationError(exc.stage, confirmed=confirmed, listing_id=exc.listing_id) from None
        for attempt in range(3):
            try:
                response = await asyncio.to_thread(registry.publish_listing, item.request)
                if response.get("listing_id") != item.offer.listing_id or response.get("status") != "open":
                    raise ContactPublicationError("registry_identity_or_status", confirmed=confirmed, listing_id=item.offer.listing_id)
                confirmed += 1
                break
            except (httpx.TransportError, RegistryClientError) as exc:
                retryable = isinstance(exc, httpx.TransportError) or getattr(exc, "status_code", 0) >= 500
                if not retryable or attempt == 2:
                    raise ContactPublicationError("registry_publish", confirmed=confirmed, listing_id=item.offer.listing_id) from None
                await asyncio.sleep(0.25 * (2 ** attempt))
            except (TypeError, ValueError):
                raise ContactPublicationError("registry_response_authentication", confirmed=confirmed, listing_id=item.offer.listing_id) from None
    return {"status": "published", "confirmed": confirmed, "listing_ids": [item.offer.listing_id for item in prepared]}


async def publish_contact_offers(runtime: BareMetalStorefrontRuntime, path: str | Path) -> dict[str, Any]:
    document = load_contact_offers(path)
    # Reject local configuration before constructing an outbound client.
    await prepare_contact_offers(runtime, document)
    with contact_registry(runtime) as registry:
        return await reconcile_contact_offers(runtime, document, registry)


def run_contact_publication(path: str | Path | None = None) -> dict[str, Any]:
    selected_path = path or os.environ.get(OFFERS_PATH_ENV)
    if not selected_path:
        raise ContactPublicationError("offer_path_required")
    return asyncio.run(publish_contact_offers(build_runtime_from_environment(), selected_path))
