"""API-credit storefront composition over the shared settlement runtime."""

from __future__ import annotations

import logging
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from domains.apicredits.settlement import (
    ApiCreditsIssuanceEvidenceBodyV1,
    CreditIssuanceRequest,
    CreditsServiceClient,
    ExpectedApiCreditsIssuanceEvidenceV1,
    decode_portable_issuance_fulfillment_ref,
    prepare_credit_issuance_request,
)
from market_alkahest import (
    AlkahestConditionalEscrowClient,
    create_alkahest_registration,
)
from market_core import MarketDomainContract
from market_core.schemas import (
    SettlementObligation,
    SettlementOption,
    SettlementPlan,
    SettlementSelection,
)
from market_hosted_settlement import (
    ConditionDescriptor,
    FundingProfile,
    StripeSettlementConfig,
    create_stripe_registration,
    stripe_accepted_obligation_builder,
)
from market_identity import Identity, Signer, TrustedIdentitySet
from market_settlement_runtime import (
    MechanismReadiness,
    SettlementConfigurationRegistry,
    SettlementPublicationClause,
    SettlementRuntime,
    SettlementServicingWorker,
    SettlementSQLiteRepository,
    compile_settlement_publication_clause,
    derive_obligation_ref,
)

from apicredits_storefront.services.issuance_evidence import (
    ApiCreditPrivateResultRepository,
    ApiCreditsIssuanceEvidenceService,
    IssuanceEvidenceRepository,
)
from apicredits_storefront.utils import config as storefront_config

logger = logging.getLogger(__name__)


def _mapping(value: Any) -> dict[str, Any]:
    if hasattr(value, "model_dump"):
        return dict(value.model_dump(mode="json"))
    return dict(value) if isinstance(value, Mapping) else {}


def build_storefront_settlement_registry() -> SettlementConfigurationRegistry:
    """Install peer Alkahest and hosted mechanism registrations."""
    return SettlementConfigurationRegistry(
        (create_alkahest_registration(), create_stripe_registration())
    )


@dataclass(frozen=True, slots=True)
class ApiCreditsHostedAgreement:
    agreement_ref: str
    obligation_ref: str
    buyer_principal: Identity
    seller_principal: Identity
    obligation: dict[str, Any]
    selection: SettlementSelection
    option: SettlementOption
    listing_id: str
    order: dict[str, Any]
    service: str
    resource_id: str
    quantity: int
    key_mode: str
    key_id: str | None


