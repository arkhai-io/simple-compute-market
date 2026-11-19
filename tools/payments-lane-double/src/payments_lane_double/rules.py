"""The double's programmed rules: refusals and transport faults a scenario installs.

A rule matches a call on the properties a scenario can name: the API ``route``,
the authenticated ``account``, an event's kind as ``event``, and the
``transaction``. Two layers read the rules. The transport-fault middleware asks
``fault_for`` before the app runs; each API handler asks ``refuse_if_programmed``
once it has authenticated the caller. Both take the first matching rule in
install order, after any *unavailable* rule, which covers every call whatever was
installed before it; so one call meets one rule, and the layer that acts on that
rule is the one that counts the match.
"""

from __future__ import annotations

import json
import re
import threading
from dataclasses import dataclass

from pydantic import ValidationError

from lane_double_controls.middleware import Fault, FaultRequest
from lane_double_controls.models import ControlError, Rule, RuleList, RuleView
from market_arkhai_payments.errors import PaymentsAPIError
from market_arkhai_payments.models import ApiErrorCode, Mandate
from market_arkhai_payments.receipts import transaction_id

from payments_lane_double.accounts import AccountDirectory, bearer_token

_TRANSACTION = r"(?P<transaction>[0-9a-f]{64})"
# Each API route's method and path, and the name a rule's ``route`` matches.
_ROUTES = (
    ("POST", re.compile(r"/transactions"), "transactions"),
    ("GET", re.compile(rf"/transactions/{_TRANSACTION}"), "snapshot"),
    ("GET", re.compile(rf"/transactions/{_TRANSACTION}/mandate"), "mandate"),
    ("POST", re.compile(rf"/transactions/{_TRANSACTION}/attachments"), "attachments"),
    ("POST", re.compile(rf"/transactions/{_TRANSACTION}/events"), "events"),
    ("GET", re.compile(r"/balances/[^/]+"), "balances"),
)
_PUBLISHED_CODES = frozenset(code.value for code in ApiErrorCode)


@dataclass
class _Entry:
    rule: Rule
    matched: int = 0


class RuleBook:
    """The rules installed on one double, in install order, with their match counts."""

    def __init__(self, directory: AccountDirectory) -> None:
        self._directory = directory
        self._entries: dict[str, _Entry] = {}
        self._lock = threading.Lock()

    def install(self, rule: Rule) -> RuleView:
        rule.check_supported("payments")
        if rule.refusal is not None and rule.refusal.code not in _PUBLISHED_CODES:
            raise ControlError(422, "invalid_request",
                               f"{rule.refusal.code} is not a published payments error code")
        with self._lock:
            if rule.rule_id in self._entries:
                raise ControlError(409, "rule_exists", f"rule {rule.rule_id} is installed")
            entry = self._entries[rule.rule_id] = _Entry(rule)
            return _view(entry)

    def listing(self) -> RuleList:
        with self._lock:
            return RuleList(rules=[_view(entry) for entry in self._entries.values()])

    def delete(self, rule_id: str) -> None:
        with self._lock:
            if self._entries.pop(rule_id, None) is None:
                raise ControlError(404, "rule_not_found", f"no rule {rule_id} is installed")

    def fault_for(self, request: FaultRequest) -> Fault | None:
        """The transport fault a call meets, counted against its rule, or ``None``."""

        with self._lock:
            entry = self._first(self.properties(request))
            if entry is None or entry.rule.refusal is not None:
                return None
            entry.matched += 1
            return Fault.UNAVAILABLE if entry.rule.unavailable else Fault.DROP_AFTER_COMMIT

    def refuse_if_programmed(self, request: FaultRequest) -> None:
        """Raise the refusal a call's first matching rule programs, counting the match."""

        with self._lock:
            entry = self._first(self.properties(request))
            if entry is None or entry.rule.refusal is None:
                return
            entry.matched += 1
            refusal = entry.rule.refusal
        raise PaymentsAPIError(refusal.status, refusal.code)

    def properties(self, request: FaultRequest) -> dict[str, str]:
        """The properties of ``request`` a rule can match."""

        found: dict[str, str] = {}
        account = self._directory.account_for_token(
            bearer_token(request.headers.get("authorization")) or "")
        if account is not None:
            found["account"] = account
        for method, pattern, name in _ROUTES:
            match = pattern.fullmatch(request.path)
            if method == request.method and match:
                found["route"] = name
                if "transaction" in pattern.groupindex:
                    found["transaction"] = match["transaction"]
                break
        body = _json(request.body)
        if found.get("route") == "events" and isinstance(body.get("kind"), str):
            found["event"] = body["kind"]
        if found.get("route") == "transactions":
            try:
                found["transaction"] = transaction_id(Mandate.model_validate(body.get("mandate")))
            except (ValidationError, ValueError):
                pass
        return found

    def _first(self, properties: dict[str, str]) -> _Entry | None:
        entries = list(self._entries.values())
        for entry in [e for e in entries if e.rule.unavailable] + [
                e for e in entries if not e.rule.unavailable]:
            if all(properties.get(key) == value for key, value in entry.rule.match.items()):
                return entry
        return None


def _json(body: bytes) -> dict[str, object]:
    try:
        parsed = json.loads(body) if body else {}
    except ValueError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _view(entry: _Entry) -> RuleView:
    # No payments rule holds a call at a gate, so none ever waits.
    return RuleView(rule=entry.rule, matched=entry.matched, waiting=0)
