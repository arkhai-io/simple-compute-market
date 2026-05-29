from __future__ import annotations

import csv
from decimal import Decimal
from importlib import resources


MOCK_TOKEN = "0x9fe46736679d2d9a65f0992f2272de9f3c7fa6e0"
MOCK_TOKEN_DECIMALS = 18
ALKAHEST_PY_ERC20_VALUE_MAX = 2**64 - 1


def _inventory_rows(name: str) -> list[dict[str, str]]:
    with resources.files("market_storefront.data").joinpath(name).open(
        newline="", encoding="utf-8"
    ) as handle:
        return list(csv.DictReader(handle))


def test_bundled_mock_inventory_prices_fit_one_hour_escrow_value_limit():
    """The README one-hour mock buy path must fit current alkahest_py.

    The SDK binding currently extracts ERC20 payment values as uint64-like
    integers. These public MOCK inventory files are the default dev/demo
    inputs, so their one-hour scaled prices need to stay inside that range.
    """
    files = [
        "btc1-machine.csv",
        "kvm1-machine.csv",
        "resources.sample.csv",
    ]

    checked = []
    for filename in files:
        for row in _inventory_rows(filename):
            if (row.get("token") or "").lower() != MOCK_TOKEN:
                continue
            min_price = row.get("min_price")
            if min_price in (None, ""):
                continue
            scaled = Decimal(min_price) * (Decimal(10) ** MOCK_TOKEN_DECIMALS)
            checked.append((filename, row["resource_id"], int(scaled)))

    assert checked
    for filename, resource_id, scaled in checked:
        assert scaled <= ALKAHEST_PY_ERC20_VALUE_MAX, (
            f"{filename}:{resource_id} publishes {scaled}, which overflows "
            "alkahest_py Erc20Data.value during the documented one-hour buy"
        )
