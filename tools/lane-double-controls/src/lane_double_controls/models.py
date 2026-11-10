"""The wire models of the lane doubles' controls.

A scenario programs a double through when→then rules and moves it through a few
direct controls: the perceived clock, funding and signer rotation at payments,
and an operator's decision or close at mediation. Every refusal a control gives
has one body, ``{"code", "message"}``, and is raised and carried as one error,
``ControlError``, on both sides of the wire.

A rule always states its ``match``: ``{}`` is a stated scope, every call of its
double, and an absent ``match`` is refused, so a rule never matches more than its
author wrote down. Rulings and effects validate against the vendored mediation
contract, so a rule cannot program a ruling the contract does not allow.
"""

from __future__ import annotations

from typing import Annotated, Any, Literal

from jsonschema import ValidationError as SchemaValidationError
from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from market_arkhai_mediation import contract

Double = Literal["payments", "mediation"]

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


class ClockAdvance(_Model):
    seconds: Annotated[int, Field(gt=0)]


class ClockView(_Model):
    """A double's perceived now, in Unix seconds, and its offset from wall time."""

    perceived_now: int
    offset_seconds: Annotated[int, Field(ge=0)]


class Funding(_Model):
    """Credit ``amount`` minor units of the double's asset to ``account``."""

    account: Annotated[str, StringConstraints(min_length=1)]
    amount: MinorUnits


class Funded(_Model):
    account: str
    amount: str


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
    """A double's perceived clock and the contract resources it serves.

    ``contracts`` maps each installed contract resource to its SHA-256, read from
    the kit wheel the double runs, for a run's record; nothing compares them.
    """

    perceived_now: int
    offset_seconds: Annotated[int, Field(ge=0)]
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
    "ClockAdvance",
    "ClockView",
    "ControlCode",
    "ControlError",
    "ControlErrorBody",
    "Double",
    "FilingAnswer",
    "Funded",
    "Funding",
    "MATCH_KEYS",
    "Refusal",
    "Rule",
    "RuleList",
    "RuleView",
    "Ruling",
    "SignerIdentity",
    "Status",
]
