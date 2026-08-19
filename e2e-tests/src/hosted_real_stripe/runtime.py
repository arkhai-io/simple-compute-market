"""Secret-contained processes for the protected Stripe test-mode system lane."""

from __future__ import annotations

import json
import os
from collections import deque
from dataclasses import dataclass
import queue
import re
import shutil
import stat
import subprocess
import signal
import tempfile
import sys
import threading
from pathlib import Path
from core_buyer.profile_service import BuyerProfileService
from market_identity import (
    CredentialProviderKind,
    CredentialReference,
    IdentityScheme,
    ProfileRepository,
    create_signer,
)
from typing import Any, Mapping, Sequence

_WEBHOOK_SECRET = re.compile(r"\b(whsec_[A-Za-z0-9]+)\b")
_SENSITIVE_ENV = re.compile(r"(?:STRIPE|WEBHOOK)", re.IGNORECASE)
#: The staged bridge speaks to the loopback stack and to nothing else, so an
#: ambient proxy is never right for it. Clients that trust the environment
#: build a transport for whatever they find there before any request is made,
#: which turns an unrelated shell setting into a failure inside the run.
_PROXY_ENV = re.compile(r"^(?:all|http|https|ftp|no)_proxy$", re.IGNORECASE)
_SAFE_CONFIG_VALUE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/@-]{0,255}$")
_PROTECTED_PROFILE = "hosted-stripe-test"
_REGISTRY_AUTH_SECTION = "[registry.auth]"
#: A bearer token, not a configuration identifier: URL-safe base64 begins with
#: whatever it begins with, and roughly one generated key in thirty starts with
#: "_" or "-". Requiring a leading alphanumeric here made a run fail on the
#: value it had been handed, intermittently. What matters is that the token
#: cannot break out of the TOML string it is written into.
_REGISTRY_BEARER = re.compile(r"^[A-Za-z0-9._~+/=:-]{1,512}$")
#: A bounded tail: enough to read a traceback, never a transcript.
_DIAGNOSTIC_LINES = 60
_DIAGNOSTIC_LINE_LIMIT = 2048
#: Long enough for a dying process to finish writing, short enough that a
#: live one is not waited on.
_DIAGNOSTIC_DRAIN_SECONDS = 5.0


class ProcessUnavailable(RuntimeError):
    """A protected external process could not satisfy its contract."""


class LifecycleContractError(RuntimeError):
    """The marketplace-owned lifecycle bridge returned invalid state."""


@dataclass(frozen=True)
class RuntimeAuthorityIdentity:
    """Public runtime response identity derived from its injected credential."""

    authority_id: str
    scheme: str
    identifier: str


def require_runtime_authority_identity(
    environment_path: Path,
    *,
    release_authority_address: str,
) -> RuntimeAuthorityIdentity:
    values = _read_environment_file(environment_path)
    authority_id = values.get("HOSTED_SETTLEMENT_AUTHORITY_ID", "")
    scheme = values.get("HOSTED_SETTLEMENT_AUTHORITY_IDENTITY_SCHEME", "")
    credential = values.get("HOSTED_SETTLEMENT_AUTHORITY_PRIVATE_KEY", "")
    if not _SAFE_CONFIG_VALUE.fullmatch(authority_id) or scheme not in {
        "eip191",
        "ed25519",
    }:
        raise ProcessUnavailable("runtime authority identity is invalid")
    try:
        signer = create_signer(scheme, credential)
    except (TypeError, ValueError) as exc:
        raise ProcessUnavailable("runtime authority credential is invalid") from exc
    identifier = signer.identity.identifier
    if scheme == "eip191" and identifier == release_authority_address.lower():
        raise ProcessUnavailable("runtime and release authority credentials must be independent")
    return RuntimeAuthorityIdentity(
        authority_id=authority_id,
        scheme=scheme,
        identifier=identifier,
    )


class LifecycleConvergenceTimeout(TimeoutError):
    """A named marketplace state did not converge within its bound."""


