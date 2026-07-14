"""Contract fixtures for the ``_publish_round`` boundary.

``_publish_round`` (in ``market_storefront.cli_publish``) returns a tuple
``(published, failed, skipped)`` where:

- ``published`` is a list of entry dicts, each describing a successfully
  posted listing.
- ``failed`` is a list of ``(resource_dict, error_str)`` tuples, one per
  resource that could not be listed.
- ``skipped`` is a list of resource dicts that were intentionally skipped
  (e.g. already covered by an open listing).

The functions here define the canonical shapes of *published entry* and
*failed item* and are shared between:

- ``test_cli_publish_helpers.py`` — producer-side tests that call real
  ``_publish_round`` code and use ``validate_*`` to assert the output
  conforms to the contract.
- ``tests/unit/cli/test_publish.py`` — consumer-side tests that mock
  ``_publish_round`` and use ``build_*`` so the mock returns the same
  shape the real function would.

Usage in a consumer test::

    from tests.fixtures.publish import build_published_entry, build_failed_resource
    monkeypatch.setattr(
        "market_storefront.cli_publish._publish_round",
        lambda **_: ([build_published_entry()], [], []),
    )

Usage in a producer test::

    from tests.fixtures.publish import validate_published_entry, validate_failed_resource
    published, failed, _ = _publish_round(db_path=db, ...)
    validate_published_entry(published[0])
    validate_failed_resource(failed[0])
"""

from __future__ import annotations


# ---------------------------------------------------------------------------
# Published entry
# ---------------------------------------------------------------------------


def build_published_entry(resource_id: str = "r1") -> dict:
    """Canonical published entry as returned in ``_publish_round``'s
    ``published`` list."""
    return {
        "resource": {
            "resource_id": resource_id,
            "gpu_model": "A100",
            "gpu_count": 1,
            "region": "us-west",
        },
        "response": {"listing_id": f"l-{resource_id}", "status": "created"},
        "accepted_escrows": [],
    }


def validate_published_entry(actual: dict) -> None:
    """Assert that *actual* conforms to the published entry contract.

    Checks structural presence only — specific resource attribute values
    (gpu_model, region, etc.) vary by DB state and are not constrained
    here.
    """
    assert "resource" in actual, "published entry must have 'resource'"
    resource = actual["resource"]
    assert "resource_id" in resource, "published entry resource must have 'resource_id'"
    assert "gpu_count" in resource, "published entry resource must have 'gpu_count'"

    assert "response" in actual, "published entry must have 'response'"
    response = actual["response"]
    assert "listing_id" in response, "published entry response must have 'listing_id'"
    assert isinstance(response["listing_id"], str) and response["listing_id"], (
        "listing_id must be a non-empty string"
    )

    assert "accepted_escrows" in actual, "published entry must have 'accepted_escrows'"
    assert isinstance(actual["accepted_escrows"], list), "'accepted_escrows' must be a list"


# ---------------------------------------------------------------------------
# Failed item
# ---------------------------------------------------------------------------


def build_failed_resource(resource_id: str = "r1") -> dict:
    """Canonical resource dict as it appears in the first element of a
    ``_publish_round`` failed tuple ``(resource_dict, error_str)``."""
    return {
        "resource_id": resource_id,
        "gpu_model": "A100",
        "gpu_count": 1,
        "region": "us-west",
    }


def validate_failed_resource(item: tuple) -> None:
    """Assert that *item* (a ``(resource_dict, error_str)`` tuple) conforms
    to the failed-resource contract.

    Callers pass the tuple directly::

        validate_failed_resource(failed[0])
    """
    assert len(item) == 2, f"failed item must be a 2-tuple, got length {len(item)}"
    resource_dict, error_msg = item
    assert "resource_id" in resource_dict, "failed resource_dict must have 'resource_id'"
    assert isinstance(error_msg, str) and error_msg, (
        "failed error_msg must be a non-empty string"
    )
