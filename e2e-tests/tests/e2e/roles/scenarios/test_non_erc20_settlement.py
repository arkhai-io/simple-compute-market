"""Full settlement-path coverage for scalar non-ERC20 Alkahest escrows."""
from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from importlib import resources
from typing import Any

import pytest
from alkahest_py import AlkahestClient
from eth_account.signers.local import LocalAccount
from web3 import Web3

from market_alkahest.alkahest import (
    Erc1155NonTierableEscrowCodec,
    NativeTokenNonTierableEscrowCodec,
    encode_recipient_demand,
    get_alkahest_network,
    get_recipient_arbiter,
    prewarm_alkahest_address_config_cache,
    resolve_alkahest_address_config,
)
from src.settings import settings
from tests.e2e.roles.scenarios.conftest import (
    delete_mock_rules_if_present,
    wait_for_stage_event,
)
from tests.e2e.roles.scenarios.escrow_helper import _ensure_ws_rpc_url

log = logging.getLogger(__name__)

pytestmark = pytest.mark.e2e_non_erc20_settlement

_CHAIN_NAME = "anvil"
_ALKAHEST_ADDRESSES_PATH = str(
    resources.files("market_storefront.data").joinpath("alkahest_anvil_addresses.json")
)
_MOCK_ERC1155_A = "0x0165878a594ca255338adfa4d48449f69242eb8f"
_MOCK_ERC20_A = "0x9fe46736679d2d9a65f0992f2272de9f3c7fa6e0"
_ANVIL_GOD_PRIVATE_KEY = (
    "0xac0974bec39a17e36ba4a6b4d238ff944bacb478cbed5efcae784d7bf4f2ff80"
)

_DURATION_SECONDS = 3600
_BUYER_INITIAL_AMOUNT = 7_000
_SELLER_RATE = 10_000
_BUYER_MAX_AMOUNT = 12_000
_AGREED_AMOUNT = (_BUYER_INITIAL_AMOUNT + _BUYER_MAX_AMOUNT) // 2

_ERC1155_ABI = [
    {
        "type": "function",
        "name": "mint",
        "stateMutability": "nonpayable",
        "inputs": [
            {"name": "to", "type": "address"},
            {"name": "id", "type": "uint256"},
            {"name": "amount", "type": "uint256"},
        ],
        "outputs": [],
    },
    {
        "type": "function",
        "name": "balanceOf",
        "stateMutability": "view",
        "inputs": [
            {"name": "account", "type": "address"},
            {"name": "id", "type": "uint256"},
        ],
        "outputs": [{"name": "", "type": "uint256"}],
    },
]


@dataclass(frozen=True)
class SettlementCase:
    name: str
    resource_id: str
    rule_id: str
    escrow_address: str
    literal_fields: dict[str, Any]
    token_id: int | None = None


def _send_tx(w3: Web3, account: LocalAccount, tx: dict[str, Any]) -> Any:
    tx.setdefault("from", account.address)
    tx.setdefault("chainId", int(settings.RPC.CHAIN_ID))
    tx.setdefault("nonce", w3.eth.get_transaction_count(account.address))
    tx["gas"] = max(int(tx.get("gas", 0)), 500_000)
    if "maxFeePerGas" not in tx and "maxPriorityFeePerGas" not in tx:
        tx.setdefault("gasPrice", w3.eth.gas_price)
    signed = account.sign_transaction(tx)
    raw_tx = (
        signed.raw_transaction
        if hasattr(signed, "raw_transaction")
        else signed.rawTransaction
    )
    receipt = w3.eth.wait_for_transaction_receipt(
        w3.eth.send_raw_transaction(raw_tx), timeout=30
    )
    assert receipt.status == 1
    return receipt


def _http_rpc_url(rpc_url: str) -> str:
    if rpc_url.startswith("ws://"):
        return "http://" + rpc_url[len("ws://"):]
    if rpc_url.startswith("wss://"):
        return "https://" + rpc_url[len("wss://"):]
    return rpc_url


