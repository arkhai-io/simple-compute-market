"""Qualification control flow and independent Linux observer boundaries."""
from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shlex
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
import yaml
from pydantic import ValidationError

from e2e_harness.real_provisioning_target import BareMetalHost, CleanupQualification
from tests.e2e.roles.helpers.ssh_access import SshEndpoint, SshKey
from tests.e2e.roles.scenarios.bare_metal import test_real_provisioning_deal as lane
from tests.e2e.roles.scenarios.bare_metal import working_data_probe as probe
from tests.e2e.roles.scenarios.bare_metal.working_data_qualification import (
    WorkingDataQualification, checked_key_reference, probe_command,
    qualification_cycles, qualification_requested, retryable_refusal,
)

EXAMPLE = Path(__file__).resolve().parents[2] / "config/config-real-provisioning-target.yml.example"


def target(tmp_path):
    # Documentation-range endpoint and synthetic local key are development
    # fixtures only and must never be used on a public network.
    value = yaml.safe_load(EXAMPLE.read_text())["REAL_PROVISIONING_TARGET"]["hosts"][1]
    key = tmp_path / "operator-key"
    key.write_text("synthetic-key-reference")
    key.chmod(0o600)
    value["cleanup_qualification"] = {"policy_id": "development-policy",
        "operator": {"host": "192.0.2.20", "port": 22, "user": "operator", "key_path": str(key)}}
    return BareMetalHost.model_validate(value)


def test_dedicated_marker_never_substitutes_a_baseline_run(tmp_path):
    baseline = BareMetalHost.model_validate(yaml.safe_load(EXAMPLE.read_text())["REAL_PROVISIONING_TARGET"]["hosts"][1])
    assert qualification_cycles(baseline, required=False) == ("baseline",)
    assert qualification_cycles(None, required=False) == ("baseline",)
    for value in (None, baseline):
        with pytest.raises(ValueError, match="requires an explicit"):
            qualification_cycles(value, required=True)
    assert qualification_cycles(target(tmp_path), required=True) == ("normal", "refusal")


@pytest.mark.parametrize("change", [
    lambda c: c.update(unknown=True),
    lambda c: c["operator"].update(key_path="relative-key"),
    lambda c: c["operator"].update(key_path="/keys/../key"),
    lambda c: c["operator"].update(port=True),
])
def test_operator_target_is_strict_and_key_is_a_local_absolute_reference(tmp_path, change):
    value = target(tmp_path).cleanup_qualification.model_dump()
    change(value)
    with pytest.raises(ValidationError):
        CleanupQualification.model_validate(value)


def test_key_reference_validation_reads_no_key_and_rejects_links_permissions(tmp_path):
    key = tmp_path / "key"
    key.write_bytes(b"synthetic")
    key.chmod(0o600)
    assert checked_key_reference(str(key)).private_key == key
    link = tmp_path / "link"
    link.symlink_to(key)
    with pytest.raises(ValueError, match="owner-only"):
        checked_key_reference(str(link))
    key.chmod(0o644)
    with pytest.raises(ValueError, match="owner-only"):
        checked_key_reference(str(key))
    key.chmod(0o600)
    os.link(key, tmp_path / "hardlink")
    with pytest.raises(ValueError, match="owner-only"):
        checked_key_reference(str(key))


def test_probe_arguments_are_one_json_argument_and_use_no_cleanup_authority():
    request = {"operation": "observe", "account": "tenant; false", "nonce": "'$(false)'"}
    argv = shlex.split(probe_command(request, operator=True))
    assert argv[:5] == ["sudo", "-n", "--", "python3", "-c"]
    assert json.loads(argv[-1]) == request
    assert "arkhai-tenant-working-data.py" not in argv[-2]


