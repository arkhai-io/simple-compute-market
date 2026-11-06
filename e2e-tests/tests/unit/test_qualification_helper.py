"""The qualification scenarios' admission-log reader and per-observation outcome."""

from __future__ import annotations

import copy
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest
import yaml

from e2e_harness.real_provisioning_target import SECTION, load_real_provisioning_target
from tests.e2e.roles.helpers.qualification import (
    REPORTS,
    StageResult,
    admission_decisions,
    check_admission,
    log_observation_outcomes,
    observation_outcomes,
    record_report,
    relay_lease_record,
    require_admitted,
    run_stage,
    stage_result,
)
from tests.unit.test_real_provisioning_target import EXAMPLE

E2E_ROOT = Path(__file__).resolve().parents[2]

RELAY = "example-bm-relay"
RESERVATION = "reservation-7"
PORT = 6101
# Invented key ids: the lease's latest grant was signed by GRANT_KEY; the relay
# has since rotated to ACTIVE_KEY, and RETIRED_KEY signed an earlier grant.
GRANT_KEY = "kid-grant"
ACTIVE_KEY = "kid-active"
RETIRED_KEY = "kid-retired"


def _record(**overrides):
    fields = dict(
        lease_id="lease-1", remote_port=PORT, host_id="example-bm-1", owner_kind="fulfillment",
        owner_id=RESERVATION, allocated_at=datetime(2027, 1, 1, tzinfo=timezone.utc),
        released_at=None, grant_key_id=GRANT_KEY,
    )
    fields.update(overrides)
    return SimpleNamespace(**fields)


def _line(**overrides) -> str:
    decision = {"ts": "2027-01-01T00:00:00Z", "event": "admit", "proxy": "tenant", "type": "tcp",
                "remote_port": PORT, "issuer": "relay", "kid": GRANT_KEY, "sub": "example-bm-1",
                "jti": RESERVATION, "exp": 1798765200, "verified": True}
    decision.update(overrides)
    return json.dumps(decision)


# ---------------------------------------------------------------------------
# Grant admission
# ---------------------------------------------------------------------------

def test_the_latest_grants_admit_is_found():
    lines = [_line(event="refuse", reason="port_outside_range", jti="other"), _line()]
    assert require_admitted(lines, _record(), relay_id=RELAY)["kid"] == GRANT_KEY


def test_an_admit_under_the_relays_newer_active_key_is_not_the_leases():
    with pytest.raises(AssertionError) as error:
        require_admitted([_line(kid=ACTIVE_KEY)], _record(), relay_id=RELAY)
    assert "lease lease-1" in str(error.value) and ACTIVE_KEY in str(error.value)


def test_an_earlier_admit_under_a_retired_key_is_ignored_beside_the_latest():
    lines = [_line(kid=RETIRED_KEY, ts="2026-12-31T23:00:00Z"), _line()]
    admitted = require_admitted(lines, _record(), relay_id=RELAY)
    assert admitted["kid"] == GRANT_KEY and admitted["ts"] == "2027-01-01T00:00:00Z"


@pytest.mark.parametrize("lines", [
    [],
    [_line(verified=False)],
    [_line(event="refuse", reason="expired")],
    [_line(jti="reservation-8")],
    [_line(remote_port=PORT + 1)],
    [_line(remote_port=str(PORT))],
    [_line(kid=RETIRED_KEY)],
], ids=["missing", "unverified", "refused", "other-reservation", "other-port", "port-as-text", "other-key"])
def test_no_matching_admit_fails_naming_the_lease(lines):
    with pytest.raises(AssertionError) as error:
        require_admitted(lines, _record(), relay_id=RELAY)
    text = str(error.value)
    assert "lease lease-1" in text and RESERVATION in text and str(PORT) in text and GRANT_KEY in text


def test_a_lease_with_no_signed_grant_fails_naming_it():
    with pytest.raises(AssertionError, match="lease lease-1 .* records no signed grant"):
        require_admitted([_line()], _record(grant_key_id=None), relay_id=RELAY)


def test_lines_that_are_not_decisions_are_skipped():
    lines = ['{"event":"config_loaded","trigger":"startup"}', "not json", '{"event":"adm', _line()]
    assert [decision["event"] for decision in admission_decisions(lines)] == ["admit"]


def _holdings(*leases):
    return SimpleNamespace(list_relay_leases=lambda relay_id: SimpleNamespace(
        relay_id=relay_id, leases=list(leases)))


def test_the_lease_record_is_the_reservations_unreleased_port():
    released = _record(lease_id="lease-0", released_at=datetime(2027, 1, 1, tzinfo=timezone.utc))
    other = _record(lease_id="lease-2", owner_id="reservation-8", remote_port=PORT + 1)
    record = relay_lease_record(_holdings(released, other, _record()), RELAY, RESERVATION)
    assert record.lease_id == "lease-1"


