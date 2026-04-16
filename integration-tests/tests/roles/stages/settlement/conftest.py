"""Settlement stage fixtures.

The ``settlement_output`` fixture (defined in parent stages/conftest.py)
waits for both orders to have escrow_uid set and status=accepted. This
file exists for settlement-specific overrides.
"""
