"""Second-precision lease reads retain historical minute-format compatibility."""

import pytest

import market_storefront.server  # noqa: F401 - controller composition order
from market_storefront.controllers.admin_controller import AdminController


@pytest.mark.parametrize("value,second", [
    ("2030-01-01 12:00", 0),
    ("2030-01-01 12:00:30", 30),
    ("2030-01-01T12:00:30Z", 30),
    ("2030-01-01T13:00:30+01:00", 30),
])
def test_recorded_lease_end_keeps_the_instant(value, second):
    assert AdminController._interrupt_time(value) == f"2030-01-01 12:00:{second:02d}"
