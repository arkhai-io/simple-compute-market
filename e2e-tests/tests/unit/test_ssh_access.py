"""The SSH access helper's invocation, retries, host-key trust, refusals, and probes.

The system `ssh` is replaced by a fake executable the session is given by path:
it records each invocation, answers from a plan, and keeps the run's
`known_hosts` the way `StrictHostKeyChecking=accept-new` does, printing what the
real client prints when it refuses a changed host key. That the real client
prints it is OpenSSH's behaviour, not something these tests can show. The
e2e package has no integration tier, so the subprocess boundary is crossed here,
to the fake, as the IaC suite's shell harness crosses it. Time is a fake clock
the session's sleep and the fake's planned attempt durations advance, so no
test waits on it.
"""

from __future__ import annotations

import base64
import json
import re
import stat
import subprocess
import sys
from pathlib import Path

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import (
    Encoding,
    PublicFormat,
    load_ssh_private_key,
)

from tests.e2e.roles.helpers.ssh_access import (
    _PROBE,
    CONNECT_TIMEOUT_SECONDS,
    MEMORY_SHORTFALL_TOLERANCE,
    RETRY_INTERVAL_SECONDS,
    HostKeyChanged,
    SshAccessError,
    SshEndpoint,
    SshSession,
    memory_within_tolerance,
    parse_probe,
    ssh_session,
)

#: An RFC 5737 documentation address, never dialled: the fake answers for it.
ENDPOINT = SshEndpoint(host="192.0.2.10", port=2222, user="vmuser")


def _host_key() -> str:
    """A host public key made for the test, as it appears in `known_hosts`."""
    public = Ed25519PrivateKey.generate().public_key()
    return public.public_bytes(Encoding.OpenSSH, PublicFormat.OpenSSH).split()[1].decode()


HOST_KEY = _host_key()
OTHER_HOST_KEY = _host_key()
PROBE_OUTPUT = (
    "user=vmuser\n"
    "vcpus=7\n"
    "MemTotal:       28734124 kB\n"
    "root_disk_bytes=171798691840\n"
)

#: Answers each invocation with the next step of its plan. A step's `host_key`
#: is the key the host presents: written to the run's known_hosts on first
#: contact, and refused as `ssh` refuses it when it differs from the one there.
FAKE_SSH = """\
import json, sys
from pathlib import Path

here = Path(__file__).parent
plan = json.loads((here / "plan.json").read_text())
calls = json.loads((here / "calls.json").read_text())
calls.append(sys.argv[1:])
(here / "calls.json").write_text(json.dumps(calls))
step = plan[min(len(calls), len(plan)) - 1]
if step.get("elapse"):
    elapsed = here / "elapsed"
    spent = float(elapsed.read_text()) if elapsed.exists() else 0.0
    elapsed.write_text(str(spent + step["elapse"]))
if step.get("hang"):
    import time
    time.sleep(step["hang"])

args = sys.argv[1:]
options = {}
for i, arg in enumerate(args):
    if arg == "-o":
        name, _, value = args[i + 1].partition("=")
        options[name] = value
port = args[args.index("-p") + 1]
host = args[-2].split("@", 1)[1]
name = host if port == "22" else f"[{host}]:{port}"

if step.get("host_key"):
    known = Path(options["UserKnownHostsFile"])
    lines = known.read_text().splitlines() if known.exists() else []
    held = [l.split()[2] for l in lines if l.split()[0] == name]
    if held and held[0] != step["host_key"]:
        sys.stderr.write("@ WARNING: REMOTE HOST IDENTIFICATION HAS CHANGED! @\\n"
                         "Host key verification failed.\\n")
        sys.exit(255)
    if not held:
        lines.append(f"{name} ssh-ed25519 {step['host_key']}")
        known.write_text("\\n".join(lines) + "\\n")

sys.stdout.write(step.get("stdout", ""))
sys.stderr.write(step.get("stderr", ""))
sys.exit(step.get("rc", 0))
"""


