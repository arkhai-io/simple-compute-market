from __future__ import annotations

import asyncio
import os
import time
import tomllib
import uuid
from pathlib import Path
from typing import Any, Literal, cast

import httpx
from market_identity import Identity, TrustedIdentitySet, create_signer
from core_buyer.registry_config import RegistryAuthority
from market_settlement_runtime import derive_obligation_ref
from market_site_client import SiteCapacityAdminClient
from registry_client import SyncRegistryClient
from vm_provisioning_operator import HostCreate, SyncProvisioningClient
from storefront_client import SyncStorefrontClient

from .authority import released_authority_client
from .driver import (
    BuyerAction,
    CompositionSnapshot,
    FulfillmentSnapshot,
    ListingSnapshot,
    MaterializationSnapshot,
    NegotiationSnapshot,
    RuntimeSnapshot,
    TerminalSnapshot,
    stable_operation_ref,
)

_RESOURCE_ID_PREFIX = "hosted-e2e-vm"
_REFUND_EXPIRATION_SECONDS = 31 * 60
_OFFER = {
    "resource_id": "",
    "gpu_model": "H100",
    "gpu_count": 1,
    "sla": 99.9,
    "region": "local",
}


def _required(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise RuntimeError(f"selected hosted E2E scenario is missing prerequisite: {name}")
    return value


def _config(path: Path) -> dict[str, Any]:
    with path.open("rb") as source:
        return tomllib.load(source)


def _trusted(value: dict[str, Any]) -> TrustedIdentitySet:
    return TrustedIdentitySet(
        identities=tuple(Identity.model_validate(item) for item in value["principals"])
    )


def _signer(config: dict[str, Any], credential: str):
    public = config["Identity"]
    principal = public.get("principal", public)
    signer = create_signer(principal["scheme"], credential)
    if signer.identity != Identity.model_validate(principal):
        raise RuntimeError("marketplace identity credential does not match hosted fixture")
    return signer


def _primary_registry_authority(config: dict[str, Any]) -> dict[str, Any]:
    registry = config.get("registry")
    if not isinstance(registry, dict):
        raise RuntimeError("buyer configuration has no registry section")
    urls = registry.get("urls")
    authorities = registry.get("authorities")
    if (
        not isinstance(urls, list)
        or not urls
        or not isinstance(urls[0], str)
        or not isinstance(authorities, dict)
    ):
        raise RuntimeError("buyer configuration has no primary registry authority")
    authority = authorities.get(urls[0])
    if not isinstance(authority, dict):
        raise RuntimeError("buyer configuration has no primary registry authority")
    return authority


def _option(listing) -> dict[str, Any]:
    options = listing.extra.get("settlement_options", [])
    hosted = [item for item in options if item.get("mechanism") == "fiat.stripe.v1"]
    if len(hosted) != 1:
        raise AssertionError("hosted listing did not publish exactly one fiat.stripe.v1 option")
    return hosted[0]


class NetworkMarketplacePort:
    """Public HTTP driver for registry, storefront, buyer, VM, and authority seams."""

    def __init__(self, *, buyer_config: Path) -> None:
        self.buyer_config = _config(buyer_config)
        storefront_path = Path(_required("HOSTED_SETTLEMENT_E2E_STOREFRONT_CONFIG"))
        if not storefront_path.is_file():
            raise RuntimeError("selected Stripe test scenario requires storefront config")
        self.storefront_config = _config(storefront_path)
        self.storefront_url = _required("HOSTED_STOREFRONT_URL")
        self.registry_url = _required("HOSTED_REGISTRY_URL")
        self.provisioning_url = _required("HOSTED_PROVISIONING_URL")
        self.authority_url = _required("HOSTED_SETTLEMENT_AUTHORITY_URL")
        self.account_ref = _required("HOSTED_SETTLEMENT_E2E_ACCOUNT_REF")
        self._buyer_signer = _signer(
            self.buyer_config,
            _required("HOSTED_SETTLEMENT_E2E_BUYER_IDENTITY_CREDENTIAL"),
        )
        buyer_signer = self._buyer_signer
        seller_signer = _signer(
            self.storefront_config,
            _required("HOSTED_SETTLEMENT_E2E_STOREFRONT_IDENTITY_CREDENTIAL"),
        )
        self._seller_signer = seller_signer
        seller_trust = TrustedIdentitySet(identities=(seller_signer.identity,))
        registry_authority = _primary_registry_authority(self.buyer_config)
        self.registry = SyncRegistryClient(
            base_url=self.registry_url,
            signer=buyer_signer,
            caller_role="buyer",
            expected_registries=_trusted(registry_authority),
            registry_authority=registry_authority["authority"],
        )
        self._registry_authority = RegistryAuthority(
            authority=registry_authority["authority"],
            principals=_trusted(registry_authority),
        )
        self.buyer = SyncStorefrontClient(
            self.storefront_url,
            signer=buyer_signer,
            caller_role="buyer",
            expected_publishers=seller_trust,
        )
        self.seller = SyncStorefrontClient(
            self.storefront_url,
            signer=seller_signer,
            caller_role="seller",
            expected_publishers=seller_trust,
        )
        provisioning_trust = TrustedIdentitySet(
            identities=tuple(
                Identity.model_validate(principal)
                for principal in self.storefront_config["provisioning"]["identity"]["principals"]
            )
        )
        self.capacity_admin = SiteCapacityAdminClient(
            self.provisioning_url,
            seller_signer,
            provisioning_trust,
        )
        admin_signer = create_signer(
            "ed25519",
            _required("HOSTED_SETTLEMENT_E2E_ADMIN_IDENTITY_CREDENTIAL"),
        )
        self._resource_id = f"{_RESOURCE_ID_PREFIX}-{uuid.uuid4().hex[:12]}"
        self._host_id = self._resource_id
        with SyncProvisioningClient(
            self.provisioning_url,
            admin_signer,
            provisioning_trust,
        ) as provisioning_admin:
            provisioning_admin.register_host(
                HostCreate(
                    name=self._host_id,
                    kvm_host="127.0.0.1",
                    ssh_user="hosted-e2e",
                    ssh_key_type="path",
                    ssh_key_value="/tmp/hosted-e2e-key",
                    gpu_count=1,
                    gpu_model="H100",
                    enabled=True,
                )
            )
        self._listing_id: str | None = None
        self._operations: dict[str, str] = {}
        self._condition_decision: Literal["satisfied"] = "satisfied"
        self._stripe_test_case: Literal["collection", "refund"] = "collection"

    def ensure_capacity(self) -> None:
        resource = asyncio.run(
            self.capacity_admin.register_resource(
                self._resource_id,
                total_units=1,
                resource_type="compute.gpu",
                pool_id="default",
                resource_subtype="h100",
                attributes={
                    "gpu_model": "H100",
                    "region": "local",
                    "vm_host": self._host_id,
                    "physical_host_id": self._host_id,
                },
                capacity={"gpu_count": 1},
                request_id=f"hosted-e2e-capacity-{self._resource_id}",
            )
        )
        if resource.get("resource_id") != self._resource_id:
            raise AssertionError("hosted capacity registration returned wrong resource")

    def verify_composition(self) -> CompositionSnapshot:
        authority = httpx.get(self.authority_url + "/health/ready", timeout=10).json()
        expected_manifest = _required("HOSTED_SETTLEMENT_E2E_PRODUCTION_MANIFEST_DIGEST")
        if authority.get("manifest_digest") != expected_manifest:
            raise AssertionError("authority readiness has the wrong production release")
        return CompositionSnapshot(
            authority_ready=authority.get("ready") is True,
            production_manifest_digest=expected_manifest,
        )

    def verify_runtime(self) -> RuntimeSnapshot:
        status = httpx.get(self.storefront_url + "/health", timeout=10)
        authority = released_authority_client(
            config_path=Path(
                os.environ.get(
                    "HOSTED_SETTLEMENT_E2E_STOREFRONT_CONFIG",
                    "/app/config/hosted-storefront.toml",
                )
            ),
            signer=self._seller_signer,
            caller_role="account_owner",
            base_url=self.authority_url,
        )
        account = authority.account_readiness(
            self.account_ref,
            request_id=f"stripe-test-account-{uuid.uuid4().hex}",
        )
        wallet_free = not self.buyer_config.get("Wallet") and not self.buyer_config.get("Chains")
        required_capabilities = {"transfers"}
        return RuntimeSnapshot(
            wallet_free=bool(wallet_free),
            runtime_ready=status.status_code == 200,
            account_ready=account.ready
            and required_capabilities.issubset(set(account.capabilities)),
        )

    def select_stripe_test_case(self, case: str) -> None:
        if case not in {"collection", "refund"}:
            raise ValueError("unsupported Stripe test lifecycle case")
        self._stripe_test_case = cast(Literal["collection", "refund"], case)

    def eligible_pretransfer_refund_available(self) -> bool:
        return True

    def create_and_publish_listing(self) -> ListingSnapshot:
        created = self.seller.create_listing(
            offer={**_OFFER, "resource_id": self._resource_id},
            settlement_config={
                "account_ref": self.account_ref,
                "currency": "usd",
                "rate_minor_units": 2000,
                "condition_profile": "vm-fulfillment",
            },
            max_duration_seconds=3600,
            paused=False,
        )
        if not created.listing_id:
            raise AssertionError("hosted listing create returned no listing identity")
        listing = self.seller.get_listing(created.listing_id)
        option = _option(listing)
        self._listing_id = created.listing_id
        return ListingSnapshot(
            listing_id=created.listing_id,
            publication_ref=str(option["option_id"]),
        )

    def discover_listing(self, listing_id: str) -> str:
        discovered = self.registry.get_listing(listing_id)
        if str(discovered.id) != listing_id or discovered.status != "open":
            raise AssertionError("registry discovery did not return the open hosted listing")
        if (
            len(
                [
                    item
                    for item in discovered.settlement_options
                    if item.get("mechanism") == "fiat.stripe.v1"
                ]
            )
            != 1
        ):
            raise AssertionError("registry did not project the hosted settlement option")
        return str(discovered.id)

    def negotiate(self, registry_listing_id: str) -> NegotiationSnapshot:
        listing = self.registry.get_listing(registry_listing_id)
        option = [
            item for item in listing.settlement_options if item.get("mechanism") == "fiat.stripe.v1"
        ][0]
        expiration_unix = int(time.time()) + (
            _REFUND_EXPIRATION_SECONDS if self._stripe_test_case == "refund" else 3600
        )
        selection = {
            "mechanism": "fiat.stripe.v1",
            "option_id": option["option_id"],
            "expiration_unix": expiration_unix,
        }
        response = self.buyer.negotiate_new(
            listing_id=registry_listing_id,
            initial_amount=2000,
            provision_terms={
                "kind": "compute.v1",
                "version": 1,
                "payload": {
                    "duration_seconds": 3600,
                    "ssh_public_key": self.buyer_config["provisioning"]["ssh_public_key"],
                },
            },
            settlement_selection=selection,
            chain_name="",
            escrow_address="",
            literal_fields={},
        )
        negotiation_id = response.get("negotiation_id")
        if response.get("action") != "accept" or not negotiation_id:
            raise AssertionError("hosted buyer negotiation did not accept fiat.stripe.v1")
        plan = response.get("settlement_plan") or {}
        obligations = plan.get("obligations") or []
        if len(obligations) != 1 or obligations[0].get("mechanism") != "fiat.stripe.v1":
            raise AssertionError("accepted Terms did not pin one hosted obligation")
        self._accepted_obligation = obligations[0]
        return NegotiationSnapshot(
            negotiation_id=str(negotiation_id),
            accepted_terms={"selection": selection, "plan": plan},
            accepted_mechanism="fiat.stripe.v1",
        )

    def materialize(self, negotiation_id: str) -> MaterializationSnapshot:
        obligation = dict(self._accepted_obligation)
        obligation_ref = derive_obligation_ref(negotiation_id, 0, obligation)
        from domains.vms.buyer.hosted_settlement import start_hosted_settlement

        started = start_hosted_settlement(
            seller_url=self.storefront_url,
            negotiation_id=negotiation_id,
            obligation_ref=obligation_ref,
            payer_principal=Identity.model_validate(obligation.get("payer_principal")),
            claimant_principal=Identity.model_validate(obligation.get("claimant_principal")),
            principal=self._buyer_signer.identity,
            signer=self._buyer_signer,
            resolve_seller_principals=self._publisher_resolver(),
        )
        action = started.get("action") or {}
        settlement_ref = started.get("settlement_ref")
        expires_at = action.get("expires_at_unix") or started.get("action_expires_at_unix")
        if not settlement_ref or not action.get("url"):
            raise AssertionError("hosted materialization returned no Checkout action")
        if not isinstance(expires_at, int):
            raise AssertionError("hosted materialization returned no action expiry")
        amount = int(obligation["amount"])
        currency = str(obligation["asset"])
        operation_ref = stable_operation_ref("materialize", obligation_ref)
        self._operations[str(settlement_ref)] = operation_ref
        return MaterializationSnapshot(
            obligation_ref=obligation_ref,
            settlement_ref=str(settlement_ref),
            operation_ref=operation_ref,
            action=BuyerAction(
                kind=str(action.get("kind") or started.get("action_kind") or "redirect"),
                expires_at_unix=expires_at,
                url=str(action["url"]),
            ),
            amount=amount,
            currency=currency,
            expiration_unix=int(obligation["expiration_unix"]),
            destination_account_ref=self.account_ref,
            transfer_group=str(settlement_ref),
            source_relation="checkout-charge",
        )

    def wait_funded(self, settlement_ref: str) -> bool:
        status = self._wait_public_status(
            settlement_ref,
            {"funded", "ready", "collecting", "collected"},
        )
        return status.get("status") in {"funded", "ready", "collecting", "collected"}

    def complete_vm_fulfillment(self, settlement_ref: str) -> FulfillmentSnapshot:
        status = self._buyer_status(settlement_ref)
        anchor = status.get("condition_anchor") or status.get("fulfillment", {}).get(
            "condition_anchor"
        )
        if not anchor:
            raise AssertionError("funded hosted obligation has no portable condition anchor")
        listing_id = self._require_listing_id()
        reservation_ref = status.get("capacity_reservation_ref") or f"capacity:{listing_id}"
        fulfillment_ref = status.get("fulfillment_ref") or f"fulfillment:{settlement_ref}"
        return FulfillmentSnapshot(
            capacity_reservation_ref=str(reservation_ref),
            fulfillment_ref=str(fulfillment_ref),
            condition_anchor=str(anchor),
            condition_decision=self._condition_decision,
        )

    def wait_terminal(self, settlement_ref: str) -> TerminalSnapshot:
        status = self._wait_public_status(settlement_ref, {"collected"})
        return TerminalSnapshot(
            operation_ref=self._operation(settlement_ref),
            marketplace_status=str(status["status"]),
            authority_status=str(status["status"]),
            effect_kind="transfer",
        )

    def reclaim(self, settlement_ref: str) -> TerminalSnapshot:
        from domains.vms.buyer.hosted_settlement import reclaim_hosted_settlement

        result = self._buyer_call(reclaim_hosted_settlement, settlement_ref)
        if result.get("status") != "reclaimed":
            result = self._wait_public_status(settlement_ref, {"reclaimed"})
        return TerminalSnapshot(
            operation_ref=self._operation(settlement_ref),
            marketplace_status=str(result["status"]),
            authority_status=str(result["status"]),
            effect_kind="refund",
        )

    def request_eligible_pretransfer_refund(self, settlement_ref: str) -> TerminalSnapshot:
        return self.reclaim(settlement_ref)

    def recover_eligible_pretransfer_refund(self, settlement_ref: str) -> TerminalSnapshot:
        return self.reclaim(settlement_ref)

    def _buyer_status(self, settlement_ref: str) -> dict[str, Any]:
        from domains.vms.buyer.hosted_settlement import poll_hosted_settlement

        return self._buyer_call(poll_hosted_settlement, settlement_ref)

    def _buyer_call(self, function, settlement_ref: str):
        return function(
            seller_url=self.storefront_url,
            settlement_ref=settlement_ref,
            principal=self._buyer_signer.identity,
            signer=self._buyer_signer,
            resolve_seller_principals=self._publisher_resolver(),
        )

    def _operation(self, settlement_ref: str) -> str:
        try:
            return self._operations[settlement_ref]
        except KeyError as exc:
            raise AssertionError("unknown protected settlement operation") from exc

    def _require_listing_id(self) -> str:
        listing_id = self._listing_id
        if listing_id is None:
            raise AssertionError("hosted listing has not been published")
        return listing_id

    def _publisher_resolver(self):
        from core_buyer.orchestration import make_publisher_trust_resolver
        from core_buyer.orchestrator import BuyConfig

        listing = self.registry.get_listing(self._require_listing_id()).to_dict()
        listing["source_registry_url"] = self.registry_url
        listing["source_registry_authority"] = self._registry_authority.authority
        config = BuyConfig(
            registry_urls=[self.registry_url],
            registry_authorities={self.registry_url: self._registry_authority},
            principal=self._buyer_signer.identity,
            signer=self._buyer_signer,
            discovery_timeout=10,
        )
        return make_publisher_trust_resolver(config=config, listing=listing)

    def _wait_public_status(self, settlement_ref: str, terminal: set[str]):
        timeout = float(os.environ.get("HOSTED_SETTLEMENT_E2E_LIFECYCLE_TIMEOUT", "180"))
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                status = self._buyer_status(settlement_ref)
            except RuntimeError as exc:
                if "authenticated HTTP 503:" not in str(exc):
                    raise
            else:
                if status.get("status") in terminal:
                    return status
            time.sleep(min(0.5, max(0.0, deadline - time.monotonic())))
        raise TimeoutError("named hosted public status did not converge")


def create_protected_marketplace(*, buyer_config: Path) -> NetworkMarketplacePort:
    marketplace = NetworkMarketplacePort(buyer_config=buyer_config)
    marketplace.ensure_capacity()
    return marketplace
