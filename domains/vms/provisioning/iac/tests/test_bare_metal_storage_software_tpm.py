"""Opt-in custody qualification against a disposable software TPM.

This test creates only temporary software-TPM state and a regular backing file.
It never opens a dm-crypt mapping, mounts a filesystem, or accesses a host TPM
or block device.  Routine test runs collect it as an explicit skip; a reviewed
isolated tool container enables it with ``ARKHAI_RUN_SOFTWARE_TPM_CUSTODY=1``.
"""

from __future__ import annotations

import importlib.util
import json
import os
import re
import socket
import stat
import struct
import subprocess
import sys
import tempfile
import time
from pathlib import Path

try:
    import pytest
except ModuleNotFoundError:  # The reviewed tool image need not carry the test runner.
    pytest = None


HELPER = (
    Path(__file__).resolve().parents[1]
    / "ansible"
    / "roles"
    / "bare-metal-access"
    / "files"
    / "arkhai-prepare-lease-storage.py"
)
CUSTODY = HELPER.with_name("arkhai_tpm_esapi_custody.py")
RUN = os.environ.get("ARKHAI_RUN_SOFTWARE_TPM_CUSTODY") == "1"
TPM2_TOOLS_MAGIC = 0xBADCC0DE
_TOOLS_52_COMMANDS = frozenset(
    {
        "tpm2_createprimary",
        "tpm2_evictcontrol",
        "tpm2_flushcontext",
        "tpm2_getcap",
        "tpm2_getpolicydigest",
        "tpm2_nvdefine",
        "tpm2_nvincrement",
        "tpm2_nvread",
        "tpm2_nvwrite",
        "tpm2_readpublic",
        "tpm2_startauthsession",
        "tpm2_startup",
    }
)


def _requires_reviewed_probe(test):
    if pytest is None:
        return test
    return pytest.mark.skipif(
        not RUN,
        reason=(
            "set ARKHAI_RUN_SOFTWARE_TPM_CUSTODY=1 in a reviewed disposable "
            "tool container"
        ),
    )(test)


def _load_helper():
    spec = importlib.util.spec_from_file_location("software_tpm_lease_storage", HELPER)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _load_custody():
    spec = importlib.util.spec_from_file_location("software_tpm_esapi_custody", CUSTODY)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _port_pair() -> tuple[int, int]:
    for _ in range(100):
        with socket.socket() as command_listener:
            command_listener.bind(("127.0.0.1", 0))
            command_port = command_listener.getsockname()[1]
            if command_port == 65535:
                continue
            try:
                with socket.socket() as control_listener:
                    control_listener.bind(("127.0.0.1", command_port + 1))
            except OSError:
                continue
            return command_port, command_port + 1
    raise RuntimeError("cannot reserve adjacent software-TPM ports")


def _run(argv, *, input_bytes=None, check=True, timeout=15):
    command = Path(str(argv[0])).name
    if command.startswith("tpm2_") and command not in _TOOLS_52_COMMANDS:
        raise AssertionError(f"unaudited tpm2-tools 5.2 command: {command}")
    return subprocess.run(
        argv,
        input=input_bytes,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=check,
        timeout=timeout,
    )


def _raw_primary_handle(context: Path) -> str:
    flags = os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW
    try:
        descriptor = os.open(context, flags)
    except OSError as exc:
        raise AssertionError(
            "generated primary context is not safely readable"
        ) from exc
    try:
        metadata = os.fstat(descriptor)
        if (
            not stat.S_ISREG(metadata.st_mode)
            or metadata.st_uid != os.geteuid()
            or metadata.st_nlink != 1
            or metadata.st_size < 27
            or metadata.st_size > 65536
        ):
            raise AssertionError("generated primary context has unsafe metadata")
        raw = os.read(descriptor, metadata.st_size + 1)
        if len(raw) != metadata.st_size:
            raise AssertionError(
                "generated primary context length changed while reading"
            )
    finally:
        os.close(descriptor)

    magic, version, hierarchy, handle, _sequence, blob_size = struct.unpack_from(
        ">IIIIQH", raw, 0
    )
    if magic != TPM2_TOOLS_MAGIC or version != 1:
        raise AssertionError("generated primary context has unsupported header")
    if hierarchy != 0x40000001:
        raise AssertionError("generated primary context has the wrong hierarchy")
    if handle >> 24 != 0x80:
        raise AssertionError("generated primary context is not a transient object")
    if blob_size < 1 or len(raw) != 26 + blob_size:
        raise AssertionError("generated primary context length is inconsistent")
    return f"0x{handle:08x}"


