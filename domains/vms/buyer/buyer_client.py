"""VM shim over the core buyer negotiation client.

The round loop, chain loading, and outcome parsing moved to
``core_buyer.negotiation_client`` when the API-credits domain became the
second schema plugin. The seam that moved with it: listings broadcast
**per-unit** rates and the core client scales them to absolute amounts
by ``unit_count`` — this module supplies the VM unit, the lease hour
(``duration_seconds / 3600``), and re-attaches ``duration_seconds`` to
the outcome for VM callers and run-log compatibility.

Importing this module also installs the RL middleware registrar so
``rl``-named policies in buyer.toml resolve (core cannot import
``domains.*``).
"""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass
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
from market_alkahest.schemas import EscrowProposal, EscrowTerms
from market_core.schemas import SettlementPlan, SettlementSelection
from market_policy.negotiation_middleware import NegotiationMiddleware
from market_identity import Identity, Signer, TrustedIdentitySet

from arkhai_vms import VmProvisionTerms

from .escrow_client import encode_escrow_proposal


def _validate_model(model_type, value):
    """Decode wire dictionaries while tolerating an already-decoded model."""
    if isinstance(value, model_type):
        return value
    if hasattr(value, "model_dump"):
        value = value.model_dump()
    return model_type.model_validate(value)


def _register_rl_middleware() -> None:
    """Trigger self-registration of the torch RL middleware.

    Imports ``domains.vms.negotiation.rl.torch_arkhai_strategy`` so its
    ``register_negotiation_middleware("rl")`` call fires. Best-effort —
    if torch / pufferlib aren't installed, the chain loader raises its
    own actionable KeyError pointing at the [rl] extras.
    """
    import domains.vms.negotiation.rl.torch_arkhai_strategy  # noqa: F401


set_rl_middleware_registrar(_register_rl_middleware)


def load_buyer_chain(**kwargs):
    """Load negotiation middleware with VM-owned chain address config."""
    from .common import buyer_chains

    kwargs.setdefault(
        "chain_config_paths",
        lambda: {
            name: chain.alkahest_address_config_path
            for name, chain in buyer_chains().items()
        },
    )
    return _core_load_buyer_chain(**kwargs)


def parse_accepted_terms_from_reply(reply: dict[str, Any]):
    """Decode core's opaque accepted settlement payloads as Alkahest models."""
    provision, proposal, selection, plan, terms = _core_parse_accepted_terms_from_reply(
        reply
    )
    return (
        VmProvisionTerms.model_validate(provision) if provision is not None else None,
        EscrowProposal.model_validate(proposal) if proposal is not None else None,
        selection,
        plan,
        [EscrowTerms.model_validate(term) for term in terms]
        if terms is not None
        else None,
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
    accepted_escrow_terms: Optional[list[EscrowTerms]] = None
    duration_seconds: Optional[float] = None

    def to_dict(self) -> dict[str, Any]:
        d = super().to_dict()
        if self.accepted_provision_terms is not None:
            d["accepted_provision_terms"] = self.accepted_provision_terms.model_dump()
        if self.accepted_escrow_proposal is not None:
            d["accepted_escrow_proposal"] = self.accepted_escrow_proposal.model_dump()
        if self.accepted_escrow_terms is not None:
            d["accepted_escrow_terms"] = [
                term.model_dump() for term in self.accepted_escrow_terms
            ]
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
) -> NegotiationOutcome:
    """Run a synchronous negotiation with one seller, round-by-round.

    VM instantiation of ``core_buyer.negotiation_client
    .negotiate_with_seller``: prices are per-hour rates, scaled to
    absolute amounts by the lease duration fixed in
    ``provision_terms.duration_seconds``.
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
        # Translate per-hour bounds → absolute amounts (× duration / 3600).
        # Listings broadcast per-hour rates; once the duration is fixed,
        # the whole negotiation runs on absolute totals.
        if duration_seconds is None or duration_seconds <= 0:
            raise RuntimeError(
                "provision_terms.duration_seconds must be > 0 to translate "
                "per-hour bounds into absolute amounts."
            )

    core_outcome = _core_negotiate_with_seller(
        seller_url=seller_url,
        principal=principal,
        signer=signer,
        listing_id=listing_id,
        initial_price=initial_price,
        max_price=max_price,
        unit_count=(
            float(duration_seconds) / 3600.0 if duration_seconds is not None else None
        ),
        provision_terms=provision_terms,
        encode_escrow_proposal=encode_escrow_proposal,
        escrow_proposal=escrow_proposal,
        decode_provision_terms=lambda value: _validate_model(VmProvisionTerms, value),
        decode_escrow_proposal=lambda value: _validate_model(EscrowProposal, value),
        decode_escrow_terms=lambda value: _validate_model(EscrowTerms, value),
        settlement_selection=settlement_selection,
        max_rounds=max_rounds,
        on_round=on_round,
        chain=chain,
        resume=resume,
        policy_params=policy_params,
        validate_advertised_plan=validate_advertised_plan,
        resolve_seller_principals=resolve_seller_principals,
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
    if core_outcome.accepted_escrow_terms is not None:
        values["accepted_escrow_terms"] = [
            _validate_model(EscrowTerms, term)
            for term in core_outcome.accepted_escrow_terms
        ]
    return NegotiationOutcome(**values, duration_seconds=duration_seconds)