def test_preflight_uses_pinned_shared_ssh_and_copies_no_private_key(tmp_path):
    host = target(tmp_path)
    ssh = MagicMock()
    ssh.run.return_value = json.dumps({"scratch": "/tmp", "ipc_root": "/dev/shm", "home_parent": str(tmp_path / "homes"), "consumed": []})
    observer = WorkingDataQualification(host, ssh, [], "normal")
    observer.preflight()
    endpoint, key, command = ssh.run.call_args.args
    assert endpoint == SshEndpoint("192.0.2.20", 22, "operator")
    assert key.private_key == Path(host.cleanup_qualification.operator.key_path)
    assert "synthetic-key-reference" not in command
    assert json.loads(shlex.split(command)[-1])["operation"] == "policy"
    assert observer.state["consumed"] == []


def _job(**changes):
    return SimpleNamespace(status="queued", retry_count=1, max_retries=3,
                           next_retry_at=datetime.now(timezone.utc), error="failed attempt", **changes)


def test_only_actual_scheduled_nonterminal_attempt_is_a_refusal():
    assert retryable_refusal(_job())
    for attribute, value in (("retry_count", 0), ("next_retry_at", None), ("error", None), ("status", "running")):
        job = _job()
        setattr(job, attribute, value)
        assert not retryable_refusal(job)
    for state in ("succeeded", "failed", "cancelled"):
        job = _job()
        job.status = state
        with pytest.raises(AssertionError, match="terminal job"):
            retryable_refusal(job)


def test_refusal_observes_real_error_and_held_capacity_before_fixture_repair(tmp_path):
    observer = WorkingDataQualification(target(tmp_path), MagicMock(), [41000], "refusal")
    observer.state = {"reservation_id": "reservation"}
    driver = MagicMock()
    driver.assert_management_connected = MagicMock()
    driver.reservation_of.return_value = ("reservation", "tearing_down")
    driver.jobs.only_job.return_value = SimpleNamespace(job_id="job")
    driver.provisioning_client.get_job.return_value = _job()
    driver.provisioning_client.get_job_logs.return_value = SimpleNamespace(logs="foreign descendant")
    state = SimpleNamespace(teardown_fulfillment_id="teardown", create_job_id="grant", deal_lease=MagicMock(), reserved_resource_id="resource")
    state.deal_lease.refresh.return_value = {"status": "releasing"}
    state.deal_lease.resource_consumed.return_value = True
    events = []
    state.deal_lease.resource_consumed.side_effect = lambda *args: events.append("capacity-held") or True
    observer._operator = lambda operation: events.append(operation) or {"fixture_only_repaired": True}
    observer.observe_refusal_and_repair(driver=driver, deal_state=state, storefront_admin_client=object())
    assert events == ["capacity-held", "repair"]
    assert observer.state["refusal_observed"]
    driver.jobs.until_succeeded.assert_not_called()
    driver.provisioning_client.submit_job.assert_not_called()


@pytest.mark.parametrize("error,held", [("unrelated transport failure", True), ("foreign descendant", False)])
def test_unrelated_failure_or_available_capacity_never_authorizes_repair(tmp_path, error, held):
    observer = WorkingDataQualification(target(tmp_path), MagicMock(), [], "refusal")
    observer.state = {"reservation_id": "reservation"}
    driver = MagicMock()
    driver.assert_management_connected = MagicMock()
    driver.reservation_of.return_value = ("reservation", "tearing_down")
    driver.jobs.only_job.return_value = SimpleNamespace(job_id="job")
    driver.provisioning_client.get_job.return_value = _job()
    driver.provisioning_client.get_job_logs.return_value = SimpleNamespace(logs=error)
    state = SimpleNamespace(teardown_fulfillment_id="teardown", create_job_id="grant", deal_lease=MagicMock(), reserved_resource_id="resource")
    state.deal_lease.refresh.return_value = {"status": "releasing"}
    state.deal_lease.resource_consumed.return_value = held
    observer._operator = MagicMock()
    with pytest.raises(AssertionError):
        observer.observe_refusal_and_repair(driver=driver, deal_state=state, storefront_admin_client=object())
    observer._operator.assert_not_called()


