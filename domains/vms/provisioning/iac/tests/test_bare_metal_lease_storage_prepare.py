"""Behavioral tests for the managed lease-storage preparation executable."""

from __future__ import annotations

import importlib.util
import json
import os
import re
import stat
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest


HELPER = (
    Path(__file__).resolve().parents[1]
    / "ansible"
    / "roles"
    / "bare-metal-access"
    / "files"
    / "arkhai-prepare-lease-storage.py"
)


def _load_helper():
    spec = importlib.util.spec_from_file_location("lease_storage_prepare", HELPER)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


LUKS_JSON = json.dumps(
    {
        "keyslots": {"0": {"type": "luks2", "key_size": 64}},
        "segments": {"0": {"type": "crypt", "offset": "16777216"}},
    }
)
LUKS_MARKER = b"LUKS\xba\xbe"


@pytest.fixture(autouse=True)
def private_fixture_root(tmp_path):
    """Make the host-owned fixture precondition independent of caller umask."""
    tmp_path.chmod(0o700)


def _private_lease_dir(config) -> Path:
    config.state_root.mkdir(mode=0o700)
    leases = config.state_root / "leases"
    leases.mkdir(mode=0o700)
    lease_dir = leases / config.generation
    lease_dir.mkdir(mode=0o700)
    return lease_dir


class RecordingRunner:
    """Controlled same-process custody and cryptsetup boundary."""

    def __init__(
        self,
        *,
        counter: int = 9,
    ) -> None:
        self.counter = counter
        self.calls: list[tuple[tuple[str, ...], bytes | None]] = []
        self.formatted: set[str] = set()
        self.keys: dict[str, bytes] = {}
        self.luks_json = LUKS_JSON
        self.sealed_secret = b"S" * 32

    @property
    def custody(self):
        return self

    def verify_resources(self, **_expected):
        self.calls.append((("esapi_verify_resources",), None))
        return None

    def read_counter(self):
        self.calls.append((("esapi_read_counter",), None))
        return self.counter

    def increment_counter(self):
        self.calls.append((("esapi_increment_counter",), None))
        self.counter += 1

    def _owned(self, recorder, kind, purpose, handle):
        record = recorder.pending(kind, purpose)
        recorder.live(record, handle)
        return record

    def _close_owned(self, recorder, record):
        recorder.close_pending(record)
        recorder.closed(record)

    def build_policy(self, counter, recorder):
        del counter
        self.calls.append((("esapi_build_policy",), None))
        record = self._owned(recorder, "session", "build-policy-nv", 0x03000000)
        try:
            self._close_owned(recorder, record)
        except BaseException as exc:
            raise RuntimeError("controlled checked-close failure") from exc
        return bytes.fromhex(
            "2f1d9f98a135b730047fd3526f9d4c85272d56f68bf3731a93110f4b033c38a1"
        )

    def create_sealed(self, secret, policy):
        self.calls.append((("esapi_create",), secret))
        assert len(policy) == 32
        self.sealed_secret = secret
        return b"private", b"public"

    def recover_and_verify(
        self, *, private_blob, public_blob, expected_policy, counter, recorder
    ):
        self.calls.append((("esapi_recover_and_verify",), None))
        assert private_blob == b"private"
        assert public_blob == b"public"
        assert len(expected_policy) == 32
        assert counter == self.counter
        obj = self._owned(recorder, "object", "load-sealed-object", 0x80000001)
        session = self._owned(recorder, "session", "unseal-policy-nv", 0x03000001)
        self._close_owned(recorder, session)
        self._close_owned(recorder, obj)
        return SimpleNamespace(name=bytes.fromhex("000baabbccdd")), self.sealed_secret

    def close(self):
        self.calls.append((("esapi_finalize",), None))
        return None

    def run(self, argv, *, stdin=None):
        argv = tuple(str(value) for value in argv)
        self.calls.append((argv, stdin))
        command = Path(argv[0]).name
        if command == "cryptsetup" and "luksFormat" in argv:
            self.formatted.add(argv[-1])
            self.keys[argv[-1]] = stdin
            with Path(argv[-1]).open("r+b") as backing:
                backing.write(LUKS_MARKER)
            return b""
        if command == "cryptsetup" and "luksDump" in argv:
            if not self._is_luks(argv[-1]):
                raise RuntimeError("not a LUKS volume")
            return self.luks_json.encode()
        if command == "cryptsetup" and "--test-passphrase" in argv:
            if not self._is_luks(argv[-1]) or self.keys.get(argv[-1]) != stdin:
                raise RuntimeError("LUKS key does not unlock this header")
            return b""
        raise AssertionError(f"unexpected command: {argv}")

    def check(self, argv) -> bool:
        argv = tuple(str(value) for value in argv)
        self.calls.append((argv, None))
        return argv[0] == "cryptsetup" and "isLuks" in argv and self._is_luks(argv[-1])

    def _is_luks(self, path: str) -> bool:
        target = Path(path)
        return target.exists() and target.read_bytes()[: len(LUKS_MARKER)] == LUKS_MARKER