def _session_handle(context: Path) -> str:
    raw = context.read_bytes()
    if len(raw) < 38:
        raise AssertionError("generated session context is too short")
    magic, version = struct.unpack_from(">II", raw, 0)
    session_type = raw[8]
    auth_hash = struct.unpack_from(">H", raw, 9)[0]
    nested_magic, nested_version, hierarchy, handle = struct.unpack_from(
        ">IIII", raw, 11
    )
    blob_size = struct.unpack_from(">H", raw, 35)[0]
    if (
        magic != TPM2_TOOLS_MAGIC
        or version != 2
        or session_type not in (0, 1, 3)
        or auth_hash != 0x000B
        or nested_magic != TPM2_TOOLS_MAGIC
        or nested_version != 1
        or hierarchy != 0x40000007
        or handle >> 24 not in (0x02, 0x03)
        or blob_size < 1
        or len(raw) != 37 + blob_size
    ):
        raise AssertionError("generated session context has unsupported metadata")
    return f"0x{handle:08x}"


def _provision_foreign_sentinels(tmp_path: Path) -> dict[str, object]:
    object_context = tmp_path / "foreign-object.ctx"
    _run(
        [
            "tpm2_createprimary", "-C", "o", "-g", "sha256", "-G", "rsa",
            "-c", str(object_context),
        ]
    )
    object_handle = _raw_primary_handle(object_context)
    persistent_handle = "0x81000030"
    _run(["tpm2_evictcontrol", "-C", "o", "-c", object_handle, persistent_handle])
    persistent_name = tmp_path / "foreign-persistent.name"
    _run(["tpm2_readpublic", "-c", persistent_handle, "-n", str(persistent_name)])

    session_context = tmp_path / "foreign-session.ctx"
    _run(["tpm2_startauthsession", "-S", str(session_context)])
    session_handle = _session_handle(session_context)

    nv_index = "0x1500030"
    nv_value = b"sentinel"
    _run(
        [
            "tpm2_nvdefine", "-C", "o", "-s", "8", "-a",
            "ownerread|ownerwrite|authread|authwrite", nv_index,
        ]
    )
    _run(["tpm2_nvwrite", "-i", "-", nv_index], input_bytes=nv_value)
    return {
        "object_handle": object_handle,
        "persistent_handle": persistent_handle,
        "persistent_name": persistent_name.read_bytes(),
        "session_context": session_context,
        "session_handle": session_handle,
        "nv_index": nv_index,
        "nv_value": nv_value,
    }


def _verify_foreign_sentinels(tmp_path: Path, sentinels) -> None:
    _run(["tpm2_readpublic", "-c", sentinels["object_handle"]])
    _run(["tpm2_getpolicydigest", "-S", str(sentinels["session_context"])])
    name = tmp_path / f"foreign-name-{time.monotonic_ns()}"
    _run(["tpm2_readpublic", "-c", sentinels["persistent_handle"], "-n", str(name)])
    assert name.read_bytes() == sentinels["persistent_name"]
    value = tmp_path / f"foreign-nv-{time.monotonic_ns()}"
    _run(
        [
            "tpm2_nvread",
            "-C",
            "o",
            "-s",
            "8",
            "-o",
            str(value),
            sentinels["nv_index"],
        ]
    )
    assert value.read_bytes() == sentinels["nv_value"]


def _verify_durable_foreign_sentinels(tmp_path: Path, sentinels) -> None:
    name = tmp_path / f"foreign-restart-name-{time.monotonic_ns()}"
    _run(["tpm2_readpublic", "-c", sentinels["persistent_handle"], "-n", str(name)])
    assert name.read_bytes() == sentinels["persistent_name"]
    value = tmp_path / f"foreign-restart-nv-{time.monotonic_ns()}"
    _run(
        [
            "tpm2_nvread",
            "-C",
            "o",
            "-s",
            "8",
            "-o",
            str(value),
            sentinels["nv_index"],
        ]
    )
    assert value.read_bytes() == sentinels["nv_value"]


