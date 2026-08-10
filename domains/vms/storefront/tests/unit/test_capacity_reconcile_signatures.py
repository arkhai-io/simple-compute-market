"""Every reconciler call supplies the arguments the reconciler requires.

The periodic full reconcile omitted `home_site` and `configured_site_count`, so
each poller cycle raised `TypeError` and was swallowed by the poller's
`except Exception` into a warning. The stack stayed up, the storefront's derived
listings stopped being reconciled against site capacity, and the symptom surfaced
several layers away as negotiations refusing with `no_matching_inventory`.

A static check rather than a behavioural one: the defect is a call-signature
mismatch on a path that only runs on a timer, and binding the signature is what
catches it before a stack does.
"""

from __future__ import annotations

import ast
import inspect
from pathlib import Path

import pytest

from market_storefront.services import capacity_client, publication_service

RECONCILERS = (
    "close_stale_compute_listings_after_capacity_change",
    "reopen_available_compute_listings_after_capacity_change",
)


def _required_keyword_only(name: str) -> set[str]:
    signature = inspect.signature(getattr(publication_service, name))
    return {
        param.name
        for param in signature.parameters.values()
        if param.kind is inspect.Parameter.KEYWORD_ONLY
        and param.default is inspect.Parameter.empty
    }


def _calls_in(module) -> list[tuple[int, str, set[str]]]:
    tree = ast.parse(Path(inspect.getsourcefile(module)).read_text(encoding="utf-8"))
    found = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        called = getattr(node.func, "id", None) or getattr(node.func, "attr", None)
        if called in RECONCILERS:
            found.append((node.lineno, called, {kw.arg for kw in node.keywords}))
    return found


@pytest.mark.parametrize("name", RECONCILERS)
def test_the_reconciler_has_required_keyword_only_arguments(name: str) -> None:
    """Guards the premise: if these become optional the test below is vacuous."""
    assert _required_keyword_only(name)


def test_every_reconciler_call_supplies_its_required_arguments() -> None:
    calls = _calls_in(capacity_client)
    assert calls, "no reconciler calls found — has the module moved?"

    missing = [
        f"{capacity_client.__name__}:{lineno} {called} missing "
        f"{sorted(_required_keyword_only(called) - kwargs)}"
        for lineno, called, kwargs in calls
        if _required_keyword_only(called) - kwargs
    ]

    assert not missing, "reconciler calls missing required arguments:\n" + "\n".join(
        missing
    )


def test_the_periodic_reconcile_and_the_delta_path_both_call_them() -> None:
    """Both paths must be covered: the defect was in the one that runs on a timer."""
    called_at = {called for _, called, _ in _calls_in(capacity_client)}

    for name in RECONCILERS:
        assert name in called_at
    assert len(_calls_in(capacity_client)) >= 4
