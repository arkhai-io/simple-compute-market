"""Deterministic payments authority shared by in-process and HTTP test doubles.

This is a contract fixture, not a production ledger. The caller owns time,
signing identity, authenticated accounts, funding and process/HTTP lifecycle.
"""

from __future__ import annotations

import base64
from collections.abc import Callable, Mapping
from copy import deepcopy
from dataclasses import dataclass, field
from datetime import datetime, timezone
import math
from typing import Any

from market_identity import Signer

from market_arkhai_payments.canonical import jcs_bytes, jcs_sha256
from market_arkhai_payments.errors import PaymentsAPIError
from market_arkhai_payments.models import (
    Balance, EventRequest, Mandate, SignedReceipt, SignedTransactionSnapshot, StoredDealAttachment,
)
from market_arkhai_payments.receipts import snapshot_message, transaction_id
from market_arkhai_payments.fixtures.receipts import build_signed_receipt
from market_arkhai_payments.fixtures.arithmetic import add_duration, periods_through


def _release_at(due: int) -> str:
    return datetime.fromtimestamp(due, timezone.utc).isoformat().replace("+00:00", "Z")


def sign_snapshot(signer: Signer, snapshot: Mapping[str, Any]) -> SignedTransactionSnapshot:
    body = dict(snapshot)
    body["issuer"] = signer.identity.model_dump(mode="json")
    return SignedTransactionSnapshot.model_validate({
        "snapshot": body,
        "proof": {
            "scheme": signer.identity.scheme.value,
            "value": base64.urlsafe_b64encode(signer.sign(snapshot_message(body))).decode().rstrip("="),
        },
    })


@dataclass
class _Part:
    terms: dict[str, Any]
    gross: int
    paid: int = 0
    earned: int = 0
    gross_earned: int = 0
    reversed: int = 0
    refunded: int = 0
    released: int = 0
    start: int | None = None
    stop: dict[str, Any] | None = None
    pending: dict[str, Any] | None = None
    # One retained amount per earning instant, newest reversed first.
    lots: list[tuple[int, int]] = field(default_factory=list)
    extensions: list[dict[str, Any]] = field(default_factory=list)

    @property
    def held(self) -> int:
        return sum(amount for _, amount in self.lots)

    @property
    def deadline(self) -> float:
        return float(min(self.terms.get("end", {}).get("at", math.inf),
                         self.pending["at"] if self.pending else math.inf))

    @property
    def retained(self) -> int:
        return (self.gross_earned if self.terms["kind"] == "rate" else self.gross) - self.reversed

    def maturity(self, earned_at: int) -> int | None:
        hold = self.terms["hold"]
        if "afterStop" in hold:
            if self.stop is None:
                return None
            normal = add_duration(self.stop["effectiveAt"], hold["afterStop"])
        else:
            normal = add_duration(earned_at, hold["for"])
        latest = max([normal] + [e.get("until", math.inf) for e in self.extensions])
        cap = self.terms["maxHoldExtension"]
        due = min(latest, math.inf if cap is None else add_duration(normal, cap))
        return int(due) if math.isfinite(due) else None


@dataclass
class _Transaction:
    mandate: dict[str, Any]
    receipt: SignedReceipt
    parts: list[_Part]
    at: int
    events: list[dict[str, Any]] = field(default_factory=list)
    retries: dict[tuple[str, str], tuple[dict[str, Any], dict[str, Any]]] = field(default_factory=dict)
    attachments: list[dict[str, Any]] = field(default_factory=list)