def _mint_erc1155(
    *, rpc_url: str, buyer_address: str, token_id: int, amount: int
) -> None:
    w3 = Web3(Web3.HTTPProvider(_http_rpc_url(rpc_url)))
    account = w3.eth.account.from_key(_ANVIL_GOD_PRIVATE_KEY)
    token = w3.eth.contract(
        address=Web3.to_checksum_address(_MOCK_ERC1155_A),
        abi=_ERC1155_ABI,
    )
    buyer = Web3.to_checksum_address(buyer_address)
    before = token.functions.balanceOf(buyer, token_id).call()
    _send_tx(
        w3,
        account,
        token.functions.mint(buyer, token_id, amount).build_transaction(),
    )
    after = token.functions.balanceOf(buyer, token_id).call()
    assert after == before + amount


def _settlement_cases() -> list[SettlementCase]:
    native_addr = NativeTokenNonTierableEscrowCodec().resolve_address(
        _CHAIN_NAME, config_path=_ALKAHEST_ADDRESSES_PATH,
    )
    erc1155_addr = Erc1155NonTierableEscrowCodec().resolve_address(
        _CHAIN_NAME, config_path=_ALKAHEST_ADDRESSES_PATH,
    )
    return [
        SettlementCase(
            name="native-token",
            resource_id="compute-e2e-native-settlement-001",
            rule_id="e2e-non-erc20-native-create",
            escrow_address=native_addr,
            literal_fields={},
        ),
        SettlementCase(
            name="erc1155",
            resource_id="compute-e2e-erc1155-settlement-001",
            rule_id="e2e-non-erc20-erc1155-create",
            escrow_address=erc1155_addr,
            literal_fields={"token": _MOCK_ERC1155_A, "tokenId": 1155_001},
            token_id=1155_001,
        ),
    ]


def _resource_csv(cases: list[SettlementCase]) -> str:
    lines = [
        "resource_id,resource_type,resource_subtype,unit,value,state,min_price,token,"
        "max_duration_seconds,attribute.gpu_model,attribute.sla,attribute.region,"
        "attribute.vm_host"
    ]
    for index, case in enumerate(cases, start=1):
        lines.append(
            f'{case.resource_id},compute.gpu,rtx5080,count,1,available,'
            f'{_SELLER_RATE},{_MOCK_ERC20_A},,RTX 5080,90.0,'
            f'"California, US",kvm{index}'
        )
    return "\n".join(lines) + "\n"


def _offer(case: SettlementCase) -> dict[str, Any]:
    return {
        "resource_id": case.resource_id,
        "gpu_model": "RTX 5080",
        "gpu_count": 1,
        "sla": 90.0,
        "region": "California, US",
    }


def _accepted_escrows(case: SettlementCase) -> list[dict[str, Any]]:
    return [{
        "chain_name": _CHAIN_NAME,
        "escrow_address": case.escrow_address,
        "literal_fields": dict(case.literal_fields),
        "rates": [{"field": "amount", "per": "hour", "value": str(_SELLER_RATE)}],
    }]


def _recipient_demands(seller_wallet: str) -> list[dict[str, Any]]:
    return [{
        "chain_name": _CHAIN_NAME,
        "arbiter": get_recipient_arbiter(
            _CHAIN_NAME, config_path=_ALKAHEST_ADDRESSES_PATH,
        ).lower(),
        "demand_data": {"recipient": seller_wallet.lower()},
    }]


def _proposal(case: SettlementCase, amount: int) -> dict[str, Any]:
    return {
        "chain_name": _CHAIN_NAME,
        "escrow_address": case.escrow_address,
        "fields": {"amount": amount},
        "literal_fields": dict(case.literal_fields),
        "expiration_unix": 2_000_000_000,
    }


