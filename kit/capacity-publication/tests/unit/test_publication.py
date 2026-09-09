from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from core_storefront.multi_registry_client import RegistryTargetIdentity
from market_identity import Ed25519Signer, TrustedIdentitySet
from registry_client import ListingRequest, ListingSummary, RegistryClientError

from market_capacity_publication import (
    BoundListing,
    CapacityBinding,
    CapacityBindingError,
    DisabledPublicationPolicy,
    PublicationCandidate,
    PublicationLifecycleResult,
    PublicationRuntime,
    PublicationTargetState,
    PublicationTransition,
    ReconciliationPlan,
)


class Repository:
    def __init__(self):
        self.statuses = {}
        self.publications = []

    async def update_listing(self, *, listing_id, status):
        self.statuses[listing_id] = status

    async def load_publications(self, *, listing_id):
        return [row for row in self.publications if row["listing_id"] == listing_id]

    async def upsert_publication(self, **row):
        self.publications.append(row)


class Hooks:
    def __init__(self, bindings):
        self.bindings = bindings
        self.validated = []
        self.commits = []

    def validate_candidate(self, candidate):
        offer = candidate.payload["offer_resource"]
        if offer["virtualization_type"] != candidate.binding.offering_mode:
            raise CapacityBindingError("advertised offering mode differs from binding")
        self.validated.append(candidate.listing_id)

    async def binding_for_listing(self, listing_id):
        return self.bindings.get(listing_id)

    async def validate_lifecycle(
        self, candidate, transition, *, previous_local_committed
    ):
        del previous_local_committed
        self.validated.append((candidate.listing_id, transition))

    def disabled_publication_policy(self, transition):
        return (
            DisabledPublicationPolicy.COMMIT_LOCAL
            if transition is PublicationTransition.REOPEN
            else DisabledPublicationPolicy.SKIP_LOCAL
        )

    async def commit_candidate(self, candidate, transition):
        self.commits.append((candidate.listing_id, transition))
        if transition is PublicationTransition.REOPEN:
            await self.repository.update_listing(
                listing_id=candidate.listing_id,
                status="open",
            )


def runtime(repository, hooks):
    hooks.repository = repository
    return PublicationRuntime(
        repository=repository,
        hooks=hooks,
        enabled=False,
        registry_urls=(),
        registry_client_factory=AsyncMock(),
        listing_request_factory=dict,
        update_listing_request_factory=dict,
        storefront_url="https://seller.example",
    )


def candidate(listing_id="listing-1", binding=None):
    binding = binding or CapacityBinding("site-a", "vm", "pool-a")
    return PublicationCandidate(
        listing_id=listing_id,
        binding=binding,
        payload={
            "listing_id": listing_id,
            "seller_principal": {"scheme": "ed25519", "identifier": "seller"},
            "offer_resource": {"virtualization_type": "vm"},
            "accepted_escrows": [],
            "settlement_options": [],
            "demands": [],
            "storefront_url": "https://seller.example",
        },
    )


_PUBLISHER = Ed25519Signer(bytes(range(32))).identity
_AUTHORITY = Ed25519Signer(bytes(range(1, 33))).identity


def _summary(
    *,
    offer_mode: str,
    offer: dict | None = None,
    status: str = "open",
    listing_id: str = "listing-1",
    publisher=_PUBLISHER,
) -> ListingSummary:
    return ListingSummary(
        id=listing_id,
        status=status,
        publisher_principals=TrustedIdentitySet(identities=(publisher,)),
        storefront_url="https://seller.example",
        offer=offer or {"virtualization_type": offer_mode},
        accepted_escrows=[],
        settlement_options=[],
        demands=[],
        max_duration_seconds=None,
    )


