"""API-credit composition over core's mechanism-opaque negotiation client."""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass
from typing import Any

from core_buyer.negotiation_client import (
    ResumeState,  # noqa: F401 — domain CLI compatibility export
    NegotiationOutcome as CoreNegotiationOutcome,
    load_buyer_chain as _core_load_buyer_chain,
    negotiate_with_seller as _core_negotiate_with_seller,
)
from domains.apicredits.negotiation import ApiCreditsProvisionTerms
from market_alkahest.schemas import EscrowProposal, EscrowTerms
from .escrow_client import encode_escrow_proposal


def _validate_model(model_type, value):
    """Decode wire dictionaries while tolerating an already-decoded model."""
    if isinstance(value, model_type):
        return value
    if hasattr(value, "model_dump"):
        value = value.model_dump()
    return model_type.model_validate(value)


def load_buyer_chain(**kwargs):
    """Load negotiation middleware with API-credit-owned chain config."""
    from .common import buyer_chains

    kwargs.setdefault(
        "chain_config_paths",
        lambda: {
            name: chain.alkahest_address_config_path
            for name, chain in buyer_chains().items()
        },
    )
    return _core_load_buyer_chain(**kwargs)


@dataclass
class NegotiationOutcome(CoreNegotiationOutcome):
    """Core outcome with API-credit Alkahest payloads decoded in-domain."""

    accepted_provision_terms: ApiCreditsProvisionTerms | None = None
    accepted_escrow_proposal: EscrowProposal | None = None
    accepted_escrow_terms: list[EscrowTerms] | None = None

    def to_dict(self) -> dict[str, Any]:
        payload = super().to_dict()
        if self.accepted_provision_terms is not None:
            payload["accepted_provision_terms"] = (
                self.accepted_provision_terms.model_dump()
            )
        if self.accepted_escrow_proposal is not None:
            payload["accepted_escrow_proposal"] = (
                self.accepted_escrow_proposal.model_dump()
            )
        if self.accepted_escrow_terms is not None:
            payload["accepted_escrow_terms"] = [
                term.model_dump() for term in self.accepted_escrow_terms
            ]
        return payload


def negotiate_with_seller(**kwargs) -> NegotiationOutcome:
    """Negotiate through core, then decode accepted Alkahest payloads."""
    kwargs.setdefault("encode_escrow_proposal", encode_escrow_proposal)
    kwargs.setdefault(
        "decode_provision_terms",
        lambda value: _validate_model(ApiCreditsProvisionTerms, value),
    )
    kwargs.setdefault(
        "decode_escrow_proposal",
        lambda value: _validate_model(EscrowProposal, value),
    )
    kwargs.setdefault(
        "decode_escrow_terms",
        lambda value: _validate_model(EscrowTerms, value),
    )
    core_outcome = _core_negotiate_with_seller(**kwargs)
    values = {
        field.name: getattr(core_outcome, field.name)
        for field in dataclasses.fields(CoreNegotiationOutcome)
    }
    if core_outcome.accepted_provision_terms is not None:
        values["accepted_provision_terms"] = _validate_model(
            ApiCreditsProvisionTerms, core_outcome.accepted_provision_terms
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
    return NegotiationOutcome(**values)