def _create_on_chain_escrow(
    *,
    case: SettlementCase,
    buyer_private_key: str,
    buyer_address: str,
    seller_wallet_address: str,
    rpc_url: str,
) -> str:
    rpc_url = _ensure_ws_rpc_url(rpc_url)
    prewarm_alkahest_address_config_cache(_ALKAHEST_ADDRESSES_PATH)
    network = get_alkahest_network(_CHAIN_NAME)
    address_config = resolve_alkahest_address_config(
        network, config_path=_ALKAHEST_ADDRESSES_PATH,
    )
    client = AlkahestClient(
        private_key=buyer_private_key,
        rpc_url=rpc_url,
        address_config=address_config,
    )
    common = {
        "arbiter": get_recipient_arbiter(
            _CHAIN_NAME, config_path=_ALKAHEST_ADDRESSES_PATH,
        ),
        "demand": encode_recipient_demand(seller_wallet_address),
    }
    expiration = int(time.time()) + 3600

    async def _do_it() -> str:
        if case.token_id is None:
            receipt = await NativeTokenNonTierableEscrowCodec().create_obligation(
                client,
                {**common, "amount": _AGREED_AMOUNT},
                expiration,
            )
        else:
            _mint_erc1155(
                rpc_url=rpc_url,
                buyer_address=buyer_address,
                token_id=case.token_id,
                amount=_AGREED_AMOUNT,
            )
            receipt = await Erc1155NonTierableEscrowCodec().create_obligation(
                client,
                {
                    **common,
                    "token": _MOCK_ERC1155_A,
                    "tokenId": case.token_id,
                    "amount": _AGREED_AMOUNT,
                },
                expiration,
            )
        uid = (
            receipt
            if isinstance(receipt, str)
            else (receipt or {}).get("log", {}).get("uid")
        )
        if not uid:
            raise RuntimeError(f"escrow.create did not return a uid: {receipt!r}")
        return uid

    return asyncio.run(_do_it())


def _assert_services_ready(storefront_admin_client, provisioning_client) -> None:
    health = storefront_admin_client.get_health()
    assert health.status == "ok"

    status = storefront_admin_client.get_system_status()
    assert (status.checks or {}).get("registry") == "ok"
    assert "anvil" in ((status.checks or {}).get("alkahest", ""))

    provisioning_health = provisioning_client.get_health()
    assert provisioning_health.get("status") == "ok"

    ansible = provisioning_client.get_ansible_readiness()
    assert ansible.get("ansible_mode") == "mock"


