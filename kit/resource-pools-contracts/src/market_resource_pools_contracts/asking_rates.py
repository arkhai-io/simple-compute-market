"""Domain-neutral structural validation for per-shape asking-rate declarations."""

from __future__ import annotations

import re
from collections.abc import Mapping
from decimal import Decimal, InvalidOperation
from typing import Any

from market_capability_shape import shape_structure_problems

ASKING_RATES_POLICY_TAG = "asking_rates"

#: The settlement publication clause's decimal-text grammar: no sign, no
#: exponent, no leading zeros. Exact text, so a price survives every hop
#: without passing through binary floating point.
_DECIMAL_AMOUNT = re.compile(r"(?:0|[1-9][0-9]*)(?:\.[0-9]+)?")
#: The settlement clause's unit grammar, so a period is spelled as a published
#: settlement unit is.
_UNIT = re.compile(r"[a-z][a-z0-9_-]*")
_ENTRY_KEYS = frozenset({"shape", "amount", "asset", "period"})


def _amount_problem(value: Any) -> str | None:
    if not isinstance(value, str) or not _DECIMAL_AMOUNT.fullmatch(value):
        return "amount must be positive decimal text without a sign or an exponent"
    try:
        if Decimal(value) <= 0:
            return "amount must be positive decimal text without a sign or an exponent"
    except InvalidOperation:
        return "amount must be positive decimal text without a sign or an exponent"
    return None


def _token_problem(name: str, value: Any) -> str | None:
    if not isinstance(value, str) or not value or value != value.strip():
        return f"{name} must be a non-empty string without surrounding whitespace"
    return None


def asking_rate_entry_problems(entry: Any) -> list[str]:
    """Structural problems with one entry, independent of any domain.

    The shape is checked only as a well-formed family-grouped shape and the
    period only as a token; whether either means anything is the reading
    domain's to say.
    """
    if not isinstance(entry, Mapping):
        return ["must be a mapping with shape, amount, asset, and period"]
    problems: list[str] = []
    missing = sorted(_ENTRY_KEYS - set(entry))
    if missing:
        problems.append(f"missing {', '.join(missing)}")
    unknown = sorted(str(key) for key in set(entry) - _ENTRY_KEYS)
    if unknown:
        problems.append(f"unknown {', '.join(unknown)}")
    if "shape" in entry:
        for problem in shape_structure_problems(entry["shape"]):
            where = f"shape.{problem.path}" if problem.path else "shape"
            problems.append(f"{where}: {problem.message}")
    if "amount" in entry and (problem := _amount_problem(entry["amount"])):
        problems.append(problem)
    if "asset" in entry and (problem := _token_problem("asset", entry["asset"])):
        problems.append(problem)
    if "period" in entry and (
        not isinstance(entry["period"], str) or not _UNIT.fullmatch(entry["period"])
    ):
        problems.append("period must be a canonical lowercase unit token")
    return problems


def validate_asking_rates(policy_tags: Mapping[str, Any]) -> list[str]:
    """Human-readable structural problems with a supplied ``asking_rates``.

    Empty means valid, including absent: the declaration is optional. A present
    value maps each offering mode to a list of entries. An empty list is
    accepted and prices nothing, as an absent mode does.
    """
    if ASKING_RATES_POLICY_TAG not in policy_tags:
        return []
    tag = ASKING_RATES_POLICY_TAG
    raw = policy_tags[tag]
    if not isinstance(raw, Mapping):
        return [f"{tag} must be a mapping of offering mode to a list of rates"]
    problems: list[str] = []
    for mode, entries in raw.items():
        if not isinstance(mode, str) or not mode:
            problems.append(f"{tag} offering modes must be non-empty strings, not {mode!r}")
            continue
        if not isinstance(entries, list):
            problems.append(f"{tag}.{mode} must be a list of rates")
            continue
        for index, entry in enumerate(entries):
            for problem in asking_rate_entry_problems(entry):
                problems.append(f"{tag}.{mode}[{index}]: {problem}")
    return problems


__all__ = [
    "ASKING_RATES_POLICY_TAG",
    "asking_rate_entry_problems",
    "validate_asking_rates",
]
