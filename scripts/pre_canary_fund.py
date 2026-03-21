#!/usr/bin/env python3
"""Plan or apply buyer/seller funding before a live canary.

The script reads the local secret source-of-truth from
~/.config/simple-market-service, inspects prod-canary.env plus wallets.env and
alchemy.env, then computes the top-ups needed before a live canary starts.

For Base Sepolia it can resolve USDC/WETH from the checked-in token registry.
For Base mainnet, provide CANARY_FUNDING_TOKEN_ADDRESS and
CANARY_FUNDING_TOKEN_DECIMALS explicitly.
"""

from __future__ import annotations

import argparse
import json
from decimal import Decimal, ROUND_CEILING
from pathlib import Path
from typing import NamedTuple


ROOT = Path(__file__).resolve().parents[1]
LOCAL_SECRETS_DIR = Path("~/.config/simple-market-service").expanduser()
BASE_SEPOLIA_TOKEN_REGISTRY = ROOT / "core/agent/app/data/token_registry_base_sepolia.json"
CHAIN_CONFIG = {
    "base_sepolia": {
        "chain_id": "84532",
        "rpc_env": "ALCHEMY_BASE_SEPOLIA_HTTP_URL",
        "funder_env": "SEPOLIA_FUNDER_PRIVATE_KEY",
    },
    "base": {
        "chain_id": "8453",
        "rpc_env": "ALCHEMY_BASE_MAINNET_HTTP_URL",
        "funder_env": "MAINNET_FUNDER_PRIVATE_KEY",
    },
}
ERC20_ABI = [
    {
        "constant": True,
        "inputs": [{"name": "owner", "type": "address"}],
        "name": "balanceOf",
        "outputs": [{"name": "", "type": "uint256"}],
        "type": "function",
    },
    {
        "constant": False,
        "inputs": [
            {"name": "to", "type": "address"},
            {"name": "value", "type": "uint256"},
        ],
        "name": "transfer",
        "outputs": [{"name": "", "type": "bool"}],
        "type": "function",
    },
]


class FundingContext(NamedTuple):
    chain_name: str
    chain_id: int
    rpc_url: str
    funder_private_key: str
    seller_wallet_address: str
    buyer_wallet_address: str
    token_symbol: str
    token_amount: Decimal
    duration_hours: int
    buyer_native_floor_wei: int
    seller_native_floor_wei: int
    buyer_token_buffer_base_units: int
    token_address_override: str | None
    token_decimals_override: int | None
    mainnet_max_native_topup_wei: int | None
    mainnet_max_erc20_topup_base_units: int | None


class TokenMetadata(NamedTuple):
    symbol: str
    address: str
    decimals: int


class FundingTransfer(NamedTuple):
    asset_kind: str
    symbol: str
    recipient: str
    amount: int


def _parse_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        values[key] = _strip_matching_quotes(value.strip())
    return values


def _strip_matching_quotes(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1]
    return value


def _require_keys(values: dict[str, str], *, label: str, keys: tuple[str, ...]) -> None:
    missing = sorted(key for key in keys if not values.get(key))
    if missing:
        raise SystemExit(f"Missing required {label} keys: {', '.join(missing)}")


def _to_base_units(amount: Decimal, decimals: int) -> int:
    scale = Decimal(10) ** decimals
    return int((amount * scale).to_integral_value(rounding=ROUND_CEILING))