class PaymentsAuthority:
    """Clock-injected, signed per-part authority with atomic idempotent commands.

    Funding is explicit: accounts absent from balances have zero available funds.
    load() installs already-approved fixture state without replaying admission.
    There is no role-specific implicit stop, notice waiver or early release.
    """

    def __init__(self, *, signer: Signer, clock: Callable[[], int],
                 balances: Mapping[str, Mapping[str, int]] | None = None,
                 livemode: bool = False, ledger: str = "approval-1") -> None:
        self.signer = signer
        self.clock = clock
        self.livemode = livemode
        self.ledger = ledger
        self.balances = {account: dict(assets) for account, assets in (balances or {}).items()}
        self._transactions: dict[str, _Transaction] = {}

    def fund(self, account: str, asset: str, amount: int) -> None:
        if amount < 0:
            raise ValueError("fixture funding must be nonnegative")
        assets = self.balances.setdefault(account, {})
        assets[asset] = assets.get(asset, 0) + amount

    def approve(self, mandate: Mandate | Mapping[str, Any], *, account: str,
                agreement: dict[str, Any] | None = None) -> SignedReceipt:
        parsed = Mandate.model_validate(mandate)
        wire = parsed.model_dump(mode="json", by_alias=True, exclude_none=True)
        if account != wire["from"]:
            raise PaymentsAPIError(403, "caller_not_authorized")
        transaction = transaction_id(parsed)
        if transaction in self._transactions:
            return self._transactions[transaction].receipt.model_copy(deep=True)
        now = self.clock()
        if now >= wire["expires"]:
            raise PaymentsAPIError(409, "mandate_expired")
        if any("afterStop" in p["hold"] and "end" not in p and not p["authorities"]["stop"]
               for p in wire["parts"]):
            raise PaymentsAPIError(422, "invalid_mandate")
        receipt = build_signed_receipt(
            signer=self.signer, mandate=parsed, approved_at=now,
            ledger=self.ledger, livemode=self.livemode,
        )
        needed: dict[str, int] = {}
        for part in receipt.receipt.parts:
            needed[part.asset.root] = needed.get(part.asset.root, 0) + int(part.gross)
        balance = self.balances.setdefault(account, {})
        if any(balance.get(asset, 0) < amount for asset, amount in needed.items()):
            raise PaymentsAPIError(409, "insufficient_funds")
        if agreement is not None and jcs_sha256(agreement) != wire["deal"]:
            raise PaymentsAPIError(409, "deal_mismatch")
        for asset, amount in needed.items():
            balance[asset] = balance.get(asset, 0) - amount
        self.load(parsed, receipt)
        if agreement is not None:
            self.attach_agreement(transaction, agreement, account=account)
        return receipt.model_copy(deep=True)

    def load(self, mandate: Mandate | Mapping[str, Any], receipt: SignedReceipt) -> None:
        """Seed a known approval; no admission, balance debit, or signature rewrite."""

        wire = Mandate.model_validate(mandate).model_dump(
            mode="json", by_alias=True, exclude_none=True)
        if transaction_id(mandate) != receipt.receipt.transaction.root:
            raise ValueError("fixture receipt does not bind mandate")
        self._install(wire, receipt)

    def load_receipt(self, receipt: SignedReceipt) -> None:
        """Seed receipt-only once fixtures; lifecycle-rich fixtures must supply a mandate."""

        body = receipt.receipt.model_dump(mode="json", by_alias=True, exclude_none=True)
        if any("rate" in p for p in body["parts"]):
            raise ValueError("rate receipt fixtures require their exact mandate")
        wire = {"from": body["from"], "to": body["to"], "fee": {"bps": 0}, "parts": [
            {"kind": "once", "asset": p["asset"], "amount": p["gross"], "hold": p["hold"],
             "maxHoldExtension": "P0D",
             "authorities": {"stop": [], "reverse": [body["to"]], "extend": []}}
            for p in body["parts"]
        ]}
        # Receipt fees allow the original bps to vary within a rounding interval;
        # only their actual paid fee matters for these once-only seeded fixtures.
        self._install(wire, receipt)

    def _install(self, wire: dict[str, Any], receipt: SignedReceipt) -> None:
        approved = receipt.receipt.approvedAt
        parts = []
        for terms, allocation in zip(deepcopy(wire["parts"]), receipt.receipt.parts):
            if "end" in terms:
                terms["end"]["at"] = max(approved, terms["end"]["at"])
            count = int(allocation.rate.periodsReserved) if allocation.rate else 0
            part = _Part(terms=terms, gross=int(allocation.gross), paid=count)
            if terms["kind"] == "once":
                part.lots = [(approved, part.gross)]
            parts.append(part)
        self._transactions[receipt.receipt.transaction.root] = _Transaction(
            wire, receipt.model_copy(deep=True), parts, approved)

    def _get(self, transaction: str) -> _Transaction:
        try:
            return self._transactions[transaction]
        except KeyError:
            raise PaymentsAPIError(404, "transaction_not_found") from None

    def attach_agreement(self, transaction: str, agreement: dict[str, Any], *,
                         account: str) -> StoredDealAttachment:
        tx = self._get(transaction)
        if account not in (tx.mandate["from"], tx.mandate["to"]):
            raise PaymentsAPIError(403, "caller_not_authorized")
        digest = jcs_sha256(agreement)
        if digest != tx.receipt.receipt.deal.root.root:
            raise PaymentsAPIError(409, "deal_mismatch")
        for attachment in tx.attachments:
            if attachment["sha256"] == digest:
                return StoredDealAttachment.model_validate(attachment)
        stored = {"kind": "deal", "content": deepcopy(agreement), "sha256": digest,
                  "name": "deal.json", "mediaType": "application/json",
                  "size": len(jcs_bytes(agreement)), "uploader": account}
        tx.attachments.append(stored)
        return StoredDealAttachment.model_validate(stored)

    def _credit(self, tx: _Transaction, asset: str, amount: int, *, payee: bool = False) -> None:
        account = tx.mandate["to" if payee else "from"]
        self.fund(account, asset, amount)

    def _release(self, tx: _Transaction, part: _Part, at: int) -> None:
        kept = []
        for earned_at, amount in part.lots:
            due = part.maturity(earned_at)
            if due is None or due > at:
                kept.append((earned_at, amount))
            else:
                before = part.released * tx.mandate["fee"]["bps"] // 10_000
                part.released += amount
                cut = part.released * tx.mandate["fee"]["bps"] // 10_000 - before
                self._credit(tx, part.terms["asset"], amount - cut, payee=True)
        part.lots = kept

    def _catch_up(self, tx: _Transaction, at: int) -> None:
        for part in tx.parts:
            if part.terms["kind"] == "rate" and part.start is not None and part.stop is None:
                cap = min(at, part.deadline, add_duration(
                    part.start, part.terms["period"], part.paid))
                count = min(part.paid, periods_through(
                    part.start, part.terms["period"], int(cap), partial=False))
                while part.earned < count:
                    part.earned += 1
                    amount = int(part.terms["amount"])
                    part.gross_earned += amount
                    part.lots.append((add_duration(
                        part.start, part.terms["period"], part.earned), amount))
            self._release(tx, part, at)
        tx.at = max(tx.at, at)

    def _trim(self, tx: _Transaction, part: _Part, now: int) -> None:
        if part.terms["kind"] != "rate" or part.stop or not math.isfinite(part.deadline):
            return
        count = min(part.paid, periods_through(
            part.start if part.start is not None else now,
            part.terms["period"], int(part.deadline)))
        refund = (part.paid - count) * int(part.terms["amount"])
        part.paid = count
        part.refunded += refund
        self._credit(tx, part.terms["asset"], refund)

    def _stop(self, tx: _Transaction, index: int, at: int, cause: str,
              sequence: int, rule: str) -> None:
        part = tx.parts[index]
        if part.stop is not None:
            return
        if part.terms["kind"] == "rate":
            unit = int(part.terms["amount"])
            if part.start is not None and part.earned < part.paid:
                lo = add_duration(part.start, part.terms["period"], part.earned)
                hi = add_duration(part.start, part.terms["period"], part.earned + 1)
                elapsed = max(0, at - lo)
                cut = 0 if rule == "returned" or not elapsed else (
                    unit if rule == "charged" else unit * elapsed // (hi - lo))
                if cut:
                    part.gross_earned += cut
                    part.earned += 1
                    part.lots.append((at, cut))
            refund = part.paid * unit - part.gross_earned
            part.refunded += refund
            self._credit(tx, part.terms["asset"], refund)
        gross = part.retained
        fee = gross * tx.mandate["fee"]["bps"] // 10_000
        part.stop = {"effectiveAt": at, "cause": cause, "sequence": sequence,
                     "partialPeriod": rule, "settled": {
                         "part": index, "asset": part.terms["asset"], "gross": str(gross),
                         "fee": str(fee), "net": str(gross - fee)}}
        part.pending = None
        self._release(tx, part, at)

    def advance(self, transaction: str, *, refill: bool = True) -> None:
        """Apply durable deadlines before catching up/refilling at the injected clock."""

        tx = self._get(transaction)
        now = max(self.clock(), tx.at)
        while True:
            active = [(i, p) for i, p in enumerate(tx.parts) if p.stop is None]
            exhaustion = min((add_duration(p.start, p.terms["period"], p.paid)
                              for _, p in active if p.terms["kind"] == "rate"
                              and p.start is not None
                              and add_duration(p.start, p.terms["period"], p.paid) < p.deadline),
                             default=math.inf)
            at = min([exhaustion] + [p.deadline for _, p in active])
            if at > now or not math.isfinite(at):
                break
            instant = int(at)
            self._catch_up(tx, instant)
            if at == exhaustion:
                sequence = len(tx.events) + 1
                tx.events.append({"issuer": "terms",
                    "requestId": f"terms:{transaction}:{instant}",
                    "event": {"kind": "stop"}, "receivedAt": instant, "sequence": sequence})
                for i, _ in active:
                    self._stop(tx, i, instant, "terms", sequence, "charged")
            else:
                for i, part in active:
                    if part.deadline != at:
                        continue
                    if part.pending is not None and part.pending["at"] == at:
                        pending = part.pending
                        self._stop(tx, i, instant, pending["cause"],
                                   pending["sequence"], pending["partialPeriod"])
                    else:
                        sequence = len(tx.events) + 1
                        tx.events.append({"issuer": "terms",
                            "requestId": f"terms:{transaction}:{i}:{instant}",
                            "event": {"kind": "stop", "part": i},
                            "receivedAt": instant, "sequence": sequence})
                        self._stop(tx, i, instant, "terms", sequence,
                                   part.terms["end"]["partialPeriod"])
        self._catch_up(tx, now)
        if refill:
            self._refill(tx, now)

    def _refill(self, tx: _Transaction, now: int) -> None:
        balance = self.balances.setdefault(tx.mandate["from"], {})
        for part in tx.parts:
            p = part.terms
            if p["kind"] != "rate" or part.start is None or part.stop:
                continue
            paid_through = add_duration(part.start, p["period"], part.paid)
            lead = max(add_duration(now, p["period"]), add_duration(now, p["reserveAhead"]))
            if paid_through >= part.deadline or lead < paid_through:
                continue
            wanted = periods_through(part.start, p["period"], lead + 60)
            if math.isfinite(part.deadline):
                wanted = min(wanted, periods_through(
                    part.start, p["period"], int(part.deadline)))
            amount = int(p["amount"])
            count = min(max(0, wanted - part.paid), max(0, balance.get(p["asset"], 0)) // amount)
            part.paid += count
            part.gross += count * amount
            balance[p["asset"]] = balance.get(p["asset"], 0) - count * amount

    def submit(self, transaction: str, request: EventRequest | Mapping[str, Any]) -> dict[str, Any]:
        """Apply one authenticated event; a lost response can be retried unchanged."""

        wire = EventRequest.model_validate(request).model_dump(
            mode="json", by_alias=True, exclude_none=True)
        tx = self._get(transaction)
        key = (wire["account"], wire["requestId"])
        prior = tx.retries.get(key)
        if prior is not None:
            if jcs_bytes(prior[0]) != jcs_bytes(wire):
                raise PaymentsAPIError(409, "request_id_reused")
            return deepcopy(prior[1])
        event = wire["event"]
        kind = event["kind"]
        specified = event.get("part")
        if specified is not None and specified >= len(tx.parts):
            raise PaymentsAPIError(404, "part_not_found")
        if (("amount" in event and (kind != "reverse" or specified is None))
                or ("at" in event and kind != "stop")
                or ("partialPeriod" in event and kind != "stop")
                or ("until" in event and kind != "extend")
                or ("ref" in event and kind != "lift")
                or (kind in ("extend", "lift") and specified is None)
                or (kind == "lift" and "ref" not in event)):
            raise PaymentsAPIError(422, "invalid_event")
        targets = [i for i, part in enumerate(tx.parts)
                   if (specified is None or specified == i)
                   and (kind != "start" or part.terms["kind"] == "rate")]
        if not targets:
            raise PaymentsAPIError(422, "invalid_event")
        for i in targets:
            auth = tx.parts[i].terms["authorities"]
            entries = auth["extend" if kind == "lift" else kind]
            if kind == "stop":
                entry = next((e for e in entries if e["account"] == wire["account"]), None)
                if entry is None:
                    raise PaymentsAPIError(403, "caller_not_authorized")
                if (entry["partialPeriod"] == "chosen") != ("partialPeriod" in event):
                    raise PaymentsAPIError(422, "invalid_event")
            elif wire["account"] not in entries:
                raise PaymentsAPIError(403, "caller_not_authorized")
        now = max(self.clock(), tx.at)
        if event.get("at", now) < now or event.get("until", now + 1) <= now:
            raise PaymentsAPIError(422, "invalid_event")
        self.advance(transaction, refill=False)
        # Failed events must not partially reverse or start several parts.
        tx = deepcopy(tx)
        balances = deepcopy(self.balances)
        try:
            result = self._apply(tx, wire, targets, now)
        except Exception:
            self.balances = balances
            raise
        tx.retries[key] = (deepcopy(wire), deepcopy(result))
        self._transactions[transaction] = tx
        return deepcopy(result)

    def _apply(self, tx: _Transaction, wire: dict[str, Any], targets: list[int],
               now: int) -> dict[str, Any]:
        event, kind = wire["event"], wire["event"]["kind"]
        if kind == "start" and any(tx.parts[i].stop for i in targets):
            raise PaymentsAPIError(409, "transaction_stopped")
        if kind == "stop" and all(tx.parts[i].stop for i in targets):
            sequence = tx.parts[targets[0]].stop["sequence"]  # type: ignore[index]
            return next(e for e in tx.events if e["sequence"] == sequence)
        if kind == "reverse":
            moved = False
            for i in targets:
                part = tx.parts[i]
                amount = int(event.get("amount", part.held))
                if not amount:
                    if event.get("part") is not None:
                        raise PaymentsAPIError(409, "hold_not_reversible")
                    continue
                if amount > part.held:
                    raise PaymentsAPIError(409, "insufficient_held_funds")
                left = amount
                while left:
                    at, available = part.lots.pop()
                    cut = min(left, available)
                    if available > cut:
                        part.lots.append((at, available - cut))
                    left -= cut
                part.reversed += amount
                self._credit(tx, part.terms["asset"], amount)
                moved = True
            if not moved:
                raise PaymentsAPIError(409, "hold_not_reversible")
        if kind in ("extend", "lift"):
            part = tx.parts[targets[0]]
            if kind == "extend" and not part.held and (part.terms["kind"] == "once" or part.stop):
                raise PaymentsAPIError(409, "hold_not_extendable")
            if kind == "lift" and not any(e["ref"] == event["ref"] for e in part.extensions):
                opened = any(e["sequence"] == event["ref"] and e["event"]["kind"] == "extend"
                             and e["event"].get("part") == event["part"] for e in tx.events)
                raise PaymentsAPIError(409 if opened else 404,
                                       "extension_closed" if opened else "extension_not_found")
        sequence = len(tx.events) + 1
        stored = deepcopy(wire) | {"receivedAt": now, "sequence": sequence}
        tx.events.append(stored)
        for i in targets:
            part = tx.parts[i]
            if kind == "start":
                if part.start is None:
                    part.start = now
                self._trim(tx, part, now)
            elif kind == "stop" and part.stop is None:
                entry = next(e for e in part.terms["authorities"]["stop"]
                             if e["account"] == wire["account"])
                rule = event["partialPeriod"] if entry["partialPeriod"] == "chosen" else entry["partialPeriod"]
                effective = max(event.get("at", now), add_duration(now, entry["notice"]))
                cause = ("payer" if wire["account"] == tx.mandate["from"] else
                         "payee" if wire["account"] == tx.mandate["to"] else "authority")
                if effective == now:
                    self._stop(tx, i, now, cause, sequence, rule)
                elif part.pending is None or effective < part.pending["at"]:
                    part.pending = {"at": effective, "cause": cause,
                                    "partialPeriod": rule, "sequence": sequence}
                self._trim(tx, part, now)
            elif kind == "extend":
                part.extensions.append({"ref": sequence, **(
                    {"until": event["until"]} if "until" in event else {})})
            elif kind == "lift":
                part.extensions = [e for e in part.extensions if e["ref"] != event["ref"]]
                self._release(tx, part, now)
        if kind == "start":
            self._refill(tx, now)
        tx.at = now
        return stored

    def snapshot(self, transaction: str) -> SignedTransactionSnapshot:
        self.advance(transaction, refill=False)
        tx = self._get(transaction)
        bps = tx.mandate["fee"]["bps"]
        parts = []
        boundaries = []
        for i, part in enumerate(tx.parts):
            p = part.terms
            rate = p["kind"] == "rate"
            reserved = part.gross - part.gross_earned - part.refunded if rate else 0
            status = ("held" if part.held + reserved else
                      "settled" if part.refunded or (part.released and part.reversed) else
                      "released" if part.released else "reversed" if part.reversed else "settled")
            view = {"part": i, "asset": p["asset"], "gross": str(part.gross),
                    "held": str(part.held), "reserved": str(reserved),
                    "refunded": str(part.refunded), "released": str(part.released),
                    "reversed": str(part.reversed),
                    "feePaid": str((part.retained if rate else part.released) * bps // 10_000),
                    "hold": p["hold"], "extensions": part.extensions, "status": status}
            for name, value in (("started", part.start), ("stop", part.stop),
                                ("pendingStop", part.pending), ("end", p.get("end"))):
                if value is not None:
                    view[name] = value
            dues = [part.maturity(at) for at, _ in part.lots]
            if not rate and not dues:
                # Once maturity remains readable after release/reversal.
                dues = [part.maturity(tx.receipt.receipt.approvedAt)]
            if dues and all(due is not None for due in dues):
                due = min(d for d in dues if d is not None)
                view["releaseAt"] = _release_at(due)
            if rate:
                progress: dict[str, Any] = {
                    "periodsEarned": str(part.earned), "grossEarned": str(part.gross_earned)}
                if part.start is not None:
                    through = int(min(add_duration(part.start, p["period"], part.paid),
                                      part.deadline, part.stop["effectiveAt"] if part.stop else math.inf))
                    progress["reservedThrough"] = through
                    if part.stop is None:
                        boundaries.append(through)
                view["rate"] = progress
            parts.append(view)
        body = {"livemode": tx.receipt.receipt.livemode, "transaction": transaction,
                "receipt": tx.receipt.model_dump(mode="json", by_alias=True, exclude_none=True),
                "observedAt": max(self.clock(), tx.at), "parts": parts, "events": tx.events,
                "latestEventSequence": len(tx.events), "attachments": tx.attachments}
        if boundaries:
            body["fundedThrough"] = min(boundaries)
        return sign_snapshot(self.signer, body)

    def balance(self, account: str) -> Balance:
        """One account's own balance, as the payments service's balance read reports it.

        Every transaction the account is a party to is first brought to the clock
        as a snapshot read brings it, so money matured since the last operation is
        already in the payee's ``available`` and a read never shows it held.
        """

        for transaction, tx in list(self._transactions.items()):
            if account in (tx.mandate["from"], tx.mandate["to"]):
                self.advance(transaction, refill=False)
        held: list[dict[str, Any]] = []
        for transaction, tx in self._transactions.items():
            if tx.mandate["to"] != account:
                continue
            for index, part in enumerate(tx.parts):
                held.extend(self._held_entries(tx, transaction, index, part))
        available = {asset: str(amount) for asset, amount in self.balances.get(account, {}).items()}
        return Balance.model_validate({"available": available, "held": held})

    @staticmethod
    def _held_entries(tx: _Transaction, transaction: str, index: int,
                      part: _Part) -> list[dict[str, Any]]:
        # A rate part's periods mature one by one, so one entry per maturity keeps
        # later money from reading as releasing at the earliest date.
        timed: dict[int, int] = {}
        open_ended = 0
        for earned_at, amount in part.lots:
            due = part.maturity(earned_at)
            if due is None:
                open_ended += amount
            else:
                timed[due] = timed.get(due, 0) + amount
        common = {"transaction": transaction, "part": index, "from": tx.mandate["from"],
                  "to": tx.mandate["to"], "asset": part.terms["asset"], "fee": tx.mandate["fee"]}
        entries = [common | {"address": f"hold:{transaction}:{index}:{due}",
                             "balance": str(amount), "releaseAt": _release_at(due)}
                   for due, amount in sorted(timed.items()) if amount]
        if open_ended:
            # An after-stop hold has no maturity until its stop, whatever extensions
            # are open; otherwise an unbounded open extension is what holds the lots.
            awaiting_stop = "afterStop" in part.terms["hold"] and part.stop is None
            until = "lift" if part.extensions and not awaiting_stop else "stop"
            entries.append(common | {"address": f"hold:{transaction}:{index}:until",
                                     "balance": str(open_ended), "until": until})
        return entries