class OpenedRegistryClient:
    urls = ["https://r1.example", "https://r2.example"]
    publisher_identity = _PUBLISHER
    registry_targets = tuple(
        RegistryTargetIdentity(
            configured_url=url,
            normalized_url=url,
            authority=f"authority-{index}",
            principals=TrustedIdentitySet(identities=(_AUTHORITY,)),
        )
        for index, url in enumerate(urls, start=1)
    )

    def __init__(self):
        self.reads = {
            "https://r1.example": [
                _summary(offer_mode="old"),
                _summary(offer_mode="vm"),
            ],
            "https://r2.example": [_summary(offer_mode="old")],
        }
        self.writes = []
        self.published_requests = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return None

    async def get_listing_from_registry(self, *, registry_url, listing_id):
        assert listing_id == "listing-1"
        value = self.reads[registry_url].pop(0)
        if isinstance(value, BaseException):
            raise value
        return value

    async def publish_listing_per_registry(self, *, payloads):
        self.writes.append(tuple(payloads))
        self.published_requests.extend(payloads.values())
        return [
            {
                "registry_url": url,
                "success": url == "https://r1.example",
                "response": {"listing_id": "listing-1"}
                if url == "https://r1.example"
                else None,
                "error": None if url == "https://r1.example" else "rejected",
                "error_type": None
                if url == "https://r1.example"
                else "RegistryClientError",
                "status_code": None if url == "https://r1.example" else 403,
                "payload": payloads[url].to_dict(),
                "registry_assigned_id": "listing-1"
                if url == "https://r1.example"
                else None,
            }
            for url in payloads
        ]


def enabled_runtime(repository, hooks, client, *, on_published=None):
    hooks.repository = repository
    return PublicationRuntime(
        repository=repository,
        hooks=hooks,
        enabled=True,
        registry_urls=tuple(client.urls),
        registry_client_factory=lambda: client,
        listing_request_factory=ListingRequest,
        update_listing_request_factory=dict,
        storefront_url="https://seller.example",
        on_published=on_published,
    )


@pytest.mark.asyncio
async def test_publish_requires_exact_durable_site_and_mode_binding():
    repository = Repository()
    expected = CapacityBinding("site-a", "vm", "pool-a")
    hooks = Hooks({"listing-1": expected})

    result = await runtime(repository, hooks).publish(candidate())

    assert result["status"] == "disabled"
    assert hooks.validated == ["listing-1"]

    with pytest.raises(CapacityBindingError, match="does not match"):
        await runtime(repository, hooks).publish(
            candidate(binding=CapacityBinding("site-b", "vm", "pool-a"))
        )


@pytest.mark.asyncio
async def test_candidate_codec_must_project_exact_offering_mode():
    repository = Repository()
    binding = CapacityBinding("site-a", "bare_metal", "pool-a")
    hooks = Hooks({"listing-1": binding})

    with pytest.raises(CapacityBindingError, match="advertised offering mode"):
        await runtime(repository, hooks).publish(candidate(binding=binding))


@pytest.mark.asyncio
async def test_reconciliation_owns_close_then_reopen_mechanics():
    repository = Repository()
    binding = CapacityBinding("site-a", "vm", "pool-a")
    hooks = Hooks({"close-me": binding, "reopen-me": binding})
    publication = runtime(repository, hooks)

    result = await publication.reconcile(
        ReconciliationPlan(
            close=(BoundListing("close-me", binding),),
            reopen=(candidate("reopen-me", binding),),
        )
    )

    assert repository.statuses == {"close-me": "closed", "reopen-me": "open"}
    assert result == {"closed": ("close-me",), "reopened": ("reopen-me",)}


@pytest.mark.asyncio
async def test_disabled_reopen_uses_explicit_domain_compatibility_policy():
    repository = Repository()
    binding = CapacityBinding("site-a", "vm", "pool-a")
    hooks = Hooks({"listing-1": binding})

    result = await runtime(repository, hooks).reopen(candidate(binding=binding))

    assert isinstance(result, PublicationLifecycleResult)
    assert result.status == "disabled"
    assert result.local_committed is True
    assert repository.statuses == {"listing-1": "open"}


