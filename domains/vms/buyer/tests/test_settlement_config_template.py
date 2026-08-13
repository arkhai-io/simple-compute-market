from domains.vms.buyer import config_cli
from domains.vms.buyer.cli import app
from typer.testing import CliRunner


def test_fiat_buyer_template_uses_shared_settlement_without_evm_or_seller_fields(
    monkeypatch,
    tmp_path,
):
    path = tmp_path / "buyer.toml"
    monkeypatch.setattr(config_cli, "user_config_file", lambda: path)
    monkeypatch.setattr(config_cli, "user_config_dir", lambda: tmp_path)

    result = CliRunner().invoke(config_cli.config_app, ["init-user"])

    assert result.exit_code == 0
    rendered = path.read_text()
    assert "[Settlement]" in rendered
    assert "priority = []" in rendered
    assert "[Settlement.stripe]" in rendered
    assert "[Settlement.alkahest]" in rendered
    assert "[Wallet]" not in rendered
    assert "[Chains." not in rendered
    assert "account_ref" not in rendered
    assert "provider" not in rendered
    assert "webhook" not in rendered
    assert "database" not in rendered


def test_evm_resources_are_opt_in_for_buyer_template(monkeypatch, tmp_path):
    path = tmp_path / "buyer.toml"
    monkeypatch.setattr(config_cli, "user_config_file", lambda: path)
    monkeypatch.setattr(config_cli, "user_config_dir", lambda: tmp_path)

    result = CliRunner().invoke(
        config_cli.config_app,
        ["init-user", "--include-evm-resources"],
    )
    assert result.exit_code == 0
    rendered = path.read_text()
    assert "[Wallet]" in rendered
    assert "[Chains.ethereum_sepolia]" in rendered


def test_removed_mechanism_and_private_key_flags_are_rejected():
    runner = CliRunner()

    buy_help = runner.invoke(app, ["buy", "--help"])
    negotiate_help = runner.invoke(app, ["negotiate", "--help"])
    settle_help = runner.invoke(app, ["settle", "--help"])

    assert buy_help.exit_code == 0
    assert negotiate_help.exit_code == 0
    assert settle_help.exit_code == 0
    assert "--settlement-mechanism" not in buy_help.output
    assert "--buyer-priv-key" not in buy_help.output
    assert "--buyer-priv-key" not in negotiate_help.output
    assert "--buyer-priv-key" not in settle_help.output
