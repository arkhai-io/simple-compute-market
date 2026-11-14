"""The VM buyer's selection of a priced option negotiates to acceptance.

A fresh VM negotiation names its settlement option explicitly, and a selection
carries no shape of its own: whether it bargains an amount is read from the
option it selects. The production buyer client and the served storefront must
agree on that, or the seller refuses the buyer's opening for a missing amount.

The buyer's acceptance-bound pricing record holds the seller-signed publication
whose ``pricing`` object carries the family rates; the seller's signed acceptance
pins the multiplier and that rate structure's digest, and the buyer verifies both
against the record when it accepts and again from its archived evidence on resume.
"""

from __future__ import annotations

import asyncio
import base64
import contextlib
import json

import pytest

from arkhai_vms import make_vm_provision_terms
from arkhai_vms_buyer.buyer_client import negotiate_with_seller
from arkhai_vms_buyer.evidence import evidence_store
from arkhai_vms_buyer.pricing_record import (
    verify_pricing_acceptance,
    verify_recovered_pricing,
)
from arkhai_vms_buyer.registry_listing import domain_listing_record
from arkhai_vms_buyer.settlement_composition import (
    accepted_listing_record,
    buyer_settlement_registry,
    buyer_stage,
)
from arkhai_vms_negotiation.amounts import rate_structure_digest
from core_buyer.profile_service import PROFILE_STORE_ENV
from core_buyer.settlement import SelectedSettlementOption
from market_alkahest.dev_chain import anvil_address_book_path
from market_core.schemas import SettlementOption, SettlementSelection
from market_identity import RequestEnvelope, TrustedIdentitySet, canonical_body_hash, sign_request

from tests._settings_overrides import settings_overrides, replaced_setting
from market_storefront.utils import config as storefront_config
from tests.fake_site import TEST_MARKETPLACE_SIGNER
from tests.introduction_deals import publish
from tests.loopback import serving
from tests.publication_app import BUYER_SIGNER, pool, publication_app, settlement_clause

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


def _as_published(world, listing: dict) -> dict:
    """The storefront's listing beside its signed publication and trust, as a
    registry returns them. A storefront's local listing alone cannot prove a
    published rate."""
    return {**listing, **_registry_listing(world, listing["listing_id"])}


def _registry_listing(world, listing_id: str) -> dict:
    """The body the storefront published, with nothing of its local listing,
    beside the seller-signed publication proof and publisher trust a registry
    keeps for it. The proof is signed here with the seller's key, standing for
    the registry's retained copy of the storefront's signed request."""
    publication = world.registries.to("publish", listing_id)[0][1]
    request = sign_request(signer=TEST_MARKETPLACE_SIGNER, envelope=RequestEnvelope(
        principal=TEST_MARKETPLACE_SIGNER.identity, role="seller", method="POST",
        operation="listing.publish", resource="listings",
        request_id="buyer-selection-publication", timestamp=1_793_966_340,
        body_hash=canonical_body_hash(publication),
    ))
    return {
        **publication,
        "publisher_principals": TrustedIdentitySet(
            identities=(TEST_MARKETPLACE_SIGNER.identity,)
        ).model_dump(mode="json"),
        "publisher_publication": {
            "body_base64": base64.b64encode(json.dumps(publication).encode()).decode(),
            "request": request.model_dump(mode="json"),
        },
    }


@contextlib.asynccontextmanager
async def _priced_alkahest_world(tmp_path, monkeypatch, *, shape_priced: bool):
    """An unbacked pool publishing two priced Alkahest options, shape-priced from
    the pool's family rates when ``shape_priced``, beside the buyer's configured
    chain. Yields the world and the storefront's published listing, with the
    settings its negotiation reads in force."""
    book = json.loads(anvil_address_book_path().read_text())
    # Deterministic local contract fixture; never used on a public network.
    book["arbiters_addresses"]["erc20_splitter"] = "0x" + "44" * 20
    address_book = tmp_path / "alkahest.json"
    address_book.write_text(json.dumps(book))
    _buyer_chain(tmp_path, monkeypatch, address_book)
    async with publication_app(
        tmp_path, mechanism_fulfillment=_ALKAHEST_PUBLISHABLE, negotiation=True
    ) as world:
        pricing = ({"gpu": {"H100": {"rates": [{
            "asset": "0x" + "22" * 20, "rate": "100", "per": "hour",
        }]}}} if shape_priced else {})
        clause = settlement_clause()
        if shape_priced:
            clause.pop("rate")
            clause.pop("per")
        world.set_settlement_clauses([clause])
        world.pools.append(pool("broker-a", backing="unbacked", pricing=pricing))
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
        with (
            settings_overrides(**{"capacity.hold_ttl_seconds": 900}),
            replaced_setting("settlement", configured),
        ):
            yield world, listing


def _alkahest_options(listing: dict) -> list[dict]:
    return [
        option
        for option in listing["settlement_options"]
        if option["settlement"]["schema"] == "alkahest.v1"
    ]


def _interruptible_selection(listing: dict) -> SelectedSettlementOption:
    """The buyer's selection of the listing's interruptible Alkahest option."""
    option = SettlementOption.model_validate(_alkahest_options(listing)[1])
    return SelectedSettlementOption(
        option=option,
        selection=SettlementSelection(
            option_id=option.option_id,
            settlement={"schema": option.settlement_schema},
            expiration_unix=1_900_000_000,
        ),
        registration=buyer_settlement_registry().registration(option.settlement_schema),
    )


