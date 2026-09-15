"""Offline contracts for the isolated supervised-custody qualification lane."""

import ast
import importlib.util
import json
import os
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest


HARNESS = Path(__file__).with_name(
    "bare_metal_storage_supervised_software_tpm.py"
)


def _load_harness():
    spec = importlib.util.spec_from_file_location(
        "bare_metal_storage_supervised_software_tpm", HARNESS
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_qualification_unit_keeps_production_controls_and_scopes_test_overlays(
    tmp_path,
):
    module = _load_harness()

    rendered = module.render_qualification_unit(
        executable=HARNESS,
        profile=tmp_path / "profile.json",
        request_root=tmp_path / "requests",
        state_root=tmp_path / "state",
    )

    assert "Slice=system.slice" in rendered
    assert "PrivateNetwork=yes" in rendered
    assert "RestrictAddressFamilies=AF_UNIX" in rendered
    assert "MemorySwapMax=0" in rendered
    assert "LimitCORE=0" in rendered
    assert "BindPaths=/dev/null" in rendered
    assert "/proc/sys/kernel/core_pattern" not in rendered
    assert "{{" not in rendered


@pytest.mark.parametrize(
    "raw, message",
    [
        (b"|/usr/lib/systemd/systemd-coredump %P\n", "piped"),
        (b"\n", "malformed"),
        (b" core\n", "malformed"),
        (b"core\x00suffix\n", "malformed"),
        (b"core\nsecond\n", "malformed"),
    ],
)
def test_underlying_core_policy_parser_refuses_unsafe_values(raw, message):
    module = _load_harness()

    with pytest.raises(module.QualificationRefused, match=message):
        module.admit_underlying_core_policy(raw)


def test_qualification_reads_genuine_policy_before_any_mutation(monkeypatch):
    module = _load_harness()
    events = []

    def refuse_policy():
        events.append("policy")
        raise module.QualificationRefused("piped core handler is not admitted")

    def mutation(*_args, **_kwargs):
        events.append("mutation")
        raise AssertionError("qualification mutated before core-policy admission")

    monkeypatch.setattr(module, "require_underlying_core_policy", refuse_policy)
    monkeypatch.setattr(module, "_install_case", mutation)
    monkeypatch.setattr(module, "_provision", mutation)
    monkeypatch.setattr(module, "_systemctl", mutation)
    monkeypatch.setattr(module.resource, "setrlimit", mutation)

    with pytest.raises(module.QualificationRefused, match="piped core handler"):
        module.qualify()

    assert events == ["policy"]


def test_missing_underlying_core_policy_refuses(monkeypatch):
    module = _load_harness()

    def missing(path, flags):
        assert path == module._CORE_PATTERN
        assert flags & os.O_NOFOLLOW
        raise FileNotFoundError(path)

    monkeypatch.setattr(module.os, "open", missing)

    with pytest.raises(module.QualificationRefused, match="unavailable"):
        module.require_underlying_core_policy()


@pytest.mark.parametrize(
    "returncode,stderr,message",
    [
        (1, b"Failed to connect to bus: No such file or directory\n", "system bus"),
        (0, b"Running in chroot, ignoring command 'start'\n", "manager response"),
        (1, b"unexpected failure\n", "manager response"),
    ],
)
def test_wait_bus_readiness_refuses_without_exact_missing_unit_response(
    monkeypatch, returncode, stderr, message
):
    module = _load_harness()
    calls = []

    def run(argv, **kwargs):
        calls.append((tuple(argv), kwargs))
        if argv[1] == "show":
            return SimpleNamespace(returncode=0, stdout=b"not-found\n", stderr=b"")
        return SimpleNamespace(returncode=returncode, stdout=b"", stderr=stderr)

    monkeypatch.setattr(module.subprocess, "run", run)

    with pytest.raises(module.QualificationRefused, match=message):
        module.require_wait_bus_dispatch()

    assert calls[0][0] == (
        "/usr/bin/systemctl",
        "show",
        "--property=LoadState",
        "--value",
        module._WAIT_BUS_PROBE_UNIT,
    )
    assert calls[1][0] == (
        "/usr/bin/systemctl",
        "start",
        "--wait",
        module._WAIT_BUS_PROBE_UNIT,
    )
    assert calls[1][1]["timeout"] == 15
    assert calls[1][1]["stdin"] is module.subprocess.DEVNULL
    assert calls[1][1]["stdout"] is module.subprocess.PIPE
    assert calls[1][1]["stderr"] is module.subprocess.PIPE
    assert "env" not in calls[1][1]


def test_wait_bus_readiness_accepts_only_manager_missing_unit_response(monkeypatch):
    module = _load_harness()
    expected = (
        f"Failed to start {module._WAIT_BUS_PROBE_UNIT}: "
        f"Unit {module._WAIT_BUS_PROBE_UNIT} not found.\n"
    ).encode("ascii")
    def run(argv, **_kwargs):
        if argv[1] == "show":
            return SimpleNamespace(returncode=0, stdout=b"not-found\n", stderr=b"")
        return SimpleNamespace(returncode=5, stdout=b"", stderr=expected)

    monkeypatch.setattr(module.subprocess, "run", run)

    module.require_wait_bus_dispatch()


@pytest.mark.parametrize(
    "returncode,stdout,suffix,message",
    [
        (5, b"", b"unexpected suffix\n", "manager response"),
        (
            5,
            b"",
            b"x" * 2048 + b"Failed to connect to bus\n",
            "system bus",
        ),
        (1, b"", b"", "manager response"),
        (-9, b"", b"", "manager response"),
        (5, b"unexpected stdout\n", b"", "manager response"),
    ],
)
def test_wait_bus_readiness_rejects_any_deviation_from_systemd_249_response(
    monkeypatch, returncode, stdout, suffix, message
):
    module = _load_harness()
    expected = (
        f"Failed to start {module._WAIT_BUS_PROBE_UNIT}: "
        f"Unit {module._WAIT_BUS_PROBE_UNIT} not found.\n"
    ).encode("ascii")

    def run(argv, **_kwargs):
        if argv[1] == "show":
            return SimpleNamespace(returncode=0, stdout=b"not-found\n", stderr=b"")
        return SimpleNamespace(
            returncode=returncode,
            stdout=stdout,
            stderr=expected + suffix,
        )

    monkeypatch.setattr(module.subprocess, "run", run)

    with pytest.raises(module.QualificationRefused, match=message):
        module.require_wait_bus_dispatch()


def test_wait_bus_readiness_preserves_only_bounded_error_detail(monkeypatch):
    module = _load_harness()
    def run(argv, **_kwargs):
        if argv[1] == "show":
            return SimpleNamespace(returncode=0, stdout=b"not-found\n", stderr=b"")
        return SimpleNamespace(
            returncode=1,
            stdout=b"",
            stderr=b"specific-probe-error:" + b"x" * 8192 + b":discarded-tail",
        )

    monkeypatch.setattr(module.subprocess, "run", run)

    with pytest.raises(module.QualificationRefused) as captured:
        module.require_wait_bus_dispatch()

    message = str(captured.value)
    assert "specific-probe-error" in message
    assert "discarded-tail" not in message
    assert len(message) < 1400


def test_wait_bus_readiness_refuses_a_start_wait_timeout(monkeypatch):
    module = _load_harness()

    def run(argv, **_kwargs):
        if argv[1] == "show":
            return SimpleNamespace(returncode=0, stdout=b"not-found\n", stderr=b"")
        raise module.subprocess.TimeoutExpired(argv, 15)

    monkeypatch.setattr(module.subprocess, "run", run)

    with pytest.raises(module.QualificationRefused, match="response is unavailable"):
        module.require_wait_bus_dispatch()


def test_wait_bus_readiness_refuses_a_manager_visible_probe_unit(monkeypatch):
    module = _load_harness()
    calls = []

    def run(argv, **_kwargs):
        calls.append(tuple(argv))
        return SimpleNamespace(returncode=0, stdout=b"loaded\n", stderr=b"")

    monkeypatch.setattr(module.subprocess, "run", run)

    with pytest.raises(module.QualificationRefused, match="probe unit is not absent"):
        module.require_wait_bus_dispatch()

    assert len(calls) == 1


@pytest.mark.parametrize("variable", ["SYSTEMD_OFFLINE", "SYSTEMD_IGNORE_CHROOT"])
def test_wait_bus_readiness_refuses_inherited_systemd_bypasses(
    monkeypatch, variable
):
    module = _load_harness()
    monkeypatch.setenv(variable, "1")
    monkeypatch.setattr(
        module.subprocess,
        "run",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("inherited bypass reached systemctl")
        ),
    )

    with pytest.raises(module.QualificationRefused, match="systemd environment"):
        module.require_wait_bus_dispatch()


