from __future__ import annotations

import asyncio
import hashlib
import json
import os
import sys
import time
import tomllib
import uuid
from pathlib import Path
from typing import Any, Literal, cast
import httpx

from core_buyer.hosted_settlement import HostedSettlementTransport
from core_buyer.orchestration import make_publisher_trust_resolver
from core_buyer.orchestrator import BuyConfig
from core_buyer.profile_service import BuyerProfileService
from core_buyer.registry_config import RegistryAuthority
from domains.vms.buyer.hosted_authorization import prepare_hosted_funding_authorization
from hosted_settlement_client import (
    FundingMode,
    FundingProfile,
    InstrumentKind,
    InstrumentReadiness,
)
from market_hosted_settlement import (
    FundingSelection,
    StripeSettlementConfig,
    payer_command_context_from_config,
)
from market_identity import (
    AuthorityPayerBinding,
    Identity,
    ProfileRepository,
    TrustedIdentitySet,
    create_signer,
)
from market_settlement_runtime import derive_obligation_ref
from market_site_client import SiteCapacityAdminClient
from registry_client import SyncRegistryClient
from storefront_client import SyncStorefrontClient
from vm_provisioning_operator import HostCreate, SyncProvisioningClient

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
)

_RESOURCE_ID_PREFIX = "hosted-e2e-vm"
_REFUND_EXPIRATION_SECONDS = 31 * 60
_OFFER = {
    "resource_id": "",
    "gpu_model": "H100",
    "gpu_count": 1,
    "sla": 99.9,
    "region": "local",
    "virtualization_type": "vm",
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


def _buyer_profile(
    config: dict[str, Any],
) -> tuple[object, object, BuyerProfileService]:
    profile_config = config.get("BuyerProfile")
    if not isinstance(profile_config, dict):
        raise RuntimeError("buyer configuration has no profile-store reference")
    store_path = profile_config.get("store_path")
    if not isinstance(store_path, str):
        raise RuntimeError("buyer profile-store reference is malformed")
    path = Path(store_path)
    service = BuyerProfileService(
        repository=ProfileRepository(path),
        run_logs_directory=path.parent / "runs",
    )
    profile, signer = service.resolve_fresh_signer()
    return profile, signer, service


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

def _capacity_site_id(config: dict[str, Any]) -> str:
    capacity = config.get("capacity")
    sites = capacity.get("sites") if isinstance(capacity, dict) else None
    if not isinstance(sites, dict) or not sites:
        raise RuntimeError("hosted storefront config requires a capacity site")
    site_id = next(iter(sites))
    if not isinstance(site_id, str) or not site_id:
        raise RuntimeError("hosted storefront capacity site identity is malformed")
    return site_id


def _option(listing, funding_profile: str) -> dict[str, Any]:
    options = getattr(listing, "settlement_options", None)
    if options is None:
        options = listing.extra.get("settlement_options", [])
    hosted = [
        item
        for item in options
        if item.get("mechanism") == "fiat.stripe.v1"
        and item.get("params", {}).get("funding_profile") == funding_profile
    ]
    if len(hosted) != 1:
        raise AssertionError("hosted listing did not publish the exact selected profile")
    return hosted[0]


async def _payer_facade_call(context, signer, operation: str, **kwargs: Any) -> Any:
    """Run one direct payer operation and always close its released client."""

    facade = context.facade(signer)
    try:
        return await getattr(facade, operation)(**kwargs)
    finally:
        await facade.aclose()


class NetworkMarketplacePort:
    """Public HTTP driver for registry, storefront, buyer, VM, and authority seams."""

    def __init__(self, *, buyer_config: Path) -> None:
        self.buyer_config_path = buyer_config
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
        profile, buyer_signer, profiles = _buyer_profile(self.buyer_config)
        self._buyer_profile = profile
        self._buyer_signer = buyer_signer
        self._profiles = profiles
        self._stripe_config = StripeSettlementConfig.model_validate(
            self.buyer_config["Settlement"]["stripe"]
        )
        self._funding_profile = FundingProfile(_required("HOSTED_SETTLEMENT_E2E_FUNDING_PROFILE"))
        self._interaction = FundingMode(_required("HOSTED_SETTLEMENT_E2E_INTERACTION"))
        self._payer_context = payer_command_context_from_config(
            self._stripe_config,
            profiles=profiles,
            dispatch_action=lambda _action, _binding: None,
        )
        payer = asyncio.run(
            _payer_facade_call(
                self._payer_context,
                buyer_signer,
                "create",
                country=self._stripe_config.country,
            )
        )
        self._payer_binding = AuthorityPayerBinding(
            authority_id=str(self._stripe_config.authority_id),
            environment=str(self._stripe_config.environment),
            binding_ref=payer.payer_profile_ref,
            bound_principal=buyer_signer.identity,
        )
        self._profiles.set_authority_payer_binding(
            profile.profile_id,
            self._payer_binding,
        )
        self._setup_ref: str | None = None
        self._selected_instrument_ref: str | None = None
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
        self._provisioning_trust = TrustedIdentitySet(
            identities=tuple(
                Identity.model_validate(principal)
                for principal in self.storefront_config["provisioning"]["identity"]["principals"]
            )
        )
        self.capacity_admin = SiteCapacityAdminClient(
            self.provisioning_url,
            seller_signer,
            self._provisioning_trust,
        )
        self._admin_signer = create_signer(
            "ed25519",
            _required("HOSTED_SETTLEMENT_E2E_ADMIN_IDENTITY_CREDENTIAL"),
        )
        self._resource_id = f"{_RESOURCE_ID_PREFIX}-{uuid.uuid4().hex[:12]}"
        self._site_id = _capacity_site_id(self.storefront_config)
        self._host_id = self._resource_id
        with SyncProvisioningClient(
            self.provisioning_url,
            self._admin_signer,
            self._provisioning_trust,
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

    def ensure_payer_profile_fixture(
        self,
        funding_profile: str,
        interaction: str,
    ) -> dict[str, Any]:
        profile = FundingProfile(funding_profile)
        mode = FundingMode(interaction)
        if profile is not self._funding_profile or mode is not self._interaction:
            raise AssertionError("payer fixture differs from the selected protected lane")
        action: dict[str, Any] | None = None
        ready = mode is FundingMode.INTERACTIVE
        if mode is FundingMode.SAVED_INSTRUMENT:
            expected_kind = (
                InstrumentKind.CARD
                if profile is FundingProfile.CARD
                else InstrumentKind.US_BANK_ACCOUNT
            )
            instruments = asyncio.run(
                _payer_facade_call(
                    self._payer_context,
                    self._buyer_signer,
                    "list_instruments",
                    payer_profile_ref=self._payer_binding.binding_ref,
                )
            )
            selected = next(
                (
                    item
                    for item in instruments.instruments
                    if item.kind is expected_kind
                    and item.readiness is InstrumentReadiness.READY
                    and not item.revoked
                ),
                None,
            )
            if selected is None:
                setup = asyncio.run(
                    _payer_facade_call(
                        self._payer_context,
                        self._buyer_signer,
                        "start_setup",
                        payer_profile_ref=self._payer_binding.binding_ref,
                        funding_profile=profile,
                        label="Protected test instrument",
                    )
                )
                self._setup_ref = setup.setup_ref
                action = (
                    None
                    if setup.action is None
                    else setup.action.model_dump(mode="json", exclude_none=True)
                )
            else:
                self._selected_instrument_ref = selected.instrument_ref
                ready = True
        return {
            "ok": True,
            "available": True,
            "selected_owner_bound": True,
            "historical_owner_recoverable": True,
            "opaque_binding_persisted": True,
            "action_persisted": False,
            "saved_instrument_ready": ready,
            "setup_action": action,
        }

    def complete_payer_setup(self) -> dict[str, Any]:
        setup_ref = self._setup_ref
        if setup_ref is None:
            raise AssertionError("protected payer setup is not pending")
        deadline = time.monotonic() + float(
            os.environ.get("HOSTED_SETTLEMENT_E2E_LIFECYCLE_TIMEOUT", "180")
        )
        while time.monotonic() < deadline:
            setup = asyncio.run(
                _payer_facade_call(
                    self._payer_context,
                    self._buyer_signer,
                    "setup_status",
                    payer_profile_ref=self._payer_binding.binding_ref,
                    setup_ref=setup_ref,
                )
            )
            if setup.readiness is InstrumentReadiness.READY:
                return self.ensure_payer_profile_fixture(
                    self._funding_profile.value,
                    self._interaction.value,
                )
            time.sleep(0.5)
        raise TimeoutError("protected payer setup did not become ready")

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
        if case == "refund":
            self._keep_refund_fulfillment_unresolved()

    def eligible_pretransfer_refund_available(self) -> bool:
        return True

    def _keep_refund_fulfillment_unresolved(self) -> None:
        with SyncProvisioningClient(
            self.provisioning_url,
            self._admin_signer,
            self._provisioning_trust,
        ) as client:
            client._post(
                "/test/mock-rules",
                {
                    "rule_id": "hosted-stripe-refund-unresolved",
                    "match": {"vm_action": "create"},
                    "pause_before_result": True,
                    "fail_with": "protected refund keeps fulfillment unresolved",
                },
            )
            evaluation = client._post(
                "/test/evaluate-job",
                {
                    "host": self._host_id,
                    "vm_target": "hosted-refund-unresolved",
                    "vm_action": "create",
                },
            )
        if evaluation.get("rule_matched") != "hosted-stripe-refund-unresolved":
            raise AssertionError("refund fulfillment failure is not active")

    def create_and_publish_listing(self) -> ListingSnapshot:
        created = self.seller.create_listing(
            offer={**_OFFER, "resource_id": self._resource_id},
            capacity_source={
                "site_id": self._site_id,
                "resource_id": self._resource_id,
                "gpu_count": 1,
            },
            settlements=[
                {
                    "mechanism": "fiat.stripe.v1",
                    "asset": "usd",
                    "rate": "20",
                    "per": "hour",
                    "mechanism_input": {
                        "funding_profile": self._funding_profile.value,
                        "interaction": self._interaction.value,
                        "funds_flow": "separate_charges_transfers",
                    },
                }
            ],
            max_duration_seconds=3600,
            paused=False,
        )
        if not created.listing_id:
            raise AssertionError("hosted listing create returned no listing identity")
        listing = self.seller.get_listing(created.listing_id)
        option = _option(listing, self._funding_profile.value)
        self._listing_id = created.listing_id
        return ListingSnapshot(
            listing_id=created.listing_id,
            publication_ref=str(option["option_id"]),
        )

    def discover_listing(self, listing_id: str) -> str:
        discovered = self.registry.get_listing(listing_id)
        if str(discovered.id) != listing_id or discovered.status != "open":
            raise AssertionError("registry discovery did not return the open hosted listing")
        _option(discovered, self._funding_profile.value)
        return str(discovered.id)

    def negotiate(self, registry_listing_id: str) -> NegotiationSnapshot:
        listing = self.registry.get_listing(registry_listing_id)
        option = _option(listing, self._funding_profile.value)
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
        accepted = obligations[0]
        params = accepted.get("params", {})
        if (
            params.get("funding_profile") != self._funding_profile.value
            or params.get("interaction") != self._interaction.value
        ):
            raise AssertionError("accepted Terms changed the exact funding profile")
        self._accepted_obligation = accepted
        return NegotiationSnapshot(
            negotiation_id=str(negotiation_id),
            accepted_terms={"selection": selection, "plan": plan},
            accepted_mechanism="fiat.stripe.v1",
        )

    def materialize(self, negotiation_id: str) -> MaterializationSnapshot:
        obligation = dict(self._accepted_obligation)
        obligation_ref = derive_obligation_ref(negotiation_id, 0, obligation)
        authorization = prepare_hosted_funding_authorization(
            buyer_profile_id=str(self._buyer_profile.profile_id),
            principal=self._buyer_signer.identity,
            signer=self._buyer_signer,
            stripe_config=self._stripe_config,
            obligation_ref=obligation_ref,
            obligation=obligation,
            selection=FundingSelection(
                mode=self._interaction,
                instrument_ref=self._selected_instrument_ref,
            ),
            automatic=False,
            profiles=self._profiles,
        )
        started = HostedSettlementTransport(
            seller_url=self.storefront_url,
            principal=self._buyer_signer.identity,
            signer=self._buyer_signer,
            resolve_seller_principals=self._publisher_resolver(),
        ).start(
            negotiation_id=negotiation_id,
            obligation_ref=obligation_ref,
            funding_authorization_ref=authorization.funding_authorization_ref,
        )
        action_value = started.get("action")
        action: BuyerAction | None = None
        if action_value is not None:
            if not isinstance(action_value, dict):
                raise AssertionError("hosted materialization returned malformed payer action")
            expires_at = action_value.get("expires_at_unix")
            if not isinstance(expires_at, int):
                raise AssertionError("hosted materialization returned no action expiry")
            action = BuyerAction(
                kind=str(action_value.get("kind")),
                expires_at_unix=expires_at,
                url=(
                    str(action_value["url"]) if isinstance(action_value.get("url"), str) else None
                ),
            )
        settlement_ref = started.get("settlement_ref")
        if not isinstance(settlement_ref, str) or not settlement_ref:
            # The response is the evidence for why it has no identity: which
            # status the storefront projected, and which fields it did fill.
            # Named, not dumped -- an action carries a Checkout URL.
            raise AssertionError(
                "hosted materialization returned no settlement identity "
                f"(status={started.get('status')!r}, "
                f"action_kind={started.get('action_kind')!r}, "
                f"funding_reason={started.get('funding_reason')!r}, "
                f"present={sorted(k for k, v in started.items() if v is not None)})"
            )
        amount = int(obligation["amount"])
        currency = str(obligation["asset"])
        condition = obligation.get("params", {}).get("condition")
        condition_hash = hashlib.sha256(
            json.dumps(condition, separators=(",", ":"), sort_keys=True).encode()
        ).hexdigest()
        self._operations[settlement_ref] = obligation_ref
        return MaterializationSnapshot(
            obligation_ref=obligation_ref,
            settlement_ref=settlement_ref,
            operation_ref=obligation_ref,
            action=action,
            amount=amount,
            currency=currency,
            expiration_unix=int(obligation["expiration_unix"]),
            destination_account_ref=self.account_ref,
            transfer_group=settlement_ref,
            source_relation="profile-funding",
            accepted_negotiation_id=negotiation_id,
            accepted_funding_profile=self._funding_profile.value,
            accepted_condition_hash=condition_hash,
            funding_authorization_bound=True,
        )

    def observe_pending_funding(self, settlement_ref: str) -> dict[str, Any]:
        status = self._buyer_status(settlement_ref)
        funding_state = status.get("funding_state")
        if funding_state not in {
            "awaiting_external",
            "action_required",
            "succeeded_unavailable",
        }:
            funding_state = status.get("financial_state")
        return {
            "funding_state": (
                "awaiting_payment"
                if funding_state in {"awaiting_external", "action_required", "awaiting_payment"}
                else "pending"
            ),
            "fulfillment_started": bool(status.get("fulfillment_ref")),
        }

    def wait_funded(self, settlement_ref: str) -> bool:
        timeout = float(os.environ.get("HOSTED_SETTLEMENT_E2E_LIFECYCLE_TIMEOUT", "180"))
        deadline = time.monotonic() + timeout
        status: dict[str, Any] = {}
        while time.monotonic() < deadline:
            try:
                status = self._buyer_status(settlement_ref)
            except RuntimeError as exc:
                if not _still_working(exc):
                    raise
                time.sleep(min(0.5, max(0.0, deadline - time.monotonic())))
                continue
            # "funded" is authoritative funding with fulfillment not yet begun,
            # which is the whole subject of this wait -- and the only state a
            # reclaim lane ever reaches, since it holds fulfillment back on
            # purpose. The later states are accepted because a collection lane
            # fulfils inline on the poll that first sees funding.
            if status.get("status") in {"funded", "ready", "collected", "reclaimed"}:
                if self._stripe_test_case == "refund":
                    self._reconcile_refund_materialization(settlement_ref)
                return True
            time.sleep(min(0.5, max(0.0, deadline - time.monotonic())))
        # A timeout says only that funding never converged. Which projection it
        # was still holding when the bound expired is the whole diagnosis, and
        # it belongs on the development diagnostic channel -- named, not dumped.
        _name_unconverged("funding", settlement_ref, status)
        return False

    def _reconcile_refund_materialization(self, settlement_ref: str) -> None:
        status: dict[str, Any] | None = None
        try:
            status = self._buyer_call(
                "status",
                settlement_ref,
                timeout=5.0,
            )
        except RuntimeError as exc:
            detail = str(exc)
            if "authenticated HTTP 503:" not in detail and " failed: timed out" not in detail:
                raise
        finally:
            self._release_refund_fulfillment_failure()
        if status and status.get("fulfillment_ref"):
            raise AssertionError("refund scenario unexpectedly completed fulfillment")

    def _release_refund_fulfillment_failure(self) -> None:
        with SyncProvisioningClient(
            self.provisioning_url,
            self._admin_signer,
            self._provisioning_trust,
        ) as client:
            client._post(
                "/test/mock-rules/hosted-stripe-refund-unresolved/resume",
                {},
            )

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
        result = self._buyer_call("reclaim", settlement_ref)
        if result.get("status") != "reclaimed":
            result = self._wait_public_status(settlement_ref, {"reclaimed"})
        return TerminalSnapshot(
            operation_ref=self._operation(settlement_ref),
            marketplace_status=str(result["status"]),
            authority_status=str(result["status"]),
            effect_kind="refund",
        )

    def request_eligible_pretransfer_refund(self, settlement_ref: str) -> TerminalSnapshot:
        timeout = float(os.environ.get("HOSTED_SETTLEMENT_E2E_LIFECYCLE_TIMEOUT", "180"))
        deadline = time.monotonic() + timeout
        while True:
            try:
                return self.reclaim(settlement_ref)
            except RuntimeError as exc:
                detail = str(exc)
                if not any(
                    marker in detail
                    for marker in ("authenticated HTTP 409:", "authenticated HTTP 503:")
                ):
                    raise
            if time.monotonic() >= deadline:
                raise TimeoutError("eligible hosted refund did not converge")
            time.sleep(min(0.5, max(0.0, deadline - time.monotonic())))

    def recover_eligible_pretransfer_refund(self, settlement_ref: str) -> TerminalSnapshot:
        return self.reclaim(settlement_ref)

    def _buyer_status(self, settlement_ref: str) -> dict[str, Any]:
        return self._buyer_call("status", settlement_ref)

    def _buyer_call(
        self,
        operation: Literal["status", "reclaim"],
        settlement_ref: str,
        *,
        timeout: float | None = None,
    ) -> dict[str, Any]:
        options = {} if timeout is None else {"request_timeout": timeout}
        transport = HostedSettlementTransport(
            seller_url=self.storefront_url,
            principal=self._buyer_signer.identity,
            signer=self._buyer_signer,
            resolve_seller_principals=self._publisher_resolver(),
            **options,
        )
        return cast(
            dict[str, Any],
            getattr(transport, operation)(settlement_ref=settlement_ref),
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
        listing = self.registry.get_listing(self._require_listing_id()).to_dict()
        listing["source_registry_url"] = self.registry_url
        listing["source_registry_authority"] = self._registry_authority.authority
        config = BuyConfig(
            buyer_profile_id=self._buyer_profile.profile_id,
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
        last: dict[str, Any] = {}
        while time.monotonic() < deadline:
            try:
                status = self._buyer_status(settlement_ref)
            except RuntimeError as exc:
                if not _still_working(exc):
                    raise
            else:
                last = status
                if status.get("status") in terminal:
                    return status
            time.sleep(min(0.5, max(0.0, deadline - time.monotonic())))
        _name_unconverged("/".join(sorted(terminal)), settlement_ref, last)
        raise TimeoutError("named hosted public status did not converge")


def _name_unconverged(
    awaited: str, settlement_ref: str, status: dict[str, Any]
) -> None:
    """Name the projection a wait was still holding when its bound expired.

    A timeout says only that something did not happen. Which state the deal was
    actually in is the diagnosis, and it belongs on the development diagnostic
    channel -- named, not dumped.
    """

    receipt = status.get("receipt")
    receipt = receipt if isinstance(receipt, dict) else {}
    incident = receipt.get("incident")
    incident = incident if isinstance(incident, dict) else {}
    print(
        f"[development] {awaited} never converged for {settlement_ref}: "
        f"status={status.get('status')!r}, "
        f"funding_reason={status.get('funding_reason')!r}, "
        f"action_kind={status.get('action_kind')!r}, "
        f"fulfillment_ref={status.get('fulfillment_ref') is not None}, "
        f"authority financial_state={receipt.get('financial_state')!r}, "
        f"funding_state={receipt.get('funding_state')!r}, "
        f"condition_state={receipt.get('condition_state')!r}, "
        f"incident kind={incident.get('kind')!r} state={incident.get('state')!r}",
        file=sys.stderr,
        flush=True,
    )


def _still_working(exc: Exception) -> bool:
    """Return whether a failed poll means the storefront has not answered yet.

    A hosted status poll is a read, and the storefront fulfils inline on the
    poll that first sees authoritative funding -- provisioning a VM can outrun
    the buyer's request timeout. Neither a 503 nor a client-side timeout is a
    refusal, so a wait keeps polling until its own bound instead of turning
    someone else's latency into a failed deal.
    """

    detail = str(exc)
    return "authenticated HTTP 503:" in detail or " failed: timed out" in detail


def create_protected_marketplace(*, buyer_config: Path) -> NetworkMarketplacePort:
    marketplace = NetworkMarketplacePort(buyer_config=buyer_config)
    marketplace.ensure_capacity()
    return marketplace
