"""Shared run-log recovery helpers for buyer deal commands.

The core records and recovers settlement proposal and term payloads as
mechanism-opaque dictionaries. Domain composition is responsible for
decoding those payloads and deriving mechanism-specific enrichments.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import typer
from market_identity import Identity, Signer, TrustedIdentitySet

from .run_log import RunLog, read_run


@dataclass
class DealContext:
    """What we need to drive stages 3-5 of a deal post-negotiation."""

    buyer_principal: Identity
    publisher_principals: TrustedIdentitySet
    publisher_id: str
    source_registry_url: str
    source_registry_authority: str
    seller_url: str
    listing_id: str
    negotiation_id: str
    agreed_amount: float
    escrow_uid: str | None = None
    settlement_ref: str | None = None
    # Buyer's lease ask, in seconds. Captured at /negotiate/new time and
    # echoed by the seller in the agreement; settlement multiplies the
    # per-hour price by duration_seconds/3600 to compute total payment.
    duration_seconds: int = 3600
    # Settlement-time enrichments captured by `market negotiate` when
    # available. None means the field wasn't logged — caller falls
    # back to flags / config.toml defaults / a fresh HTTP lookup.
    seller_wallet_address: str | None = None
    token_contract: str | None = None
    token_decimals: float | None = None
    accepted_escrow_proposal: dict[str, Any] | None = None
    # Canonical mechanism-neutral settlement carrier plus the optional
    # legacy flat term payload recorded on older wire exchanges.
    settlement_plan: dict[str, Any] | None = None
    accepted_escrow_terms: list[dict[str, Any]] | None = None
    accepted_provision_terms: dict[str, Any] | None = None
    settlement_selection: dict[str, Any] | None = None
    settlement_operation_identities: tuple[str, ...] = ()


def accepted_settlement_mechanism(deal: DealContext) -> str:
    """Return the mechanism pinned by accepted Terms, never current config."""

    selected: str | None = None
    if deal.settlement_selection is not None:
        value = deal.settlement_selection.get("mechanism")
        if not isinstance(value, str) or not value:
            raise ValueError("accepted settlement selection has no mechanism")
        selected = value

    planned: set[str] = set()
    if deal.settlement_plan is not None:
        obligations = deal.settlement_plan.get("obligations")
        if not isinstance(obligations, list) or not obligations:
            raise ValueError("accepted settlement plan has no obligations")
        for obligation in obligations:
            if not isinstance(obligation, dict):
                raise ValueError("accepted settlement plan has a malformed obligation")
            mechanism = obligation.get("mechanism")
            if not isinstance(mechanism, str) or not mechanism:
                raise ValueError("accepted settlement obligation has no mechanism")
            planned.add(mechanism)
        if selected is None and len(planned) != 1:
            raise ValueError(
                "accepted settlement plan spans multiple mechanisms without a selection"
            )

    if selected is not None and planned and selected not in planned:
        raise ValueError(
            "accepted settlement selection conflicts with the settlement plan"
        )
    mechanism = selected or next(iter(planned), None)
    if mechanism is None:
        raise ValueError("run-log has no accepted settlement mechanism")
    return mechanism


def settlement_acceptance_fields(
    *,
    negotiation_id: str,
    selection: Any | None,
    plan: Any | None,
) -> dict[str, Any]:
    """Serialize public accepted selection and stable obligation identities."""

    from market_core.schemas import SettlementPlan, SettlementSelection
    from market_settlement_runtime import derive_obligation_ref

    decoded_selection = (
        SettlementSelection.model_validate(selection) if selection is not None else None
    )
    decoded_plan = SettlementPlan.model_validate(plan) if plan is not None else None
    if decoded_plan is None:
        return {
            "settlement_selection": (
                decoded_selection.model_dump(mode="json")
                if decoded_selection is not None
                else None
            ),
            "settlement_plan": None,
            "settlement_operation_identities": [],
        }

    mechanisms = {obligation.mechanism for obligation in decoded_plan.obligations}
    if (
        decoded_selection is not None
        and decoded_selection.mechanism not in mechanisms
    ):
        raise ValueError(
            "accepted settlement selection conflicts with the settlement plan"
        )
    if not negotiation_id:
        raise ValueError("accepted settlement plan has no negotiation identity")
    identities = [
        derive_obligation_ref(
            negotiation_id,
            index,
            obligation.model_dump(mode="json"),
        )
        for index, obligation in enumerate(decoded_plan.obligations)
    ]
    return {
        "settlement_selection": (
            decoded_selection.model_dump(mode="json")
            if decoded_selection is not None
            else None
        ),
        "settlement_plan": decoded_plan.model_dump(mode="json"),
        "settlement_operation_identities": identities,
    }


def _parse_publisher_trust(value: Any) -> TrustedIdentitySet:
    if isinstance(value, TrustedIdentitySet):
        return value
    if not isinstance(value, dict) or set(value) != {"identities"}:
        raise ValueError("publisher_principals must contain identities")
    identities = value["identities"]
    if not isinstance(identities, (list, tuple)):
        raise ValueError("publisher_principals identities must be an array")
    return TrustedIdentitySet(
        identities=tuple(Identity.model_validate(item) for item in identities)
    )


def _refresh_publisher_trust(
    run_id: str,
    *,
    signer: Signer,
    listing_id: str,
    recorded: TrustedIdentitySet,
    refresh: Callable[[str, str, str, str], TrustedIdentitySet],
    publisher_id: str,
    source_registry_url: str,
    source_registry_authority: str,
) -> TrustedIdentitySet:
    current = refresh(
        listing_id,
        publisher_id,
        source_registry_url,
        source_registry_authority,
    )
    if not isinstance(current, TrustedIdentitySet):
        raise typer.BadParameter(
            "Signed listing refresh did not return publisher_principals"
        )
    if current != recorded:
        RunLog.open(run_id, signer=signer).event(
            "publisher_trust_refreshed",
            listing_id=listing_id,
            publisher_id=publisher_id,
            publisher_principals=current.model_dump(mode="json"),
            source_registry_url=source_registry_url,
            source_registry_authority=source_registry_authority,
        )
    return current


def load_deal_context(
    run_id: str,
    *,
    signer: Signer,
    refresh_publisher_principals: Callable[[str, str, str, str], TrustedIdentitySet],
) -> DealContext:
    """Read a buyer run-log and extract signer-bound deal context.

    Tolerates either a `market negotiate` log (one negotiation,
    fields at the run_started/run_ended boundary) or a `market buy`
    log (potentially multiple negotiation attempts; uses the most
    recent agreed one). Picks up any `escrow_created` event already
    present so callers can short-circuit stage 3.
    """
    events = read_run(run_id, signer=signer)
    if not events:
        raise typer.BadParameter(
            f"No run-log found for run_id={run_id!r}. Check `market logs runs`."
        )
    buyer_principal = Identity.model_validate(events[0]["buyer_principal"])
    publisher_principals: TrustedIdentitySet | None = None
    publisher_id: str | None = None
    source_registry_url: str | None = None
    source_registry_authority: str | None = None

    seller_url: str | None = None
    listing_id: str | None = None
    negotiation_id: str | None = None
    agreed_amount: float | None = None
    escrow_uid: str | None = None
    settlement_ref: str | None = None
    duration_seconds: int = 3600
    seller_wallet_address: str | None = None
    token_contract: str | None = None
    token_decimals: float | None = None
    accepted_escrow_proposal: dict[str, Any] | None = None
    settlement_plan: dict[str, Any] | None = None
    accepted_escrow_terms: list[dict[str, Any]] | None = None
    accepted_provision_terms: dict[str, Any] | None = None
    settlement_selection: dict[str, Any] | None = None
    settlement_operation_identities: tuple[str, ...] = ()
    last_status: str | None = None

    def _capture_accepted_terms(ev: dict[str, Any]) -> None:
        nonlocal accepted_escrow_proposal, settlement_plan, accepted_escrow_terms
        nonlocal accepted_provision_terms, settlement_selection
        nonlocal settlement_operation_identities
        nonlocal seller_wallet_address, token_contract
        raw_plan = ev.get("settlement_plan")
        if isinstance(raw_plan, dict):
            settlement_plan = raw_plan
        raw_selection = ev.get("settlement_selection")
        if isinstance(raw_selection, dict):
            if (
                settlement_selection is not None
                and settlement_selection != raw_selection
            ):
                raise typer.BadParameter(
                    f"Run-log {run_id!r} has conflicting accepted settlement selections."
                )
            settlement_selection = raw_selection
        raw_identities = ev.get("settlement_operation_identities")
        if isinstance(raw_identities, list) and all(
            isinstance(item, str) and item for item in raw_identities
        ):
            identities = tuple(raw_identities)
            if (
                settlement_operation_identities
                and settlement_operation_identities != identities
            ):
                raise typer.BadParameter(
                    f"Run-log {run_id!r} has conflicting settlement operation identities."
                )
            settlement_operation_identities = identities
        raw_terms = ev.get("accepted_escrow_terms")
        if isinstance(raw_terms, list):
            accepted_escrow_terms = [
                item for item in raw_terms if isinstance(item, dict)
            ]
        raw_proposal = ev.get("accepted_escrow_proposal")
        if isinstance(raw_proposal, dict):
            accepted_escrow_proposal = raw_proposal
        raw_provision = ev.get("accepted_provision_terms")
        if isinstance(raw_provision, dict):
            accepted_provision_terms = raw_provision

    def _capture_publisher_principals(ev: dict[str, Any]) -> None:
        nonlocal publisher_principals
        raw = ev.get("publisher_principals")
        if raw is None:
            return
        try:
            candidate = _parse_publisher_trust(raw)
        except (TypeError, ValueError) as exc:
            raise typer.BadParameter(
                f"Run-log {run_id!r} has malformed publisher_principals."
            ) from exc
        if publisher_principals is not None and candidate != publisher_principals:
            raise typer.BadParameter(
                f"Run-log {run_id!r} has conflicting selected publisher principals."
            )
        publisher_principals = candidate

    def _capture_publisher_binding(ev: dict[str, Any]) -> None:
        nonlocal publisher_id, source_registry_url, source_registry_authority
        values = (
            ("publisher_id", ev.get("publisher_id")),
            ("source_registry_url", ev.get("source_registry_url")),
            ("source_registry_authority", ev.get("source_registry_authority")),
        )
        for name, value in values:
            if value is None:
                continue
            normalized = (
                str(value).rstrip("/") if name == "source_registry_url" else str(value)
            )
            existing = {
                "publisher_id": publisher_id,
                "source_registry_url": source_registry_url,
                "source_registry_authority": source_registry_authority,
            }[name]
            if existing is not None and existing != normalized:
                raise typer.BadParameter(f"Run-log {run_id!r} has conflicting {name}.")
            if name == "publisher_id":
                publisher_id = normalized
            elif name == "source_registry_url":
                source_registry_url = normalized
            else:
                source_registry_authority = normalized

    for ev in events:
        ev_type = ev.get("event")
        _capture_publisher_binding(ev)
        if ev_type == "publisher_trust_refreshed":
            try:
                publisher_principals = _parse_publisher_trust(
                    ev.get("publisher_principals")
                )
            except (TypeError, ValueError) as exc:
                raise typer.BadParameter(
                    f"Run-log {run_id!r} has malformed refreshed publisher trust."
                ) from exc

        # `negotiate` end carries the agreed_amount + negotiation_id.
        if ev_type == "run_ended":
            _capture_publisher_principals(ev)
            last_status = ev.get("status")
            _capture_accepted_terms(ev)
            if ev.get("agreed_amount") is not None:
                agreed_amount = float(ev["agreed_amount"])
            if ev.get("negotiation_id"):
                negotiation_id = str(ev["negotiation_id"])

        # `market buy`-style log.
        if ev_type == "negotiation_completed" and ev.get("status") == "agreed":
            _capture_publisher_principals(ev)
            _capture_accepted_terms(ev)
            seller_url = ev.get("seller_url") or seller_url
            if ev.get("agreed_amount") is not None:
                agreed_amount = float(ev["agreed_amount"])
            if ev.get("negotiation_id"):
                negotiation_id = str(ev["negotiation_id"])
            if ev.get("listing_id"):
                listing_id = str(ev["listing_id"])
        if ev_type == "escrow_created":
            uid = ev.get("escrow_uid")
            if isinstance(uid, str) and uid:
                escrow_uid = uid
        if ev_type == "settlement_started":
            ref = ev.get("settlement_ref")
            if isinstance(ref, str) and ref:
                settlement_ref = ref
        if ev_type == "escrow_create_start":
            terms = ev.get("terms", {})
            if isinstance(terms, dict):
                if terms.get("seller_url"):
                    seller_url = terms["seller_url"]
                if terms.get("listing_id"):
                    listing_id = terms["listing_id"]
                if terms.get("duration_seconds"):
                    duration_seconds = int(terms["duration_seconds"])

        # `negotiate`-style log start carries seller_url + listing id.
        if ev_type == "run_started":
            _capture_publisher_principals(ev)
            if ev.get("seller_url"):
                seller_url = ev["seller_url"]
            if ev.get("listing_id"):
                listing_id = ev["listing_id"]
            if ev.get("duration_seconds"):
                duration_seconds = int(ev["duration_seconds"])
            if ev.get("seller_wallet_address"):
                seller_wallet_address = str(ev["seller_wallet_address"])
            if ev.get("token_contract"):
                token_contract = str(ev["token_contract"])
            if ev.get("token_decimals") is not None:
                try:
                    token_decimals = int(ev["token_decimals"])
                except (TypeError, ValueError):
                    pass

    missing = [
        name
        for name, v in (
            ("publisher_principals", publisher_principals),
            ("publisher_id", publisher_id),
            ("source_registry_url", source_registry_url),
            ("source_registry_authority", source_registry_authority),
            ("seller_url", seller_url),
            ("listing_id", listing_id),
            ("negotiation_id", negotiation_id),
            ("agreed_amount", agreed_amount),
        )
        if not v
    ]
    if missing:
        raise typer.BadParameter(
            f"Run-log {run_id!r} is missing fields: {', '.join(missing)}. "
            f"Last status was {last_status!r}. Recovery requires a "
            f"prior `agreed` outcome."
        )
    publisher_principals = _refresh_publisher_trust(
        run_id,
        signer=signer,
        listing_id=listing_id,  # type: ignore[arg-type]
        recorded=publisher_principals,  # type: ignore[arg-type]
        refresh=refresh_publisher_principals,
        publisher_id=publisher_id,  # type: ignore[arg-type]
        source_registry_url=source_registry_url,  # type: ignore[arg-type]
        source_registry_authority=source_registry_authority,  # type: ignore[arg-type]
    )

    # Pre-plan logs carry only the flat opaque terms; the generic carrier
    # can preserve those payloads without decoding their mechanism schema.
    if settlement_plan is None and accepted_escrow_terms:
        from market_core.schemas import SettlementPlan

        settlement_plan = SettlementPlan.model_validate(
            accepted_escrow_terms
        ).model_dump()

    if settlement_plan is not None:
        expected_identities = tuple(
            settlement_acceptance_fields(
                negotiation_id=negotiation_id,  # type: ignore[arg-type]
                selection=settlement_selection,
                plan=settlement_plan,
            )["settlement_operation_identities"]
        )
        if (
            settlement_operation_identities
            and settlement_operation_identities != expected_identities
        ):
            raise typer.BadParameter(
                f"Run-log {run_id!r} has conflicting settlement operation identities."
            )
        settlement_operation_identities = expected_identities

    return DealContext(
        buyer_principal=buyer_principal,
        publisher_principals=publisher_principals,  # type: ignore[arg-type]
        publisher_id=publisher_id,  # type: ignore[arg-type]
        source_registry_url=source_registry_url,  # type: ignore[arg-type]
        source_registry_authority=source_registry_authority,  # type: ignore[arg-type]
        seller_url=seller_url,  # type: ignore[arg-type]
        listing_id=listing_id,  # type: ignore[arg-type]
        negotiation_id=negotiation_id,  # type: ignore[arg-type]
        agreed_amount=agreed_amount,  # type: ignore[arg-type]
        escrow_uid=escrow_uid,
        settlement_ref=settlement_ref,
        duration_seconds=duration_seconds,
        seller_wallet_address=seller_wallet_address,
        token_contract=token_contract,
        token_decimals=token_decimals,
        accepted_escrow_proposal=accepted_escrow_proposal,
        settlement_plan=settlement_plan,
        accepted_escrow_terms=accepted_escrow_terms,
        accepted_provision_terms=accepted_provision_terms,
        settlement_selection=settlement_selection,
        settlement_operation_identities=settlement_operation_identities,
    )


def open_run_log(run_id: str, *, signer: Signer) -> RunLog:
    """Append-only run log for the signer-bound run being recovered."""
    return RunLog.open(run_id, signer=signer)


@dataclass
class NegotiationResumePoint:
    """What ``market negotiate --from`` needs to resume the round loop.

    Pulled from a prior run-log via :func:`load_negotiation_resume_point`.
    Fed into :func:`buyer_client.negotiate_with_seller` as the
    ``resume=`` argument so we skip ``/negotiate/new`` and continue
    against the seller's existing thread.
    """

    seller_url: str
    listing_id: str
    negotiation_id: str
    transcript: list  # list[NegotiationRound] — typed downstream
    buyer_principal: Identity
    publisher_principals: TrustedIdentitySet
    publisher_id: str
    source_registry_url: str
    source_registry_authority: str
    last_seller_proposal: dict | None
    rounds_completed: int
    last_status: str | None
    # Negotiation policy recorded at run start — a resume continues
    # under the policy that opened the negotiation, not whatever the
    # config says today.
    policy: str | None = None


def is_negotiation_complete(run_id: str, *, signer: Signer) -> bool:
    """Return whether the signer-bound log has an agreed negotiation outcome."""

    for ev in read_run(run_id, signer=signer):
        if ev.get("event") == "negotiation_completed" and ev.get("status") == "agreed":
            return True
        if ev.get("event") == "run_ended" and ev.get("status") == "agreed":
            return True
    return False


def load_negotiation_resume_point(
    run_id: str,
    *,
    signer: Signer,
    refresh_publisher_principals: Callable[[str, str, str, str], TrustedIdentitySet],
) -> NegotiationResumePoint:
    """Reconstruct a partial negotiation for the principal owning the log."""
    from market_policy.negotiation_middleware import NegotiationRound

    events = read_run(run_id, signer=signer)
    if not events:
        raise typer.BadParameter(
            f"No run-log found for run_id={run_id!r}. Check `market logs runs`."
        )
    buyer_principal = Identity.model_validate(events[0]["buyer_principal"])
    publisher_principals: TrustedIdentitySet | None = None
    publisher_id: str | None = None
    source_registry_url: str | None = None
    source_registry_authority: str | None = None

    seller_url: str | None = None
    listing_id: str | None = None
    negotiation_id: str | None = None
    transcript: list = []
    last_seller_proposal: dict | None = None
    last_status: str | None = None
    rounds_completed = 0

    policy: str | None = None
    for ev in events:
        for name in (
            "publisher_id",
            "source_registry_url",
            "source_registry_authority",
        ):
            raw_binding = ev.get(name)
            if raw_binding is None:
                continue
            normalized = (
                str(raw_binding).rstrip("/")
                if name == "source_registry_url"
                else str(raw_binding)
            )
            existing = {
                "publisher_id": publisher_id,
                "source_registry_url": source_registry_url,
                "source_registry_authority": source_registry_authority,
            }[name]
            if existing is not None and existing != normalized:
                raise typer.BadParameter(f"Run-log {run_id!r} has conflicting {name}.")
            if name == "publisher_id":
                publisher_id = normalized
            elif name == "source_registry_url":
                source_registry_url = normalized
            else:
                source_registry_authority = normalized
        et = ev.get("event")
        raw_publisher_principals = ev.get("publisher_principals")
        if raw_publisher_principals is not None:
            try:
                candidate = _parse_publisher_trust(raw_publisher_principals)
            except (TypeError, ValueError) as exc:
                raise typer.BadParameter(
                    f"Run-log {run_id!r} has malformed publisher_principals."
                ) from exc
            if et != "publisher_trust_refreshed":
                if (
                    publisher_principals is not None
                    and candidate != publisher_principals
                ):
                    raise typer.BadParameter(
                        f"Run-log {run_id!r} has conflicting publisher principals."
                    )
            publisher_principals = candidate
        if et == "run_started":
            seller_url = ev.get("seller_url") or seller_url
            listing_id = ev.get("listing_id") or listing_id
            policy = ev.get("policy") or policy
        elif et == "run_ended":
            last_status = ev.get("status") or last_status
            if ev.get("negotiation_id"):
                negotiation_id = str(ev["negotiation_id"])
        elif et == "negotiation_round":
            our = ev.get("our_message") or {}
            their = ev.get("their_reply") or {}
            if their.get("negotiation_id"):
                negotiation_id = str(their["negotiation_id"])
            round_idx = int(ev.get("round", rounds_completed))
            rounds_completed = max(rounds_completed, round_idx + 1)
            our_action = our.get("action") or "initial"
            our_proposal = our.get("proposal")
            transcript.append(
                NegotiationRound(
                    round_number=round_idx,
                    sender="us",
                    action=our_action,
                    proposal=our_proposal if isinstance(our_proposal, dict) else None,
                )
            )
            their_action = their.get("action") or "counter"
            their_proposal = their.get("proposal")
            transcript.append(
                NegotiationRound(
                    round_number=round_idx,
                    sender="them",
                    action=their_action,
                    proposal=their_proposal
                    if isinstance(their_proposal, dict)
                    else None,
                )
            )
            if their_action == "counter" and isinstance(their_proposal, dict):
                last_seller_proposal = their_proposal
        elif et == "negotiation_completed":
            last_status = ev.get("status") or last_status
            if ev.get("negotiation_id"):
                negotiation_id = str(ev["negotiation_id"])
            if ev.get("listing_id"):
                listing_id = str(ev["listing_id"])

    missing = [
        n
        for n, v in (
            ("seller_url", seller_url),
            ("publisher_principals", publisher_principals),
            ("publisher_id", publisher_id),
            ("source_registry_url", source_registry_url),
            ("source_registry_authority", source_registry_authority),
            ("listing_id", listing_id),
            ("negotiation_id", negotiation_id),
        )
        if not v
    ]
    if missing:
        raise typer.BadParameter(
            f"Run-log {run_id!r} is missing fields needed to resume: "
            f"{', '.join(missing)}. Last status was {last_status!r}."
        )
    publisher_principals = _refresh_publisher_trust(
        run_id,
        signer=signer,
        listing_id=listing_id,  # type: ignore[arg-type]
        recorded=publisher_principals,  # type: ignore[arg-type]
        refresh=refresh_publisher_principals,
        publisher_id=publisher_id,  # type: ignore[arg-type]
        source_registry_url=source_registry_url,  # type: ignore[arg-type]
        source_registry_authority=source_registry_authority,  # type: ignore[arg-type]
    )

    return NegotiationResumePoint(
        seller_url=seller_url,  # type: ignore[arg-type]
        listing_id=listing_id,  # type: ignore[arg-type]
        negotiation_id=negotiation_id,  # type: ignore[arg-type]
        buyer_principal=buyer_principal,
        publisher_principals=publisher_principals,  # type: ignore[arg-type]
        publisher_id=publisher_id,  # type: ignore[arg-type]
        source_registry_url=source_registry_url,  # type: ignore[arg-type]
        source_registry_authority=source_registry_authority,  # type: ignore[arg-type]
        transcript=transcript,
        last_seller_proposal=last_seller_proposal,
        rounds_completed=rounds_completed,
        last_status=last_status,
        policy=policy,
    )
