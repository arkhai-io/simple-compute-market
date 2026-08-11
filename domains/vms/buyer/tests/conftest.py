"""Test configuration for the VM buyer package.

These tests cover transport and orchestration, not negotiation strategy.

This module previously aliased the ``rl`` policy name to a cheap middleware so
that the global chain loader could resolve it without importing torch. That
alias is no longer needed, and could no longer work: names resolve against a
catalogue each caller composes, so a test that needs a policy offers it to its
own catalogue instead of mutating shared state that every other test inherits.
"""

from __future__ import annotations