def test_missing_wait_bus_refuses_before_qualification_mutation(monkeypatch):
    module = _load_harness()
    events = []

    monkeypatch.setattr(module, "require_underlying_core_policy", lambda: "core")
    monkeypatch.setattr(module.os, "geteuid", lambda: 0)
    original_read_text = module.Path.read_text

    def read_text(path, *args, **kwargs):
        if path == module.Path("/proc/1/comm"):
            return "systemd\n"
        return original_read_text(path, *args, **kwargs)

    def run(argv, **_kwargs):
        if argv[0] == "systemd-detect-virt":
            return SimpleNamespace(returncode=0)
        if argv[0] == "systemd-analyze":
            return SimpleNamespace(returncode=0, stdout="systemd 249\n")
        raise AssertionError(f"unexpected command: {argv}")

    def refuse_bus():
        events.append("wait-bus")
        raise module.QualificationRefused("system bus is unavailable")

    def mutation(*_args, **_kwargs):
        events.append("mutation")
        raise AssertionError("qualification mutated before wait-bus readiness")

    monkeypatch.setattr(module.Path, "read_text", read_text)
    monkeypatch.setattr(module.subprocess, "run", run)
    monkeypatch.setattr(module, "require_wait_bus_dispatch", refuse_bus, raising=False)
    monkeypatch.setattr(module, "assert_fresh_unit_boundary", mutation)
    monkeypatch.setattr(module, "_install_case", mutation)
    monkeypatch.setattr(module, "_provision", mutation)
    monkeypatch.setattr(module.resource, "setrlimit", mutation)

    with pytest.raises(module.QualificationRefused, match="system bus"):
        module.qualify()

    assert events == ["wait-bus"]


