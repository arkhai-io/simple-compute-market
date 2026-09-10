"""The buyer's own validator accepts the seller's Alkahest acceptance.

Both sides run here: the real Alkahest publication builder produces the
advertised option, the buyer builds its escrow proposal and selection carrier
from that option, the composed bare-metal storefront accepts it, and the
buyer's `validate_accepted_alkahest_plan` re-derives the whole obligation from
its own proposal. That is the seam a wrong seller payload has to survive, so
the tampering cases below alter the accepted plan the way a lying seller would
and require the buyer to refuse.

Nothing is published, purchased, funded or provisioned: the storefront writes
to a temporary SQLite database and no chain, registry or provisioner is
contacted. Every address and key is obviously synthetic development material
with no value on any network, and must never be used on one.
"""

from __future__ import annotations

import base64
import json
from typing import Any

import pytest
from arkhai_bare_metal import make_bare_metal_provision_terms
from arkhai_bare_metal_buyer.settlement_composition import (
    BareMetalBuyerMechanismError,
    bare_metal_escrow_proposal,
    validate_accepted_alkahest_plan,
)
from arkhai_bare_metal_storefront.domain_runtime import get_market_domain_contract
from arkhai_bare_metal_storefront.negotiation_service import (
    BareMetalNegotiationService,
)
from arkhai_bare_metal_storefront.settlement_composition import (
    BareMetalStorefrontSettlementComposition,
)
from arkhai_bare_metal_storefront.sqlite_client import SQLiteClient
from core_storefront.models.negotiation_models import NegotiateNewRequest
from market_alkahest import AlkahestSettlementConfig, create_alkahest_registration
from market_core.schemas import SettlementOption, SettlementPlan, SettlementSelection
from market_identity import Eip191Signer
from market_settlement_runtime import MechanismReadiness

BUYER_SIGNER = Eip191Signer(bytes.fromhex("22" * 32))
SELLER_SIGNER = Eip191Signer(bytes.fromhex("11" * 32))
SELLER_WALLET = "0x" + "bb" * 20
ESCROW_ADDRESS = "0x" + "11" * 20
TOKEN_ADDRESS = "0x" + "aa" * 20
CHAIN = "base_sepolia"
LISTING_ID = "alkahest-listing"
SSH_PUBLIC_KEY = "ssh-ed25519 " + base64.b64encode(b"x" * 32).decode()
DURATION_SECONDS = 7200
RATE_PER_HOUR = 1000
EXPIRATION_UNIX = 1_900_000_000
BUYER_REDERIVATION_ERROR = (
    "^accepted obligation could not be re-derived from the buyer proposal$"
)

ACCEPTED_ESCROW = {
    "chain_name": CHAIN,
    "escrow_address": ESCROW_ADDRESS,
    "literal_fields": {"token": TOKEN_ADDRESS},
    "rates": [{"field": "amount", "per": "hour", "value": str(RATE_PER_HOUR)}],
}


def _published_option() -> SettlementOption:
    registration = create_alkahest_registration()
    artifacts = registration.option_builder(
        AlkahestSettlementConfig(enabled=True),
        MechanismReadiness(
            mechanism="alkahest.v1",
            configured=True,
            enabled=True,
            ready=True,
        ),
        {"accepted_escrows": [ACCEPTED_ESCROW]},
        "seller",
    )
    option = SettlementOption.model_validate(artifacts["settlement_options"][0])
    assert set(option.params) == {"accepted_escrow"}
    return option


async def _seller(tmp_path, option: SettlementOption) -> BareMetalNegotiationService:
    domain = get_market_domain_contract()
    db = SQLiteClient(str(tmp_path / "storefront.db"), domain=domain)
    await db.upsert_bare_metal_listing(
        listing_id=LISTING_ID,
        status="open",
        created_at="2026-01-01T00:00:00Z",
        updated_at="2026-01-01T00:00:00Z",
        seller_principal=SELLER_SIGNER.identity,
        storefront_url="http://seller:8000",
        site_id="site-a",
        pool_id="pool-a",
        physical_resource_id="resource-1",
        listing={
            "kind": "bare_metal.v1",
            "machine_id": "bm-machine-1",
            "physical_host_id": "physical-host-1",
            "access_methods": ["ssh"],
        },
        accepted_escrows=[],
        settlement_options=[option.model_dump(mode="json")],
    )
    composition = BareMetalStorefrontSettlementComposition.from_raw_config(
        {"priority": ["alkahest.v1"], "alkahest": {"enabled": True}},
        resources={"wallet": {"address": SELLER_WALLET}},
    )
    return BareMetalNegotiationService(
        db=db,
        domain=domain,
        seller_principal=SELLER_SIGNER.identity,
        round_hook=None,  # type: ignore[arg-type]
        build_plan=lambda **kwargs: {},
        accepted_obligation_dispatch=composition.accepted_obligation_dispatch(),
        now_unix=lambda: EXPIRATION_UNIX - 3600,
    )


