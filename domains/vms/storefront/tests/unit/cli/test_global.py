from __future__ import annotations

from pathlib import Path


def test_version_installed(monkeypatch, runner, app):
    import market_storefront.cli as cli_mod

    monkeypatch.setattr(cli_mod, "version", lambda _name: "1.2.3")

    result = runner.invoke(app, ["--version"])

    assert result.exit_code == 0
    assert "1.2.3" in result.output


def test_version_not_installed(monkeypatch, runner, app):
    from importlib.metadata import PackageNotFoundError
    import market_storefront.cli as cli_mod

    monkeypatch.setattr(
        cli_mod,
        "version",
        lambda _name: (_ for _ in ()).throw(PackageNotFoundError()),
    )

    result = runner.invoke(app, ["--version"])

    assert result.exit_code == 0
    assert "unknown" in result.output


def test_config_flag_calls_set_user_config_path(monkeypatch, tmp_path, runner, app):
    import market_storefront.server as server_mod

    received: list[Path] = []
    monkeypatch.setattr(
        "market_config.config_loader.set_user_config_path",
        lambda p: received.append(p),
    )
    monkeypatch.setattr(server_mod, "run_serve", lambda **_kwargs: None)

    cfg = tmp_path / "custom.toml"
    cfg.write_text("")

    result = runner.invoke(app, ["--config", str(cfg), "serve"])

    assert result.exit_code == 0
    assert received == [cfg]