@pytest.mark.parametrize("collision", ["unit", "drop-in", "instance-drop-in"])
def test_preexisting_unit_boundary_is_refused_without_adoption(tmp_path, collision):
    module = _load_harness()
    systemd = tmp_path / "systemd"
    systemd.mkdir()
    unit = systemd / module.UNIT_PATH.name
    if collision == "unit":
        target = unit
        target.write_text("foreign unit\n", encoding="utf-8")
    elif collision == "drop-in":
        target = systemd / f"{module.UNIT_PATH.name}.d"
        target.mkdir()
    else:
        target = systemd / "arkhai-lease-storage-prepare@foreign.service.d"
        target.mkdir()

    with pytest.raises(module.QualificationRefused, match="already exists"):
        module.assert_fresh_unit_boundary(
            unit_path=unit, search_dirs=(systemd,)
        )

    assert target.exists()
    if target.is_file():
        assert target.read_text() == "foreign unit\n"


def test_qualification_refuses_existing_unit_before_mutable_setup(monkeypatch):
    module = _load_harness()
    events = []

    monkeypatch.setattr(module, "require_underlying_core_policy", lambda: "core")
    monkeypatch.setattr(module.os, "geteuid", lambda: 0)
    original_read_text = module.Path.read_text

    def read_text(path, *args, **kwargs):
        if path == module.Path("/proc/1/comm"):
            return "systemd\n"
        return original_read_text(path, *args, **kwargs)

    def run(argv, **_kwargs):
        if argv[0] == "systemd-detect-virt":
            return SimpleNamespace(returncode=0)
        if argv[0] == "systemd-analyze":
            return SimpleNamespace(returncode=0, stdout="systemd 249\n")
        raise AssertionError(f"unexpected command: {argv}")

    def collision(*_args, **_kwargs):
        events.append("unit-boundary")
        raise module.QualificationRefused("qualification unit already exists")

    def mutation(*_args, **_kwargs):
        events.append("mutation")
        raise AssertionError("qualification mutated after unit collision")

    monkeypatch.setattr(module.Path, "read_text", read_text)
    monkeypatch.setattr(module.subprocess, "run", run)
    monkeypatch.setattr(module, "assert_fresh_unit_boundary", collision)
    monkeypatch.setattr(module, "_install_case", mutation)
    monkeypatch.setattr(module, "_systemctl", mutation)
    monkeypatch.setattr(module.resource, "setrlimit", mutation)

    with pytest.raises(module.QualificationRefused, match="already exists"):
        module.qualify()

    assert events == ["unit-boundary"]


def test_owned_unit_publication_never_overwrites_or_unlinks_a_replacement(tmp_path):
    module = _load_harness()
    systemd = tmp_path / "systemd"
    systemd.mkdir()
    unit = systemd / module.UNIT_PATH.name
    unit.write_text("foreign\n", encoding="utf-8")

    with pytest.raises(module.QualificationRefused, match="already exists"):
        module.publish_owned_unit("ours\n", unit_path=unit)
    assert unit.read_text() == "foreign\n"

    unit.unlink()
    identity = module.publish_owned_unit("ours\n", unit_path=unit)
    assert unit.read_text() == "ours\n"
    assert module.publish_owned_unit(
        "updated\n", identity=identity, unit_path=unit
    ) == identity
    assert unit.read_text() == "updated\n"

    unit.unlink()
    unit.write_text("replacement\n", encoding="utf-8")
    with pytest.raises(module.QualificationRefused, match="ownership changed"):
        module.remove_owned_unit(identity, unit_path=unit)
    assert unit.read_text() == "replacement\n"