async def _accepted(tmp_path) -> tuple[dict[str, Any], Any, SettlementSelection]:
    """Drive one buyer selection through the seller and return the wire reply."""

    option = _published_option()
    service = await _seller(tmp_path, option)
    # The buyer's own carrier: the advertised entry decides the escrow, and the
    # expiry is the buyer's — an advertised Alkahest escrow carries none.
    proposal = bare_metal_escrow_proposal(
        listing={"demands": []},
        option=option,
        expiration_unix=EXPIRATION_UNIX,
    )
    selection = SettlementSelection(
        mechanism=option.mechanism,
        option_id=option.option_id,
        expiration_unix=EXPIRATION_UNIX,
    )
    body = {
        "listing_id": LISTING_ID,
        "buyer_principal": BUYER_SIGNER.identity.model_dump(mode="json"),
        "buyer_agent_url": "https://buyer.example",
        "provision_terms": make_bare_metal_provision_terms(
            duration_seconds=DURATION_SECONDS,
            ssh_public_key=SSH_PUBLIC_KEY,
        ).model_dump(mode="json"),
        "proposal": {
            "settlement_selection": selection.model_dump(mode="json"),
            "fields": {},
        },
    }
    response = await service.open(
        request=NegotiateNewRequest.model_validate(json.loads(json.dumps(body))),
        buyer_principal=BUYER_SIGNER.identity,
    )
    reply = json.loads(json.dumps(response.model_dump(mode="json")))
    return reply, proposal, selection


async def test_buyer_validates_the_sellers_accepted_alkahest_plan(tmp_path) -> None:
    reply, proposal, selection = await _accepted(tmp_path)

    assert reply["action"] == "accept"
    assert reply["settlement_selection"] == selection.model_dump(mode="json")
    plan = SettlementPlan.model_validate(reply["settlement_plan"])
    obligation = plan.obligations[0]
    # What core_buyer requires before delegating the mechanism-specific view.
    assert obligation.payer == "buyer" and obligation.claimant == "seller"
    assert obligation.payer_principal == BUYER_SIGNER.identity.model_dump(mode="json")
    assert obligation.claimant_principal == SELLER_SIGNER.identity.model_dump(
        mode="json"
    )
    assert obligation.mechanism == selection.mechanism
    assert obligation.expiration_unix == selection.expiration_unix
    assert obligation.amount == int(reply["proposal"]["fields"]["amount"])
    assert obligation.amount == RATE_PER_HOUR * DURATION_SECONDS // 3600

    validate_accepted_alkahest_plan(
        plan=plan,
        proposal=proposal,
        duration_seconds=DURATION_SECONDS,
        address_config_path=None,
        seller_payout_address=SELLER_WALLET,
    )


def _tampered(reply: dict[str, Any], mutate) -> SettlementPlan:
    payload = json.loads(json.dumps(reply["settlement_plan"]))
    mutate(payload["obligations"][0])
    return SettlementPlan.model_validate(payload)


@pytest.mark.parametrize(
    ("mutate", "detail"),
    [
        pytest.param(
            lambda ob: ob["params"]["obligation_data"].update({"amount": "1"}),
            "accepted Alkahest amount carriers disagree",
            id="nested-amount",
        ),
        pytest.param(
            lambda ob: ob["params"]["obligation_data"].update(
                {"token": "0x" + "cc" * 20}
            ),
            "accepted Alkahest asset and token disagree",
            id="nested-token",
        ),
        pytest.param(
            lambda ob: ob["params"]["obligation_data"].update(
                {"demand": "0x" + "00" * 32}
            ),
            "accepted Alkahest payout differs from the pinned seller",
            id="payout-demand",
        ),
        pytest.param(
            lambda ob: ob["params"].update({"chain_name": "arbitrum_sepolia"}),
            "accepted Alkahest chain differs from the proposal",
            id="chain",
        ),
        pytest.param(
            lambda ob: ob["params"].update({"escrow_contract": "0x" + "dd" * 20}),
            "accepted Alkahest escrow differs from the proposal",
            id="escrow-contract",
        ),
        pytest.param(
            lambda ob: ob.update({"conditions": [{"arbiter": "0x" + "ee" * 20}]}),
            "accepted Alkahest obligation declares unsupported conditions",
            id="conditions",
        ),
    ],
)
async def test_buyer_refuses_an_altered_accepted_obligation(
    tmp_path, mutate, detail
) -> None:
    reply, proposal, _ = await _accepted(tmp_path)
    accepted = SettlementPlan.model_validate(reply["settlement_plan"])

    validate_accepted_alkahest_plan(
        plan=accepted,
        proposal=proposal,
        duration_seconds=DURATION_SECONDS,
        address_config_path=None,
        seller_payout_address=SELLER_WALLET,
    )

    with pytest.raises(
        BareMetalBuyerMechanismError, match=BUYER_REDERIVATION_ERROR
    ) as exc_info:
        validate_accepted_alkahest_plan(
            plan=_tampered(reply, mutate),
            proposal=proposal,
            duration_seconds=DURATION_SECONDS,
            address_config_path=None,
            seller_payout_address=SELLER_WALLET,
        )
    assert type(exc_info.value.__cause__) is ValueError
    assert str(exc_info.value.__cause__) == detail


async def test_buyer_refuses_an_accepted_plan_paying_another_address(
    tmp_path,
) -> None:
    """The payout the buyer pinned is the one the whole obligation must imply."""

    reply, proposal, _ = await _accepted(tmp_path)
    accepted = SettlementPlan.model_validate(reply["settlement_plan"])

    validate_accepted_alkahest_plan(
        plan=accepted,
        proposal=proposal,
        duration_seconds=DURATION_SECONDS,
        address_config_path=None,
        seller_payout_address=SELLER_WALLET,
    )

    with pytest.raises(
        BareMetalBuyerMechanismError, match=BUYER_REDERIVATION_ERROR
    ) as exc_info:
        validate_accepted_alkahest_plan(
            plan=accepted,
            proposal=proposal,
            duration_seconds=DURATION_SECONDS,
            address_config_path=None,
            seller_payout_address="0x" + "cc" * 20,
        )
    assert type(exc_info.value.__cause__) is ValueError
    assert str(exc_info.value.__cause__) == (
        "accepted Alkahest payout differs from the pinned seller"
    )
