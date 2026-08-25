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
    RETURN_INSTRUCTIONS_EMAIL_OPTION,
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

def _create_payer_when_admitted(context: Any, signer: Any, *, country: str) -> Any:
    """Create the payer profile once the authority will admit one.

    Binding an account and the account becoming ready are not the same moment:
    the authority reconciles readiness after the binding lands, so a payer
    created in between is refused. The refusal arrives as `invalid_response`,
    which reads like a malformed answer rather than a state that has not
    arrived yet, and it kills the bridge before any stage runs.

    Waiting here rather than at the call site keeps the port's own construction
    honest: a port that exists has a payer, or the wait says why it never got
    one.
    """

    deadline = time.monotonic() + float(
        os.environ.get("HOSTED_SETTLEMENT_E2E_ADMISSION_TIMEOUT", "120")
    )
    last: Exception | None = None
    while True:
        try:
            return asyncio.run(
                _payer_facade_call(context, signer, "create", country=country)
            )
        except Exception as exc:  # the facade names the authority's refusal
            last = exc
            if time.monotonic() >= deadline:
                raise RuntimeError(
                    "hosted authority never admitted a payer profile; last "
                    f"refusal: {exc}"
                ) from exc
            time.sleep(min(2.0, max(0.0, deadline - time.monotonic())))


def _obligation_expiration(case: str | None) -> int:
    """How long the accepted obligation lives.

    A reclaim needs one short enough that pre-transfer reclaim becomes eligible
    inside a run. The override exists so a lane can hold every other variable
    still and vary only this, which is how the window is told apart from the
    scenario using it.
    """

    raw = os.environ.get("HOSTED_SETTLEMENT_E2E_OBLIGATION_EXPIRATION")
    if raw:
        value = int(raw)
        if value <= 0:
            raise ValueError("obligation expiration must be positive")
        return value
    return _REFUND_EXPIRATION_SECONDS if case == "refund" else 3600


def _materialize_timeout() -> dict[str, float]:
    """The materialize request bound, overridable for profiles that fund inline.

    The bridge that drives this process gives up on its own bound, so a
    materialize bound at or above it can never be reached: the outer wait
    abandons a subprocess that is still working correctly, and the run reports a
    stage that did not converge when what expired was the harness. Refuse that
    pairing rather than let a setting mean nothing.
    """

    raw = os.environ.get("HOSTED_SETTLEMENT_E2E_MATERIALIZE_TIMEOUT")
    if not raw:
        return {}
    value = float(raw)
    if value <= 0:
        raise ValueError("materialize timeout must be positive")
    outer = os.environ.get("HOSTED_SETTLEMENT_E2E_LIFECYCLE_TIMEOUT")
    if outer and value >= float(outer):
        raise ValueError(
            f"materialize timeout {value} must be below the lifecycle bound "
            f"{float(outer)} that governs this process"
        )
    return {"request_timeout": value}


class HostedAuthorityRefusal(RuntimeError):
    """An authority answer a wait must not keep retrying.

    The authority states a code and its own ``retryable`` flag on every refusal.
    That flag means the identical request may be re-sent, which is not the same
    question a polling wait asks: a lost reservation is not re-sendable, yet the
    condition behind it can still clear. So a wait retries what it knows can
    change and treats every other refusal as an answer.
    """

    def __init__(self, code: str, detail: str) -> None:
        super().__init__(f"hosted authority refused: {code}")
        self.code = code
        self.detail = detail


#: Refusals a polling wait may outlast. ``operation_conflict`` is the
#: compare-and-set race the eligible-reclaim wait exists for.
_RETRYABLE_REFUSAL_CODES = frozenset({"operation_conflict"})