@pytest.mark.asyncio
async def test_refresh_commits_after_confirmation_and_reports_partial_targets():
    repository = Repository()
    binding = CapacityBinding("site-a", "vm", "pool-a")
    hooks = Hooks({"listing-1": binding})
    client = OpenedRegistryClient()

    result = await enabled_runtime(repository, hooks, client).refresh(
        candidate(binding=binding)
    )

    assert isinstance(result, PublicationLifecycleResult)
    assert result.status == "partial"
    assert result.local_committed is True
    assert result.partial is True
    assert result.to_dict()["message"] == (
        "registry publication is only partially confirmed: "
        "https://r1.example=confirmed, https://r2.example=write_failed"
    )
    assert [target.state for target in result.target_results] == [
        PublicationTargetState.CONFIRMED,
        PublicationTargetState.WRITE_FAILED,
    ]
    assert client.writes == [
        ("https://r1.example", "https://r2.example")
    ]
    assert all("status" not in request.to_dict() for request in client.published_requests)
    assert hooks.commits == [
        ("listing-1", PublicationTransition.REFRESH)
    ]
    assert {row["status"] for row in repository.publications} == {
        "published",
        "failed",
    }
    failed_receipt = next(
        row for row in repository.publications if row["status"] == "failed"
    )
    assert failed_receipt["last_error"] == (
        "registry write failed: RegistryClientError HTTP 403"
    )
    assert "rejected" not in repr(failed_receipt)


@pytest.mark.asyncio
async def test_all_rejected_targets_do_not_commit_or_report_partial_convergence():
    repository = Repository()
    binding = CapacityBinding("site-a", "vm", "pool-a")
    hooks = Hooks({"listing-1": binding})
    client = OpenedRegistryClient()

    async def reject_all(*, payloads):
        client.writes.append(tuple(payloads))
        return [
            {
                "registry_url": url,
                "success": False,
                "response": None,
                "error": "private rejection marker",
                "error_type": "RegistryClientError",
                "status_code": 403,
                "payload": request.to_dict(),
                "registry_assigned_id": None,
            }
            for url, request in payloads.items()
        ]

    client.publish_listing_per_registry = reject_all

    result = await enabled_runtime(repository, hooks, client).refresh(
        candidate(binding=binding)
    )

    assert result.status == "error"
    assert result.partial is False
    assert result.local_committed is False
    assert [target.state for target in result.target_results] == [
        PublicationTargetState.WRITE_FAILED,
        PublicationTargetState.WRITE_FAILED,
    ]
    assert hooks.commits == []
    assert "private rejection marker" not in repr(result.to_dict())
    assert result.to_dict()["message"].endswith(
        "https://r1.example=write_failed, https://r2.example=write_failed"
    )


@pytest.mark.asyncio
async def test_changed_terms_start_a_new_intent_for_every_configured_target():
    repository = Repository()
    binding = CapacityBinding("site-a", "vm", "pool-a")
    hooks = Hooks({"listing-1": binding})
    client = OpenedRegistryClient()
    client.urls = ["https://r1.example"]
    client.registry_targets = client.registry_targets[:1]
    client.reads = {
        "https://r1.example": [
            _summary(offer_mode="old"),
            _summary(offer_mode="vm"),
            _summary(
                offer_mode="vm",
                offer={"virtualization_type": "vm", "generation": 1},
            ),
            _summary(
                offer_mode="vm",
                offer={"virtualization_type": "vm", "generation": 2},
            ),
        ]
    }
    publication = enabled_runtime(repository, hooks, client)

    first = await publication.refresh(candidate(binding=binding))
    changed = candidate(binding=binding)
    changed.payload["offer_resource"]["generation"] = 2
    second = await publication.refresh(changed)

    assert first.status == "published"
    assert second.status == "published"
    assert first.intent is not None and second.intent is not None
    assert first.intent.canonical_request != second.intent.canonical_request
    assert client.writes == [
        ("https://r1.example",),
        ("https://r1.example",),
    ]


@pytest.mark.asyncio
async def test_reopen_after_refresh_is_a_new_explicit_status_intent():
    repository = Repository()
    binding = CapacityBinding("site-a", "vm", "pool-a")
    hooks = Hooks({"listing-1": binding})
    client = OpenedRegistryClient()
    client.urls = ["https://r1.example"]
    client.registry_targets = client.registry_targets[:1]
    client.reads = {
        "https://r1.example": [
            _summary(offer_mode="vm", status="open"),
            _summary(offer_mode="vm", status="closed"),
            _summary(offer_mode="vm", status="open"),
        ]
    }
    publication = enabled_runtime(repository, hooks, client)

    refreshed = await publication.refresh(candidate(binding=binding))
    reopened = await publication.reopen(candidate(binding=binding))

    assert refreshed.status == "published"
    assert reopened.status == "published"
    assert refreshed.intent is not None and reopened.intent is not None
    assert refreshed.intent.canonical_request != reopened.intent.canonical_request
    assert len(client.published_requests) == 1
    assert client.published_requests[0].to_dict()["status"] == "open"