def _config(module, tmp_path: Path, **changes):
    values = {
        "state_root": tmp_path / "state",
        "host_id": "physical-host-7",
        "machine_id": "executor-host-7",
        "generation": "reservation-44",
        "backing_size": 32 * 1024 * 1024,
        "free_space_floor": 1024,
        "nv_index": "0x1500020",
        "counter_headroom": 16,
        "parent_handle": "0x81000020",
        "parent_name": "000b11223344",
        "required_uid": os.geteuid(),
    }
    values.update(changes)
    return module.PrepareConfig(**values)


def _prepare(tmp_path: Path, **changes):
    module = _load_helper()
    runner = changes.pop("runner", RecordingRunner())
    receipt = module.prepare(
        _config(module, tmp_path, **changes),
        runner=runner,
        random_bytes=lambda length: b"S" * length,
    )
    return module, runner, receipt


def test_prepare_formats_one_keyslot_and_records_exact_identity(tmp_path):
    _, runner, receipt = _prepare(tmp_path)

    assert receipt == {
        "schema": "arkhai.lease-storage-preparation.v1",
        "host_id": "physical-host-7",
        "machine_id": "executor-host-7",
        "generation": "reservation-44",
        "counter": 10,
        "nv_index": "0x1500020",
        "parent_name": "000b11223344",
        "sealed_object_name": "000baabbccdd",
        "state": "prepared",
    }
    commands = [call[0] for call in runner.calls]
    assert ("esapi_increment_counter",) in commands
    assert (("esapi_create",), b"S" * 32) in runner.calls
    luks = next(argv for argv in commands if "luksFormat" in argv)
    assert luks[:6] == (
        "cryptsetup", "--batch-mode", "--type", "luks2", "--key-file", "-"
    )
    assert luks[luks.index("--keyfile-size") + 1] == "32"
    assert luks[-2] == "luksFormat"
    secret_inputs = [stdin for _, stdin in runner.calls if stdin == b"S" * 32]
    assert len(secret_inputs) == 3

    manifest = next((tmp_path / "state" / "leases").glob("*/manifest.json"))
    persisted = manifest.read_bytes()
    manifest_data = json.loads(persisted)
    assert {record["handle"] for record in manifest_data["sessions"]} == {
        "0x03000000", "0x03000001"
    }
    assert {record["handle"] for record in manifest_data["objects"]} == {
        "0x80000001"
    }
    assert all(record["state"] == "confirmed_closed" for record in manifest_data["objects"])
    assert {record["executor"] for record in manifest_data["objects"]} == {
        "same-process-esapi"
    }
    assert not any(argv[0].startswith("tpm2_") for argv in commands)
    assert b"S" * 8 not in persisted
    assert b"53535353" not in persisted
    for argv, _ in runner.calls:
        assert "53" * 32 not in " ".join(argv)