@pytest.mark.parametrize("case", _settlement_cases(), ids=lambda c: c.name)
def test_scalar_non_erc20_settlement_reaches_ready(
    case: SettlementCase,
    storefront_client,
    storefront_admin_client,
    provisioning_client,
    provisioning_test_client,
    buyer_config,
    seller_wallet,
):
    """Native-token and ERC1155 escrows settle through provisioning."""
    _assert_services_ready(storefront_admin_client, provisioning_client)

    import_result = storefront_admin_client.admin_import_resources(
        _resource_csv([case]).encode("utf-8"),
        filename=f"{case.name}-settlement-resource.csv",
    )
    assert import_result.failed_count == 0, import_result

    listing_resp = storefront_admin_client.create_listing(
        agent_wallet_address=seller_wallet,
        offer=_offer(case),
        accepted_escrows=_accepted_escrows(case),
        demands=_recipient_demands(seller_wallet),
        max_duration_seconds=_DURATION_SECONDS,
        paused=True,
    )
    listing_id = listing_resp.listing_id
    assert listing_id

    listing = storefront_admin_client.get_listing(listing_id)
    assert listing.status == "open"
    assert listing.paused is True

    result = storefront_admin_client.resume_listing(listing_id)
    assert result.paused is False
    assert result.registry_status == "published"

    eval_result = storefront_admin_client.evaluate_negotiate(
        listing_id,
        proposal=_proposal(case, _BUYER_INITIAL_AMOUNT),
        requested_duration_seconds=_DURATION_SECONDS,
        buyer_address=buyer_config["wallet_address"],
    )
    assert eval_result.would_negotiate, (
        f"{case.name} evaluate-negotiate exited: {eval_result}"
    )
    assert eval_result.decision == "counter"

    negotiate_resp = storefront_client.negotiate_new(
        listing_id=listing_id,
        buyer_address=buyer_config["wallet_address"],
        initial_amount=_BUYER_INITIAL_AMOUNT,
        duration_seconds=_DURATION_SECONDS,
        chain_name=_CHAIN_NAME,
        escrow_address=case.escrow_address,
        literal_fields=dict(case.literal_fields),
    )
    negotiation_id = negotiate_resp.get("negotiation_id")
    assert negotiation_id, negotiate_resp

    force = storefront_admin_client.force_accept_negotiation(
        listing_id,
        negotiation_id,
        amount=_AGREED_AMOUNT,
    )
    assert force.action == "accept"
    assert force.amount == _AGREED_AMOUNT

    detail = storefront_admin_client.get_negotiation(listing_id, negotiation_id)
    assert detail.terminal_state == "success"
    assert detail.agreed_amount == _AGREED_AMOUNT

    escrow_uid = _create_on_chain_escrow(
        case=case,
        buyer_private_key=buyer_config["private_key"],
        buyer_address=buyer_config["wallet_address"],
        seller_wallet_address=seller_wallet,
        rpc_url=buyer_config["rpc_url"],
    )
    log.info("[%s] Created on-chain escrow %s", case.name, escrow_uid)

    delete_mock_rules_if_present(
        provisioning_test_client,
        "e2e-buy-create",
        "e2e-create-pause",
        "e2e-non-erc20-native-create",
        "e2e-non-erc20-erc1155-create",
        case.rule_id,
    )
    provisioning_test_client.add_mock_rule(
        rule_id=case.rule_id,
        match={"vm_action": "create"},
        pause_before_result=True,
        result_stdout=(
            '{"vm_name": "e2e-test-vm", "tenant_user": "vmuser", '
            '"tenant_ssh_key_path": "/tmp/e2e.key", '
            '"frp": {"enabled": false}, '
            '"authentication": {"tenant": {"ssh_commands": '
            '{"external": "ssh vmuser@localhost", '
            '"internal": "ssh vmuser@10.0.0.1"}}}}'
        ),
        fail_with=None,
    )

    evaluate = storefront_admin_client.evaluate_settle(
        escrow_uid,
        listing_id=listing_id,
        ssh_public_key=buyer_config["ssh_public_key"],
        duration_seconds=_DURATION_SECONDS,
    )
    assert evaluate.get("would_submit") is True, evaluate
    vm_host = evaluate.get("vm_host")
    assert vm_host

    job_eval = provisioning_test_client.evaluate_job(
        vm_host,
        vm_target=evaluate.get("vm_target") or "eval-target",
        vm_action="create",
    )
    assert job_eval.get("params_valid") is True, job_eval
    assert job_eval.get("rule_matched") == case.rule_id, job_eval
    assert job_eval.get("would_pause") is True, job_eval

    settle = storefront_client.settle(
        escrow_uid,
        negotiation_id=negotiation_id,
        buyer_address=buyer_config["wallet_address"],
        ssh_public_key=buyer_config["ssh_public_key"],
    )
    assert settle.status == "provisioning", settle

    event = wait_for_stage_event(
        storefront_admin_client,
        "provision",
        "job_submitted",
        listing_id=listing_id,
        timeout=15.0,
    )
    assert event.data.get("resource_id") == case.resource_id

    status = storefront_client.get_settle_status(
        escrow_uid,
        buyer_address=buyer_config["wallet_address"],
    )
    assert status.provisioning_job_id

    provisioning_test_client.resume_rule(case.rule_id)
    job = provisioning_test_client.wait_for_job(status.provisioning_job_id, timeout=30)
    assert job["status"] == "succeeded", job

    wait = storefront_admin_client.wait_for_settlement(escrow_uid, timeout=60.0)
    assert wait.ready is True, wait
    assert wait.status == "ready", wait

    final_status = storefront_client.get_settle_status(
        escrow_uid,
        buyer_address=buyer_config["wallet_address"],
    )
    assert final_status.status == "ready"
    assert final_status.tenant_credentials

    final_listing = storefront_admin_client.get_listing(listing_id)
    assert final_listing.status == "closed"

    final_detail = storefront_admin_client.get_negotiation(listing_id, negotiation_id)
    primary = next((escrow for escrow in final_detail.escrows if escrow["is_primary"]), None)
    assert primary is not None
    assert primary["escrow_uid"] == escrow_uid
    assert primary["status"] == "ready"
    assert primary["fulfillment_uid"]
