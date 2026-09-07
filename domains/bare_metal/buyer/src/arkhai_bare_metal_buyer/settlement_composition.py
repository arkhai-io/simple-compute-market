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
from market_alkahest.plans import materialize_settlement_plan_from_proposal
from market_alkahest.schemas import EscrowProposal, accepted_recipient_address
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


def _recipient_from_encoded_demand(
    obligation_data: Mapping[str, Any],
    *,
    chain_name: str,
    address_config_path: str | None,
) -> str | None:
    """Decode the payee from an encoded demand using the arbiter's own codec.

    The arbiter address selects the codec, so a demand encoded for a kind that
    binds something other than a recipient is not read as one.
    """
    from alkahest_py import RecipientArbiterDemandData
    from market_alkahest.alkahest import address_to_slot

    arbiter = obligation_data.get("arbiter")
    encoded = obligation_data.get("demand")
    if not isinstance(arbiter, str) or not isinstance(encoded, str):
        return None
    try:
        kind = address_to_slot(chain_name, arbiter, config_path=address_config_path)
    except Exception:
        return None
    if kind != "recipient_arbiter":
        return None
    try:
        decoded = RecipientArbiterDemandData.decode(
            bytes.fromhex(encoded.removeprefix("0x"))
        )
    except Exception:
        return None
    recipient = getattr(decoded, "recipient", None)
    return recipient if isinstance(recipient, str) and recipient else None


def _accepted_payout_address(
    obligation: Any,
    *,
    chain_name: str,
    address_config_path: str | None,
) -> str | None:
    """The address the accepted obligation would pay, wherever the kind puts it.

    Only a candidate: the whole obligation is re-derived from it and compared, so
    a wrong reading fails that comparison rather than being trusted.
    """
    params = obligation.params or {}
    obligation_data = params.get("obligation_data")
    if isinstance(obligation_data, Mapping):
        recipient = accepted_recipient_address(
            {"demand": {"demand_data": dict(obligation_data)}}
        )
        if recipient:
            return recipient
        recipient = _recipient_from_encoded_demand(
            obligation_data,
            chain_name=chain_name,
            address_config_path=address_config_path,
        )
        if recipient:
            return recipient
    for condition in obligation.conditions or []:
        recipient = accepted_recipient_address({"demand": dict(condition)})
        if recipient:
            return recipient
    return None


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
    obligation = accepted.obligations[0]
    params = obligation.params or {}
    if obligation.amount is None:
        raise BareMetalBuyerMechanismError(
            "accepted obligation carries no scalar amount to re-derive from"
        )
    agreed_amount = int(obligation.amount)

    if str(params.get("chain_name") or "") != proposal.chain_name:
        raise BareMetalBuyerMechanismError(
            "accepted obligation settles on a chain the buyer did not propose"
        )
    if str(params.get("escrow_contract") or "").lower() != (
        proposal.escrow_address.lower()
    ):
        raise BareMetalBuyerMechanismError(
            "accepted obligation names an escrow the buyer did not propose"
        )

    derived_payout = _accepted_payout_address(
        obligation,
        chain_name=proposal.chain_name,
        address_config_path=address_config_path,
    )
    payout = seller_payout_address or derived_payout
    if not payout:
        raise BareMetalBuyerMechanismError(
            "accepted obligation names no payout address to verify against"
        )
    if seller_payout_address is not None:
        if (derived_payout or "").lower() != seller_payout_address.lower():
            raise BareMetalBuyerMechanismError(
                "accepted obligation pays an address other than the pinned seller"
            )

    try:
        expected_plan = materialize_settlement_plan_from_proposal(
            proposal=proposal,
            seller_wallet_address=payout,
            agreed_amount=agreed_amount,
            duration_seconds=duration_seconds,
            addr_config_path=address_config_path,
        )
    except Exception as exc:
        raise BareMetalBuyerMechanismError(
            "accepted obligation could not be re-derived from the buyer proposal"
        ) from exc

    expected = expected_plan.obligations[0].model_dump(mode="json")
    actual = obligation.model_dump(mode="json")
    # Compared as whole mappings: the point is to catch a field nobody listed.
    if actual.get("params") != expected.get("params"):
        raise BareMetalBuyerMechanismError(
            "accepted obligation funds escrow data the buyer did not propose"
        )
    if actual.get("conditions") != expected.get("conditions"):
        raise BareMetalBuyerMechanismError(
            "accepted obligation gates collection on conditions the buyer did "
            "not propose"
        )


__all__ = [
    "ALKAHEST_MECHANISM",
    "HOSTED_MECHANISM",
    "BareMetalBuyerMechanismError",
    "alkahest_accepted_escrow",
    "bare_metal_escrow_proposal",
    "validate_accepted_alkahest_plan",
]