def test_foreign_sentinel_verification_uses_supported_tools_52_argv(
    tmp_path, monkeypatch
):
    calls = []
    sentinels = {
        "object_handle": "0x80000001",
        "session_context": tmp_path / "foreign-session.ctx",
        "persistent_handle": "0x81000030",
        "persistent_name": b"persistent-name",
        "nv_index": "0x1500030",
        "nv_value": b"sentinel",
    }

    def controlled_run(argv, **_kwargs):
        command = tuple(str(value) for value in argv)
        calls.append(command)
        if command[0] == "tpm2_readpublic" and "-n" in command:
            Path(command[command.index("-n") + 1]).write_bytes(
                sentinels["persistent_name"]
            )
        elif command[0] == "tpm2_nvread":
            Path(command[command.index("-o") + 1]).write_bytes(
                sentinels["nv_value"]
            )
        return subprocess.CompletedProcess(command, 0, b"", b"")

    monkeypatch.setattr(sys.modules[__name__], "_run", controlled_run)
    monkeypatch.setattr(time, "monotonic_ns", lambda: 41)

    _verify_foreign_sentinels(tmp_path, sentinels)

    assert calls == [
        ("tpm2_readpublic", "-c", "0x80000001"),
        (
            "tpm2_getpolicydigest",
            "-S",
            str(sentinels["session_context"]),
        ),
        (
            "tpm2_readpublic",
            "-c",
            "0x81000030",
            "-n",
            str(tmp_path / "foreign-name-41"),
        ),
        (
            "tpm2_nvread",
            "-C",
            "o",
            "-s",
            "8",
            "-o",
            str(tmp_path / "foreign-nv-41"),
            "0x1500030",
        ),
    ]


_HANDLE_OBSERVATION = re.compile(r"- 0x([0-9a-fA-F]{8})")


def _parse_handle_observation(raw: bytes) -> tuple[str, ...]:
    try:
        lines = raw.decode("ascii").splitlines()
    except UnicodeDecodeError as exc:
        raise AssertionError("TPM handle inventory is not ASCII") from exc
    handles = []
    for line in lines:
        if not line.strip():
            continue
        match = _HANDLE_OBSERVATION.fullmatch(line.strip())
        if match is None:
            raise AssertionError("TPM handle inventory has an unsupported shape")
        handles.append(f"0x{int(match.group(1), 16):08x}")
    if len(handles) != len(set(handles)):
        raise AssertionError("TPM handle inventory contains duplicates")
    return tuple(handles)


def _observe_transient_handles(
    observations: list[dict[str, object]], stage: str
) -> tuple[str, ...]:
    handles = _parse_handle_observation(
        _run(["tpm2_getcap", "handles-transient"]).stdout
    )
    observation = {"stage": stage, "transient_handles": list(handles)}
    observations.append(observation)
    if RUN:
        print(
            "TPM_RESOURCE_OBSERVATION " + json.dumps(observation, sort_keys=True),
            file=sys.stderr,
            flush=True,
        )
    return handles


def _provision_persistent_parent(
    tmp_path: Path, parent_handle: str
) -> tuple[Path, list[dict[str, object]]]:
    observations: list[dict[str, object]] = []
    if _observe_transient_handles(observations, "before-primary"):
        raise AssertionError("disposable TPM did not start without transient objects")

    primary = tmp_path / "primary.ctx"
    if primary.exists() or primary.is_symlink():
        raise AssertionError("primary context path is not fresh")
    _run(
        [
            "tpm2_createprimary",
            "-C",
            "o",
            "-g",
            "sha256",
            "-G",
            "rsa",
            "-a",
            "restricted|decrypt|fixedtpm|fixedparent|sensitivedataorigin|userwithauth",
            "-c",
            str(primary),
        ]
    )
    primary_handle = _raw_primary_handle(primary)
    owned_observed = False
    try:
        after_create = _observe_transient_handles(observations, "after-createprimary")
        if after_create != (primary_handle,):
            raise AssertionError(
                "createprimary did not leave exactly its recorded transient object"
            )
        owned_observed = True

        # A raw context path would be loaded again by a later tool process.
        # Direct TCTI keeps the original handle resident, so use that exact
        # owned handle to persist it without consuming another object slot.
        _run(
            [
                "tpm2_evictcontrol",
                "-C",
                "o",
                "-c",
                primary_handle,
                parent_handle,
            ]
        )
        if _observe_transient_handles(observations, "after-evictcontrol") != (
            primary_handle,
        ):
            raise AssertionError("persisting the primary changed transient ownership")

        parent_name_path = tmp_path / "parent.name"
        if parent_name_path.exists() or parent_name_path.is_symlink():
            raise AssertionError("parent Name path is not fresh")
        _run(["tpm2_readpublic", "-c", parent_handle, "-n", str(parent_name_path)])
    finally:
        if owned_observed:
            _run(["tpm2_flushcontext", primary_handle])
            if _observe_transient_handles(observations, "after-primary-flush"):
                raise AssertionError("owned primary cleanup left a transient object")

    return parent_name_path, observations


