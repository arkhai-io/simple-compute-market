## 1. Relocate `ResourcePoolService` to `kit/resource-pools`

- [x] 1.1 Create `kit/resource-pools/` scaffold: `pyproject.toml` (`arkhai-kit-resource-pools`, deps `pydantic>=2.7`, `sqlalchemy>=2.0`), `Makefile` (copy `kit/site`'s build target shape), `src/market_resource_pools/__init__.py`, `tests/unit/`.
- [x] 1.2 Move `ResourcePool` ORM model and `DEFAULT_POOL_ID` from `domains/vms/provisioning/service/src/db/models.py` into `kit/resource-pools/src/market_resource_pools/db.py` (own `Base`).
- [x] 1.3 Move `ResourcePoolService`, `PoolDefinition`, `DocumentValidationResult`, `ReconciliationPlan`, `PoolNotFoundError`, `PoolAlreadyExistsError`, `PoolValidationError` from `domains/vms/provisioning/service/src/services/resource_pool_service.py` into `kit/resource-pools/src/market_resource_pools/service.py`; drop the `AnsiblePoolConfigHandler` default-import fallback, requiring `handlers` to be injected explicitly.
- [x] 1.4 Update `domains/vms/provisioning/service/src/db/models.py` to re-export `ResourcePool`/`DEFAULT_POOL_ID` from `market_resource_pools.db`, matching the existing `market_site.db` re-export block.
- [x] 1.5 Update `domains/vms/provisioning/service/src/db/database.py` to `create_all` the new package's `Base.metadata` alongside the existing two.
- [x] 1.6 Update `_migrate_resource_pools_and_hosts_pool_id` in `db/migrations.py` to create the table from the new package's metadata.
- [x] 1.7 Update `container.py`, `pools_controller.py`, `ansible_pool_config_handler.py` (if needed) import paths.
- [x] 1.8 Add `arkhai-kit-resource-pools` to `domains/vms/provisioning/service/pyproject.toml` dependencies.
- [x] 1.9 Add `dist-kit-resource-pools` to the root `Makefile` (`.PHONY`, target body, `dist:` list).
- [x] 1.10 Move `test_resource_pool_service.py` into `kit/resource-pools/tests/unit/`, updating imports only.
- [x] 1.11 Update `test_pools_api.py` and `test_database.py` import paths only.
- [x] 1.12 Tombstone the old `resource_pool_service.py` and its old test location.
- [x] 1.13 Run `kit/resource-pools` and VM provisioning service unit/integration suites; confirm no behavior change.

## 2. Correct default-pool disable behavior

- [x] 2.1 Remove `_ensure_default_pool_enabled` and its three call sites from `market_resource_pools/service.py`.
- [x] 2.2 Remove the `default_pool_disabled` validation-problem branch from the YAML import validator.
- [x] 2.3 Replace "disabling default is rejected" test cases with "disabling default succeeds; omitted-pool-id hosts still resolve to it" in both the relocated unit tests and `test_pools_api.py`.

## 3. Capacity reservation watchdog

- [x] 3.1 Promote `_expire_stale_holds` to a public `expire_due_holds` on `CapacityLedgerService` (`kit/site/src/market_site/ledger.py`).
- [x] 3.2 Add `kit/site/tests/unit/test_ledger.py` case exercising `expire_due_holds` directly (not only via `reserve`).
- [x] 3.3 Add `domains/vms/provisioning/service/src/services/capacity_reservation_watchdog.py`, mirroring `lease_watchdog.py`.
- [x] 3.4 Add `capacity_reservation_watchdog` provider to `container.py`.
- [x] 3.5 Add startup wiring to `app_runtime.py`, mirroring the lease-watchdog block.
- [x] 3.6 Add `capacity_reservation_watchdog_enabled`/`_poll_interval_seconds` to `settings.toml`.
- [x] 3.7 Add `test_capacity_reservation_watchdog.py`.

## 4. `PhysicalSettlementScheduler`

- [x] 4.1 Add `PhysicalSettlementRequest`/`SettlementResource` pydantic models to `provisioning/compute/src/compute_provisioning/physical_settlement.py`.
- [x] 4.2 Add `domains/vms/provisioning/service/src/services/physical_settlement_scheduler.py`: pool eligibility via `ResourcePoolService`, per-pool utilization via `CapacityLedgerService` + `Host.pool_id` join, dimension-agnostic bottleneck-normalized selection, in-memory `allocation_id → SettlementResource` binding store, explicit `resource_id` path honored without substitution.
- [x] 4.3 Add `physical_settlement_scheduler` provider to `container.py`.
- [x] 4.4 Add the active-binding guardrail to `ResourcePoolService.disable_pool`, wired to the scheduler via a late-bound lookup callable (mirroring `_resolved_job_queue`'s pattern), avoiding a circular DI dependency.
- [x] 4.5 Add `provisioning/compute/tests/unit/test_physical_settlement.py`.
- [x] 4.6 Add `test_physical_settlement_scheduler.py`: idempotency by `allocation_id`, disabled/exhausted-pool exclusion, explicit `resource_id` binding, no-match error, concurrent-selection race, multi-dimension bottleneck selection.
- [x] 4.7 Add active-binding guardrail case to `test_pools_api.py`.

## 5. Documentation sync

- [x] 5.1 Update `docs/development/ARCHITECTURE.md` to reflect only what has actually landed and passed its tests at the point this task is done (per working-note: no unimplemented-feature prose).
- [x] 5.2 Re-run `openspec validate --all --strict`.