def test_new_policy_and_sealed_blobs_are_private_files(tmp_path):
    module = _load_helper()
    config = _config(module, tmp_path)

    module.prepare(
        config,
        runner=RecordingRunner(),
        random_bytes=lambda length: b"S" * length,
    )

    lease_dir = config.state_root / "leases" / config.generation
    for name in ("policy.nv", "sealed.pub", "sealed.priv"):
        info = (lease_dir / name).stat()
        assert stat.S_ISREG(info.st_mode)
        assert info.st_uid == os.geteuid()
        assert info.st_nlink == 1
        assert stat.S_IMODE(info.st_mode) == 0o600


def test_prepare_refuses_counter_headroom_before_increment(tmp_path):
    module = _load_helper()
    runner = RecordingRunner(counter=(1 << 64) - 16)
    with pytest.raises(module.PreparationRefused, match="headroom"):
        module.prepare(_config(module, tmp_path), runner=runner)
    assert not any(call[0][0] == "esapi_increment_counter" for call in runner.calls)


def test_prepare_refuses_free_space_floor_before_counter_increment(tmp_path, monkeypatch):
    module = _load_helper()
    runner = RecordingRunner()
    config = _config(module, tmp_path)
    usage = type("Usage", (), {"free": config.backing_size + config.free_space_floor - 1})
    monkeypatch.setattr(module.shutil, "disk_usage", lambda path: usage)

    with pytest.raises(module.PreparationRefused, match="free-space floor"):
        module.prepare(config, runner=runner)
    assert not any(call[0][0] == "esapi_increment_counter" for call in runner.calls)


def test_retry_attributes_v_plus_one_without_incrementing_again(tmp_path):
    module = _load_helper()
    runner = RecordingRunner()
    config = _config(module, tmp_path)
    with pytest.raises(module.InjectedInterruption):
        module.prepare(
            config,
            runner=runner,
            random_bytes=lambda length: b"S" * length,
            fail_after="counter_increment",
        )
    assert runner.counter == 10

    module.prepare(
        config,
        runner=runner,
        random_bytes=lambda length: b"S" * length,
    )
    assert runner.counter == 10
    assert sum(call[0][0] == "esapi_increment_counter" for call in runner.calls) == 1


@pytest.mark.parametrize("failure_point", ["increment", "confirmation"])
def test_uncertain_counter_increment_is_durably_quarantined(tmp_path, failure_point):
    module = _load_helper()
    runner = RecordingRunner()
    config = _config(module, tmp_path)
    reads = 0

    original_read = runner.read_counter
    original_increment = runner.increment_counter

    def fail_counter_read():
        nonlocal reads
        reads += 1
        if failure_point == "confirmation" and reads == 2:
            raise RuntimeError("simulated counter confirmation failure")
        return original_read()

    def fail_counter_increment():
        if failure_point == "increment":
            raise module.PreparationRefused("simulated increment failure")
        return original_increment()

    runner.read_counter = fail_counter_read
    runner.increment_counter = fail_counter_increment
    with pytest.raises(module.PreparationQuarantined, match="uncertain"):
        module.prepare(config, runner=runner)

    manifest = config.state_root / "leases" / config.generation / "manifest.json"
    assert json.loads(manifest.read_text(encoding="utf-8"))["state"] == "quarantined"

    calls_before_retry = list(runner.calls)
    manifest_before_retry = manifest.read_bytes()
    runner.read_counter = original_read
    runner.increment_counter = original_increment
    with pytest.raises(module.PreparationQuarantined, match="already quarantined"):
        module.prepare(config, runner=runner)
    assert runner.calls == calls_before_retry
    assert manifest.read_bytes() == manifest_before_retry