@pytest.mark.asyncio
async def test_ambiguous_write_recovery_reconfirms_without_repeating_write():
    repository = Repository()
    binding = CapacityBinding("site-a", "vm", "pool-a")
    hooks = Hooks({"listing-1": binding})
    client = OpenedRegistryClient()
    client.urls = ["https://r1.example"]
    client.registry_targets = client.registry_targets[:1]
    client.reads = {
        "https://r1.example": [
            _summary(offer_mode="old"),
            RuntimeError("readback interrupted"),
            _summary(offer_mode="vm"),
        ]
    }
    publication = enabled_runtime(repository, hooks, client)

    first = await publication.refresh(candidate(binding=binding))
    recovered = await publication.recover(candidate(binding=binding), first)

    assert first.local_committed is False
    assert first.target_results[0].state is PublicationTargetState.WRITE_UNCONFIRMED
    assert recovered.status == "published"
    assert recovered.local_committed is True
    assert recovered.target_results[0].state is PublicationTargetState.CONFIRMED
    assert client.writes == [("https://r1.example",)]
    assert hooks.commits == [
        ("listing-1", PublicationTransition.REFRESH)
    ]


@pytest.mark.asyncio
async def test_fanout_exception_is_ambiguous_and_recovery_does_not_repeat_write():
    repository = Repository()
    binding = CapacityBinding("site-a", "vm", "pool-a")
    hooks = Hooks({"listing-1": binding})
    client = OpenedRegistryClient()
    client.urls = ["https://r1.example"]
    client.registry_targets = client.registry_targets[:1]
    client.reads = {
        "https://r1.example": [
            _summary(offer_mode="old"),
            _summary(offer_mode="vm"),
        ]
    }
    writes = 0

    async def interrupted_fanout(*, payloads):
        nonlocal writes
        writes += 1
        raise TimeoutError("private transport marker")

    client.publish_listing_per_registry = interrupted_fanout
    publication = enabled_runtime(repository, hooks, client)

    first = await publication.refresh(candidate(binding=binding))
    recovered = await publication.recover(candidate(binding=binding), first)

    assert first.failure_stage == "fanout"
    assert first.target_results[0].state is PublicationTargetState.WRITE_UNKNOWN
    assert "private transport marker" not in repr(first.to_dict())
    assert recovered.status == "published"
    assert recovered.local_committed is True
    assert writes == 1


@pytest.mark.asyncio
async def test_authenticated_missing_post_write_readback_is_mismatch_not_unknown():
    repository = Repository()
    binding = CapacityBinding("site-a", "vm", "pool-a")
    hooks = Hooks({"listing-1": binding})
    client = OpenedRegistryClient()
    client.urls = ["https://r1.example"]
    client.registry_targets = client.registry_targets[:1]
    client.reads = {
        "https://r1.example": [
            _summary(offer_mode="old"),
            RegistryClientError(
                "GET",
                "https://r1.example/listings/listing-1",
                404,
                "not found",
            ),
        ]
    }

    result = await enabled_runtime(repository, hooks, client).refresh(
        candidate(binding=binding)
    )

    assert result.status == "error"
    assert result.target_results[0].state is PublicationTargetState.CONFIRMATION_MISMATCH
    assert result.local_committed is False


@pytest.mark.asyncio
async def test_recovery_retries_only_the_known_failed_target():
    repository = Repository()
    binding = CapacityBinding("site-a", "vm", "pool-a")
    hooks = Hooks({"listing-1": binding})
    client = OpenedRegistryClient()
    publication = enabled_runtime(repository, hooks, client)

    first = await publication.refresh(candidate(binding=binding))

    async def accept_retry(*, payloads):
        client.writes.append(tuple(payloads))
        return [
            {
                "registry_url": url,
                "success": True,
                "response": {"listing_id": "listing-1"},
                "error": None,
                "error_type": None,
                "status_code": None,
                "payload": payloads[url].to_dict(),
                "registry_assigned_id": "listing-1",
            }
            for url in payloads
        ]

    client.publish_listing_per_registry = accept_retry
    client.reads["https://r2.example"].append(_summary(offer_mode="vm"))
    recovered = await publication.recover(candidate(binding=binding), first)

    assert recovered.status == "published"
    assert [target.state for target in recovered.target_results] == [
        PublicationTargetState.CONFIRMED,
        PublicationTargetState.CONFIRMED,
    ]
    assert client.writes == [
        ("https://r1.example", "https://r2.example"),
        ("https://r2.example",),
    ]
    assert hooks.commits == [
        ("listing-1", PublicationTransition.REFRESH)
    ]