@dataclass(frozen=True, slots=True)
class ApiCreditsSettlementComposition:
    domain: MarketDomainContract
    repository: SettlementSQLiteRepository
    runtime: SettlementRuntime
    worker: SettlementServicingWorker
    local_principal: Identity
    mechanism_clients: Mapping[str, Any]
    settlement_config: Any
    configuration_registry: SettlementConfigurationRegistry
    mechanism_resources: Mapping[str, Any]
    credits_client: CreditsServiceClient
    evidence_service: ApiCreditsIssuanceEvidenceService
    private_results: ApiCreditPrivateResultRepository
    failure_policy: Any

    async def readiness(self) -> tuple[MechanismReadiness, ...]:
        return await self.configuration_registry.ordered_readiness(
            self.settlement_config,
            role="seller",
            resources=self.mechanism_resources,
        )

    def accepted_obligation_dispatch(
        self,
    ) -> dict[str, Callable[[Mapping[str, Any], Mapping[str, Any]], Any]]:
        """Curried registry dispatch for every enabled obligation-building mechanism."""

        dispatch: dict[str, Callable[[Mapping[str, Any], Mapping[str, Any]], Any]] = {}
        for mechanism_id in self.settlement_config.priority:
            registration = self.configuration_registry.registration(mechanism_id)
            if registration.accepted_obligation_builder is None:
                continue

            def build(
                option: Mapping[str, Any],
                context: Mapping[str, Any],
                *,
                _mechanism_id: str = mechanism_id,
            ) -> Any:
                return self.configuration_registry.build_accepted_obligation(
                    _mechanism_id,
                    option,
                    self.settlement_config,
                    role="seller",
                    context=context,
                )

            dispatch[mechanism_id] = build
        return dispatch

    async def publication_artifacts(
        self,
        resources: Mapping[str, Any],
        clauses: list[SettlementPublicationClause | Mapping[str, Any]] | None = None,
    ) -> tuple[
        list[dict[str, Any]], list[dict[str, Any]], tuple[MechanismReadiness, ...]
    ]:
        """Compile each complete ready clause without suppressing ready peers."""
        merged_resources = {**self.mechanism_resources, **resources}
        compiled = (
            [
                compile_settlement_publication_clause(
                    clause,
                    registry=self.configuration_registry,
                    config=self.settlement_config,
                    role="seller",
                )
                for clause in clauses
            ]
            if clauses is not None
            else None
        )
        readiness_resources = merged_resources
        if compiled is not None:
            alkahest_chains = tuple(
                dict.fromkeys(
                    str(clause.mechanism_input["chain"])
                    for clause in compiled
                    if clause.mechanism == "alkahest.v1"
                    and isinstance(clause.mechanism_input.get("chain"), str)
                )
            )
            hosted_clauses = [
                clause.model_dump(mode="json")
                for clause in compiled
                if clause.mechanism == "fiat.stripe.v1"
            ]
            readiness_resources = {
                **merged_resources,
                **(
                    {
                        "accepted_escrows": [
                            {"chain_name": name} for name in alkahest_chains
                        ]
                    }
                    if alkahest_chains
                    else {}
                ),
                **({"publication_clauses": hosted_clauses} if hosted_clauses else {}),
            }
        readiness = await self.configuration_registry.ordered_readiness(
            self.settlement_config,
            role="seller",
            resources=readiness_resources,
        )
        statuses = {status.mechanism: status for status in readiness}
        work = (
            [
                (
                    statuses.get(clause.mechanism),
                    {**merged_resources, "publication_clause": clause},
                )
                for clause in compiled
            ]
            if compiled is not None
            else [(status, merged_resources) for status in readiness]
        )
        accepted_escrows: list[dict[str, Any]] = []
        settlement_options: list[dict[str, Any]] = []
        for status, option_resources in work:
            if status is None:
                raise RuntimeError("settlement clause has no registered mechanism")
            if not status.enabled:
                if compiled is not None:
                    raise ValueError(
                        f"settlement publication mechanism {status.mechanism!r} is disabled"
                    )
                continue
            if not status.ready:
                logger.warning(
                    "[SETTLEMENT] option suppressed mechanism=%s blockers=%s",
                    status.mechanism,
                    ",".join(blocker.code for blocker in status.blockers),
                )
                continue
            envelope = self.configuration_registry.build_option(
                status,
                self.settlement_config,
                role="seller",
                resources=option_resources,
            )
            if not isinstance(envelope, Mapping):
                raise RuntimeError("settlement option builder returned no envelope")
            accepted_escrows.extend(
                dict(item) for item in envelope.get("accepted_escrows", ())
            )
            settlement_options.extend(
                dict(item) for item in envelope.get("settlement_options", ())
            )
        if not accepted_escrows and not settlement_options:
            raise RuntimeError("no enabled settlement mechanism is ready")
        return accepted_escrows, settlement_options, readiness