def test_failure_is_quarantined_before_a_waiting_prepare_can_resume(tmp_path, monkeypatch):
    module = _load_helper()
    runner = RecordingRunner()
    config = _config(module, tmp_path)
    second_waiting = threading.Event()
    increment_started = threading.Event()
    original_lock = module._lock_host
    original_increment = runner.increment_counter
    failed_once = False

    def observed_lock(selected):
        if threading.current_thread().name == "waiting-prepare":
            second_waiting.set()
        return original_lock(selected)

    def fail_first_increment():
        nonlocal failed_once
        if not failed_once:
            failed_once = True
            increment_started.set()
            assert second_waiting.wait(timeout=5), "waiting prepare never reached the lock"
            raise module.PreparationRefused("simulated uncertain increment")
        return original_increment()

    monkeypatch.setattr(module, "_lock_host", observed_lock)
    runner.increment_counter = fail_first_increment
    results = {}

    def invoke(name):
        try:
            results[name] = module.prepare(
                config,
                runner=runner,
                random_bytes=lambda length: b"S" * length,
            )
        except BaseException as exc:
            results[name] = exc

    first = threading.Thread(target=invoke, args=("first",), name="failing-prepare")
    second = threading.Thread(target=invoke, args=("second",), name="waiting-prepare")
    first.start()
    assert increment_started.wait(timeout=5), "first prepare never reached the increment"
    second.start()
    for caller in (first, second):
        caller.join(timeout=10)
        assert not caller.is_alive(), "interleaved prepare did not finish"

    assert isinstance(results["first"], module.PreparationQuarantined)
    assert isinstance(results["second"], module.PreparationQuarantined)
    assert "already quarantined" in str(results["second"])
    assert runner.counter == 9
    manifest = config.state_root / "leases" / config.generation / "manifest.json"
    assert json.loads(manifest.read_text(encoding="utf-8"))["state"] == "quarantined"


def test_quarantine_persistence_failure_reports_unresolved_state(tmp_path, monkeypatch):
    module = _load_helper()
    runner = RecordingRunner()
    config = _config(module, tmp_path)
    original_replace = module._replace_owned_json

    def fail_increment():
        raise module.PreparationRefused("simulated uncertain increment")

    def fail_quarantine_write(path, value, *, uid):
        if value.get("state") == "quarantined":
            raise OSError("simulated durable-storage failure")
        return original_replace(path, value, uid=uid)

    runner.increment_counter = fail_increment
    monkeypatch.setattr(module, "_replace_owned_json", fail_quarantine_write)
    with pytest.raises(module.PreparationUnresolved, match="persist quarantine"):
        module.prepare(config, runner=runner)

    manifest = config.state_root / "leases" / config.generation / "manifest.json"
    assert json.loads(manifest.read_text(encoding="utf-8"))["state"] == (
        "counter_increment_pending"
    )
    assert runner.counter == 9


def test_cli_reports_unresolved_when_quarantine_cannot_be_persisted(monkeypatch, capsys):
    module = _load_helper()

    def unresolved(*args, **kwargs):
        raise module.PreparationUnresolved("quarantine durability is unresolved")

    monkeypatch.setattr(module, "prepare", unresolved)
    status = module.main(
        [
            "--state-root", "/var/lib/arkhai/lease-storage",
            "--host-id", "physical-host-7",
            "--machine-id", "executor-host-7",
            "--generation", "reservation-44",
            "--backing-size", str(32 * 1024 * 1024),
            "--free-space-floor", "1024",
            "--nv-index", "0x1500020",
            "--counter-headroom", "16",
            "--parent-handle", "0x81000020",
            "--parent-name", "000b11223344",
        ]
    )

    assert status == 1
    assert json.loads(capsys.readouterr().err) == {
        "state": "unresolved",
        "reason": "quarantine durability is unresolved",
    }


def test_counter_drift_is_quarantined_without_sealing(tmp_path):
    module = _load_helper()
    runner = RecordingRunner()
    config = _config(module, tmp_path)
    with pytest.raises(module.InjectedInterruption):
        module.prepare(config, runner=runner, fail_after="counter_intent")
    runner.counter = 12

    with pytest.raises(module.PreparationQuarantined, match="counter drift"):
        module.prepare(config, runner=runner)
    assert not any(call[0][0] == "esapi_create" for call in runner.calls)