def test_failure_diagnostics_capture_missing_invocation_and_durable_state(
    monkeypatch, tmp_path
):
    module = _load_harness()
    request_id = "a" * 64
    instance = module.UNIT.format(request_id)
    requests = tmp_path / "requests"
    requests.mkdir(mode=0o700)
    outcome = requests / f"{request_id}.execution.json"
    module._write_private_json(
        outcome,
        {
            "schema": "arkhai.lease-storage-execution.v1",
            "request_id": request_id,
            "state": "accepted",
            "receipt": {"secret-shaped-field": "must-not-appear"},
        },
    )
    module._write_private_json(
        requests / "unit-failure.json",
        {
            "schema": "arkhai.supervised-software-tpm-unit-failure.v5",
            "request_id": request_id,
            "stage": "custody-after-flush-object",
            "error_code": "preparation-refused",
            "origin_stage": "helper-prepare",
            "origin_error_code": "luks2-format-uncertain",
            "origin_cause_code": "cryptsetup-exit-status",
            "origin_operation": "cryptsetup-luks-format",
            "origin_operation_result": "exit-status",
            "origin_operation_returncode": 2,
            "origin_tss2_rc": None,
            "origin_tss2_layer": "not-observed",
            "origin_tss2_subject": "not-observed",
            "unit_memory_events": {
                "high": 0,
                "low": 0,
                "max": 0,
                "oom": 0,
                "oom_kill": 0,
            },
        },
    )
    calls = []

    def systemctl(argv, **_kwargs):
        calls.append(tuple(argv))
        if argv[0] == "show":
            return SimpleNamespace(
                returncode=0,
                stdout=(
                    b"Result=success\nExecMainCode=0\nExecMainStatus=0\n"
                    b"SubState=dead\nControlGroup=\nInvocationID=\n"
                    b"ConditionResult=yes\nAssertResult=yes\n"
                ),
                stderr=b"",
            )
        return SimpleNamespace(returncode=0, stdout=b"unit evidence\n", stderr=b"")

    monkeypatch.setattr(module, "_systemctl", systemctl)
    monkeypatch.setattr(
        module,
        "_journal_diagnostics",
        lambda expected: f"journal for {expected}",
        raising=False,
    )

    diagnostic = module._diagnostics(instance, outcome)

    show = calls[0]
    for name in (
        "ConditionResult",
        "AssertResult",
        "InvocationID",
        "ExecStart",
        "ExecMainStartTimestampMonotonic",
        "ExecMainExitTimestampMonotonic",
        "FragmentPath",
        "DropInPaths",
        "NeedDaemonReload",
    ):
        assert f"--property={name}" in show
    assert ("cat", "--no-pager", instance) in calls
    assert "durable_state=accepted" in diagnostic
    assert "unit_failure_last_stage=custody-after-flush-object" in diagnostic
    assert "unit_failure_error_code=preparation-refused" in diagnostic
    assert "unit_failure_origin_stage=helper-prepare" in diagnostic
    assert "unit_failure_origin_error_code=luks2-format-uncertain" in diagnostic
    assert "unit_failure_origin_cause_code=cryptsetup-exit-status" in diagnostic
    assert "unit_failure_origin_operation=cryptsetup-luks-format" in diagnostic
    assert "unit_failure_origin_operation_result=exit-status" in diagnostic
    assert "unit_failure_origin_operation_returncode=2" in diagnostic
    assert "unit_failure_origin_tss2_rc=absent" in diagnostic
    assert "unit_failure_origin_tss2_layer=not-observed" in diagnostic
    assert "unit_failure_origin_tss2_subject=not-observed" in diagnostic
    assert (
        'unit_failure_unit_memory_events={"high":0,"low":0,"max":0,'
        '"oom":0,"oom_kill":0}' in diagnostic
    )
    assert "main_process_observed=no" in diagnostic
    assert "journal for" in diagnostic
    assert "must-not-appear" not in diagnostic


def test_failure_diagnostics_reject_an_untrusted_unit_name(monkeypatch):
    module = _load_harness()
    monkeypatch.setattr(
        module,
        "_systemctl",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("untrusted unit reached systemctl")
        ),
    )

    assert module._diagnostics("foreign.service", None) == (
        "qualification diagnostic unit identity is invalid"
    )


def test_preparation_refusal_classifier_covers_every_static_helper_branch():
    module = _load_harness()
    tree = ast.parse(module.PREPARE.read_text(encoding="utf-8"))
    messages = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Raise) or not isinstance(node.exc, ast.Call):
            continue
        function = node.exc.func
        if not isinstance(function, ast.Name) or not function.id.startswith(
            "Preparation"
        ):
            continue
        if node.exc.args and isinstance(node.exc.args[0], ast.Constant):
            value = node.exc.args[0].value
            if isinstance(value, str):
                messages.add(value)

    assert messages == set(module._PREPARATION_REFUSAL_CODES)
    assert all(
        module._preparation_refusal_code(RuntimeError(message))
        != "preparation-refusal-unclassified"
        for message in messages
    )


@pytest.mark.parametrize(
    "message, expected",
    [
        ("invalid host_id", "lease-identity-invalid"),
        ("invalid machine_id", "lease-identity-invalid"),
        ("invalid generation", "lease-identity-invalid"),
        ("unapproved external command: false", "external-command-unapproved"),
        ("cryptsetup failed with exit status 2", "cryptsetup-exit-status"),
        ("other failed with exit status -9", "external-command-exit-status"),
        ("required tool unavailable: other", "external-tool-unavailable"),
        ("unsafe existing directory: /state", "existing-directory-unsafe"),
        ("state path contains a symlink: /state/x", "state-path-symlink"),
        ("refusing symlink: /state/x", "path-symlink"),
        ("unsafe owned metadata file: /state/x", "owned-metadata-file-unsafe"),
        ("invalid owned metadata file: /state/x", "owned-metadata-file-invalid"),
        ("invalid owned metadata object: /state/x", "owned-metadata-object-invalid"),
        ("refusing existing output path: public.blob", "generated-output-exists"),
        ("unsafe existing file: /state/x", "existing-file-unsafe"),
        ("unrecognized sensitive detail", "preparation-refusal-unclassified"),
    ],
)
def test_preparation_refusal_classifier_bounds_dynamic_messages(message, expected):
    module = _load_harness()

    assert module._preparation_refusal_code(RuntimeError(message)) == expected


