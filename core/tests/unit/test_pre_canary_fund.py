from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[3]
SCRIPT_PATH = ROOT / "scripts/pre_canary_fund.py"


def _load_script_module():
    spec = importlib.util.spec_from_file_location("pre_canary_fund", SCRIPT_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _write_env(path: Path, values: dict[str, str]) -> None:
    path.write_text(
        "".join(f"{key}={value}\n" for key, value in values.items()),
        encoding="utf-8",
    )


def test_pre_canary_fund_plans_native_and_usdc_topups(tmp_path: Path) -> None:
    module = _load_script_module()
    shared_secrets_dir = tmp_path / "shared-secrets"
    local_secrets_dir = tmp_path / "local-secrets"
    shared_secrets_dir.mkdir()
    local_secrets_dir.mkdir()

    _write_env(
        local_secrets_dir / "shared.env",
        {
            "CHAIN_NAME": "base_sepolia",
            "CHAIN_ID": "84532",
        },
    )
    _write_env(
        local_secrets_dir / "alchemy.env",
        {
            "ALCHEMY_BASE_SEPOLIA_HTTP_URL": "https://alchemy.example/base-sepolia-http",
            "ALCHEMY_BASE_SEPOLIA_WSS_URL": "wss://alchemy.example/base-sepolia-wss",
        },
    )
    _write_env(
        local_secrets_dir / "wallets.env",
        {
            "SEPOLIA_FUNDER_PRIVATE_KEY": "0xfunder-private-key",
            "SELLER_PRIVATE_KEY": "0xseller-private-key",
            "SELLER_WALLET_ADDRESS": "0x4444444444444444444444444444444444444444",
            "BUYER_PRIVATE_KEY": "0xbuyer-private-key",
            "BUYER_WALLET_ADDRESS": "0x5555555555555555555555555555555555555555",
        },
    )
    _write_env(
        local_secrets_dir / "prod-canary.env",
        {
            "CANARY_TOKEN_SYMBOL": "USDC",
            "CANARY_TOKEN_AMOUNT": "1.5",
            "CANARY_DURATION_HOURS": "2",
            "BUYER_NATIVE_FLOOR_WEI": "20000",
            "SELLER_NATIVE_FLOOR_WEI": "10000",
            "BUYER_TOKEN_BUFFER_BASE_UNITS": "100000",
        },
    )

    context = module.load_funding_context(local_secrets_dir, shared_secrets_dir=shared_secrets_dir)
    token_metadata = module.resolve_token_metadata(context)
    plan = module.build_funding_plan(
        context=context,
        token_metadata=token_metadata,
        native_balances={
            context.seller_wallet_address: 9000,
            context.buyer_wallet_address: 15000,
        },
        erc20_balances={
            (context.buyer_wallet_address, token_metadata.address): 500000,
        },
    )

    assert [transfer.asset_kind for transfer in plan] == ["native", "native", "erc20"]
    assert [transfer.recipient for transfer in plan] == [
        context.seller_wallet_address,
        context.buyer_wallet_address,
        context.buyer_wallet_address,
    ]
    assert [transfer.amount for transfer in plan] == [1000, 5000, 2600000]
    assert plan[2].symbol == "USDC"


def test_pre_canary_fund_requires_explicit_token_metadata_for_base_mainnet(
    tmp_path: Path,
) -> None:
    module = _load_script_module()
    shared_secrets_dir = tmp_path / "shared-secrets"
    local_secrets_dir = tmp_path / "local-secrets"
    shared_secrets_dir.mkdir()
    local_secrets_dir.mkdir()

    _write_env(
        local_secrets_dir / "shared.env",
        {
            "CHAIN_NAME": "base",
            "CHAIN_ID": "8453",
        },
    )
    _write_env(
        local_secrets_dir / "alchemy.env",
        {
            "ALCHEMY_BASE_MAINNET_HTTP_URL": "https://alchemy.example/base-mainnet-http",
            "ALCHEMY_BASE_MAINNET_WSS_URL": "wss://alchemy.example/base-mainnet-wss",
        },
    )
    _write_env(
        local_secrets_dir / "wallets.env",
        {
            "MAINNET_FUNDER_PRIVATE_KEY": "0xfunder-private-key",
            "SELLER_PRIVATE_KEY": "0xseller-private-key",
            "SELLER_WALLET_ADDRESS": "0x4444444444444444444444444444444444444444",
            "BUYER_PRIVATE_KEY": "0xbuyer-private-key",
            "BUYER_WALLET_ADDRESS": "0x5555555555555555555555555555555555555555",
        },
    )
    _write_env(
        local_secrets_dir / "prod-canary.env",
        {
            "CANARY_TOKEN_SYMBOL": "USDC",
            "CANARY_TOKEN_AMOUNT": "1.0",
            "CANARY_DURATION_HOURS": "1",
            "BUYER_NATIVE_FLOOR_WEI": "20000",
            "SELLER_NATIVE_FLOOR_WEI": "10000",
        },
    )

    context = module.load_funding_context(local_secrets_dir, shared_secrets_dir=shared_secrets_dir)

    with pytest.raises(
        SystemExit,
        match="Provide CANARY_FUNDING_TOKEN_ADDRESS and CANARY_FUNDING_TOKEN_DECIMALS",
    ):
        module.resolve_token_metadata(context)


def test_pre_canary_fund_refuses_base_mainnet_apply_without_allow_flag(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_script_module()
    shared_secrets_dir = tmp_path / "shared-secrets"
    local_secrets_dir = tmp_path / "local-secrets"
    shared_secrets_dir.mkdir()
    local_secrets_dir.mkdir()

    _write_env(local_secrets_dir / "shared.env", {"CHAIN_NAME": "base", "CHAIN_ID": "8453"})
    _write_env(
        local_secrets_dir / "alchemy.env",
        {
            "ALCHEMY_BASE_MAINNET_HTTP_URL": "https://alchemy.example/base-mainnet-http",
            "ALCHEMY_BASE_MAINNET_WSS_URL": "wss://alchemy.example/base-mainnet-wss",
        },
    )
    _write_env(
        local_secrets_dir / "wallets.env",
        {
            "MAINNET_FUNDER_PRIVATE_KEY": "0xfunder-private-key",
            "SELLER_WALLET_ADDRESS": "0x4444444444444444444444444444444444444444",
            "BUYER_WALLET_ADDRESS": "0x5555555555555555555555555555555555555555",
        },
    )
    _write_env(
        local_secrets_dir / "prod-canary.env",
        {
            "CANARY_TOKEN_SYMBOL": "USDC",
            "CANARY_TOKEN_AMOUNT": "1.0",
            "CANARY_DURATION_HOURS": "1",
            "BUYER_NATIVE_FLOOR_WEI": "20000",
            "SELLER_NATIVE_FLOOR_WEI": "10000",
            "CANARY_FUNDING_TOKEN_ADDRESS": "0x6666666666666666666666666666666666666666",
            "CANARY_FUNDING_TOKEN_DECIMALS": "6",
            "CANARY_MAINNET_MAX_NATIVE_TOPUP_WEI": "50000",
            "CANARY_MAINNET_MAX_ERC20_TOPUP_BASE_UNITS": "2000000",
        },
    )

    monkeypatch.setattr(
        module,
        "fetch_live_balances",
        lambda **kwargs: (
            {
                "0x4444444444444444444444444444444444444444": 9000,
                "0x5555555555555555555555555555555555555555": 15000,
            },
            {("0x5555555555555555555555555555555555555555", "0x6666666666666666666666666666666666666666"): 0},
        ),
    )

    with pytest.raises(SystemExit, match="Refusing to apply base mainnet funding without --allow-mainnet"):
        module.main(
            [
                "--shared-secrets-dir",
                str(shared_secrets_dir),
                "--local-secrets-dir",
                str(local_secrets_dir),
                "--apply",
            ]
        )


def test_pre_canary_fund_rejects_base_mainnet_plan_that_exceeds_caps(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_script_module()
    shared_secrets_dir = tmp_path / "shared-secrets"
    local_secrets_dir = tmp_path / "local-secrets"
    shared_secrets_dir.mkdir()
    local_secrets_dir.mkdir()

    _write_env(local_secrets_dir / "shared.env", {"CHAIN_NAME": "base", "CHAIN_ID": "8453"})
    _write_env(
        local_secrets_dir / "alchemy.env",
        {
            "ALCHEMY_BASE_MAINNET_HTTP_URL": "https://alchemy.example/base-mainnet-http",
            "ALCHEMY_BASE_MAINNET_WSS_URL": "wss://alchemy.example/base-mainnet-wss",
        },
    )
    _write_env(
        local_secrets_dir / "wallets.env",
        {
            "MAINNET_FUNDER_PRIVATE_KEY": "0xfunder-private-key",
            "SELLER_WALLET_ADDRESS": "0x4444444444444444444444444444444444444444",
            "BUYER_WALLET_ADDRESS": "0x5555555555555555555555555555555555555555",
        },
    )
    _write_env(
        local_secrets_dir / "prod-canary.env",
        {
            "CANARY_TOKEN_SYMBOL": "USDC",
            "CANARY_TOKEN_AMOUNT": "1.0",
            "CANARY_DURATION_HOURS": "1",
            "BUYER_NATIVE_FLOOR_WEI": "20000",
            "SELLER_NATIVE_FLOOR_WEI": "10000",
            "BUYER_TOKEN_BUFFER_BASE_UNITS": "0",
            "CANARY_FUNDING_TOKEN_ADDRESS": "0x6666666666666666666666666666666666666666",
            "CANARY_FUNDING_TOKEN_DECIMALS": "6",
            "CANARY_MAINNET_MAX_NATIVE_TOPUP_WEI": "4000",
            "CANARY_MAINNET_MAX_ERC20_TOPUP_BASE_UNITS": "1000000",
        },
    )

    monkeypatch.setattr(
        module,
        "fetch_live_balances",
        lambda **kwargs: (
            {
                "0x4444444444444444444444444444444444444444": 9000,
                "0x5555555555555555555555555555555555555555": 15000,
            },
            {("0x5555555555555555555555555555555555555555", "0x6666666666666666666666666666666666666666"): 0},
        ),
    )

    with pytest.raises(SystemExit, match="Base mainnet funding plan exceeds configured caps"):
        module.main(
            [
                "--shared-secrets-dir",
                str(shared_secrets_dir),
                "--local-secrets-dir",
                str(local_secrets_dir),
                "--apply",
                "--allow-mainnet",
            ]
        )


def test_pre_canary_fund_merges_shared_credentials_with_local_canary_inputs(
    tmp_path: Path,
) -> None:
    module = _load_script_module()
    shared_secrets_dir = tmp_path / "shared-secrets"
    local_secrets_dir = tmp_path / "local-secrets"
    shared_secrets_dir.mkdir()
    local_secrets_dir.mkdir()

    _write_env(local_secrets_dir / "shared.env", {"CHAIN_NAME": "base_sepolia", "CHAIN_ID": "84532"})
    _write_env(
        shared_secrets_dir / "alchemy.env",
        {
            "ALCHEMY_BASE_SEPOLIA_HTTP_URL": "https://alchemy.example/shared-http",
            "ALCHEMY_BASE_SEPOLIA_WSS_URL": "wss://alchemy.example/shared-wss",
        },
    )
    _write_env(
        shared_secrets_dir / "wallets.env",
        {
            "SEPOLIA_FUNDER_PRIVATE_KEY": "0xshared-funder-private-key",
            "SELLER_WALLET_ADDRESS": "0x4444444444444444444444444444444444444444",
            "BUYER_WALLET_ADDRESS": "0x5555555555555555555555555555555555555555",
        },
    )
    _write_env(local_secrets_dir / "wallets.env", {"BUYER_WALLET_ADDRESS": "0x6666666666666666666666666666666666666666"})
    _write_env(
        local_secrets_dir / "prod-canary.env",
        {
            "CANARY_TOKEN_SYMBOL": "USDC",
            "CANARY_TOKEN_AMOUNT": "1.5",
            "CANARY_DURATION_HOURS": "2",
            "BUYER_NATIVE_FLOOR_WEI": "20000",
            "SELLER_NATIVE_FLOOR_WEI": "10000",
            "BUYER_TOKEN_BUFFER_BASE_UNITS": "100000",
        },
    )

    context = module.load_funding_context(
        local_secrets_dir=local_secrets_dir,
        shared_secrets_dir=shared_secrets_dir,
    )

    assert context.rpc_url == "https://alchemy.example/shared-http"
    assert context.funder_private_key == "0xshared-funder-private-key"
    assert context.seller_wallet_address == "0x4444444444444444444444444444444444444444"
    assert context.buyer_wallet_address == "0x6666666666666666666666666666666666666666"