def test_v_plus_one_without_exclusive_writer_attribution_is_quarantined(tmp_path):
    module = _load_helper()
    runner = RecordingRunner()
    config = _config(module, tmp_path)
    with pytest.raises(module.InjectedInterruption):
        module.prepare(config, runner=runner, fail_after="counter_increment")
    manifest = config.state_root / "leases" / config.generation / "manifest.json"
    data = json.loads(manifest.read_text(encoding="utf-8"))
    del data["counter_intent"]["exclusive_writer"]
    manifest.write_text(json.dumps(data), encoding="utf-8")
    manifest.chmod(0o600)

    with pytest.raises(module.PreparationQuarantined, match="exclusive-writer"):
        module.prepare(config, runner=runner)
    assert sum(call[0][0] == "esapi_increment_counter" for call in runner.calls) == 1


def test_retry_does_not_reformat_an_existing_owned_luks_volume(tmp_path):
    module = _load_helper()
    runner = RecordingRunner()
    config = _config(module, tmp_path)
    with pytest.raises(module.InjectedInterruption):
        module.prepare(
            config,
            runner=runner,
            random_bytes=lambda length: b"S" * length,
            fail_after="luks_format",
        )

    module.prepare(config, runner=runner)
    assert sum("luksFormat" in call[0] for call in runner.calls) == 1


def test_completed_retry_revalidates_without_repeating_counter_or_format(tmp_path):
    module = _load_helper()
    runner = RecordingRunner()
    config = _config(module, tmp_path)
    module.prepare(config, runner=runner, random_bytes=lambda length: b"S" * length)
    module.prepare(config, runner=runner)

    assert sum(call[0][0] == "esapi_increment_counter" for call in runner.calls) == 1
    assert sum("luksFormat" in call[0] for call in runner.calls) == 1
    assert any("--test-passphrase" in call[0] for call in runner.calls)
    assert sum(call[0][0] == "esapi_recover_and_verify" for call in runner.calls) == 2
    runner.counter = 11
    with pytest.raises(module.PreparationQuarantined, match="counter drift"):
        module.prepare(config, runner=runner)


def test_completed_retry_refuses_a_destroyed_header_without_reformatting(tmp_path):
    module = _load_helper()
    runner = RecordingRunner()
    config = _config(module, tmp_path)
    module.prepare(config, runner=runner, random_bytes=lambda length: b"S" * length)
    backing = config.state_root / "leases" / config.generation / "volume.luks"
    with backing.open("r+b") as target:
        target.write(b"\0" * config.backing_size)
        target.flush()
        os.fsync(target.fileno())
    runner.calls.clear()

    with pytest.raises(module.PreparationQuarantined, match="LUKS2 header"):
        module.prepare(config, runner=runner)
    assert any("isLuks" in call[0] for call in runner.calls)
    assert not any("luksFormat" in call[0] for call in runner.calls)


def test_completed_retry_quarantines_changed_keyslots_without_reformatting(tmp_path):
    module = _load_helper()
    runner = RecordingRunner()
    config = _config(module, tmp_path)
    module.prepare(config, runner=runner, random_bytes=lambda length: b"S" * length)
    runner.calls.clear()
    runner.luks_json = json.dumps({"keyslots": {"0": {}, "1": {}}})

    with pytest.raises(module.PreparationQuarantined, match="exactly one keyslot"):
        module.prepare(config, runner=runner)
    assert not any("luksFormat" in call[0] for call in runner.calls)