def test_raw_primary_context_parser_accepts_a_saved_transient_object(tmp_path):
    context = tmp_path / "primary.ctx"
    blob = b"synthetic-primary-context"
    context.write_bytes(
        struct.pack(
            ">IIIIQH",
            TPM2_TOOLS_MAGIC,
            1,
            0x40000001,
            0x80000007,
            19,
            len(blob),
        )
        + blob
    )

    assert _raw_primary_handle(context) == "0x80000007"


def test_raw_primary_context_parser_rejects_wrong_kind_and_trailing_bytes(tmp_path):
    context = tmp_path / "primary.ctx"
    blob = b"synthetic-primary-context"
    context.write_bytes(
        struct.pack(
            ">IIIIQH",
            TPM2_TOOLS_MAGIC,
            1,
            0x40000001,
            0x03000000,
            19,
            len(blob),
        )
        + blob
    )

    with pytest.raises(AssertionError, match="transient object"):
        _raw_primary_handle(context)

    context.write_bytes(
        struct.pack(
            ">IIIIQH",
            TPM2_TOOLS_MAGIC,
            1,
            0x40000001,
            0x80000007,
            19,
            len(blob),
        )
        + blob
        + b"trailing"
    )
    with pytest.raises(AssertionError, match="length"):
        _raw_primary_handle(context)


def test_session_sentinel_parser_requires_the_complete_tools_wrapper(tmp_path):
    context = tmp_path / "session.ctx"
    blob = b"synthetic-session"
    context.write_bytes(
        struct.pack(">IIBH", TPM2_TOOLS_MAGIC, 2, 0, 0x000B)
        + struct.pack(
            ">IIIIQH", TPM2_TOOLS_MAGIC, 1, 0x40000007, 0x02000001, 7, len(blob)
        )
        + blob
    )
    assert _session_handle(context) == "0x02000001"

    context.write_bytes(context.read_bytes() + b"trailing")
    with pytest.raises(AssertionError, match="unsupported metadata"):
        _session_handle(context)

def test_transient_handle_observation_parser_requires_cli_shape():
    assert _parse_handle_observation(b"- 0x80000000\n- 0x80000002\n") == (
        "0x80000000",
        "0x80000002",
    )

    with pytest.raises(AssertionError, match="handle inventory"):
        _parse_handle_observation(b"saved-handle: 0x80000000\n")