def test_no_unreleased_port_for_the_reservation_fails_naming_it():
    with pytest.raises(AssertionError, match=f"0 unreleased ports for reservation '{RESERVATION}'"):
        relay_lease_record(_holdings(_record(owner_id="reservation-8")), RELAY, RESERVATION)


def _target(admission_log=None, mode="relay"):
    section = yaml.safe_load(EXAMPLE.read_text())[SECTION]
    section = copy.deepcopy(section)
    access = section["hosts"][1]["access"]
    if mode == "direct":
        section["hosts"][1]["access"] = {"mode": "direct", "public_host": "192.0.2.1"}
    elif admission_log is not None:
        access["admission_log"] = admission_log
    return load_real_provisioning_target({SECTION: section}).host_for("bare_metal")


def test_check_admission_reads_the_target_named_log(tmp_path):
    log_file = tmp_path / "frps-admission.log"
    log_file.write_text(_line() + "\n")
    admitted = check_admission(_target(str(log_file)), _holdings(_record()), RESERVATION)
    assert admitted["jti"] == RESERVATION


def test_check_admission_without_the_log_skips_naming_the_field():
    with pytest.raises(pytest.skip.Exception, match="hosts.bare_metal.access.admission_log"):
        check_admission(_target(), _holdings(_record()), RESERVATION)


def test_check_admission_on_a_direct_target_has_no_relayed_lease_to_admit():
    assert check_admission(_target(mode="direct"), _holdings(), RESERVATION) is None


class _Clock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now

    def sleep(self, seconds):
        self.now += seconds


def test_check_admission_rereads_a_trailing_copy_within_its_bound(tmp_path):
    log_file = tmp_path / "frps-admission.log"
    log_file.write_text(_line(kid=RETIRED_KEY) + "\n")
    clock = _Clock()

    def sleep(seconds):
        clock.sleep(seconds)
        log_file.write_text(_line(kid=RETIRED_KEY) + "\n" + _line() + "\n")

    admitted = check_admission(_target(str(log_file)), _holdings(_record()), RESERVATION,
                               bound=10, poll_interval=2, clock=clock, sleep=sleep)
    assert admitted["kid"] == GRANT_KEY and clock.now == 2


def test_check_admission_fails_naming_the_lease_at_its_bound(tmp_path):
    log_file = tmp_path / "frps-admission.log"
    log_file.write_text(_line(verified=False) + "\n")
    clock = _Clock()
    with pytest.raises(AssertionError, match="lease lease-1"):
        check_admission(_target(str(log_file)), _holdings(_record()), RESERVATION,
                        bound=10, poll_interval=2, clock=clock, sleep=clock.sleep)
    assert clock.now == 10


def test_a_lease_with_no_grant_fails_without_rereading(tmp_path):
    log_file = tmp_path / "frps-admission.log"
    log_file.write_text(_line() + "\n")
    clock = _Clock()
    with pytest.raises(AssertionError, match="records no signed grant"):
        check_admission(_target(str(log_file)), _holdings(_record(grant_key_id=None)),
                        RESERVATION, bound=10, poll_interval=2, clock=clock, sleep=clock.sleep)
    assert clock.now == 0


def test_an_unreadable_admission_log_fails_naming_the_field_and_path(tmp_path):
    missing = str(tmp_path / "absent.log")
    with pytest.raises(AssertionError, match=f"admission_log '{missing}' cannot be read"):
        check_admission(_target(missing), _holdings(_record()), RESERVATION)


# ---------------------------------------------------------------------------
# Per-observation outcome
# ---------------------------------------------------------------------------

def _result(stage, observations, outcome, reason=""):
    return StageResult(stage, frozenset(observations), outcome, reason)


def test_observation_2_is_unproven_naming_the_management_unit_when_its_reads_skipped():
    results = [
        _result("test_purchase", {"2"}, "passed"),
        _result("test_heartbeat", {"2"}, "passed"),
        _result("test_management_reads", {"2"}, "skipped",
                f"{SECTION}.hosts.vm.management_unit is not set"),
        _result("test_admission", {"2"}, "passed"),
    ]
    (outcome,) = observation_outcomes(["2"], results)
    assert outcome.outcome == "unproven"
    assert outcome.stages == ("test_management_reads",)
    assert "management_unit" in outcome.reasons[0]


def test_observations_4_and_5_resolve_independently_in_one_module():
    results = [
        _result("test_normal_purchase", {"4"}, "passed"),
        _result("test_normal_admission", {"4"}, "passed"),
        _result("test_successor_purchase", {"5"}, "passed"),
        _result("test_refusal_observed", {"5"}, "failed"),
        _result("test_shared_readiness", {"4", "5"}, "passed"),
    ]
    four, five = observation_outcomes(["4", "5"], results)
    assert (four.observation, four.outcome) == ("4", "made")
    assert set(four.stages) == {"test_normal_purchase", "test_normal_admission", "test_shared_readiness"}
    assert (five.observation, five.outcome, five.stages) == ("5", "failed", ("test_refusal_observed",))


