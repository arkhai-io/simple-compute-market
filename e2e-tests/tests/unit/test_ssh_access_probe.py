"""Revocation evidence must distinguish a rejected key from an unreachable host."""

from __future__ import annotations

import subprocess

import pytest

from src.ssh_access import (
    AccessVerdict,
    HostKeyTrust,
    SshProbeResult,
    buyer_probe_environment,
    buyer_ssh_argv,
    classify_ssh_probe,
    freeze_lease_key,
    resolve_host_key_trust,
)


FINGERPRINT = "SHA256:LEASEKEY"
OFFERED = f"debug1: Offering public key: /run/buyer/key ED25519 {FINGERPRINT}\r\n"


def _result(returncode: int, stderr: str = "", stdout: str = "") -> SshProbeResult:
    return SshProbeResult(returncode=returncode, stdout=stdout, stderr=stderr)


def _classify(result: SshProbeResult, fingerprint: str = FINGERPRINT):
    """The fingerprint is required by the API; tests state it explicitly."""
    return classify_ssh_probe(result, offered_fingerprint=fingerprint)


def test_successful_command_is_granted() -> None:
    assert _classify(_result(0, stdout="ok")) is AccessVerdict.GRANTED


@pytest.mark.parametrize(
    "stderr",
    [
        "buyer@host: Permission denied (publickey).",
        "No supported authentication methods available",
        "Received disconnect from 10.0.0.1 port 22:2: Too many authentication failures",
    ],
)
def test_authentication_failures_are_key_rejection(stderr: str) -> None:
    """The lease key must be shown as offered, or a denial names no key."""
    assert (
        _classify(_result(255, stderr=OFFERED + stderr)) is AccessVerdict.KEY_REJECTED
    )


@pytest.mark.parametrize(
    "stderr",
    [
        "buyer@host: Permission denied (publickey).",
        "No supported authentication methods available",
    ],
)
def test_a_denial_without_the_lease_key_offered_is_not_revocation(stderr: str) -> None:
    assert _classify(_result(255, stderr=stderr)) is AccessVerdict.INDETERMINATE


@pytest.mark.parametrize(
    "stderr",
    [
        "ssh: connect to host 10.0.0.1 port 22: Connection timed out",
        "ssh: connect to host 10.0.0.1 port 22: Connection refused",
        "ssh: connect to host 10.0.0.1 port 22: No route to host",
        "ssh: connect to host 10.0.0.1 port 22: Network is unreachable",
        "ssh: Could not resolve hostname nowhere.invalid: Name or service not known",
        "kex_exchange_identification: Connection closed by remote host",
        "Connection closed by 10.0.0.1 port 22",
    ],
)
def test_transport_failures_are_not_key_rejection(stderr: str) -> None:
    """A dead host, a dropped tunnel, or DNS loss is not proof of revocation."""
    assert (
        _classify(_result(255, stderr=stderr))
        is AccessVerdict.HOST_UNREACHABLE
    )


@pytest.mark.parametrize(
    "stderr",
    [
        "@@@@ WARNING: REMOTE HOST IDENTIFICATION HAS CHANGED! @@@@",
        "Host key verification failed.",
    ],
)
def test_host_key_problems_are_distinct(stderr: str) -> None:
    """Talking to a different machine proves nothing about the lease."""
    assert (
        _classify(_result(255, stderr=stderr))
        is AccessVerdict.HOST_KEY_CHANGED
    )


def test_unrecognised_ssh_failure_is_indeterminate_not_revoked() -> None:
    assert (
        _classify(_result(255, stderr="something else entirely"))
        is AccessVerdict.INDETERMINATE
    )


def test_remote_command_exit_status_is_not_an_access_verdict() -> None:
    """ssh passes the command's status through; authentication had succeeded."""
    assert _classify(_result(2)) is AccessVerdict.REMOTE_COMMAND_FAILED
    assert (
        _classify(_result(1, stderr="something else entirely"))
        is AccessVerdict.REMOTE_COMMAND_FAILED
    )


