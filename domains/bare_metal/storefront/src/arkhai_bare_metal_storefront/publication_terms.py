"""Bare-metal clause precedence, shared by pool admission and payload building."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any


def pool_settlement_clauses(pool: Mapping[str, Any]) -> Any:
    """Read the bare-metal hint without treating malformed statements as absent."""
    metadata = pool.get("pool_metadata") or {}
    tags = metadata.get("policy_tags") or {}
    pricing = tags.get("pricing")
    if pricing is None:
        return None
    if not isinstance(pricing, Mapping):
        raise ValueError("pool pricing hint must be a mapping")
    terms = pricing.get("bare_metal")
    if terms is None:
        return None
    if not isinstance(terms, Mapping):
        raise ValueError("pool pricing.bare_metal hint must be a mapping")
    clauses = terms.get("settlements")
    if clauses is not None and not isinstance(clauses, list):
        raise ValueError("pool pricing.bare_metal.settlements must be a list")
    return clauses