def test_successor_reused_uid_fails_before_any_fixture_write(tmp_path):
    observer = WorkingDataQualification(target(tmp_path), MagicMock(), [41000], "refusal")
    ssh = MagicMock()
    ssh.run.return_value = "41000\n"
    with pytest.raises(AssertionError, match="reused"):
        observer.seed(ssh=ssh, endpoint=SshEndpoint("192.0.2.20", 22, "tenant"),
                      key=SshKey(tmp_path / "buyer", "synthetic"), reservation_id="second")
    assert ssh.run.call_count == 1
    observer.operator_ssh.run.assert_not_called()


def test_independent_filesystem_scan_never_follows_symlinks(tmp_path):
    root = tmp_path / "scratch"
    root.mkdir()
    outside = tmp_path / "operator"
    outside.mkdir()
    sentinel = outside / "sentinel"
    sentinel.write_text("retained")
    (root / "link").symlink_to(outside)
    nested = root / "nested"
    nested.mkdir()
    (nested / "data").write_text("synthetic")
    found = probe.owned_entries(str(root), os.getuid())
    assert str(root / "link") in found
    assert str(nested / "data") in found
    assert not any("sentinel" in item for item in found)
    assert sentinel.read_text() == "retained"


def test_independent_proc_observation_checks_all_four_uid_fields(tmp_path):
    for pid, values in ((1, (1001, 0, 0, 0)), (2, (0, 1001, 0, 0)), (3, (0, 0, 1001, 0)), (4, (0, 0, 0, 1001)), (5, (0, 0, 0, 0))):
        entry = tmp_path / str(pid)
        entry.mkdir()
        (entry / "status").write_text("Uid:\t" + "\t".join(map(str, values)) + "\n")
    assert sorted(probe.uid_processes(1001, tmp_path)) == [1, 2, 3, 4]


def test_independent_kernel_ipc_observation_checks_owner_and_creator(tmp_path):
    for kind, identifier in (("shm", "shmid"), ("sem", "semid"), ("msg", "msqid")):
        (tmp_path / kind).write_text(f"{identifier} uid cuid\n1 1001 0\n2 0 1001\n3 0 0\n")
    assert probe.uid_ipc(1001, tmp_path) == [(kind, identifier) for kind in ("shm", "sem", "msg") for identifier in (1, 2)]
    (tmp_path / "sem").unlink()
    with pytest.raises(FileNotFoundError):
        probe.uid_ipc(1001, tmp_path)


def test_directory_observer_refuses_symlinked_ancestors(tmp_path):
    real = tmp_path / "real"
    real.mkdir()
    (tmp_path / "alias").symlink_to(real)
    with pytest.raises(OSError):
        with probe.directory(str(tmp_path / "alias")):
            pytest.fail("symlink was traversed")


@pytest.mark.parametrize("expression,required", [
    ("", False),
    ("e2e_bare_metal_real_provisioning", False),
    ("e2e_bare_metal_bounded_cleanup", True),
    ("not e2e_bare_metal_bounded_cleanup", False),
    ("e2e_bare_metal_bounded_cleanup and not contracts", True),
    ("e2e_bare_metal_bounded_cleanup or e2e_bare_metal_real_provisioning", False),
])
def test_marker_expression_requires_cleanup_only_when_selected(expression, required):
    assert qualification_requested(expression) is required


def test_missing_operator_key_fails_before_any_ssh_observation(tmp_path):
    host = target(tmp_path)
    Path(host.cleanup_qualification.operator.key_path).unlink()
    observer = WorkingDataQualification(host, MagicMock(), [], "normal")
    with pytest.raises(FileNotFoundError):
        observer.preflight()
    observer.operator_ssh.run.assert_not_called()


def test_successor_preflight_refuses_before_purchase_when_predecessor_not_verified(tmp_path):
    with pytest.raises(AssertionError, match="independently verified predecessor"):
        lane.cleanup_preflight.__wrapped__(target(tmp_path), "refusal", [])