def test_direct_tcti_parent_provisioning_flushes_only_its_saved_handle(
    tmp_path, monkeypatch
):
    resident: list[str] = []
    calls = []

    def controlled_run(argv, **kwargs):
        argv = tuple(str(value) for value in argv)
        calls.append(argv)
        if argv[:2] == ("tpm2_getcap", "handles-transient"):
            stdout = "".join(f"- {handle}\n" for handle in resident).encode()
        elif argv[0] == "tpm2_createprimary":
            context = Path(argv[argv.index("-c") + 1])
            blob = b"synthetic-primary-context"
            context.write_bytes(
                struct.pack(
                    ">IIIIQH",
                    TPM2_TOOLS_MAGIC,
                    1,
                    0x40000001,
                    0x80000007,
                    19,
                    len(blob),
                )
                + blob
            )
            resident.append("0x80000007")
            stdout = b""
        elif argv[0] == "tpm2_evictcontrol":
            assert argv[argv.index("-c") + 1] == "0x80000007"
            stdout = b""
        elif argv[0] == "tpm2_readpublic":
            Path(argv[argv.index("-n") + 1]).write_bytes(b"parent-name")
            stdout = b""
        elif argv == ("tpm2_flushcontext", "0x80000007"):
            resident.remove("0x80000007")
            stdout = b""
        else:
            raise AssertionError(f"unexpected command: {argv}")
        return subprocess.CompletedProcess(argv, 0, stdout, b"")

    monkeypatch.setattr(sys.modules[__name__], "_run", controlled_run)

    name_path, observations = _provision_persistent_parent(tmp_path, "0x81000020")

    assert name_path.read_bytes() == b"parent-name"
    assert observations == [
        {"stage": "before-primary", "transient_handles": []},
        {"stage": "after-createprimary", "transient_handles": ["0x80000007"]},
        {"stage": "after-evictcontrol", "transient_handles": ["0x80000007"]},
        {"stage": "after-primary-flush", "transient_handles": []},
    ]
    assert all(
        "primary.ctx" not in call for call in calls if call[0] == "tpm2_evictcontrol"
    )
    assert [call for call in calls if call[0] == "tpm2_flushcontext"] == [
        ("tpm2_flushcontext", "0x80000007")
    ]


def _stop_process(process, *, timeout=2) -> bytes:
    process.terminate()
    try:
        _, stderr = process.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        process.kill()
        _, stderr = process.communicate(timeout=timeout)
    return stderr or b""


def _restore_tcti(previous_tcti: str | None) -> None:
    if previous_tcti is None:
        os.environ.pop("TPM2TOOLS_TCTI", None)
    else:
        os.environ["TPM2TOOLS_TCTI"] = previous_tcti


def _start_swtpm(tmp_path: Path, *, startup_timeout=5, state=None):
    command_port, control_port = _port_pair()
    state = state or tmp_path / "swtpm"
    state.mkdir(mode=0o700, exist_ok=True)
    process = subprocess.Popen(
        [
            "swtpm",
            "socket",
            "--tpm2",
            f"--tpmstate=dir={state}",
            f"--server=type=tcp,port={command_port},bindaddr=127.0.0.1",
            f"--ctrl=type=tcp,port={control_port},bindaddr=127.0.0.1",
            "--flags=not-need-init,startup-clear",
        ],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
    )
    tcti = f"swtpm:host=127.0.0.1,port={command_port}"
    previous_tcti = os.environ.get("TPM2TOOLS_TCTI")
    os.environ["TPM2TOOLS_TCTI"] = tcti
    deadline = time.monotonic() + startup_timeout
    try:
        while True:
            started = _run(["tpm2_startup", "-c"], check=False, timeout=1)
            if started.returncode == 0:
                return process, previous_tcti, tcti, state
            if process.poll() is not None or time.monotonic() >= deadline:
                raise AssertionError("disposable swtpm did not start")
            time.sleep(0.05)
    except BaseException as exc:
        try:
            stderr = _stop_process(process).decode(errors="replace")
        finally:
            _restore_tcti(previous_tcti)
        if isinstance(exc, AssertionError):
            raise AssertionError(f"{exc}: {stderr}") from exc
        raise


def test_software_tpm_uses_the_control_port_adjacent_to_its_command_port(monkeypatch):
    bindings = []

    class Listener:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def bind(self, address):
            bindings.append(address)

        @staticmethod
        def getsockname():
            return "127.0.0.1", 31000

    monkeypatch.setattr(socket, "socket", Listener)
    command_port, control_port = _port_pair()

    assert control_port == command_port + 1
    assert bindings == [("127.0.0.1", 0), ("127.0.0.1", 31001)]


