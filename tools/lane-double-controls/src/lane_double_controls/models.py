"""The wire models of the lane doubles' controls.

A scenario programs a double through when→then rules and moves it through a few
direct controls: its injected time, funding, signer rotation and a rate part's
further reservation at payments, and an operator's decision or close at
mediation. The API-credits lane's sample app
serves the time control and the status alone. Every refusal a control gives has
one body, ``{"code", "message"}``, and is raised and carried as one error,
``ControlError``, on both sides of the wire.

A rule always states its ``match``: ``{}`` is a stated scope, every call of its
double, and an absent ``match`` is refused, so a rule never matches more than its
author wrote down. Rulings and effects validate against the vendored mediation
contract, so a rule cannot program a ruling the contract does not allow.
"""

from __future__ import annotations

from typing import Annotated, Any, Literal

from jsonschema import ValidationError as SchemaValidationError
from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    model_validator,
)

from injected_time import check_instant
from market_arkhai_mediation import contract

Double = Literal["payments", "mediation"]
#: Every party serving control routes: the two doubles, and the API-credits lane's
#: sample app, which serves only the time control and the status.
ControlParty = Literal["payments", "mediation", "sample-app"]

#: The request properties each double's rules may match on. Payments matches its
#: API route (``transactions``, ``snapshot``, ``mandate``, ``attachments``,
#: ``events``, ``balances``), the authenticated account, an event's kind and the
#: transaction; mediation matches the operation, the filing party, the claim's
#: kind and cause, and the transaction.
MATCH_KEYS: dict[Double, frozenset[str]] = {
    "payments": frozenset({"route", "account", "event", "transaction"}),
    "mediation": frozenset({"operation", "filer", "kind", "cause", "transaction"}),
}

#: The actions a rule of each double may take. Filing overrides and rulings are
#: mediation's decisions; refusals and transport faults apply to both.
ACTIONS: dict[Double, frozenset[str]] = {
    "payments": frozenset({"refusal", "drop_response_after_commit", "unavailable"}),
    "mediation": frozenset({"refusal", "drop_response_after_commit", "unavailable",
                            "filing_answer", "ruling"}),
}

ControlCode = Literal[
    "invalid_request",
    "authentication_required",
    "rule_exists",
    "rule_not_found",
    "rule_not_waiting",
    "case_not_found",
    "case_closed",
    # Closing a mediation case whose ruling is not yet fully applied: the
    # contract's closed entry follows every effect's application.
    "case_applying",
    "account_not_found",
    # A control that must reach payments and could not, such as closing a
    # mediation case whose extensions payments did not lift.
    "payments_unavailable",
    # The time control's refusals, the time component's own: a body that is not
    # exactly {"now": <instant>}, and an instant earlier than the party's.
    "invalid_time",
    "time_moves_forward",
    # The payments double's reservation control's refusals: a transaction it
    # does not hold, and one with no started, unstopped rate part to reserve.
    "transaction_not_found",
    "no_running_rate_part",
]

# A rule id sits in a control route's path, so it is restricted to characters
# that need no escaping there.
RuleId = Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9._-]{1,128}$")]
MinorUnits = Annotated[str, StringConstraints(pattern=r"^[1-9][0-9]*$")]


class ControlError(Exception):
    """A control's refusal: the double raises it, and the client raises it again.

    ``status`` is the HTTP status, and ``code`` the stable reason a caller
    branches on; ``message`` says what was wrong in words.
    """

    def __init__(self, status: int, code: str, message: str) -> None:
        super().__init__(f"{status} {code}: {message}")
        self.status = status
        self.code = code
        self.message = message

    def body(self) -> dict[str, str]:
        return ControlErrorBody(code=self.code, message=self.message).model_dump()


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ControlErrorBody(_Model):
    code: str
    message: str


class Refusal(_Model):
    """Answer a matching call with this published status and error code."""

    status: Annotated[int, Field(ge=400, le=599)]
    code: Annotated[str, StringConstraints(min_length=1)]


