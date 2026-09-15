#!/usr/bin/python3
"""Rootless real-CLI proof for LUKS2 verification under a request_key filter."""

from __future__ import annotations

import ctypes
import json
import os
import re
import resource
import stat
import subprocess
import sys
import tempfile
from pathlib import Path


EXPECTED_VERSION = "2.4.3"
REQUEST_KEY_X86_64 = 249
SCMP_ACT_ALLOW = 0x7FFF0000
SCMP_ACT_KILL_PROCESS = 0x80000000
# Public deterministic fixture material. It is not a production storage key.
FIXTURE_KEY = bytes.fromhex("91" * 32)
WRONG_KEY = bytes.fromhex("92" * 32)
SAFE_ENV = {"LC_ALL": "C", "PATH": "/usr/sbin:/usr/bin:/sbin:/bin"}


class QualificationRefused(RuntimeError):
    def __init__(self, code: str, returncode: int | None = None):
        super().__init__(code)
        self.code = code
        self.returncode = returncode


def cryptsetup_binary() -> Path:
    path = Path(os.environ.get("ARKHAI_CRYPTSETUP_PATH", "/usr/sbin/cryptsetup"))
    if not path.is_absolute():
        raise QualificationRefused("cryptsetup-path-not-absolute")
    try:
        info = path.lstat()
    except FileNotFoundError as exc:
        raise QualificationRefused("cryptsetup-unavailable") from exc
    if not stat.S_ISREG(info.st_mode) or info.st_uid != 0 or info.st_nlink != 1:
        raise QualificationRefused("cryptsetup-file-unsafe")
    if stat.S_IMODE(info.st_mode) & 0o022:
        raise QualificationRefused("cryptsetup-file-unsafe")
    return path