@pytest.mark.parametrize(
    "argv, expected",
    [
        (
            ("cryptsetup", "isLuks", "--type", "luks2", "/private/volume"),
            "cryptsetup-is-luks",
        ),
        (
            (
                "cryptsetup",
                "--batch-mode",
                "--type",
                "luks2",
                "--key-file",
                "-",
                "--keyfile-size",
                "32",
                "luksFormat",
                "/private/volume",
            ),
            "cryptsetup-luks-format",
        ),
        (
            (
                "cryptsetup",
                "luksDump",
                "--dump-json-metadata",
                "/private/volume",
            ),
            "cryptsetup-luks-metadata",
        ),
        (
            (
                "cryptsetup",
                "--type",
                "luks2",
                "--test-passphrase",
                "--disable-keyring",
                "--key-file",
                "-",
                "--keyfile-size",
                "32",
                "open",
                "/private/volume",
            ),
            "cryptsetup-test-passphrase",
        ),
        (("cryptsetup", "unsupported", "/private/volume"), "cryptsetup-unclassified"),
    ],
)
def test_cryptsetup_operation_classifier_names_exact_helper_argv(argv, expected):
    module = _load_harness()

    assert module._cryptsetup_operation(argv) == expected


@pytest.mark.parametrize(
    "message, expected",
    [
        ("cryptsetup failed with exit status 1", ("exit-status", 1)),
        ("cryptsetup failed with exit status 5", ("exit-status", 5)),
        ("cryptsetup failed with exit status 137", ("exit-status", 137)),
        ("cryptsetup failed with exit status -9", ("signal-sigkill", -9)),
        ("cryptsetup failed with exit status -31", ("signal-sigsys", -31)),
        ("cryptsetup failed with exit status -11", ("signal-sigsegv", -11)),
        ("cryptsetup failed with exit status -6", ("signal-sigabrt", -6)),
        ("cryptsetup failed with exit status -15", ("signal-other", -15)),
        ("cryptsetup failed with exit status 0", ("returncode-zero", 0)),
        (
            "cryptsetup failed with exit status 2147483648",
            ("returncode-out-of-range", None),
        ),
        (
            "required tool unavailable: cryptsetup",
            ("refused-without-returncode", None),
        ),
        (
            "cryptsetup failed with exit status 2 secret",
            ("refused-without-returncode", None),
        ),
    ],
)
def test_cryptsetup_result_classifier_publishes_only_bounded_values(
    message, expected
):
    module = _load_harness()

    assert module._cryptsetup_operation_result(RuntimeError(message)) == expected


@pytest.mark.parametrize(
    "cause, expected",
    [
        (subprocess.TimeoutExpired(["cryptsetup"], 30), ("timeout", None)),
        (OSError("synthetic unavailable"), ("os-error", None)),
    ],
)
def test_cryptsetup_result_classifier_preserves_bounded_chained_causes(
    cause, expected
):
    module = _load_harness()
    refusal = RuntimeError("required tool unavailable: cryptsetup")
    refusal.__cause__ = cause

    assert module._cryptsetup_operation_result(refusal) == expected


@pytest.mark.parametrize(
    "result, returncode",
    [
        ("signal-sigkill", -15),
        ("signal-other", -9),
        ("exit-status", 0),
        ("timeout", -9),
        ("exit-status", True),
        ("exit-status", 2147483648),
    ],
)
def test_cryptsetup_result_validator_rejects_mismatched_or_unbounded_values(
    result, returncode
):
    module = _load_harness()

    assert not module._valid_operation_result(result, returncode)


def test_memory_event_parser_selects_only_bounded_oom_counters():
    module = _load_harness()

    assert module._parse_memory_events(
        "low 0\nhigh 1\nmax 2\noom 3\noom_kill 4\noom_group_kill 5\n"
    ) == {"high": 1, "low": 0, "max": 2, "oom": 3, "oom_kill": 4}
    assert module._parse_memory_events("low 0\nhigh 0\nmax 0\noom 0\n") is None
    assert module._parse_memory_events(
        "low 0\nlow 1\nhigh 0\nmax 0\noom 0\noom_kill 0\n"
    ) is None


def test_unit_memory_events_reads_only_the_calling_unit_cgroup(monkeypatch):
    module = _load_harness()
    request_id = "a" * 64
    unit = module.UNIT.format(request_id)
    reads = []

    class SyntheticPath:
        def __init__(self, value):
            self.value = str(value)

        def read_text(self, *, encoding):
            reads.append((self.value, encoding))
            if self.value == "/proc/self/cgroup":
                return f"0::/system.slice/{unit}\n"
            if self.value == f"/sys/fs/cgroup/system.slice/{unit}/memory.events":
                return "low 0\nhigh 1\nmax 2\noom 3\noom_kill 4\n"
            raise AssertionError("unexpected cgroup diagnostic path")

    monkeypatch.setattr(module, "Path", SyntheticPath)

    assert module._unit_memory_events(request_id) == {
        "high": 1,
        "low": 0,
        "max": 2,
        "oom": 3,
        "oom_kill": 4,
    }
    assert reads == [
        ("/proc/self/cgroup", "ascii"),
        (f"/sys/fs/cgroup/system.slice/{unit}/memory.events", "ascii"),
    ]