async def load_api_credit_hosted_agreement(
    *,
    sqlite_client: Any,
    agreement_ref: str,
    expected_claimant: Identity,
    obligation_ref: str | None = None,
) -> ApiCreditsHostedAgreement:
    """Reload and validate the exact accepted API-credit hosted obligation."""
    thread = await sqlite_client.load_negotiation_thread_row(
        negotiation_id=agreement_ref
    )
    if not thread or thread.get("terminal_state") != "success":
        raise ValueError("hosted settlement negotiation is not accepted")
    buyer = Identity.model_validate(thread.get("buyer_principal"))
    seller = Identity.model_validate(thread.get("seller_principal"))
    if seller != expected_claimant:
        raise ValueError("accepted seller principal does not match storefront")
    raw_plan = thread.get("settlement_plan")
    if not isinstance(raw_plan, Mapping):
        raise ValueError("accepted negotiation has no pinned settlement plan")
    plan = SettlementPlan.model_validate(raw_plan)
    if len(plan.obligations) != 1:
        raise ValueError("hosted settlement plan must contain exactly one obligation")
    obligation = plan.obligations[0].model_dump(mode="json")
    if obligation.get("mechanism") != "fiat.stripe.v1":
        raise ValueError("accepted negotiation did not select hosted settlement")
    derived_ref = derive_obligation_ref(agreement_ref, 0, obligation)
    if obligation_ref is not None and derived_ref != obligation_ref:
        raise ValueError("hosted obligation identifier does not match accepted plan")
    if (
        plan.buyer_principal is None
        or Identity.model_validate(plan.buyer_principal) != buyer
    ):
        raise ValueError("accepted plan buyer principal mismatch")
    if (
        plan.seller_principal is None
        or Identity.model_validate(plan.seller_principal) != seller
    ):
        raise ValueError("accepted plan seller principal mismatch")
    service_state = _mapping(plan.service_terms.get("api_credits.v1"))
    listing_id = str(service_state.get("listing_id") or "")
    order = _mapping(service_state.get("order"))
    quantity = service_state.get("quantity")
    key_mode = service_state.get("key_mode")
    key_id = service_state.get("key_id")
    if not listing_id or order.get("listing_id") != listing_id:
        raise ValueError("accepted API-credit listing identity is inconsistent")
    if isinstance(quantity, bool) or not isinstance(quantity, int) or quantity < 1:
        raise ValueError("accepted API-credit quantity is invalid")
    if key_mode not in {"new", "existing"}:
        raise ValueError("accepted API-credit key mode is invalid")
    if (key_mode == "new") != (key_id is None):
        raise ValueError("accepted API-credit key target is invalid")
    carrier = _mapping(thread.get("buyer_escrow_proposal"))
    selection = SettlementSelection.model_validate(
        carrier.get("settlement_selection", carrier)
    )
    options = [
        SettlementOption.model_validate(value)
        for value in order.get("settlement_options", ())
    ]
    matches = [
        option
        for option in options
        if option.option_id == selection.option_id
        and option.mechanism == selection.mechanism
    ]
    if len(matches) != 1:
        raise ValueError("accepted hosted option is not exact in trusted listing")
    option = matches[0]
    if selection.expiration_unix != obligation.get("expiration_unix"):
        raise ValueError("hosted expiry does not match accepted selection")
    # The accepted plan and this reload verify against one definition: the
    # mechanism's own accepted-obligation builder rebuilds the canonical
    # obligation from the trusted option, and the persisted record must
    # match it exactly.
    try:
        rebuilt = stripe_accepted_obligation_builder(
            StripeSettlementConfig(),
            option.model_dump(mode="json"),
            {
                "buyer_principal": buyer.model_dump(mode="json"),
                "seller_principal": seller.model_dump(mode="json"),
                "expiration_unix": selection.expiration_unix,
                "unit_quantity": quantity,
                "domain_param_keys": (),
            },
        )
    except (TypeError, ValueError) as exc:
        raise ValueError(
            "accepted hosted option cannot rebuild its exact obligation"
        ) from exc
    expected_obligation = SettlementObligation.model_validate(
        rebuilt.obligation
    ).model_dump(mode="json")
    if obligation != expected_obligation:
        raise ValueError("hosted obligation does not match its trusted rebuild")
    if thread.get("agreed_price") != rebuilt.amount:
        raise ValueError("hosted amount does not match exact quantity pricing")
    resource = _mapping(order.get("offer_resource"))
    service = str(resource.get("service_name") or "")
    resource_id = str(resource.get("resource_id") or "")
    if not service or not resource_id:
        raise ValueError("trusted API-credit service/resource is unavailable")
    return ApiCreditsHostedAgreement(
        agreement_ref=agreement_ref,
        obligation_ref=derived_ref,
        buyer_principal=buyer,
        seller_principal=seller,
        obligation=obligation,
        selection=selection,
        option=option,
        listing_id=listing_id,
        order=order,
        service=service,
        resource_id=resource_id,
        quantity=quantity,
        key_mode=key_mode,
        key_id=str(key_id) if key_id is not None else None,
    )


