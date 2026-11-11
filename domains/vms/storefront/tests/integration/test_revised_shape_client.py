"""A revised shape crosses the typed client and the served negotiation API.

A buyer's counter carries its revision as ``proposal.provision_terms``, the
domain's versioned envelope inside an otherwise opaque proposal. The storefront
client serializes it, the request model validates it, the controller forwards it
to the runtime, and the accepted deal must carry the revised shape into its
recorded terms and settlement order rather than fall back to the advertised one.
"""

from __future__ import annotations

import json

from market_alkahest.dev_chain import anvil_address_book_path

from market_storefront.services.vm_job_spec_service import compute_capacity_claim_from_order
from market_storefront.utils import config as storefront_config
from tests._settings_overrides import replaced_setting
from tests.introduction_deals import publish, vm_provision
from tests.publication_app import pool, publication_app, settlement_clause

# VM may publish Alkahest for an unbacked pool in this composition double.
_ALKAHEST_PUBLISHABLE = {"alkahest.v1": False, "arkhai.payments.v1": True}
# Deterministic local contract and token fixtures; never used on a public network.
_SPLITTER = "0x" + "44" * 20
_ASSET = "0x" + "22" * 20


async def test_a_smaller_shape_counter_reaches_the_accepted_terms_and_order(tmp_path) -> None:
    book = json.loads(anvil_address_book_path().read_text())
    book["arbiters_addresses"]["erc20_splitter"] = _SPLITTER
    address_book = tmp_path / "alkahest.json"
    address_book.write_text(json.dumps(book))
    async with publication_app(
        tmp_path, mechanism_fulfillment=_ALKAHEST_PUBLISHABLE, negotiation=True
    ) as world:
        clause = settlement_clause()
        clause.pop("rate")
        clause.pop("per")
        world.set_settlement_clauses([clause])
        world.pools.append(pool(
            "broker-a", backing="unbacked",
            capacity={"gpu_count": 1, "vcpu_count": 8},
            pricing={
                "gpu": {"H100": {"rates": [{"asset": _ASSET, "rate": "60", "per": "hour"}]}},
                "cpu": {"rates": [{"asset": _ASSET, "rate": "5", "per": "hour"}]},
            },
            listing_shapes={"vm": [{
                "gpu": {"model": "H100", "count": 1},
                "cpu": {"count": {"offer": 8, "min": 2}},
            }]},
        ))
        configured = storefront_config.settlement_config_mapping()
        configured["alkahest"].update(address_books={"anvil": str(address_book)})
        world.composition.settlement_config = world.composition.configuration_registry.resolve(
            configured, role="seller"
        )
        with replaced_setting("settlement", configured):
            listing = (await publish(world))["broker-a"]
            option = next(
                option for option in listing["settlement_options"]
                if option["settlement"]["schema"] == "alkahest.v1"
            )
            selection = {
                "option_id": option["option_id"],
                "settlement": {"schema": "alkahest.v1"},
                "expiration_unix": 1_900_000_000,
            }
            opened = await world.buyer.negotiate_new(
                listing_id=listing["listing_id"],
                # Below the seller's floor, so the seller counters at it.
                initial_amount=9000,
                provision_terms=vm_provision(),
                settlement_selection=selection,
                selection_only=True,
                buyer_agent_url="https://buyer.invalid",
            )
            assert opened["action"] == "counter", opened
            revised = {
                "gpu": {"model": "H100", "count": 1},
                "cpu": {"count": 2},
            }
            accepted = await world.buyer.negotiate_continue(
                opened["negotiation_id"],
                action="counter",
                proposal={
                    "fields": {"amount": opened["proposal"]["fields"]["amount"]},
                    "settlement_selection": selection,
                    "provision_terms": {"kind": "compute.v1", "version": 1, "payload": revised},
                },
            )

    assert accepted["action"] == "accept", accepted
    terms = accepted["agreement"]["provision_terms"]["payload"]["compute_resource"]
    assert terms["vcpu_count"] == 2 and terms["gpu_count"] == 1
    order = accepted["settlement_plan"]["service_terms"]["vm.v1"]["order"]
    assert compute_capacity_claim_from_order(order)["dimensions"] == {
        "gpu_count": 1, "vcpu_count": 2,
    }
    row = await world.db.load_negotiation_thread_row(
        negotiation_id=opened["negotiation_id"]
    )
    assert json.loads(row["agreement_bytes"])["provision_terms"]["payload"][
        "compute_resource"
    ]["vcpu_count"] == 2
