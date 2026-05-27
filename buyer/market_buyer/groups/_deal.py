"""Shared helpers for deal-recovery commands (`settle`, `escrow create`).

Both pull deal context (seller_url, agreed_amount, …) from a buyer
run-log JSONL, then feed `buy_orchestrator` stage helpers and
`escrow_client.make_create_escrow_fn` to advance the deal.

Putting this in one place avoids duplicating run-log scraping +
chain-config resolution between the two commands.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional, TYPE_CHECKING

import typer

from ..common import resolve_config_value
from ..run_log import RunLog, read_run

if TYPE_CHECKING:
    from service.config_loader import ChainConfig


@dataclass
class DealContext:
    """What we need to drive stages 3-5 of a deal post-negotiation."""
    seller_url: str
    listing_id: str
    negotiation_id: str
    agreed_amount: float
    escrow_uid: Optional[str] = None
    # Buyer's lease ask, in seconds. Captured at /negotiate/new time and
    # echoed by the seller in the agreement; settlement multiplies the
    # per-hour price by duration_seconds/3600 to compute total payment.
    duration_seconds: int = 3600
    # Settlement-time enrichments captured by `market negotiate` when
    # available. None means the field wasn't logged — caller falls
    # back to flags / config.toml defaults / a fresh HTTP lookup.
    seller_wallet_address: Optional[str] = None
    token_contract: Optional[str] = None
    token_decimals: Optional[float] = None


def load_deal_context(run_id: str) -> DealContext:
    """Read a buyer run-log and extract the deal context.

    Tolerates either a `market negotiate` log (one negotiation,
    fields at the run_started/run_ended boundary) or a `market buy`
    log (potentially multiple negotiation attempts; uses the most
    recent agreed one). Picks up any `escrow_created` event already
    present so callers can short-circuit stage 3.
    """
    events = read_run(run_id)
    if not events:
        raise typer.BadParameter(
            f"No run-log found for run_id={run_id!r}. "
            f"Check `market logs runs`."
        )

    seller_url: Optional[str] = None
    listing_id: Optional[str] = None
    negotiation_id: Optional[str] = None
    agreed_amount: Optional[float] = None
    escrow_uid: Optional[str] = None
    duration_seconds: int = 3600
    seller_wallet_address: Optional[str] = None
    token_contract: Optional[str] = None
    token_decimals: Optional[float] = None
    last_status: Optional[str] = None

    for ev in events:
        ev_type = ev.get("event")

        # `negotiate` end carries the agreed_amount + negotiation_id.
        if ev_type == "run_ended":
            last_status = ev.get("status")
            if ev.get("agreed_amount") is not None:
                agreed_amount = float(ev["agreed_amount"])
            if ev.get("negotiation_id"):
                negotiation_id = str(ev["negotiation_id"])

        # `market buy`-style log.
        if ev_type == "negotiation_completed" and ev.get("status") == "agreed":
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
        name for name, v in (
            ("seller_url", seller_url),
            ("listing_id", listing_id),
            ("negotiation_id", negotiation_id),
            ("agreed_amount", agreed_amount),
        ) if not v
    ]
    if missing:
        raise typer.BadParameter(
            f"Run-log {run_id!r} is missing fields: {', '.join(missing)}. "
            f"Last status was {last_status!r}. Recovery requires a "
            f"prior `agreed` outcome."
        )

    return DealContext(
        seller_url=seller_url,                # type: ignore[arg-type]
        listing_id=listing_id,                # type: ignore[arg-type]
        negotiation_id=negotiation_id,        # type: ignore[arg-type]
        agreed_amount=agreed_amount,            # type: ignore[arg-type]
        escrow_uid=escrow_uid,
        duration_seconds=duration_seconds,
        seller_wallet_address=seller_wallet_address,
        token_contract=token_contract,
        token_decimals=token_decimals,
    )


@dataclass
class ChainSettings:
    """Buyer-side chain + token resolution result.

    `ssh_public_key` is empty for commands that don't submit settlement
    (e.g. `market escrow create`). Pass `require_ssh=False` to opt out
    of the missing-key guard.
    """
    buyer_address: str
    buyer_private_key: str
    ssh_public_key: str
    rpc_url: str
    chain_name: str
    alkahest_addr_config: Optional[str]
    token_contract: str
    token_decimals: int


def resolve_chain_settings(
    *,
    buyer_address: Optional[str],
    buyer_private_key: Optional[str],
    ssh_public_key: Optional[str],
    chain: "ChainConfig",
    token_contract: Optional[str],
    token_decimals: Optional[int],
    require_ssh: bool = True,
) -> ChainSettings:
    """Resolve wallet/SSH/token credentials around a pre-selected ChainConfig.

    Callers pick the chain first — via :func:`select_chain_for_listing` (buy /
    negotiate), :func:`chain_by_name` (escrow ops with --chain), or by
    looking it up from the run-log (settle --from). This function only
    validates the wallet/ssh credentials and resolves token decimals against
    the chosen chain's RPC.

    `require_ssh=False` skips the SSH-key check for commands that don't
    submit settlement.
    """
    from ..common import resolve_buyer_wallet, resolve_ssh_public_key

    addr, pk = resolve_buyer_wallet(
        override_addr=buyer_address, override_pk=buyer_private_key,
    )
    ssh = resolve_ssh_public_key(override=ssh_public_key)

    _key_for = {
        "buyer_priv_key": "wallet.private_key",
        "ssh_public_key": "wallet.ssh_public_key",
    }
    missing = [n for n, v in (
        ("buyer_priv_key", pk),
    ) if not v]
    if require_ssh and not ssh:
        missing.append("ssh_public_key")
    if missing:
        typer.secho("Missing required config:", err=True, fg=typer.colors.RED)
        for name in missing:
            typer.secho(
                f"  • {name} — set with: market config set {_key_for[name]} <value>",
                err=True, fg=typer.colors.RED,
            )
        typer.secho(
            "Run `market config init-user` to scaffold a config file with the full set of keys.",
            err=True, fg=typer.colors.YELLOW,
        )
        raise typer.Exit(2)

    tc = token_contract
    decimals: Optional[int] = token_decimals
    if not tc:
        typer.secho(
            "No --token-contract given and no token recorded on the run-log. "
            "Pass --token-contract or resume from a run-log that captured the "
            "negotiated token (`market buy` / `market negotiate` log it as "
            "part of round 0).",
            err=True, fg=typer.colors.RED,
        )
        raise typer.Exit(2)
    if decimals is None:
        from service.clients.token import resolve_token, TokenResolutionError
        try:
            meta = resolve_token(
                tc, rpc_url=chain.rpc_url, chain_id=chain.chain_id,
            )
            decimals = meta.decimals
        except (TokenResolutionError, RuntimeError) as exc:
            typer.secho(
                f"Could not resolve token {tc} on chain {chain.name!r} — pass "
                f"--token-decimals or check the chain's rpc_url. ({exc})",
                err=True, fg=typer.colors.RED,
            )
            raise typer.Exit(2)

    return ChainSettings(
        buyer_address=addr,
        buyer_private_key=pk,
        ssh_public_key=ssh,
        rpc_url=chain.rpc_url,
        chain_name=chain.name,
        alkahest_addr_config=chain.alkahest_address_config_path,
        token_contract=tc,
        token_decimals=decimals,
    )


def open_run_log(run_id: str) -> RunLog:
    """Append-only run log for the run we're recovering."""
    return RunLog.open(run_id)


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
    last_seller_proposal: Optional[dict]
    rounds_completed: int
    last_status: Optional[str]