class Clock:
    """Fake time: what the session slept, plus what the fake's attempts spent.

    A plan step's `elapse` is how long that attempt takes in this time, so an
    attempt can run past a deadline without the test waiting on it.
    """

    def __init__(self, elapsed: Path) -> None:
        self.slept = 0.0
        self.sleeps: list[float] = []
        self._elapsed = elapsed

    @property
    def now(self) -> float:
        spent = float(self._elapsed.read_text()) if self._elapsed.exists() else 0.0
        return self.slept + spent

    def __call__(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.slept += seconds


@pytest.fixture
def fake_ssh(tmp_path: Path):
    """A fake `ssh` and the means to plan its answers and read its calls."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    executable = bin_dir / "ssh"
    executable.write_text(f"#!{sys.executable}\n{FAKE_SSH}")
    executable.chmod(executable.stat().st_mode | stat.S_IXUSR)
    (bin_dir / "calls.json").write_text("[]")

    class Fake:
        path = str(executable)
        elapsed = bin_dir / "elapsed"

        @staticmethod
        def plan(*steps: dict) -> None:
            (bin_dir / "plan.json").write_text(json.dumps(list(steps)))

        @staticmethod
        def calls() -> list[list[str]]:
            return json.loads((bin_dir / "calls.json").read_text())

    return Fake


@pytest.fixture
def clock(fake_ssh) -> Clock:
    return Clock(fake_ssh.elapsed)


@pytest.fixture
def session(tmp_path: Path, fake_ssh, clock: Clock):
    directory = tmp_path / "run"
    directory.mkdir(mode=0o700)
    return SshSession(
        directory,
        ssh=fake_ssh.path,
        clock=clock,
        sleep=clock.sleep,
        connect_retry_seconds=60,
    )


def _option(argv: list[str], name: str) -> str | None:
    values = [argv[i + 1] for i, arg in enumerate(argv) if arg == "-o"]
    found = [value.split("=", 1)[1] for value in values if value.startswith(f"{name}=")]
    return found[0] if found else None


def test_a_generated_key_is_ed25519_and_owner_only(session: SshSession):
    key = session.new_key("buyer")
    assert stat.S_IMODE(key.private_key.stat().st_mode) == 0o600
    assert key.public_line.startswith("ssh-ed25519 AAAA")
    loaded = load_ssh_private_key(key.private_key.read_bytes(), password=None)
    assert loaded.public_key().public_bytes_raw()
    assert session.new_key("unrelated").public_line != key.public_line


def test_the_run_directory_is_owner_only_and_removed_afterwards():
    with ssh_session() as run:
        directory = run.directory
        key = run.new_key("buyer")
        assert stat.S_IMODE(directory.stat().st_mode) == 0o700
        assert key.private_key.exists()
    assert not directory.exists()


def test_the_invocation_offers_only_the_given_key_against_the_runs_known_hosts(
    session: SshSession, fake_ssh
):
    fake_ssh.plan({"host_key": HOST_KEY, "stdout": "ok"})
    key = session.new_key("buyer")
    assert session.run(ENDPOINT, key, "true") == "ok"
    (argv,) = fake_ssh.calls()
    assert argv[argv.index("-i") + 1] == str(key.private_key)
    assert argv.count("-i") == 1
    assert argv[argv.index("-p") + 1] == "2222"
    assert argv[argv.index("-F") + 1] == "/dev/null"
    assert _option(argv, "BatchMode") == "yes"
    assert _option(argv, "ConnectTimeout") == str(CONNECT_TIMEOUT_SECONDS)
    assert _option(argv, "IdentitiesOnly") == "yes"
    assert _option(argv, "IdentityAgent") == "none"
    assert _option(argv, "StrictHostKeyChecking") == "accept-new"
    assert _option(argv, "UserKnownHostsFile") == str(session.known_hosts)
    assert _option(argv, "GlobalKnownHostsFile") == "/dev/null"
    assert _option(argv, "HashKnownHosts") == "no"
    assert argv[-2:] == ["vmuser@192.0.2.10", "true"]


def test_a_connection_failure_is_retried_until_it_succeeds(
    session: SshSession, fake_ssh, clock: Clock
):
    fake_ssh.plan(
        {"rc": 255, "stderr": "Connection refused"},
        {"rc": 255, "stderr": "Permission denied (publickey)."},
        {"host_key": HOST_KEY, "stdout": "up"},
    )
    assert session.run(ENDPOINT, session.new_key("buyer"), "true") == "up"
    assert len(fake_ssh.calls()) == 3
    assert clock.sleeps == [RETRY_INTERVAL_SECONDS] * 2


def test_a_connection_that_never_succeeds_fails_at_the_bound(
    session: SshSession, fake_ssh, clock: Clock
):
    fake_ssh.plan({"rc": 255, "stderr": "Connection timed out"})
    with pytest.raises(SshAccessError, match="within 60s: Connection timed out"):
        session.run(ENDPOINT, session.new_key("buyer"), "true")
    assert clock.now >= 60
    assert len(fake_ssh.calls()) == 60 // RETRY_INTERVAL_SECONDS + 1


def test_a_failing_command_is_not_retried(session: SshSession, fake_ssh):
    fake_ssh.plan({"host_key": HOST_KEY, "rc": 1, "stderr": "nope"})
    with pytest.raises(SshAccessError, match="exit 1: nope"):
        session.run(ENDPOINT, session.new_key("buyer"), "false")
    assert len(fake_ssh.calls()) == 1


def test_the_first_host_key_is_trusted_and_logged(
    session: SshSession, fake_ssh, caplog: pytest.LogCaptureFixture
):
    fake_ssh.plan({"host_key": HOST_KEY})
    caplog.set_level("INFO")
    session.run(ENDPOINT, session.new_key("buyer"), "true")
    fingerprint = session.host_key_fingerprint(ENDPOINT)
    # SHA256 of the key blob, unpadded base64: 43 characters for any key.
    assert fingerprint and fingerprint.startswith("SHA256:")
    assert len(fingerprint) == len("SHA256:") + 43
    base64.b64decode(fingerprint[len("SHA256:"):] + "=")
    assert fingerprint in caplog.text
    assert session.host_key_fingerprint(
        SshEndpoint(host=ENDPOINT.host, port=22, user=ENDPOINT.user)
    ) is None


@pytest.fixture
def hanging_session(tmp_path: Path, fake_ssh, clock: Clock) -> SshSession:
    """A session whose attempts run out of time after half a second of real time."""
    directory = tmp_path / "hung"
    directory.mkdir(mode=0o700)
    return SshSession(
        directory, ssh=fake_ssh.path, clock=clock, sleep=clock.sleep,
        connect_retry_seconds=60, attempt_seconds=0.5,
    )


def test_an_attempt_that_hangs_is_retried_as_a_connection_failure(
    hanging_session: SshSession, fake_ssh
):
    fake_ssh.plan({"hang": 5}, {"host_key": HOST_KEY, "stdout": "up"})
    assert hanging_session.run(ENDPOINT, hanging_session.new_key("buyer"), "true") == "up"
    assert len(fake_ssh.calls()) == 2


def test_an_attempt_that_hangs_is_not_a_refusal_but_is_retried(
    hanging_session: SshSession, fake_ssh, clock: Clock
):
    """Something answered and stayed connected: only ``ssh`` failing later refuses."""
    fake_ssh.plan({"hang": 5}, {"rc": 255, "stderr": "Connection refused"})
    key = hanging_session.new_key("buyer")
    assert hanging_session.assert_refused(ENDPOINT, key) == "Connection refused"
    assert len(fake_ssh.calls()) == 2
    assert clock.sleeps == [RETRY_INTERVAL_SECONDS]


def test_access_still_hanging_at_the_bound_fails(
    hanging_session: SshSession, fake_ssh
):
    fake_ssh.plan({"hang": 5})
    with pytest.raises(SshAccessError, match="not shown to refuse buyer within 10s"):
        hanging_session.assert_refused(ENDPOINT, hanging_session.new_key("buyer"), bound=10)
    assert len(fake_ssh.calls()) == 10 // RETRY_INTERVAL_SECONDS


def test_access_accepted_after_a_hang_fails_as_still_accepted(
    hanging_session: SshSession, fake_ssh
):
    fake_ssh.plan({"hang": 5}, {"host_key": HOST_KEY})
    with pytest.raises(SshAccessError, match="still accepted buyer after 10s"):
        hanging_session.assert_refused(ENDPOINT, hanging_session.new_key("buyer"), bound=10)


def test_a_changed_host_key_fails_without_a_retry(session: SshSession, fake_ssh):
    key = session.new_key("buyer")
    fake_ssh.plan({"host_key": HOST_KEY}, {"host_key": OTHER_HOST_KEY})
    session.run(ENDPOINT, key, "true")
    trusted = session.host_key_fingerprint(ENDPOINT)
    with pytest.raises(HostKeyChanged, match=re.escape(trusted)):
        session.run(ENDPOINT, key, "true")
    assert len(fake_ssh.calls()) == 2


@pytest.mark.parametrize(
    "stderr",
    ["Permission denied (publickey).", "Connection refused", "Connection timed out"],
)
def test_a_refusal_or_timeout_is_reported_as_refused(
    session: SshSession, fake_ssh, stderr: str
):
    fake_ssh.plan({"rc": 255, "stderr": stderr})
    assert session.assert_refused(ENDPOINT, session.new_key("unrelated")) == stderr
    assert len(fake_ssh.calls()) == 1


def test_access_still_accepted_at_the_bound_fails(
    session: SshSession, fake_ssh, clock: Clock
):
    fake_ssh.plan({"host_key": HOST_KEY})
    with pytest.raises(SshAccessError, match="still accepted"):
        session.assert_refused(ENDPOINT, session.new_key("buyer"), bound=30)
    assert clock.now >= 30


def test_access_ending_within_the_bound_is_refused(session: SshSession, fake_ssh):
    fake_ssh.plan({"host_key": HOST_KEY}, {"rc": 255, "stderr": "Connection refused"})
    assert session.assert_refused(ENDPOINT, session.new_key("buyer")) == "Connection refused"


def test_no_refusal_attempt_starts_after_the_bound(
    session: SshSession, fake_ssh, clock: Clock
):
    fake_ssh.plan(
        {"host_key": HOST_KEY, "elapse": 27},
        {"rc": 255, "stderr": "Connection refused"},
    )
    with pytest.raises(SshAccessError, match="still accepted buyer after 30s"):
        session.assert_refused(ENDPOINT, session.new_key("buyer"), bound=30)
    assert clock.sleeps == [3]
    assert len(fake_ssh.calls()) == 1


def test_a_refusal_returned_after_the_bound_fails(session: SshSession, fake_ssh):
    fake_ssh.plan({"rc": 255, "stderr": "Connection refused", "elapse": 40})
    with pytest.raises(SshAccessError, match="only after 30s: Connection refused"):
        session.assert_refused(ENDPOINT, session.new_key("buyer"), bound=30)


def test_an_attempt_cut_short_by_the_bound_is_not_a_refusal(
    tmp_path: Path, fake_ssh, clock: Clock
):
    """Cut to the half second left, the attempt runs out of time while still
    connected, and the bound has closed before any refusal was seen."""
    directory = tmp_path / "short"
    directory.mkdir(mode=0o700)
    session = SshSession(
        directory, ssh=fake_ssh.path, clock=clock, sleep=clock.sleep, attempt_seconds=5,
    )
    fake_ssh.plan({"host_key": HOST_KEY, "elapse": 24.5}, {"hang": 10})
    with pytest.raises(SshAccessError, match="not shown to refuse buyer within 30s"):
        session.assert_refused(ENDPOINT, session.new_key("buyer"), bound=30)


@pytest.mark.parametrize("call", ["run", "assert_key_refused"])
def test_no_retry_sleeps_past_the_connect_window(
    session: SshSession, fake_ssh, clock: Clock, call: str
):
    fake_ssh.plan({"rc": 255, "stderr": "Connection refused", "elapse": 57})
    key = session.new_key("buyer")
    attempt = (
        (lambda: session.run(ENDPOINT, key, "true"))
        if call == "run"
        else (lambda: session.assert_key_refused(ENDPOINT, key))
    )
    with pytest.raises(SshAccessError, match="within 60s: Connection refused"):
        attempt()
    assert clock.sleeps == [3]
    assert len(fake_ssh.calls()) == 2


def test_a_key_refusal_needs_the_host_to_deny_the_key(
    session: SshSession, fake_ssh, clock: Clock
):
    fake_ssh.plan(
        {"rc": 255, "stderr": "Connection timed out"},
        {"host_key": HOST_KEY, "rc": 255,
         "stderr": "vmuser@192.0.2.10: Permission denied (publickey)."},
    )
    reason = session.assert_key_refused(ENDPOINT, session.new_key("unrelated"))
    assert "Permission denied" in reason
    assert len(fake_ssh.calls()) == 2


def test_a_key_refusal_fails_when_the_host_is_never_reached(
    session: SshSession, fake_ssh
):
    fake_ssh.plan({"rc": 255, "stderr": "Connection timed out"})
    with pytest.raises(SshAccessError, match="could not reach"):
        session.assert_key_refused(ENDPOINT, session.new_key("unrelated"))


def test_a_key_refusal_fails_when_the_key_is_accepted(session: SshSession, fake_ssh):
    fake_ssh.plan({"host_key": HOST_KEY})
    with pytest.raises(SshAccessError, match="accepted unrelated"):
        session.assert_key_refused(ENDPOINT, session.new_key("unrelated"))


def test_the_probe_reads_user_cpus_memory_and_disk(session: SshSession, fake_ssh):
    fake_ssh.plan({"host_key": HOST_KEY, "stdout": PROBE_OUTPUT})
    shape = session.probe(ENDPOINT, session.new_key("buyer"))
    assert shape.user == "vmuser"
    assert shape.vcpu_count == 7
    assert shape.memory_gib == pytest.approx(28734124 / 1024 / 1024)
    assert shape.root_disk_gib == 160


@pytest.mark.parametrize(
    "output",
    [
        PROBE_OUTPUT.replace("vcpus=7\n", ""),
        PROBE_OUTPUT.replace("root_disk_bytes=171798691840", "root_disk_bytes="),
        PROBE_OUTPUT.replace(" kB", " MB"),
        PROBE_OUTPUT.replace(" kB", ""),
    ],
    ids=["no-vcpus", "empty-disk", "memory-unit", "memory-no-unit"],
)
def test_an_incomplete_probe_is_refused(output: str):
    with pytest.raises(SshAccessError):
        parse_probe(output)


def test_the_probe_command_parses_as_shell():
    """The probe runs in the guest's login shell, which this cannot run; it
    can at least refuse a command that would not parse there."""
    parsed = subprocess.run(["bash", "-n", "-c", _PROBE], capture_output=True, text=True)
    assert parsed.returncode == 0, parsed.stderr


def test_memory_is_the_negotiated_amount_less_a_strict_tolerance():
    assert MEMORY_SHORTFALL_TOLERANCE <= 0.05
    assert memory_within_tolerance(27.4, 28)
    assert memory_within_tolerance(28, 28)
    assert not memory_within_tolerance(26.5, 28)
    assert not memory_within_tolerance(28.5, 28)
