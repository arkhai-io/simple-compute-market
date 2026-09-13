"""Buyer-side Alkahest selection for the bare-metal domain.

The seller publishes Alkahest and hosted alternatives from one registry, so the
rail is decided by the option the buyer selected. This module owns only what the
shared surfaces do not: building the buyer's escrow proposal from the advertised
entry, and checking the part of an accepted plan that
``core_buyer.negotiation_client`` delegates.

`_validate_settlement_acceptance` checks principals, single obligation,
payer/claimant roles, mechanism, amount, expiry and asset; a caller that supplies
`validate_advertised_plan` *replaces* its final `obligation.params` and
`obligation.conditions` equality checks. An Alkahest obligation's params are
materialized from the proposal and never equal the advertised option's params, so
the callback is required, and it must cover exactly what it displaced without
restating what the shared code still enforces.

The physical terms (SSH key, host, duration) are not checked here either:
`_validate_accepted_provision_terms` in the same shared client refuses a reply
whose `accepted_provision_terms` differ from what the buyer requested.

See openspec/specs/settlement-configuration/spec.md#requirement-mechanism-owned-typed-registration.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from market_alkahest import ALKAHEST_MECHANISM_ID
from market_alkahest.proposals import escrow_proposal_from_accepted_entry
from market_alkahest.plans import validate_accepted_alkahest_obligation
from market_alkahest.schemas import EscrowProposal
from market_core.schemas import SettlementOption, SettlementPlan

HOSTED_MECHANISM = "fiat.stripe.v1"
ALKAHEST_MECHANISM = ALKAHEST_MECHANISM_ID


class BareMetalBuyerMechanismError(ValueError):
    """A selected settlement option cannot be driven as the rail it names."""


def alkahest_accepted_escrow(
    option: SettlementOption | Mapping[str, Any],
) -> dict[str, Any]:
    """Return the escrow entry an Alkahest option advertises.

    `alkahest_option_builder` derives the option identity from this payload, so
    it is the seller's own advertised terms. It carries no expiry: an
    `AcceptedEscrow` is `chain_name`, `escrow_address`, `literal_fields` and
    `rates` only. The expiry is the buyer's, supplied to the proposal below.
    """
    decoded = SettlementOption.model_validate(option)
    if decoded.mechanism != ALKAHEST_MECHANISM:
        raise BareMetalBuyerMechanismError("option does not select Alkahest")
    escrow = (decoded.params or {}).get("accepted_escrow")
    if not isinstance(escrow, Mapping) or not escrow:
        raise BareMetalBuyerMechanismError(
            "Alkahest option advertises no accepted escrow"
        )
    return dict(escrow)


def bare_metal_escrow_proposal(
    *,
    listing: Mapping[str, Any],
    option: SettlementOption | Mapping[str, Any],
    expiration_unix: int,
) -> EscrowProposal:
    """The buyer's round-0 proposal for an advertised Alkahest option.

    The shared builder resolves the token literal and selects the demand whose
    chain matches the entry, so a listing advertising several chains cannot have
    one chain's arbiter attached to another chain's escrow.
    """
    if expiration_unix <= 0:
        raise BareMetalBuyerMechanismError("escrow expiry must be a positive instant")
    return escrow_proposal_from_accepted_entry(
        listing=dict(listing),
        entry=alkahest_accepted_escrow(option),
        expiration_unix=expiration_unix,
    )


def validate_accepted_alkahest_plan(
    *,
    plan: SettlementPlan | Mapping[str, Any],
    proposal: EscrowProposal,
    duration_seconds: int,
    address_config_path: str | None = None,
    seller_payout_address: str | None = None,
) -> None:
    """Re-derive the whole obligation and require the accepted one to equal it.

    Field-by-field comparison is not sufficient. `materialize_escrow_terms_from_proposal`
    encodes the arbiter and the payee *inside* `params.obligation_data`, so an
    accepted plan can carry a correct top-level amount, asset and `conditions`
    list while its nested `amount`, `arbiter` or `demand` name different terms —
    and the buyer funds `obligation_data` verbatim. Deriving the expected
    obligation with the shared codec and comparing the whole thing closes that
    class of substitution rather than the instances someone enumerated.

    The payout address is the seller's own choice and cannot be derived from the
    buyer's proposal, so it is taken from the accepted plan unless the caller
    pins one. Everything downstream of it — the encoded demand, the arbiter, the
    obligation data, the escrow contract — is then required to be exactly what
    that address implies.

    The amount re-derived from is the accepted obligation's own total, which is
    the negotiated absolute amount: `core_buyer._validate_settlement_acceptance`
    requires it to equal the negotiated total before delegating here. The
    advertised rate is per hour and is not that total for any rental that is not
    exactly one hour. Taking it from the plan is not trusting the plan — the
    nested `obligation_data["amount"]` is then required to equal it.

    Principals, top-level amount, asset, expiry and mechanism are already
    enforced by that same validator and are deliberately not repeated.
    """
    accepted = SettlementPlan.model_validate(plan)
    try:
        validate_accepted_alkahest_obligation(
            obligation=accepted.obligations[0],
            proposal=proposal,
            duration_seconds=duration_seconds,
            address_config_path=address_config_path,
            seller_payout_address=seller_payout_address,
        )
    except Exception as exc:
        raise BareMetalBuyerMechanismError(
            "accepted obligation could not be re-derived from the buyer proposal"
        ) from exc


__all__ = [
    "ALKAHEST_MECHANISM",
    "HOSTED_MECHANISM",
    "BareMetalBuyerMechanismError",
    "alkahest_accepted_escrow",
    "bare_metal_escrow_proposal",
    "validate_accepted_alkahest_plan",
]
