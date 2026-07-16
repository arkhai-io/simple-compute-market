# POOLS-3 tasks

## Provider contract

- [x] **Superseded by the implementation-review correction:** add the provider-neutral contract in `kit/resource-pools` instead of `services/fulfillment_provider.py`: `FulfillmentProvider` (ABC),
      `FulfillmentResult` (frozen dataclass, `provider_metadata` only — no
      `credentials` field), `ProviderStatus` (frozen dataclass wrapping
      `ProviderOperationState`), and `ProviderOperationState` (str enum:
      `pending` / `succeeded` / `failed` / `unknown`). `create` and
      `teardown` are both abstract, async, and dispatch-only (return
      `FulfillmentResult` immediately after the underlying work is
      accepted, not after it completes); `get_status` is abstract and
      returns `ProviderStatus`.
- [x] **Superseded by the implementation-review correction:** define the error taxonomy in the shared `kit/resource-pools` contract rather than locally in the VM
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

- [x] Add `services/ansible_fulfillment_provider.py`: `AnsibleFulfillmentProvider(FulfillmentProvider)`
      wrapping the existing `AnsibleJobService`/`AnsibleService`. Define the
      provider-local frozen `AnsiblePoolConfig` dataclass (`playbook_path`,
      `extra_vars` — no `inventory_group`; see design.md Decision 6).
- [x] `create()`: resolve `resource_pool_service.get_pool(resource.pool_id).provider_config`,
      validate/translate it into Ansible job variables, snapshot those
      resolved inputs into the submitted job's stored parameters (not just
      a `pool_id` reference — see design.md's snapshotting requirement),
      submit via `AnsibleJobService.submit()`, and return
      `FulfillmentResult(provider_metadata={"job_id": ..., "operation": "create"})`.
- [x] `teardown()`: same dispatch-only shape as `create()`, targeting
      `vm_action="vm_remove"` (or the resource's equivalent), returning
      `FulfillmentResult(provider_metadata={"job_id": ..., "operation": "teardown"})`.
- [x] `get_status()`: look up the job via `provider_metadata["job_id"]`,
      map `AnsibleJobService`'s job status to `ProviderOperationState`
      per design.md's table (`queued/running/retrying` → `pending`,
      `succeeded` → `succeeded`, `failed/cancelled` → `failed`,
      missing/unreadable → `unknown`).
- [x] Confirm `ProgrammableMockAnsibleService` (selected via the `mockMode`
      profile flag in `_make_ansible_service`) requires no changes — the
      provider sits above `AnsibleJobService`/`AnsibleService` and the mock
      seam is unaffected.
- [x] **Superseded in part by synchronous validation requirements:** no database or migration changes were needed; `AnsiblePoolConfigHandler` may share the extracted provider-config validator. Original instruction: do not touch `db/models.py` or
      `db/migrations.py` — the DB-facing `inventory_group` field stays
      required and populated exactly as today; only the provider's own
      typed config stops reading it. No DB/migration work this round.

## Registry

- [x] **Superseded by the implementation-review correction:** add the shared registry in `kit/resource-pools` instead of `services/provider_registry.py`: `ProviderRegistry` with
      `require(provider: str) -> FulfillmentProvider`, raising
      `ProviderNotFoundError` for an unregistered provider string.

## Fulfillment service

- [x] Add `services/fulfillment_service.py`: `FulfillmentService`, taking
      `provider_registry` as a dependency. It does **not** depend on or
      call `PhysicalSettlementScheduler` — `create`/`teardown` both take an
      already-selected `SettlementResource` as an input parameter (see
      design.md Decision 1).
- [x] `create(request: PhysicalSettlementRequest, resource: SettlementResource) -> FulfillmentResult`:
      validate the request against the supplied resource, check the
      in-memory idempotency store (below) for an existing fulfillment
      keyed on `allocation_id` — equivalent request (same agreement,
      resource, provider, fulfillment identity) returns the existing
      result; conflicting reuse raises `FulfillmentConflictError` before
      any provider call; otherwise resolve the provider via
      `ProviderRegistry.require(resource.provider)` and dispatch.
- [x] `teardown(allocation_id, resource, provider_metadata) -> FulfillmentResult`:
      same idempotency treatment — retried teardown for the same
      fulfillment is detected and does not dispatch a second provider
      operation.
- [x] `get_status(allocation_id, resource, provider_metadata) -> ProviderStatus`:
      thin pass-through to the resolved provider's `get_status`.
