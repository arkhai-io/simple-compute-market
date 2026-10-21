"""The Alkahest release conditions a listing authorizes an escrow to settle under.

A listing's ``demands`` are its advertised release conditions, each an arbiter
and its demand data, scoped to one chain by ``chain_name`` or to every chain
without one. An escrow settles under exactly one of them: a condition a
proposal selects must equal one the listing authorizes on the proposal's chain,
a proposal selecting none takes the listing's, and a listing authorizing none,
or stating its conditions in a form that cannot be read, leaves no condition
to settle under at all. Every kit entry point that encodes an obligation's
release condition reads it through here, so a caller cannot reach an encoded
condition its listing does not authorize.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

from market_alkahest.schemas import EscrowDemand, EscrowProposal, accepted_demands


class ReleaseConditionError(ValueError):
    """An escrow cannot be settled under the release condition it was offered.

    The condition is an arbiter and its demand data. An obligation is
    materialized only under one its listing authorizes for the chain, so a
    selection the listing does not authorize, a listing authorizing none, and a
    condition that cannot be read or encoded all refuse before anything is
    accepted. The message starts with a ``release_condition_*`` reason, or with
    ``escrow_contract_unpinned`` for the subclass below.
    """


class UnpinnedEscrowError(ReleaseConditionError):
    """An escrow proposal names no escrow contract to fund.

    An escrow is funded, priced, and verified at the contract its proposal names,
    so a proposal naming none (no address, or the zero address) has nothing to
    settle at and is refused, whatever release condition it selects. It is a
    ``ReleaseConditionError`` so every caller translating that family refuses it
    the same way. The message starts with ``escrow_contract_unpinned``.
    """


def require_pinned_escrow(proposal: EscrowProposal | Mapping[str, Any] | Any) -> None:
    """Refuse ``proposal`` when it names no escrow contract.

    Raises ``UnpinnedEscrowError`` for a missing or empty escrow address and for
    the zero address.
    """
    address = (
        proposal.get("escrow_address")
        if isinstance(proposal, Mapping)
        else getattr(proposal, "escrow_address", None)
    )
    digits = address.lower().removeprefix("0x") if isinstance(address, str) else ""
    if not digits or set(digits) <= {"0"}:
        chain = (
            proposal.get("chain_name")
            if isinstance(proposal, Mapping)
            else getattr(proposal, "chain_name", None)
        )
        raise UnpinnedEscrowError(
            "escrow_contract_unpinned: the escrow proposal names no escrow contract "
            f"on chain {chain!r}"
        )


def _listing_value(listing: Any, key: str) -> Any:
    if isinstance(listing, Mapping):
        return listing.get(key)
    return getattr(listing, key, None)


def _comparable(value: Any) -> Any:
    """A condition's value with address and byte hex compared case-insensitively."""
    if isinstance(value, Mapping):
        return {str(key): _comparable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_comparable(item) for item in value]
    if isinstance(value, str) and value[:2].lower() == "0x":
        return value.lower()
    return value


def authorized_release_conditions(
    listing: Any, *, chain_name: str
) -> list[EscrowDemand]:
    """The release conditions ``listing`` authorizes on ``chain_name``, in order.

    ``listing`` is a mapping or model carrying ``demands``, as a list or as its
    stored JSON text. Raises ``ReleaseConditionError`` when the listing
    authorizes none on the chain, or states its conditions in a form that
    cannot be read: either way there is no condition to settle under.
    """
    raw = _listing_value(listing, "demands")
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except ValueError as exc:
            raise ReleaseConditionError(
                "release_condition_unreadable: the listing's demands are not JSON"
            ) from exc
    if raw is None:
        raw = []
    if not isinstance(raw, (list, tuple)):
        raise ReleaseConditionError(
            "release_condition_unreadable: the listing's demands are not a list"
        )
    authorized: list[EscrowDemand] = []
    for item in raw:
        if hasattr(item, "model_dump"):
            item = item.model_dump(exclude_none=True)
        if not isinstance(item, Mapping):
            raise ReleaseConditionError(
                "release_condition_unreadable: a listing demand is not an object"
            )
        scope = item.get("chain_name")
        if scope is not None and not isinstance(scope, str):
            raise ReleaseConditionError(
                "release_condition_unreadable: a listing demand's chain_name is "
                "not a string"
            )
        if scope and scope != chain_name:
            continue
        arbiter = item.get("arbiter")
        demand_data = item.get("demand_data")
        if not isinstance(arbiter, str) or not arbiter:
            raise ReleaseConditionError(
                "release_condition_unreadable: a listing demand names no arbiter"
            )
        if not isinstance(demand_data, Mapping):
            raise ReleaseConditionError(
                "release_condition_unreadable: a listing demand's demand_data is "
                "not an object"
            )
        authorized.append(
            EscrowDemand(
                chain_name=scope or None,
                arbiter=arbiter,
                demand_data=dict(demand_data),
            )
        )
    if not authorized:
        raise ReleaseConditionError(
            "release_condition_not_advertised: the listing authorizes no release "
            f"condition on chain {chain_name!r}"
        )
    return authorized


def authorized_release_condition(
    listing: Any,
    *,
    chain_name: str,
    selected: Any = None,
) -> EscrowDemand:
    """The condition an escrow on ``chain_name`` settles under for ``listing``.

    ``selected`` is the condition a proposal names, if any: it must equal one
    the listing authorizes on the chain, arbiter and demand data both, and that
    listing condition is returned. With no selection, the listing's first
    authorized condition on the chain is. Raises ``ReleaseConditionError``.
    """
    authorized = authorized_release_conditions(listing, chain_name=chain_name)
    if selected is None:
        return authorized[0]
    if hasattr(selected, "model_dump"):
        selected = selected.model_dump(exclude_none=True)
    if not isinstance(selected, Mapping):
        raise ReleaseConditionError(
            "release_condition_unreadable: the selected release condition is not "
            "an object"
        )
    wanted = (
        _comparable(selected.get("arbiter")),
        _comparable(selected.get("demand_data")),
    )
    for condition in authorized:
        if (
            _comparable(condition.arbiter),
            _comparable(condition.demand_data),
        ) == wanted:
            return condition
    raise ReleaseConditionError(
        "release_condition_not_authorized: the selected release condition is not "
        f"one the listing authorizes on chain {chain_name!r}"
    )


def selected_release_condition(
    proposal: EscrowProposal | Mapping[str, Any] | Any | None,
) -> Any:
    """The release condition a proposal selects, or None when it selects none.

    Read from its ``demand``, or the deprecated one-element ``demands`` list.
    Raises ``ReleaseConditionError`` for a proposal selecting several.
    """
    if proposal is None:
        return None
    selected = accepted_demands(proposal)
    if len(selected) > 1:
        raise ReleaseConditionError(
            "release_condition_ambiguous: a proposal selects at most one release "
            "condition; listing demands[] remains the allowed-options list"
        )
    return selected[0] if selected else None
