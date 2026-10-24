"""The payment stage's validators, servicing, reconciliation loop, and refusals, over injected collaborators."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from arkhai_api.labels import IssuanceLabel
from arkhai_api_selling.contributions import ConsumptionRule, IssuanceSubject, SellingContributions
from arkhai_api_selling.issuance import SettlementRefusal
from market_arkhai_payments import ARKHAI_PAYMENTS_MECHANISM, ArkhaiPaymentsConfig
from market_identity import Ed25519Signer
from market_negotiation_runtime import OfferUnfulfillableError
from market_storefront_kit import LifecycleRouteError
from pydantic import BaseModel

from arkhai_api_selling_arkhai_payments.stage import PAYMENT_RECONCILIATION, ArkhaiPaymentsSellerStage
from arkhai_api_selling_arkhai_payments.validators import (
    validate_payer_account,
    validate_payment_publication_clause,
)

# A deterministic development key and placeholder accounts for these tests only.
SERVICE = Ed25519Signer(bytes(range(32)))
PAYER = "11111111-1111-4111-8111-111111111111"
PAYEE = "22222222-2222-4222-8222-222222222222"
DISPUTE = "33333333-3333-4333-8333-333333333333"


class _Listing(BaseModel):
    listing_resource: dict


EXAMPLE = SellingContributions(
    label=IssuanceLabel("example"),
    kind="example.v1",
    offering_mode="example",
    contribution_id="example",
    table_prefix="example",
    listing_schema=_Listing,
    publication_mapping=lambda request, source: {},
    issuance_projection=lambda resource: IssuanceSubject(service="", resource_id=None, endpoint=None),
    consumption_rule=ConsumptionRule.FIXED_PER_REQUEST,
    refusal_noun="Example",
)


def _stage(**collaborators) -> ArkhaiPaymentsSellerStage:
    defaults = {
        "fulfils_through_capacity": True,
        "capacity": None,
        "hold_ttl_seconds": lambda: 0,
        "composition": lambda: None,
        "sqlite_client": lambda: None,
        "reconciliation_interval": lambda: 45,
        "stage_event": lambda *a, **k: None,
    }
    return ArkhaiPaymentsSellerStage(EXAMPLE, **{**defaults, **collaborators})


def _config(*, enabled: bool, servicing: bool = True):
    section = ArkhaiPaymentsConfig(
        enabled=enabled,
        service_url="http://127.0.0.1:9" if servicing else None,
        service_identity=SERVICE.identity if servicing else None,
        fee_bps=250, dispute_authority=DISPUTE, development_auth=True,
    )
    return SimpleNamespace(mechanism_config=lambda _key: section)


def test_a_payer_account_is_an_account_id():
    assert validate_payer_account(PAYER) == PAYER
    with pytest.raises(ValueError):
        validate_payer_account("not-an-account")


def test_a_publication_clause_states_an_integer_rate_per_credit():
    clause = {"mechanism": ARKHAI_PAYMENTS_MECHANISM, "asset": "USD/2", "per": "credit", "rate": "100",
              "mechanism_input": {"payee_account": PAYEE}}
    assert validate_payment_publication_clause(clause, noun="Example").rate == "100"

    with pytest.raises(ValueError, match="^Example payment rate must be integer base units per credit$"):
        validate_payment_publication_clause({**clause, "rate": "1.5"}, noun="Example")


def test_a_selection_states_exactly_a_valid_payer_account():
    stage = _stage()
    stage.validate_selection(SimpleNamespace(params={"payer_account": PAYER}))

    with pytest.raises(OfferUnfulfillableError, match="payments_payer_account_missing"):
        stage.validate_selection(SimpleNamespace(params={}))
    with pytest.raises(OfferUnfulfillableError, match="payments_payer_account_invalid"):
        stage.validate_selection(SimpleNamespace(params={"payer_account": "nope"}))


@pytest.mark.parametrize("enabled", [True, False])
def test_accepted_deals_are_serviced_whether_or_not_new_options_publish(enabled):
    assert _stage().servicing(_config(enabled=enabled)) is not None
    assert _stage().servicing(_config(enabled=enabled, servicing=False)) is None


def test_the_reconciliation_loop_is_contributed_only_while_payments_is_serviced():
    db = object()
    serviced = SimpleNamespace(servicing={ARKHAI_PAYMENTS_MECHANISM: object()}, contributions=EXAMPLE)
    unserviced = SimpleNamespace(servicing={}, contributions=EXAMPLE)

    assert _stage().contributed_loops() == ()
    assert _stage(composition=lambda: unserviced, sqlite_client=lambda: db).contributed_loops() == ()
    (loop,) = _stage(composition=lambda: serviced, sqlite_client=lambda: db).contributed_loops()
    assert (loop.name, loop.route, loop.interval_seconds) == (
        PAYMENT_RECONCILIATION, "payment-reconciliation", 45,
    )
    assert _stage().startup_steps() == () and _stage().health_checks() == {}


async def test_reconciliation_before_persistence_refuses_and_without_payments_attempts_nothing():
    composition = SimpleNamespace(servicing={}, contributions=EXAMPLE)

    with pytest.raises(LifecycleRouteError):
        _stage(composition=lambda: composition).contributed_loops()
    assert await _stage().reconciliation_step() == {
        "loop": PAYMENT_RECONCILIATION, "attempted": 0, "failed": 0,
    }


async def test_without_payments_servicing_settlement_refuses_and_refund_is_skipped():
    stage = _stage()
    composition = SimpleNamespace(servicing={}, contributions=EXAMPLE)
    body = SimpleNamespace(negotiation_id="neg-1", buyer_principal=SERVICE.identity)

    with pytest.raises(SettlementRefusal) as refused:
        await stage.settle(db=object(), composition=composition, reference="neg-1", body=body,
                           signer=SERVICE)
    assert (refused.value.status_code, refused.value.detail) == (503, "Arkhai payments is not enabled")
    with pytest.raises(SettlementRefusal) as keyed:
        await stage.settle(db=object(), composition=composition, reference="0xother", body=body,
                           signer=SERVICE)
    assert keyed.value.status_code == 400
    assert await stage.refund_before_delivery(db=object(), composition=composition, negotiation_id="neg-1") == {
        "action": "refund", "status": "skipped", "reason": "payments_unavailable",
    }
    with pytest.raises(ValueError, match="not enabled"):
        stage.agreement_artifacts({}, composition)