def test_failed_software_tpm_startup_terminates_reaps_and_restores_environment(
    tmp_path, monkeypatch
):
    events = []

    class Process:
        stderr = object()

        @staticmethod
        def poll():
            return None

        @staticmethod
        def terminate():
            events.append("terminate")

        @staticmethod
        def communicate(*, timeout):
            events.append(("communicate", timeout))
            return b"", b"startup failed"

    process = Process()
    monkeypatch.setattr(subprocess, "Popen", lambda *args, **kwargs: process)
    monkeypatch.setattr(sys.modules[__name__], "_port_pair", lambda: (31000, 31001))
    monkeypatch.setattr(
        sys.modules[__name__],
        "_run",
        lambda argv, **kwargs: subprocess.CompletedProcess(argv, 1, b"", b"failed"),
    )
    moments = iter((0.0, 1.0))
    monkeypatch.setattr(time, "monotonic", lambda: next(moments))
    monkeypatch.setenv("TPM2TOOLS_TCTI", "prior:tcti")

    with pytest.raises(AssertionError, match="startup failed"):
        _start_swtpm(tmp_path, startup_timeout=0.5)

    assert events == ["terminate", ("communicate", 2)]
    assert os.environ["TPM2TOOLS_TCTI"] == "prior:tcti"


def test_timed_out_software_tpm_startup_still_reaps_and_restores_environment(
    tmp_path, monkeypatch
):
    events = []

    class Process:
        @staticmethod
        def terminate():
            events.append("terminate")

        @staticmethod
        def communicate(*, timeout):
            events.append(("communicate", timeout))
            return b"", b"timed out"

    monkeypatch.setattr(subprocess, "Popen", lambda *args, **kwargs: Process())
    monkeypatch.setattr(sys.modules[__name__], "_port_pair", lambda: (31000, 31001))

    def time_out(*args, **kwargs):
        raise subprocess.TimeoutExpired("tpm2_startup", 1)

    monkeypatch.setattr(sys.modules[__name__], "_run", time_out)
    monkeypatch.setenv("TPM2TOOLS_TCTI", "prior:tcti")

    with pytest.raises(subprocess.TimeoutExpired):
        _start_swtpm(tmp_path)

    assert events == ["terminate", ("communicate", 2)]
    assert os.environ["TPM2TOOLS_TCTI"] == "prior:tcti"


def test_software_tpm_cleanup_escalates_only_the_owned_process_and_reaps():
    events = []

    class Process:
        attempts = 0

        @staticmethod
        def terminate():
            events.append("terminate")

        @staticmethod
        def kill():
            events.append("kill")

        def communicate(self, *, timeout):
            self.attempts += 1
            events.append(("communicate", timeout))
            if self.attempts == 1:
                raise subprocess.TimeoutExpired("swtpm", timeout)
            return b"", b"stopped"

    assert _stop_process(Process(), timeout=0.25) == b"stopped"
    assert events == [
        "terminate",
        ("communicate", 0.25),
        "kill",
        ("communicate", 0.25),
    ]


class _MemoryRecorder:
    """Non-durable probe recorder used only after the helper path is complete."""

    def __init__(self):
        self.records = []

    def pending(self, kind, purpose):
        record = {"kind": kind, "purpose": purpose, "state": "pending"}
        self.records.append(record)
        return record

    @staticmethod
    def live(record, handle):
        record.update(state="live", handle=f"0x{handle:08x}")

    @staticmethod
    def close_pending(record):
        record["state"] = "close_pending"

    @staticmethod
    def closed(record):
        record["state"] = "confirmed_closed"


def _open_test_executor(custody_module, tcti_config, parent_handle, nv_index):
    import tpm2_pytss

    name, configuration = tcti_config.split(":", 1)
    if name != "swtpm":
        raise AssertionError("qualification may inject only its disposable swtpm TCTI")
    tcti = tpm2_pytss.TCTILdr(name, configuration)
    backend = custody_module.PytssBackend.for_test_transport(
        tcti, pytss=tpm2_pytss
    )
    backend.bind(
        parent_handle=int(parent_handle, 16), nv_index=int(nv_index, 16)
    )
    return custody_module.EsapiCustodyExecutor(backend)


def _run_kill_child(specification) -> None:
    helper = _load_helper()
    custody_module = _load_custody()

    def checkpoint(event):
        if event == specification["checkpoint"]:
            os._exit(97)

    config = helper.PrepareConfig(
        **{
            **specification["config"],
            "state_root": Path(specification["config"]["state_root"]),
        }
    )
    executor = _open_test_executor(
        custody_module,
        specification["tcti"],
        config.parent_handle,
        config.nv_index,
    )
    executor._checkpoint = checkpoint
    helper.prepare(
        config,
        runner=helper.SubprocessRunner(),
        custody=executor,
    )
    raise AssertionError("selected kill checkpoint was not reached")