def _issuance_request(agreement: ApiCreditsHostedAgreement) -> CreditIssuanceRequest:
    return prepare_credit_issuance_request(
        obligation_ref=agreement.obligation_ref,
        mechanism="fiat.stripe.v1",
        authoritative_gate="hosted_funded",
        owner=agreement.buyer_principal,
        service=agreement.service,
        resource_id=agreement.resource_id,
        quantity=agreement.quantity,
        key_mode=agreement.key_mode,
        key_id=agreement.key_id,
    )


def _assert_exact_issuance(request: CreditIssuanceRequest, issuance: Any) -> None:
    for name in (
        "fulfillment_id",
        "obligation_ref",
        "mechanism",
        "owner",
        "service",
        "resource_id",
        "quantity",
        "request_digest",
    ):
        if getattr(issuance, name) != getattr(request, name):
            raise ValueError(f"credits authority changed immutable {name}")
    if issuance.key_mode != request.key.mode:
        raise ValueError("credits authority changed immutable key mode")
    if request.key.key_id is not None and issuance.key_id != request.key.key_id:
        raise ValueError("credits authority changed immutable key id")


def _condition(agreement: ApiCreditsHostedAgreement) -> ConditionDescriptor:
    raw = _mapping(agreement.obligation.get("params")).get("condition")
    if raw is None:
        conditions = agreement.obligation.get("conditions") or []
        raw = conditions[0] if conditions else None
    return ConditionDescriptor.model_validate(raw)


async def _committed_issuance(
    composition: ApiCreditsSettlementComposition,
    agreement: ApiCreditsHostedAgreement,
) -> tuple[CreditIssuanceRequest, Any]:
    request = _issuance_request(agreement)
    try:
        issuance = await composition.credits_client.submit_credit_issuance(request)
    except Exception:
        issuance = await composition.credits_client.get_credit_issuance(
            request.fulfillment_id
        )
        if issuance is None:
            raise RuntimeError(
                "credits issuance outcome is not authoritative"
            ) from None
        _assert_exact_issuance(request, issuance)
        if request.key.mode == "new" and issuance.secret is None:
            issuance = await composition.credits_client.submit_credit_issuance(request)
    _assert_exact_issuance(request, issuance)
    if request.key.mode == "new":
        if issuance.secret is None:
            raise RuntimeError(
                "committed new-key issuance has no recoverable bearer secret"
            )
        composition.private_results.store(
            fulfillment_id=issuance.fulfillment_id,
            owner=agreement.buyer_principal,
            key_id=issuance.key_id,
            secret=issuance.secret,
        )
    elif issuance.secret is not None:
        raise ValueError(
            "credits authority returned a bearer secret for existing-key issuance"
        )
    return request, issuance