@pytest.mark.asyncio
async def test_preflight_unknown_performs_no_write_or_local_commit():
    repository = Repository()
    binding = CapacityBinding("site-a", "vm", "pool-a")
    hooks = Hooks({"listing-1": binding})
    client = OpenedRegistryClient()
    client.urls = ["https://r1.example"]
    client.registry_targets = client.registry_targets[:1]
    client.reads = {"https://r1.example": [TimeoutError("unavailable")]}

    result = await enabled_runtime(repository, hooks, client).refresh(
        candidate(binding=binding)
    )

    assert result.status == "error"
    assert result.partial is False
    assert result.local_committed is False
    assert result.target_results[0].state is PublicationTargetState.PREFLIGHT_UNKNOWN
    assert client.writes == []
    assert hooks.commits == []


@pytest.mark.asyncio
async def test_reopen_sends_open_in_one_publication_and_requires_open_readback():
    repository = Repository()
    binding = CapacityBinding("site-a", "vm", "pool-a")
    hooks = Hooks({"listing-1": binding})
    client = OpenedRegistryClient()
    client.urls = ["https://r1.example"]
    client.registry_targets = client.registry_targets[:1]
    client.reads = {
        "https://r1.example": [
            _summary(offer_mode="old", status="closed"),
            _summary(offer_mode="vm", status="open"),
        ]
    }

    result = await enabled_runtime(repository, hooks, client).reopen(
        candidate(binding=binding)
    )

    assert result.status == "published"
    assert result.local_committed is True
    assert client.published_requests[0].to_dict()["status"] == "open"


@pytest.mark.asyncio
async def test_wrong_publisher_is_rejected_during_preflight_before_write():
    repository = Repository()
    binding = CapacityBinding("site-a", "vm", "pool-a")
    hooks = Hooks({"listing-1": binding})
    client = OpenedRegistryClient()
    client.urls = ["https://r1.example"]
    client.registry_targets = client.registry_targets[:1]
    other = Ed25519Signer(bytes(range(2, 34))).identity
    client.reads = {
        "https://r1.example": [_summary(offer_mode="old", publisher=other)]
    }

    result = await enabled_runtime(repository, hooks, client).refresh(
        candidate(binding=binding)
    )

    assert result.status == "error"
    assert result.target_results[0].state is PublicationTargetState.CONFIRMATION_MISMATCH
    assert client.writes == []
    assert repository.publications == []
    assert hooks.commits == []


@pytest.mark.asyncio
async def test_receipt_persistence_and_local_commit_failures_remain_distinct():
    binding = CapacityBinding("site-a", "vm", "pool-a")

    class FailingRepository(Repository):
        async def upsert_publication(self, **row):
            raise RuntimeError("private persistence marker")

    repository = FailingRepository()
    hooks = Hooks({"listing-1": binding})
    client = OpenedRegistryClient()
    client.urls = ["https://r1.example"]
    client.registry_targets = client.registry_targets[:1]
    result = await enabled_runtime(repository, hooks, client).refresh(
        candidate(binding=binding)
    )

    assert result.failure_stage == "persistence"
    assert result.local_committed is False
    assert result.target_results[0].state is PublicationTargetState.CONFIRMED
    assert hooks.commits == []
    assert "private persistence marker" not in repr(result.to_dict())

    class FailingHooks(Hooks):
        async def commit_candidate(self, candidate, transition):
            raise RuntimeError("private local marker")

    repository = Repository()
    hooks = FailingHooks({"listing-1": binding})
    client = OpenedRegistryClient()
    client.urls = ["https://r1.example"]
    client.registry_targets = client.registry_targets[:1]
    result = await enabled_runtime(repository, hooks, client).refresh(
        candidate(binding=binding)
    )

    assert result.failure_stage == "local_commit"
    assert result.local_committed is False
    assert repository.publications[0]["status"] == "published"
    assert "private local marker" not in repr(result.to_dict())