class StripeWebhookForwarder:
    """Run Stripe CLI while discarding every line after in-memory secret capture."""

    def __init__(self, *, api_key: str, forward_to: str, executable: str = "stripe") -> None:
        self._api_key = api_key
        self._forward_to = forward_to
        self._executable = executable
        self._process: subprocess.Popen[str] | None = None
        self._values: queue.Queue[str | None] = queue.Queue()
        self._reader: threading.Thread | None = None
        self._paused = False

    def start(self, timeout: float = 30.0) -> str:
        if self._process is not None:
            raise ProcessUnavailable("Stripe webhook forwarder is already running")
        executable = shutil.which(self._executable)
        if executable is None:
            raise ProcessUnavailable("Stripe CLI is unavailable")
        env = {key: value for key, value in os.environ.items() if not _SENSITIVE_ENV.search(key)}
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

    def pause(self) -> None:
        process = self._process
        if process is None or process.poll() is not None or not hasattr(signal, "SIGSTOP"):
            raise ProcessUnavailable("Stripe webhook forwarder cannot be paused")
        process.send_signal(signal.SIGSTOP)
        self._paused = True

    def resume(self) -> None:
        process = self._process
        if process is None or process.poll() is not None or not hasattr(signal, "SIGCONT"):
            raise ProcessUnavailable("Stripe webhook forwarder cannot be resumed")
        process.send_signal(signal.SIGCONT)
        self._paused = False

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
        if self._paused and process.poll() is None and hasattr(signal, "SIGCONT"):
            process.send_signal(signal.SIGCONT)
            self._paused = False
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


def _caller_scheme(caller: str) -> str:
    return caller.partition(":")[0]


def _caller_identifier(caller: str) -> str:
    return caller.partition(":")[2]


class EphemeralServiceEnv:
    """Create a mode-0600 authority env file and remove it on every outcome."""

    def __init__(
        self,
        *,
        api_key: str,
        webhook_secret: str,
        authority_environment: str,
        storefront_caller: str,
        authority_caller: str,
        manifest_digest: str,
        release_authority_id: str,
        release_authority_address: str,
        release_repository: str,
        release_workflow_ref: str,
        release_source_commit: str,
        base_path: Path | None = None,
        shared_directory: Path,
    ) -> None:
        self._values = {
            "HOSTED_SETTLEMENT_PROVIDER_KIND": "stripe",
            "HOSTED_SETTLEMENT_STRIPE_MODE": "test",
            "HOSTED_SETTLEMENT_STRIPE_SECRET_KEY": api_key,
            "HOSTED_SETTLEMENT_STRIPE_WEBHOOK_SECRET": webhook_secret,
            "HOSTED_SETTLEMENT_MANIFEST_DIGEST": manifest_digest,
            # The environment the run pins everywhere else; the authority is
            # told it here rather than trusted to have been told the same.
            "HOSTED_SETTLEMENT_ENVIRONMENT": authority_environment,
            # Fixed by the Compose file's named volume, not by whoever supplied
            # the credentials, so the harness states it.
            "HOSTED_SETTLEMENT_DATABASE_PATH": (
                "/var/lib/hosted-settlement/hosted-settlement.sqlite3"
            ),
            "HOSTED_SETTLEMENT_CHECKOUT_SUCCESS_URL": "http://127.0.0.1:18081/checkout/success",
            "HOSTED_SETTLEMENT_CHECKOUT_CANCEL_URL": "http://127.0.0.1:18081/checkout/cancel",
            # Onboarding redirects land on the same loopback storefront. Every
            # callback URL the authority allows must be distinct.
            "HOSTED_SETTLEMENT_ACCOUNT_LINK_RETURN_URLS": "http://127.0.0.1:18081/connect/return",
            "HOSTED_SETTLEMENT_ACCOUNT_LINK_REFRESH_URLS": (
                "http://127.0.0.1:18081/connect/refresh"
            ),
            "HOSTED_SETTLEMENT_RELEASE_PATH": "/opt/hosted-settlement/release/release-manifest.json",
            "HOSTED_SETTLEMENT_RELEASE_AUTHORITY_ID": release_authority_id,
            "HOSTED_SETTLEMENT_RELEASE_AUTHORITY_ADDRESS": release_authority_address,
            "HOSTED_SETTLEMENT_RELEASE_REPOSITORY": release_repository,
            "HOSTED_SETTLEMENT_RELEASE_WORKFLOW_REF": release_workflow_ref,
            "HOSTED_SETTLEMENT_RELEASE_SOURCE_COMMIT": release_source_commit,
            # The authority refuses every storefront principal until it is told
            # which one exists. The harness builds that storefront, so it says
            # so rather than trusting a credential payload to agree with it.
            "HOSTED_SETTLEMENT_STOREFRONT_CALLERS": storefront_caller,
            # The portable resolver is this authority calling itself: it signs
            # the lookup with its own runtime key and stamps portable
            # attestations with the same identity. Both sides therefore name
            # the runtime authority, not the independent key that signed the
            # release -- those are deliberately different principals.
            "HOSTED_SETTLEMENT_RESOLVER_CALLERS": authority_caller,
            "HOSTED_SETTLEMENT_REMOTE_RESOLVERS_JSON": json.dumps(
                [
                    {
                        "resolver_id": "vm-portable",
                        "evaluator_id": "vm-portable",
                        "base_url": "http://127.0.0.1:8080",
                        "authority_id": authority_environment,
                        "principals": [
                            {
                                "scheme": _caller_scheme(authority_caller),
                                "identifier": _caller_identifier(authority_caller),
                            }
                        ],
                        "portable_authority_address": _caller_identifier(
                            authority_caller
                        ),
                        "allow_insecure_loopback": True,
                    }
                ],
                separators=(",", ":"),
                sort_keys=True,
            ),
        }
        self._base_path = base_path
        self._shared_directory = shared_directory
        self._directory: Path | None = None
        self.path: Path | None = None

    def __enter__(self) -> Path:
        values = self._read_base()
        values.update(self._values)
        directory = Path(
            tempfile.mkdtemp(
                prefix="arkhai-hosted-stripe-test-",
                dir=self._shared_directory,
            )
        )
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
        return _read_environment_file(self._base_path)

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