def test_unit_memory_events_refuses_a_different_cgroup(monkeypatch):
    module = _load_harness()

    class SyntheticPath:
        def __init__(self, value):
            self.value = str(value)

        def read_text(self, *, encoding):
            assert self.value == "/proc/self/cgroup"
            assert encoding == "ascii"
            return "0::/system.slice/foreign.service\n"

    monkeypatch.setattr(module, "Path", SyntheticPath)

    assert module._unit_memory_events("a" * 64) is None


def test_failure_diagnostics_are_emitted_before_cleanup_unwinds(capsys):
    module = _load_harness()

    with pytest.raises(AssertionError, match="original failure"):
        module._raise_qualification_failure(
            RuntimeError("original failure"), "main_process_observed=no"
        )

    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == (
        "QUALIFICATION_FAILURE_DIAGNOSTICS\nmain_process_observed=no\n"
    )


def test_test_transport_is_only_an_absolute_private_unix_socket(tmp_path):
    module = _load_harness()
    root = tmp_path / "private"
    root.mkdir(mode=0o700)

    assert module.command_tcti(root, root / "command.sock") == (
        f"cmd:nc -q 0 -U {root / 'command.sock'}"
    )

    for unsafe in (tmp_path / "other.sock", Path("relative.sock")):
        try:
            module.command_tcti(root, unsafe)
        except ValueError:
            pass
        else:
            raise AssertionError("unsafe qualification socket was admitted")


def _write_unit_config(module, root, mode):
    (root / "requests").mkdir(mode=0o700)
    profile = root / "profile.json"
    profile.write_text("{}\n", encoding="utf-8")
    profile.chmod(0o600)
    module._write_private_json(
        root / "qualification.json",
        {
            "schema": module._QUALIFICATION_SCHEMA,
            "mode": mode,
            "state": str(root / "tpm-state"),
            "backend_marker": str(root / "backend-opened"),
            "checkpoint": None,
        },
    )
    return profile


def test_unit_refusal_uses_production_runtime_check_before_test_backend(
    tmp_path, monkeypatch
):
    module = _load_harness()
    tmp_path.chmod(0o700)
    profile_path = _write_unit_config(module, tmp_path, "no-custody")
    calls = []

    class Refused(RuntimeError):
        pass

    def execute(_profile, request_id, **kwargs):
        calls.append((request_id, set(kwargs)))
        assert "runtime_check" not in kwargs
        raise Refused("controlled live admission refusal")

    supervisor = SimpleNamespace(
        SupervisionRefused=Refused,
        load_profile=lambda path: SimpleNamespace(path=path),
        execute_request=execute,
    )
    monkeypatch.setattr(module, "_supervisor", lambda: supervisor)
    monkeypatch.setattr(
        module,
        "_load",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("runtime refusal loaded the helper")
        ),
    )

    assert module.unit_execute("a" * 64, profile_path) == 1
    assert calls == [("a" * 64, {"backend_factory"})]
    assert not (tmp_path / "backend-opened").exists()


def test_unit_positive_dispatch_keeps_real_admission_and_injects_only_transport(
    tmp_path, monkeypatch
):
    module = _load_harness()
    tmp_path.chmod(0o700)
    profile_path = _write_unit_config(module, tmp_path, "prepare")
    events = []
    backend = object()
    custody = SimpleNamespace(EsapiCustodyExecutor=object)

    def execute(_profile, request_id, **kwargs):
        events.append(("execute", request_id, set(kwargs)))
        assert "runtime_check" not in kwargs
        assert issubclass(
            kwargs["custody_module"].EsapiCustodyExecutor,
            custody.EsapiCustodyExecutor,
        )
        assert kwargs["backend_factory"]("/dev/tpm0") is backend

    supervisor = SimpleNamespace(
        SupervisionRefused=RuntimeError,
        load_profile=lambda _path: object(),
        execute_request=execute,
    )
    software = SimpleNamespace(
        _stop_process=lambda process: events.append(("stop", process)),
        _restore_tcti=lambda previous: events.append(("restore", previous)),
    )
    monkeypatch.setattr(module, "_supervisor", lambda: supervisor)
    monkeypatch.setattr(module, "_custody", lambda: custody)
    monkeypatch.setattr(module, "_software_tpm", lambda: software)
    monkeypatch.setattr(
        module,
        "_start_swtpm_unix",
        lambda root, state: events.append(("transport", root, state))
        or ("process", "previous", "cmd:nc -q 0 -U /run/x.sock"),
    )
    monkeypatch.setattr(module, "_ephemeral_sentinels", lambda _root: "sentinels")
    monkeypatch.setattr(
        module,
        "_verify_and_close_ephemeral",
        lambda sentinels: events.append(("sentinels", sentinels)),
    )
    monkeypatch.setattr(module, "_open_backend", lambda api, tcti: backend)

    assert module.unit_execute("b" * 64, profile_path) == 0
    assert events == [
        (
            "execute",
            "b" * 64,
            {"backend_factory", "custody_module", "helper_module"},
        ),
        ("transport", tmp_path, tmp_path / "tpm-state"),
        ("sentinels", "sentinels"),
        ("stop", "process"),
        ("restore", "previous"),
    ]