def is_negotiation_complete(run_id: str) -> bool:
    """True iff the run-log already contains an `agreed` negotiation outcome.

    Used by ``market buy --from`` to decide whether to resume the
    negotiation round loop or jump straight to settlement.
    """
    for ev in read_run(run_id):
        if ev.get("event") == "negotiation_completed" and ev.get("status") == "agreed":
            return True
        if ev.get("event") == "run_ended" and ev.get("status") == "agreed":
            return True
    return False


def load_negotiation_resume_point(run_id: str) -> NegotiationResumePoint:
    """Reconstruct a partial negotiation from a prior run-log.

    Reads ``negotiation_round`` events to rebuild the transcript and
    pick the most recent seller counter proposal. Raises
    ``typer.BadParameter`` if the log doesn't have enough state to
    resume (no negotiation_id, no recorded rounds, etc.).
    """
    from market_policy.negotiation_middleware import NegotiationRound

    events = read_run(run_id)
    if not events:
        raise typer.BadParameter(
            f"No run-log found for run_id={run_id!r}. "
            f"Check `market logs runs`."
        )

    seller_url: Optional[str] = None
    listing_id: Optional[str] = None
    negotiation_id: Optional[str] = None
    transcript: list = []
    last_seller_proposal: Optional[dict] = None
    last_status: Optional[str] = None
    rounds_completed = 0

    for ev in events:
        et = ev.get("event")
        if et == "run_started":
            seller_url = ev.get("seller_url") or seller_url
            listing_id = ev.get("listing_id") or listing_id
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
            transcript.append(NegotiationRound(
                round_number=round_idx,
                sender="us",
                action=our_action,
                proposal=our_proposal if isinstance(our_proposal, dict) else None,
            ))
            their_action = their.get("action") or "counter"
            their_proposal = their.get("proposal")
            transcript.append(NegotiationRound(
                round_number=round_idx,
                sender="them",
                action=their_action,
                proposal=their_proposal if isinstance(their_proposal, dict) else None,
            ))
            if their_action == "counter" and isinstance(their_proposal, dict):
                last_seller_proposal = their_proposal
        elif et == "negotiation_completed":
            last_status = ev.get("status") or last_status
            if ev.get("negotiation_id"):
                negotiation_id = str(ev["negotiation_id"])
            if ev.get("listing_id"):
                listing_id = str(ev["listing_id"])

    missing = [n for n, v in (
        ("seller_url", seller_url),
        ("listing_id", listing_id),
        ("negotiation_id", negotiation_id),
    ) if not v]
    if missing:
        raise typer.BadParameter(
            f"Run-log {run_id!r} is missing fields needed to resume: "
            f"{', '.join(missing)}. Last status was {last_status!r}."
        )

    return NegotiationResumePoint(
        seller_url=seller_url,                # type: ignore[arg-type]
        listing_id=listing_id,                # type: ignore[arg-type]
        negotiation_id=negotiation_id,        # type: ignore[arg-type]
        transcript=transcript,
        last_seller_proposal=last_seller_proposal,
        rounds_completed=rounds_completed,
        last_status=last_status,
    )