def _negotiate(
    base_url: str, listing: dict, selected: SelectedSettlementOption, *,
    opening: int | None = None, **kwargs,
):
    """The production buyer client's negotiation of ``selected`` for one hour, up
    to its listed hourly rate, opening at ``opening`` or at that rate."""
    option = selected.option
    hourly = int(option.price_rates[0].value)
    return negotiate_with_seller(
        seller_url=base_url,
        principal=BUYER_SIGNER.identity,
        signer=BUYER_SIGNER,
        listing_id=listing["listing_id"],
        listing=listing,
        resolve_seller_principals=lambda: TrustedIdentitySet(
            identities=(TEST_MARKETPLACE_SIGNER.identity,)
        ),
        initial_price=opening if opening is not None else hourly,
        max_price=hourly,
        provision_terms=make_vm_provision_terms(duration_seconds=3600, ssh_public_key=""),
        settlement_selection=selected.selection,
        policy_params={"_selected_settlement_option": option.model_dump(mode="json")},
        # As `market negotiate` does: the selected entry checks the plan the
        # seller materializes from its selection.
        validate_advertised_plan=buyer_stage(option.settlement_schema).plan_validator(
            listing, selected
        ),
        max_rounds=10,
        **kwargs,
    )


@pytest.mark.parametrize("shape_priced", [False, True])
async def test_a_buyer_selection_of_a_priced_alkahest_option_reaches_acceptance(
    tmp_path, monkeypatch, shape_priced
) -> None:
    async with _priced_alkahest_world(
        tmp_path, monkeypatch, shape_priced=shape_priced,
    ) as (world, listing):
        if shape_priced:
            listing = _as_published(world, listing)
        raw_options = _alkahest_options(listing)
        assert len(raw_options) == 2
        assert len({option["option_id"] for option in raw_options}) == 2
        assert all("lifecycle" not in option for option in raw_options)
        assert "interruptible" not in listing["listing_resource"]
        assert "oracle" in raw_options[1]["settlement"]["accepted_escrow"]["demand"]["demand_data"]
        selected = _interruptible_selection(listing)
        option = selected.option
        hourly = int(option.price_rates[0].value)
        assert bool(listing.get("rate_structure")) == shape_priced
        rounds: list[tuple[int, str | None]] = []

        with serving(world.app) as base_url:
            outcome = await asyncio.to_thread(lambda: _negotiate(
                base_url, listing, selected,
                on_round=lambda number, ours, theirs: rounds.append(
                    (number, theirs.get("action"))
                ),
            ))

    assert outcome.status == "agreed", outcome
    assert outcome.agreed_amount == hourly
    assert outcome.negotiated_scalar == (10000 if shape_priced else hourly)
    assert outcome.settlement_selection.option_id == option.option_id
    assert outcome.accepted_escrow_proposal is not None
    assert rounds[-1][1] == "accept"


def _signed_replies(evidence) -> list[dict]:
    return [json.loads(item.body) for item in evidence.items if item.kind == "signed_response"]


async def test_the_signed_pricing_pin_binds_the_registry_publication_at_acceptance_and_on_resume(
    tmp_path, monkeypatch,
) -> None:
    """A registry serves a shape-priced listing's family rates only in its signed
    ``pricing`` object. The buyer lifts them into its record and opens below the
    seller's floor; the served seller names the published structure's digest on
    every round and pins the multiplier with it in its signed acceptance, which the
    production buyer client verifies as it accepts. The record the buyer
    keeps at acceptance verifies again from the archived exchange, as a resumed
    run does; a changed pin is refused, and a record that kept no publication
    proof fails closed."""
    monkeypatch.setenv(PROFILE_STORE_ENV, str(tmp_path / "profiles" / "profiles.json"))
    async with _priced_alkahest_world(tmp_path, monkeypatch, shape_priced=True) as (world, served):
        published = _registry_listing(world, served["listing_id"])
        listing = domain_listing_record(published)
        selected = _interruptible_selection(listing)
        hourly = int(selected.option.price_rates[0].value)
        with serving(world.app) as base_url:
            outcome = await asyncio.to_thread(lambda: _negotiate(
                base_url, listing, selected, opening=hourly * 9 // 10,
                capture=evidence_store().capture,
            ))
    evidence = await evidence_store().read(outcome.agreement.negotiation_id)

    assert "rate_structure" not in published
    digest = rate_structure_digest({"rate_structure": published["pricing"]["rate_structure"]})
    assert outcome.status == "agreed", outcome
    replies = _signed_replies(evidence)
    assert [reply["action"] for reply in replies][-1] == "accept"
    assert "counter" in [reply["action"] for reply in replies]
    assert {reply["rate_structure_digest"] for reply in replies} == {digest}
    accepted = replies[-1]
    multiplier = outcome.negotiated_scalar
    assert accepted["pricing_pin"] == {"multiplier": str(multiplier), "rate_structure_digest": digest}

    record = accepted_listing_record({**listing, "_selected_settlement": selected}, None)
    project = buyer_settlement_registry().project_billing
    verify_recovered_pricing(
        record, outcome.agreement, outcome.agreement_bytes, evidence, project_billing=project,
    )
    with pytest.raises(ValueError, match="signed pricing multiplier differs from transcript"):
        verify_pricing_acceptance(
            record, outcome.agreement,
            {**accepted, "pricing_pin": {**accepted["pricing_pin"], "multiplier": str(multiplier - 1)}},
            multiplier=multiplier, project_billing=project,
        )
    legacy = {key: value for key, value in record.items() if not key.startswith("publisher_")}
    with pytest.raises(ValueError, match="requires retained seller publication proof"):
        verify_recovered_pricing(
            legacy, outcome.agreement, outcome.agreement_bytes, evidence, project_billing=project,
        )
