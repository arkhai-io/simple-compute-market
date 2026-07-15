# POOLS-3 tasks

Status: implemented this session. 303/303 unit tests and 138/138
integration tests pass (full existing suite + 27 new tests), verified in a
clean venv against this repo's actual dependency set.

## Provider contract

- [x] Add `services/fulfillment_provider.py`: `FulfillmentProvider` (ABC),
      `FulfillmentResult`, `ProviderStatus`, `ProviderOperationState`.
      `create`/`teardown` are dispatch-only; `resource`/`provider_metadata`
      stay explicit parameters (this layer has no identity map — see
      Decision 4a for how `FulfillmentService` differs).
- [x] Define this change's own error taxonomy locally (not in
      `compute_provisioning`): `ProviderNotFoundError`,
      `ProviderUnavailableError`, `ProviderConfigInvalidError`,
      `FulfillmentConflictError`, `FulfillmentCreateFailedError`,
      `FulfillmentStatusFailedError`, `FulfillmentTeardownFailedError`.
      Every one has a concrete trigger, wired below.
      `ProviderUnavailableError` is defined but has no trigger yet in this
      change — nothing in the Ansible provider currently distinguishes
      "unavailable" from "config invalid" or "create failed". Left defined
      for the contract's completeness (a future provider may need it);
      flagged here rather than silently unused.

## Ansible provider

- [x] Extend `models/jobs_model.py::AnsibleJobParams` with
      `playbook_path: str | None = None` and
      `provider_extra_vars: dict[str, Any] = field(default_factory=dict)`.
      No migration — `AnsibleJob.params` is already JSON.
- [x] `AnsibleJobService._build_params()` restores both fields from the
      persisted dict.
- [x] `AnsibleJobService._playbook_path_for_params()` prefers
      `params.playbook_path` when present, falling back to the existing
      executor-kind-based selection.
- [x] `AnsibleService._build_vm_vars()` merges `provider_extra_vars` into
      the rendered YAML. Built-in fields are authoritative — a colliding
      key raises `ValueError`, derived dynamically from the keys already
      emitted (not a hand-maintained list, so it can't silently drift out
      of sync with the fields above it).
      **Correction from the original task description**: this collision
      check does NOT run synchronously inside `AnsibleFulfillmentProvider.
      create()`. `build_vars_file`/`_build_vm_vars` only runs later, inside
      `AnsibleJobService._process_job` (the background job worker), not
      inside `submit()`. So a collision surfaces as a *failed job*,
      discoverable via `get_status()` returning `state=failed`, not as an
      exception raised synchronously from `create()`. This is actually
      consistent with the dispatch-only design (Decision 3) — validation
      that can only happen at execution time surfaces as an execution
      failure, same as any other Ansible playbook failure would. Verified
      directly against `_build_vm_vars` in
      `test_ansible_fulfillment_provider.py::TestExtraVarsCollision`
      rather than asserting a synchronous exception from `create()`.
- [x] Add `services/ansible_fulfillment_provider.py`:
      `AnsibleFulfillmentProvider(FulfillmentProvider)`. Depends on
      `job_service`, `resource_pool_service`, `job_queue_provider` (no
      direct `AnsibleService` dependency).
- [x] Provider-local frozen `AnsiblePoolConfig` dataclass (`playbook_path`,
      `extra_vars` — no `inventory_group`).
- [x] `create()`: resolves pool config eagerly (missing pool or missing
      `playbook_path` raises `ProviderConfigInvalidError` synchronously,
      before dispatch — this part *is* checkable pre-flight, unlike the
      extra-vars collision above), submits via `job_service.submit()`,
      wraps unexpected submission failures as `FulfillmentCreateFailedError`.
- [x] `teardown()`: same shape, `vm_action="vm_remove"`, wraps failures as
      `FulfillmentTeardownFailedError`.
