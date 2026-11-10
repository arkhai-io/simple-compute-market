"""A module's rules and clock advances on the lane's doubles are undone when it ends.

Each double is stood in for by a small in-memory control surface behind an
httpx mock transport, so the controls package's typed client sends exactly the
requests a module's fixtures send. The cleanup is driven through the context
managers the module fixtures run, after a body that fails as a failing module
does. Every value below is a development fixture, never used on any network.
"""

from __future__ import annotations

import json

import httpx
import pytest
from lane_double_controls import ClockView, ControlClient, Rule, RuleList, RuleView, Status
from lane_double_controls.models import ControlErrorBody

from tests.e2e.roles.helpers.cleanup import CleanupFailed
from tests.e2e.roles.helpers.lane_doubles import (
    LaneDoubleClock, clocks_reset_after, rules_removed_after,
)

_TOKEN = "lane-double-control-public-development-token"
_WALL = 1_800_000_000


class FakeDouble:
    """A double's rule book and perceived clock, as its control routes answer."""

    def __init__(self, *, stuck_offset: int = 0, listing_fails: bool = False) -> None:
        self.rules: dict[str, RuleView] = {}
        self.offset = 0
        self.deleted: list[str] = []
        # An offset a reset leaves in place, as a broken double would.
        self.stuck_offset = stuck_offset
        # A rule listing answered with a server error, as a failing double would.
        self.listing_fails = listing_fails

    def hold(self, rule_id: str) -> None:
        """A case reaches the rule's gate and waits there."""
        view = self.rules[rule_id]
        self.rules[rule_id] = view.model_copy(update={"matched": 1, "waiting": 1})

    def client(self) -> ControlClient:
        return ControlClient("https://double.test", token=_TOKEN,
                             transport=httpx.MockTransport(self._answer))

    def _answer(self, request: httpx.Request) -> httpx.Response:
        assert request.headers["authorization"] == f"Bearer {_TOKEN}"
        route = (request.method, request.url.path)
        if route == ("POST", "/test/rules"):
            rule = Rule.model_validate(json.loads(request.content))
            self.rules[rule.rule_id] = RuleView(rule=rule, matched=0, waiting=0)
            return httpx.Response(201, json=self.rules[rule.rule_id].model_dump(mode="json"))
        if route == ("GET", "/test/rules"):
            if self.listing_fails:
                return httpx.Response(500, text="internal error")
            listing = RuleList(rules=list(self.rules.values()))
            return httpx.Response(200, json=listing.model_dump(mode="json"))
        if request.method == "DELETE" and request.url.path.startswith("/test/rules/"):
            rule_id = request.url.path.removeprefix("/test/rules/")
            if self.rules.pop(rule_id, None) is None:
                body = ControlErrorBody(code="rule_not_found", message=f"no rule {rule_id}")
                return httpx.Response(404, json=body.model_dump())
            self.deleted.append(rule_id)
            return httpx.Response(204)
        if route == ("POST", "/test/clock/advance"):
            self.offset += json.loads(request.content)["seconds"]
            return httpx.Response(200, json=self._clock().model_dump(mode="json"))
        if route == ("POST", "/test/clock/reset"):
            self.offset = self.stuck_offset
            return httpx.Response(200, json=self._clock().model_dump(mode="json"))
        if route == ("GET", "/test/status"):
            status = Status(perceived_now=_WALL + self.offset, offset_seconds=self.offset,
                            contracts={})
            return httpx.Response(200, json=status.model_dump(mode="json"))
        raise AssertionError(f"no control route {route}")

    def _clock(self) -> ClockView:
        return ClockView(perceived_now=_WALL + self.offset, offset_seconds=self.offset)


class ModuleFailed(Exception):
    """A module's failure, raised from inside the body the cleanup wraps."""


def _rule(rule_id: str) -> Rule:
    return Rule.model_validate({"rule_id": rule_id, "match": {}, "unavailable": True})


def test_every_rule_a_failing_module_installed_is_deleted_on_both_doubles() -> None:
    payments, mediation = FakeDouble(), FakeDouble()

    with pytest.raises(ModuleFailed):
        with rules_removed_after({"payments": payments.client(),
                                  "mediation": mediation.client()}) as rules:
            rules.install("payments", _rule("payments-outage"))
            rules.install("mediation", _rule("mediation-outage"))
            raise ModuleFailed

    assert (payments.rules, mediation.rules) == ({}, {})
    assert (payments.deleted, mediation.deleted) == (["payments-outage"], ["mediation-outage"])


def test_a_rule_the_module_deleted_itself_is_not_deleted_again() -> None:
    payments, mediation = FakeDouble(), FakeDouble()

    with rules_removed_after({"payments": payments.client(),
                              "mediation": mediation.client()}) as rules:
        rules.install("mediation", _rule("dropped"))
        rules.install("mediation", _rule("kept"))
        rules.delete("mediation", "dropped")

    assert mediation.deleted == ["dropped", "kept"]
    assert mediation.rules == {}


def test_a_rule_left_holding_a_case_is_named_after_every_rule_is_deleted() -> None:
    payments, mediation = FakeDouble(), FakeDouble()

    with pytest.raises(pytest.fail.Exception, match="mediation rule gated.*1 waiting"):
        with rules_removed_after({"payments": payments.client(),
                                  "mediation": mediation.client()}) as rules:
            rules.install("payments", _rule("payments-outage"))
            rules.install("mediation", _rule("gated"))
            mediation.hold("gated")
            raise ModuleFailed

    assert (payments.rules, mediation.rules) == ({}, {})


def test_an_unreadable_listing_still_leaves_no_rule_installed() -> None:
    payments, mediation = FakeDouble(listing_fails=True), FakeDouble()

    with pytest.raises(CleanupFailed, match="read the payments double's rules"):
        with rules_removed_after({"payments": payments.client(),
                                  "mediation": mediation.client()}) as rules:
            rules.install("payments", _rule("payments-outage"))
            rules.install("mediation", _rule("mediation-outage"))

    assert (payments.rules, mediation.rules) == ({}, {})


def test_the_clock_advances_both_doubles_together() -> None:
    payments, mediation = FakeDouble(), FakeDouble()
    clock = LaneDoubleClock({"payments": payments.client(), "mediation": mediation.client()})

    nows = clock.advance(3600)

    assert nows == {"payments": _WALL + 3600, "mediation": _WALL + 3600}
    assert (payments.offset, mediation.offset) == (3600, 3600)


def test_both_clocks_are_reset_after_a_failing_module() -> None:
    payments, mediation = FakeDouble(), FakeDouble()

    with pytest.raises(ModuleFailed):
        with clocks_reset_after({"payments": payments.client(),
                                 "mediation": mediation.client()}) as clock:
            clock.advance(8 * 86_400)
            raise ModuleFailed

    assert (payments.offset, mediation.offset) == (0, 0)


def test_a_double_that_keeps_an_offset_after_its_reset_is_named() -> None:
    payments, mediation = FakeDouble(), FakeDouble(stuck_offset=60)

    with pytest.raises(pytest.fail.Exception, match=r"mediation \(60s ahead\)"):
        with clocks_reset_after({"payments": payments.client(),
                                 "mediation": mediation.client()}) as clock:
            clock.advance(60)

    assert payments.offset == 0
