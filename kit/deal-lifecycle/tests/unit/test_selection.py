"""Authority selection keeps why it refused, for a buyer left with nothing."""

from __future__ import annotations

import pytest

from market_deal_lifecycle.configuration import NO_DISPUTE_AUTHORITIES
from market_deal_lifecycle.selection import AuthoritySelection
from market_deal_lifecycle.terms import TermContext


def test_each_distinct_refusal_is_kept_once_in_the_order_first_met():
    selection = AuthoritySelection({}, contexts={
        "hosted.v1": TermContext(mechanism="hosted.v1", has_adapter=True),
    })
    lifecycle = {"adjudication": {
        "version": 1,
        "dispute": {"interface": "example.dispute.v1", "origin": "https://dispute.example",
                    "account": "a", "record_key": "k", "params": {}},
        "dispute_window_seconds": 60, "case_hold_max_seconds": None,
    }}
    for value in (None, lifecycle, lifecycle):
        with pytest.raises(ValueError):
            selection.rank("hosted.v1", value)
    assert selection.rank("plain.v1", None) == 0
    assert list(selection.refusals) == [
        "a lifecycle adapter requires adjudication", NO_DISPUTE_AUTHORITIES,
    ]
