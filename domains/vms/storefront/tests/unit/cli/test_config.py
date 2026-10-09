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


_LAYER_NAMES = {
    "storefront_toml": "storefront.toml",
    "storefront_json": "storefront.json",
    "storefront_secrets_toml": "storefront.secrets.toml",
}


def _layers(tmp_path, **files: str):
    directory = tmp_path / "arkhai"
    directory.mkdir(parents=True, exist_ok=True)
    for name, text in files.items():
        (directory / _LAYER_NAMES[name]).write_text(text)
    return directory


def test_config_show_reports_no_layer(monkeypatch, tmp_path, runner, app):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))

    result = runner.invoke(app, ["config", "show"])

    assert result.exit_code == 1
    assert "No storefront config" in result.output


def test_config_show_merges_rendered_layers_without_a_toml(
    monkeypatch, tmp_path, runner, app
):
    """A chart-deployed pod has the rendered JSON and the overlay, and no TOML."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    _layers(
        tmp_path,
        storefront_json='{"port": 8001, "Chains": {"anvil": {"chain_id": 31337}}}',
        storefront_secrets_toml='[chains.anvil]\nrpc_url = "http://anvil:8545"\n',
    )

    result = runner.invoke(app, ["config", "show"])

    assert result.exit_code == 0
    assert json.loads(result.output) == {
        "chains": {"anvil": {"chain_id": 31337, "rpc_url": "http://anvil:8545"}},
        "port": 8001,
    }


def test_config_show_raw_prints_public_layers_and_never_the_overlay(
    monkeypatch, tmp_path, runner, app
):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    directory = _layers(
        tmp_path,
        storefront_toml="port = 8000\n",
        storefront_json='{"port": 8001}',
        storefront_secrets_toml='[wallet]\nprivate_key = "0xsecret"\n',
    )

    result = runner.invoke(app, ["config", "show", "--raw"])

    assert result.exit_code == 0
    toml_at = result.output.index(f"# {directory / 'storefront.toml'}")
    json_at = result.output.index(f"# {directory / 'storefront.json'}")
    assert toml_at < json_at
    assert "port = 8000" in result.output and '{"port": 8001}' in result.output
    assert "storefront.secrets.toml" not in result.output
    assert "0xsecret" not in result.output


def test_config_show_raw_without_public_layer(monkeypatch, tmp_path, runner, app):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    _layers(tmp_path, storefront_secrets_toml='[wallet]\nprivate_key = "0xsecret"\n')

    result = runner.invoke(app, ["config", "show", "--raw"])

    assert result.exit_code == 1
    assert "0xsecret" not in result.output


def test_config_get_key_found_scalar(monkeypatch, runner, app):
    import market_storefront.groups.config as config_group

    monkeypatch.setattr(config_group, "load_storefront_config", lambda: {"port": 8001})
    monkeypatch.setattr(config_group, "get_dotted", lambda doc, key: doc.get(key))

    result = runner.invoke(app, ["config", "get", "port"])

    assert result.exit_code == 0
    assert "8001" in result.output


def test_config_get_key_found_dict(monkeypatch, runner, app):
    import market_storefront.groups.config as config_group

    monkeypatch.setattr(
        config_group, "load_storefront_config", lambda: {"wallet": {"address": "0xabc"}}
    )
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
    assert "# settlements = [" in cfg.read_text()


def test_config_set_rejects_legacy_path_with_exact_migration_command(
    monkeypatch, runner, app
):
    from market_config.settlement_migration import STOREFRONT_MIGRATION_COMMAND

    import market_storefront.groups.config as config_group

    monkeypatch.setattr(
        config_group,
        "write_user_config",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("legacy edit reached writer")
        ),
    )

    result = runner.invoke(
        app,
        ["config", "set", "settlement.hosted.base_url", "do-not-write"],
    )

    assert result.exit_code == 2
    assert STOREFRONT_MIGRATION_COMMAND in result.output


_PAYMENTS_SETTLEMENT = """[Settlement]
schema_version = 1
priority = ["arkhai.payments.v1"]

[Settlement.arkhai_payments]
enabled = true
service_url = "https://payments.example.test"
service_identity = { scheme = "ed25519", identifier = "6yzxO_euOl9hQWih-wknLTl3HsS4UjcngV5GbK-O4WM" }
fee_bps = 250
dispute_authority = "33333333-3333-4333-8333-333333333333"
api_key_env = "ARKHAI_PAYMENTS_API_KEY"
"""


def test_settlement_migration_accepts_the_installed_payments_mechanism(
    monkeypatch, tmp_path, runner, app
):
    import market_storefront.groups.config as config_group

    cfg = tmp_path / "storefront.toml"
    cfg.write_text(_PAYMENTS_SETTLEMENT)
    monkeypatch.setattr(config_group, "storefront_config_file", lambda: cfg)

    result = runner.invoke(app, ["config", "migrate", "--scope", "settlement", "--check"])

    assert result.exit_code == 0, result.output
    assert cfg.read_text() == _PAYMENTS_SETTLEMENT


def test_settlement_migration_refuses_stripe_with_its_removal(monkeypatch, tmp_path, runner, app):
    import market_storefront.groups.config as config_group

    cfg = tmp_path / "storefront.toml"
    cfg.write_text('[Settlement]\nschema_version = 1\npriority = ["fiat.stripe.v1"]\n')
    monkeypatch.setattr(config_group, "storefront_config_file", lambda: cfg)

    result = runner.invoke(app, ["config", "migrate", "--scope", "settlement", "--check"])

    assert result.exit_code != 0
    assert "was removed" in result.output


def test_publication_migration_compiles_a_payment_clause():
    import tomllib

    from market_storefront.groups.config import _seller_publication_clause_compiler

    compile_clause = _seller_publication_clause_compiler(tomllib.loads(_PAYMENTS_SETTLEMENT))
    clause = compile_clause(
        {
            "mechanism": "arkhai.payments.v1",
            "asset": "USD/2",
            "rate": "200",
            "per": "hour",
            "mechanism_input": {
                "payee_account": "22222222-2222-4222-8222-222222222222",
                "asset": "USD/2",
            },
        }
    )

    assert clause.mechanism == "arkhai.payments.v1"
