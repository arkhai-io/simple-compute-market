"""Secret-contained processes for the protected real-provider E2E lane."""

from __future__ import annotations

import json
import os
import queue
import re
import shutil
import stat
import subprocess
import tempfile
import sys
import threading
from pathlib import Path
from typing import Any, Mapping, Sequence

_WEBHOOK_SECRET = re.compile(r"\b(whsec_[A-Za-z0-9]+)\b")
_SENSITIVE_ENV = re.compile(r"(?:STRIPE|WEBHOOK)", re.IGNORECASE)


class ProcessUnavailable(RuntimeError):
    """A protected external process could not satisfy its contract."""


class LifecycleContractError(RuntimeError):
    """The marketplace-owned lifecycle bridge returned invalid state."""


class StripeWebhookForwarder:
    """Run Stripe CLI while discarding every line after in-memory secret capture."""

    def __init__(self, *, api_key: str, forward_to: str, executable: str = "stripe") -> None:
        self._api_key = api_key
        self._forward_to = forward_to
        self._executable = executable
        self._process: subprocess.Popen[str] | None = None
        self._values: queue.Queue[str | None] = queue.Queue()
        self._reader: threading.Thread | None = None

    def start(self, timeout: float = 30.0) -> str:
        if self._process is not None:
            raise ProcessUnavailable("Stripe webhook forwarder is already running")
        executable = shutil.which(self._executable)
        if executable is None:
            raise ProcessUnavailable("Stripe CLI is unavailable")
        env = dict(os.environ)
        env["STRIPE_API_KEY"] = self._api_key
        try:
            self._process = subprocess.Popen(
                [executable, "listen", "--forward-to", self._forward_to],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                env=env,
            )
        except OSError as exc:
            raise ProcessUnavailable("Stripe CLI could not start") from exc
        self._reader = threading.Thread(target=self._discard_output, daemon=True)
        self._reader.start()
        try:
            value = self._values.get(timeout=timeout)
        except queue.Empty as exc:
            self.stop()
            raise ProcessUnavailable("Stripe CLI did not provide a webhook secret") from exc
        if value is None:
            self.stop()
            raise ProcessUnavailable("Stripe CLI exited before webhook forwarding was ready")
        return value

    def _discard_output(self) -> None:
        process = self._process
        assert process is not None and process.stdout is not None
        supplied = False
        try:
            for line in process.stdout:
                if not supplied:
                    match = _WEBHOOK_SECRET.search(line)
                    if match is not None:
                        supplied = True
                        self._values.put(match.group(1))
                # Never retain or forward Stripe CLI output. It may contain the
                # signing secret, event payloads, or provider identifiers.
        finally:
            if not supplied:
                self._values.put(None)

    def stop(self) -> None:
        process = self._process
        if process is None:
            return
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
        if process.stdout is not None:
            process.stdout.close()
        self._process = None

    def __enter__(self) -> "StripeWebhookForwarder":
        return self

    def __exit__(self, *_exc: object) -> None:
        self.stop()


class EphemeralServiceEnv:
    """Create a mode-0600 authority env file and remove it on every outcome."""

    def __init__(
        self,
        *,
        api_key: str,
        webhook_secret: str,
        base_path: Path | None = None,
    ) -> None:
        self._values = {
            "HOSTED_SETTLEMENT_PROVIDER_KIND": "stripe",
            "HOSTED_SETTLEMENT_STRIPE_MODE": "test",
            "HOSTED_SETTLEMENT_STRIPE_SECRET_KEY": api_key,
            "HOSTED_SETTLEMENT_STRIPE_WEBHOOK_SECRET": webhook_secret,
        }
        self._base_path = base_path
        self._directory: Path | None = None
        self.path: Path | None = None

    def __enter__(self) -> Path:
        values = self._read_base()
        values.update(self._values)
        directory = Path(tempfile.mkdtemp(prefix="arkhai-hosted-real-stripe-"))
        directory.chmod(stat.S_IRWXU)
        path = directory / "authority.env"
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
                for key, value in values.items():
                    if not _valid_env_name(key) or "\n" in value or "\r" in value:
                        raise ProcessUnavailable("authority environment contains an invalid entry")
                    stream.write(f"{key}={value}\n")
        except BaseException:
            path.unlink(missing_ok=True)
            directory.rmdir()
            raise
        self._directory = directory
        self.path = path
        return path

    def _read_base(self) -> dict[str, str]:
        if self._base_path is None:
            return {}
        try:
            text = self._base_path.read_text(encoding="utf-8")
        except OSError as exc:
            raise ProcessUnavailable("authority environment template is unavailable") from exc
        values: dict[str, str] = {}
        for line in text.splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            if "=" not in stripped:
                raise ProcessUnavailable("authority environment template is malformed")
            key, value = stripped.split("=", 1)
            if not _valid_env_name(key) or key in values:
                raise ProcessUnavailable("authority environment template is malformed")
            values[key] = value
        return values

    def __exit__(self, *_exc: object) -> None:
        if self.path is not None:
            self.path.unlink(missing_ok=True)
        if self._directory is not None:
            try:
                self._directory.rmdir()
            except OSError:
                pass
        self.path = None
        self._directory = None


