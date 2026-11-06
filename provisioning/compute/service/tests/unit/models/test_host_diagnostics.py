"""VM's host diagnostics contract: the service unit names a request may carry,
refused by the request model itself, and the typed reading of a succeeded job's
result.

The boot and invocation IDs are synthetic.
"""

from __future__ import annotations

import copy

import pytest
from compute_provisioning_contracts import ResultEnvelope
from pydantic import ValidationError
from vm_provisioning_operator import (
    HOST_DIAGNOSTICS_RESULT_KIND,
    HostDiagnostics,
    HostDiagnosticsError,
    HostDiagnosticsRequest,
    check_service_unit_name,
)


@pytest.mark.parametrize(
    "name",
    [
        "operator-agent.service",
        "getty@tty1.service",
        "getty@.service",
        "operator-agent@by\\x2dlabel.service",
        "a..b.service",
        "a:b_c.service",
        "x" * 247 + ".service",
    ],
)
def test_a_systemd_service_unit_name_is_accepted(name):
    assert check_service_unit_name(name) == name


@pytest.mark.parametrize(
    "name",
    [
        "",
        "operator-agent",
        "/etc/systemd/system/agent.service",
        "../agent.service",
        "agent service.service",
        "agent.service; reboot",
        "agent.service\n",
        "agent.unknown",
        "@instance.service",
        "x" * 248 + ".service",
        # Unit names of other types: none reports a main PID or a restart
        # count, so a diagnostics read of one could not be parsed.
        "operator-agent.socket",
        "dev-disk-by\\x2dlabel-data.device",
        "-.mount",
        "machine.slice",
        "a:b_c.timer",
        "multi-user.target",
    ],
)
def test_anything_else_is_refused(name):
    with pytest.raises(ValueError, match="not a systemd service unit name"):
        check_service_unit_name(name)


@pytest.mark.parametrize(
    "name", ["../agent.service", "agent service.service", "", "agent", "agent.socket"]
)
def test_the_request_refuses_a_unit_that_is_not_a_systemd_service_unit_name(name):
    with pytest.raises(ValidationError) as refused:
        HostDiagnosticsRequest(management_unit=name)

    assert refused.value.errors()[0]["loc"] == ("management_unit",)


def test_the_request_names_no_unit_by_default():
    assert HostDiagnosticsRequest().management_unit is None
    assert HostDiagnosticsRequest(management_unit="agent.service").management_unit == "agent.service"


def _unit(**changes) -> dict:
    unit = {
        "active_state": "active",
        "invocation_id": "3c1b0e4d5f6a4b7c8d9e0f1a2b3c4d5e",
        "main_pid": 812,
        "restart_count": 0,
        "active_enter_timestamp": "Thu 2026-11-05 09:00:00 UTC",
        "result": "success",
    }
    unit.update(changes)
    return unit


def _value(**changes) -> dict:
    value = {
        "host": "kvm1",
        "timestamp": "2026-11-05T10:00:00Z",
        "boot_id": "0f6c1d2e-3a4b-4c5d-8e9f-a0b1c2d3e4f5",
        "uptime_seconds": 3600.5,
        "kernel": "6.8.0-49-generic",
        "running_guests": 1,
        "management_unit": "operator-agent.service",
        "units": {
            "libvirtd.service": _unit(),
            "frpc-buyers.service": _unit(main_pid=913, restart_count=2),
            "operator-agent.service": _unit(main_pid=1014),
        },
        # The codec's other result fields, which the parse ignores.
        "action": "diagnose",
        "status": "success",
        "ansible_result": {},
    }
    value.update(changes)
    return value


def _result(value: dict, kind: str = HOST_DIAGNOSTICS_RESULT_KIND) -> ResultEnvelope:
    return ResultEnvelope(offering_mode="vm", result_kind=kind, value=value)


def _refused(value: dict) -> HostDiagnosticsError:
    with pytest.raises(HostDiagnosticsError) as refused:
        HostDiagnostics.from_job_result(_result(value))
    return refused.value


def test_a_well_formed_result_is_read_whole():
    diagnostics = HostDiagnostics.from_job_result(_result(_value()))

    assert diagnostics.boot_id == "0f6c1d2e-3a4b-4c5d-8e9f-a0b1c2d3e4f5"
    assert diagnostics.uptime_seconds == 3600.5
    assert diagnostics.running_guests == 1
    assert diagnostics.libvirtd.main_pid == 812
    assert diagnostics.relay_client.restart_count == 2
    assert diagnostics.management is not None
    assert diagnostics.management.invocation_id == "3c1b0e4d5f6a4b7c8d9e0f1a2b3c4d5e"


def test_a_result_naming_no_management_unit_needs_only_the_host_units():
    value = _value(management_unit=None)
    del value["units"]["operator-agent.service"]

    diagnostics = HostDiagnostics.from_job_result(_result(value))

    assert diagnostics.management is None
    assert diagnostics.reported_units() == ("libvirtd.service", "frpc-buyers.service")


def test_a_whole_number_of_seconds_is_an_uptime():
    assert HostDiagnostics.from_job_result(_result(_value(uptime_seconds=3600))).uptime_seconds == 3600


@pytest.mark.parametrize(
    "field",
    ["host", "timestamp", "boot_id", "uptime_seconds", "kernel", "running_guests",
     "management_unit", "units"],
)
def test_each_missing_field_is_refused_by_name(field):
    value = _value()
    del value[field]

    assert _refused(value).field == field


@pytest.mark.parametrize(
    "field",
    ["active_state", "invocation_id", "main_pid", "restart_count", "active_enter_timestamp",
     "result"],
)
def test_each_missing_unit_field_is_refused_by_name(field):
    value = _value()
    del value["units"]["frpc-buyers.service"][field]

    assert _refused(value).field == f"units.frpc-buyers.service.{field}"


@pytest.mark.parametrize(
    ("path", "wrong"),
    [
        (("running_guests",), "1"),
        (("running_guests",), True),
        (("uptime_seconds",), "3600.5"),
        (("boot_id",), 7),
        (("units", "libvirtd.service", "restart_count"), ""),
        (("units", "libvirtd.service", "main_pid"), 812.0),
        (("units", "libvirtd.service", "invocation_id"), None),
    ],
)
def test_a_field_of_the_wrong_type_is_refused_by_name(path, wrong):
    value = copy.deepcopy(_value())
    target = value
    for part in path[:-1]:
        target = target[part]
    target[path[-1]] = wrong

    assert _refused(value).field == ".".join(path)


@pytest.mark.parametrize("unit", ["libvirtd.service", "frpc-buyers.service", "operator-agent.service"])
def test_a_unit_the_job_was_asked_for_and_did_not_report_is_refused_by_name(unit):
    value = _value()
    del value["units"][unit]

    assert _refused(value).field == f"units.{unit}"


def test_no_result_is_refused():
    with pytest.raises(HostDiagnosticsError) as refused:
        HostDiagnostics.from_job_result(None)
    assert refused.value.field == "result"


def test_another_actions_result_is_refused_by_its_kind():
    with pytest.raises(HostDiagnosticsError) as refused:
        HostDiagnostics.from_job_result(_result(_value(), kind="vm_list"))
    assert refused.value.field == "result_kind"
