"""A per-period Agreement at the VM buyer's last two money reads before approval.

The accepted-pricing check, which a resumed run repeats over its retained
evidence, recomputes one period's quote from the seller-signed publication and
the signed multiplier; the confirmation shows the accepted amount with its unit.
Neither scales a period's price by the horizon.
"""

from __future__ import annotations

import base64
import json
from io import StringIO

import pytest
from arkhai_vms import make_vm_provision_terms
from arkhai_vms_negotiation.amounts import rate_structure_digest
from market_core.schemas import AgreedPrice, Agreement, PriceBasis, SettlementOption, derive_settlement_option_id
from market_identity import RequestEnvelope, canonical_body_hash, sign_request
from rich.console import Console
from typer.testing import CliRunner

from arkhai_vms_buyer.arkhai_payments import AgreedTerms
from arkhai_vms_buyer.buy_cli import _confirm_settlement_interactive
from arkhai_vms_buyer.pricing_record import verify_pricing_acceptance
from identity_helpers import BUYER_SIGNER, SELLER_SIGNER, SELLER_TRUST
from test_negotiation_amounts import HOURLY, RATE_STRUCTURE, TOKEN, shape_priced_listing

QUARTER_HOUR = PriceBasis(unit="per_period", period="PT15M", period_seconds=900)
#: 1,000 an hour for the advertised shape is 250 a quarter-hour period.
PERIOD_PRICE = 250
#: Two days: a reader taking the period price for an hourly rate, or scaling it
#: by the horizon's periods, would ask for 192 times as much.
HORIZON = 172_800


def _rate_option() -> dict:
    body = {
        "price": {"asset": TOKEN, "rates": [{"field": "amount", "per": "hour", "value": str(HOURLY)}]},
        "settlement": {"schema": "fixture.rate.v1", "period": "PT15M"},
    }
    return {"option_id": derive_settlement_option_id(**body), **body}


def _signed_record() -> dict:
    """The record a VM buyer retains: the listing beside its seller-signed publication."""
    listing = shape_priced_listing()
    listing["settlement_options"] = [_rate_option()]
    listing["pricing"] = {"rate_structure": RATE_STRUCTURE}
    publication = {key: listing[key] for key in (
        "listing_id", "storefront_url", "listing_resource", "pricing", "settlement_options",
    )}
    request = sign_request(signer=SELLER_SIGNER, envelope=RequestEnvelope(
        principal=SELLER_SIGNER.identity, role="seller", method="POST", operation="listing.publish",
        resource="listings", request_id="per-period-publication", timestamp=1_793_966_340,
        body_hash=canonical_body_hash(publication),
    ))
    return {
        **listing,
        "publisher_principals": SELLER_TRUST.model_dump(mode="json"),
        "publisher_publication": {
            "body_base64": base64.b64encode(json.dumps(publication).encode()).decode(),
            "request": request.model_dump(mode="json"),
        },
    }


def _agreement(record: dict, amount: int) -> Agreement:
    return Agreement(
        negotiation_id="neg-1", listing_id=record["listing_id"], listing_hash="0" * 64,
        buyer=BUYER_SIGNER.identity.model_dump(mode="json"),
        seller=SELLER_SIGNER.identity.model_dump(mode="json"),
        settlement=SettlementOption.model_validate(record["settlement_options"][0]),
        amount=amount, asset=TOKEN, duration_seconds=HORIZON,
        start_utc="2026-11-12T00:00:00Z", accepted_at="2026-11-12T00:00:00Z",
        # The buyer named no horizon; the seller resolved it into the Agreement.
        provision_terms=make_vm_provision_terms(
            duration_seconds=None, ssh_public_key="",
        ).model_dump(mode="json"),
    )


def _accepting_reply(record: dict) -> dict:
    digest = rate_structure_digest(record)
    return {
        "action": "accept", "rate_structure_digest": digest,
        "pricing_pin": {"rate_structure_digest": digest, "multiplier": "10000"},
    }


def test_accepted_per_period_money_matches_one_signed_period_quote():
    record = _signed_record()
    verify_pricing_acceptance(
        record, _agreement(record, PERIOD_PRICE), _accepting_reply(record),
        multiplier=10_000, project_billing=lambda _option: QUARTER_HOUR,
    )


@pytest.mark.parametrize("amount", [PERIOD_PRICE * 192, HOURLY, PERIOD_PRICE + 1])
def test_accepted_money_off_one_period_s_quote_is_refused(amount):
    record = _signed_record()
    with pytest.raises(ValueError, match="accepted monetary amount differs from authenticated pricing"):
        verify_pricing_acceptance(
            record, _agreement(record, amount), _accepting_reply(record),
            multiplier=10_000, project_billing=lambda _option: QUARTER_HOUR,
        )


def test_a_period_s_price_read_as_a_whole_term_total_is_refused():
    # The mechanism's projection decides the unit: read as a total, one period's
    # price is short of the whole horizon's quote, and the check refuses it.
    record = _signed_record()
    with pytest.raises(ValueError, match="accepted monetary amount differs from authenticated pricing"):
        verify_pricing_acceptance(
            record, _agreement(record, PERIOD_PRICE), _accepting_reply(record),
            multiplier=10_000, project_billing=lambda _option: PriceBasis(unit="total"),
        )


def _confirmation(terms: AgreedTerms) -> str:
    """The panel shown before settlement, the buyer declining at the prompt.

    The decline is typed on the isolated standard input Click's test runner
    gives the prompt; the test itself replaces no name.
    """
    output = StringIO()
    with CliRunner().isolation(input="n\n"):
        assert not _confirm_settlement_interactive(
            terms=terms, listing={}, console=Console(file=output, width=160, color_system=None),
        )
    return output.getvalue()


def test_the_confirmation_shows_one_period_s_charge_unscaled():
    quote = AgreedPrice(**QUARTER_HOUR.model_dump(), amount=PERIOD_PRICE, asset=TOKEN)
    shown = _confirmation(AgreedTerms(
        "https://seller.invalid", "", "neg-1", "L-shape", PERIOD_PRICE, HORIZON, quote,
    ))
    assert "250 (per_period (PT15M), raw token units)" in shown
    assert "Period charge" in shown and "Total payment" not in shown
    assert "172800s (48h)" in shown
    assert str(PERIOD_PRICE * 192) not in shown and str(PERIOD_PRICE * 48) not in shown


def test_the_confirmation_shows_a_whole_term_total_unscaled():
    quote = AgreedPrice(unit="total", amount=2000, asset=TOKEN)
    shown = _confirmation(AgreedTerms("https://seller.invalid", "", "neg-1", "L-shape", 2000, 7200, quote))
    assert "2000 (total, raw token units)" in shown
    assert "Total payment" in shown
    assert "4000" not in shown
