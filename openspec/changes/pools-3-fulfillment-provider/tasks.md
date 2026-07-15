# POOLS-3 tasks

## Provider contract

- [ ] Add `services/fulfillment_provider.py`: `FulfillmentProvider` (ABC),
      `FulfillmentResult` (frozen dataclass, `provider_metadata` only — no
      `credentials` field), `ProviderStatus` (frozen dataclass wrapping
      `ProviderOperationState`), and `ProviderOperationState` (str enum:
      `pending` / `succeeded` / `failed` / `unknown`). `create` and
      `teardown` are both abstract, async, and dispatch-only (return
      `FulfillmentResult` immediately after the underlying work is
      accepted, not after it completes); `get_status` is abstract and
      returns `ProviderStatus`.
- [ ] Define this change's own error taxonomy locally in the VM
      provisioning service (not in `compute_provisioning`): `ProviderNotFoundError`,
      `ProviderUnavailableError`, `ProviderConfigInvalidError`,
      `FulfillmentConflictError`, `FulfillmentCreateFailedError`,
      `FulfillmentStatusFailedError`, `FulfillmentTeardownFailedError`.
      Note: `pools-2` put its equivalent taxonomy in
      `compute_provisioning/physical_settlement.py` since
      `PhysicalSettlementRequest`/`SettlementResource` already live there.
      This change's new errors are kept VM-service-local instead, to honor
      `proposal.md`'s "no change to `provisioning/compute` this round" —
      revisit if/when `pools-5` extracts these contracts to a shared
      package, at which point reconciling with `pools-2`'s precedent makes
      sense.

## Ansible provider

- [ ] Add `services/ansible_fulfillment_provider.py`: `AnsibleFulfillmentProvider(FulfillmentProvider)`
      wrapping the existing `AnsibleJobService`/`AnsibleService`. Define the
      provider-local frozen `AnsiblePoolConfig` dataclass (`playbook_path`,
      `extra_vars` — no `inventory_group`; see design.md Decision 6).
- [ ] `create()`: resolve `resource_pool_service.get_pool(resource.pool_id).provider_config`,
      validate/translate it into Ansible job variables, snapshot those
      resolved inputs into the submitted job's stored parameters (not just
      a `pool_id` reference — see design.md's snapshotting requirement),
      submit via `AnsibleJobService.submit()`, and return
      `FulfillmentResult(provider_metadata={"job_id": ..., "operation": "create"})`.
- [ ] `teardown()`: same dispatch-only shape as `create()`, targeting
      `vm_action="vm_remove"` (or the resource's equivalent), returning
      `FulfillmentResult(provider_metadata={"job_id": ..., "operation": "teardown"})`.
- [ ] `get_status()`: look up the job via `provider_metadata["job_id"]`,
      map `AnsibleJobService`'s job status to `ProviderOperationState`
      per design.md's table (`queued/running/retrying` → `pending`,
      `succeeded` → `succeeded`, `failed/cancelled` → `failed`,
      missing/unreadable → `unknown`).
- [ ] Confirm `ProgrammableMockAnsibleService` (selected via the `mockMode`
      profile flag in `_make_ansible_service`) requires no changes — the
      provider sits above `AnsibleJobService`/`AnsibleService` and the mock
      seam is unaffected.
- [ ] Do not touch `AnsiblePoolConfigHandler`, `db/models.py`, or
      `db/migrations.py` — the DB-facing `inventory_group` field stays
      required and populated exactly as today; only the provider's own
      typed config stops reading it. No DB/migration work this round.

## Registry

- [ ] Add `services/provider_registry.py`: `ProviderRegistry` with
      `require(provider: str) -> FulfillmentProvider`, raising
      `ProviderNotFoundError` for an unregistered provider string.

## Fulfillment service

- [ ] Add `services/fulfillment_service.py`: `FulfillmentService`, taking
      `provider_registry` as a dependency. It does **not** depend on or
      call `PhysicalSettlementScheduler` — `create`/`teardown` both take an
      already-selected `SettlementResource` as an input parameter (see
      design.md Decision 1).
