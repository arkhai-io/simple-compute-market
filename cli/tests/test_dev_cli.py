from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from market.cli import app
from market.groups import dev as dev_module


def test_dev_deploy_contracts_uses_canonical_wrapper(
    monkeypatch,
) -> None:
    observed: dict[str, object] = {}

    def fake_run_step(
        label: str,
        cmd: list[str],
        cwd: Path,
        extra_env: dict[str, str] | None = None,
    ) -> None:
        observed["label"] = label
        observed["cmd"] = cmd
        observed["cwd"] = cwd
        observed["extra_env"] = extra_env

    monkeypatch.setattr(dev_module, "run_step", fake_run_step)
    monkeypatch.setattr(dev_module.sys, "executable", "/tmp/core-venv-python")

    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "dev",
            "deploy-contracts",
            "--rpc-url",
            "http://127.0.0.1:45165",
        ],
    )

    assert result.exit_code == 0, result.output
    assert observed == {
        "label": "Deploy local ERC-8004 contracts to http://127.0.0.1:45165",
        "cmd": [
            "/tmp/core-venv-python",
            "scripts/deploy_local_contracts.py",
            "--rpc-url",
            "http://127.0.0.1:45165",
        ],
        "cwd": Path("/home/levi/Dropbox/Documents/Work/CoopHive/github/simple-market-service"),
        "extra_env": None,
    }


def test_dev_deploy_registry_alias_routes_to_same_canonical_wrapper(
    monkeypatch,
) -> None:
    observed: list[list[str]] = []

    def fake_run_step(
        label: str,
        cmd: list[str],
        cwd: Path,
        extra_env: dict[str, str] | None = None,
    ) -> None:
        observed.append(cmd)

    monkeypatch.setattr(dev_module, "run_step", fake_run_step)
    monkeypatch.setattr(dev_module.sys, "executable", "/tmp/core-venv-python")

    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "dev",
            "deploy-registry",
            "--rpc-url",
            "http://127.0.0.1:45165",
        ],
    )

    assert result.exit_code == 0, result.output
    assert observed == [
        [
            "/tmp/core-venv-python",
            "scripts/deploy_local_contracts.py",
            "--rpc-url",
            "http://127.0.0.1:45165",
        ]
    ]