def test_a_failure_outranks_a_skip():
    results = [
        _result("test_admission", {"5"}, "skipped", "admission_log is not set"),
        _result("test_refusal_observed", {"5"}, "failed"),
    ]
    (outcome,) = observation_outcomes(["5"], results)
    assert (outcome.outcome, outcome.stages) == ("failed", ("test_refusal_observed",))


def test_an_observation_no_stage_ran_for_is_unproven():
    (outcome,) = observation_outcomes(["6"], [_result("test_other", {"2"}, "passed")])
    assert outcome.outcome == "unproven" and outcome.reasons == ("no stage requiring it ran",)


def _report(when, outcome, reason=""):
    return SimpleNamespace(
        when=when, failed=outcome == "failed", skipped=outcome == "skipped",
        passed=outcome == "passed",
        longrepr=("module.py", 1, f"Skipped: {reason}") if outcome == "skipped" else None,
    )


@pytest.mark.parametrize(("reports", "expected"), [
    ({"setup": _report("setup", "passed"), "call": _report("call", "passed")}, ("passed", "")),
    ({"setup": _report("setup", "passed"), "call": _report("call", "failed")}, ("failed", "")),
    ({"setup": _report("setup", "failed")}, ("failed", "")),
    ({"setup": _report("setup", "skipped", "no target")}, ("skipped", "no target")),
    ({"setup": _report("setup", "passed"), "call": _report("call", "skipped", "admission_log")},
     ("skipped", "admission_log")),
    ({}, ("skipped", "the stage did not run")),
], ids=["passed", "failed", "setup-error", "setup-skip", "call-skip", "not-run"])
def test_a_stages_reports_decide_its_outcome(reports, expected):
    result = stage_result("test_stage", ["2"], reports)
    assert (result.outcome, result.reason) == expected


def test_a_failed_teardown_fails_the_stage():
    reports = {"setup": _report("setup", "passed"), "call": _report("call", "passed"),
               "teardown": _report("teardown", "failed")}
    assert stage_result("test_stage", ["4"], reports).outcome == "failed"


def _module(observations=("2",), **classes):
    """A qualification module; a class given ``None`` takes the module's default."""
    module = ModuleType("qualification_module")
    module.OBSERVATIONS = observations
    for name, declared in classes.items():
        body = {"test_" + name.lower(): lambda self: None}
        if declared is not None:
            body["observations"] = declared
        setattr(module, "Test" + name, type("Test" + name, (), body))
    return module


def _item(module, cls, name, *reports, cycle=None):
    item = SimpleNamespace(name=name, originalname=name, cls=cls, module=module,
                           stash=pytest.Stash(), session=SimpleNamespace(items=[]))
    if cycle is not None:
        item.callspec = SimpleNamespace(params={module.CYCLE_PARAM: cycle})
    for report in reports:
        record_report(item, report)
    return item


def test_reports_are_kept_for_required_stages_only_and_logged(caplog):
    module = _module(Reads=None, Readiness=())
    required = _item(module, module.TestReads, "test_reads", _report("setup", "passed"),
                     _report("call", "skipped", "management_unit is not set"))
    opted_out = _item(module, module.TestReadiness, "test_readiness", _report("setup", "passed"),
                      _report("call", "failed"))
    assert REPORTS not in opted_out.stash
    with caplog.at_level("INFO"):
        (outcome,) = log_observation_outcomes(module, [required, opted_out])
    assert outcome.outcome == "unproven"
    assert ("Observation 2: unproven: TestReads::test_reads: management_unit is not set"
            in caplog.text)


def test_a_module_run_once_per_cycle_resolves_each_cycles_observation():
    module = _module(observations=("4", "5"), Shared=None, Refusal={"refusal": ("5",)})
    module.CYCLE_PARAM = "cleanup_cycle"
    module.CYCLE_OBSERVATIONS = {"normal": ("4",), "refusal": ("5",)}
    passed = (_report("setup", "passed"), _report("call", "passed"))
    items = [
        _item(module, module.TestShared, "test_shared", *passed, cycle="normal"),
        _item(module, module.TestRefusal, "test_refusal", _report("setup", "passed"),
              _report("call", "skipped", "the normal cycle plants nothing"), cycle="normal"),
        _item(module, module.TestShared, "test_shared", *passed, cycle="refusal"),
        _item(module, module.TestRefusal, "test_refusal", _report("setup", "passed"),
              _report("call", "failed"), cycle="refusal"),
    ]
    four, five = log_observation_outcomes(module, items)
    assert (four.outcome, four.stages) == ("made", ("TestShared::test_shared",))
    assert (five.outcome, five.stages) == ("failed", ("TestRefusal::test_refusal",))


