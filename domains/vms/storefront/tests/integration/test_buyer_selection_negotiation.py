"""The VM buyer's selection of a priced option negotiates to acceptance.

A fresh VM negotiation names its settlement option explicitly, and a selection
carries no shape of its own: whether it bargains an amount is read from the
option it selects. The production buyer client and the served storefront must
agree on that, or the seller refuses the buyer's opening for a missing amount.
"""

from __future__ import annotations

import asyncio

from arkhai_vms import make_vm_provision_terms
from arkhai_vms_buyer.buyer_client import negotiate_with_seller
from arkhai_vms_buyer.settlement_composition import (
    buyer_settlement_registry,
    buyer_stage,
)
from core_buyer.settlement import SelectedSettlementOption
from market_core.schemas import SettlementOption, SettlementSelection
from market_identity import TrustedIdentitySet

from tests._settings_overrides import settings_overrides
from tests.fake_site import TEST_MARKETPLACE_SIGNER
from tests.introduction_deals import publish
from tests.loopback import serving
from tests.publication_app import BUYER_SIGNER, pool, publication_app

# VM may publish Alkahest for an unbacked pool in this composition double.
_ALKAHEST_PUBLISHABLE = {"alkahest.v1": False, "arkhai.payments.v1": True}


async def test_a_buyer_selection_of_a_priced_alkahest_option_reaches_acceptance(
    tmp_path,
) -> None:
    async with publication_app(
        tmp_path, mechanism_fulfillment=_ALKAHEST_PUBLISHABLE, negotiation=True
    ) as world:
        world.pools.append(pool("broker-a", backing="unbacked"))
        listing = (await publish(world))["broker-a"]
        listing_id = listing["listing_id"]
        (raw,) = [
            option
            for option in listing["settlement_options"]
            if option["mechanism"] == "alkahest.v1"
        ]
        option = SettlementOption.model_validate(raw)
        hourly = int(option.rates[0].value)
        selection = SettlementSelection(
            mechanism=option.mechanism,
            option_id=option.option_id,
            expiration_unix=1_900_000_000,
        )
        selected = SelectedSettlementOption(
            option=option,
            selection=selection,
            registration=buyer_settlement_registry().registration(option.mechanism),
        )
        rounds: list[tuple[int, str | None]] = []

        with settings_overrides(**{"capacity.hold_ttl_seconds": 900}):
            with serving(world.app) as base_url:
                outcome = await asyncio.to_thread(
                    lambda: negotiate_with_seller(
                        seller_url=base_url,
                        principal=BUYER_SIGNER.identity,
                        signer=BUYER_SIGNER,
                        listing_id=listing_id,
                        resolve_seller_principals=lambda: TrustedIdentitySet(
                            identities=(TEST_MARKETPLACE_SIGNER.identity,)
                        ),
                        initial_price=hourly,
                        max_price=hourly,
                        provision_terms=make_vm_provision_terms(
                            duration_seconds=3600, ssh_public_key=""
                        ),
                        settlement_selection=selection,
                        policy_params={
                            "_selected_settlement_option": option.model_dump(mode="json")
                        },
                        # As `market negotiate` does: the selected entry checks
                        # the plan the seller materializes from its selection.
                        validate_advertised_plan=buyer_stage(
                            option.mechanism
                        ).plan_validator(listing, selected),
                        max_rounds=10,
                        on_round=lambda number, ours, theirs: rounds.append(
                            (number, theirs.get("action"))
                        ),
                    )
                )

    assert outcome.status == "agreed", outcome
    assert outcome.agreed_amount == hourly
    assert outcome.settlement_selection.option_id == option.option_id
    assert outcome.accepted_escrow_proposal is not None
    assert rounds[-1][1] == "accept"
