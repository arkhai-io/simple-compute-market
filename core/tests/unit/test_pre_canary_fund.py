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
    local_secrets_dir = tmp_path / "local-secrets"
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

    context = module.load_funding_context(local_secrets_dir)
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
    local_secrets_dir = tmp_path / "local-secrets"
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

    context = module.load_funding_context(local_secrets_dir)

    with pytest.raises(
        SystemExit,
        match="Provide CANARY_FUNDING_TOKEN_ADDRESS and CANARY_FUNDING_TOKEN_DECIMALS",
    ):
        module.resolve_token_metadata(context)
