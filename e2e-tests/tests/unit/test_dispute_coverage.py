"""The delivery allowance and dispute coverage payment scenarios state and expect.

PAYMENTS.DISPUTE_WINDOW_SECONDS names it; a run naming none keeps the default
every lane states. Whatever it is, the settlement a VM listing states carries
it, and each purchase driver's option check expects it. VM delivery allowance
also follows its named setting. Every value below is a
development fixture, never used on any network.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
from market_arkhai_payments import ArkhaiPaymentsPublicationInput
from market_core.schemas import RateValue

from tests.e2e.roles.helpers import payments
from tests.e2e.roles.scenarios.bare_metal.compute_deal_driver import BareMetalComputeDealDriver
from tests.e2e.roles.scenarios.vms import test_vm_payment_deal as hosted_deal
from tests.e2e.roles.scenarios.bare_metal.purchase_driver import (
    DELIVERY_DEADLINE_SECONDS as BARE_METAL_DELIVERY_DEADLINE,
    BareMetalPurchaseDriver,
)
from tests.e2e.roles.scenarios.vms.composed_listing import (
    DELIVERY_DEADLINE_SECONDS as VM_DELIVERY_DEADLINE,
    payments_settlement,
)
from tests.e2e.roles.scenarios.vms.real_purchase_driver import RealVmPurchaseDriver

Failed = pytest.fail.Exception

#: A short coverage: the 300-second delivery deadline plus an authority's
#: 60-second minimum filing window.
SHORT = 360
#: A payee account that names no real account; never use it on a network.
SELLER_ACCOUNT = "00000000-0000-4000-8000-0000000000b2"


class _Settings:
    def __init__(self, values: dict[str, Any]) -> None:
        self._values = {f"PAYMENTS.{key}": value for key, value in values.items()}

    def get(self, key: str, default: object = None) -> object:
        return self._values.get(key, default)


@pytest.fixture
def configure(monkeypatch):
    def _configure(**values: Any) -> None:
        monkeypatch.setattr(payments, "settings", _Settings(values))

    return _configure


def _coverage() -> int:
    return payments.dispute_window_seconds(delivery_deadline_seconds=300)


@pytest.mark.parametrize("values", [{}, {"DISPUTE_WINDOW_SECONDS": ""},
                                    {"DISPUTE_WINDOW_SECONDS": None}])
def test_a_run_naming_no_coverage_keeps_the_default(configure, values) -> None:
    configure(**values)
    assert _coverage() == payments.DEFAULT_DISPUTE_WINDOW_SECONDS == 15 * 86400


@pytest.mark.parametrize("value", [SHORT, "360", " 360 ", 300])
def test_a_named_coverage_covering_the_delivery_deadline_is_taken(configure, value) -> None:
    configure(DISPUTE_WINDOW_SECONDS=value)
    assert _coverage() == int(str(value).strip())


@pytest.mark.parametrize("value", [True, 360.0, "P7D", "-1", -1, 299, "3.6e2"])
def test_a_coverage_that_is_not_an_integer_or_short_of_the_deadline_fails(configure, value) -> None:
    configure(DISPUTE_WINDOW_SECONDS=value)
    with pytest.raises(Failed, match="PAYMENTS.DISPUTE_WINDOW_SECONDS must be an integer"):
        _coverage()


@pytest.mark.parametrize(("values", "expected"), [
    ({}, 15 * 86400), ({"DISPUTE_WINDOW_SECONDS": SHORT}, SHORT),
])
def test_a_vm_listings_payments_settlement_states_the_runs_coverage(
    configure, values, expected,
) -> None:
    configure(**values)
    settlement = payments_settlement(seller_account=SELLER_ACCOUNT, dispute_window="P7D")
    clause = ArkhaiPaymentsPublicationInput.model_validate(settlement["mechanism_input"])
    assert (clause.dispute_window_seconds, clause.delivery_deadline_seconds) == (
        expected, VM_DELIVERY_DEADLINE)


def _option_for(mechanism_input: dict[str, Any]) -> SimpleNamespace:
    """The payments option a listing publishes for ``mechanism_input``, as the
    drivers' checks read it."""
    return SimpleNamespace(
        settlement_params={"window": mechanism_input["window"]},
        lifecycle={
            "adjudication": {
                "dispute_window_seconds": mechanism_input["dispute_window_seconds"],
                "case_hold_max_seconds": mechanism_input.get("case_hold_max_seconds"),
            },
            "delivery_deadline_seconds": mechanism_input["delivery_deadline_seconds"],
        },
        price_asset="USD/6",
        price_rates=[RateValue(field="amount", per="hour", value=1_000_000)],
    )


def _vm_driver() -> RealVmPurchaseDriver:
    driver = object.__new__(RealVmPurchaseDriver)
    driver.dispute_window = "P7D"
    return driver


def test_the_vm_purchase_expects_the_coverage_its_listing_stated(configure) -> None:
    configure(DISPUTE_WINDOW_SECONDS=SHORT)
    option = _option_for(payments_settlement(
        seller_account=SELLER_ACCOUNT, dispute_window="P7D")["mechanism_input"])
    _vm_driver().check_payments_option(option)


def test_the_vm_purchase_refuses_an_option_stating_another_coverage(configure) -> None:
    configure()
    stated = payments_settlement(seller_account=SELLER_ACCOUNT, dispute_window="P7D")
    configure(DISPUTE_WINDOW_SECONDS=SHORT)
    with pytest.raises(AssertionError):
        _vm_driver().check_payments_option(_option_for(stated["mechanism_input"]))


