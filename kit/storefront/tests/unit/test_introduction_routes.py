"""A deal its stage completes outside settlement is refused settle and fulfillment."""

from __future__ import annotations

import pytest

from market_storefront_kit import (
    LifecycleRouteError,
    refuse_introduction_fulfillment,
    refuse_introduction_settle,
)

REASON = "a contact exchange completes by introduction, not settlement"


@pytest.mark.parametrize(
    ("refuse", "status_code"),
    [(refuse_introduction_settle, 409), (refuse_introduction_fulfillment, 404)],
    ids=["settle", "fulfillment"],
)
def test_a_stage_completing_outside_settlement_is_refused_with_the_domains_reason(
    refuse, status_code
):
    with pytest.raises(LifecycleRouteError) as refused:
        refuse(completes_outside_settlement=True, reason=REASON)

    assert refused.value.status_code == status_code
    assert refused.value.detail == REASON


@pytest.mark.parametrize(
    "refuse", [refuse_introduction_settle, refuse_introduction_fulfillment]
)
def test_a_stage_that_settles_is_not_refused(refuse):
    assert refuse(completes_outside_settlement=False, reason=REASON) is None
