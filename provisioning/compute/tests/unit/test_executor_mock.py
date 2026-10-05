from __future__ import annotations

import asyncio

import pytest

from compute_provisioning.route_errors import ProvisioningRouteError
from compute_provisioning.jobs.executor_mock import (
    MockRule,
    MockRuleRouteService,
    MockRuleSet,
)


def test_first_matching_rule_wins_and_an_empty_match_catches_all() -> None:
    rules = MockRuleSet()
    rules.add(MockRule(rule_id="grant", match={"action": "grant"}))
    rules.add(MockRule(rule_id="any", match={}))

    assert rules.find({"action": "grant", "host_id": "h1"}).rule_id == "grant"
    assert rules.find({"action": "reclaim"}).rule_id == "any"


def test_a_rule_needs_every_match_entry_equal() -> None:
    rules = MockRuleSet()
    rules.add(MockRule(rule_id="h1", match={"action": "grant", "host_id": "h1"}))

    assert rules.find({"action": "grant", "host_id": "h2"}) is None
    assert rules.find({"action": "grant"}) is None


def test_a_rule_without_an_id_gets_one() -> None:
    rule = MockRuleSet().add(MockRule(match={}))

    assert rule.rule_id


def test_rules_listed_in_insertion_order_report_their_pause_state() -> None:
    rules = MockRuleSet()
    rules.add(MockRule(rule_id="a", match={}, pause_before_result=True))
    rules.add(MockRule(rule_id="b", match={}, result_stdout="out"))

    listed = rules.list()

    assert [rule["rule_id"] for rule in listed] == ["a", "b"]
    assert listed[0]["paused"] is True
    assert listed[0]["waiting"] == 0
    assert listed[1]["result_stdout"] is True
    assert rules.resume("a") is True
    assert rules.list()[0]["paused"] is False
    assert rules.resume("b") is False
    assert rules.resume("missing") is False


@pytest.mark.asyncio
async def test_hold_waits_until_the_rule_is_resumed() -> None:
    rules = MockRuleSet()
    rule = rules.add(MockRule(rule_id="gate", match={}, pause_before_result=True))
    held = asyncio.create_task(rules.hold(rule))
    await asyncio.wait_for(rules.wait_until_held("gate"), timeout=1.0)
    assert not held.done()

    rules.resume("gate")
    await asyncio.wait_for(held, timeout=1.0)
    assert rule.waiting == 0


@pytest.mark.asyncio
async def test_the_gate_signal_counts_every_held_job() -> None:
    rules = MockRuleSet()
    rule = rules.add(MockRule(rule_id="gate", match={}, pause_before_result=True))
    held = [asyncio.create_task(rules.hold(rule)) for _ in range(2)]

    assert await asyncio.wait_for(rules.wait_until_held("gate", count=2), timeout=1.0) == 2
    assert rules.list()[0]["waiting"] == 2

    rules.resume("gate")
    await asyncio.wait_for(asyncio.gather(*held), timeout=1.0)
    assert rules.list()[0]["waiting"] == 0


@pytest.mark.asyncio
async def test_a_job_meeting_an_open_gate_is_not_counted_as_held() -> None:
    rules = MockRuleSet()
    rule = rules.add(MockRule(rule_id="gate", match={}, pause_before_result=True))
    rules.resume("gate")

    await asyncio.wait_for(rules.hold(rule), timeout=1.0)

    assert rules.list()[0]["waiting"] == 0


@pytest.mark.asyncio
async def test_waiting_for_a_rule_without_a_gate_is_refused() -> None:
    rules = MockRuleSet()
    rules.add(MockRule(rule_id="open", match={}))

    with pytest.raises(LookupError):
        await rules.wait_until_held("open")
    with pytest.raises(LookupError):
        await rules.wait_until_held("missing")
    with pytest.raises(ValueError):
        await rules.wait_until_held("open", count=0)


@pytest.mark.asyncio
async def test_removing_a_rule_fails_a_wait_for_its_gate() -> None:
    rules = MockRuleSet()
    rules.add(MockRule(rule_id="gate", match={}, pause_before_result=True))
    waiter = asyncio.create_task(rules.wait_until_held("gate"))
    # One loop turn lets the waiter reach its wait; nothing depends on timing.
    await asyncio.sleep(0)

    rules.delete("gate")

    with pytest.raises(LookupError):
        await asyncio.wait_for(waiter, timeout=1.0)