def load_funding_context(local_secrets_dir: Path) -> FundingContext:
    shared = _parse_env_file(local_secrets_dir / "shared.env")
    alchemy = _parse_env_file(local_secrets_dir / "alchemy.env")
    wallets = _parse_env_file(local_secrets_dir / "wallets.env")
    canary = _parse_env_file(local_secrets_dir / "prod-canary.env")

    _require_keys(shared, label="shared.env", keys=("CHAIN_NAME",))
    chain_name = shared["CHAIN_NAME"]
    if chain_name not in CHAIN_CONFIG:
        raise SystemExit(
            "shared.env:CHAIN_NAME must be one of "
            + ", ".join(sorted(CHAIN_CONFIG))
            + f", got {chain_name}"
        )
    chain_cfg = CHAIN_CONFIG[chain_name]

    _require_keys(alchemy, label="alchemy.env", keys=(chain_cfg["rpc_env"],))
    _require_keys(
        wallets,
        label="wallets.env",
        keys=(
            chain_cfg["funder_env"],
            "SELLER_WALLET_ADDRESS",
            "BUYER_WALLET_ADDRESS",
        ),
    )
    _require_keys(
        canary,
        label="prod-canary.env",
        keys=("CANARY_TOKEN_SYMBOL", "CANARY_TOKEN_AMOUNT", "CANARY_DURATION_HOURS"),
    )

    token_decimals_override = canary.get("CANARY_FUNDING_TOKEN_DECIMALS")

    return FundingContext(
        chain_name=chain_name,
        chain_id=int(shared.get("CHAIN_ID", chain_cfg["chain_id"])),
        rpc_url=alchemy[chain_cfg["rpc_env"]],
        funder_private_key=wallets[chain_cfg["funder_env"]],
        seller_wallet_address=wallets["SELLER_WALLET_ADDRESS"],
        buyer_wallet_address=wallets["BUYER_WALLET_ADDRESS"],
        token_symbol=canary["CANARY_TOKEN_SYMBOL"].upper(),
        token_amount=Decimal(canary["CANARY_TOKEN_AMOUNT"]),
        duration_hours=int(canary["CANARY_DURATION_HOURS"]),
        buyer_native_floor_wei=int(canary.get("BUYER_NATIVE_FLOOR_WEI", "20000000000000")),
        seller_native_floor_wei=int(canary.get("SELLER_NATIVE_FLOOR_WEI", "10000000000000")),
        buyer_token_buffer_base_units=int(canary.get("BUYER_TOKEN_BUFFER_BASE_UNITS", "0")),
        token_address_override=canary.get("CANARY_FUNDING_TOKEN_ADDRESS") or None,
        token_decimals_override=int(token_decimals_override) if token_decimals_override else None,
        mainnet_max_native_topup_wei=(
            int(canary["CANARY_MAINNET_MAX_NATIVE_TOPUP_WEI"])
            if canary.get("CANARY_MAINNET_MAX_NATIVE_TOPUP_WEI")
            else None
        ),
        mainnet_max_erc20_topup_base_units=(
            int(canary["CANARY_MAINNET_MAX_ERC20_TOPUP_BASE_UNITS"])
            if canary.get("CANARY_MAINNET_MAX_ERC20_TOPUP_BASE_UNITS")
            else None
        ),
    )


def resolve_token_metadata(context: FundingContext) -> TokenMetadata:
    if context.token_symbol in {"ETH", "NATIVE"}:
        return TokenMetadata(symbol=context.token_symbol, address="", decimals=18)

    if context.token_address_override and context.token_decimals_override is not None:
        return TokenMetadata(
            symbol=context.token_symbol,
            address=context.token_address_override,
            decimals=context.token_decimals_override,
        )

    if context.chain_name == "base_sepolia":
        token_registry = json.loads(BASE_SEPOLIA_TOKEN_REGISTRY.read_text(encoding="utf-8"))
        for entry in token_registry:
            if entry.get("symbol", "").upper() == context.token_symbol:
                return TokenMetadata(
                    symbol=context.token_symbol,
                    address=str(entry["contract_address"]),
                    decimals=int(entry["decimals"]),
                )

    raise SystemExit(
        "Provide CANARY_FUNDING_TOKEN_ADDRESS and CANARY_FUNDING_TOKEN_DECIMALS "
        f"for {context.chain_name} {context.token_symbol} funding"
    )