def _fill_registry_auth(text: str) -> str:
    """Supply the bearer key for every registry the template says demands one.

    The declaration is committed and reviewable -- which registries are private
    is not a secret -- and the key is not, so it arrives from the run's own
    environment. A template that declares none is returned untouched, and a run
    that holds no key leaves the declaration empty rather than inventing one,
    so the registry refuses it visibly instead of being handed a wrong value.
    """

    if _REGISTRY_AUTH_SECTION not in text:
        return text
    key = os.environ.get("VMS_REGISTRY_BOOTSTRAP_API_KEY", "")
    if not key:
        return text
    if not _REGISTRY_BEARER.fullmatch(key):
        raise ProcessUnavailable("registry bootstrap authorization is invalid")
    head, _, tail = text.partition(_REGISTRY_AUTH_SECTION)
    section, boundary, rest = tail.partition("\n[")
    filled = re.sub(r'(?m)^("[^"\n]+"\s*=\s*)""$', rf'\1"{key}"', section)
    return head + _REGISTRY_AUTH_SECTION + filled + boundary + rest


class EphemeralMarketplaceConfig:
    """Render release-pinned marketplace trust without provider identifiers."""

    def __init__(
        self,
        *,
        template: Path,
        account_ref: str,
        authority_id: str,
        authority_scheme: str,
        authority_address: str,
        authority_environment: str,
        manifest_digest: str,
        funding_profile: str,
        shared_directory: Path,
    ) -> None:
        self._template = template
        self._values = {
            "account_ref": account_ref,
            "authority_id": authority_id,
            "authority_scheme": authority_scheme,
            "authority_address": authority_address,
            "authority_environment": authority_environment,
            "manifest_digest": manifest_digest,
            "funding_profile": funding_profile,
        }
        self._shared_directory = shared_directory
        self._directory: Path | None = None
        self.path: Path | None = None

    def __enter__(self) -> Path:
        if any(not _SAFE_CONFIG_VALUE.fullmatch(value) for value in self._values.values()):
            raise ProcessUnavailable("marketplace release configuration is invalid")
        try:
            text = self._template.read_text(encoding="utf-8")
        except OSError as exc:
            raise ProcessUnavailable("marketplace configuration template is unavailable") from exc
        text = _fill_registry_auth(text)
        text = _replace_toml_setting(text, "authority_id", self._values["authority_id"])
        text = _replace_toml_setting(
            text,
            "environment",
            self._values["authority_environment"],
        )
        text = _replace_toml_setting(
            text,
            "expected_manifest_digest",
            self._values["manifest_digest"],
        )
        stripe_header = "[Settlement.stripe]\n"
        if text.count(stripe_header) != 1:
            raise ProcessUnavailable("marketplace configuration has no exact Stripe section")
        text = text.replace(
            stripe_header,
            stripe_header + f'account_ref = "{self._values["account_ref"]}"\n',
            1,
        )
        text, profile_count = re.subn(
            r'funding_profile\s*=\s*"[^"]+"',
            f'funding_profile = "{self._values["funding_profile"]}"',
            text,
            count=1,
        )
        if profile_count != 1:
            raise ProcessUnavailable("marketplace config has no exact hosted funding profile")
        authority_pattern = re.compile(
            r"(\[Settlement\.stripe\.authority\]\n)principals = \[[^\n]+\]"
        )
        text, count = authority_pattern.subn(
            lambda match: (
                match.group(1)
                + 'principals = [{ scheme = "'
                + self._values["authority_scheme"]
                + '", identifier = "'
                + self._values["authority_address"]
                + '" }]'
            ),
            text,
            count=1,
        )
        if count != 1:
            raise ProcessUnavailable("marketplace authority trust section is invalid")
        directory = Path(
            tempfile.mkdtemp(
                prefix="arkhai-hosted-stripe-test-config-",
                dir=self._shared_directory,
            )
        )
        directory.chmod(stat.S_IRWXU)
        path = directory / "storefront.toml"
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
                stream.write(text)
        except BaseException:
            path.unlink(missing_ok=True)
            directory.rmdir()
            raise
        self._directory = directory
        self.path = path
        return path

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


