"""Reopening a tracked listing transitions the registry record to open.

A registry record that was closed stays closed through a republication: the
publish body carries no status, and the registry preserves the one it holds.
The fake registry here therefore keeps the status of a record it already has
and is driven from the real ``ListingRequest`` serializer, so a publisher that
only reposts terms cannot report success.

Every fixture value is obviously synthetic development material and must never
be used on a public network.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from typing import Any

import pytest
from arkhai_bare_metal import (
    BareMetalResourceProjection,
    TrustedBareMetalProjection,
    bare_metal_listing_candidates,
    record_derived_bare_metal_listing,
)
from core_storefront.publication_command import (
    StorefrontPublicationCommandCallbacks,
    StorefrontPublicationCommandConfig,
)
from market_identity import Ed25519Signer
from registry_client import (
    ListingRequest,
    ListingSummary,
    RegistryClientError,
    UpdateListingRequest,
)

from arkhai_bare_metal_storefront import publication_cli
from arkhai_bare_metal_storefront.publication import (
    build_bare_metal_publication_selection,
    run_bare_metal_publication,
)
from arkhai_bare_metal_storefront.server import BARE_METAL_STOREFRONT_REGISTRY
from arkhai_bare_metal_storefront.sqlite_client import SQLiteClient

_LISTING_ID = "listing-fixture-tracked"
_STOREFRONT_URL = "https://storefront.example"
_SELLER = Ed25519Signer(bytes.fromhex("33" * 32)).identity
_ESCROW = {"chain_name": "base", "token": "fixture-token-a"}
# A registry listing response always names its publisher; the parsed model
# requires it.
_PUBLISHER_PRINCIPALS = {
    "identities": [
        {"scheme": _SELLER.scheme.value, "identifier": _SELLER.identifier}
    ]
}


class _FakeRegistry:
    """A registry whose POST preserves the status of a record it already has.

    This is the semantic the real service implements: the publish body has no
    status field, so republishing a closed record leaves it closed. Only the
    authenticated update transitions it.
    """

    def __init__(self, *, status: str = "closed", accept_update: bool = True) -> None:
        self.records: dict[str, dict[str, Any]] = {
            _LISTING_ID: {
                "listing_id": _LISTING_ID,
                "status": status,
                "publisher_principals": _PUBLISHER_PRINCIPALS,
            }
        }
        self.accept_update = accept_update
        self.calls: list[str] = []

    def publish_listing(self, request: ListingRequest) -> dict[str, Any]:
        # The actual serializer decides what reaches the registry.
        body = request.to_dict()
        self.calls.append("publish")
        listing_id = str(body["listing_id"])
        record = self.records.setdefault(
            listing_id,
            {
                "listing_id": listing_id,
                "status": "open",
                "publisher_principals": _PUBLISHER_PRINCIPALS,
            },
        )
        record.update(
            {key: value for key, value in body.items() if key != "listing_id"}
        )
        return {"listing_id": listing_id, "status": record["status"]}

    def update_listing(
        self, listing_id: str, request: UpdateListingRequest
    ) -> dict[str, Any]:
        self.calls.append("update")
        if not self.accept_update:
            raise RegistryClientError("PUT", "https://registry.example", 409, "{}")
        self.records[listing_id].update(request.to_dict())
        return {"listing_id": listing_id, **request.to_dict()}

    def get_listing(self, listing_id: str) -> ListingSummary:
        self.calls.append("get")
        # The real response model, parsed the way the client parses it, so the
        # confirmation reads the fields a registry actually returns.
        return ListingSummary.from_dict(dict(self.records[listing_id]))

    def close(self) -> None:  # pragma: no cover - parity with the real client
        pass


def _projection() -> TrustedBareMetalProjection:
    return TrustedBareMetalProjection(
        site_id="site-a",
        revision=3,
        digest="generation-3",
        complete=True,
        resources=[
            BareMetalResourceProjection(
                physical_resource_id="resource-1",
                pool_id="pool-1",
                physical_host_id="physical-host-1",
                machine_id="machine-1",
                available=True,
                allocation_mode="exclusive",
                access_methods=["ssh"],
                capacity={"gpu_count": 8},
                capabilities={"gpu_model": "H200"},
            ),
        ],
    )


def _candidate() -> dict[str, Any]:
    (candidate,) = bare_metal_listing_candidates([_projection()])
    return candidate


def _republish(client: _FakeRegistry) -> dict[str, Any]:
    return publication_cli._republish_open_listing(
        client,
        listing_id=_LISTING_ID,
        offer={"kind": "bare_metal.v1", "machine_id": "machine-1"},
        accepted_escrows=[_ESCROW],
        settlement_options=[],
        demands=[],
        max_duration_seconds=7200,
        storefront_url=_STOREFRONT_URL,
    )


def test_a_normal_reopen_transitions_the_registry_record_to_open():
    client = _FakeRegistry(status="closed")

    result = _republish(client)

    assert result == {"status": "published", "listing_id": _LISTING_ID}
    assert client.records[_LISTING_ID]["status"] == "open"
    assert client.records[_LISTING_ID]["accepted_escrows"] == [_ESCROW]
    # One record, one identity: republication never creates a second listing.
    assert list(client.records) == [_LISTING_ID]
    assert client.calls == ["publish", "update", "get"]


def test_a_registry_that_stays_closed_is_not_reported_as_published():
    client = _FakeRegistry(status="closed")
    # An update the registry acknowledges without applying: the read-back is
    # the only honest evidence of the transition.
    client.update_listing = lambda listing_id, request: {"listing_id": listing_id}

    with pytest.raises(RuntimeError) as raised:
        _republish(client)

    assert client.records[_LISTING_ID]["status"] == "closed"
    assert "open" in str(raised.value)


def test_a_rejected_or_unreachable_update_fails_the_reopen():
    client = _FakeRegistry(status="closed", accept_update=False)

    with pytest.raises(RuntimeError):
        _republish(client)

    assert client.records[_LISTING_ID]["status"] == "closed"


def test_a_confirmation_naming_another_listing_fails_the_reopen():
    client = _FakeRegistry(status="closed")
    # A registry answering with a different record must not be read as this
    # listing's confirmation.
    client.get_listing = lambda _listing_id: ListingSummary.from_dict(
        {
            "listing_id": "listing-fixture-other",
            "status": "open",
            "publisher_principals": _PUBLISHER_PRINCIPALS,
        }
    )

    with pytest.raises(RuntimeError) as raised:
        _republish(client)

    assert "identity" in str(raised.value)


def test_an_unreadable_confirmation_fails_the_reopen():
    client = _FakeRegistry(status="closed")

    def timeout(_listing_id: str) -> Any:
        raise TimeoutError("registry read timed out")

    client.get_listing = timeout

    with pytest.raises(RuntimeError):
        _republish(client)


def _closed_tracked_listing(tmp_path) -> str:
    """A tracked listing whose local and derived records are closed."""
    path = str(tmp_path / "storefront.db")
    db = SQLiteClient(path)
    candidate = _candidate()
    now = datetime.now(timezone.utc).isoformat()
    asyncio_run = __import__("asyncio").run
    asyncio_run(
        db.upsert_bare_metal_listing(
            listing_id=_LISTING_ID,
            status="closed",
            created_at=now,
            updated_at=now,
            seller_principal=_SELLER,
            storefront_url=_STOREFRONT_URL,
            listing=candidate["listing"],
            accepted_escrows=[],
            settlement_options=[],
            demands=[],
            site_id=candidate["site_id"],
            pool_id=str(candidate["pool_id"]),
            physical_resource_id=candidate["physical_resource_id"],
        )
    )
    record_derived_bare_metal_listing(
        path,
        listing_id=_LISTING_ID,
        candidate=candidate,
        status="closed",
    )
    return path


def _local_state(db_path: str) -> dict[str, Any]:
    conn = sqlite3.connect(db_path)
    try:
        listing = conn.execute(
            "SELECT status, accepted_escrows FROM listings WHERE listing_id = ?",
            (_LISTING_ID,),
        ).fetchone()
        derived = conn.execute(
            "SELECT status FROM derived_bare_metal_listings WHERE listing_id = ?",
            (_LISTING_ID,),
        ).fetchone()
    finally:
        conn.close()
    return {
        "listing_status": listing[0],
        "accepted_escrows": json.loads(listing[1] or "[]"),
        "derived_status": derived[0],
    }


def _run(db_path: str, publish_existing_listing) -> Any:
    selection = build_bare_metal_publication_selection(
        BARE_METAL_STOREFRONT_REGISTRY,
        projection_snapshot=lambda: [_projection()],
        close_listing=lambda *_args: {"status": "closed"},
        publish_existing_listing=publish_existing_listing,
    )
    return run_bare_metal_publication(
        selection,
        config=StorefrontPublicationCommandConfig(
            db_path=db_path,
            base_url=_STOREFRONT_URL,
            close_stale=False,
        ),
        callbacks=StorefrontPublicationCommandCallbacks(
            build_payload=lambda _source, _candidate, _offer: (
                [_ESCROW],
                [],
                7200,
            ),
            publish_offer=lambda *_args, **_kwargs: pytest.fail(
                "a reopen must never create a second listing identity"
            ),
        ),
    )


def test_a_failed_reopen_leaves_the_local_records_closed_and_retries(tmp_path):
    db_path = _closed_tracked_listing(tmp_path)
    attempts: list[str] = []

    def failing(**values):
        attempts.append(values["listing_id"])
        raise RuntimeError("registry listing.update failed: fixture")

    failed = _run(db_path, failing)

    assert failed.published == []
    assert failed.failed_count == 1
    assert attempts == [_LISTING_ID]
    state = _local_state(db_path)
    assert state["listing_status"] == "closed"
    assert state["derived_status"] == "closed"

    def succeeding(**values):
        attempts.append(values["listing_id"])
        return {"status": "published", "listing_id": values["listing_id"]}

    retried = _run(db_path, succeeding)

    assert retried.failed == []
    assert retried.published_count == 1
    assert attempts == [_LISTING_ID, _LISTING_ID]
    state = _local_state(db_path)
    assert state["listing_status"] == "open"
    assert state["derived_status"] == "open"
    assert state["accepted_escrows"] == [_ESCROW]