def test_a_cycle_that_never_ran_leaves_its_observation_unproven():
    module = _module(observations=("4", "5"), Shared=None)
    module.CYCLE_PARAM = "cleanup_cycle"
    module.CYCLE_OBSERVATIONS = {"normal": ("4",), "refusal": ("5",)}
    items = [_item(module, module.TestShared, "test_shared", _report("setup", "passed"),
                   _report("call", "passed"), cycle="normal")]
    four, five = log_observation_outcomes(module, items)
    assert four.outcome == "made"
    assert (five.outcome, five.stages) == ("unproven", ("TestShared::test_shared[refusal]",))


def test_run_stage_runs_a_shared_body_on_the_given_fixtures():
    seen = {}

    class Shared:
        def test_body(self, deal_state, deal_driver):
            seen.update(state=deal_state, driver=deal_driver)

    run_stage(Shared, deal_state="second", deal_driver="driver")
    assert seen == {"state": "second", "driver": "driver"}


def test_a_stage_the_run_did_not_collect_reads_as_not_run():
    module = _module(Purchase=None, Reads=None)
    ran = _item(module, module.TestPurchase, "test_purchase", _report("setup", "passed"),
                _report("call", "passed"))
    (outcome,) = log_observation_outcomes(module, [ran])
    assert outcome.outcome == "unproven"
    assert outcome.stages == ("TestReads::test_reads",)
    assert outcome.reasons == ("the stage did not run",)


_STAGES_MODULE = '''
import pytest

OBSERVATIONS = ("2", "4", "5", "6")


@pytest.fixture
def broken_teardown():
    yield
    raise RuntimeError("teardown failed")


class TestPassed:
    observations = ("2",)
    def test_passed(self):
        pass


class TestSkipped:
    observations = ("2",)
    def test_skipped(self):
        pytest.skip("REAL_PROVISIONING_TARGET.hosts.vm.management_unit is not set")


class TestDeselected:
    observations = ("6",)
    def test_deselected(self):
        pass


class TestUndeclared:
    observations = ()
    def test_undeclared(self):
        pass


class TestMade:
    observations = ("5",)
    def test_made(self):
        pass


class TestTeardownFails:
    observations = ("4",)
    def test_teardown_fails(self, broken_teardown):
        pass
'''

_STOPPED_MODULE = '''
OBSERVATIONS = ("2", "5")


class TestFails:
    observations = ("2",)
    def test_fails(self):
        assert False


class TestLater:
    observations = ("5",)
    def test_later(self):
        pass
'''


def _run_pytest(tmp_path, module: str, *arguments: str) -> str:
    """Run pytest over ``module`` with the roles conftest's two hooks."""
    (tmp_path / "pytest.ini").write_text("[pytest]\n")
    (tmp_path / "conftest.py").write_text(
        "from tests.e2e.roles.conftest import (  # noqa: F401\n"
        "    pytest_runtest_makereport, pytest_sessionfinish,\n"
        ")\n"
    )
    (tmp_path / "test_stages.py").write_text(module)
    run = subprocess.run(
        [sys.executable, "-m", "pytest", "-p", "no:cacheprovider", *arguments,
         "-o", "log_cli=true", "--log-cli-level=INFO", "test_stages.py"],
        cwd=tmp_path, capture_output=True, text=True, timeout=120,
        env={**os.environ, "PYTHONPATH": str(E2E_ROOT)},
    )
    return run.stdout + run.stderr


def test_the_roles_hooks_log_each_observation_after_the_last_teardown(tmp_path):
    """The last stage's failed teardown counts; a deselected stage did not run."""
    output = _run_pytest(tmp_path, _STAGES_MODULE, "-k", "not deselected")
    assert "1 deselected" in output, output
    assert ("Observation 2: unproven: TestSkipped::test_skipped: "
            "REAL_PROVISIONING_TARGET.hosts.vm.management_unit is not set") in output, output
    assert "Observation 4: failed at TestTeardownFails::test_teardown_fails" in output, output
    assert "Observation 5: made (TestMade::test_made)" in output, output
    assert ("Observation 6: unproven: TestDeselected::test_deselected: the stage did not run"
            in output), output
    assert output.count("Observation 5:") == 1, output


def test_a_stopped_run_logs_its_outcomes_at_the_sessions_end(tmp_path):
    output = _run_pytest(tmp_path, _STOPPED_MODULE, "-x")
    assert "Observation 2: failed at TestFails::test_fails" in output, output
    assert "Observation 5: unproven: TestLater::test_later: the stage did not run" in output, output
    assert output.count("Observation 2:") == 1, output
