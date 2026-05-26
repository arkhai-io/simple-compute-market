"""Buyer-CLI subprocess fixture for two-machine e2e tests.

The buyer has no long-running node: in production they invoke `market`
on their own machine to negotiate, escrow, settle, and poll. Tests
that want to verify cross-machine behavior should drive that same
binary as a subprocess, not call ``SyncStorefrontClient`` directly.

This fixture spawns the buyer's installed ``market`` CLI against a
hermetic XDG state/config dir, exposes helpers to wait on run-log
events emitted by the CLI, and parses the JSONL for assertions.

Resolution order for the binary path:
  1. ``MARKET_CLI_BIN`` env var (absolute path)
  2. ``shutil.which("market")`` (any PATH entry)
  3. ``<repo_root>/buyer/.venv/bin/market`` (developer default)

If none of those exist the fixture skips, with instructions.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import time
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable, Optional

import pytest

from src.settings import settings

log = logging.getLogger(__name__)

# buyer_cli.py lives at integration-tests/tests/e2e/roles/buyer_cli.py
# Four parents = simple-compute-market (the repo root).
_REPO_ROOT = Path(__file__).resolve().parents[4]


def _resolve_market_binary() -> Optional[Path]:
    """Locate the ``market`` console script. None if not found."""
    env_override = os.environ.get("MARKET_CLI_BIN")
    if env_override:
        p = Path(env_override).expanduser()
        if p.is_file():
            return p
    on_path = shutil.which("market")
    if on_path:
        return Path(on_path)
    sibling = _REPO_ROOT / "buyer" / ".venv" / "bin" / "market"
    if sibling.is_file():
        return sibling
    return None


@dataclass
class MarketRun:
    """One invocation of ``market <subcommand>``.

    Carries the resolved run-id (looked up by listing the JSONL dir
    or extracted from a ``--from`` flag on the args) and the
    subprocess handle. Helpers tail the run-log so the test can
    coordinate with the CLI between event milestones.
    """

    run_dir: Path
    popen: Optional[subprocess.Popen] = None
    completed: Optional[subprocess.CompletedProcess] = None
    _run_id: Optional[str] = None
    pre_existing_run_ids: frozenset[str] = field(default_factory=frozenset)

    @property
    def run_id(self) -> str:
        if self._run_id is None:
            self._run_id = self._discover_run_id()
        return self._run_id

    def _discover_run_id(self) -> str:
        deadline = time.monotonic() + 10.0
        while time.monotonic() < deadline:
            if self.run_dir.exists():
                current = {p.stem for p in self.run_dir.glob("*.jsonl")}
                new = current - self.pre_existing_run_ids
                if len(new) == 1:
                    return next(iter(new))
                if len(new) > 1:
                    newest = max(
                        self.run_dir.glob("*.jsonl"),
                        key=lambda p: p.stat().st_mtime,
                    )
                    return newest.stem
            time.sleep(0.1)
        raise AssertionError(
            f"market did not produce a run-log in {self.run_dir} within 10s "
            f"(pre-existing run-ids: {self.pre_existing_run_ids})"
        )

    @property
    def log_path(self) -> Path:
        return self.run_dir / f"{self.run_id}.jsonl"

    def read_events(self) -> list[dict[str, Any]]:
        path = self.log_path
        if not path.exists():
            return []
        out: list[dict[str, Any]] = []
        with path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    out.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
        return out

    def wait_for_event(
        self,
        event_name: str,
        *,
        predicate: Optional[Callable[[dict[str, Any]], bool]] = None,
        timeout: float = 30.0,
    ) -> dict[str, Any]:
        """Tail the run-log JSONL until a matching event appears.

        Polls every 200ms. Raises ``AssertionError`` on timeout with the
        last few events for diagnosis.
        """
        deadline = time.monotonic() + timeout
        last_seen: list[str] = []
        while time.monotonic() < deadline:
            events = self.read_events()
            last_seen = [e.get("event", "?") for e in events[-6:]]
            for ev in events:
                if ev.get("event") != event_name:
                    continue
                if predicate is None or predicate(ev):
                    return ev
            if self.popen is not None and self.popen.poll() is not None:
                if self.popen.returncode != 0:
                    stdout, stderr = self._drain_streams()
                    raise AssertionError(
                        f"market subprocess exited rc={self.popen.returncode} "
                        f"before emitting {event_name!r}. last events={last_seen}\n"
                        f"stdout (tail): {stdout[-1500:]}\n"
                        f"stderr (tail): {stderr[-1500:]}"
                    )
            time.sleep(0.2)
        raise AssertionError(
            f"Did not see event {event_name!r} in run {self.run_id} within {timeout}s. "
            f"last events={last_seen}"
        )

    def _drain_streams(self) -> tuple[str, str]:
        if self.popen is None:
            return "", ""
        try:
            out, err = self.popen.communicate(timeout=2)
            return out or "", err or ""
        except subprocess.TimeoutExpired:
            return "", ""

    def wait(self, timeout: float = 60.0) -> int:
        if self.completed is not None:
            return self.completed.returncode
        assert self.popen is not None
        try:
            return self.popen.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            self.popen.kill()
            raise

    def terminate(self) -> None:
        if self.popen is not None and self.popen.poll() is None:
            self.popen.terminate()
            try:
                self.popen.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.popen.kill()

    @property
    def returncode(self) -> Optional[int]:
        if self.completed is not None:
            return self.completed.returncode
        if self.popen is not None:
            return self.popen.returncode
        return None

    def stdout(self) -> str:
        if self.completed is not None:
            return self.completed.stdout or ""
        if self.popen is not None and self.popen.returncode is not None:
            out, _ = self._drain_streams()
            return out
        return ""

    def stderr(self) -> str:
        if self.completed is not None:
            return self.completed.stderr or ""
        if self.popen is not None and self.popen.returncode is not None:
            _, err = self._drain_streams()
            return err
        return ""


class BuyerCli:
    """Helper for invoking ``market`` against a hermetic XDG environment.

    Each call to ``run`` returns a :class:`MarketRun`. Same instance can
    be reused across multiple invocations in one test (e.g. ``negotiate``
    then ``settle --from <run_id>``); both write to the same run-log dir.
    """

    def __init__(self, *, binary: Path, config_path: Path, state_dir: Path, home_dir: Path):
        self.binary = binary
        self.config_path = config_path
        self.state_dir = state_dir
        self.home_dir = home_dir

    @property
    def run_dir(self) -> Path:
        return self.state_dir / "arkhai" / "buy-runs"

    def _resolve_run_id_from_args(self, args: Iterable[str]) -> Optional[str]:
        args_list = list(args)
        for i, a in enumerate(args_list):
            if a in ("--from", "--run", "-r") and i + 1 < len(args_list):
                return args_list[i + 1]
        return None

    def run(
        self,
        args: Iterable[str],
        *,
        background: bool = False,
        timeout: float = 180.0,
    ) -> MarketRun:
        """Spawn ``market <args>``.

        Foreground (``background=False``): block until exit; the returned
        :class:`MarketRun` has ``completed`` set and ``returncode``
        populated. Useful for ``market negotiate`` which terminates on
        agreement.

        Background (``background=True``): return immediately with
        ``popen`` set. Useful for ``market settle`` which blocks polling
        and needs the test to inject side-effects between event
        milestones.
        """
        args_list = list(args)
        resolved_run_id = self._resolve_run_id_from_args(args_list)
        pre = frozenset(
            p.stem for p in self.run_dir.glob("*.jsonl")
        ) if self.run_dir.exists() else frozenset()

        env = dict(os.environ)
        env["XDG_STATE_HOME"] = str(self.state_dir)
        env["XDG_CONFIG_HOME"] = str(self.config_path.parent.parent)
        env["HOME"] = str(self.home_dir)

        cmd = [str(self.binary), "--config", str(self.config_path), *args_list]
        log.info("[buyer_cli] %s", " ".join(cmd))

        if background:
            popen = subprocess.Popen(
                cmd,
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            return MarketRun(
                run_dir=self.run_dir,
                popen=popen,
                pre_existing_run_ids=pre,
                _run_id=resolved_run_id,
            )

        completed = subprocess.run(
            cmd,
            env=env,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return MarketRun(
            run_dir=self.run_dir,
            completed=completed,
            pre_existing_run_ids=pre,
            _run_id=resolved_run_id,
        )


def _alkahest_addresses_path() -> Optional[str]:
    """Locate the alkahest_anvil_addresses.json shipped with market-storefront.

    Same import path the storefront uses internally; it's installed
    transitively into the integration-tests venv via the market-storefront
    dep so this resolves without runtime config.
    """
    try:
        from importlib import resources
        ref = resources.files("market_storefront.data").joinpath(
            "alkahest_anvil_addresses.json"
        )
        return str(ref)
    except Exception:
        return None


@pytest.fixture(scope="session")
def buyer_cli_binary() -> Path:
    """Locate the ``market`` console script or skip with instructions."""
    p = _resolve_market_binary()
    if p is None:
        pytest.skip(
            "`market` binary not found. Install the buyer wheel "
            "(`cd buyer && uv sync`) so $REPO/buyer/.venv/bin/market exists, "
            "or set MARKET_CLI_BIN=/path/to/market."
        )
    try:
        result = subprocess.run(
            [str(p), "--version"],
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        pytest.skip(f"market binary at {p} is not executable: {exc}")
    if result.returncode != 0:
        pytest.skip(
            f"`{p} --version` exited {result.returncode}: "
            f"{(result.stderr or result.stdout)[:300]}"
        )
    log.info("[buyer_cli] using market binary at %s", p)
    return p


@pytest.fixture(scope="module")
def buyer_cli(buyer_cli_binary: Path, tmp_path_factory) -> BuyerCli:
    """A ``BuyerCli`` wired to a hermetic XDG state/config dir for the module.

    Writes a buyer ``config.toml`` populated from the integration-test
    settings (BUYER.PRIVATE_KEY/WALLET_ADDRESS/SSH_PUBLIC_KEY,
    chain RPC/name/alkahest addresses, registry URL). All buyer-side
    subcommand invocations resolve config from this file.
    """
    base = tmp_path_factory.mktemp("buyer_cli")
    home_dir = base / "home"
    state_dir = base / "state"
    config_root = base / "config"
    config_dir = config_root / "arkhai"
    for d in (home_dir, state_dir, config_dir):
        d.mkdir(parents=True, exist_ok=True)

    private_key = str(settings.BUYER.PRIVATE_KEY or "")
    wallet_address = str(settings.BUYER.WALLET_ADDRESS or "")
    if not private_key or not wallet_address:
        pytest.skip("BUYER.PRIVATE_KEY / BUYER.WALLET_ADDRESS not configured")

    ssh_public_key = str(
        getattr(settings.BUYER, "SSH_PUBLIC_KEY", None)
        or "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAITestKeyForE2E test@e2e"
    )
    rpc_url = (
        str(settings.BUYER.CHAIN_RPC_URL or "").strip()
        or str(settings.RPC.URL or "").strip()
        or "ws://localhost:8545"
    )
    if rpc_url.startswith("http://"):
        rpc_url = "ws://" + rpc_url[len("http://"):]
    elif rpc_url.startswith("https://"):
        rpc_url = "wss://" + rpc_url[len("https://"):]

    registry_url = str(settings.REGISTRY.API_URL or "http://localhost:8080")

    alkahest_path = _alkahest_addresses_path()
    if not alkahest_path:
        pytest.skip(
            "Could not locate alkahest_anvil_addresses.json via "
            "market_storefront.data — is market-storefront installed?"
        )

    def _toml_quote(s: str) -> str:
        return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'

    config_path = config_dir / "buyer.toml"
    config_path.write_text(
        "\n".join([
            "# Hermetic buyer config — generated by buyer_cli fixture.",
            "[wallet]",
            f"address        = {_toml_quote(wallet_address)}",
            f"private_key    = {_toml_quote(private_key)}",
            f"ssh_public_key = {_toml_quote(ssh_public_key)}",
            "",
            "[chain]",
            'name                         = "anvil"',
            f"rpc_url                      = {_toml_quote(rpc_url)}",
            f"alkahest_address_config_path = {_toml_quote(alkahest_path)}",
            "",
            "[registry]",
            f"urls = [{_toml_quote(registry_url)}]",
            "",
            "[negotiation]",
            "# The buyer wheel installs without torch by default — the RL",
            "# strategy self-register would fail at module import. Force",
            "# bisection so the negotiation engine matches the seller's",
            "# [seller.negotiation] policy_mode=bisection in config.bob.toml.",
            'policy_mode = "bisection"',
            "",
        ]),
        encoding="utf-8",
    )

    with config_path.open("rb") as f:
        tomllib.load(f)

    log.info(
        "[buyer_cli] hermetic env: state=%s config=%s rpc=%s registry=%s",
        state_dir, config_path, rpc_url, registry_url,
    )

    cli = BuyerCli(
        binary=buyer_cli_binary,
        config_path=config_path,
        state_dir=state_dir,
        home_dir=home_dir,
    )
    yield cli