class ComposeStack:
    """Start the ordinary digest-pinned marketplace/authority topology."""

    def __init__(
        self,
        *,
        compose_env: Path,
        compose_files: Sequence[Path],
        executable: str = "docker",
        cwd: Path,
    ) -> None:
        self._cwd = cwd
        self._base = [executable, "compose", "--env-file", str(compose_env)]
        for path in compose_files:
            self._base.extend(("-f", str(path)))
        self._started = False
        self._runtime_env: dict[str, str] | None = None

    def start(self, *, authority_env_path: Path) -> None:
        env = dict(os.environ)
        env["HOSTED_SETTLEMENT_ENV_FILE"] = str(authority_env_path)
        self._runtime_env = env
        self._run((*self._base, "up", "-d", "--wait"), env=env, check=True)
        self._started = True

    def stop(self) -> None:
        env = self._runtime_env or dict(os.environ)
        self._run(
            (*self._base, "down", "-v", "--remove-orphans"),
            env=env,
            check=False,
        )
        self._started = False
        self._runtime_env = None

    def _run(self, argv: Sequence[str], *, env: Mapping[str, str], check: bool) -> None:
        try:
            completed = subprocess.run(
                argv,
                cwd=self._cwd,
                env=env,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                timeout=900,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise ProcessUnavailable("ordinary hosted Compose operation was unavailable") from exc
        if check and completed.returncode != 0:
            raise ProcessUnavailable("ordinary hosted Compose startup failed")

    def __enter__(self) -> "ComposeStack":
        return self

    def __exit__(self, *_exc: object) -> None:
        self.stop()


class MarketplaceLifecycleSession:
    """In-memory JSON-lines bridge to the marketplace-owned staged scenario."""

    def __init__(self, command: Sequence[str], *, cwd: Path) -> None:
        if not command or any(not isinstance(item, str) or not item for item in command):
            raise LifecycleContractError("lifecycle command must be a non-empty argv array")
        self._command = tuple(command)
        self._cwd = cwd
        self._process: subprocess.Popen[str] | None = None
        self._stderr_reader: threading.Thread | None = None

    def start(self) -> None:
        env = {
            key: value
            for key, value in os.environ.items()
            if not _SENSITIVE_ENV.search(key)
        }
        try:
            self._process = subprocess.Popen(
                self._command,
                cwd=self._cwd,
                env=env,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                bufsize=1,
            )
        except OSError as exc:
            raise ProcessUnavailable("marketplace lifecycle bridge was unavailable") from exc
        self._stderr_reader = threading.Thread(target=self._discard_stderr, daemon=True)
        self._stderr_reader.start()

    def request(self, action: str, **fields: object) -> dict[str, Any]:
        process = self._process
        if process is None or process.stdin is None or process.stdout is None:
            raise LifecycleContractError("marketplace lifecycle bridge is not running")
        request = {"action": action, **fields}
        process.stdin.write(json.dumps(request, separators=(",", ":")) + "\n")
        process.stdin.flush()
        line = process.stdout.readline()
        if not line:
            raise ProcessUnavailable("marketplace lifecycle bridge exited unexpectedly")
        try:
            response = json.loads(line)
        except json.JSONDecodeError as exc:
            raise LifecycleContractError("marketplace lifecycle bridge returned invalid JSON") from exc
        if not isinstance(response, dict):
            raise LifecycleContractError("marketplace lifecycle bridge returned a non-object")
        if response.get("ok") is not True:
            if response.get("code") == "marketplace_unavailable":
                raise ProcessUnavailable("marketplace lifecycle state was unavailable")
            raise LifecycleContractError("marketplace lifecycle bridge rejected a stage")
        return response

    def _discard_stderr(self) -> None:
        process = self._process
        assert process is not None and process.stderr is not None
        for _line in process.stderr:
            # Staged output can contain ephemeral buyer actions and provider
            # identifiers; neither belongs in workflow logs or evidence.
            pass

    def stop(self) -> None:
        process = self._process
        if process is None:
            return
        if process.stdin is not None:
            try:
                process.stdin.write('{"action":"shutdown"}\n')
                process.stdin.flush()
            except (BrokenPipeError, OSError):
                pass
            process.stdin.close()
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
        if process.stdout is not None:
            process.stdout.close()
        if process.stderr is not None:
            process.stderr.close()
        self._process = None

    def __enter__(self) -> "MarketplaceLifecycleSession":
        self.start()
        return self

    def __exit__(self, *_exc: object) -> None:
        self.stop()


def parse_lifecycle_command(value: str | None) -> tuple[str, ...]:
    if not value:
        return (sys.executable, "-m", "src.hosted_real_stripe.lifecycle_bridge")
    try:
        command = json.loads(value)
    except json.JSONDecodeError as exc:
        raise LifecycleContractError("lifecycle command must be a JSON argv array") from exc
    if not isinstance(command, list) or any(not isinstance(item, str) for item in command):
        raise LifecycleContractError("lifecycle command must be a JSON argv array")
    return tuple(command)


def _valid_env_name(value: str) -> bool:
    return bool(re.fullmatch(r"[A-Z_][A-Z0-9_]*", value))
