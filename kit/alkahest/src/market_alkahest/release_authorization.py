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

    An escrow proposal states the contract its escrow is to be funded at, so a
    proposal naming none (no address, or the zero address) states no escrow to
    settle and is refused, whatever release condition it selects. It is a
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


class EscrowNotAcceptedError(ReleaseConditionError):
    """An escrow proposal names an escrow its listing does not accept.

    A listing's ``accepted_escrows`` state the contracts it settles through and
    the literal fields, such as an ERC-20 escrow's token, each one fixes. A
    seller policy decides whether and at what price to deal within what the
    listing offers; what can settle is the listing's, so a plan is never
    materialized for a contract the listing does not accept, or with a literal
    field other than its entry's, whatever policies ran. It is a
    ``ReleaseConditionError`` so every caller translating that family refuses it
    the same way. The message starts with ``escrow_not_in_accepted_set`` or
    ``escrow_field_mismatch``.
    """


def _listing_value(listing: Any, key: str) -> Any:
    if isinstance(listing, Mapping):
        return listing.get(key)
    return getattr(listing, key, None)


def _proposal_value(proposal: Any, key: str) -> Any:
    if isinstance(proposal, Mapping):
        return proposal.get(key)
    return getattr(proposal, key, None)


def _accepted_entries(listing: Any) -> list[Mapping[str, Any]]:
    raw = _listing_value(listing, "accepted_escrows")
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except ValueError:
            return []
    if not isinstance(raw, (list, tuple)):
        return []
    entries = [
        item.model_dump(mode="json") if hasattr(item, "model_dump") else item
        for item in raw
    ]
    return [entry for entry in entries if isinstance(entry, Mapping)]


def _literal_comparable(value: Any) -> Any:
    if isinstance(value, str) and value.strip()[:2].lower() == "0x":
        return value.strip().lower()
    return value


def require_accepted_escrow(
    proposal: EscrowProposal | Mapping[str, Any] | Any, *, listing: Any
) -> None:
    """Refuse ``proposal`` unless ``listing`` accepts its escrow as proposed.

    The proposal's chain and escrow contract must be one of the listing's
    ``accepted_escrows`` (a list or its stored JSON text; absent or unreadable
    accepts none), and every literal field that entry fixes must equal the
    proposal's, addresses compared case-insensitively. Raises
    ``EscrowNotAcceptedError``.
    """
    chain = _proposal_value(proposal, "chain_name")
    address = _proposal_value(proposal, "escrow_address")
    target = address.lower() if isinstance(address, str) else ""
    matched = next(
        (
            entry
            for entry in _accepted_entries(listing)
            if entry.get("chain_name") == chain
            and isinstance(entry.get("escrow_address"), str)
            and entry["escrow_address"].lower() == target
        ),
        None,
    )
    if matched is None:
        raise EscrowNotAcceptedError(
            f"escrow_not_in_accepted_set: (chain={chain!r}, address={address!r}) "
            "is not one of the listing's accepted escrows"
        )
    required = matched.get("literal_fields") or {}
    offered = _proposal_value(proposal, "literal_fields") or {}
    if not isinstance(required, Mapping):
        return
    for key, value in required.items():
        if _literal_comparable(offered.get(key)) != _literal_comparable(value):
            raise EscrowNotAcceptedError(
                f"escrow_field_mismatch: field {key!r} - proposed "
                f"{offered.get(key)!r}, the listing's accepted escrow requires {value!r}"
            )


def advertised_release_conditions(listing: Any) -> list[Any]:
    """Every release condition ``listing`` advertises, as a buyer records them.

    ``demands`` as a list or as its stored JSON text, each condition in its wire
    form. An absent or unreadable value advertises none, so a record of it
    authorizes nothing when ``authorized_release_conditions`` reads it back.
    """
    raw = _listing_value(listing, "demands")
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except ValueError:
            return []
    if not isinstance(raw, (list, tuple)):
        return []
    return [
        item.model_dump(mode="json") if hasattr(item, "model_dump") else item
        for item in raw
    ]


_RELEASE_CONDITIONS = "release_conditions"


def release_conditions_record(listing: Any) -> dict[str, Any]:
    """What a buyer records about ``listing`` to derive its escrow on resume.

    The listing's advertised release conditions, under the one key
    ``recorded_release_conditions`` reads back; the buyer's run carries the
    record opaquely.
    """
    return {_RELEASE_CONDITIONS: advertised_release_conditions(listing)}


def recorded_release_conditions(record: Mapping[str, Any] | None) -> list[Any] | None:
    """The release conditions ``record`` holds, or None when it holds none.

    ``record`` is what ``release_conditions_record`` wrote. None, or a record
    without the conditions, is a run that recorded none. A record that is not an
    object, or conditions that are not a list, raise ``ValueError`` naming
    ``release_conditions_unreadable``.
    """
    if record is None:
        return None
    if not isinstance(record, Mapping):
        raise ValueError(
            "release_conditions_unreadable: the recorded listing record is not an object"
        )
    raw = record.get(_RELEASE_CONDITIONS)
    if raw is None:
        return None
    if not isinstance(raw, list):
        raise ValueError(
            "release_conditions_unreadable: the recorded release conditions are not a list"
        )
    return list(raw)


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