def test_completed_retry_quarantines_when_sealed_secret_no_longer_unlocks(tmp_path):
    module = _load_helper()
    runner = RecordingRunner()
    config = _config(module, tmp_path)
    module.prepare(config, runner=runner, random_bytes=lambda length: b"S" * length)
    runner.calls.clear()
    original_run = runner.run

    def reject_test_passphrase(argv, *, stdin=None):
        if "--test-passphrase" in argv:
            raise module.PreparationRefused("simulated wrong LUKS2 key")
        return original_run(argv, stdin=stdin)

    runner.run = reject_test_passphrase
    with pytest.raises(module.PreparationQuarantined, match="does not unlock"):
        module.prepare(config, runner=runner)
    assert not any("luksFormat" in call[0] for call in runner.calls)


def test_an_unreleased_generation_fences_the_host_counter(tmp_path):
    module = _load_helper()
    runner = RecordingRunner()
    original = _config(module, tmp_path)
    module.prepare(original, runner=runner, random_bytes=lambda length: b"S" * length)
    replacement = _config(module, tmp_path, generation="reservation-45")

    with pytest.raises(module.PreparationRefused, match="active generation"):
        module.prepare(
            replacement,
            runner=runner,
            random_bytes=lambda length: b"R" * length,
        )

    assert runner.counter == 10
    assert not (replacement.state_root / "leases" / replacement.generation).exists()
    fences = list((original.state_root / "hosts").glob("*.json"))
    assert len(fences) == 1
    assert json.loads(fences[0].read_text(encoding="utf-8"))["generation"] == original.generation
    receipt = module.prepare(original, runner=runner)
    assert receipt["generation"] == original.generation
    assert receipt["counter"] == 10


def test_waiting_same_generation_reloads_manifest_after_taking_lock(tmp_path, monkeypatch):
    module = _load_helper()
    runner = RecordingRunner()
    config = _config(module, tmp_path)
    with pytest.raises(module.InjectedInterruption):
        module.prepare(config, runner=runner, fail_after="lease_state")

    original_lock = module._lock_host
    both_waiting = threading.Barrier(2)

    def synchronized_lock(selected):
        both_waiting.wait(timeout=5)
        return original_lock(selected)

    monkeypatch.setattr(module, "_lock_host", synchronized_lock)
    results = []

    def invoke():
        try:
            results.append(
                module.prepare(
                    config,
                    runner=runner,
                    random_bytes=lambda length: b"S" * length,
                )
            )
        except BaseException as exc:
            results.append(exc)

    callers = [threading.Thread(target=invoke) for _ in range(2)]
    for caller in callers:
        caller.start()
    for caller in callers:
        caller.join(timeout=10)
        assert not caller.is_alive(), "concurrent prepare did not finish"

    failures = [result for result in results if isinstance(result, BaseException)]
    assert not failures, repr(failures)
    assert [result["state"] for result in results] == ["prepared", "prepared"]
    manifest_path = config.state_root / "leases" / config.generation / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert len(manifest["helper_attempts"]) == 2
    assert len(manifest["objects"]) == 2
    assert all(record["state"] == "confirmed_closed" for record in manifest["objects"])
    assert runner.counter == 10
    assert sum("luksFormat" in call[0] for call in runner.calls) == 1


@pytest.mark.parametrize(
    "boundary",
    [
        "lease_state",
        "host_lock",
        "helper_intent",
        "counter_intent",
        "counter_confirmed",
        "policy_digest",
        "policy_session_closed",
        "policy_committed",
        "sealed_object_intent",
        "sealed_object",
        "sealed_object_recorded",
        "object_closed",
        "sealed_object_verified",
        "backing_file_intent",
        "backing_file",
        "luks_format",
        "luks_verified",
        "prepared_receipt",
        "helper_completed",
    ],
)
def test_retry_resumes_attributable_partial_prepare_without_reincrement(tmp_path, boundary):
    module = _load_helper()
    runner = RecordingRunner()
    config = _config(module, tmp_path)
    with pytest.raises(module.InjectedInterruption):
        module.prepare(
            config,
            runner=runner,
            random_bytes=lambda length: b"S" * length,
            fail_after=boundary,
        )

    receipt = module.prepare(config, runner=runner)
    assert receipt["state"] == "prepared"
    assert sum(call[0][0] == "esapi_increment_counter" for call in runner.calls) == 1
    assert sum("luksFormat" in call[0] for call in runner.calls) == 1