def build_funding_plan(
    *,
    context: FundingContext,
    token_metadata: TokenMetadata,
    native_balances: dict[str, int],
    erc20_balances: dict[tuple[str, str], int],
) -> list[FundingTransfer]:
    plan: list[FundingTransfer] = []

    seller_balance = native_balances.get(context.seller_wallet_address, 0)
    if seller_balance < context.seller_native_floor_wei:
        plan.append(
            FundingTransfer(
                asset_kind="native",
                symbol="ETH",
                recipient=context.seller_wallet_address,
                amount=context.seller_native_floor_wei - seller_balance,
            )
        )

    buyer_balance = native_balances.get(context.buyer_wallet_address, 0)
    buyer_native_floor = context.buyer_native_floor_wei

    if context.token_symbol == "WETH":
        buyer_native_floor += _to_base_units(
            context.token_amount * Decimal(context.duration_hours),
            token_metadata.decimals,
        ) + context.buyer_token_buffer_base_units

    if buyer_balance < buyer_native_floor:
        plan.append(
            FundingTransfer(
                asset_kind="native",
                symbol="ETH",
                recipient=context.buyer_wallet_address,
                amount=buyer_native_floor - buyer_balance,
            )
        )

    if context.token_symbol not in {"ETH", "NATIVE", "WETH"}:
        required_token_units = _to_base_units(
            context.token_amount * Decimal(context.duration_hours),
            token_metadata.decimals,
        ) + context.buyer_token_buffer_base_units
        current_token_balance = erc20_balances.get(
            (context.buyer_wallet_address, token_metadata.address),
            0,
        )
        if current_token_balance < required_token_units:
            plan.append(
                FundingTransfer(
                    asset_kind="erc20",
                    symbol=token_metadata.symbol,
                    recipient=context.buyer_wallet_address,
                    amount=required_token_units - current_token_balance,
                )
            )

    return plan


def _load_web3():
    from eth_account import Account
    from web3 import HTTPProvider, Web3

    return Account, Web3(HTTPProvider("")), HTTPProvider


def _build_web3(rpc_url: str):
    from web3 import HTTPProvider, Web3

    return Web3(HTTPProvider(rpc_url, request_kwargs={"timeout": 20}))


def fetch_live_balances(
    *,
    context: FundingContext,
    token_metadata: TokenMetadata,
) -> tuple[dict[str, int], dict[tuple[str, str], int]]:
    web3 = _build_web3(context.rpc_url)
    native_balances = {
        context.seller_wallet_address: int(web3.eth.get_balance(context.seller_wallet_address)),
        context.buyer_wallet_address: int(web3.eth.get_balance(context.buyer_wallet_address)),
    }
    erc20_balances: dict[tuple[str, str], int] = {}
    if token_metadata.address:
        contract = web3.eth.contract(address=web3.to_checksum_address(token_metadata.address), abi=ERC20_ABI)
        erc20_balances[(context.buyer_wallet_address, token_metadata.address)] = int(
            contract.functions.balanceOf(
                web3.to_checksum_address(context.buyer_wallet_address)
            ).call()
        )
    return native_balances, erc20_balances


def _send_native_transfer(web3, *, private_key: str, recipient: str, amount: int) -> str:
    from eth_account import Account

    account = Account.from_key(private_key)
    tx = {
        "chainId": web3.eth.chain_id,
        "nonce": web3.eth.get_transaction_count(account.address),
        "to": web3.to_checksum_address(recipient),
        "value": amount,
        "gas": 21_000,
        "gasPrice": int(web3.eth.gas_price),
    }
    signed = account.sign_transaction(tx)
    tx_hash = web3.eth.send_raw_transaction(signed.raw_transaction)
    receipt = web3.eth.wait_for_transaction_receipt(tx_hash)
    if int(receipt.status) != 1:
        raise SystemExit(f"Native funding transfer failed: {tx_hash.hex()}")
    return tx_hash.hex()


def _send_erc20_transfer(
    web3,
    *,
    private_key: str,
    token_address: str,
    recipient: str,
    amount: int,
) -> str:
    from eth_account import Account

    account = Account.from_key(private_key)
    contract = web3.eth.contract(address=web3.to_checksum_address(token_address), abi=ERC20_ABI)
    tx = contract.functions.transfer(
        web3.to_checksum_address(recipient),
        amount,
    ).build_transaction(
        {
            "chainId": web3.eth.chain_id,
            "nonce": web3.eth.get_transaction_count(account.address),
            "from": account.address,
            "gasPrice": int(web3.eth.gas_price),
        }
    )
    signed = account.sign_transaction(tx)
    tx_hash = web3.eth.send_raw_transaction(signed.raw_transaction)
    receipt = web3.eth.wait_for_transaction_receipt(tx_hash)
    if int(receipt.status) != 1:
        raise SystemExit(f"ERC20 funding transfer failed: {tx_hash.hex()}")
    return tx_hash.hex()


