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
  interruptible oracle, else the seller wallet) declares the refund split if
  the deal is interrupted.

A domain delivers only some of these models; an interruptible deal, for
instance, presumes a listing that can be preempted. Each domain's Alkahest
seller entry therefore declares the models it delivers, and its composition
refuses a configured model outside them with
:func:`require_deliverable_release_model`.
"""

from __future__ import annotations

from collections.abc import Collection, Iterable, Mapping
from typing import Any

from market_settlement_runtime import SettlementPublicationClause

from .alkahest import (
    get_erc20_splitter,
    get_recipient_arbiter,
    get_trusted_oracle_arbiter,
)
from .settlement_config import (
    ALKAHEST_MECHANISM_ID,
    AlkahestPublicationInput,
    AlkahestSettlementConfig,
)

RECIPIENT_RELEASE = "recipient"
ORACLE_GATED_RELEASE = "oracle_gated"
INTERRUPTIBLE_RELEASE = "interruptible"
RELEASE_MODELS: frozenset[str] = frozenset(
    {RECIPIENT_RELEASE, ORACLE_GATED_RELEASE, INTERRUPTIBLE_RELEASE}
)


class ReleaseModelError(ValueError):
    """The configured release model is contradictory or cannot be delivered."""


def configured_release_model(config: AlkahestSettlementConfig | None) -> str:
    """The release model ``config`` selects; no section selects ``recipient``.

    Raises ``ReleaseModelError`` when the section selects both the oracle-gated
    and the interruptible model, since an escrow has one arbiter.
    """
    if config is None:
        return RECIPIENT_RELEASE
    if config.oracle_gated and config.interruptible:
        raise ReleaseModelError(
            "Settlement.alkahest oracle and interruptible policies are mutually "
            "exclusive"
        )
    if config.oracle_gated:
        return ORACLE_GATED_RELEASE
    if config.interruptible:
        return INTERRUPTIBLE_RELEASE
    return RECIPIENT_RELEASE


def require_deliverable_release_model(
    config: AlkahestSettlementConfig | None,
    deliverable: Collection[str],
) -> str:
    """Return the configured release model, refusing one the domain cannot deliver.

    ``deliverable`` is the set a domain's Alkahest seller entry declares. The
    refusal names the configured model, so a storefront that composes this
    check at startup reports which setting it cannot honour.
    """
    unknown = set(deliverable) - RELEASE_MODELS
    if unknown:
        raise ValueError(f"unknown Alkahest release models {sorted(unknown)}")
    model = configured_release_model(config)
    if model not in deliverable:
        raise ReleaseModelError(
            f"Settlement.alkahest configures the {model!r} release model, which "
            "this storefront's domain cannot deliver (it delivers "
            f"{', '.join(repr(name) for name in sorted(deliverable)) or 'none'})"
        )
    return model


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

    Raises ``ValueError`` for a chain ``chains`` does not configure, an
    oracle-gated model with no trusted oracle or whose oracle is the seller
    wallet (the party collecting cannot also decide collection), and
    ``ReleaseModelError`` for a contradictory model.
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
        if oracle.lower() == wallet:
            raise ValueError(
                "Settlement.alkahest trusted oracle equals the storefront wallet"
            )
        arbiter_for = get_trusted_oracle_arbiter
        demand_data = {"oracle": oracle.lower(), "data": "0x"}
    elif model == INTERRUPTIBLE_RELEASE:
        oracle = (_first(config.interruptible_oracle_addresses) if config else "") or wallet
        arbiter_for = get_erc20_splitter
        demand_data = {"oracle": oracle.lower(), "data": "0x"}
    else:
        arbiter_for = get_recipient_arbiter
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
    chains: Mapping[str, Any],
    wallet_address: str,
) -> list[dict[str, Any]]:
    """The release conditions for every chain the Alkahest clauses publish on.

    Clauses of other mechanisms advertise no release condition and are
    skipped; a listing publishing no Alkahest clause advertises none.
    """
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
    "require_deliverable_release_model",
]
