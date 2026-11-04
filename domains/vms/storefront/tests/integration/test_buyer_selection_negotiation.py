"""The VM buyer's selection of a priced option negotiates to acceptance.

A fresh VM negotiation names its settlement option explicitly, and a selection
carries no shape of its own: whether it bargains an amount is read from the
option it selects. The production buyer client and the served storefront must
agree on that, or the seller refuses the buyer's opening for a missing amount.
"""

from __future__ import annotations

import asyncio
import json

from arkhai_vms import make_vm_provision_terms
from arkhai_vms_buyer.buyer_client import negotiate_with_seller
from arkhai_vms_buyer.settlement_composition import (
    buyer_settlement_registry,
    buyer_stage,
)
from core_buyer.settlement import SelectedSettlementOption
from market_alkahest.dev_chain import anvil_address_book_path
from market_core.schemas import SettlementOption, SettlementSelection
from market_identity import TrustedIdentitySet

from tests._settings_overrides import settings_overrides, replaced_setting
from market_storefront.utils import config as storefront_config
from tests.fake_site import TEST_MARKETPLACE_SIGNER
from tests.introduction_deals import publish
from tests.loopback import serving
from tests.publication_app import BUYER_SIGNER, pool, publication_app

# VM may publish Alkahest for an unbacked pool in this composition double.
_ALKAHEST_PUBLISHABLE = {"alkahest.v1": False, "arkhai.payments.v1": True}


def _buyer_chain(tmp_path, monkeypatch, address_book) -> None:
    """The buyer's configured anvil chain, with the address book the seller uses.

    The buyer reads the arbiter's codec from it to check the plan's demand.
    """
    config_dir = tmp_path / "buyer-config" / "arkhai"
    config_dir.mkdir(parents=True)
    (config_dir / "buyer.toml").write_text(
        "[chains.anvil]\n"
        'rpc_url = "http://anvil.test"\n'
        "\n"
        "[Settlement.alkahest]\n"
        f'address_books = {{ anvil = "{address_book}" }}\n'
    )
    monkeypatch.setenv("XDG_CONFIG_HOME", str(config_dir.parent))


async def test_a_buyer_selection_of_a_priced_alkahest_option_reaches_acceptance(
    tmp_path, monkeypatch
) -> None:
    book = json.loads(anvil_address_book_path().read_text())
    # Deterministic local contract fixture; never used on a public network.
    book["arbiters_addresses"]["erc20_splitter"] = "0x" + "44" * 20
    address_book = tmp_path / "alkahest.json"
    address_book.write_text(json.dumps(book))
    _buyer_chain(tmp_path, monkeypatch, address_book)
    async with publication_app(
        tmp_path, mechanism_fulfillment=_ALKAHEST_PUBLISHABLE, negotiation=True
    ) as world:
        world.pools.append(pool("broker-a", backing="unbacked"))
        configured = storefront_config.settlement_config_mapping()
        configured["alkahest"].update(
            release_models=["recipient", "interruptible"],
            address_books={"anvil": str(address_book)},
            interruptible_oracle_addresses=["0x" + "cd" * 20],
        )
        world.composition.settlement_config = world.composition.configuration_registry.resolve(
            configured, role="seller"
        )
        with replaced_setting("settlement", configured):
            listing = (await publish(world))["broker-a"]
        listing_id = listing["listing_id"]
        raw_options = [
            option
            for option in listing["settlement_options"]
            if option["settlement"]["schema"] == "alkahest.v1"
        ]
        assert len(raw_options) == 2
        assert len({option["option_id"] for option in raw_options}) == 2
        assert all("lifecycle" not in option for option in raw_options)
        assert "interruptible" not in listing["listing_resource"]
        raw = raw_options[1]
        assert "oracle" in raw["settlement"]["accepted_escrow"]["demand"]["demand_data"]
        option = SettlementOption.model_validate(raw)
        hourly = int(option.price_rates[0].value)
        selection = SettlementSelection(
            option_id=option.option_id,
            settlement={"schema": option.settlement_schema},
            expiration_unix=1_900_000_000,
        )
        selected = SelectedSettlementOption(
            option=option,
            selection=selection,
            registration=buyer_settlement_registry().registration(
                option.settlement_schema
            ),
        )
        rounds: list[tuple[int, str | None]] = []

        with (
            settings_overrides(**{"capacity.hold_ttl_seconds": 900}),
            replaced_setting("settlement", configured),
        ):
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
                            "_selected_settlement_option": option.model_dump(
                                mode="json"
                            )
                        },
                        # As `market negotiate` does: the selected entry checks
                        # the plan the seller materializes from its selection.
                        validate_advertised_plan=buyer_stage(
                            option.settlement_schema
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