def test_unit_failure_publishes_only_bounded_stage_and_error_code(
    tmp_path, monkeypatch
):
    module = _load_harness()
    tmp_path.chmod(0o700)
    profile_path = _write_unit_config(module, tmp_path, "prepare")
    request_id = "c" * 64

    class PreparationRefused(RuntimeError):
        pass

    class PreparationQuarantined(PreparationRefused):
        pass

    class Runner:
        def __init__(self, **_kwargs):
            pass

        def run(self, _argv, *, stdin=None):
            assert stdin == b"x" * 32
            raise PreparationRefused("cryptsetup failed with exit status -9")

    class Refused(RuntimeError):
        pass

    class Executor:
        def __init__(self, _backend, *, _checkpoint=None):
            assert _checkpoint is not None
            _checkpoint("after-flush-object")

        def close(self):
            pass

    def prepare(*_args, runner, **_kwargs):
        try:
            runner.run(
                (
                    "cryptsetup",
                    "--type",
                    "luks2",
                    "--test-passphrase",
                    "--disable-keyring",
                    "--key-file",
                    "-",
                    "--keyfile-size",
                    "32",
                    "open",
                    "/private/volume.luks",
                ),
                stdin=b"x" * 32,
            )
        except PreparationRefused as exc:
            raise PreparationQuarantined(
                "sealed secret does not unlock the verified LUKS2 header"
            ) from exc

    helper = SimpleNamespace(
        PreparationRefused=PreparationRefused,
        PreparationQuarantined=PreparationQuarantined,
        SubprocessRunner=Runner,
        PrepareConfig=object,
        prepare=prepare,
    )
    custody = SimpleNamespace(EsapiCustodyExecutor=Executor)

    def execute(_profile, _request_id, **kwargs):
        runner = kwargs["helper_module"].SubprocessRunner(
            cryptsetup_path=Path("/usr/sbin/cryptsetup"),
            expected_version="2.4.3",
        )
        try:
            kwargs["helper_module"].prepare(object(), runner=runner)
        except PreparationRefused as exc:
            executor = kwargs["custody_module"].EsapiCustodyExecutor(object())
            executor.close()
            raise Refused("outer detail must not be published") from exc

    supervisor = SimpleNamespace(
        SupervisionRefused=Refused,
        load_profile=lambda _path: object(),
        execute_request=execute,
    )
    monkeypatch.setattr(module, "_supervisor", lambda: supervisor)
    monkeypatch.setattr(module, "_custody", lambda: custody)
    monkeypatch.setattr(module, "_software_tpm", lambda: SimpleNamespace())
    original_load = module._load
    monkeypatch.setattr(
        module,
        "_load",
        lambda path, name: helper
        if path.name == "arkhai-prepare-lease-storage.py"
        else original_load(path, name),
    )

    assert module.unit_execute(request_id, profile_path) == 1
    evidence = json.loads((tmp_path / "requests" / "unit-failure.json").read_text())
    assert evidence == {
        "error_code": "preparation-refused",
        "request_id": request_id,
        "schema": "arkhai.supervised-software-tpm-unit-failure.v5",
        "stage": "custody-finalized",
        "origin_stage": "helper-prepare",
        "origin_error_code": "sealed-secret-unlock-failed",
        "origin_cause_code": "cryptsetup-exit-status",
        "origin_operation": "cryptsetup-test-passphrase",
        "origin_operation_result": "signal-sigkill",
        "origin_operation_returncode": -9,
        "origin_tss2_rc": None,
        "origin_tss2_layer": "not-observed",
        "origin_tss2_subject": "not-observed",
        "unit_memory_events": None,
    }
    assert "detail" not in evidence


@pytest.mark.parametrize(
    ("rc", "expected"),
    (
        (0x00000920, (0x00000920, "tpm", "tpm-format-zero")),
        (0x000002C4, (0x000002C4, "tpm", "tpm-parameter")),
        (0x0000098E, (0x0000098E, "tpm", "tpm-session")),
        (0x0000018B, (0x0000018B, "tpm", "tpm-handle")),
        (0x000A000A, (0x000A000A, "tcti", "software-layer")),
        (0x000C0920, (0x000C0920, "resmgr-tpm", "tpm-format-zero")),
    ),
)
def test_tss2_failure_identity_preserves_numeric_rc_layer_and_tpm_subject(
    rc, expected
):
    module = _load_harness()
    tss_error = type("TSS2_Exception", (RuntimeError,), {})("private detail")
    tss_error.rc = rc
    outer = RuntimeError("outer detail")
    outer.__cause__ = tss_error

    assert module._tss2_failure_identity(outer) == expected


@pytest.mark.parametrize("rc", (True, -1, 2**32, "0x920", None))
def test_tss2_failure_identity_rejects_malformed_rc_values(rc):
    module = _load_harness()
    error = type("TSS2_Exception", (RuntimeError,), {})("private detail")
    error.rc = rc

    assert module._tss2_failure_identity(error) == (
        None,
        "not-observed",
        "not-observed",
    )


