"""Public deterministic dispute terms for the API-credit buyer's fixtures."""

from market_arkhai_mediation.contract import INTERFACE
from market_arkhai_payments.fixtures import dispute_lifecycle
from market_deal_lifecycle.configuration import DisputeEntry


def lifecycle():
    value = dispute_lifecycle("33333333-3333-4333-8333-333333333333")
    value["adjudication"]["dispute"]["interface"] = INTERFACE
    return value


def authority():
    return DisputeEntry.model_validate({
        **lifecycle()["adjudication"]["dispute"],
        "advertisement": {"mechanisms": ["arkhai.payments.v1"],
                          "minimum_dispute_window_seconds": 0,
                          "minimum_case_hold_seconds": None},
    })
