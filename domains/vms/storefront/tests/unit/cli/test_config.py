from __future__ import annotations

import json


def test_config_path_file_exists(monkeypatch, tmp_path, runner, app):
    import market_storefront.groups.config as config_group

    cfg = tmp_path / "storefront.toml"
    cfg.write_text("")
    monkeypatch.setattr(config_group, "storefront_config_file", lambda: cfg)

    result = runner.invoke(app, ["config", "path"])

    assert result.exit_code == 0
    assert str(cfg) in result.output
    assert "not present" not in result.output


def test_config_path_file_missing(monkeypatch, tmp_path, runner, app):
    import market_storefront.groups.config as config_group

    cfg = tmp_path / "storefront.toml"
    monkeypatch.setattr(config_group, "storefront_config_file", lambda: cfg)

    result = runner.invoke(app, ["config", "path"])

    assert result.exit_code == 0
    assert str(cfg) in result.output
    assert "not present" in result.output or "init-user" in result.output


def test_config_show_file_missing(monkeypatch, tmp_path, runner, app):
    import market_storefront.groups.config as config_group

    cfg = tmp_path / "storefront.toml"
    monkeypatch.setattr(config_group, "storefront_config_file", lambda: cfg)

    result = runner.invoke(app, ["config", "show"])

    assert result.exit_code == 1
    assert "No storefront config" in result.output


def test_config_show_raw(monkeypatch, tmp_path, runner, app):
    import market_storefront.groups.config as config_group

    cfg = tmp_path / "storefront.toml"
    cfg.write_text("port = 8001\n")
    monkeypatch.setattr(config_group, "storefront_config_file", lambda: cfg)

    result = runner.invoke(app, ["config", "show", "--raw"])

    assert result.exit_code == 0
    assert "port = 8001" in result.output


def test_config_show_json(monkeypatch, tmp_path, runner, app):
    import market_storefront.groups.config as config_group

    cfg = tmp_path / "storefront.toml"
    cfg.write_text("port = 8001\n")
    monkeypatch.setattr(config_group, "storefront_config_file", lambda: cfg)
    monkeypatch.setattr(config_group, "load_storefront_config", lambda: {"port": 8001})

    result = runner.invoke(app, ["config", "show"])

    assert result.exit_code == 0
    assert json.loads(result.output)["port"] == 8001


def test_config_get_key_found_scalar(monkeypatch, runner, app):
    import market_storefront.groups.config as config_group

    monkeypatch.setattr(config_group, "load_storefront_config", lambda: {"port": 8001})
    monkeypatch.setattr(config_group, "get_dotted", lambda doc, key: doc.get(key))

    result = runner.invoke(app, ["config", "get", "port"])

    assert result.exit_code == 0
    assert "8001" in result.output


def test_config_get_key_found_dict(monkeypatch, runner, app):
    import market_storefront.groups.config as config_group

    monkeypatch.setattr(config_group, "load_storefront_config", lambda: {"wallet": {"address": "0xabc"}})
    monkeypatch.setattr(config_group, "get_dotted", lambda doc, key: doc.get(key))

    result = runner.invoke(app, ["config", "get", "wallet"])

    assert result.exit_code == 0
    assert json.loads(result.output)["address"] == "0xabc"


def test_config_get_key_missing(monkeypatch, tmp_path, runner, app):
    import market_storefront.groups.config as config_group

    cfg = tmp_path / "storefront.toml"
    monkeypatch.setattr(config_group, "storefront_config_file", lambda: cfg)
    monkeypatch.setattr(config_group, "load_storefront_config", lambda: {})
    monkeypatch.setattr(config_group, "get_dotted", lambda _doc, _key: None)

    result = runner.invoke(app, ["config", "get", "missing"])

    assert result.exit_code == 1
    assert "missing" in result.output


def test_config_set_coerces_values_and_writes(monkeypatch, tmp_path, runner, app):
    import market_storefront.groups.config as config_group

    cfg = tmp_path / "storefront.toml"
    doc: dict = {}
    calls: list[tuple[str, object]] = []
    monkeypatch.setattr(config_group, "storefront_config_file", lambda: cfg)
    monkeypatch.setattr(config_group, "load_user_config", lambda path: doc)

    def fake_set_dotted(target, key, value):
        calls.append((key, value))
        target[key] = value

    monkeypatch.setattr(config_group, "set_dotted", fake_set_dotted)
    monkeypatch.setattr(config_group, "write_user_config", lambda written, path: path)

    cases = [
        ("enabled", "true", True),
        ("port", "8001", 8001),
        ("ratio", "1.5", 1.5),
        ("agent_name", "alice", "alice"),
    ]
    for key, raw, expected in cases:
        result = runner.invoke(app, ["config", "set", key, raw])
        assert result.exit_code == 0
        assert calls[-1] == (key, expected)


def test_config_set_real_dotted_nested_key(monkeypatch, tmp_path, runner, app):
    import market_storefront.groups.config as config_group

    cfg = tmp_path / "storefront.toml"
    doc: dict = {}
    monkeypatch.setattr(config_group, "storefront_config_file", lambda: cfg)
    monkeypatch.setattr(config_group, "load_user_config", lambda path: doc)
    monkeypatch.setattr(config_group, "write_user_config", lambda written, path: path)

    result = runner.invoke(app, ["config", "set", "pricing.default_min_price", "42"])

    assert result.exit_code == 0
    assert doc == {"pricing": {"default_min_price": 42}}


def test_config_init_user_exists_no_overwrite(monkeypatch, tmp_path, runner, app):
    import market_storefront.groups.config as config_group

    cfg = tmp_path / "storefront.toml"
    cfg.write_text("existing")
    monkeypatch.setattr(config_group, "storefront_config_file", lambda: cfg)
    monkeypatch.setattr(config_group, "user_config_dir", lambda: tmp_path)

    result = runner.invoke(app, ["config", "init-user"])

    assert result.exit_code == 1
    assert cfg.read_text() == "existing"


def test_config_init_user_exists_with_overwrite(monkeypatch, tmp_path, runner, app):
    import market_storefront.groups.config as config_group

    cfg = tmp_path / "storefront.toml"
    cfg.write_text("existing")
    monkeypatch.setattr(config_group, "storefront_config_file", lambda: cfg)
    monkeypatch.setattr(config_group, "user_config_dir", lambda: tmp_path)

    result = runner.invoke(app, ["config", "init-user", "--overwrite"])

    assert result.exit_code == 0
    assert "arkhai storefront config" in cfg.read_text()


def test_config_init_user_new_file(monkeypatch, tmp_path, runner, app):
    import market_storefront.groups.config as config_group

    cfg = tmp_path / "nested" / "storefront.toml"
    monkeypatch.setattr(config_group, "storefront_config_file", lambda: cfg)
    monkeypatch.setattr(config_group, "user_config_dir", lambda: cfg.parent)

    result = runner.invoke(app, ["config", "init-user"])

    assert result.exit_code == 0
    assert cfg.exists()
    assert "arkhai storefront config" in cfg.read_text()