def test_unit_failure_preserves_retry_nv_read_tss2_identity(tmp_path, monkeypatch):
    module = _load_harness()
    tmp_path.chmod(0o700)
    profile_path = _write_unit_config(module, tmp_path, "prepare")
    request_id = "d" * 64

    class PreparationRefused(RuntimeError):
        pass

    class PreparationQuarantined(PreparationRefused):
        pass

    class Refused(RuntimeError):
        pass

    class Executor:
        pass

    tss_error = type("TSS2_Exception", (RuntimeError,), {})("private TPM detail")
    tss_error.rc = 0x00000920
    custody_error = RuntimeError("private custody detail")
    custody_error.__cause__ = tss_error

    def prepare(*_args, **_kwargs):
        error = PreparationQuarantined("NV counter read failed")
        error.__cause__ = custody_error
        raise error

    helper = SimpleNamespace(
        PreparationRefused=PreparationRefused,
        PreparationQuarantined=PreparationQuarantined,
        SubprocessRunner=object,
        PrepareConfig=object,
        prepare=prepare,
    )

    def execute(_profile, _request_id, **kwargs):
        try:
            kwargs["helper_module"].prepare(object())
        except PreparationRefused as exc:
            raise Refused("outer detail must not be published") from exc

    supervisor = SimpleNamespace(
        SupervisionRefused=Refused,
        load_profile=lambda _path: object(),
        execute_request=execute,
    )
    monkeypatch.setattr(module, "_supervisor", lambda: supervisor)
    monkeypatch.setattr(
        module, "_custody", lambda: SimpleNamespace(EsapiCustodyExecutor=Executor)
    )
    monkeypatch.setattr(module, "_software_tpm", lambda: SimpleNamespace())
    original_load = module._load
    monkeypatch.setattr(
        module,
        "_load",
        lambda path, name: helper
        if path.name == "arkhai-prepare-lease-storage.py"
        else original_load(path, name),
    )

    assert module.unit_execute(request_id, profile_path) == 1
    evidence = json.loads((tmp_path / "requests" / "unit-failure.json").read_text())
    assert evidence["origin_error_code"] == "nv-counter-read-failed"
    assert evidence["origin_cause_code"] == "nv-counter-read-failed"
    assert evidence["origin_tss2_rc"] == 0x00000920
    assert evidence["origin_tss2_layer"] == "tpm"
    assert evidence["origin_tss2_subject"] == "tpm-format-zero"
    assert "private" not in json.dumps(evidence)


def test_prepared_retry_precedes_cli_authorized_inspection(tmp_path, monkeypatch):
    module = _load_harness()
    software = module._software_tpm()
    events = []
    durable = {
        "persistent_handle": "0x81000030",
        "persistent_name": b"persistent-name",
        "nv_index": "0x1500030",
        "nv_value": b"sentinel",
    }

    def controlled_run(argv, **_kwargs):
        command = tuple(str(value) for value in argv)
        events.append(command)
        if command[0] == "tpm2_readpublic":
            Path(command[command.index("-n") + 1]).write_bytes(
                durable["persistent_name"]
            )
        elif command[0] == "tpm2_nvread":
            output = Path(command[command.index("-o") + 1])
            output.write_bytes(
                durable["nv_value"]
                if command[-1] == durable["nv_index"]
                else (2).to_bytes(8, "big")
            )
        return subprocess.CompletedProcess(command, 0, b"", b"")

    monkeypatch.setattr(software, "_run", controlled_run)
    monkeypatch.setattr(software.time, "monotonic_ns", lambda: 41)
    monkeypatch.setattr(module, "_software_tpm", lambda: software)
    monkeypatch.setattr(
        module,
        "_start_swtpm_unix",
        lambda root, state: ("process", "previous", "test-tcti"),
    )
    monkeypatch.setattr(
        software,
        "_stop_process",
        lambda process: events.append(("stop", process)),
    )
    monkeypatch.setattr(
        software,
        "_restore_tcti",
        lambda previous: events.append(("restore", previous)),
    )

    receipt, counter = module._validated_retry_then_inspect(
        lambda: events.append(("submit", "prepared-retry")) or {"state": "prepared"},
        lambda value: events.append(("validate", value["state"])),
        lambda: module._inspect_tpm(tmp_path, durable),
    )

    assert receipt == {"state": "prepared"}
    assert counter == 2
    assert events == [
        ("submit", "prepared-retry"),
        ("validate", "prepared"),
        (
            "tpm2_readpublic",
            "-c",
            "0x81000030",
            "-n",
            str(tmp_path / "foreign-restart-name-41"),
        ),
        (
            "tpm2_nvread",
            "-C",
            "o",
            "-s",
            "8",
            "-o",
            str(tmp_path / "foreign-restart-nv-41"),
            "0x1500030",
        ),
        (
            "tpm2_nvread",
            "-C",
            "o",
            "-s",
            "8",
            "-o",
            str(tmp_path / "counter-41"),
            "0x1500020",
        ),
        ("stop", "process"),
        ("restore", "previous"),
    ]


@pytest.mark.skipif(
    os.environ.get("ARKHAI_RUN_SUPERVISED_SOFTWARE_TPM") != "1",
    reason="requires a reviewed disposable systemd/software-TPM container",
)
def test_real_systemd_supervisor_esapi_luks_composition():
    module = _load_harness()

    assert module.qualify()["state"] == "qualified"