def _read_counter_for_probe(tmp_path: Path, nv_index: str) -> int:
    output = tmp_path / f"counter-{time.monotonic_ns()}"
    _run(["tpm2_nvread", "-C", "o", "-s", "8", "-o", str(output), nv_index])
    raw = output.read_bytes()
    assert len(raw) == 8
    return int.from_bytes(raw, "big")


def _qualify_process_kill_checkpoints(tmp_path: Path) -> dict[str, object]:
    helper = _load_helper()
    checkpoints = (
        "after-policy-session-create",
        "after-object-load",
        "after-unseal",
        "after-flush-session",
        "after-flush-object",
    )
    for checkpoint in checkpoints:
        case = tmp_path / checkpoint
        case.mkdir(mode=0o700)
        process, previous_tcti, tcti, _ = _start_swtpm(case)
        nv_index = "0x1500020"
        parent_handle = "0x81000020"
        try:
            _run(
                [
                    "tpm2_nvdefine", "-C", "o", "-s", "8", "-a",
                    "ownerread|ownerwrite|authread|authwrite|nt=counter", nv_index,
                ]
            )
            _run(["tpm2_nvincrement", nv_index])
            parent_name_path, _ = _provision_persistent_parent(case, parent_handle)
            config_values = {
                "state_root": str(case / "lease-state"),
                "host_id": "kill-checkpoint-host",
                "machine_id": "kill-checkpoint-machine",
                "generation": f"generation-{checkpoint}",
                "backing_size": 32 * 1024 * 1024,
                "free_space_floor": 1024 * 1024,
                "nv_index": nv_index,
                "counter_headroom": 16,
                "parent_handle": parent_handle,
                "parent_name": parent_name_path.read_bytes().hex(),
                "required_uid": os.geteuid(),
            }
            child_environment = os.environ.copy()
            child_environment["ARKHAI_CUSTODY_CHILD_SPEC"] = json.dumps(
                {"checkpoint": checkpoint, "config": config_values, "tcti": tcti}
            )
            child = subprocess.run(
                [sys.executable, str(Path(__file__).resolve())],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=child_environment,
                check=False,
                close_fds=True,
                timeout=30,
            )
            assert child.returncode == 97
            assert child.stdout == b""
            counter_before = _read_counter_for_probe(case, nv_index)

            class NoTpmAfterRestart:
                def __getattr__(self, name):
                    raise AssertionError(f"retry attempted stale TPM operation: {name}")

            config = helper.PrepareConfig(
                **{**config_values, "state_root": Path(config_values["state_root"])}
            )
            try:
                helper.prepare(
                    config,
                    runner=helper.SubprocessRunner(),
                    custody=NoTpmAfterRestart(),
                )
            except helper.PreparationQuarantined as exc:
                assert "ownership" in str(exc)
            else:
                raise AssertionError("uncertain prior lifetime was not quarantined")
            assert _read_counter_for_probe(case, nv_index) == counter_before
        finally:
            try:
                _stop_process(process)
            finally:
                _restore_tcti(previous_tcti)
    return {
        "checkpoints": list(checkpoints),
        "counter_readvances": 0,
        "stale_handle_flushes": 0,
        "state": "qualified",
    }


@_requires_reviewed_probe
def test_process_kill_checkpoints_quarantine_without_stale_cleanup_or_readvance(tmp_path):
    assert _qualify_process_kill_checkpoints(tmp_path)["state"] == "qualified"