def require_version(binary: Path) -> None:
    try:
        result = subprocess.run(
            (str(binary), "--version"),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            timeout=10,
            check=False,
            env=SAFE_ENV,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise QualificationRefused("cryptsetup-version-unavailable") from exc
    try:
        version = result.stdout.decode("ascii", errors="strict").strip()
    except UnicodeError as exc:
        raise QualificationRefused("cryptsetup-version-unqualified") from exc
    if result.returncode != 0 or re.fullmatch(
        rf"cryptsetup {EXPECTED_VERSION}(?: .*)?", version
    ) is None:
        raise QualificationRefused("cryptsetup-version-unqualified")


def create_private_backing(path: Path) -> None:
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        os.ftruncate(descriptor, 32 * 1024 * 1024)
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def install_request_key_kill_filter() -> None:
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    seccomp = ctypes.CDLL("libseccomp.so.2")
    seccomp.seccomp_init.argtypes = [ctypes.c_uint32]
    seccomp.seccomp_init.restype = ctypes.c_void_p
    seccomp.seccomp_syscall_resolve_name.argtypes = [ctypes.c_char_p]
    seccomp.seccomp_syscall_resolve_name.restype = ctypes.c_int
    seccomp.seccomp_rule_add.argtypes = [
        ctypes.c_void_p,
        ctypes.c_uint32,
        ctypes.c_int,
        ctypes.c_uint,
    ]
    seccomp.seccomp_rule_add.restype = ctypes.c_int
    seccomp.seccomp_load.argtypes = [ctypes.c_void_p]
    seccomp.seccomp_load.restype = ctypes.c_int
    seccomp.seccomp_release.argtypes = [ctypes.c_void_p]

    request_key = seccomp.seccomp_syscall_resolve_name(b"request_key")
    if request_key != REQUEST_KEY_X86_64:
        raise RuntimeError("request_key syscall identity mismatch")
    context = seccomp.seccomp_init(SCMP_ACT_ALLOW)
    if not context:
        raise RuntimeError("seccomp filter allocation failed")
    try:
        if (
            seccomp.seccomp_rule_add(
                context,
                SCMP_ACT_KILL_PROCESS,
                request_key,
                0,
            )
            != 0
        ):
            raise RuntimeError("seccomp rule installation failed")
        if seccomp.seccomp_load(context) != 0:
            raise RuntimeError("seccomp filter activation failed")
    finally:
        seccomp.seccomp_release(context)


def exec_filtered() -> None:
    if sys.platform != "linux" or os.uname().machine != "x86_64":
        raise RuntimeError("qualification launcher requires Linux x86-64")
    binary = Path(sys.argv[2])
    install_request_key_kill_filter()
    os.execve(str(binary), (str(binary), *sys.argv[3:]), SAFE_ENV)


def classify(returncode: int) -> dict[str, int | str]:
    if returncode < 0:
        return {"kind": "signal", "code": -returncode}
    return {"kind": "exit", "code": returncode}


def run_filtered(binary: Path, arguments: tuple[str, ...], key: bytes) -> int:
    try:
        result = subprocess.run(
            (
                sys.executable,
                str(Path(__file__).resolve()),
                "--exec-filtered",
                str(binary),
                *arguments,
            ),
            input=key,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=120,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise QualificationRefused("cryptsetup-filtered-timeout") from exc
    return result.returncode


def qualify(binary: Path) -> dict[str, object]:
    if sys.platform != "linux" or os.uname().machine != "x86_64":
        raise QualificationRefused("platform-unqualified")
    require_version(binary)
    with tempfile.TemporaryDirectory(prefix="m22-cryptsetup-keyring-") as temporary:
        root = Path(temporary)
        root.chmod(0o700)
        backing = root / "volume.luks2"
        create_private_backing(backing)
        try:
            formatted = subprocess.run(
                (
                    str(binary),
                    "--batch-mode",
                    "--type",
                    "luks2",
                    "--key-file",
                    "-",
                    "--keyfile-size",
                    "32",
                    "luksFormat",
                    str(backing),
                ),
                input=FIXTURE_KEY,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=120,
                check=False,
                env=SAFE_ENV,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise QualificationRefused("cryptsetup-format-unavailable") from exc
        if formatted.returncode != 0:
            raise QualificationRefused(
                "cryptsetup-format-failed", formatted.returncode
            )

        common = (
            "--type",
            "luks2",
            "--test-passphrase",
            "--key-file",
            "-",
            "--keyfile-size",
            "32",
            "open",
            str(backing),
        )
        corrected = (*common[:3], "--disable-keyring", *common[3:])
        results = {
            "without_disable_keyring": classify(
                run_filtered(binary, common, FIXTURE_KEY)
            ),
            "with_disable_keyring": classify(
                run_filtered(binary, corrected, FIXTURE_KEY)
            ),
            "wrong_key_with_disable_keyring": classify(
                run_filtered(binary, corrected, WRONG_KEY)
            ),
        }

    if results["without_disable_keyring"] != {"kind": "signal", "code": 31}:
        raise QualificationRefused("unfiltered-result-mismatch")
    if results["with_disable_keyring"] != {"kind": "exit", "code": 0}:
        raise QualificationRefused("corrected-result-mismatch")
    wrong = results["wrong_key_with_disable_keyring"]
    if (
        wrong["kind"] != "exit"
        or not isinstance(wrong["code"], int)
        or wrong["code"] <= 0
    ):
        raise QualificationRefused("wrong-key-result-mismatch")
    return {
        "schema": "arkhai.cryptsetup-keyring-filter-qualification.v1",
        "qualified": True,
        "cryptsetup_version": EXPECTED_VERSION,
        "request_key_syscall": REQUEST_KEY_X86_64,
        "results": results,
    }


def main() -> int:
    try:
        result = qualify(cryptsetup_binary())
    except QualificationRefused as exc:
        result = {
            "schema": "arkhai.cryptsetup-keyring-filter-qualification.v1",
            "qualified": False,
            "error_code": exc.code,
        }
        if exc.returncode is not None:
            result["returncode"] = exc.returncode
        print(json.dumps(result, sort_keys=True))
        return 1
    except Exception:
        print(
            json.dumps(
                {
                    "schema": "arkhai.cryptsetup-keyring-filter-qualification.v1",
                    "qualified": False,
                    "error_code": "harness-internal-failure",
                },
                sort_keys=True,
            )
        )
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    if sys.argv[1:2] == ["--exec-filtered"]:
        exec_filtered()
    raise SystemExit(main())