def _authority_refusal(exc: RuntimeError) -> tuple[str | None, bool]:
    """Return the authority's refusal code and whether a wait may retry it.

    The buyer client puts the response body into the error message, so the
    structured code the authority already sends is readable here without a
    second request.
    """

    detail = str(exc)
    index = detail.find("authenticated HTTP ")
    if index < 0:
        return None, False
    separator = detail.find(":", index)
    if separator < 0:
        return None, False
    try:
        parsed = json.loads(detail[separator + 1 :].strip())
    except (ValueError, TypeError):
        return None, False
    if not isinstance(parsed, dict):
        return None, False
    code = parsed.get("code")
    if isinstance(code, str) and code:
        return code, parsed.get("retryable") is True or code in _RETRYABLE_REFUSAL_CODES
    # The storefront answers in its own shape and does not forward the
    # authority's code, so the only thing that survives the boundary is its
    # detail string. Recording it keeps a wait from reporting "no refusal" when
    # it was in fact refused repeatedly, and names the layer to look at next.
    detail_text = parsed.get("detail")
    if isinstance(detail_text, str) and detail_text:
        # Retryable on purpose. The storefront collapses every mechanism failure
        # into its own shape, so a permanent refusal and a lost reservation are
        # indistinguishable here; stopping on both would abandon the retry this
        # wait exists for. Recording the text still turns "no refusal" into the
        # sentence the storefront actually returned, which names the layer that
        # dropped the authority's code.
        return f"storefront: {detail_text[:120]}", True
    return None, False


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
        payer = _create_payer_when_admitted(
            self._payer_context,
            buyer_signer,
            country=self._stripe_config.country,
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
        # A setup's identity is derived from its label, and the authority turns
        # that identity into a provider idempotency key. Stripe remembers such a
        # key for a day; the authority forgets its own state the moment the run
        # ends. A fixed label therefore replays a burnt key with a moved expiry
        # and the second setup of any day is refused. Scoping the label to the
        # run keeps retries inside one run idempotent, which is what idempotency
        # is for, without asking Stripe to answer for state nobody kept.
        self._instrument_label = f"Protected test instrument {_required('HOSTED_SETTLEMENT_E2E_RUN_REF')}"[:64]
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
        payment_method: str | None = None,
    ) -> dict[str, Any]:
        profile = FundingProfile(funding_profile)
        mode = FundingMode(interaction)
        if profile is not self._funding_profile or mode is not self._interaction:
            raise AssertionError("payer fixture differs from the selected protected lane")
        action: dict[str, Any] | None = None
        verification_pending = False
        ready = mode is FundingMode.INTERACTIVE
        if mode is FundingMode.SAVED_INSTRUMENT:
            expected_kind = (
                InstrumentKind.CARD
                if profile is FundingProfile.CARD
                else InstrumentKind.US_BANK_ACCOUNT
            )
            selected = self._ready_instrument(expected_kind)
            if selected is None:
                setup = asyncio.run(
                    _payer_facade_call(
                        self._payer_context,
                        self._buyer_signer,
                        "start_setup",
                        payer_profile_ref=self._payer_binding.binding_ref,
                        funding_profile=profile,
                        label=self._instrument_label,
                        payment_method=payment_method,
                    )
                )
                self._setup_ref = setup.setup_ref
                # An authority handed the payer's own instrument has nothing to
                # ask a browser for; it waits for the deposits instead, or, where
                # the instrument needs no deposits, for nothing at all.
                verification_pending = (
                    setup.readiness is InstrumentReadiness.VERIFICATION_PENDING
                )
                # A setup the authority completed on the spot is already usable.
                # A directly handed card confirms off-session, so it arrives
                # ready here rather than after a browser or a deposit, and a
                # fixture that ignored that would demand a browser action for a
                # setup that has already finished.
                #
                # The setup result names no instrument, so the instrument it
                # produced is resolved the one way this side can: by asking
                # again. A deposit-bound setup reaches the same call later,
                # through verification.
                if setup.readiness is InstrumentReadiness.READY:
                    selected = self._ready_instrument(expected_kind)
                    if selected is None:
                        raise AssertionError(
                            "a completed payer setup produced no ready instrument"
                        )
                    self._selected_instrument_ref = selected.instrument_ref
                    ready = True
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
            "setup_verification_pending": verification_pending,
        }

    def _ready_instrument(self, expected_kind: InstrumentKind):
        """The payer's own ready instrument of that kind, or nothing."""

        instruments = asyncio.run(
            _payer_facade_call(
                self._payer_context,
                self._buyer_signer,
                "list_instruments",
                payer_profile_ref=self._payer_binding.binding_ref,
            )
        )
        return next(
            (
                item
                for item in instruments.instruments
                if item.kind is expected_kind
                and item.readiness is InstrumentReadiness.READY
                and not item.revoked
            ),
            None,
        )

    def verify_payer_setup(
        self,
        *,
        amounts: tuple[int, ...] | None,
        descriptor_code: str | None,
    ) -> dict[str, Any]:
        """Answer a pending setup with the payer's own deposit evidence."""

        setup_ref = self._setup_ref
        if setup_ref is None:
            raise AssertionError("payer setup is not pending verification")
        setup = asyncio.run(
            _payer_facade_call(
                self._payer_context,
                self._buyer_signer,
                "verify_setup",
                payer_profile_ref=self._payer_binding.binding_ref,
                setup_ref=setup_ref,
                amounts=amounts,
                descriptor_code=descriptor_code,
            )
        )
        if setup.readiness is not InstrumentReadiness.READY:
            raise AssertionError("payer setup did not become ready on submitted evidence")
        return self.ensure_payer_profile_fixture(
            self._funding_profile.value,
            self._interaction.value,
        )

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

    def induce_test_ach_return(self, settlement_ref: str) -> dict[str, object]:
        """Report that the return this lane needs is already on its way.

        Nothing is induced here, because the return was armed before the
        payment existed: the lane funds from the test account Stripe settles
        and then disputes. There is no later moment to reach in and cause one,
        so this states that the arming happened rather than pretending to act.
        """

        del settlement_ref
        return {"ok": True}

    def _funds_within_materialization(self) -> bool:
        """Whether funding completes inside the materialize call.

        A saved card the payer already holds is charged off-session during
        materialization; every other shape returns first and funds after.
        """

        return (
            self._funding_profile is FundingProfile.CARD
            and self._interaction is FundingMode.SAVED_INSTRUMENT
        )

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
                    # Holding the job before its result keeps fulfillment
                    # unresolved, and the release runs once funding is observed.
                    # A profile that funds inside materialization never gets
                    # there: the storefront polls this job within that same
                    # request, so the call that would release it cannot run
                    # until the call it is blocking returns. Resuming a held
                    # job yields this same failure, so failing at once reaches
                    # the identical state without the deadlock.
                    "pause_before_result": not self._funds_within_materialization(),
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
            _obligation_expiration(self._stripe_test_case)
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
            # Materialization is answered inline, so how long it may take is a
            # property of the profile rather than of the transport. A card the
            # payer already holds funds within this call, which a profile that
            # waits on a bank does not.
            **_materialize_timeout(),
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
        # Only a held job needs releasing. Where the job was failed outright,
        # there is nothing paused to resume and asking would refuse.
        if self._funds_within_materialization():
            return
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
        last_refusal: str | None = None
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
                code, retryable = _authority_refusal(exc)
                if code is not None:
                    last_refusal = code
                    if not retryable:
                        # Waiting cannot change this answer. Outlasting it would
                        # report a cause the authority already gave as a stage
                        # that did not converge.
                        raise HostedAuthorityRefusal(code, detail) from exc
            if time.monotonic() >= deadline:
                raise TimeoutError(
                    "eligible hosted refund did not converge; last refusal: "
                    f"{last_refusal or 'none received'}"
                )
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
        call: dict[str, Any] = {"settlement_ref": settlement_ref}
        if operation == "reclaim":
            mechanism_options = self._reclaim_options()
            if mechanism_options:
                call["mechanism_options"] = mechanism_options
        return cast(dict[str, Any], getattr(transport, operation)(**call))

    def _reclaim_options(self) -> dict[str, str]:
        """What this buyer has to say about how its funding comes back.

        A push-funded obligation is returned by mailing the payer for return
        bank details, so the run supplies the address it is entitled to use.
        The address is given to the run rather than derived here, because
        deriving it would mean holding provider credentials in the buyer role.
        """

        if self._funding_profile is not FundingProfile.US_BANK_TRANSFER:
            return {}
        address = os.environ.get("HOSTED_SETTLEMENT_E2E_RETURN_ADDRESS", "").strip()
        if not address:
            # Naming the missing input beats letting the authority refuse a
            # request the run could not have completed anyway.
            raise RuntimeError(
                "selected hosted E2E scenario is missing prerequisite: "
                "HOSTED_SETTLEMENT_E2E_RETURN_ADDRESS"
            )
        return {RETURN_INSTRUCTIONS_EMAIL_OPTION: address}

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
        parked = False
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
                if status.get("status") == "manual_required":
                    # Only a parked obligation that names its reason is one a
                    # wait may stop on. The marketplace guarantees a reason for
                    # every obligation the authority itself parked, so a reason
                    # means a person is genuinely required and time cannot help.
                    #
                    # Without one the state is merely derived from the
                    # authority's current status on this poll, which a later
                    # poll re-derives -- stopping there would fail a lane for a
                    # state it was passing through. Record it and keep waiting.
                    reason = status.get("funding_reason")
                    parked = True
                    # A reason the wait already knows can clear is not a reason
                    # to stop. Losing a compare-and-set reservation parks the
                    # obligation and then resolves itself, so stopping on it
                    # fails a lane for the one refusal that was always meant to
                    # be outlasted.
                    if reason in _RETRYABLE_REFUSAL_CODES:
                        reason = None
                    if reason:
                        _name_unconverged(
                            "/".join(sorted(terminal)), settlement_ref, status
                        )
                        raise HostedAuthorityRefusal(
                            str(reason),
                            "hosted obligation parked awaiting operator "
                            f"evidence: {reason!r}",
                        )
            time.sleep(min(0.5, max(0.0, deadline - time.monotonic())))
        _name_unconverged("/".join(sorted(terminal)), settlement_ref, last)
        if parked:
            raise HostedAuthorityRefusal(
                "settlement_parked",
                "hosted obligation held an unexplained operator-evidence state "
                "until the wait expired",
            )
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