@pytest.mark.parametrize("value", [900, "900", " 900 "])
def test_the_vm_listing_and_purchase_use_the_configured_delivery_allowance(
    configure, value,
) -> None:
    configure(VM_DELIVERY_DEADLINE_SECONDS=value, DISPUTE_WINDOW_SECONDS=960)
    settlement = payments_settlement(seller_account=SELLER_ACCOUNT, dispute_window="P7D")
    clause = ArkhaiPaymentsPublicationInput.model_validate(settlement["mechanism_input"])
    assert clause.delivery_deadline_seconds == 900
    _vm_driver().check_payments_option(_option_for(settlement["mechanism_input"]))


@pytest.mark.parametrize("value", [True, False, 0, -1, 900.0, "P15M", "-1", "9e2"])
def test_the_vm_listing_refuses_an_invalid_delivery_allowance(configure, value) -> None:
    configure(VM_DELIVERY_DEADLINE_SECONDS=value)
    with pytest.raises(Failed, match="PAYMENTS.VM_DELIVERY_DEADLINE_SECONDS"):
        payments_settlement(seller_account=SELLER_ACCOUNT, dispute_window="P7D")


def test_the_vm_purchase_refuses_an_option_with_another_delivery_allowance(configure) -> None:
    configure(VM_DELIVERY_DEADLINE_SECONDS=900, DISPUTE_WINDOW_SECONDS=960)
    option = _option_for({"window": "P7D", "dispute_window_seconds": 960,
                          "delivery_deadline_seconds": 300})
    with pytest.raises(AssertionError):
        _vm_driver().check_payments_option(option)


def test_the_vm_listing_refuses_coverage_shorter_than_its_delivery_allowance(configure) -> None:
    configure(VM_DELIVERY_DEADLINE_SECONDS=900, DISPUTE_WINDOW_SECONDS=SHORT)
    with pytest.raises(Failed, match="covering the 900-second delivery deadline"):
        payments_settlement(seller_account=SELLER_ACCOUNT, dispute_window="P7D")


def test_the_hosted_vm_deal_publishes_the_same_configured_delivery_allowance(configure) -> None:
    configure(VM_DELIVERY_DEADLINE_SECONDS=900, DISPUTE_WINDOW_SECONDS=960,
              SELLER_ACCOUNT=SELLER_ACCOUNT)

    class Published(Exception):
        pass

    def publish(**request):
        (settlement,) = request["settlements"]
        clause = ArkhaiPaymentsPublicationInput.model_validate(settlement["mechanism_input"])
        assert clause.delivery_deadline_seconds == 900
        assert clause.dispute_window_seconds == 960
        raise Published

    with pytest.raises(Published):
        hosted_deal.test_hosted_commit_delivers_after_a_verified_receipt(
            payments_config=None, hosted={}, deal_driver=SimpleNamespace(seed_supply=lambda: None),
            deal_state=None, storefront_seller_client=SimpleNamespace(create_listing=publish),
            storefront_client=None, storefront_admin_client=None, registry_client=None,
            provisioning_client=None, provisioning_test_client=None, site_capacity=None,
        )


@pytest.mark.parametrize(("values", "expected"), [
    ({}, 300), ({"VM_DELIVERY_DEADLINE_SECONDS": 900}, 900),
    ({"VM_DELIVERY_DEADLINE_SECONDS": 60}, 300),
])
def test_the_vm_buyer_waits_at_least_its_configured_delivery_allowance(
    configure, values, expected,
) -> None:
    configure(**values)
    driver = _vm_driver()
    # An inert development marker, never an SSH key used on a network.
    driver.buyer_public_key = "development-public-key"
    arguments = driver.buy_arguments("development-listing", "development-option")
    assert arguments[arguments.index("--settlement-timeout") + 1] == str(expected)


def test_the_bare_metal_lane_pool_override_states_the_runs_coverage(
    configure, monkeypatch,
) -> None:
    # The canonical deal's own supply is the lane's, and not what is checked here.
    monkeypatch.setattr(BareMetalComputeDealDriver, "seed_supply", lambda self: None)
    written: list[dict[str, Any]] = []
    driver = object.__new__(BareMetalPurchaseDriver)
    driver.site_id, driver.pool_id = "site", "pool"
    driver.seller_account, driver.dispute_window = SELLER_ACCOUNT, "P7D"
    driver.pool_overrides = SimpleNamespace(put_pool_override=written.append)
    configure(DISPUTE_WINDOW_SECONDS=SHORT)
    driver.seed_supply()
    ((override,),) = [entry["settlements"] for entry in written]
    clause = ArkhaiPaymentsPublicationInput.model_validate(override["mechanism_input"])
    assert (clause.dispute_window_seconds, clause.delivery_deadline_seconds) == (
        SHORT, BARE_METAL_DELIVERY_DEADLINE)


@pytest.mark.parametrize(("values", "stated", "accepted"), [
    ({"DISPUTE_WINDOW_SECONDS": SHORT}, SHORT, True),
    ({}, 15 * 86400, True),
    ({"DISPUTE_WINDOW_SECONDS": SHORT}, 15 * 86400, False),
])
def test_the_bare_metal_lane_purchase_expects_the_runs_coverage(
    configure, values, stated, accepted,
) -> None:
    configure(**values)
    driver = object.__new__(BareMetalPurchaseDriver)
    driver.dispute_window = "P7D"
    driver.storefront_pins = "pins"
    option = _option_for({"window": "P7D", "dispute_window_seconds": stated,
                          "delivery_deadline_seconds": BARE_METAL_DELIVERY_DEADLINE})
    listing = SimpleNamespace(settlement_options=[option], publisher_principals="pins",
                              listing_resource={"capacity_backing": "backed"})
    if accepted:
        driver.check_purchase_option(listing, option)
        return
    with pytest.raises(AssertionError):
        driver.check_purchase_option(listing, option)