def _qualify_esapi_custody(tmp_path: Path) -> dict[str, object]:
    helper = _load_helper()
    custody_module = _load_custody()
    process, previous_tcti, tcti, state = _start_swtpm(tmp_path)
    nv_index = "0x1500020"
    parent_handle = "0x81000020"
    try:
        _run(
            [
                "tpm2_nvdefine", "-C", "o", "-s", "8", "-a",
                "ownerread|ownerwrite|authread|authwrite|nt=counter", nv_index,
            ]
        )
        _run(["tpm2_nvincrement", nv_index])
        parent_name_path, observations = _provision_persistent_parent(
            tmp_path, parent_handle
        )
        sentinels = _provision_foreign_sentinels(tmp_path)
        config = helper.PrepareConfig(
            state_root=tmp_path / "lease-state",
            host_id="software-tpm-host",
            machine_id="software-tpm-machine",
            generation="software-tpm-generation-1",
            backing_size=32 * 1024 * 1024,
            free_space_floor=1024 * 1024,
            nv_index=nv_index,
            counter_headroom=16,
            parent_handle=parent_handle,
            parent_name=parent_name_path.read_bytes().hex(),
            required_uid=os.geteuid(),
        )

        executor = _open_test_executor(
            custody_module, tcti, parent_handle, nv_index
        )
        receipt = helper.prepare(
            config,
            runner=helper.SubprocessRunner(),
            custody=executor,
        )
        assert receipt["state"] == "prepared" and receipt["counter"] == 2

        retry_executor = _open_test_executor(
            custody_module, tcti, parent_handle, nv_index
        )
        assert helper.prepare(
            config,
            runner=helper.SubprocessRunner(),
            custody=retry_executor,
        ) == receipt
        _verify_foreign_sentinels(tmp_path, sentinels)
        _run(["tpm2_flushcontext", sentinels["session_handle"]])
        _run(["tpm2_flushcontext", sentinels["object_handle"]])

        process_stderr = _stop_process(process)
        process = None
        _restore_tcti(previous_tcti)
        process, previous_tcti, tcti, _ = _start_swtpm(
            tmp_path, state=state
        )
        _verify_durable_foreign_sentinels(tmp_path, sentinels)
        restart_executor = _open_test_executor(
            custody_module, tcti, parent_handle, nv_index
        )
        assert helper.prepare(
            config,
            runner=helper.SubprocessRunner(),
            custody=restart_executor,
        ) == receipt

        revoke = _open_test_executor(custody_module, tcti, parent_handle, nv_index)
        revoke.increment_counter()
        lease_dir = config.state_root / "leases" / config.generation
        recorder = _MemoryRecorder()
        try:
            revoke.recover_and_verify(
                private_blob=(lease_dir / "sealed.priv").read_bytes(),
                public_blob=(lease_dir / "sealed.pub").read_bytes(),
                expected_policy=(lease_dir / "policy.nv").read_bytes(),
                counter=receipt["counter"],
                recorder=recorder,
            )
        except custody_module.CustodyUncertain:
            pass
        else:
            raise AssertionError("revoked sealed blobs were accepted")
        finally:
            revoke.close()
        assert recorder.records and all(
            record["state"] == "confirmed_closed" for record in recorder.records
        )
        return {
            "counter_after_revocation": 3,
            "emulator_restart_recovered_from_blobs": True,
            "foreign_sentinels_preserved": True,
            "luks_target": "disposable regular file",
            "physical_tpm_used": False,
            "primary_resource_observations": observations,
            "process_stderr_bytes": len(process_stderr),
            "retry_header_and_key_verified": True,
            "state": "qualified",
        }
    finally:
        if process is not None:
            try:
                _stop_process(process)
            finally:
                _restore_tcti(previous_tcti)


@_requires_reviewed_probe
def test_disposable_software_tpm_seals_luks_secret_and_counter_revokes_it(tmp_path):
    assert _qualify_esapi_custody(tmp_path)["state"] == "qualified"


if __name__ == "__main__":
    child_specification = os.environ.get("ARKHAI_CUSTODY_CHILD_SPEC")
    if child_specification is not None:
        _run_kill_child(json.loads(child_specification))
        raise SystemExit("kill child unexpectedly completed")
    if not RUN:
        raise SystemExit("refusing: set ARKHAI_RUN_SOFTWARE_TPM_CUSTODY=1")
    with tempfile.TemporaryDirectory(prefix="arkhai-custody-") as temporary:
        root = Path(temporary)
        positive = root / "positive"
        process_kills = root / "process-kills"
        positive.mkdir(mode=0o700)
        process_kills.mkdir(mode=0o700)
        print(
            json.dumps(
                {
                    "custody": _qualify_esapi_custody(positive),
                    "process_kills": _qualify_process_kill_checkpoints(
                        process_kills
                    ),
                },
                sort_keys=True,
            )
        )