class FilingAnswer(_Model):
    """Answer a matching filing as the contract's ``pending``, ``error`` or ``rejected``.

    ``error`` names one of the contract's mediation failure codes, and
    ``rejected`` one of its filing refusal reasons; ``pending`` names neither.
    """

    status: Literal["pending", "error", "rejected"]
    code: str | None = None
    reason: str | None = None

    @model_validator(mode="after")
    def _matches_the_contract(self) -> FilingAnswer:
        if self.status == "pending":
            if self.code is not None or self.reason is not None:
                raise ValueError("a pending answer names no code or reason")
        elif self.status == "error":
            if self.code is None or self.reason is not None:
                raise ValueError("an error answer names a code and no reason")
            _contract("MediationFailure", {"status": "error", "code": self.code, "message": ""})
        else:
            if self.reason is None or self.code is not None:
                raise ValueError("a rejected answer names a reason and no code")
            _contract("FilingRefusalCode", self.reason)
        return self


class Ruling(_Model):
    """A ruling the mediation double records and applies.

    ``basis`` is the contract's ruling basis. ``delivery_end`` true records the
    contract's delivery-end effect at the ruling's time; ``effects`` are the
    payment effects applied in order, each a contract ``Effect``, and may be
    empty: a ruling that moves no money. The delivery end is stated only by
    ``delivery_end``, never as an effect, so a ruling has one way to say it.
    ``close`` closes the case once its effects are applied.
    """

    basis: str
    delivery_end: bool
    effects: list[dict[str, Any]]
    close: bool

    @model_validator(mode="after")
    def _matches_the_contract(self) -> Ruling:
        _contract("RulingBasis", self.basis)
        for effect in self.effects:
            _contract("Effect", effect)
            if effect["kind"] == "end_delivery":
                raise ValueError("a ruling states its delivery end with delivery_end, "
                                 "not as an effect")
        return self


class Rule(_Model):
    """A when→then rule installed on one double.

    A call matches when every ``match`` entry equals the call's property of that
    name; ``{}`` matches every call. Exactly one action is given. ``unavailable``
    covers every contract API route, so its ``match`` is ``{}``: a scoped outage
    would only drop some requests before they commit, which no caller needs.
    ``pause_before_effects`` holds a matching case's ruling before its effects
    until the rule is resumed.
    """

    rule_id: RuleId
    match: dict[str, str]
    refusal: Refusal | None = None
    drop_response_after_commit: Literal[True] | None = None
    unavailable: Literal[True] | None = None
    filing_answer: FilingAnswer | None = None
    ruling: Ruling | None = None
    pause_before_effects: bool = False

    @model_validator(mode="after")
    def _one_action(self) -> Rule:
        actions = self.actions()
        if len(actions) != 1:
            raise ValueError("a rule takes exactly one action: refusal, "
                             "drop_response_after_commit, unavailable, filing_answer or ruling")
        if self.unavailable and self.match:
            raise ValueError("an unavailable rule covers every API route; its match is {}")
        if self.pause_before_effects and self.ruling is None:
            raise ValueError("only a ruling can pause before its effects")
        return self

    def actions(self) -> list[str]:
        return [name for name in ("refusal", "drop_response_after_commit", "unavailable",
                                  "filing_answer", "ruling")
                if getattr(self, name) is not None]

    def check_supported(self, double: Double) -> None:
        """Refuse, as an invalid request, a rule ``double`` cannot evaluate."""

        unknown = sorted(set(self.match) - MATCH_KEYS[double])
        if unknown:
            raise ControlError(422, "invalid_request",
                               f"the {double} double cannot match on {', '.join(unknown)}")
        unsupported = sorted(set(self.actions()) - ACTIONS[double])
        if unsupported:
            raise ControlError(422, "invalid_request",
                               f"the {double} double cannot take {', '.join(unsupported)}")


