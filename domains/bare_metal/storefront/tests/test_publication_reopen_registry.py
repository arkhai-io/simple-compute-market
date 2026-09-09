"""Reopening a tracked listing confirms an explicit open publication.

The fake registry is driven from the real ``ListingRequest`` serializer, so
the test proves that reopen carries explicit ``open`` status while refresh
retains the omission behavior of an ordinary publication.

Every fixture value is obviously synthetic development material and must never
be used on a public network.
"""

from __future__ import annotations

import asyncio
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
from arkhai_bare_metal import storefront_publication
from core_storefront.multi_registry_client import RegistryTargetIdentity
from core_storefront.publication_command import (
    StorefrontPublicationCommandCallbacks,
    StorefrontPublicationCommandConfig,
)
from market_capacity_publication import (
    CapacityBinding,
    CapacityBindingError,
    PublicationCandidate,
)
from market_identity import Ed25519Signer, TrustedIdentitySet
from registry_client import (
    ListingRequest,
    ListingSummary,
    RegistryClientError,
    UpdateListingRequest,
)

from arkhai_bare_metal_storefront.publication import (
    build_bare_metal_lifecycle_runtime,
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
    """A registry implementing the typed publication status semantics."""

    def __init__(self, *, status: str = "closed", accept_publish: bool = True) -> None:
        self.records: dict[str, dict[str, Any]] = {
            _LISTING_ID: {
                "listing_id": _LISTING_ID,
                "status": status,
                "publisher_principals": _PUBLISHER_PRINCIPALS,
                "storefront_url": _STOREFRONT_URL,
                "offer_resource": {},
                "accepted_escrows": [],
                "settlement_options": [],
                "demands": [],
                "max_duration_seconds": None,
            }
        }
        self.accept_publish = accept_publish
        self.calls: list[str] = []

    def publish_listing(self, request: ListingRequest) -> dict[str, Any]:
        # The actual serializer decides what reaches the registry.
        body = request.to_dict()
        self.calls.append("publish")
        if not self.accept_publish:
            raise RegistryClientError("POST", "https://registry.example", 409, "{}")
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

    def get_listing(self, listing_id: str) -> ListingSummary:
        self.calls.append("get")
        # The real response model, parsed the way the client parses it, so the
        # confirmation reads the fields a registry actually returns.
        return ListingSummary.from_dict(dict(self.records[listing_id]))

    def close(self) -> None:  # pragma: no cover - parity with the real client
        pass


class _OpenedFakeRegistry:
    urls = ["https://registry.example"]
    publisher_identity = _SELLER
    registry_targets = (
        RegistryTargetIdentity(
            configured_url="https://registry.example",
            normalized_url="https://registry.example",
            authority="fixture-registry",
            principals=TrustedIdentitySet(identities=(_SELLER,)),
        ),
    )

    def __init__(self, registry: _FakeRegistry) -> None:
        self.registry = registry

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return None

    async def get_listing_from_registry(self, *, registry_url, listing_id):
        assert registry_url == self.urls[0]
        return self.registry.get_listing(listing_id)

    async def publish_listing_per_registry(self, *, payloads):
        results = []
        for url, request in payloads.items():
            try:
                response = self.registry.publish_listing(request)
            except RegistryClientError as exc:
                results.append(
                    {
                        "registry_url": url,
                        "success": False,
                        "response": None,
                        "error": "rejected",
                        "error_type": type(exc).__name__,
                        "status_code": exc.status_code,
                        "payload": request.to_dict(),
                        "registry_assigned_id": None,
                    }
                )
            else:
                results.append(
                    {
                        "registry_url": url,
                        "success": True,
                        "response": response,
                        "error": None,
                        "error_type": None,
                        "status_code": None,
                        "payload": request.to_dict(),
                        "registry_assigned_id": _LISTING_ID,
                    }
                )
        return results


class _PartialRecoveryRegistry:
    urls = ["https://registry-one.example", "https://registry-two.example"]
    publisher_identity = _SELLER
    registry_targets = tuple(
        RegistryTargetIdentity(
            configured_url=url,
            normalized_url=url,
            authority=f"fixture-registry-{index}",
            principals=TrustedIdentitySet(identities=(_SELLER,)),
        )
        for index, url in enumerate(urls, start=1)
    )

    def __init__(self) -> None:
        self.records = {
            url: {
                "listing_id": _LISTING_ID,
                "status": "closed",
                "publisher_principals": _PUBLISHER_PRINCIPALS,
                "storefront_url": _STOREFRONT_URL,
                "offer_resource": {},
                "accepted_escrows": [],
                "settlement_options": [],
                "demands": [],
                "max_duration_seconds": None,
            }
            for url in self.urls
        }
        self.calls: list[tuple[str, str]] = []
        self.writes: list[tuple[str, ...]] = []
        self.reject_second = True

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return None

    async def get_listing_from_registry(self, *, registry_url, listing_id):
        self.calls.append(("get", registry_url))
        assert listing_id == _LISTING_ID
        return ListingSummary.from_dict(dict(self.records[registry_url]))

    async def publish_listing_per_registry(self, *, payloads):
        self.writes.append(tuple(payloads))
        results = []
        for url, request in payloads.items():
            rejected = self.reject_second and url == self.urls[1]
            if not rejected:
                self.records[url].update(request.to_dict())
            results.append(
                {
                    "registry_url": url,
                    "success": not rejected,
                    "response": None if rejected else {"listing_id": _LISTING_ID},
                    "error": "rejected" if rejected else None,
                    "error_type": "RegistryClientError" if rejected else None,
                    "status_code": 403 if rejected else None,
                    "payload": request.to_dict(),
                    "registry_assigned_id": None if rejected else _LISTING_ID,
                }
            )
        return results


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


def _reopen(tmp_path, registry: _FakeRegistry):
    db_path, runtime, candidate = _reopen_runtime(
        tmp_path,
        _OpenedFakeRegistry(registry),
    )
    return db_path, asyncio.run(runtime.reopen(candidate))


def _reopen_runtime(tmp_path, client, *, available: bool = True):
    db_path = _closed_tracked_listing(tmp_path)
    db = SQLiteClient(db_path)
    source = _candidate()
    offer = dict(source["offer_resource"])
    offer["virtualization_type"] = "bare_metal"
    candidate = PublicationCandidate(
        _LISTING_ID,
        CapacityBinding("site-a", "bare_metal", "resource-1"),
        {
            "listing_id": _LISTING_ID,
            "seller_principal": _SELLER,
            "storefront_url": _STOREFRONT_URL,
            "offer_resource": offer,
            "accepted_escrows": [_ESCROW],
            "settlement_options": [],
            "publication_clauses": [],
            "demands": [],
            "max_duration_seconds": 7200,
            "bare_metal_candidate": source,
        },
    )
    runtime = build_bare_metal_lifecycle_runtime(
        repository=db,
        available_keys=(
            frozenset({str(source["derivation_key"])})
            if available
            else frozenset()
        ),
        enabled=True,
        registry_urls=tuple(client.urls),
        registry_client_factory=lambda: client,
        listing_request_factory=ListingRequest,
        update_listing_request_factory=UpdateListingRequest,
        storefront_url=_STOREFRONT_URL,
    )
    return db_path, runtime, candidate


def test_a_normal_reopen_transitions_the_registry_record_to_open(tmp_path):
    client = _FakeRegistry(status="closed")

    db_path, result = _reopen(tmp_path, client)

    assert result.status == "published"
    assert result.local_committed is True
    assert client.records[_LISTING_ID]["status"] == "open"
    assert client.records[_LISTING_ID]["accepted_escrows"] == [_ESCROW]
    # One record, one identity: republication never creates a second listing.
    assert list(client.records) == [_LISTING_ID]
    assert client.calls == ["get", "publish", "get"]
    assert _local_state(db_path)["listing_status"] == "open"


def test_a_registry_that_stays_closed_is_not_reported_as_published(tmp_path):
    client = _FakeRegistry(status="closed")
    # An update the registry acknowledges without applying: the read-back is
    # the only honest evidence of the transition.
    original_publish = client.publish_listing

    def ignore_status(request):
        status = client.records[_LISTING_ID]["status"]
        response = original_publish(request)
        client.records[_LISTING_ID]["status"] = status
        return response

    client.publish_listing = ignore_status

    db_path, result = _reopen(tmp_path, client)

    assert result.status == "error"
    assert client.records[_LISTING_ID]["status"] == "closed"
    assert _local_state(db_path)["listing_status"] == "closed"


def test_a_rejected_write_fails_the_reopen(tmp_path):
    client = _FakeRegistry(status="closed", accept_publish=False)

    db_path, result = _reopen(tmp_path, client)

    assert result.status == "error"
    assert client.records[_LISTING_ID]["status"] == "closed"
    assert _local_state(db_path)["listing_status"] == "closed"


def test_a_confirmation_naming_another_listing_fails_the_reopen(tmp_path):
    client = _FakeRegistry(status="closed")
    # A registry answering with a different record must not be read as this
    # listing's confirmation.
    def another_listing(_listing_id: str) -> ListingSummary:
        client.calls.append("get")
        return ListingSummary.from_dict(
            {
                "listing_id": "listing-fixture-other",
                "status": "open",
                "publisher_principals": _PUBLISHER_PRINCIPALS,
            }
        )

    client.get_listing = another_listing

    db_path, result = _reopen(tmp_path, client)

    assert result.status == "error"
    assert client.calls == ["get"]
    assert len(result.target_results) == 1
    assert result.target_results[0].state.value == "confirmation_mismatch"
    assert result.target_results[0].wrote is False
    assert _local_state(db_path)["listing_status"] == "closed"


def test_an_unreadable_preflight_fails_without_a_write(tmp_path):
    client = _FakeRegistry(status="closed")

    def timeout(_listing_id: str) -> Any:
        client.calls.append("get")
        raise TimeoutError("registry read timed out")

    client.get_listing = timeout

    db_path, result = _reopen(tmp_path, client)

    assert result.status == "error"
    assert client.calls == ["get"]
    assert len(result.target_results) == 1
    assert result.target_results[0].state.value == "preflight_unknown"
    assert result.target_results[0].wrote is False
    assert result.target_results[0].error_type == "TimeoutError"
    assert _local_state(db_path)["listing_status"] == "closed"


def test_partial_reopen_recovers_only_failed_target_after_local_commit(
    tmp_path,
    monkeypatch,
):
    client = _PartialRecoveryRegistry()
    db_path, runtime, candidate = _reopen_runtime(tmp_path, client)
    commits = 0
    original_commit = storefront_publication.commit_derived_bare_metal_listing

    def counted_commit(*args, **kwargs):
        nonlocal commits
        commits += 1
        return original_commit(*args, **kwargs)

    monkeypatch.setattr(
        "arkhai_bare_metal_storefront.publication.commit_derived_bare_metal_listing",
        counted_commit,
    )

    first = asyncio.run(runtime.reopen(candidate))

    assert first.status == "partial"
    assert first.local_committed is True
    assert commits == 1
    assert client.writes == [tuple(client.urls)]
    assert _local_state(db_path)["listing_status"] == "open"

    calls = list(client.calls)
    with pytest.raises(CapacityBindingError):
        asyncio.run(runtime.reopen(candidate))
    assert client.calls == calls

    wrong_binding = PublicationCandidate(
        candidate.listing_id,
        CapacityBinding("site-a", "bare_metal", "resource-other"),
        candidate.payload,
    )
    with pytest.raises(CapacityBindingError):
        asyncio.run(runtime.recover(wrong_binding, first))
    assert client.calls == calls

    (tmp_path / "unavailable").mkdir()
    _, unavailable_runtime, unavailable_candidate = _reopen_runtime(
        tmp_path / "unavailable",
        client,
        available=False,
    )
    with pytest.raises(CapacityBindingError):
        asyncio.run(unavailable_runtime.recover(unavailable_candidate, first))
    assert client.calls == calls

    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "UPDATE derived_bare_metal_listings SET status = 'closed' "
            "WHERE listing_id = ?",
            (_LISTING_ID,),
        )
    with pytest.raises(CapacityBindingError):
        asyncio.run(runtime.recover(candidate, first))
    assert client.calls == calls
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "UPDATE derived_bare_metal_listings SET status = 'open' "
            "WHERE listing_id = ?",
            (_LISTING_ID,),
        )

    client.reject_second = False
    recovered = asyncio.run(runtime.recover(candidate, first))

    assert recovered.status == "published"
    assert recovered.local_committed is True
    assert [item.state.value for item in recovered.target_results] == [
        "confirmed",
        "confirmed",
    ]
    assert client.writes == [tuple(client.urls), (client.urls[1],)]
    assert client.calls == [
        ("get", client.urls[0]),
        ("get", client.urls[1]),
        ("get", client.urls[0]),
        ("get", client.urls[1]),
    ]
    assert commits == 1
    assert _local_state(db_path)["listing_status"] == "open"