class TestBuyerSshArgv:
    def _argv(self, **overrides):
        params = {
            "host": "10.0.0.1",
            "port": 2222,
            "username": "arkhai-0123456789abcdef",
            "private_key_file": "/run/buyer/key",
            "known_hosts_file": "/run/buyer/known_hosts",
            "strict_host_key_checking": "yes",
            "command": "printf ok",
        }
        params.update(overrides)
        return buyer_ssh_argv(**params)

    def test_uses_only_the_supplied_key(self) -> None:
        argv = self._argv()

        assert "-i" in argv and "/run/buyer/key" in argv
        assert "IdentitiesOnly=yes" in argv
        # An agent or a default key would let an unrelated credential answer
        # the challenge and mask a genuine revocation.
        assert "IdentityAgent=none" in argv
        assert "PreferredAuthentications=publickey" in argv
        assert "PasswordAuthentication=no" in argv
        assert "KbdInteractiveAuthentication=no" in argv
        assert "NumberOfPasswordPrompts=0" in argv
        assert "BatchMode=yes" in argv

    def test_ignores_operator_ssh_configuration(self) -> None:
        """The operator's own config may name aliases, keys, or a proxy."""
        argv = self._argv()

        assert "-F" in argv
        assert argv[argv.index("-F") + 1] == "/dev/null"

    def test_host_key_checking_is_never_disabled(self) -> None:
        argv = self._argv()

        assert "StrictHostKeyChecking=yes" in argv
        assert "UserKnownHostsFile=/run/buyer/known_hosts" in argv
        assert not any("StrictHostKeyChecking=no" in item for item in argv)

    def test_refuses_to_disable_host_key_checking(self) -> None:
        with pytest.raises(ValueError):
            self._argv(strict_host_key_checking="no")

    def test_first_contact_may_pin_the_key(self) -> None:
        argv = self._argv(strict_host_key_checking="accept-new")

        assert "StrictHostKeyChecking=accept-new" in argv

    def test_target_and_command_are_last(self) -> None:
        argv = self._argv()

        assert argv[-2] == "arkhai-0123456789abcdef@10.0.0.1"
        assert argv[-1] == "printf ok"
        assert "-p" in argv and "2222" in argv


class TestHostKeyTrust:
    """First contact is trust-on-first-use, and must not be called otherwise."""

    def test_operator_supplied_known_hosts_is_independently_trusted(
        self, tmp_path
    ) -> None:
        known_hosts = tmp_path / "known_hosts"
        known_hosts.write_text("10.0.0.1 ssh-ed25519 AAAAC3Nz\n")

        trust = resolve_host_key_trust(known_hosts_file=known_hosts)

        assert trust.independently_verified is True
        assert trust.strict_host_key_checking == "yes"
        assert trust.known_hosts_file == known_hosts

    def test_absent_known_hosts_falls_back_to_first_use(self, tmp_path) -> None:
        session_known_hosts = tmp_path / "session_known_hosts"

        trust = resolve_host_key_trust(
            known_hosts_file=None, session_known_hosts=session_known_hosts
        )

        assert trust.independently_verified is False
        assert trust.strict_host_key_checking == "accept-new"
        assert trust.known_hosts_file == session_known_hosts

    def test_empty_operator_file_is_not_trust(self, tmp_path) -> None:
        """An empty file would silently degrade to accepting any key."""
        known_hosts = tmp_path / "known_hosts"
        known_hosts.write_text("   \n")

        with pytest.raises(ValueError):
            resolve_host_key_trust(known_hosts_file=known_hosts)

    def test_missing_operator_file_is_an_error_not_a_downgrade(self, tmp_path) -> None:
        with pytest.raises(ValueError):
            resolve_host_key_trust(known_hosts_file=tmp_path / "absent")

    def test_first_use_trust_states_what_it_did_not_verify(self, tmp_path) -> None:
        trust = resolve_host_key_trust(
            known_hosts_file=None, session_known_hosts=tmp_path / "kh"
        )

        assert "not independently verified" in trust.caveat.lower()

    def test_verified_trust_has_no_caveat(self, tmp_path) -> None:
        known_hosts = tmp_path / "known_hosts"
        known_hosts.write_text("10.0.0.1 ssh-ed25519 AAAAC3Nz\n")

        assert resolve_host_key_trust(known_hosts_file=known_hosts).caveat == ""

    def test_first_use_trust_is_still_a_host_key_trust(self, tmp_path) -> None:
        trust = resolve_host_key_trust(
            known_hosts_file=None, session_known_hosts=tmp_path / "kh"
        )

        assert isinstance(trust, HostKeyTrust)


class TestFalsePositivesFromReview:
    """Cases that a bare `permission denied` substring test accepts wrongly."""

    def test_local_key_load_failure_is_not_revocation(self) -> None:
        """The server never judged the lease key, so this proves nothing."""
        result = _result(
            255,
            stderr=(
                'Load key "/run/buyer/key": Permission denied\r\n'
                "buyer@host: Permission denied (publickey)."
            ),
        )

        assert _classify(result) is AccessVerdict.LOCAL_KEY_ERROR

    def test_malformed_key_then_denial_is_not_revocation(self) -> None:
        result = _result(
            255,
            stderr=(
                'Load key "/run/buyer/key": invalid format\r\n'
                "buyer@host: Permission denied (publickey)."
            ),
        )

        assert _classify(result) is AccessVerdict.LOCAL_KEY_ERROR

    def test_remote_command_permission_error_is_not_revocation(self) -> None:
        """Authentication succeeded; the command failed. The opposite of proof."""
        result = _result(1, stderr="sh: printf: Permission denied")

        assert _classify(result) is AccessVerdict.REMOTE_COMMAND_FAILED

    def test_bare_permission_denied_text_is_not_enough(self) -> None:
        result = _result(255, stderr="Permission denied, please try again.")

        assert _classify(result) is AccessVerdict.INDETERMINATE

    def test_denial_without_the_lease_key_being_offered_is_indeterminate(self) -> None:
        result = _result(
            255,
            stderr=(
                "debug1: Offering public key: /other/key ED25519 SHA256:OTHERKEY\r\n"
                "buyer@host: Permission denied (publickey)."
            ),
        )

        verdict = classify_ssh_probe(result, offered_fingerprint=FINGERPRINT)

        assert verdict is AccessVerdict.INDETERMINATE

    def test_denial_after_offering_the_lease_key_is_revocation(self) -> None:
        result = _result(
            255,
            stderr=(
                "debug1: Offering public key: /run/buyer/key ED25519 SHA256:LEASEKEY\r\n"
                "buyer@host: Permission denied (publickey)."
            ),
        )

        verdict = classify_ssh_probe(result, offered_fingerprint=FINGERPRINT)

        assert verdict is AccessVerdict.KEY_REJECTED