@pytest.mark.asyncio
async def test_recovery_retries_receipt_persistence_without_repeating_remote_write():
    binding = CapacityBinding("site-a", "vm", "pool-a")

    class FlakyRepository(Repository):
        def __init__(self):
            super().__init__()
            self.attempts = 0

        async def upsert_publication(self, **row):
            self.attempts += 1
            if self.attempts < 3:
                raise RuntimeError("private persistence marker")
            await super().upsert_publication(**row)

    repository = FlakyRepository()
    hooks = Hooks({"listing-1": binding})
    client = OpenedRegistryClient()
    client.urls = ["https://r1.example"]
    client.registry_targets = client.registry_targets[:1]
    events = []

    def record_event(**values):
        events.append(values["listing_id"])

    publication = enabled_runtime(
        repository,
        hooks,
        client,
        on_published=record_event,
    )
    first = await publication.refresh(candidate(binding=binding))
    second = await publication.recover(candidate(binding=binding), first)
    recovered = await publication.recover(candidate(binding=binding), second)

    assert first.failure_stage == "persistence"
    assert second.failure_stage == "persistence"
    assert first.local_committed is False
    assert second.local_committed is False
    assert first.receipts_persisted is False
    assert second.receipts_persisted is False
    assert first.event_emitted is False
    assert second.event_emitted is False
    assert recovered.status == "published"
    assert recovered.local_committed is True
    assert recovered.receipts_persisted is True
    assert recovered.event_emitted is True
    assert client.writes == [("https://r1.example",)]
    assert repository.attempts == 3
    assert len(repository.publications) == 1
    assert events == ["listing-1"]
    assert hooks.commits == [("listing-1", PublicationTransition.REFRESH)]


@pytest.mark.asyncio
async def test_matching_preflight_requires_durable_receipt_before_local_commit():
    binding = CapacityBinding("site-a", "vm", "pool-a")

    class FlakyRepository(Repository):
        def __init__(self):
            super().__init__()
            self.fail = True

        async def upsert_publication(self, **row):
            if self.fail:
                raise RuntimeError("private persistence marker")
            await super().upsert_publication(**row)

    repository = FlakyRepository()
    hooks = Hooks({"listing-1": binding})
    client = OpenedRegistryClient()
    client.urls = ["https://r1.example"]
    client.registry_targets = client.registry_targets[:1]
    client.reads = {"https://r1.example": [_summary(offer_mode="vm")]}
    publication = enabled_runtime(repository, hooks, client)

    first = await publication.refresh(candidate(binding=binding))
    repository.fail = False
    recovered = await publication.recover(candidate(binding=binding), first)

    assert first.failure_stage == "persistence"
    assert first.target_results[0].state is PublicationTargetState.CONFIRMED
    assert first.local_committed is False
    assert first.receipts_persisted is False
    assert recovered.status == "published"
    assert recovered.local_committed is True
    assert recovered.receipts_persisted is True
    assert client.writes == []
    assert len(repository.publications) == 1
    assert hooks.commits == [("listing-1", PublicationTransition.REFRESH)]


@pytest.mark.asyncio
async def test_recovery_retries_outstanding_event_without_repeating_receipts_or_write():
    binding = CapacityBinding("site-a", "vm", "pool-a")
    repository = Repository()
    hooks = Hooks({"listing-1": binding})
    client = OpenedRegistryClient()
    client.urls = ["https://r1.example"]
    client.registry_targets = client.registry_targets[:1]
    event_attempts = 0

    def flaky_event(**_values):
        nonlocal event_attempts
        event_attempts += 1
        if event_attempts < 3:
            raise RuntimeError("private event marker")

    publication = enabled_runtime(
        repository,
        hooks,
        client,
        on_published=flaky_event,
    )
    first = await publication.refresh(candidate(binding=binding))
    second = await publication.recover(candidate(binding=binding), first)
    recovered = await publication.recover(candidate(binding=binding), second)

    assert first.failure_stage == "event"
    assert second.failure_stage == "event"
    assert first.local_committed is False
    assert second.local_committed is False
    assert first.receipts_persisted is True
    assert second.receipts_persisted is True
    assert first.event_emitted is False
    assert second.event_emitted is False
    assert recovered.status == "published"
    assert recovered.local_committed is True
    assert recovered.event_emitted is True
    assert client.writes == [("https://r1.example",)]
    assert len(repository.publications) == 1
    assert event_attempts == 3
    assert hooks.commits == [("listing-1", PublicationTransition.REFRESH)]


