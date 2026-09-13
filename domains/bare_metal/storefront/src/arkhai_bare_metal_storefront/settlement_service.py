"""Commercial settlement verification without fulfillment claims."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from typing import Any

from market_core.schemas import EscrowProposal, SettlementPlan
from market_alkahest.plans import (
    AcceptedAlkahestObligation,
    decode_accepted_alkahest_obligation,
)
from market_settlement_runtime import SettlementRuntime
from market_identity import Identity

from arkhai_bare_metal import BareMetalTerms

from .models import (
    BareMetalSettleRequest,
    BareMetalSettleResponse,
    BareMetalSettleStatusResponse,
)
from .sqlite_client import SQLiteClient


class SettlementRequestError(ValueError):
    def __init__(self, detail: str, *, status_code: int = 409) -> None:
        super().__init__(detail)
        self.detail = detail
        self.status_code = status_code


VerifyEscrow = Callable[..., Awaitable[int]]
PlanBuilder = Callable[..., dict[str, Any]]

ALKAHEST_MECHANISM = "alkahest.v1"


@dataclass(frozen=True)
class _AcceptedAlkahestSettlement:
    """The immutable accepted agreement an exact selection settles against."""

    plan: SettlementPlan
    terms: AcceptedAlkahestObligation


def _accepted_int(value: Any, *, field: str) -> int:
    """Read one integer an accepted record carries in an opaque carrier.

    Mechanism params, service terms and the selection envelope are opaque to
    the plan schema, so a malformed or absent number reaches this resolver as
    raw JSON. It is a refusal to settle, not a server fault.
    """
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise SettlementRequestError(
            f"accepted agreement carries an unreadable {field}"
        ) from exc


def _principal(value: Any) -> Identity:
    try:
        return Identity.model_validate(value)
    except Exception as exc:
        raise SettlementRequestError(
            "accepted agreement names an unreadable principal"
        ) from exc


def _accepted_alkahest_settlement(
    thread: Mapping[str, Any],
    *,
    agreed_amount: int,
    listing_id: str,
    terms: BareMetalTerms,
    buyer_principal: Identity,
    seller_principal: Identity,
) -> _AcceptedAlkahestSettlement:
    """Read the accepted obligation an exact-selection thread committed.

    An exact selection persists a selection envelope rather than a legacy
    escrow proposal, so the funded terms live only in the accepted plan. That
    plan is the financial authority here: the listing's advertised terms are
    mutable and a later refresh must never redefine what the buyer funded.

    The plan is only that authority while it still agrees with the rest of the
    committed record, so every party, role, selected option and physical fact
    it declares is bound back to the thread and the domain terms artifact.
    Anything inconsistent fails closed before a chain read or a write.
    """
    raw_plan = thread.get("settlement_plan")
    try:
        plan = SettlementPlan.model_validate(raw_plan)
    except Exception as exc:
        raise SettlementRequestError(
            "accepted settlement plan is missing or invalid"
        ) from exc
    if len(plan.obligations) != 1:
        raise SettlementRequestError(
            "accepted settlement plan must carry one obligation"
        )
    if (
        _principal(plan.buyer_principal) != buyer_principal
        or _principal(plan.seller_principal) != seller_principal
    ):
        raise SettlementRequestError(
            "accepted settlement plan names different parties"
        )
    obligation = plan.obligations[0]
    raw_obligations = (
        raw_plan.get("obligations") if isinstance(raw_plan, Mapping) else None
    )
    raw_obligation = (
        raw_obligations[0]
        if isinstance(raw_obligations, list) and len(raw_obligations) == 1
        else obligation.model_dump(mode="json")
    )
    try:
        accepted = decode_accepted_alkahest_obligation(raw_obligation)
    except Exception as exc:
        raise SettlementRequestError(
            "accepted obligation does not name a funded Alkahest escrow"
        ) from exc
    # The buyer funds and the seller collects; the reverse would let a
    # reclaim-side record settle as a payment.
    if obligation.payer != "buyer" or obligation.claimant != "seller":
        raise SettlementRequestError(
            "accepted obligation does not carry the negotiated settlement roles"
        )
    if (
        _principal(obligation.payer_principal) != buyer_principal
        or _principal(obligation.claimant_principal) != seller_principal
    ):
        raise SettlementRequestError(
            "accepted obligation names different settlement parties"
        )
    if accepted.amount != agreed_amount:
        raise SettlementRequestError(
            "accepted obligation disagrees with the committed agreement"
        )
    chain_name = accepted.escrow_terms.chain_name
    assert chain_name is not None
    escrow_address = accepted.escrow_terms.escrow_contract

    physical = (plan.service_terms or {}).get("bare_metal.v1")
    if not isinstance(physical, Mapping) or physical.get("listing_id") != listing_id:
        raise SettlementRequestError(
            "accepted agreement does not name the negotiated listing"
        )
    try:
        accepted_terms = BareMetalTerms.model_validate(
            physical.get("provision_terms")
        )
    except Exception as exc:
        raise SettlementRequestError(
            "accepted agreement carries no readable provision terms"
        ) from exc
    if accepted_terms.model_dump(mode="json", exclude_none=True) != terms.model_dump(
        mode="json", exclude_none=True
    ):
        raise SettlementRequestError(
            "accepted agreement disagrees with the committed bare-metal terms"
        )
    # The producer writes the same physical facts twice, in the provision
    # terms and in the binding the listing was published from. A record whose
    # two views disagree is not one agreement.
    binding = physical.get("physical_binding")
    if not isinstance(binding, Mapping):
        raise SettlementRequestError(
            "accepted agreement carries no physical binding"
        )
    if (
        str(binding.get("physical_host_id") or "") != terms.physical_host_id
        or str(binding.get("access_method") or "") != terms.access_method
    ):
        raise SettlementRequestError(
            "accepted physical binding disagrees with the committed terms"
        )

    raw_selection = thread.get("buyer_escrow_proposal") or {}
    selection = (
        raw_selection.get("settlement_selection")
        if isinstance(raw_selection, Mapping)
        else None
    )
    if not isinstance(selection, Mapping):
        raise SettlementRequestError("accepted agreement carries no exact selection")
    mechanism = str(selection.get("mechanism") or "")
    option_id = str(selection.get("option_id") or "")
    mechanism_terms = (plan.service_terms or {}).get(ALKAHEST_MECHANISM)
    if (
        mechanism != ALKAHEST_MECHANISM
        or str(physical.get("mechanism") or "") != ALKAHEST_MECHANISM
        or not option_id
        or str(physical.get("option_id") or "") != option_id
        or not isinstance(mechanism_terms, Mapping)
        or str(mechanism_terms.get("option_id") or "") != option_id
        or str(mechanism_terms.get("listing_id") or "") != listing_id
    ):
        raise SettlementRequestError(
            "accepted selection does not name the accepted settlement option"
        )
    if _accepted_int(
        selection.get("expiration_unix"), field="selection expiration"
    ) != int(obligation.expiration_unix):
        raise SettlementRequestError(
            "accepted selection disagrees with the accepted obligation"
        )
    if (
        str(mechanism_terms.get("chain_name") or "") != chain_name
        or str(mechanism_terms.get("escrow_contract") or "") != escrow_address
        or _accepted_int(
            mechanism_terms.get("expiration_unix"), field="settlement expiration"
        )
        != int(obligation.expiration_unix)
    ):
        raise SettlementRequestError(
            "accepted settlement terms disagree with the accepted obligation"
        )
    return _AcceptedAlkahestSettlement(
        plan=plan,
        terms=accepted,
    )


@dataclass(frozen=True)
class BareMetalSettlementService:
    db: SQLiteClient
    seller_wallet: str
    chain_clients: Mapping[str, Any]
    chain_config_paths: Mapping[str, str | None]
    build_plan: PlanBuilder
    verify_escrow: VerifyEscrow
    settlement_runtime: SettlementRuntime

    @staticmethod
    def _response(
        *,
        escrow_uid: str,
        negotiation_id: str,
        buyer_principal: Identity,
        seller_principal: Identity,
        obligation_ref: str | None = None,
    ) -> BareMetalSettleResponse:
        return BareMetalSettleResponse(
            escrow_uid=escrow_uid,
            negotiation_id=negotiation_id,
            buyer_principal=buyer_principal,
            seller_principal=seller_principal,
            obligation_ref=obligation_ref,
        )

    async def _owned_thread(
        self,
        *,
        negotiation_id: str,
        buyer_principal: Identity,
    ) -> dict[str, Any]:
        thread = await self.db.load_negotiation_thread_row(
            negotiation_id=negotiation_id,
        )
        if thread is None:
            raise SettlementRequestError("negotiation not found", status_code=404)
        if Identity.model_validate(thread.get("buyer_principal")) != buyer_principal:
            raise SettlementRequestError("negotiation buyer mismatch", status_code=403)
        return thread

    async def verify(
        self,
        *,
        escrow_uid: str,
        request: BareMetalSettleRequest,
        buyer_principal: Identity,
    ) -> BareMetalSettleResponse:
        existing = await self.db.load_escrow(escrow_uid=escrow_uid)
        thread = await self._owned_thread(
            negotiation_id=request.negotiation_id,
            buyer_principal=buyer_principal,
        )
        if thread.get("terminal_state") != "success":
            raise SettlementRequestError("negotiation is not accepted")
        agreed_amount = thread.get("agreed_price")
        duration = thread.get("agreed_duration_seconds")
        if agreed_amount is None or not isinstance(duration, int) or duration < 1:
            raise SettlementRequestError("negotiation has no committed agreement")
        terms = await self.db.load_bare_metal_terms(
            negotiation_id=request.negotiation_id,
        )
        if terms is None or terms.duration_seconds != duration:
            raise SettlementRequestError(
                "bare-metal agreement terms are missing or inconsistent"
            )
        listing = await self.db.load_listing(listing_id=thread["our_listing_id"])
        if listing is None:
            raise SettlementRequestError(
                "negotiated listing not found", status_code=404
            )
        offer = await self.db.load_bare_metal_listing_payload(
            listing_id=thread["our_listing_id"],
        )
        assert offer is not None
        if (
            offer.machine_id != terms.machine_id
            or offer.physical_host_id != terms.physical_host_id
            or terms.listing_ref != thread["our_listing_id"]
        ):
            raise SettlementRequestError(
                "bare-metal agreement no longer matches its listing"
            )
        raw_proposal = thread.get("buyer_escrow_proposal")
        accepted: _AcceptedAlkahestSettlement | None = None
        if isinstance(raw_proposal, Mapping) and "settlement_selection" in raw_proposal:
            accepted = _accepted_alkahest_settlement(
                thread,
                agreed_amount=int(agreed_amount),
                listing_id=str(thread["our_listing_id"]),
                terms=terms,
                buyer_principal=buyer_principal,
                seller_principal=Identity.model_validate(
                    thread["seller_principal"],
                ),
            )
            proposal = accepted.terms.verifier_proposal
        else:
            proposal = EscrowProposal.model_validate(raw_proposal)
        primary = await self.db.load_primary_escrow_for_negotiation(
            negotiation_id=request.negotiation_id,
        )
        if primary is not None and primary.get("escrow_uid") != escrow_uid:
            raise SettlementRequestError("negotiation already has a primary escrow")
        if existing is not None and (
            existing.get("negotiation_id") != request.negotiation_id
            or existing.get("status") != "settlement_verified"
            or existing.get("chain_name") != proposal.chain_name
            or str(existing.get("escrow_address", "")).lower()
            != proposal.escrow_address.lower()
        ):
            raise SettlementRequestError(
                "escrow identity already belongs to another state"
            )

        try:
            if accepted is not None:
                # The accepted plan is already committed and immutable;
                # rebuilding it would re-derive funded terms from the listing.
                plan = accepted.plan
            else:
                artifacts = self.build_plan(
                    proposal=proposal,
                    agreed_amount=int(agreed_amount),
                    duration_seconds=terms.duration_seconds,
                    buyer_principal=buyer_principal,
                    seller_principal=Identity.model_validate(
                        thread["seller_principal"],
                    ),
                    seller_wallet_address=self.seller_wallet,
                    chain_config_paths=self.chain_config_paths,
                )
                plan = SettlementPlan.model_validate(artifacts.get("settlement_plan"))
        except SettlementRequestError:
            raise
        except Exception as exc:
            raise SettlementRequestError(
                "settlement verification failed",
                status_code=400,
            ) from exc
        obligations = tuple(
            obligation.model_dump(mode="json") for obligation in plan.obligations
        )
        if not obligations:
            raise SettlementRequestError(
                "accepted settlement plan has no obligations",
                status_code=400,
            )

        records = None
        if existing is not None:
            try:
                records = await self.settlement_runtime.register_plan(
                    agreement_ref=request.negotiation_id,
                    obligations=list(obligations),
                )
            except Exception as exc:
                raise SettlementRequestError(
                    "settlement plan conflicts with accepted terms"
                ) from exc
            adopted = [
                record
                for record in records
                if record.mechanism_ref == escrow_uid
                and record.materialization_state == "materialized"
            ]
            if len(adopted) == 1:
                return self._response(
                    escrow_uid=escrow_uid,
                    negotiation_id=request.negotiation_id,
                    buyer_principal=buyer_principal,
                    seller_principal=Identity.model_validate(
                        thread["seller_principal"],
                    ),
                    obligation_ref=adopted[0].obligation_ref,
                )
            if any(record.mechanism_ref == escrow_uid for record in records):
                raise SettlementRequestError(
                    "verified settlement adoption is incomplete"
                )

        client = self.chain_clients.get(proposal.chain_name)
        if client is None:
            raise SettlementRequestError(
                f"settlement chain {proposal.chain_name!r} is unavailable",
                status_code=503,
            )
        try:
            matched_index = await self.verify_escrow(
                escrow_uid=escrow_uid,
                seller_wallet=self.seller_wallet,
                agreed_price=int(agreed_amount),
                agreed_duration_seconds=terms.duration_seconds,
                listing=listing,
                alkahest_client=client,
                chain_name=proposal.chain_name,
                alkahest_address_config_path=self.chain_config_paths.get(
                    proposal.chain_name,
                ),
                escrow_proposal=proposal,
                **(
                    # Compare the chain against the exact bytes and deadline
                    # the buyer funded, not against a re-derivation of them.
                    {
                        "expected_obligation_data": accepted.terms.obligation_data,
                        "expected_expiration_unix": (
                            accepted.terms.escrow_terms.expiration_unix
                        ),
                    }
                    if accepted is not None
                    else {}
                ),
            )
        except SettlementRequestError:
            raise
        except Exception as exc:
            raise SettlementRequestError(
                "settlement verification failed",
                status_code=400,
            ) from exc
        if (
            isinstance(matched_index, bool)
            or not isinstance(matched_index, int)
            or matched_index < 0
            or matched_index >= len(obligations)
        ):
            raise SettlementRequestError(
                "settlement verification returned no exact obligation",
                status_code=400,
            )

        if records is None:
            try:
                records = await self.settlement_runtime.register_plan(
                    agreement_ref=request.negotiation_id,
                    obligations=list(obligations),
                )
            except Exception as exc:
                raise SettlementRequestError(
                    "settlement plan conflicts with accepted terms"
                ) from exc

        try:
            outcome = await self.settlement_runtime.adopt(
                records[matched_index].obligation_ref,
                local_principal=Identity.model_validate(thread["seller_principal"]),
                mechanism_ref=escrow_uid,
                receipt=None,
                condition_anchor=None,
                mechanism_state=None,
                worker_id="bare-metal-verified",
            )
        except Exception as exc:
            raise SettlementRequestError(
                "conflicting verified settlement adoption"
            ) from exc
        if outcome.status != "succeeded":
            raise SettlementRequestError("verified settlement adoption is incomplete")
        if existing is None:
            inserted = await self.db.insert_escrow(
                escrow_uid=escrow_uid,
                negotiation_id=request.negotiation_id,
                chain_name=proposal.chain_name,
                escrow_address=proposal.escrow_address,
                is_primary=True,
                status="settlement_verified",
            )
            if not inserted:
                raced = await self.db.load_escrow(escrow_uid=escrow_uid)
                if not raced or (
                    raced.get("negotiation_id") != request.negotiation_id
                    or raced.get("chain_name") != proposal.chain_name
                    or str(raced.get("escrow_address", "")).lower()
                    != proposal.escrow_address.lower()
                    or raced.get("status") != "settlement_verified"
                ):
                    raise SettlementRequestError("conflicting escrow settlement")
        return self._response(
            escrow_uid=escrow_uid,
            negotiation_id=request.negotiation_id,
            buyer_principal=buyer_principal,
            seller_principal=Identity.model_validate(thread["seller_principal"]),
            obligation_ref=records[matched_index].obligation_ref,
        )

    async def status(
        self,
        *,
        escrow_uid: str,
        buyer_principal: Identity,
    ) -> BareMetalSettleStatusResponse:
        escrow = await self.db.load_escrow(escrow_uid=escrow_uid)
        if escrow is None:
            raise SettlementRequestError("escrow not found", status_code=404)
        await self._owned_thread(
            negotiation_id=str(escrow["negotiation_id"]),
            buyer_principal=buyer_principal,
        )
        try:
            aggregate = await self.settlement_runtime.get_status(
                str(escrow["negotiation_id"])
            )
        except Exception as exc:
            raise SettlementRequestError(
                "verified settlement lifecycle is unavailable"
            ) from exc
        adopted = [
            obligation
            for obligation in aggregate.obligations
            if obligation.mechanism_ref == escrow_uid
            and obligation.materialization_state == "materialized"
        ]
        if len(adopted) != 1 or adopted[0].fulfillment_ref is not None:
            raise SettlementRequestError(
                "verified settlement lifecycle is inconsistent"
            )
        return BareMetalSettleStatusResponse(
            escrow_uid=escrow_uid,
            negotiation_id=str(escrow["negotiation_id"]),
            buyer_principal=buyer_principal,
            seller_principal=Identity.model_validate(
                (await self._owned_thread(
                    negotiation_id=str(escrow["negotiation_id"]),
                    buyer_principal=buyer_principal,
                ))["seller_principal"],
            ),
            status=str(escrow["status"]),
            obligation_ref=adopted[0].obligation_ref,
        )
