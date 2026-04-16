"""Negotiation stage fixtures.

The ``negotiation_output`` fixture (defined in parent stages/conftest.py)
waits for both sides' negotiation threads to reach terminal_state=success.
This file exists for negotiation-specific overrides — e.g. a variant
that exits instead of agreeing, or one that runs until round cap.
"""