def apply_funding_plan(
    *,
    context: FundingContext,
    token_metadata: TokenMetadata,
    plan: list[FundingTransfer],
) -> list[str]:
    web3 = _build_web3(context.rpc_url)
    tx_hashes: list[str] = []
    for transfer in plan:
        if transfer.asset_kind == "native":
            tx_hashes.append(
                _send_native_transfer(
                    web3,
                    private_key=context.funder_private_key,
                    recipient=transfer.recipient,
                    amount=transfer.amount,
                )
            )
            continue
        tx_hashes.append(
            _send_erc20_transfer(
                web3,
                private_key=context.funder_private_key,
                token_address=token_metadata.address,
                recipient=transfer.recipient,
                amount=transfer.amount,
            )
        )
    return tx_hashes


def _plan_to_json(plan: list[FundingTransfer]) -> str:
    payload = [
        {
            "asset_kind": transfer.asset_kind,
            "symbol": transfer.symbol,
            "recipient": transfer.recipient,
            "amount": transfer.amount,
        }
        for transfer in plan
    ]
    return json.dumps(payload, indent=2, sort_keys=True)


def _enforce_mainnet_apply_guard(
    *,
    context: FundingContext,
    plan: list[FundingTransfer],
    allow_mainnet: bool,
) -> None:
    if context.chain_name != "base":
        return

    if not allow_mainnet:
        raise SystemExit("Refusing to apply base mainnet funding without --allow-mainnet")

    if (
        context.mainnet_max_native_topup_wei is None
        or context.mainnet_max_erc20_topup_base_units is None
    ):
        raise SystemExit(
            "Base mainnet funding requires CANARY_MAINNET_MAX_NATIVE_TOPUP_WEI "
            "and CANARY_MAINNET_MAX_ERC20_TOPUP_BASE_UNITS"
        )

    native_total = sum(transfer.amount for transfer in plan if transfer.asset_kind == "native")
    erc20_total = sum(transfer.amount for transfer in plan if transfer.asset_kind == "erc20")
    if (
        native_total > context.mainnet_max_native_topup_wei
        or erc20_total > context.mainnet_max_erc20_topup_base_units
    ):
        raise SystemExit("Base mainnet funding plan exceeds configured caps")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Plan or apply canary funding from ~/.config/simple-market-service "
            "using prod-canary.env, wallets.env, and alchemy.env."
        )
    )
    parser.add_argument(
        "--local-secrets-dir",
        type=Path,
        default=LOCAL_SECRETS_DIR,
        help="Directory containing prod-canary.env, wallets.env, shared.env, and alchemy.env.",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Broadcast the planned top-up transactions instead of only printing the plan.",
    )
    parser.add_argument(
        "--allow-mainnet",
        action="store_true",
        help=(
            "Explicitly allow Base mainnet funding when applying a plan. "
            "Requires CANARY_MAINNET_MAX_NATIVE_TOPUP_WEI and "
            "CANARY_MAINNET_MAX_ERC20_TOPUP_BASE_UNITS."
        ),
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    context = load_funding_context(args.local_secrets_dir.expanduser())
    token_metadata = resolve_token_metadata(context)
    native_balances, erc20_balances = fetch_live_balances(context=context, token_metadata=token_metadata)
    plan = build_funding_plan(
        context=context,
        token_metadata=token_metadata,
        native_balances=native_balances,
        erc20_balances=erc20_balances,
    )
    print(_plan_to_json(plan))

    if args.apply and plan:
        _enforce_mainnet_apply_guard(
            context=context,
            plan=plan,
            allow_mainnet=args.allow_mainnet,
        )
        tx_hashes = apply_funding_plan(context=context, token_metadata=token_metadata, plan=plan)
        print(json.dumps({"applied": tx_hashes}, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
