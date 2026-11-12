"""VM shim over the core buyer negotiation client.

The core owns round sequencing and opaque acceptance checks. Shape-priced
listings use the VM amount codec: policy scalars are basis points while accepted
outcomes carry derived payments. Flat listings scale hourly bounds by the
selected billing span: one period or the reserved term. A recurring horizon is
optional; the VM outcome also carries the buyer's requested duration.

Importing this module also installs the RL middleware registrar so
``rl``-named policies in buyer.toml resolve (core cannot import
``domains.*``).
"""

from __future__ import annotations

from market_identity import EnvelopeCapture

import dataclasses
from dataclasses import dataclass
from functools import partial
from typing import Any, Callable, Optional

from core_buyer.negotiation_client import (  # noqa: F401 — re-exports
    DEFAULT_MAX_ROUNDS,
    DEFAULT_TIMEOUT_SECONDS,
    NegotiationOutcome as CoreNegotiationOutcome,
    ResumeState,
    set_rl_middleware_registrar,
)
from core_buyer.negotiation_client import (
    load_buyer_chain as _core_load_buyer_chain,
    negotiate_with_seller as _core_negotiate_with_seller,
    parse_accepted_terms_from_reply as _core_parse_accepted_terms_from_reply,
)
from market_alkahest.schemas import EscrowProposal
from market_core.schemas import SettlementPlan, SettlementSelection
from market_policy.negotiation_middleware import NegotiationMiddleware
from market_identity import Identity, Signer, TrustedIdentitySet

from arkhai_vms import VmProvisionTerms, normalize_vm_provision_terms

from .common import chain_address_books
from .escrow_client import encode_escrow_proposal
from .settlement_composition import validate_buyer_acceptance
from .negotiation_amounts import amount_codec, priced_unit_count


def _validate_model(model_type, value):
    """Decode wire dictionaries while tolerating an already-decoded model."""
    if isinstance(value, model_type):
        return value
    if hasattr(value, "model_dump"):
        value = value.model_dump()
    return model_type.model_validate(value)


def _register_rl_middleware() -> None:
    """Trigger self-registration of the torch RL middleware.

    Imports ``arkhai_vms_negotiation.rl.torch_arkhai_strategy`` so its
    ``register_negotiation_middleware("rl")`` call fires. Best-effort —
    if torch / pufferlib aren't installed, the chain loader raises its
    own actionable KeyError pointing at the [rl] extras.
    """
    import arkhai_vms_negotiation.rl.torch_arkhai_strategy  # noqa: F401


set_rl_middleware_registrar(_register_rl_middleware)


def load_buyer_chain(**kwargs):
    """Load negotiation middleware with each configured chain's Alkahest
    address book, as the buyer's Alkahest section names it."""
    kwargs.setdefault("chain_config_paths", chain_address_books)
    return _core_load_buyer_chain(**kwargs)


def parse_accepted_terms_from_reply(reply: dict[str, Any]):
    """Decode core's opaque accepted settlement payloads as Alkahest models."""
    provision, proposal, selection, plan = _core_parse_accepted_terms_from_reply(reply)
    return (
        VmProvisionTerms.model_validate(provision) if provision is not None else None,
        EscrowProposal.model_validate(proposal) if proposal is not None else None,
        selection,
        plan,
    )


@dataclass
class NegotiationOutcome(CoreNegotiationOutcome):
    """Core outcome plus the VM domain's ``duration_seconds`` echo.

    ``duration_seconds`` is the buyer's lease ask from negotiation init
    (None on resume) — the VM reading of the core ``unit_count``
    (hours × 3600).
    """

    accepted_provision_terms: Optional[VmProvisionTerms] = None
    accepted_escrow_proposal: Optional[EscrowProposal] = None
    duration_seconds: Optional[float] = None

    def to_dict(self) -> dict[str, Any]:
        d = super().to_dict()
        if self.accepted_provision_terms is not None:
            d["accepted_provision_terms"] = self.accepted_provision_terms.model_dump()
        if self.accepted_escrow_proposal is not None:
            d["accepted_escrow_proposal"] = self.accepted_escrow_proposal.model_dump()
        if self.duration_seconds is not None:
            d["duration_seconds"] = self.duration_seconds
        return d