class EphemeralBuyerConfig:
    """Render role-correct buyer trust from the same staged producer identity."""

    def __init__(
        self,
        *,
        template: Path,
        authority_id: str,
        authority_scheme: str,
        authority_address: str,
        authority_environment: str,
        authority_base_url: str,
        manifest_digest: str,
        funding_profile: str,
        buyer_identity_scheme: str,
        shared_directory: Path,
    ) -> None:
        self._template = template
        self._values = {
            "authority_id": authority_id,
            "authority_scheme": authority_scheme,
            "authority_address": authority_address,
            "authority_environment": authority_environment,
            "authority_base_url": authority_base_url,
            "manifest_digest": manifest_digest,
            "funding_profile": funding_profile,
            "buyer_identity_scheme": buyer_identity_scheme,
        }
        self._buyer_identity_scheme = buyer_identity_scheme
        self._shared_directory = shared_directory
        self._directory: Path | None = None
        self.path: Path | None = None

    def __enter__(self) -> Path:
        if any(not _SAFE_CONFIG_VALUE.fullmatch(value) for value in self._values.values()):
            raise ProcessUnavailable("buyer release configuration is invalid")
        try:
            text = self._template.read_text(encoding="utf-8")
        except OSError as exc:
            raise ProcessUnavailable("buyer configuration template is unavailable") from exc
        text = _fill_registry_auth(text)
        for key, value in (
            ("authority_id", self._values["authority_id"]),
            ("environment", self._values["authority_environment"]),
        ):
            pattern = re.compile(rf"^{re.escape(key)} = \"[^\n]*\"$", re.MULTILINE)
            text, count = pattern.subn(f'{key} = "{value}"', text)
            if count != 2:
                raise ProcessUnavailable(f"buyer configuration has no exact {key} bindings")
        text = _replace_toml_setting(
            text,
            "base_url",
            self._values["authority_base_url"],
        )
        text = _replace_toml_setting(
            text,
            "expected_manifest_digest",
            self._values["manifest_digest"],
        )
        text = _replace_toml_setting(
            text,
            "funding_profile",
            self._values["funding_profile"],
        )
        authority_pattern = re.compile(
            r"(\[Settlement\.stripe\.authority\]\n)principals = \[[^\n]+\]"
        )
        text, count = authority_pattern.subn(
            lambda match: (
                match.group(1)
                + 'principals = [{ scheme = "'
                + self._values["authority_scheme"]
                + '", identifier = "'
                + self._values["authority_address"]
                + '" }]'
            ),
            text,
            count=1,
        )
        if count != 1:
            raise ProcessUnavailable("buyer authority trust section is invalid")
        directory = Path(
            tempfile.mkdtemp(
                prefix="arkhai-hosted-stripe-test-buyer-",
                dir=self._shared_directory,
            )
        )
        directory.chmod(stat.S_IRWXU)
        try:
            store_path = directory / "profiles.json"
            BuyerProfileService(
                repository=ProfileRepository(store_path),
                run_logs_directory=directory / "runs",
            ).create(
                name="protected-hosted-stripe",
                credential_reference=CredentialReference(
                    provider=CredentialProviderKind.ENVIRONMENT,
                    locator="HOSTED_SETTLEMENT_E2E_BUYER_IDENTITY_CREDENTIAL",
                ),
                scheme=IdentityScheme(self._buyer_identity_scheme),
                generate=False,
                select=True,
            )
            text = _replace_toml_setting(text, "store_path", str(store_path))
            text = _replace_toml_setting(
                text,
                "authorization_journal_path",
                str(directory / "funding-authorizations.jsonl"),
            )
            path = directory / "buyer.toml"
            descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
            with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
                stream.write(text)
        except BaseException:
            shutil.rmtree(directory, ignore_errors=True)
            raise
        self._directory = directory
        self.path = path
        return path

    def __exit__(self, *_exc: object) -> None:
        if self._directory is not None:
            shutil.rmtree(self._directory, ignore_errors=True)
        self.path = None
        self._directory = None


