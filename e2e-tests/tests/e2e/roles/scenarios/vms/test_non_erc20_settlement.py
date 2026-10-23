"""Full settlement-path coverage for scalar non-ERC20 Alkahest escrows."""
from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from typing import Any

import pytest
from market_alkahest.dev_chain import anvil_address_book_path
from alkahest_py import AlkahestClient
from eth_account.signers.local import LocalAccount
from web3 import Web3

from market_alkahest.alkahest import (
    Erc1155DefaultEscrowCodec,
    NativeTokenDefaultEscrowCodec,
    encode_recipient_demand,
    get_alkahest_network,
    get_recipient_arbiter,
    prewarm_alkahest_address_config_cache,
    resolve_alkahest_address_config,
)
from e2e_harness.settings import settings
from tests.e2e.roles.helpers.compute_deal import (
    advance_storefront,
    assert_storefront_loops_held,
    delete_mock_rules_if_present,
    wait_for_stage_event,
)
from tests.e2e.roles.helpers.escrow import ensure_ws_rpc_url
from tests.e2e.roles.scenarios.vms.conftest import (
    _signer,
    capacity_source_for,
    one_site,
)
from tests.e2e.roles.scenarios.vms.host_registry import (
    E2E_NON_ERC20_HOST,
    E2E_NON_ERC20_POOL_ID,
    provision_e2e_executor,
    refresh_storefront_projections,
)

log = logging.getLogger(__name__)

pytestmark = [
    # Listed first, so the holds are taken before, and released after, every
    # fixture of the module but the lane's autouse ones.
    # The module steps the storefront's loops and fulfillment convergence (a
    # timer cycle could claim a row mid-provider-call, and the module's own
    # explicit cycle would then reach nothing) itself.
    pytest.mark.usefixtures("storefront_loops_held", "fulfillment_convergence_held"),
    pytest.mark.e2e_non_erc20_settlement,
]

