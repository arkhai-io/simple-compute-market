"""The release conditions an Alkahest listing advertises.

A listing that publishes an Alkahest option advertises, for each chain it
publishes on, the condition its escrow is released under: an arbiter and the
demand data that arbiter checks. Those conditions are the listing's ``demands``,
and the buyer's escrow must name one of them.

The condition follows the seller's ``[Settlement.alkahest]`` release model, the
seller wallet, and the chain's address book, and nothing about the market the
listing sells, so every domain that composes Alkahest derives it here:

- ``recipient``, the default: the recipient arbiter, releasing to the seller
  wallet once the seller's fulfillment attestation exists;
- ``oracle_gated``: the trusted-oracle arbiter, releasing when the first
  configured third-party oracle arbitrates in the seller's favour;
- ``interruptible``: the ERC-20 splitter, whose oracle (the first configured
  interruptible oracle) declares the refund split if the deal is interrupted.

A domain delivers only some of these models; an interruptible deal, for
instance, presumes a listing that can be preempted. Each domain's Alkahest
seller entry therefore declares the models it delivers, and a composition passes
them to the Alkahest preflight as ``deliverable_release_models``, which reports a
model outside them as a configuration blocker: an undeliverable model costs the
seller Alkahest, never the storefront. :func:`publication_release_conditions`
derives conditions only while Alkahest is ready.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from market_settlement_runtime import MechanismReadiness, SettlementPublicationClause

from .alkahest import (
    get_erc20_splitter,
    get_recipient_arbiter,
    get_trusted_oracle_arbiter,
)
from .settlement_config import (
    ALKAHEST_MECHANISM_ID,
    INTERRUPTIBLE_RELEASE,
    ORACLE_GATED_RELEASE,
    RECIPIENT_RELEASE,
    RELEASE_MODELS,
    AlkahestPublicationInput,
    AlkahestSettlementConfig,
    ReleaseModelError,
    configured_release_model,
)


def _first(addresses: tuple[str, ...]) -> str:
    return addresses[0] if addresses else ""


def _address_config_path(chain: Any) -> str | None:
    if isinstance(chain, Mapping):
        value = chain.get("alkahest_address_config_path")
    else:
        value = getattr(chain, "alkahest_address_config_path", None)
    return str(value) if value else None


def release_conditions(
    config: AlkahestSettlementConfig | None,
    *,
    chain_names: Iterable[str],
    chains: Mapping[str, Any],
    wallet_address: str,
) -> list[dict[str, Any]]:
    """One release condition per named chain, ordered by chain name.

    ``chains`` maps each configured chain's name to its configuration, a mapping
    or an object, whose ``alkahest_address_config_path`` locates the chain's
    address book (the SDK's own addresses are used where it names none).
    ``wallet_address`` is the seller wallet the escrow pays.

    Raises ``ValueError`` for a chain ``chains`` does not configure, and for an
    oracle-gated or interruptible model with no oracle of its own or whose
    oracle is the seller wallet: the party collecting cannot also decide
    collection, so no condition stands in for a missing oracle. Raises
    ``ReleaseModelError`` for a contradictory model, which startup refuses.
    Alkahest readiness reports each ``ValueError`` case as a blocker, so a caller
    that derives only for a ready mechanism, as
    :func:`publication_release_conditions` does, never meets them.
    """
    names = sorted(set(chain_names))
    if not names:
        return []
    unknown = [name for name in names if name not in chains]
    if unknown:
        raise ValueError(f"settlement clause references unknown chain {unknown[0]!r}")

    model = configured_release_model(config)
    wallet = wallet_address.lower()
    if model == ORACLE_GATED_RELEASE:
        oracle = _first(config.trusted_oracle_addresses) if config else ""
        if not oracle:
            raise ValueError("Settlement.alkahest.oracle_gated requires a trusted oracle")
        arbiter_for = get_trusted_oracle_arbiter
    elif model == INTERRUPTIBLE_RELEASE:
        oracle = _first(config.interruptible_oracle_addresses) if config else ""
        if not oracle:
            raise ValueError(
                "Settlement.alkahest.interruptible requires an interruptible oracle"
            )
        arbiter_for = get_erc20_splitter
    else:
        oracle = ""
        arbiter_for = get_recipient_arbiter
    if oracle:
        if oracle.lower() == wallet:
            raise ValueError(
                "Settlement.alkahest release oracle equals the storefront wallet"
            )
        demand_data: dict[str, str] = {"oracle": oracle.lower(), "data": "0x"}
    else:
        demand_data = {"recipient": wallet}

    return [
        {
            "chain_name": name,
            "arbiter": arbiter_for(
                name, config_path=_address_config_path(chains[name])
            ).lower(),
            "demand_data": dict(demand_data),
        }
        for name in names
    ]


def publication_release_conditions(
    config: AlkahestSettlementConfig | None,
    clauses: Iterable[SettlementPublicationClause],
    *,
    readiness: Iterable[MechanismReadiness],
    chains: Mapping[str, Any],
    wallet_address: str,
) -> list[dict[str, Any]]:
    """The release conditions for every chain the Alkahest clauses publish on.

    ``readiness`` is the readiness the clauses' publication was evaluated
    under. While Alkahest is not ready its clauses publish no option, so they
    advertise no release condition either. Clauses of other mechanisms
    advertise none and are skipped; a listing publishing no Alkahest clause
    advertises none.
    """
    if not any(
        status.mechanism == ALKAHEST_MECHANISM_ID and status.ready
        for status in readiness
    ):
        return []
    chain_names = {
        AlkahestPublicationInput.model_validate(clause.mechanism_input).chain
        for clause in clauses
        if clause.mechanism == ALKAHEST_MECHANISM_ID
    }
    return release_conditions(
        config,
        chain_names=chain_names,
        chains=chains,
        wallet_address=wallet_address,
    )


__all__ = [
    "INTERRUPTIBLE_RELEASE",
    "ORACLE_GATED_RELEASE",
    "RECIPIENT_RELEASE",
    "RELEASE_MODELS",
    "ReleaseModelError",
    "configured_release_model",
    "publication_release_conditions",
    "release_conditions",
]
