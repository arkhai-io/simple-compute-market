"""The buyer finds the repository checkout it runs from, at any install depth."""

from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from arkhai_vms_buyer import common, network_cli


def _checkout(root: Path) -> Path:
    (root / "domains" / "vms" / "storefront").mkdir(parents=True)
    (root / ".python-version").write_text("3.13\n", "utf-8")
    return root


def test_the_root_is_found_from_a_module_nested_at_any_depth(tmp_path):
    root = _checkout(tmp_path / "repo")
    nested = root / "domains" / "vms" / "buyer" / "src" / "arkhai_vms_buyer"
    nested.mkdir(parents=True)

    assert common.repository_root(nested) == root


def test_an_unrelated_python_pin_is_not_taken_for_the_root(tmp_path):
    (tmp_path / ".python-version").write_text("3.12\n", "utf-8")
    elsewhere = tmp_path / "projects" / "other"
    elsewhere.mkdir(parents=True)

    assert common.repository_root(elsewhere) is None


def test_the_working_directory_is_searched_when_the_module_is_installed_elsewhere(tmp_path):
    root = _checkout(tmp_path / "repo")
    site_packages = tmp_path / "venv" / "lib" / "site-packages" / "arkhai_vms_buyer"
    site_packages.mkdir(parents=True)

    assert common.repository_root(site_packages, root / "domains") == root


def test_this_checkout_is_found_and_holds_the_zerotier_scripts():
    root = common.repository_root()

    assert root is not None
    assert (root / "scripts" / "zerotier").is_dir()


def test_network_join_runs_the_checkouts_zerotier_scripts(monkeypatch):
    calls = []
    monkeypatch.setattr(network_cli, "run_step", lambda label, cmd, cwd: calls.append((cmd, cwd)))

    result = CliRunner().invoke(network_cli.network_app, ["join", "abcdef0123456789"])

    assert result.exit_code == 0, result.output
    [(cmd, cwd)] = calls
    assert cmd == ["make", "join", "NETWORK_ID=abcdef0123456789"]
    assert cwd == common.repository_root() / "scripts" / "zerotier" and cwd.is_dir()


def test_network_commands_refuse_to_run_outside_a_checkout(monkeypatch):
    monkeypatch.setattr(network_cli, "repository_root", lambda: None)

    result = CliRunner().invoke(network_cli.network_app, ["get-peers"])

    assert result.exit_code == 2
    assert "run them from a checkout of the repository" in result.output