- [x] `get_status()`: `LookupError` from `job_service.get_job()` → `unknown`
      (documented 404 signal); any other exception →
      `FulfillmentStatusFailedError`; known job states mapped per the
      table in design.md Decision 3 (`queued`/`running` → `pending`,
      `succeeded` → `succeeded`, `failed`/`cancelled` → `failed`).
- [x] Confirmed `ProgrammableMockAnsibleService` needs no changes — its
      `build_vars_file` is a stub that never calls `_build_vm_vars`.

## Pool config public-contract change (`inventory_group`)

- [x] Removed from `AnsiblePoolConfigHandler._FIELDS` and required-field
      validation.
- [x] `read_config` no longer returns it.
- [x] `replace_config` writes a fixed internal compatibility constant
      (`_UNUSED_INVENTORY_GROUP_COMPAT_VALUE`) into the still-`NOT NULL`
      column instead of a user-supplied value — no migration.
- [x] Updated `tests/integration/test_pools_api.py` (fixture + YAML import
      test + assertion) to match the new contract.
- [x] `tests/unit/test_database.py` needed no change — it exercises
      `db/migrations.py`'s own `default_inventory_group` default-writing
      directly, bypassing the handler entirely; untouched, as planned.
- [x] `db/models.py` and `db/migrations.py` untouched — no schema change.

## Registry

- [x] `services/provider_registry.py`: `ProviderRegistry.require()`.

## Fulfillment service

- [x] `services/fulfillment_service.py`: `FulfillmentService`, no
      `PhysicalSettlementScheduler` dependency. `create` takes a
      `SettlementResource`; `teardown`/`get_status` take only
      `allocation_id` (Decision 4a).
- [x] `FulfillmentEntry` frozen dataclass as the in-memory store's value
      type.
- [x] `create()`: equivalence check scoped to `agreement_id`/`market`/
      `terms` (request) plus the full stored `SettlementResource` —
      explicitly excludes `request.resource_id`. Mismatch raises
      `FulfillmentConflictError` before any provider call.
- [x] `teardown()`: idempotent via `entry.teardown_result`.
- [x] `get_status(allocation_id, operation="create"|"teardown")`: selects
      the right stored `FulfillmentResult`'s `provider_metadata`.
- [x] In-memory `dict[str, FulfillmentEntry]`, documented as non-durable
      and not a concurrency guarantee (pools-7 replaces it).

## DI wiring

- [x] `container.py`: `ansible_fulfillment_provider` (with
      `job_queue_provider=_resolved_job_queue` — the item the external
      review caught missing from the original plan), `provider_registry`,
      `fulfillment_service`. No dependency on `physical_settlement_scheduler`.
- [x] `app_runtime.py`: `resolved_fulfillment_service` added to
      `resolve_request_path_services()` and declared in `container.py`'s
      `resolved_*` block. No controller/route wired.

## Tests

- [x] `test_fulfillment_provider.py`, `test_provider_registry.py`,
      `test_fulfillment_service.py`, `test_ansible_fulfillment_provider.py`
      — 27 new tests, all passing.
- [x] `test_pools_api.py` updated for the `inventory_group` contract
      change.
- [x] Full existing suite reverified: 276 pre-existing unit tests + 138
      integration tests all still pass unchanged.

## Docs

- [x] `proposal.md`/`design.md`/spec delta were finalized during the
      design-review session before implementation; no drift found during
      implementation except the extra-vars collision-timing detail noted
      above, which doesn't change any documented decision — the mechanism
      described (built-ins authoritative, collision rejected) is exactly
      what's implemented, just observed via `get_status` rather than a
      synchronous exception, which the dispatch-only model already implied.
- [ ] `docs/development/ARCHITECTURE.md`: not updated this round. The
      existing one-line summary (added during the design-review session)
      still accurately describes the current state — provisioning-side
      fulfillment service owns idempotent physical dispatch, no storefront
      wiring yet. Revisit when `pools-7` gives this a production caller.
