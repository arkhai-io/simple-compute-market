"""The dispute authority's API mechanics over programmed decisions, free of any web framework.

The double reproduces what the authority does mechanically: bearer
authentication, schema validation against the vendored contract, idempotency and
its conflict answer, each part's extension at payments as the authority's own
account, the automatic dismissal of a case whose every part is not held, appends
by either party with concurrence only from the payee, the closed-case refusal, the
signed per-Agreement record with its sequence and cursors, the respondent listing,
and the execution of a ruling's effects as payment events under stable keys,
resumed after a payments failure without applying an effect twice.

Every decision the authority would make is a scenario's: whether a case is ruled,
its basis, delivery end and effects, a filing's answer, and a gate before effects.
With no matching rule nothing is ever ruled. A filing is admitted as the
authority admits one: its filer is a party, and its Agreement is the one the
payment's signed receipt commits to. The double verifies no concurrence signature
or mechanical guard; the kits prove the marketplace's own verification against
the producer's vectors.

All state is in this process's memory, behind one lock; a restart loses it, since
a run lives only as long as its lane.
"""

from __future__ import annotations

import hashlib
import json
import re
import secrets
import threading
from collections.abc import Callable, Mapping
from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any, Protocol
from urllib.parse import unquote

from jsonschema import ValidationError as SchemaValidationError
from lane_double_controls.middleware import Fault, FaultRequest
from lane_double_controls.models import (
    CaseList,
    CaseView,
    ControlError,
    FilingAnswer,
    Rule,
    RuleView,
    Ruling,
)
from market_arkhai_mediation.contract import validate
from market_arkhai_mediation.records import record_message
from market_arkhai_payments.errors import PaymentsAPIError, PaymentsError
from market_identity import SignatureProof, canonical_json

from mediation_lane_double.authority import AuthorityFixture
from mediation_lane_double.protection import not_held_reason
from mediation_lane_double.rules import Entry, RuleBook

_KEY = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")
# The scheme name is case-insensitive (RFC 7235); a token holds no whitespace.
_BEARER = re.compile(r"^bearer (\S+)$", re.IGNORECASE)


class PaymentsPeer(Protocol):
    """What the double asks of payments, as the authority's own account."""

    def get_transaction(self, transaction: str) -> Any: ...

    def submit_event(self, transaction: str, event: Mapping[str, Any], *,
                     request_id: str) -> Any: ...


class ApiRefusal(Exception):
    """An API call refused with an HTTP status and the contract's error code."""

    def __init__(self, status: int, code: str) -> None:
        super().__init__(f"{status} {code}")
        self.status = status
        self.code = code


class _Incomplete(Exception):
    """A part's protection could not be determined; a retry under the same key completes it."""


@dataclass(frozen=True)
class _Parties:
    payer: str
    payee: str
    parts: int
    #: The receipt's deal commitment: the JCS SHA-256 of the Agreement it paid.
    deal: str


@dataclass
class Case:
    case_ref: str
    transaction: str
    agreement: str
    filer: str
    filer_account: str
    request: dict[str, Any]
    parts: list[dict[str, Any]]
    filed_at: int
    filed_record_ref: str
    state: str = "open"
    appended: set[str] = field(default_factory=set)
    ruling: Ruling | None = None
    #: How many rulings the case has had; it names each ruling's effects.
    rulings: int = 0
    outcome: list[dict[str, Any]] = field(default_factory=list)
    #: Each prepared effect's request id and payment event, by its effect id.
    events: dict[str, tuple[str, dict[str, Any]]] = field(default_factory=dict)
    rule_id: str | None = None
    lifted: set[int] = field(default_factory=set)

    def answer(self) -> dict[str, Any]:
        return {"case_ref": self.case_ref, "transaction": self.transaction,
                "agreement": self.agreement, "state": self.state, "parts": deepcopy(self.parts)}

    def view(self) -> CaseView:
        return CaseView(case_ref=self.case_ref, transaction=self.transaction,
                        agreement=self.agreement, state=self.state, filer=self.filer,
                        kind=self.request["kind"], cause=self.request.get("cause"))