async def ensure_hosted_fulfillment(
    *,
    composition: ApiCreditsSettlementComposition,
    sqlite_client: Any,
    record: Any,
    worker_id: str,
) -> Any:
    """Issue once after authoritative funding and bind signed portable evidence."""
    if record.fulfillment_ref:
        await composition.worker.wake(record.obligation_ref)
        return record
    if record.mechanism_status != "ready":
        return record
    reserved = await composition.runtime.reserve_fulfillment(
        record.obligation_ref,
        local_principal=composition.local_principal,
        worker_id=worker_id,
    )
    if reserved.status in {"busy", "succeeded"}:
        row = await composition.repository.load_settlement_obligation(
            record.obligation_ref
        )
        return type(record).model_validate(row)
    agreement = await load_api_credit_hosted_agreement(
        sqlite_client=sqlite_client,
        agreement_ref=record.agreement_ref,
        obligation_ref=record.obligation_ref,
        expected_claimant=composition.local_principal,
    )
    if not record.condition_anchor:
        error = ValueError("hosted authority returned no immutable condition anchor")
        await composition.runtime.retry_fulfillment(
            record.obligation_ref,
            error,
            local_principal=composition.local_principal,
            worker_id=worker_id,
        )
        raise error
    try:
        request, issuance = await _committed_issuance(composition, agreement)
        condition = _condition(agreement)
        resolver_id = condition.evaluator.resolver_id
        if not resolver_id:
            raise ValueError("hosted condition has no configured evidence resolver")
        stripe = composition.settlement_config.mechanism_config("stripe")
        resolver = _mapping(getattr(stripe, "resolvers", {}).get(resolver_id))
        if resolver.get("evidence_mode") != "portable-remote.v1":
            raise ValueError("API-credit hosted evidence must use portable-remote.v1")
        publisher = composition.mechanism_clients.get("fiat.stripe.v1")
        if publisher is None:
            raise ValueError("hosted evidence publisher is unavailable")
        body = ApiCreditsIssuanceEvidenceBodyV1(
            condition_anchor=record.condition_anchor,
            obligation_ref=agreement.obligation_ref,
            fulfillment_id=issuance.fulfillment_id,
            grant_id=issuance.grant_id,
            service=agreement.service,
            resource_id=agreement.resource_id,
            quantity=agreement.quantity,
            key_mode=agreement.key_mode,
            key_id=issuance.key_id,
            owner=agreement.buyer_principal,
            buyer=agreement.buyer_principal,
            claimant=agreement.seller_principal,
            issuer=composition.local_principal,
            committed_at_unix=issuance.committed_at_unix,
            request_digest=request.request_digest,
        )
        publication = await composition.evidence_service.publish_portable(
            body,
            publisher=publisher,
            resolver_id=resolver_id,
        )
        completed = await composition.runtime.complete_fulfillment(
            record.obligation_ref,
            publication.fulfillment_ref,
            local_principal=composition.local_principal,
            worker_id=worker_id,
        )
        logger.info(
            "[SETTLEMENT] API-credit issuance evidence committed obligation=%s key=%s",
            record.obligation_ref,
            issuance.key_id,
        )
    except Exception as exc:
        await composition.runtime.retry_fulfillment(
            record.obligation_ref,
            exc,
            local_principal=composition.local_principal,
            worker_id=worker_id,
        )
        raise
    await composition.worker.wake(record.obligation_ref)
    return completed


async def reconcile_before_reclaim(
    *,
    composition: ApiCreditsSettlementComposition,
    sqlite_client: Any,
    record: Any,
    worker_id: str,
) -> Any:
    """Resolve an uncertain grant before financial reclaim can win."""
    if record.fulfillment_ref:
        return record
    agreement = await load_api_credit_hosted_agreement(
        sqlite_client=sqlite_client,
        agreement_ref=record.agreement_ref,
        obligation_ref=record.obligation_ref,
        expected_claimant=composition.local_principal,
    )
    request = _issuance_request(agreement)
    issuance = await composition.credits_client.get_credit_issuance(
        request.fulfillment_id
    )
    if issuance is None:
        return record
    _assert_exact_issuance(request, issuance)
    if record.mechanism_status != "ready":
        raise ValueError("credits grant committed while hosted funding is not ready")
    return await ensure_hosted_fulfillment(
        composition=composition,
        sqlite_client=sqlite_client,
        record=record,
        worker_id=worker_id,
    )


def hosted_public_status(record: Any) -> str:
    if record.reclaim_state == "succeeded":
        return "reclaimed"
    if any(
        value == "manual_required"
        for value in (
            record.materialization_state,
            record.condition_state,
            record.collection_state,
            record.reclaim_state,
            record.mechanism_status,
        )
    ):
        return "manual_required"
    if record.collection_state == "succeeded":
        return "collected"
    if record.condition_state == "failed" or record.mechanism_status == "failed":
        return "failed"
    if record.mechanism_status == "ready":
        return "ready" if record.fulfillment_ref else "funded"
    return record.mechanism_status or "pending"