def negotiate_with_seller(
    *,
    seller_url: str,
    principal: Identity,
    signer: Signer,
    listing_id: str,
    initial_price: float,
    max_price: float,
    provision_terms: Optional[VmProvisionTerms] = None,
    escrow_proposal: Optional[EscrowProposal] = None,
    settlement_selection: Optional[SettlementSelection] = None,
    max_rounds: int = DEFAULT_MAX_ROUNDS,
    on_round: Optional[Callable[[int, dict, dict], None]] = None,
    chain: Optional[list[NegotiationMiddleware]] = None,
    resume: Optional[ResumeState] = None,
    policy_params: Optional[dict[str, Any]] = None,
    resolve_seller_principals: Callable[[], TrustedIdentitySet],
    validate_advertised_plan: Callable[[SettlementPlan], None] | None = None,
    validate_acceptance: Callable[[CoreNegotiationOutcome], None]
    | None = validate_buyer_acceptance,
    capture: EnvelopeCapture | None = None,
    listing: dict[str, Any] | None = None,
) -> NegotiationOutcome:
    """Run a synchronous negotiation with one seller, round-by-round.

    Prices are per-hour bounds for the shape the buyer opens with. A
    seller-authenticated registry ``listing`` with a rate structure converts
    those bounds to basis points once; accepted terms determine the monetary
    payment, which may not exceed ``max_price`` over one period for a recurring
    option, or over the accepted duration for a reserved one. Without a rate
    structure, the selected period or reserved lease hours scale the bounds.

    ``validate_acceptance`` defaults to the purchase table's entry guard. An
    introduction has no purchase entry and passes None; its command checks
    the accepted plan itself.
    """
    duration_seconds: Optional[float] = None
    if resume is None:
        if provision_terms is None:
            raise RuntimeError(
                "provision_terms is required for fresh negotiations "
                "(what the seller will provision: duration, ssh_key, compute)"
            )
        if (escrow_proposal is None) == (settlement_selection is None):
            raise RuntimeError(
                "exactly one of escrow_proposal or settlement_selection is "
                "required for fresh negotiations"
            )
        duration_seconds = provision_terms.duration_seconds

    proposal_for_amount = settlement_selection or escrow_proposal
    opening_terms: Any = provision_terms
    if resume is not None:
        proposal_for_amount = next(
            (entry.proposal for entry in resume.transcript if entry.sender == "us" and entry.proposal),
            None,
        )
        # The seller's round-zero echo is the complete shape the run opened with.
        opening_terms = resume.accepted_provision_terms
    codec = (
        amount_codec(
            listing, proposal_for_amount, opening_terms=opening_terms, max_price=max_price,
        )
        if proposal_for_amount is not None else None
    )
    if validate_acceptance is validate_buyer_acceptance and listing is not None:
        # A purchase holds the signed horizon to the authenticated listing's
        # bounds and to what the buyer opened with; a resumed run opened with the
        # seller's round-zero echo of the buyer's terms.
        opening = opening_terms.model_dump(mode="json") if hasattr(opening_terms, "model_dump") else opening_terms
        validate_acceptance = partial(
            validate_buyer_acceptance, listing=listing,
            requested_duration_seconds=(
                normalize_vm_provision_terms(opening).duration_seconds if opening is not None else None
            ),
        )
    core_outcome = _core_negotiate_with_seller(
        seller_url=seller_url,
        principal=principal,
        signer=signer,
        listing_id=listing_id,
        initial_price=initial_price,
        max_price=max_price,
        unit_count=(
            priced_unit_count(listing, proposal_for_amount, duration_seconds) if resume is None else None
        ),
        provision_terms=provision_terms,
        encode_escrow_proposal=encode_escrow_proposal,
        escrow_proposal=escrow_proposal,
        decode_provision_terms=lambda value: _validate_model(VmProvisionTerms, value),
        decode_escrow_proposal=lambda value: _validate_model(EscrowProposal, value),
        settlement_selection=settlement_selection,
        max_rounds=max_rounds,
        on_round=on_round,
        chain=chain,
        resume=resume,
        policy_params=policy_params,
        validate_advertised_plan=validate_advertised_plan,
        validate_acceptance=validate_acceptance,
        amount_codec=codec,
        resolve_seller_principals=resolve_seller_principals,
        capture=capture,
    )
    values = {
        field.name: getattr(core_outcome, field.name)
        for field in dataclasses.fields(CoreNegotiationOutcome)
    }
    if core_outcome.accepted_provision_terms is not None:
        values["accepted_provision_terms"] = _validate_model(
            VmProvisionTerms, core_outcome.accepted_provision_terms
        )
    if core_outcome.accepted_escrow_proposal is not None:
        values["accepted_escrow_proposal"] = _validate_model(
            EscrowProposal, core_outcome.accepted_escrow_proposal
        )
    return NegotiationOutcome(**values, duration_seconds=duration_seconds)