@pytest.mark.asyncio
async def test_lifecycle_rejects_payload_listing_identity_before_registry_io():
    repository = Repository()
    binding = CapacityBinding("site-a", "vm", "pool-a")
    hooks = Hooks({"listing-1": binding})

    class UnopenedClient(OpenedRegistryClient):
        def __init__(self):
            super().__init__()
            self.entries = 0

        async def __aenter__(self):
            self.entries += 1
            return self

    client = UnopenedClient()
    mismatched = candidate(binding=binding)
    mismatched.payload["listing_id"] = "listing-2"

    result = await enabled_runtime(repository, hooks, client).reopen(mismatched)

    assert result.status == "error"
    assert result.failure_stage == "setup"
    assert result.error_type == "ValueError"
    assert client.entries == 0
    assert client.writes == []
    assert hooks.commits == []


@pytest.mark.asyncio
async def test_recovery_rejects_changed_payload_listing_identity_before_registry_io():
    repository = Repository()
    binding = CapacityBinding("site-a", "vm", "pool-a")
    hooks = Hooks({"listing-1": binding})
    client = OpenedRegistryClient()
    publication = enabled_runtime(repository, hooks, client)
    first = await publication.refresh(candidate(binding=binding))
    reads = {url: list(values) for url, values in client.reads.items()}
    writes = list(client.writes)
    mismatched = candidate(binding=binding)
    mismatched.payload["listing_id"] = "listing-2"

    recovered = await publication.recover(mismatched, first)

    assert recovered.status == "error"
    assert recovered.failure_stage == "recovery"
    assert recovered.error_type == "ValueError"
    assert client.reads == reads
    assert client.writes == writes
    assert hooks.commits == [("listing-1", PublicationTransition.REFRESH)]


@pytest.mark.asyncio
async def test_local_commit_failure_reuses_confirmation_without_remote_write():
    binding = CapacityBinding("site-a", "vm", "pool-a")
    repository = Repository()

    class RetryableHooks(Hooks):
        def __init__(self, bindings):
            super().__init__(bindings)
            self.attempts = 0

        async def commit_candidate(self, candidate, transition):
            self.attempts += 1
            if self.attempts == 1:
                raise RuntimeError("private local marker")
            await super().commit_candidate(candidate, transition)

    hooks = RetryableHooks({"listing-1": binding})
    client = OpenedRegistryClient()
    client.urls = ["https://r1.example"]
    client.registry_targets = client.registry_targets[:1]
    publication = enabled_runtime(repository, hooks, client)

    first = await publication.refresh(candidate(binding=binding))
    writes = list(client.writes)
    recovered = await publication.recover(candidate(binding=binding), first)

    assert first.failure_stage == "local_commit"
    assert recovered.status == "published"
    assert recovered.local_committed is True
    assert client.writes == writes
    assert hooks.attempts == 2


@pytest.mark.asyncio
async def test_event_and_client_context_failures_preserve_receipts_without_commit():
    binding = CapacityBinding("site-a", "vm", "pool-a")
    repository = Repository()
    hooks = Hooks({"listing-1": binding})
    client = OpenedRegistryClient()
    client.urls = ["https://r1.example"]
    client.registry_targets = client.registry_targets[:1]

    def fail_event(**_values):
        raise RuntimeError("private event marker")

    result = await enabled_runtime(
        repository,
        hooks,
        client,
        on_published=fail_event,
    ).refresh(candidate(binding=binding))

    assert result.failure_stage == "event"
    assert result.target_results[0].state is PublicationTargetState.CONFIRMED
    assert result.receipts_persisted is True
    assert result.event_emitted is False
    assert repository.publications[0]["status"] == "published"
    assert hooks.commits == []
    assert "private event marker" not in repr(result.to_dict())

    class FailingContextClient(OpenedRegistryClient):
        async def __aexit__(self, *_args):
            raise RuntimeError("private context marker")

    repository = Repository()
    hooks = Hooks({"listing-1": binding})
    client = FailingContextClient()
    client.urls = ["https://r1.example"]
    client.registry_targets = client.registry_targets[:1]
    result = await enabled_runtime(repository, hooks, client).refresh(
        candidate(binding=binding)
    )

    assert result.failure_stage == "context"
    assert result.target_results[0].state is PublicationTargetState.CONFIRMED
    assert result.receipts_persisted is True
    assert result.event_emitted is True
    assert repository.publications[0]["status"] == "published"
    assert hooks.commits == []
    assert "private context marker" not in repr(result.to_dict())