- [x] Idempotency store: a plain in-memory `dict[str, ...]` keyed on
      `allocation_id`, private to `FulfillmentService`. Explicitly **not**
      a concurrency guarantee and not durable — matches
      `PhysicalSettlementScheduler`'s own in-memory pattern. Leave a
      docstring/comment pointing at `pools-7` for the durable, race-safe
      replacement, consistent with design.md Decision 4.

## DI wiring

- [x] `container.py`: add `ansible_fulfillment_provider` (Singleton,
      depends on `job_service`/`resource_pool_service`), `provider_registry`
      (Singleton, registers `"ansible" -> ansible_fulfillment_provider`),
      and `fulfillment_service` (Singleton, depends on `provider_registry`).
      Do not wire `physical_settlement_scheduler` as a dependency of
      `fulfillment_service` — they stay independent providers in the
      container, exactly as they are independent classes.
- [x] `app_runtime.py` / `container.py`'s `resolved_*` block: add
      `resolved_fulfillment_service`, set in
      `resolve_request_path_services()`, following the existing pattern
      (e.g. `resolved_physical_settlement_scheduler`). No controller/route
      wires it yet — this is just making the singleton resolvable the same
      way the scheduler already is, for `pools-7` to consume later.

## Tests

- [x] `tests/unit/services/test_fulfillment_provider.py`: `ProviderOperationState`
      mapping/enum sanity, `FulfillmentResult`/`ProviderStatus` shape.
- [x] `tests/unit/services/test_ansible_fulfillment_provider.py`: create/teardown
      are dispatch-only (return before the background job completes, using
      `ProgrammableMockAnsibleService`'s job-control hooks); config
      snapshotting (editing the pool after dispatch does not change an
      already-accepted operation); `get_status` state mapping, including
      `unknown` on an unreadable/missing job.
- [x] `tests/unit/services/test_provider_registry.py`: `require()` success
      and `ProviderNotFoundError` for an unregistered provider string.
- [x] `tests/unit/services/test_fulfillment_service.py`: equivalent-retry
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

- [x] No further openspec edits expected — `proposal.md`, `design.md`, and
      the `physical-provisioning` spec delta were finalized during this
      session's design review. Re-check them against the actual
      implementation once code is written, and correct anything that
      drifts (same discipline applied throughout this session).
- [x] Update `docs/development/ARCHITECTURE.md` only if implementation
      reveals the current one-line summary (added this session) needs more
      than a sentence — keep it a current-state description, not a
      changelog entry for this change.

## Corrections from implementation review

- [x] Move provider-neutral fulfillment contracts and the provider registry to
      `kit/resource-pools`; leave the concrete `FulfillmentService` in the VM
      provisioning service. Replace the migrated service files with tombstones
      so their manual deletion is visible during review.
- [x] Rename `PhysicalSettlementRequest.terms` to `requirements`. Keep deal-term
      translation in storefront code; provisioning receives concrete technical
      requirements and validates them independently against the allocation.
- [x] Add typed VM fulfillment requirements containing the complete create
      shape, including deterministic `vm_target`, image, vCPU, memory, disk, and
      SSH key inputs. Do not source these values from pool configuration or the
      Capacity Reservation.
- [x] Preserve typed Ansible provider metadata containing operation identity,
      `vm_host`, and `vm_target`; teardown MUST submit `vm_remove` with both the
      exact host and target.
- [x] Validate disabled pools, pool/resource/provider mismatches, missing
      `vm_host`, malformed VM requirements, and reserved Ansible variable
      collisions before provider dispatch.
- [x] Add a side-effect-free `FulfillmentService.validate_create(...)` path and
      use that same validation from create.
- [ ] Expose the shared validation path through the public dry-run endpoint when
      the fulfillment controller is introduced.
- [x] Add atomic capacity-ledger settlement assignment. Rebinding an allocation
      transfers its existing held units from the reservation resource to the
      selected settlement resource in one transaction; fulfillment MUST NOT
      subtract capacity again.
- [ ] Add integration coverage that inspects persisted outbound Ansible create
      and teardown parameters, including `vm_host`, `vm_target`, and every VM
      create field.
- [x] Add capacity-rebind rollback/idempotency tests and document the current
      concurrent idempotency limitation.
- [x] Update the provisioning service `reinit` target to upgrade and reinstall
      `arkhai-kit-resource-pools`, ensuring `make test` consumes the wheel built
      by the repository-level `make dist` target even when the package version
      is unchanged.
- [x] Record mutable provider-configuration snapshot and durable concurrent
      idempotency concerns in POOLS-7 rather than solving them with a
      process-local lock in POOLS-3.