class RuleView(_Model):
    """An installed rule, how many calls it has matched, and how many wait at its gate."""

    rule: Rule
    matched: Annotated[int, Field(ge=0)]
    waiting: Annotated[int, Field(ge=0)]


class RuleList(_Model):
    rules: list[RuleView]


class TimeView(_Model):
    """A party's time: ``{"source": "injected", "now": <instant>}``, or ``{"source": "wall"}``.

    The answer to a time setting, and the time section of a status, as the time
    component's route service shapes both. ``now`` is Unix seconds, stated for
    an injected source alone; a boolean is never an instant.
    """

    source: Literal["wall", "injected"]
    # Strict, so a string, a float or a boolean is never taken for an instant;
    # the component's one rule then refuses a value out of range.
    now: Annotated[int, Field(strict=True), AfterValidator(check_instant)] | None = None

    @model_validator(mode="after")
    def _now_with_injected_time(self) -> TimeView:
        if (self.source == "injected") != (self.now is not None):
            raise ValueError("an injected time states its now, and a wall time none")
        return self


class Funding(_Model):
    """Credit ``amount`` minor units of the double's asset to ``account``."""

    account: Annotated[str, StringConstraints(min_length=1)]
    amount: MinorUnits


class Funded(_Model):
    account: str
    amount: str


#: An instant on the wire, Unix seconds: strict, so a string, a float or a boolean
#: is never taken for one, then held to the time component's range.
Instant = Annotated[int, Field(strict=True), AfterValidator(check_instant)]


class Reservation(_Model):
    """Reserve a transaction's running rate parts' further periods through ``through``.

    The payments service's scheduler decides when a started rate part is
    reserved further; at the double a scenario programs that decision.
    """

    through: Instant


class ReservedPart(_Model):
    """One running rate part a reservation reached: the instant it is then
    reserved through, as the signed snapshot reports it, and the periods added,
    which the part's end and the payer's balance may hold to zero."""

    part: Annotated[int, Field(strict=True, ge=0)]
    reserved_through: Instant
    periods_added: Annotated[int, Field(strict=True, ge=0)]


class Reserved(_Model):
    """A reservation's answer: every running rate part of ``transaction``.

    A transaction with no running rate part is refused, never answered with no
    parts, so a reservation that reached nothing cannot read as one that did.
    """

    transaction: Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
    parts: Annotated[list[ReservedPart], Field(min_length=1)]


class SignerIdentity(_Model):
    """The identity the payments double signs receipts and snapshots with."""

    scheme: str
    identifier: str


class CaseView(_Model):
    """One mediation case, as the double holds it."""

    case_ref: str
    transaction: str
    agreement: str
    state: Literal["open", "applying", "closed"]
    filer: str
    kind: str
    cause: str | None = None


class CaseList(_Model):
    cases: list[CaseView]


class Status(_Model):
    """A party's time and the contract resources it serves.

    ``contracts`` maps each installed contract resource to its SHA-256, read from
    the kit wheel the double runs, for a run's record; nothing compares them. The
    sample app serves no contract, so its mapping is empty.
    """

    time: TimeView
    contracts: dict[str, str]


def _contract(name: str, value: Any) -> None:
    try:
        contract.validate(name, value)
    except SchemaValidationError as error:
        raise ValueError(f"not a contract {name}: {error.message}") from None


__all__ = [
    "ACTIONS",
    "CaseList",
    "CaseView",
    "ControlCode",
    "ControlError",
    "ControlErrorBody",
    "ControlParty",
    "Double",
    "FilingAnswer",
    "Funded",
    "Funding",
    "MATCH_KEYS",
    "Refusal",
    "Reservation",
    "Reserved",
    "ReservedPart",
    "Rule",
    "RuleList",
    "RuleView",
    "Ruling",
    "SignerIdentity",
    "Status",
    "TimeView",
]
