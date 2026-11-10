"""The double's programmed rules: every decision the authority would make.

A rule matches a call on the properties a scenario can name: the ``operation``
(``file``, ``append``, ``case``, ``record``, ``respondent``), the case's ``filer``
(``payer`` or ``payee``), its claim's ``kind`` and ``cause``, and its
``transaction``. Two layers read the rules, as in the payments double: the
transport-fault middleware acts on a drop or *unavailable* match before the app
runs; the service acts on a refusal, a filing answer or a ruling. Both take the
first matching rule in install order, after any *unavailable* rule, so one call
meets one rule and the layer that acts on it counts the match.

A ruling's case waits on its rule while the ruling is held at the rule's gate or
its application stopped part-way; resuming the rule continues each such case.
"""

from __future__ import annotations

import re
import threading
from dataclasses import dataclass, field

from lane_double_controls.models import ControlError, Rule, RuleList, RuleView
from market_arkhai_mediation.contract import schema

# The refusal codes the authority publishes, which a refusal rule answers with.
_PUBLISHED_CODES = frozenset(schema()["$defs"]["MediationFailure"]["properties"]["code"]["enum"])
# The effects the double applies, each to one part as one payment event. A stop and
# a penalty act on rate parts (a stop's partial period and time against payments'
# own now; a penalty's reverse of earned amounts still held, across parts in
# mandate order), which no lane running the double has, so each is refused rather
# than applied untested; the contract makes an award unexecutable on payments v1.
_APPLIED_EFFECTS = frozenset({"reverse"})
# What each match property may equal; any other value could never match.
_MATCH_VALUES = {
    "filer": frozenset({"payer", "payee"}),
    "kind": frozenset({"delivery_end", "effects"}),
    "cause": frozenset({"payer", "payee"}),
}
_TRANSACTION = re.compile(r"^[0-9a-f]{64}$")
#: The API operations a rule's ``operation`` names.
OPERATIONS = ("file", "append", "case", "record", "respondent")
_ALL_ACTIONS = frozenset({"refusal", "drop_response_after_commit", "unavailable",
                          "filing_answer", "ruling"})
_READ_ACTIONS = frozenset({"refusal", "drop_response_after_commit", "unavailable"})
# The actions a call of each operation can take: a filing answer answers a
# filing, and a ruling rules the case a filing or an append reaches.
_APPLICABLE = {
    "file": _ALL_ACTIONS,
    "append": _READ_ACTIONS | {"ruling"},
    "case": _READ_ACTIONS,
    "record": _READ_ACTIONS,
    "respondent": _READ_ACTIONS,
}


@dataclass
class Entry:
    rule: Rule
    matched: int = 0
    #: The cases whose ruling waits on this rule.
    waiting: set[str] = field(default_factory=set)


class RuleBook:
    """The rules installed on the double, in install order, with their counts."""

    def __init__(self) -> None:
        self._entries: dict[str, Entry] = {}
        self._lock = threading.Lock()

    def install(self, rule: Rule) -> RuleView:
        rule.check_supported("mediation")
        _check_acts(rule)
        if rule.refusal is not None and rule.refusal.code not in _PUBLISHED_CODES:
            raise ControlError(422, "invalid_request",
                               f"{rule.refusal.code} is not a published mediation error code")
        if rule.ruling is not None:
            unapplied = sorted({effect["kind"] for effect in rule.ruling.effects}
                               - _APPLIED_EFFECTS)
            if unapplied:
                raise ControlError(422, "invalid_request",
                                   f"the mediation double applies reverse effects, "
                                   f"not {', '.join(unapplied)}")
        with self._lock:
            if rule.rule_id in self._entries:
                raise ControlError(409, "rule_exists", f"rule {rule.rule_id} is installed")
            entry = self._entries[rule.rule_id] = Entry(rule)
            return _view(entry)

    def listing(self) -> RuleList:
        with self._lock:
            return RuleList(rules=[_view(entry) for entry in self._entries.values()])

    def view(self, rule_id: str) -> RuleView:
        with self._lock:
            return _view(self._get(rule_id))

    def delete(self, rule_id: str) -> None:
        with self._lock:
            if self._entries.pop(rule_id, None) is None:
                raise ControlError(404, "rule_not_found", f"no rule {rule_id} is installed")

    def waiting(self, rule_id: str) -> list[str]:
        """The cases waiting on ``rule_id``, refusing a rule with none."""

        with self._lock:
            entry = self._get(rule_id)
            if not entry.waiting:
                raise ControlError(409, "rule_not_waiting",
                                   f"no case waits on rule {rule_id}")
            return sorted(entry.waiting)

    def first(self, properties: dict[str, str]) -> Entry | None:
        """The first rule ``properties`` match, an *unavailable* rule before any other.

        A rule whose action the call's operation cannot take, such as a ruling on
        a read, is passed over, so it neither counts nor hides a later rule.
        """

        applicable = _APPLICABLE.get(properties.get("operation", ""), _ALL_ACTIONS)
        with self._lock:
            entries = [entry for entry in self._entries.values()
                       if entry.rule.actions()[0] in applicable]
            for entry in [e for e in entries if e.rule.unavailable] + [
                    e for e in entries if not e.rule.unavailable]:
                if all(properties.get(key) == value for key, value in entry.rule.match.items()):
                    return entry
            return None

    def matches_on(self, key: str) -> bool:
        """Whether any installed rule matches on the property ``key``."""

        with self._lock:
            return any(key in entry.rule.match for entry in self._entries.values())

    def count(self, entry: Entry) -> None:
        with self._lock:
            entry.matched += 1

    def set_waiting(self, rule_id: str | None, case_ref: str, waiting: bool) -> None:
        """Record whether ``case_ref`` waits on ``rule_id``, which may have been deleted."""

        if rule_id is None:
            return
        with self._lock:
            entry = self._entries.get(rule_id)
            if entry is not None:
                (entry.waiting.add if waiting else entry.waiting.discard)(case_ref)

    def _get(self, rule_id: str) -> Entry:
        entry = self._entries.get(rule_id)
        if entry is None:
            raise ControlError(404, "rule_not_found", f"no rule {rule_id} is installed")
        return entry


def _check_acts(rule: Rule) -> None:
    """Refuse a rule that could never act, rather than install it to match nothing."""

    for key, allowed in _MATCH_VALUES.items():
        if key in rule.match and rule.match[key] not in allowed:
            raise ControlError(422, "invalid_request",
                               f"{key} is one of {', '.join(sorted(allowed))}")
    if "transaction" in rule.match and not _TRANSACTION.fullmatch(rule.match["transaction"]):
        raise ControlError(422, "invalid_request", "transaction is a transaction's id")
    operation = rule.match.get("operation")
    if operation is not None and operation not in OPERATIONS:
        raise ControlError(422, "invalid_request",
                           f"operation is one of {', '.join(OPERATIONS)}, not {operation}")
    if rule.filing_answer is not None and operation not in (None, "file"):
        raise ControlError(422, "invalid_request", "a filing answer answers a filing")
    if rule.ruling is not None and operation not in (None, "file", "append"):
        raise ControlError(422, "invalid_request", "a ruling rules a filed or appended case")
    if operation in ("record", "respondent") and set(rule.match) - {"operation"}:
        # A record or respondent read names no case, so nothing else of it matches.
        raise ControlError(422, "invalid_request",
                           f"a {operation} read matches on its operation alone")


def _view(entry: Entry) -> RuleView:
    return RuleView(rule=entry.rule, matched=entry.matched, waiting=len(entry.waiting))
