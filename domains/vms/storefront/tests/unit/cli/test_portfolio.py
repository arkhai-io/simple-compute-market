from __future__ import annotations

import subprocess


def test_portfolio_import_csv_not_found(runner, app):
    result = runner.invoke(app, ["portfolio", "import-csv", "/nonexistent/resources.csv"])

    assert result.exit_code != 0


def test_portfolio_import_script_not_found(monkeypatch, tmp_path, runner, app):
    import market_storefront.cli_portfolio as portfolio_mod

    fake_root = tmp_path / "fake_storefront"
    fake_root.mkdir()
    monkeypatch.setattr(portfolio_mod, "STOREFRONT_ROOT", fake_root)
    csv = tmp_path / "resources.csv"
    csv.write_text("resource_id\n")

    result = runner.invoke(app, ["portfolio", "import-csv", str(csv)])

    assert result.exit_code != 0
    assert "Import script not found" in result.output


def test_portfolio_import_happy_path(monkeypatch, tmp_path, runner, app):
    import market_storefront.cli_portfolio as portfolio_mod

    csv = tmp_path / "resources.csv"
    csv.write_text("resource_id\n")
    fake_root = tmp_path / "storefront"
    scripts = fake_root / "scripts"
    scripts.mkdir(parents=True)
    (scripts / "import_resources_csv.py").write_text("")
    monkeypatch.setattr(portfolio_mod, "STOREFRONT_ROOT", fake_root)

    calls: list[dict] = []
    monkeypatch.setattr(subprocess, "run", lambda cmd, **kwargs: calls.append({"cmd": cmd, "kwargs": kwargs}))

    result = runner.invoke(app, ["portfolio", "import-csv", str(csv), "--db-path", "/tmp/agent.db", "--dry-run"])

    assert result.exit_code == 0
    assert len(calls) == 1
    assert str(csv.resolve()) in calls[0]["cmd"]
    assert ["--db-path", "/tmp/agent.db"] == calls[0]["cmd"][-3:-1]
    assert calls[0]["cmd"][-1] == "--dry-run"
    assert calls[0]["kwargs"]["cwd"] == str(fake_root)