class MediationDouble:
    """The authority's behaviour over the double's records and its payments peer.

    Each API method takes the authenticated account and the request's parts and
    returns the response body, refusing with ``ApiRefusal``; each control method
    refuses with ``ControlError``.
    """

    def __init__(self, authority: AuthorityFixture, payments: PaymentsPeer, *,
                 clock: Callable[[], int], rules: RuleBook) -> None:
        self.authority = authority
        self.payments = payments
        self.rules = rules
        self._clock = clock
        self._signer = authority.signer()
        self._issuer = self._signer.identity.model_dump(mode="json")
        self._cases: dict[str, Case] = {}
        self._order: list[str] = []
        self._records: dict[str, list[dict[str, Any]]] = {}
        # The two parties of every Agreement a party has filed for: who may read
        # its record. An Agreement is known from its first admitted filing.
        self._readers: dict[str, frozenset[str]] = {}
        self._parties: dict[str, _Parties] = {}
        self._replays: dict[tuple[str, str, str], tuple[bytes, dict[str, Any]]] = {}
        # A case reference handed out before its case exists, with the filing it
        # was handed to, under the key that asked: a pending answer's, or a filing
        # whose protection is incomplete.
        self._reserved: dict[tuple[str, str], tuple[str, bytes]] = {}
        self._next = 0
        # Case references, and so the payments request ids built from them, are
        # unique to this process: the payments double outlives a restarted
        # mediation double, and must not answer a new case's extends with an
        # earlier process's stored events.
        self._prefix = secrets.token_hex(4)
        self._lock = threading.RLock()
        self._cache_lock = threading.Lock()

    # API -----------------------------------------------------------------------

    def authenticate(self, authorization: str | None) -> str:
        match = _BEARER.fullmatch(authorization or "")
        account = self.authority.account_for_token(match.group(1)) if match else None
        if account is None:
            raise ApiRefusal(401, "authentication_required")
        return account

    def file(self, actor: str, key: str | None, body: bytes) -> dict[str, Any]:
        idempotency_key = _key(key)
        filing = _payload(body, "Filing")
        with self._lock:
            replay = self._replay(actor, idempotency_key, "/cases", filing)
            if replay is not None:
                return replay
            reserved = self._reserved.get((actor, idempotency_key))
            if reserved is not None and reserved[1] != canonical_json(filing):
                # A key a filing reserved a case under stays that filing's.
                return _failure("idempotency_conflict", "the key was used for another request")
            transaction = filing["transaction"]
            try:
                parties = self._parties_of(transaction)
            except PaymentsError:
                return _failure("protection_incomplete", "payments could not be read")
            if actor not in (parties.payer, parties.payee):
                return self._remember(actor, idempotency_key, "/cases", filing, {
                    "status": "rejected", "reason": "filer_not_party",
                    "message": "the filer is neither party to the transaction"})
            agreement = hashlib.sha256(canonical_json(filing["agreement"])).hexdigest()
            if agreement != parties.deal:
                # The authority's admission rule: a case binds the Agreement the
                # payment committed to, so a filing naming another Agreement makes
                # it known to no reader and reserves no case.
                return self._remember(actor, idempotency_key, "/cases", filing, {
                    "status": "rejected", "reason": "agreement_hash_mismatch",
                    "message": "the Agreement is not the one the payment's receipt commits to"})
            # The Agreement's first filing names who may read its record.
            self._readers.setdefault(agreement, frozenset({parties.payer, parties.payee}))
            filer = "payer" if actor == parties.payer else "payee"
            entry = self.rules.first(_claim_properties("file", filer, transaction, filing["request"]))
            ruling_rule = self._act_on(entry, filing=(actor, idempotency_key, filing))
            if isinstance(ruling_rule, dict):
                return ruling_rule
            case_ref = self._reserve((actor, idempotency_key), filing)
            try:
                parts = self._protect(case_ref, transaction, parties.parts)
            except _Incomplete:
                return _failure("protection_incomplete",
                                "payments has not answered every part's extension")
            case = Case(case_ref=case_ref, transaction=transaction, agreement=agreement,
                        filer=filer, filer_account=actor, request=deepcopy(filing["request"]),
                        parts=parts, filed_at=self._clock(), filed_record_ref="")
            self._cases[case_ref] = case
            self._order.append(case_ref)
            filed = self._record(case, actor, "filed", filing=deepcopy(filing))
            # The respondent listing's filing time is the signed filed entry's.
            case.filed_record_ref = filed["entry"]["record_ref"]
            case.filed_at = filed["entry"]["at"]
            if all(part["status"] == "not_held" for part in parts):
                # The contract's automatic dismissal: payments can act on no part.
                self._record(case, self.authority.account, "closed", reason="dismissed",
                             dismissal_reason="nothing_held", outcome=[])
                case.state = "closed"
            elif ruling_rule is not None:
                assert ruling_rule.ruling is not None
                self._rule(case, ruling_rule.ruling, ruling_rule)
            answer = self._remember(actor, idempotency_key, "/cases", filing,
                                    {"status": "accepted", "case": case.answer()})
            # Released only once the answer is remembered under the key.
            del self._reserved[(actor, idempotency_key)]
            return answer

    def append(self, actor: str, key: str | None, body: bytes) -> dict[str, Any]:
        idempotency_key = _key(key)
        append = _payload(body, "Append")
        with self._lock:
            replay = self._replay(actor, idempotency_key, "/append", append)
            if replay is not None:
                return replay
            case = self._cases.get(append["case_ref"])
            refusal = None
            if case is None:
                refusal = ("case_not_found", "no such case")
            elif case.state == "closed":
                refusal = ("case_closed", "the case is closed")
            elif actor not in self._readers[case.agreement]:
                refusal = ("actor_not_party", "the caller is neither party to the case")
            elif "concurrence" in append and actor != self._parties[case.transaction].payee:
                refusal = ("actor_not_party", "only the payee may concur")
            if refusal is not None:
                return self._remember(actor, idempotency_key, "/append", append, {
                    "status": "rejected", "reason": refusal[0], "message": refusal[1]})
            assert case is not None
            entry = self.rules.first(_case_properties("append", case))
            ruling_rule = self._act_on(entry, filing=None)
            fields: dict[str, Any] = {"items": deepcopy(append.get("items", []))}
            if "concurrence" in append:
                fields["concurrence"] = deepcopy(append["concurrence"])
            signed = self._record(case, actor, "appended", **fields)
            case.appended.add(actor)
            if isinstance(ruling_rule, Rule) and case.state == "open":
                assert ruling_rule.ruling is not None
                self._rule(case, ruling_rule.ruling, ruling_rule)
            return self._remember(actor, idempotency_key, "/append", append,
                                  {"status": "accepted", "record": signed})

    def case(self, actor: str, case_ref: str) -> dict[str, Any]:
        with self._lock:
            case = self._cases.get(case_ref)
            self._act_on(self.rules.first(
                _case_properties("case", case) if case is not None else {"operation": "case"}),
                filing=None)
            if case is None or actor not in self._readers[case.agreement]:
                raise ApiRefusal(404, "invalid_request")
            return {"status": "accepted", "case": case.answer()}

    def record(self, actor: str, query: Mapping[str, str]) -> dict[str, Any]:
        request: dict[str, Any] = {"agreement": query.get("agreement")}
        try:
            request["after"] = int(query.get("after", ""))
            if "limit" in query:
                request["limit"] = int(query["limit"])
            validate("ReadAfter", request)
        except (ValueError, SchemaValidationError):
            raise ApiRefusal(400, "invalid_request") from None
        with self._lock:
            self._act_on(self.rules.first({"operation": "record"}), filing=None)
            # An Agreement nobody has filed for and a reader who is no party to it
            # get the same refusal, so a read discloses nothing of either.
            if actor not in self._readers.get(request["agreement"], frozenset()):
                raise ApiRefusal(404, "invalid_request")
            entries = [signed for signed in self._records.get(request["agreement"], [])
                       if signed["entry"]["sequence"] > request["after"]]
            selected = entries[:request.get("limit", 100)]
            return {"agreement": request["agreement"], "entries": deepcopy(selected),
                    "next_after": (selected[-1]["entry"]["sequence"] if selected
                                   else request["after"]),
                    "has_more": len(entries) > len(selected)}

    def respondent(self, actor: str, query: Mapping[str, str]) -> dict[str, Any]:
        request: dict[str, Any] = {"after": query.get("after", "")}
        try:
            if "limit" in query:
                request["limit"] = int(query["limit"])
            validate("RespondentAfter", request)
            after = int(request["after"]) if request["after"] else 0
        except (ValueError, SchemaValidationError):
            raise ApiRefusal(400, "invalid_request") from None
        with self._lock:
            self._act_on(self.rules.first({"operation": "respondent"}), filing=None)
            pending = []
            for position, case_ref in enumerate(self._order, 1):
                case = self._cases[case_ref]
                if (position <= after or case.state == "closed" or case.filer_account == actor
                        or actor not in self._readers[case.agreement] or actor in case.appended):
                    continue
                pending.append((position, {
                    **{key: value for key, value in case.answer().items() if key != "state"},
                    "filed_at": case.filed_at, "filer": case.filer,
                    "request": deepcopy(case.request), "filed_record_ref": case.filed_record_ref,
                }))
            selected = pending[:request.get("limit", 100)]
            return {"cases": [answer for _, answer in selected],
                    "next_after": str(selected[-1][0]) if selected else request["after"],
                    "has_more": len(pending) > len(selected)}

    def fault_for(self, request: FaultRequest) -> Fault | None:
        """The transport fault a call meets, counted against its rule, or ``None``."""

        entry = self.rules.first(self._properties(request))
        if entry is None or not (entry.rule.unavailable or entry.rule.drop_response_after_commit):
            return None
        self.rules.count(entry)
        return Fault.UNAVAILABLE if entry.rule.unavailable else Fault.DROP_AFTER_COMMIT

    # Controls ------------------------------------------------------------------

    def cases(self, transaction: str) -> CaseList:
        with self._lock:
            return CaseList(cases=[self._cases[ref].view() for ref in self._order
                                   if self._cases[ref].transaction == transaction])

    def decide(self, case_ref: str, ruling: Ruling) -> CaseView:
        """Rule an open case as its operator, or continue that ruling's application."""

        with self._lock:
            case = self._open_case(case_ref)
            if case.state == "applying":
                # Repeating the ruling a case is applying continues it, past its
                # gate or from where payments stopped it, whether or not the rule
                # that made it is still installed.
                if case.ruling != ruling:
                    raise ControlError(422, "invalid_request",
                                       f"case {case_ref} is applying another ruling")
                self._apply(case)
            else:
                self._rule(case, ruling, None)
            return case.view()

    def close_case(self, case_ref: str) -> CaseView:
        """Close an open case without a ruling, once its extensions are lifted.

        A case applying a ruling is refused and keeps its extensions: the
        contract's closed entry is final only after every effect is applied and
        the case's extensions are lifted, and it has no state for an abandoned
        effect. Resuming the rule or repeating the ruling completes its application.
        """

        with self._lock:
            case = self._open_case(case_ref)
            if case.state == "applying":
                raise ControlError(409, "case_applying",
                                   f"case {case_ref} is applying a ruling not yet applied")
            if not self._lift(case):
                raise ControlError(502, "payments_unavailable",
                                   f"payments did not lift case {case_ref}'s extensions")
            self._record(case, self.authority.account, "closed", reason="dismissed",
                         basis="operator", outcome=[])
            case.state = "closed"
            return case.view()

    def resume(self, rule_id: str) -> RuleView:
        """Continue every case waiting on ``rule_id``: past its gate, or where it stopped."""

        with self._lock:
            for case_ref in self.rules.waiting(rule_id):
                self._apply(self._cases[case_ref])
            return self.rules.view(rule_id)

    # Internals -----------------------------------------------------------------

    def _act_on(self, entry: Entry | None, *,
                filing: tuple[str, str, dict[str, Any]] | None
                ) -> Rule | dict[str, Any] | None:
        """Act on a call's first matching rule: refuse, answer a filing, or name its ruling.

        A drop or *unavailable* match is the middleware's, which counted it. A
        filing answer applies to a filing alone.
        """

        if entry is None:
            return None
        rule = entry.rule
        if rule.refusal is not None:
            self.rules.count(entry)
            raise ApiRefusal(rule.refusal.status, rule.refusal.code)
        if rule.filing_answer is not None and filing is not None:
            self.rules.count(entry)
            return self._programmed(filing, rule.filing_answer)
        if rule.ruling is not None:
            self.rules.count(entry)
            return rule
        return None

    def _programmed(self, filing: tuple[str, str, dict[str, Any]],
                    answer: FilingAnswer) -> dict[str, Any]:
        # A programmed answer is not remembered under its key, so a retry once the
        # rule is gone files for real; a pending answer's case reference is the one
        # that filing then takes.
        if answer.status == "pending":
            actor, key, payload = filing
            return {"status": "pending", "case_ref": self._reserve((actor, key), payload)}
        if answer.status == "error":
            return _failure(answer.code or "", "a programmed answer")
        return {"status": "rejected", "reason": answer.reason, "message": "a programmed answer"}

    def _reserve(self, key: tuple[str, str], filing: dict[str, Any]) -> str:
        """The case reference ``key``'s filing takes, reserved until its case exists."""

        reserved = self._reserved.get(key)
        if reserved is None:
            reserved = self._reserved[key] = (self._new_ref(), canonical_json(filing))
        return reserved[0]

    def _protect(self, case_ref: str, transaction: str, count: int) -> list[dict[str, Any]]:
        """Each part's protection: extended at payments, or not held and why.

        Each extend is sent under ``<case_ref>:<part>``, so a retry of an incomplete
        filing, which keeps its case reference, re-sends the same extends and
        payments answers those it already took with their stored events.
        """

        parts: list[dict[str, Any]] = []
        snapshot: list[dict[str, Any]] | None = None
        for part in range(count):
            try:
                stored = self.payments.submit_event(
                    transaction, {"kind": "extend", "part": part,
                                  "payload": {"case_ref": case_ref}},
                    request_id=f"{case_ref}:{part}")
            except PaymentsAPIError as error:
                # Only payments' nothing-held refusal says a part is not held.
                # Any other refusal, such as a misconfigured authority account,
                # must never tell a filer their money is not held.
                if error.code != "hold_not_extendable":
                    raise _Incomplete from error
                parts.append({"part": part, "status": "not_held"})
                continue
            except PaymentsError as error:
                raise _Incomplete from error
            parts.append({"part": part, "status": "held", "extension_ref": stored.sequence})
        for part in parts:
            if part["status"] == "not_held":
                if snapshot is None:
                    try:
                        snapshot = self._snapshot(transaction)["parts"]
                    except PaymentsError as error:
                        raise _Incomplete from error
                part["reason"] = not_held_reason(snapshot[part["part"]])
        return parts

    def _rule(self, case: Case, ruling: Ruling, rule: Rule | None) -> None:
        """Record ``ruling`` on ``case``, then apply it unless its rule holds it first.

        Each effect's id, stable within the Agreement, names the case and its
        ruling, so a later ruling on the same case never reuses one.
        """

        held = rule is not None and rule.pause_before_effects
        case.rulings += 1
        prefix = f"{case.case_ref}:{case.rulings}"
        outcome: list[dict[str, Any]] = []
        if ruling.delivery_end:
            # The delivery end is consumed from the signed record, never sent to
            # payments, so it is applied as it is recorded, unless the ruling is
            # held at its gate, which holds every effect.
            outcome.append({"id": f"{prefix}:end",
                            "effect": {"kind": "end_delivery", "at": self._clock()},
                            "state": "prepared" if held else "applied"})
        outcome.extend({"id": f"{prefix}:{number}", "effect": deepcopy(effect),
                        "state": "prepared"} for number, effect in enumerate(ruling.effects, 1))
        case.ruling, case.outcome, case.state = ruling, outcome, "applying"
        case.rule_id = rule.rule_id if rule is not None else None
        self._record(case, self.authority.account, "ruled", basis=ruling.basis,
                     outcome=deepcopy(outcome))
        if held:
            self.rules.set_waiting(case.rule_id, case.case_ref, True)
            return
        self._apply(case)

    def _apply(self, case: Case) -> bool:
        """Apply what remains of the case's ruling; ``False`` where payments stopped it.

        A refusal and a transport failure alike leave the case waiting, so a
        response lost after payments committed an effect is resent under the same
        key, and payments answers it with the event it stored rather than applying
        it twice.
        """

        assert case.ruling is not None
        prepared = any(item["state"] == "prepared" for item in case.outcome)
        for item in case.outcome:
            if item["state"] == "applied":
                continue
            if item["effect"]["kind"] == "end_delivery":
                item["state"] = "applied"
                continue
            # The event is fixed when it is first sent, so every resend under its
            # key is the same request.
            if item["id"] not in case.events:
                prefix, number = item["id"].rsplit(":", 1)
                case.events[item["id"]] = (f"mediation:{prefix}:effect:{number}",
                                           self._payment_event(item, case.case_ref))
            request_id, event = case.events[item["id"]]
            try:
                self.payments.submit_event(case.transaction, event, request_id=request_id)
            except PaymentsError:
                self.rules.set_waiting(case.rule_id, case.case_ref, True)
                return False
            item["state"] = "applied"
        if case.ruling.close:
            if not self._lift(case):
                self.rules.set_waiting(case.rule_id, case.case_ref, True)
                return False
            self._record(case, self.authority.account, "closed", reason="ruled",
                         basis=case.ruling.basis, outcome=deepcopy(case.outcome))
            case.state = "closed"
        else:
            # A later ruled entry attests the effects applied, when the ruling's
            # entry left any prepared; the case stays open.
            if prepared:
                self._record(case, self.authority.account, "ruled", basis=case.ruling.basis,
                             outcome=deepcopy(case.outcome))
            case.state = "open"
        self.rules.set_waiting(case.rule_id, case.case_ref, False)
        return True

    @staticmethod
    def _payment_event(item: dict[str, Any], case_ref: str) -> dict[str, Any]:
        # A rule's effects are reverses alone (``rules.py``).
        effect = item["effect"]
        return {"kind": "reverse", "part": effect["part"], "amount": effect["amount"],
                "payload": {"case_ref": case_ref, "effect_id": item["id"]}}

    def _lift(self, case: Case) -> bool:
        """Lift this case's extensions, and no other case's; ``False`` if payments stopped it."""

        for part in case.parts:
            if part["status"] != "held" or part["part"] in case.lifted:
                continue
            try:
                self.payments.submit_event(
                    case.transaction, {"kind": "lift", "part": part["part"],
                                       "ref": part["extension_ref"],
                                       "payload": {"case_ref": case.case_ref}},
                    request_id=f"mediation:{case.case_ref}:lift:{part['part']}")
            except PaymentsAPIError as error:
                # An extension payments already closed, at its cap, needs no lift.
                if error.code != "extension_closed":
                    return False
            except PaymentsError:
                return False
            case.lifted.add(part["part"])
        return True

    def _record(self, case: Case, actor: str, kind: str, **fields: Any) -> dict[str, Any]:
        records = self._records.setdefault(case.agreement, [])
        sequence = len(records) + 1
        entry = {"agreement": case.agreement, "transaction": case.transaction,
                 "case_ref": case.case_ref, "sequence": sequence,
                 "record_ref": f"{case.agreement[:16]}:{sequence}", "actor": actor,
                 "at": self._clock(), "parts": deepcopy(case.parts), "issuer": self._issuer,
                 "kind": kind, **fields}
        proof = SignatureProof.from_bytes(self._signer.identity.scheme,
                                          self._signer.sign(record_message(entry)))
        signed = {"entry": entry, "proof": proof.model_dump(mode="json")}
        records.append(signed)
        return deepcopy(signed)

    def _parties_of(self, transaction: str) -> _Parties:
        # A transaction's parties never change, so a read made outside the
        # service's lock, as the fault classifier makes one, may be cached.
        with self._cache_lock:
            known = self._parties.get(transaction)
        if known is None:
            receipt = self._snapshot(transaction)["receipt"]["receipt"]
            known = _Parties(payer=receipt["from"], payee=receipt["to"],
                             parts=len(receipt["parts"]), deal=receipt["deal"])
            with self._cache_lock:
                self._parties[transaction] = known
        return known

    def _snapshot(self, transaction: str) -> dict[str, Any]:
        signed = self.payments.get_transaction(transaction)
        snapshot: dict[str, Any] = signed.model_dump(
            mode="json", by_alias=True, exclude_unset=True)["snapshot"]
        return snapshot

    def _properties(self, request: FaultRequest) -> dict[str, str]:
        """The properties of an API request a rule can match, before the app reads it."""

        operation = {("POST", "/cases"): "file", ("POST", "/append"): "append",
                     ("GET", "/record"): "record", ("GET", "/respondent"): "respondent",
                     }.get((request.method, request.path))
        if operation is None and request.method == "GET" and request.path.startswith("/cases/"):
            operation = "case"
        if operation is None:
            return {}
        try:
            body = json.loads(request.body) if request.body else {}
        except ValueError:
            body = {}
        if not isinstance(body, dict):
            body = {}
        if operation == "file" and isinstance(body.get("request"), dict):
            # Which party files is the transaction's, not the request's. The
            # classifier runs before the app, on the middleware's worker thread,
            # so the parties of a transaction the double has not yet read are
            # read here, never under the service's lock. An unreadable
            # transaction leaves the filer unmatched.
            transaction = str(body.get("transaction", ""))
            filer = ""
            try:
                if self.rules.matches_on("filer"):
                    actor = self.authenticate(request.headers.get("authorization"))
                    parties = self._parties_of(transaction)
                    filer = ("payer" if actor == parties.payer
                             else "payee" if actor == parties.payee else "")
            except (ApiRefusal, PaymentsError, ValueError):
                # A malformed transaction is the app's to refuse, as invalid.
                pass
            properties = _claim_properties("file", filer, transaction, body["request"])
            return {key: value for key, value in properties.items() if value}
        reference = (str(body.get("case_ref", "")) if operation == "append"
                     else unquote(request.path.removeprefix("/cases/")) if operation == "case"
                     else "")
        case = self._cases.get(reference)
        return _case_properties(operation, case) if case is not None else {"operation": operation}

    def _open_case(self, case_ref: str) -> Case:
        case = self._cases.get(case_ref)
        if case is None:
            raise ControlError(404, "case_not_found", f"no case {case_ref}")
        if case.state == "closed":
            raise ControlError(409, "case_closed", f"case {case_ref} is closed")
        return case

    def _replay(self, actor: str, key: str, path: str,
                payload: dict[str, Any]) -> dict[str, Any] | None:
        prior = self._replays.get((actor, key, path))
        if prior is None:
            return None
        if prior[0] != canonical_json(payload):
            return _failure("idempotency_conflict", "the key was used for another request")
        return deepcopy(prior[1])

    def _remember(self, actor: str, key: str, path: str, payload: dict[str, Any],
                  answer: dict[str, Any]) -> dict[str, Any]:
        self._replays[(actor, key, path)] = (canonical_json(payload), deepcopy(answer))
        return answer

    def _new_ref(self) -> str:
        self._next += 1
        return f"case-{self._prefix}-{self._next}"


def _claim_properties(operation: str, filer: str, transaction: str,
                      request: Mapping[str, Any]) -> dict[str, str]:
    properties = {"operation": operation, "filer": filer, "transaction": transaction,
                  "kind": str(request.get("kind", ""))}
    if "cause" in request:
        properties["cause"] = str(request["cause"])
    return properties


def _case_properties(operation: str, case: Case) -> dict[str, str]:
    return _claim_properties(operation, case.filer, case.transaction, case.request)


def _key(value: str | None) -> str:
    if value is None or not _KEY.fullmatch(value):
        raise ApiRefusal(400, "invalid_request")
    return value


def _payload(body: bytes, definition: str) -> dict[str, Any]:
    try:
        payload = json.loads(body)
        validate(definition, payload)
    except (ValueError, SchemaValidationError):
        raise ApiRefusal(400, "invalid_request") from None
    assert isinstance(payload, dict)
    return payload


def _failure(code: str, message: str) -> dict[str, Any]:
    return {"status": "error", "code": code, "message": message}