- [ ] `create(request: PhysicalSettlementRequest, resource: SettlementResource) -> FulfillmentResult`:
      validate the request against the supplied resource, check the
      in-memory idempotency store (below) for an existing fulfillment
      keyed on `allocation_id` — equivalent request (same agreement,
      resource, provider, fulfillment identity) returns the existing
      result; conflicting reuse raises `FulfillmentConflictError` before
      any provider call; otherwise resolve the provider via
      `ProviderRegistry.require(resource.provider)` and dispatch.
- [ ] `teardown(allocation_id, resource, provider_metadata) -> FulfillmentResult`:
      same idempotency treatment — retried teardown for the same
      fulfillment is detected and does not dispatch a second provider
      operation.
- [ ] `get_status(allocation_id, resource, provider_metadata) -> ProviderStatus`:
      thin pass-through to the resolved provider's `get_status`.
- [ ] Idempotency store: a plain in-memory `dict[str, ...]` keyed on
      `allocation_id`, private to `FulfillmentService`. Explicitly **not**
      a concurrency guarantee and not durable — matches
      `PhysicalSettlementScheduler`'s own in-memory pattern. Leave a
      docstring/comment pointing at `pools-7` for the durable, race-safe
      replacement, consistent with design.md Decision 4.

## DI wiring

- [ ] `container.py`: add `ansible_fulfillment_provider` (Singleton,
      depends on `job_service`/`resource_pool_service`), `provider_registry`
      (Singleton, registers `"ansible" -> ansible_fulfillment_provider`),
      and `fulfillment_service` (Singleton, depends on `provider_registry`).
      Do not wire `physical_settlement_scheduler` as a dependency of
      `fulfillment_service` — they stay independent providers in the
      container, exactly as they are independent classes.
- [ ] `app_runtime.py` / `container.py`'s `resolved_*` block: add
      `resolved_fulfillment_service`, set in
      `resolve_request_path_services()`, following the existing pattern
      (e.g. `resolved_physical_settlement_scheduler`). No controller/route
      wires it yet — this is just making the singleton resolvable the same
      way the scheduler already is, for `pools-7` to consume later.

## Tests

- [ ] `tests/unit/services/test_fulfillment_provider.py`: `ProviderOperationState`
      mapping/enum sanity, `FulfillmentResult`/`ProviderStatus` shape.
- [ ] `tests/unit/services/test_ansible_fulfillment_provider.py`: create/teardown
      are dispatch-only (return before the background job completes, using
      `ProgrammableMockAnsibleService`'s job-control hooks); config
      snapshotting (editing the pool after dispatch does not change an
      already-accepted operation); `get_status` state mapping, including
      `unknown` on an unreadable/missing job.
- [ ] `tests/unit/services/test_provider_registry.py`: `require()` success
      and `ProviderNotFoundError` for an unregistered provider string.
- [ ] `tests/unit/services/test_fulfillment_service.py`: equivalent-retry
      returns the existing result without a second provider dispatch
      (assert the provider mock's create/teardown call count);
      conflicting reuse (different agreement/resource/provider for the
      same `allocation_id`) raises `FulfillmentConflictError` before any
      provider call; teardown retry is idempotent the same way; provider
      resolution failure propagates `ProviderNotFoundError`. Use a fake
      `FulfillmentProvider` here, not `AnsibleFulfillmentProvider` — this
      is a `FulfillmentService`-boundary test, not an Ansible-integration
      test.
- [ ] Confirm existing `AnsibleJobService`/`AnsibleService`/scheduler test
      suites pass unchanged (this change wraps, not replaces, that
      machinery).

## Docs

- [ ] No further openspec edits expected — `proposal.md`, `design.md`, and
      the `physical-provisioning` spec delta were finalized during this
      session's design review. Re-check them against the actual
      implementation once code is written, and correct anything that
      drifts (same discipline applied throughout this session).
- [ ] Update `docs/development/ARCHITECTURE.md` only if implementation
      reveals the current one-line summary (added this session) needs more
      than a sentence — keep it a current-state description, not a
      changelog entry for this change.