@pytest.mark.asyncio
async def test_concurrent_operations_keep_separate_immutable_intents():
    repository = Repository()
    binding = CapacityBinding("site-a", "vm", "pool-a")
    hooks = Hooks({"listing-1": binding, "listing-2": binding})

    class ConcurrentClient(OpenedRegistryClient):
        urls = ["https://r1.example"]
        registry_targets = OpenedRegistryClient.registry_targets[:1]

        def __init__(self):
            self.records = {}
            self.writes = []
            self.published_requests = []

        async def get_listing_from_registry(self, *, registry_url, listing_id):
            if listing_id not in self.records:
                raise RegistryClientError("GET", registry_url, 404, "not found")
            return _summary(offer_mode="vm", listing_id=listing_id)

        async def publish_listing_per_registry(self, *, payloads):
            await __import__("asyncio").sleep(0)
            request = next(iter(payloads.values()))
            self.records[request.listing_id] = request.to_dict()
            self.writes.append((request.listing_id, tuple(payloads)))
            return [
                {
                    "registry_url": url,
                    "success": True,
                    "response": {"listing_id": request.listing_id},
                    "error": None,
                    "error_type": None,
                    "status_code": None,
                    "payload": request.to_dict(),
                    "registry_assigned_id": request.listing_id,
                }
                for url in payloads
            ]

    client = ConcurrentClient()
    publication = enabled_runtime(repository, hooks, client)
    first, second = await __import__("asyncio").gather(
        publication.refresh(candidate("listing-1", binding)),
        publication.refresh(candidate("listing-2", binding)),
    )

    assert first.intent is not None and second.intent is not None
    assert first.intent.listing_id == "listing-1"
    assert second.intent.listing_id == "listing-2"
    assert first.intent is not second.intent
    assert {listing_id for listing_id, _targets in client.writes} == {
        "listing-1",
        "listing-2",
    }


@pytest.mark.asyncio
async def test_recovery_rejects_changed_target_trust_before_read_or_write():
    repository = Repository()
    binding = CapacityBinding("site-a", "vm", "pool-a")
    hooks = Hooks({"listing-1": binding})
    client = OpenedRegistryClient()
    publication = enabled_runtime(repository, hooks, client)
    first = await publication.refresh(candidate(binding=binding))
    original_reads = {
        url: list(values) for url, values in client.reads.items()
    }
    original_writes = list(client.writes)
    client.registry_targets = (
        RegistryTargetIdentity(
            configured_url="https://r1.example",
            normalized_url="https://r1.example",
            authority="replacement-authority",
            principals=TrustedIdentitySet(identities=(_AUTHORITY,)),
        ),
        client.registry_targets[1],
    )

    recovered = await publication.recover(candidate(binding=binding), first)

    assert recovered.status == "error"
    assert recovered.failure_stage == "recovery"
    assert recovered.error_type == "ValueError"
    assert client.reads == original_reads
    assert client.writes == original_writes


@pytest.mark.asyncio
async def test_reconciliation_rejects_conflicting_plan():
    repository = Repository()
    binding = CapacityBinding("site-a", "vm", "pool-a")
    hooks = Hooks({"listing-1": binding})

    with pytest.raises(ValueError, match="cannot close and reopen"):
        await runtime(repository, hooks).reconcile(
            ReconciliationPlan(
                close=(BoundListing("listing-1", binding),),
                reopen=(candidate(binding=binding),),
            )
        )