def test_retry_quarantines_an_uncertain_luks_format_intent(tmp_path):
    module = _load_helper()
    runner = RecordingRunner()
    config = _config(module, tmp_path)
    with pytest.raises(module.InjectedInterruption):
        module.prepare(
            config,
            runner=runner,
            random_bytes=lambda length: b"S" * length,
            fail_after="luks_format_intent",
        )

    with pytest.raises(module.PreparationQuarantined, match="LUKS2 header"):
        module.prepare(config, runner=runner)
    assert not any("luksFormat" in call[0] for call in runner.calls)


def test_existing_foreign_lease_path_is_never_adopted(tmp_path):
    module = _load_helper()
    config = _config(module, tmp_path)
    lease_dir = _private_lease_dir(config)
    (lease_dir / "foreign").write_text("do not touch", encoding="utf-8")

    with pytest.raises(module.PreparationRefused, match="ownership"):
        module.prepare(config, runner=RecordingRunner())
    assert (lease_dir / "foreign").read_text(encoding="utf-8") == "do not touch"


def test_symlink_backing_path_is_never_followed(tmp_path):
    module = _load_helper()
    runner = RecordingRunner()
    config = _config(module, tmp_path)
    lease_dir = _private_lease_dir(config)
    (lease_dir / "ownership.json").write_text(
        json.dumps(module.ownership_record(config)), encoding="utf-8"
    )
    (lease_dir / "ownership.json").chmod(0o600)
    target = tmp_path / "foreign"
    target.write_text("keep", encoding="utf-8")
    (lease_dir / "volume.luks").symlink_to(target)

    refusal = rf"^refusing symlink: {re.escape(str(lease_dir / 'volume.luks'))}$"
    with pytest.raises(module.PreparationRefused, match=refusal):
        module.prepare(config, runner=runner)
    assert target.read_text(encoding="utf-8") == "keep"


def test_existing_regular_backing_file_without_intent_is_never_adopted(tmp_path):
    module = _load_helper()
    runner = RecordingRunner()
    config = _config(module, tmp_path)
    lease_dir = _private_lease_dir(config)
    ownership = lease_dir / "ownership.json"
    ownership.write_text(json.dumps(module.ownership_record(config)), encoding="utf-8")
    ownership.chmod(0o600)
    backing = lease_dir / "volume.luks"
    backing.write_bytes(b"foreign")
    backing.chmod(0o600)

    with pytest.raises(module.PreparationRefused, match="ownership intent"):
        module.prepare(config, runner=runner)
    assert backing.read_bytes() == b"foreign"
    assert not any(call[0][0] == "esapi_increment_counter" for call in runner.calls)


def test_subprocess_failure_does_not_echo_stdin_or_child_output(tmp_path, monkeypatch):
    module = _load_helper()
    tools = tmp_path / "tools"
    tools.mkdir(mode=0o700)
    for command in module.SubprocessRunner._REQUIRED:
        executable = tools / command
        executable.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        executable.chmod(0o700)
    failing = tools / "cryptsetup"
    failing.write_text("#!/bin/sh\nsecret=$(cat)\necho \"$secret\" >&2\nexit 9\n", encoding="utf-8")
    failing.chmod(0o700)
    monkeypatch.setenv("PATH", str(tools))
    secret = b"secret-canary-that-must-not-escape"

    runner = module.SubprocessRunner()
    with pytest.raises(module.PreparationRefused) as error:
        runner.run(("cryptsetup",), stdin=secret)
    assert secret.decode() not in str(error.value)
    assert str(error.value) == "cryptsetup failed with exit status 9"


