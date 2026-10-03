from typer.testing import CliRunner

from domains.vms.buyer import config_cli
from domains.vms.buyer.cli import app


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
    assert "--settlement" in buy_help.output
    assert "--settlement" in negotiate_help.output
    assert "--action" not in buy_help.output
    assert "--action" not in settle_help.output
    assert "--settlement-mechanism" not in buy_help.output
    assert "--settlement-asset" not in buy_help.output
    assert "--settlement-option-id" not in buy_help.output
    assert "--no-browser" not in buy_help.output
    for removed in (
        "--chain",
        "--token-contract",
        "--token-decimals",
        "--escrow-uid",
        "--duration-hours",
        "--ssh-public-key",
    ):
        assert removed not in settle_help.output
    for removed in ("--chain", "--token-contract", "--token-decimals"):
        assert removed not in buy_help.output
    for removed in ("--chain", "--token-contract", "--token-decimals"):
        assert removed not in negotiate_help.output
    assert "--buyer-priv-key" not in buy_help.output
    assert "--buyer-priv-key" not in negotiate_help.output
    assert "--buyer-priv-key" not in settle_help.output