async def hosted_settlement_projection(
    *,
    composition: ApiCreditsSettlementComposition,
    record: Any,
    transient_action: Mapping[str, Any] | None = None,
    transient_receipt: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Project safe financial state plus owner-authenticated credential output."""
    params = {
        **_mapping(record.obligation.get("params")),
        **_mapping(record.mechanism_params),
    }
    profile = FundingProfile(params.get("funding_profile"))
    authorization_ref = params.get("funding_authorization_ref")
    if not isinstance(authorization_ref, str):
        raise ValueError("hosted settlement has no immutable funding authorization")
    receipt = dict(
        transient_receipt
        or record.reclaim_receipt
        or record.collection_receipt
        or record.status_receipt
        or record.materialization_receipt
        or {}
    )
    state = _mapping(record.mechanism_state)
    action = dict(transient_action) if transient_action else None
    action_metadata = action or _mapping(record.buyer_action)
    result: dict[str, Any] | None = None
    credentials: dict[str, Any] | None = None
    if record.fulfillment_ref:
        portable = decode_portable_issuance_fulfillment_ref(record.fulfillment_ref)
        evidence = composition.evidence_service.resolve(portable.evidence_digest)
        if evidence is None:
            raise ValueError("committed fulfillment evidence is unavailable")
        body = evidence.body
        expected = ExpectedApiCreditsIssuanceEvidenceV1(
            condition_anchor=body.condition_anchor,
            obligation_ref=body.obligation_ref,
            fulfillment_id=body.fulfillment_id,
            grant_id=body.grant_id,
            service=body.service,
            resource_id=body.resource_id,
            quantity=body.quantity,
            key_mode=body.key_mode,
            key_id=body.key_id,
            owner=body.owner,
            buyer=body.buyer,
            claimant=body.claimant,
            issuer=body.issuer,
            request_digest=body.request_digest,
            funding_expiration_unix=int(record.obligation.get("expiration_unix") or 0),
        )
        composition.evidence_service.resolve_verified(
            portable.evidence_digest, expected=expected
        )
        credentials_ref = composition.private_results.credentials_ref(
            body.fulfillment_id, body.owner
        )
        private = composition.private_results.get(
            credentials_ref=credentials_ref,
            owner=body.owner,
        )
        result = {
            "fulfillment_id": body.fulfillment_id,
            "grant_id": body.grant_id,
            "service": body.service,
            "resource_id": body.resource_id,
            "quantity": body.quantity,
            "key_mode": body.key_mode,
            "key_id": body.key_id,
            "evidence_digest": portable.evidence_digest,
            "fulfillment_ref": record.fulfillment_ref,
            **({"credentials_ref": credentials_ref} if private is not None else {}),
        }
        if private is not None:
            credentials = {
                "credentials_ref": credentials_ref,
                "key_id": private.key_id,
                "secret": private.secret,
            }
    return {
        "settlement_ref": record.mechanism_ref,
        "obligation_ref": record.obligation_ref,
        "funding_authorization_ref": authorization_ref,
        "funding_profile": profile.value,
        "payer_principal": record.payer_principal,
        "claimant_principal": record.claimant_principal,
        "status": hosted_public_status(record),
        "funding_reason": receipt.get("funding_reason") or state.get("funding_reason"),
        "funding_deadline_unix": receipt.get("funding_deadline_unix")
        or state.get("funding_deadline_unix"),
        "action": action,
        "action_kind": action_metadata.get("kind"),
        "action_expires_at_unix": action_metadata.get("expires_at_unix"),
        "receipt": receipt or None,
        "result": result,
        "tenant_credentials": credentials,
    }


async def cleanup_hosted_settlement(
    *,
    composition: ApiCreditsSettlementComposition,
    sqlite_client: Any,
    agreement_ref: str,
    reason: str,
) -> None:
    """Release an uncommitted quota hold after authoritative reclaim."""
    hold = await sqlite_client.load_capacity_hold(negotiation_id=agreement_ref)
    if not hold:
        return
    payload = dict(hold.get("payload") or {})
    await composition.failure_policy.apply(
        sqlite_client,
        {
            "capacity_reservation_id": hold.get("capacity_reservation_id"),
            "escrow_uid": None,
            "listing_id": payload.get("listing_id"),
            "resource_id": payload.get("resource_id"),
            "reason": "hosted_reclaim",
            "message": reason,
            "source": "hosted_settlement",
            "state": None,
            "reopened_listing_ids": [],
        },
    )
    await sqlite_client.delete_capacity_hold(negotiation_id=agreement_ref)


def build_api_credit_settlement_composition(
    *,
    domain: MarketDomainContract,
    sqlite_client: Any,
    alkahest_clients: Mapping[str, Any],
    marketplace_signer: Signer,
    failure_policy: Any,
) -> ApiCreditsSettlementComposition:
    """Build lazy mechanism clients and the shared servicing worker."""
    repository = SettlementSQLiteRepository(
        sqlite_client.db_path, apply_migrations=False
    )
    registry = build_storefront_settlement_registry()
    settlement_config = registry.resolve(
        storefront_config.settlement_config_mapping(),
        role="seller",
    )
    resources: dict[str, Any] = {
        "marketplace_signer": marketplace_signer,
        "clients": dict(alkahest_clients),
        "get_client": lambda chain: alkahest_clients.get(chain or ""),
        "chains": storefront_config.CHAINS,
        "default_chain": next(iter(storefront_config.CHAINS), None),
    }
    mechanism_clients: dict[str, Any] = {}
    for registration in registry.ordered_registrations(
        settlement_config, role="seller"
    ):
        section = settlement_config.mechanism_config(registration.config_key)
        if section is None or not getattr(section, "enabled", False):
            continue
        if registration.mechanism_id == "alkahest.v1":
            mechanism_clients[registration.mechanism_id] = (
                AlkahestConditionalEscrowClient(
                    get_client=resources["get_client"],
                    chain_config_paths={
                        name: chain.alkahest_address_config_path
                        for name, chain in storefront_config.CHAINS.items()
                    },
                    default_chain=resources["default_chain"],
                )
            )
        else:
            mechanism_clients[registration.mechanism_id] = registry.create_client(
                registration.mechanism_id,
                settlement_config,
                role="seller",
                resources=resources,
            )
    hosted_client = mechanism_clients.get("fiat.stripe.v1")
    if hosted_client is not None:
        resources["hosted_client"] = hosted_client
    runtime = SettlementRuntime(repository, mechanism_clients)
    credits_client = CreditsServiceClient(
        storefront_config.credits_service_url(),
        storefront_config.credits_admin_key(),
    )
    evidence_service = ApiCreditsIssuanceEvidenceService(
        IssuanceEvidenceRepository(sqlite_client.db_path),
        signer=marketplace_signer,
        trusted_issuers=TrustedIdentitySet(identities=(marketplace_signer.identity,)),
    )
    private_results = ApiCreditPrivateResultRepository(sqlite_client.db_path)
    holder: dict[str, ApiCreditsSettlementComposition] = {}

    async def on_ready(record: Any, worker_id: str) -> None:
        if record.obligation.get("mechanism") != "fiat.stripe.v1":
            return
        await ensure_hosted_fulfillment(
            composition=holder["value"],
            sqlite_client=sqlite_client,
            record=record,
            worker_id=worker_id,
        )

    worker = SettlementServicingWorker(
        runtime,
        repository,
        worker_id=f"api-credit-storefront:{storefront_config.AGENT_ID}",
        interval_seconds=float(
            storefront_config.settings.get("claims_sweep_interval", 30)
        ),
        on_ready=on_ready,
    )
    composition = ApiCreditsSettlementComposition(
        domain=domain,
        repository=repository,
        runtime=runtime,
        worker=worker,
        local_principal=marketplace_signer.identity,
        mechanism_clients=mechanism_clients,
        settlement_config=settlement_config,
        configuration_registry=registry,
        mechanism_resources=resources,
        credits_client=credits_client,
        evidence_service=evidence_service,
        private_results=private_results,
        failure_policy=failure_policy,
    )
    holder["value"] = composition
    return composition


__all__ = [
    "ApiCreditsHostedAgreement",
    "ApiCreditsSettlementComposition",
    "build_api_credit_settlement_composition",
    "build_storefront_settlement_registry",
    "cleanup_hosted_settlement",
    "ensure_hosted_fulfillment",
    "hosted_settlement_projection",
    "load_api_credit_hosted_agreement",
    "reconcile_before_reclaim",
]