def test_production_prepare_refuses_without_enabled_esapi_custody(tmp_path, monkeypatch):
    module = _load_helper()
    tools = tmp_path / "tools"
    tools.mkdir(mode=0o700)
    for command in module.SubprocessRunner._REQUIRED:
        executable = tools / command
        executable.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        executable.chmod(0o700)
    monkeypatch.setenv("PATH", str(tools))
    config = _config(module, tmp_path)

    with pytest.raises(module.PreparationRefused, match="not enabled for production"):
        module.prepare(config)

    assert not config.state_root.exists()


def test_owned_object_cleanup_failure_keeps_pending_evidence(tmp_path):
    module = _load_helper()

    class FailedLoadCleanupRunner(RecordingRunner):
        def recover_and_verify(self, **kwargs):
            recorder = kwargs["recorder"]
            record = recorder.pending("object", "load-sealed-object")
            recorder.live(record, 0x80000001)
            recorder.close_pending(record)
            raise RuntimeError("controlled cleanup failure")

    config = _config(module, tmp_path)
    with pytest.raises(module.PreparationQuarantined, match="checked cleanup"):
        module.prepare(config, runner=FailedLoadCleanupRunner())

    manifest_path = config.state_root / "leases" / config.generation / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["state"] == "quarantined"
    assert manifest["objects"][-1]["purpose"] == "load-sealed-object"
    assert manifest["objects"][-1]["state"] == "close_pending"


def test_flush_success_lost_before_durable_close_never_reflushes_on_retry(
    tmp_path, monkeypatch
):
    module = _load_helper()
    runner = RecordingRunner()
    config = _config(module, tmp_path)
    original_persist = module._persist
    lost = False

    def lose_first_close_receipt(path, manifest, selected, event):
        nonlocal lost
        if event == "handle_confirmed_closed" and not lost:
            lost = True
            raise OSError("controlled lost durable close receipt")
        return original_persist(path, manifest, selected, event)

    monkeypatch.setattr(module, "_persist", lose_first_close_receipt)
    with pytest.raises(module.PreparationQuarantined, match="close cleanly"):
        module.prepare(config, runner=runner)

    manifest_path = config.state_root / "leases" / config.generation / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["state"] == "quarantined"
    assert manifest["sessions"][0]["state"] == "close_pending"
    calls_before = list(runner.calls)

    monkeypatch.setattr(module, "_persist", original_persist)
    with pytest.raises(module.PreparationQuarantined, match="already quarantined"):
        module.prepare(config, runner=runner)
    assert runner.calls == calls_before


def test_missing_tool_refuses_before_creating_lease_state(tmp_path, monkeypatch):
    module = _load_helper()
    config = _config(module, tmp_path)
    monkeypatch.setenv("PATH", "")

    with pytest.raises(module.PreparationRefused, match="required tool unavailable"):
        module.prepare(config)
    assert not config.state_root.exists()


def test_foreign_manifest_identity_is_never_adopted(tmp_path):
    module, runner, _ = _prepare(tmp_path)
    manifest = next((tmp_path / "state" / "leases").glob("*/manifest.json"))
    data = json.loads(manifest.read_text(encoding="utf-8"))
    data["generation"] = "replacement-generation"
    manifest.write_text(json.dumps(data), encoding="utf-8")

    with pytest.raises(module.PreparationRefused, match="identity"):
        module.prepare(_config(module, tmp_path), runner=runner)


def test_all_declared_side_effect_boundaries_leave_a_durable_manifest(tmp_path):
    module = _load_helper()
    for boundary in module.FAILPOINTS:
        case = tmp_path / boundary
        case.mkdir(mode=0o700)
        runner = RecordingRunner()
        with pytest.raises(module.InjectedInterruption):
            module.prepare(
                _config(module, case),
                runner=runner,
                random_bytes=lambda length: b"S" * length,
                fail_after=boundary,
            )
        manifests = list((case / "state" / "leases").glob("*/manifest.json"))
        if boundary == "host_lock":
            assert manifests == []
            continue
        assert len(manifests) == 1, boundary
        json.loads(manifests[0].read_text(encoding="utf-8"))