class TestIdentityIsolation:
    def test_absent_lease_key_does_not_fall_back_to_operator_identities(
        self, tmp_path
    ) -> None:
        """`ssh -G` is the check, because the fallback is silent otherwise.

        OpenSSH drops an unreadable `-i` identity and substitutes the invoking
        account's default `~/.ssh/id_*` list, which on an operator workstation
        is the management keys.
        """
        argv = buyer_ssh_argv(
            host="example.invalid",
            port=22,
            username="arkhai-0123456789abcdef",
            private_key_file=str(tmp_path / "absent-key"),
            known_hosts_file=str(tmp_path / "kh"),
            strict_host_key_checking="yes",
            command="true",
            verbose=False,
        )
        expanded = subprocess.run(
            [argv[0], "-G", *argv[1:-1]],
            capture_output=True,
            text=True,
            timeout=30,
        ).stdout.lower()

        identities = [
            line.split(None, 1)[1]
            for line in expanded.splitlines()
            if line.startswith("identityfile ")
        ]
        assert identities == ["none"], identities
        assert "id_rsa" not in expanded and "id_ed25519" not in expanded

    def test_supplied_lease_key_is_the_only_identity(self, tmp_path) -> None:
        key = tmp_path / "lease-key"
        subprocess.run(
            ["ssh-keygen", "-t", "ed25519", "-N", "", "-f", str(key), "-q"],
            check=True,
            capture_output=True,
        )
        argv = buyer_ssh_argv(
            host="example.invalid",
            port=22,
            username="arkhai-0123456789abcdef",
            private_key_file=str(key),
            known_hosts_file=str(tmp_path / "kh"),
            strict_host_key_checking="yes",
            command="true",
            verbose=False,
        )
        expanded = subprocess.run(
            [argv[0], "-G", *argv[1:-1]], capture_output=True, text=True, timeout=30
        ).stdout.lower()

        identities = [
            line.split(None, 1)[1]
            for line in expanded.splitlines()
            if line.startswith("identityfile ")
        ]
        assert identities == ["none", str(key).lower()]

    def test_global_known_hosts_is_not_an_accepted_trust_source(
        self, tmp_path
    ) -> None:
        argv = buyer_ssh_argv(
            host="example.invalid",
            port=22,
            username="arkhai-0123456789abcdef",
            private_key_file=str(tmp_path / "k"),
            known_hosts_file=str(tmp_path / "kh"),
            strict_host_key_checking="yes",
            command="true",
            verbose=False,
        )
        expanded = subprocess.run(
            [argv[0], "-G", *argv[1:-1]], capture_output=True, text=True, timeout=30
        ).stdout.lower()

        globals_line = next(
            line for line in expanded.splitlines()
            if line.startswith("globalknownhostsfile ")
        )
        assert globals_line.split(None, 1)[1].strip() == "/dev/null"

    def test_probe_environment_carries_no_operator_credentials(self) -> None:
        env = buyer_probe_environment()

        assert set(env) == {"PATH", "LANG", "HOME"}
        assert "SSH_AUTH_SOCK" not in env
        assert env["HOME"] == "/nonexistent"


class TestLeaseKeyMaterial:
    def test_usable_key_yields_a_fingerprint(self, tmp_path) -> None:
        key = tmp_path / "k"
        subprocess.run(
            ["ssh-keygen", "-t", "ed25519", "-N", "", "-f", str(key), "-q"],
            check=True,
            capture_output=True,
        )

        material = freeze_lease_key(key)

        assert material.fingerprint.startswith("SHA256:")

    def test_absent_key_is_rejected_before_any_market_effect(self, tmp_path) -> None:
        with pytest.raises(ValueError):
            freeze_lease_key(tmp_path / "absent")

    def test_unusable_key_is_rejected(self, tmp_path) -> None:
        junk = tmp_path / "junk"
        junk.write_text("not a key\n")

        with pytest.raises(ValueError):
            freeze_lease_key(junk)