#: A volume Compose named for the project looks like ``<project>_<name>``; one
#: a service asked for anonymously is addressed only by its own digest.
_ANONYMOUS_VOLUME = re.compile(r"^[0-9a-f]{64}$")


class ComposeStack:
    """Start the ordinary digest-pinned marketplace/authority topology."""

    def __init__(
        self,
        *,
        compose_env: Path,
        compose_files: Sequence[Path],
        executable: str = "docker",
        cwd: Path,
        retain_diagnostics: bool = False,
        retain_authority_state: bool = False,
    ) -> None:
        self._cwd = cwd
        self._retain_authority_state = retain_authority_state
        self._preexisting_volumes: frozenset[str] = frozenset()
        # Compose prints the container output that says why an operation
        # failed. Held for a development operator only, on the same terms as
        # the staged bridge's stderr.
        self._retain_diagnostics = retain_diagnostics
        self._base = [
            executable,
            "compose",
            "--profile",
            _PROTECTED_PROFILE,
            "--env-file",
            str(compose_env),
        ]
        for compose_file in compose_files:
            self._base.extend(("-f", str(compose_file)))
        self._started = False
        self._runtime_env: dict[str, str] | None = None

    def start(
        self,
        *,
        authority_env_path: Path,
        marketplace_config_path: Path,
        storefront_servicing_interval_seconds: float | None = None,
    ) -> None:
        env = {key: value for key, value in os.environ.items() if not _SENSITIVE_ENV.search(key)}
        env["HOSTED_SETTLEMENT_ENV_FILE"] = str(authority_env_path)
        env["VMS_BOB_STRIPE_STOREFRONT_CONFIG"] = str(marketplace_config_path)
        if storefront_servicing_interval_seconds is not None:
            if storefront_servicing_interval_seconds <= 0:
                raise ProcessUnavailable("storefront servicing interval must be positive")
            env["HOSTED_STOREFRONT_SERVICING_INTERVAL_SECONDS"] = (
                f"{storefront_servicing_interval_seconds:g}"
            )
        self._runtime_env = env
        # Only meaningful when the named volume is kept: a teardown that spares
        # it also spares the anonymous volumes the services bring with them, so
        # the run notes which ones predate it and removes only what it added.
        self._preexisting_volumes = (
            self._volumes() if self._retain_authority_state else frozenset()
        )
        self._run((*self._base, "up", "-d", "--wait"), env=env, check=True)
        self._started = True

    def bind_existing_account(
        self,
        *,
        account_ref: str,
        binding_contract: str,
    ) -> None:
        if self._runtime_env is None:
            raise ProcessUnavailable("ordinary hosted account admission is unavailable")
        self._run(
            (
                *self._base,
                "exec",
                "-T",
                "hosted-settlement-api",
                "/opt/venv/bin/hosted-settlement-admin",
                "bind-existing-account",
                "--account-ref",
                account_ref,
                "--binding-file",
                "-",
                "--actor",
                "protected-stripe-test",
                "--reason-code",
                "maintained-test-account",
            ),
            env=self._runtime_env,
            check=True,
            input_text=binding_contract,
        )

    def restart(self, role: str) -> None:
        service = {
            "api": "hosted-settlement-api",
            "worker": "hosted-settlement-worker",
        }.get(role)
        if service is None or self._runtime_env is None:
            raise ProcessUnavailable("ordinary hosted restart role is unavailable")
        self._run((*self._base, "restart", service), env=self._runtime_env, check=True)

    def stop(self) -> None:
        env = self._runtime_env or {
            key: value for key, value in os.environ.items() if not _SENSITIVE_ENV.search(key)
        }
        # The authority's state belongs to one run. Leaving the named volume
        # behind makes the next run start against a database that already
        # remembers this one -- locally, where runs share a machine, that is
        # every second run; on a runner it is every retry after an interruption.
        #
        # A development run may ask to keep it, and only the authority's: the
        # topology declares exactly one named volume, and every other service
        # keeps its state inside the container. What survives is therefore the
        # payer fixture -- the profile, its instrument, and the account owner
        # binding -- and nothing about the marketplace side of the run. That
        # buys back the one thing a saved-instrument lane cannot automate: the
        # hosted setup page, which is completed once and then reused.
        teardown = (*self._base, "down", "--remove-orphans")
        self._run(
            teardown if self._retain_authority_state else (*teardown, "--volumes"),
            env=env,
            check=False,
        )
        if self._retain_authority_state:
            self._drop_added_anonymous_volumes(env)
        self._started = False
        self._runtime_env = None

    def _volumes(self) -> frozenset[str]:
        try:
            completed = subprocess.run(
                (self._base[0], "volume", "ls", "-q"),
                cwd=self._cwd,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
                timeout=60,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            return frozenset()
        if completed.returncode != 0:
            return frozenset()
        return frozenset(line.strip() for line in completed.stdout.splitlines() if line.strip())

    def _drop_added_anonymous_volumes(self, env: Mapping[str, str]) -> None:
        """Remove the unnamed volumes this run added, and only those.

        A name of the project's own choosing is the cache and must survive. An
        anonymous one is a service's scratch space, and leaving it behind on
        every retained run leaks a volume per run. Volumes present before the
        stack came up are somebody else's and are never touched.
        """

        added = self._volumes() - self._preexisting_volumes
        for name in sorted(added):
            if not _ANONYMOUS_VOLUME.fullmatch(name):
                continue
            self._run((self._base[0], "volume", "rm", name), env=env, check=False)

    def _run(
        self,
        argv: Sequence[str],
        *,
        env: Mapping[str, str],
        check: bool,
        input_text: str | None = None,
    ) -> None:
        try:
            completed = subprocess.run(
                argv,
                cwd=self._cwd,
                env=env,
                stdin=None if input_text is not None else subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                timeout=900,
                check=False,
                input=input_text,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise ProcessUnavailable("ordinary hosted Compose operation was unavailable") from exc
        if check and completed.returncode != 0:
            raise ProcessUnavailable(
                self._with_diagnostics(
                    f"ordinary hosted Compose operation failed: {argv[-1]}",
                    completed.stdout or "",
                )
            )

    def _with_diagnostics(self, summary: str, output: str) -> str:
        if not self._retain_diagnostics or not output.strip():
            return summary
        tail = "\n".join(output.splitlines()[-_DIAGNOSTIC_LINES:])
        return f"{summary}\n--- Compose output (development run only) ---\n{tail}"

    def __enter__(self) -> "ComposeStack":
        return self

    def __exit__(self, *_exc: object) -> None:
        self.stop()


class MarketplaceLifecycleSession:
    """In-memory JSON-lines bridge to the marketplace-owned staged scenario."""

    def __init__(
        self,
        command: Sequence[str],
        *,
        cwd: Path,
        environment: Mapping[str, str] | None = None,
        request_timeout: float = 120.0,
        retain_diagnostics: bool = False,
    ) -> None:
        if not command or any(not isinstance(item, str) or not item for item in command):
            raise LifecycleContractError("lifecycle command must be a non-empty argv array")
        if request_timeout <= 0:
            raise LifecycleContractError("lifecycle request timeout must be positive")
        additions = dict(environment or {})
        if any(_SENSITIVE_ENV.search(key) for key in additions):
            raise LifecycleContractError(
                "lifecycle environment cannot receive provider credentials"
            )
        self._command = tuple(command)
        self._cwd = cwd
        self._environment = additions
        self._request_timeout = request_timeout
        # Staged output can contain ephemeral buyer actions and provider
        # identifiers, so a protected run discards it unread. A development run
        # is the one place the operator is already holding those credentials,
        # and discarding it there is what makes a failed stage undiagnosable.
        self._retain_diagnostics = retain_diagnostics
        self._diagnostics: deque[str] = deque(maxlen=_DIAGNOSTIC_LINES)
        self._process: subprocess.Popen[str] | None = None
        self._stderr_reader: threading.Thread | None = None
        self._stdout_reader: threading.Thread | None = None
        self._responses: queue.Queue[str | None] = queue.Queue()

    def start(self) -> None:
        env = {
            key: value
            for key, value in os.environ.items()
            if not _SENSITIVE_ENV.search(key) and not _PROXY_ENV.match(key)
        }
        env.update(self._environment)
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
        self._stdout_reader = threading.Thread(target=self._read_stdout, daemon=True)
        self._stderr_reader.start()
        self._stdout_reader.start()

    def request(self, action: str, **fields: object) -> dict[str, Any]:
        process = self._process
        if process is None or process.stdin is None or process.stdout is None:
            raise LifecycleContractError("marketplace lifecycle bridge is not running")
        request = {"action": action, **fields}
        process.stdin.write(json.dumps(request, separators=(",", ":")) + "\n")
        process.stdin.flush()
        try:
            line = self._responses.get(timeout=self._request_timeout)
        except queue.Empty as exc:
            raise LifecycleConvergenceTimeout(
                self._with_diagnostics(
                    "marketplace lifecycle stage did not converge within its bound"
                )
            ) from exc
        if line is None:
            raise ProcessUnavailable(
                self._with_diagnostics("marketplace lifecycle bridge exited unexpectedly")
            )
        try:
            response = json.loads(line)
        except json.JSONDecodeError as exc:
            raise LifecycleContractError(
                "marketplace lifecycle bridge returned invalid JSON"
            ) from exc
        if not isinstance(response, dict):
            raise LifecycleContractError("marketplace lifecycle bridge returned a non-object")
        if response.get("ok") is not True:
            code = response.get("code")
            if code == "marketplace_unavailable":
                raise ProcessUnavailable(
                    self._with_diagnostics("marketplace lifecycle state was unavailable")
                )
            if code == "convergence_timeout":
                raise LifecycleConvergenceTimeout(
                    "marketplace lifecycle stage did not converge within its bound"
                )
            raise LifecycleContractError(
                self._with_diagnostics(
                    f"marketplace lifecycle bridge rejected a stage: {code or 'no code'}"
                )
            )
        return response

    def _read_stdout(self) -> None:
        process = self._process
        assert process is not None and process.stdout is not None
        for line in process.stdout:
            self._responses.put(line)
        self._responses.put(None)

    def _discard_stderr(self) -> None:
        process = self._process
        assert process is not None and process.stderr is not None
        for line in process.stderr:
            # Nothing read here belongs in workflow logs or evidence. A
            # development run keeps a bounded tail in memory for the operator
            # who is running it; a protected run does not read it at all.
            if self._retain_diagnostics:
                self._diagnostics.append(line.rstrip("\n")[:_DIAGNOSTIC_LINE_LIMIT])

    def diagnostics(self) -> str:
        """The retained tail, empty when the run is not allowed to keep one."""

        return "\n".join(self._diagnostics)

    def _with_diagnostics(self, summary: str) -> str:
        # stdout reaching EOF says the bridge is gone; it does not say the
        # stderr reader has caught up. Without this the tail is empty exactly
        # when it matters most -- the run where the bridge died on startup.
        reader = self._stderr_reader
        if reader is not None and self._retain_diagnostics:
            reader.join(timeout=_DIAGNOSTIC_DRAIN_SECONDS)
        tail = self.diagnostics()
        if not tail:
            return summary
        return f"{summary}\n--- staged output (development run only) ---\n{tail}"

    def stop(self) -> None:
        process = self._process
        if process is None:
            return
        if process.stdin is not None:
            try:
                process.stdin.write('{"action":"shutdown"}\n')
                process.stdin.flush()
                process.stdin.close()
            except (BrokenPipeError, OSError):
                pass
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


def _replace_toml_setting(text: str, key: str, value: str) -> str:
    pattern = re.compile(rf"^{re.escape(key)} = \"[^\n]*\"$", re.MULTILINE)
    replaced, count = pattern.subn(f'{key} = "{value}"', text, count=1)
    if count != 1:
        raise ProcessUnavailable(f"marketplace configuration is missing {key}")
    return replaced


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


def _read_environment_file(path: Path) -> dict[str, str]:
    try:
        text = path.read_text(encoding="utf-8")
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


def _valid_env_name(value: str) -> bool:
    return bool(re.fullmatch(r"[A-Z_][A-Z0-9_]*", value))