_CHAIN_NAME = "anvil"
_ALKAHEST_ADDRESSES_PATH = str(anvil_address_book_path())
_MOCK_ERC1155_A = "0x0165878a594ca255338adfa4d48449f69242eb8f"
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
    native_addr = NativeTokenDefaultEscrowCodec().resolve_address(
        _CHAIN_NAME, config_path=_ALKAHEST_ADDRESSES_PATH,
    )
    erc1155_addr = Erc1155DefaultEscrowCodec().resolve_address(
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


def _offer(case: SettlementCase) -> dict[str, Any]:
    return {
        # The storefront refuses a listing whose resource does not declare the
        # offering mode its domain binding selected.
        "offering_mode": "vm",
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


def _proposal(case: SettlementCase, amount: int, seller_wallet: str) -> dict[str, Any]:
    # A proposal against a listed escrow names the demand it selects from the
    # listing's; the seller refuses one that names none.
    return {
        "chain_name": _CHAIN_NAME,
        "escrow_address": case.escrow_address,
        "fields": {"amount": amount},
        "literal_fields": dict(case.literal_fields),
        "demand": _recipient_demands(seller_wallet)[0],
        "expiration_unix": 2_000_000_000,
    }


def _create_on_chain_escrow(
    *,
    case: SettlementCase,
    buyer_private_key: str,
    buyer_address: str,
    seller_wallet_address: str,
    rpc_url: str,
    expiration_unix: int,
) -> str:
    rpc_url = ensure_ws_rpc_url(rpc_url)
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
    expiration = expiration_unix

    async def _do_it() -> str:
        if case.token_id is None:
            receipt = await NativeTokenDefaultEscrowCodec().create_obligation(
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
            receipt = await Erc1155DefaultEscrowCodec().create_obligation(
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
    assert provisioning_health.status == "ok"

    assert provisioning_client.get_system_status().execution.mocked


@pytest.mark.parametrize("case", _settlement_cases(), ids=lambda c: c.name)
def test_scalar_non_erc20_settlement_reaches_ready(
    case: SettlementCase,
    storefront_client,
    storefront_admin_client, storefront_seller_client,
    provisioning_client,
    provisioning_test_client,
    site_capacity_admin_client,
    registry_client,
    buyer_config,
    seller_wallet,
):
    """Native-token and ERC1155 escrows settle through provisioning."""
    # The listing below is created explicitly; a running publication loop
    # could bind the same slice first and the create would be refused, so the
    # module holds the loops.
    assert_storefront_loops_held(storefront_admin_client)
    _assert_services_ready(storefront_admin_client, provisioning_client)

    # Each case sells its own resource, declared at the site: the listing's
    # source must be in the projection the storefront checks it against, and
    # one executor carries one declaration.
    provision_e2e_executor(
        provisioning_client,
        site_capacity_admin_client,
        host=f"{E2E_NON_ERC20_HOST}-{case.name}",
        pool_id=f"{E2E_NON_ERC20_POOL_ID}-{case.name}",
        resource_id=case.resource_id,
        sellable_units=1,
        attributes={"gpu_model": "RTX 5080", "region": "California, US", "sla": "90.0"},
    )
    refresh_storefront_projections(storefront_admin_client)

    listing_resp = storefront_seller_client.create_listing(
        listing_resource=_offer(case),
        capacity_source=capacity_source_for(_offer(case)),
        accepted_escrows=_accepted_escrows(case),
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
        proposal=_proposal(case, _BUYER_INITIAL_AMOUNT, seller_wallet),
        provision_terms={
            "kind": "compute.v1",
            "version": 1,
            "payload": {
                "duration_seconds": _DURATION_SECONDS,
                "ssh_public_key": buyer_config["ssh_public_key"],
            },
        },
        buyer_principal=_signer(
            "eip191",
            settings.BUYER.MARKETPLACE_CREDENTIAL,
            "BUYER.MARKETPLACE_CREDENTIAL",
        ).identity,
    )
    assert eval_result.would_negotiate, (
        f"{case.name} evaluate-negotiate exited: {eval_result}"
    )
    assert eval_result.decision == "counter"

    # Pin the escrow deadline once: the negotiated terms and the escrow
    # created on chain must state the same one, and settlement refuses an
    # escrow whose deadline differs.
    expiration_unix = int(time.time()) + 3600
    # The VM seller infers nothing from an escrow's shape, so the opening names
    # the listing's Alkahest option explicitly, as the published copy lists it.
    (alkahest_option,) = [
        dict(option)
        for option in registry_client.get_listing(listing_id).settlement_options
        if dict(option)["mechanism"] == "alkahest.v1"
    ]
    negotiate_resp = storefront_client.negotiate_new(
        listing_id=listing_id,
        initial_amount=_BUYER_INITIAL_AMOUNT,
        settlement_selection={
            "mechanism": "alkahest.v1",
            "option_id": alkahest_option["option_id"],
            "expiration_unix": expiration_unix,
        },
        escrow_expiration_unix=expiration_unix,
        demands=_recipient_demands(seller_wallet),
        provision_terms={
            "kind": "compute.v1",
            "version": 1,
            "payload": {
                "duration_seconds": _DURATION_SECONDS,
                # The key is a negotiated term, not a settle-time input:
                # settle reads it from the accepted terms and refuses to
                # substitute the caller's, so an empty value here cannot
                # be supplied later.
                "ssh_public_key": buyer_config["ssh_public_key"],
            },
        },
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
        expiration_unix=expiration_unix,
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
        # The create fact the VM playbook prints, with the forwarded port and
        # the time access became ready: a create reporting neither says
        # nothing a buyer can use, and fails.
        result_stdout=(
            'ok: [kvm1] => {\n    "vm_creation_data": '
            '{"action": "create", "vm_name": "e2e-test-vm", "tenant_user": "vmuser", '
            '"external_ssh_port": "2222", "timestamp": "2030-01-01T00:00:01Z", '
            '"tenant_ssh_key_path": "/tmp/e2e.key", "frp": {"enabled": false}, '
            '"authentication": {"tenant": {"ssh_commands": '
            '{"external": "ssh vmuser@localhost", '
            '"internal": "ssh vmuser@10.0.0.1"}}}}\n}\n'
        ),
        fail_with=None,
    )

    evaluate = storefront_admin_client.evaluate_settle(
        escrow_uid,
        listing_id=listing_id,
        ssh_public_key=buyer_config["ssh_public_key"],
        duration_seconds=_DURATION_SECONDS,
        negotiation_id=negotiation_id,
    )
    assert evaluate.get("would_submit") is True, evaluate
    host_id = evaluate.get("host_id")
    assert host_id

    job_eval = provisioning_test_client.evaluate_job(host_id, vm_action="create")
    assert job_eval.get("params_valid") is True, job_eval
    assert job_eval.get("rule_matched") == case.rule_id, job_eval
    assert job_eval.get("would_pause") is True, job_eval

    settle = storefront_client.settle_evm(
        escrow_uid,
        negotiation_id=negotiation_id,
        buyer_evm_address=buyer_config["wallet_address"],
    )
    assert settle.status == "provisioning", settle

    event = wait_for_stage_event(
        storefront_admin_client,
        "provision",
        "job_submitted",
        listing_id=listing_id,
        timeout=15.0,
    )
    # The seller holds no physical resource identity: provisioning picks the
    # host, so the event names the fulfillment rather than a resource.
    assert event.data.get("fulfillment_id"), event.data

    status = storefront_client.get_settle_status(
        escrow_uid,
    )
    # provisioning_job_id is always None for a fulfillment on the durable
    # path; fulfillment_id is that path's durable identity. See
    # core_storefront.models.settle_models.SettleStatusResponse.
    fulfillment_id = status.fulfillment_id
    assert fulfillment_id == event.data["fulfillment_id"], status

    provisioning_test_client.resume_rule(case.rule_id)
    provisioning_test_client.drain(timeout=30)
    # `advance` rather than `run`: a plain cycle cannot reach a row whose
    # claim lease is still live, which is the case straight after a pending
    # poll. See test_full_deal.py's stage 09a.
    provisioning_client.advance_fulfillment_convergence_cycle()
    fulfillment_status = provisioning_client.get_fulfillment_status(fulfillment_id).model_dump(mode="json")
    assert fulfillment_status.get("state") == "active", fulfillment_status

    wait = storefront_admin_client.wait_for_settlement(escrow_uid, timeout=60.0)
    assert wait.ready is True, wait
    assert wait.status == "ready", wait

    final_status = storefront_client.get_settle_status(
        escrow_uid,
    )
    assert final_status.status == "ready"
    assert final_status.tenant_credentials

    # The storefront's loops are held, so the listing closes only when its
    # capacity events are applied, and the close decides from the projection
    # cache, which must already reflect the deal's reservation.
    advance_storefront(storefront_admin_client, "site-projections")
    for _ in range(5):
        cycle = one_site(advance_storefront(storefront_admin_client, "capacity-events"))
        assert cycle["error"] is None, cycle
        if not cycle["truncated"]:
            break
    else:
        raise AssertionError("capacity-event feed still truncated after five cycles")
    final_listing = storefront_admin_client.get_listing(listing_id)
    assert final_listing.status == "closed"

    final_detail = storefront_admin_client.get_negotiation(listing_id, negotiation_id)
    primary = next((escrow for escrow in final_detail.escrows if escrow["is_primary"]), None)
    assert primary is not None
    assert primary["escrow_uid"] == escrow_uid
    assert primary["status"] == "ready"
    assert primary["fulfillment_uid"]