@pytest.mark.asyncio
async def test_hold_returns_at_once_without_a_gate() -> None:
    rules = MockRuleSet()
    await asyncio.wait_for(rules.hold(None), timeout=1.0)
    await asyncio.wait_for(rules.hold(rules.add(MockRule(match={}))), timeout=1.0)


def test_evaluate_reports_host_rule_and_missing_parameters() -> None:
    rules = MockRuleSet()
    rules.add(MockRule(rule_id="gate", match={"action": "grant"}, pause_before_result=True))
    hosts = {"h1": object()}

    known = rules.evaluate(
        {"action": "grant"}, host_id="h1", host_lookup=hosts.get, required=("action",)
    )
    unknown = rules.evaluate(
        {}, host_id="h2", host_lookup=hosts.get, required=("action",)
    )

    assert known == {
        "params_valid": True,
        "host_exists": True,
        "rule_matched": "gate",
        "would_pause": True,
        "errors": [],
    }
    assert unknown["params_valid"] is False
    assert unknown["host_exists"] is False
    assert unknown["rule_matched"] is None
    assert len(unknown["errors"]) == 2


def test_evaluate_reports_a_failing_host_lookup() -> None:
    def broken(_host_id: str):
        raise RuntimeError("registry down")

    report = MockRuleSet().evaluate({}, host_id="h1", host_lookup=broken)

    assert report["params_valid"] is False
    assert "registry down" in report["errors"][0]


def test_route_service_drives_its_own_rule_set() -> None:
    rules = MockRuleSet()
    routes = MockRuleRouteService(lambda: rules)

    added = routes.add({"rule_id": "r", "match": {"action": "grant"}})

    assert added == {"rule_id": "r", "status": "added"}
    assert routes.list()[0]["match"] == {"action": "grant"}
    assert routes.delete("r") == {"rule_id": "r", "deleted": True}
    assert routes.delete("r") == {"rule_id": "r", "deleted": False}


def test_route_service_refuses_resume_of_a_rule_without_a_gate() -> None:
    rules = MockRuleSet()
    routes = MockRuleRouteService(lambda: rules)
    routes.add({"rule_id": "gated", "match": {}, "pause_before_result": True})
    routes.add({"rule_id": "open", "match": {}})

    assert routes.resume("gated") == {"rule_id": "gated", "resumed": True}
    with pytest.raises(ProvisioningRouteError) as refused:
        routes.resume("open")
    assert refused.value.status_code == 404


def test_route_service_without_an_active_mock_is_unavailable() -> None:
    routes = MockRuleRouteService(lambda: None)

    with pytest.raises(ProvisioningRouteError) as refused:
        routes.list()
    assert refused.value.status_code == 503


@pytest.mark.asyncio
async def test_the_release_signal_waits_for_every_held_job_to_leave() -> None:
    rules = MockRuleSet()
    rule = rules.add(MockRule(rule_id="gate", match={}, pause_before_result=True))
    held = [asyncio.create_task(rules.hold(rule)) for _ in range(2)]
    await asyncio.wait_for(rules.wait_until_held("gate", count=2), timeout=1.0)

    released = asyncio.create_task(rules.wait_until_released("gate"))
    held[0].cancel()
    await asyncio.wait_for(rules.wait_until_held("gate", count=1), timeout=1.0)
    assert not released.done()

    held[1].cancel()
    await asyncio.wait_for(released, timeout=1.0)
    assert rules.list()[0]["waiting"] == 0


@pytest.mark.asyncio
async def test_the_release_signal_returns_at_once_for_a_rule_holding_nothing() -> None:
    rules = MockRuleSet()
    rules.add(MockRule(rule_id="gate", match={}, pause_before_result=True))

    await asyncio.wait_for(rules.wait_until_released("gate"), timeout=1.0)
    await asyncio.wait_for(rules.wait_until_released("unknown"), timeout=1.0)