@pytest.mark.parametrize("mismatch", ["binding", "availability"])
def test_local_binding_and_availability_fail_before_registry_io(tmp_path, mismatch):
    db_path = _closed_tracked_listing(tmp_path)
    db = SQLiteClient(db_path)
    source = _candidate()
    client = _OpenedFakeRegistry(_FakeRegistry(status="closed"))
    binding = CapacityBinding("site-a", "bare_metal", "resource-1")
    if mismatch == "binding":
        binding = CapacityBinding("site-a", "bare_metal", "resource-other")
    runtime = build_bare_metal_lifecycle_runtime(
        repository=db,
        available_keys=(
            frozenset()
            if mismatch == "availability"
            else frozenset({str(source["derivation_key"])})
        ),
        enabled=True,
        registry_urls=tuple(client.urls),
        registry_client_factory=lambda: client,
        listing_request_factory=ListingRequest,
        update_listing_request_factory=UpdateListingRequest,
        storefront_url=_STOREFRONT_URL,
    )
    candidate = PublicationCandidate(
        _LISTING_ID,
        binding,
        {
            "listing_id": _LISTING_ID,
            "storefront_url": _STOREFRONT_URL,
            "offer_resource": {
                **source["offer_resource"],
                "virtualization_type": "bare_metal",
            },
            "accepted_escrows": [_ESCROW],
            "settlement_options": [],
            "demands": [],
            "max_duration_seconds": 7200,
            "bare_metal_candidate": source,
        },
    )

    with pytest.raises(CapacityBindingError):
        asyncio.run(runtime.reopen(candidate))

    assert client.registry.calls == []


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
        storefront_publication.commit_derived_bare_metal_listing(
            db_path,
            listing_id=values["listing_id"],
            base_url=values["storefront_url"],
            candidate=values["candidate"],
            offer=values["offer"],
            accepted_escrows=values["accepted_escrows"],
            demands=values["demands"],
            max_duration_seconds=values["max_duration_seconds"],
            settlement_options=values["settlement_options"],
            publication_clauses=values["publication_clauses"],
            reopen=True,
        )
        return {"status": "published", "listing_id": values["listing_id"]}

    retried = _run(db_path, succeeding)

    assert retried.failed == []
    assert retried.published_count == 1
    assert attempts == [_LISTING_ID, _LISTING_ID]
    state = _local_state(db_path)
    assert state["listing_status"] == "open"
    assert state["derived_status"] == "open"
    assert state["accepted_escrows"] == [_ESCROW]
