## 1. Finalize shared contracts and package skeleton

- [ ] 1.1 Create `kit/physical-settlement` using repository-standard Python kit packaging, Makefile, tests, typing marker, and distribution/reinit conventions.
- [ ] 1.2 Define globally unique opaque ID value types for `capacity_reservation_id`, `fulfillment_id`, `provisioned_resource_id`, `settlement_resource_id`, and `result_id`; evaluate UUIDv7 against repository conventions and document the selected format.
- [ ] 1.3 Decide and document whether routing/integrity requires an explicit site-plus-pool composite reference in addition to globally unique `pool_id` and explicit `site_id`.
- [ ] 1.4 Move domain-neutral physical-settlement request/resource types, `PhysicalSettlementScheduler`, and `DeterministicRoundRobinPolicy` into the new kit without introducing VM/storefront dependencies.
- [ ] 1.5 Remove provisioning commercial identity from shared contracts: delete `agreement_id` and rename `allocation_id` to `capacity_reservation_id` across new interfaces.
- [ ] 1.6 Add versioned payload envelopes for prepared provider create/teardown inputs, provider metadata, and `SettlementResult`; prohibit unversioned cross-domain generic dictionaries.
- [ ] 1.7 Add package-boundary/import tests proving dependency direction and carrier purity.

## 2. Reshape site capacity and identifiers

- [ ] 2.1 Rename `SiteAllocation` and related APIs/models/columns to `CapacityReservation` / `capacity_reservation_id` across `kit/site`, provisioning services, clients, fixtures, and tests.
- [ ] 2.2 Implement the approved breaking separation of host identity, resource-pool membership, reservable capacity, and nullable settlement-resource assignment; retire `SiteResource` and obsolete fields where the final model replaces them.
- [ ] 2.3 Add explicit `site_id` ownership and database uniqueness/foreign-key constraints for pools, resources, reservations, fulfillments, and provisioned resources.
- [ ] 2.4 Extract one shared feasibility predicate used by reservation-time admission and scheduling-time eligibility.
- [ ] 2.5 Make ledger unit-claim aliases configurable rather than VM-specific, and remove the scheduler's default VM-flavored `resource_kind` fallback.
- [ ] 2.6 Reject scheduling requirements that exceed the capacity reservation in any governed dimension while permitting smaller shapes.
- [ ] 2.7 Add migration and unit tests for uniqueness, site ownership, host-granular feasibility, and the shared predicate.

## 3. Add shared settlement persistence

- [ ] 3.1 Define shared SQLAlchemy mappings for the fulfillment/settlement aggregate, provisioned-resource outputs, versioned prepared operations, recovery claims, and result-delivery outbox.
- [ ] 3.2 Implement generic SQLAlchemy repositories using caller-supplied sessions so site-capacity and settlement changes can share one transaction.
- [ ] 3.3 Define fulfillment, provider-command, teardown, abandonment, and result-delivery states plus a compact table-driven transition validator.
- [ ] 3.4 Persist canonical request identity/fingerprints and enforce one fulfillment aggregate per `capacity_reservation_id`.
- [ ] 3.5 Implement equivalent retry return and conflicting retry rejection before provider submission.
- [ ] 3.6 Model one fulfillment to many `ProvisionedResource` rows with aggregate status; leave per-resource teardown unexposed unless a current caller requires it.
- [ ] 3.7 Add repository, concurrency, state-transition, and canonicalization tests.

## 4. Implement atomic scheduling

- [ ] 4.1 Replace process-local scheduler assignment and round-robin state with database-backed selection and deterministic persisted fairness state where required.
- [ ] 4.2 Implement `schedule_resource(capacity_reservation_id, requirements)` against the local owning site only.
- [ ] 4.3 In one transaction, lock/validate the active reservation, select an eligible resource, perform any fair capacity rebind, and create or return the immutable assigned settlement record.
- [ ] 4.4 Reject unknown reservation/pool/resource identifiers rather than forwarding, reinterpreting, or trying another site.
- [ ] 4.5 Make changed requirements supersede the reservation instead of mutating an accepted assignment.
- [ ] 4.6 Atomically abandon assigned-but-unfulfilled settlements and release/supersede their capacity during lease lifecycle events; add watchdog reconciliation.
- [ ] 4.7 Add race, retry, rollback, expiry, supersession, and multi-replica scheduling tests.

## 5. Migrate existing hosts and active leases

- [ ] 5.1 Create the default resource pool and migrate all existing hosts and pool-membership/resource-capacity records before fulfillment backfill.
- [ ] 5.2 Backfill a settlement/fulfillment aggregate for every active or releasing VM capacity reservation.
- [ ] 5.3 Derive selected resource, Ansible provider identity, domain resource reference, and versioned teardown input from existing `vm_host`, `vm_target`/`executor_target`, executor identity, and lease data.
- [ ] 5.4 Mark migrated aggregates as backfilled and allow historical create input to be absent for already-active VMs.
- [ ] 5.5 Fail migration visibly when an active reservation cannot be mapped unambiguously; do not create partial teardown records.
- [ ] 5.6 Skip terminal/expired historical allocations unless another retention requirement applies.
- [ ] 5.7 Add migration tests covering active, releasing, expired, ambiguous, duplicate, and rollback cases.

## 6. Implement fulfillment acceptance and provider preparation

- [ ] 6.1 Add `begin_fulfillment(capacity_reservation_id, fulfillment_request)` returning `fulfillment_id`; load the persisted scheduled resource rather than trusting a caller-supplied resource.
- [ ] 6.2 Preserve `FulfillmentService`'s boundary: it receives an already-selected `SettlementResource` and does not call the scheduler.
- [ ] 6.3 Split provider behavior into synchronous `prepare_create`/`prepare_teardown` and post-commit `dispatch_create`/`dispatch_teardown` operations.
- [ ] 6.4 Validate and persist versioned prepared input in the same transaction that accepts a pending provider command.
- [ ] 6.5 Submit Ansible create/teardown through `ExecutorActionEnvelope` or the equivalent contract-deduplication path using deterministic action/version keys.
- [ ] 6.6 Persist provider job identity and normalized provider metadata without exposing VM-specific job state as the cross-domain lifecycle contract.
- [ ] 6.7 Add tests for equivalent/conflicting retries, pool-config mutation after acceptance, duplicate submission races, and create/teardown command deduplication.

## 7. Add provisioning-owned recovery and lifecycle convergence

- [ ] 7.1 Implement a periodic multi-replica-safe watchdog framework with bounded database claims/leases, claim expiry, attempt counters, exponential backoff with jitter, and no locks held during external calls.
- [ ] 7.2 Add separate handlers for create submission recovery, create status convergence, teardown submission recovery, teardown status convergence, and abandonment reconciliation.
- [ ] 7.3 Persist normalized fulfillment and teardown terminal states plus provisioned-resource outputs independently of storefront availability.
- [ ] 7.4 Ensure pending and in-progress records recover after process restart, transient provider failure, and worker death.
- [ ] 7.5 Add metrics and structured operator diagnostics for stuck claims, retry age, provider failures, and non-terminal lifecycle age.
- [ ] 7.6 Add crash-window, restart, multi-replica, backoff, and eventual-convergence tests.

## 8. Implement durable pushed SettlementResult delivery

- [ ] 8.1 Define the versioned `SettlementResult` contract containing `result_id`, `fulfillment_id`, `capacity_reservation_id`, aggregate state, provisioned-resource outputs, failure details, and credential-generation metadata without persisted raw credentials.
- [ ] 8.2 Insert the result-delivery outbox row atomically with each reportable fulfillment transition.
- [ ] 8.3 Add an authenticated storefront result-receiver endpoint/client contract that deduplicates by `result_id`, persists before acknowledgement, and rejects incorrectly routed site/reservation results.
- [ ] 8.4 Implement a delivery worker handler that claims due rows, obtains or refreshes credentials just in time, sends them only in memory over the authenticated encrypted channel, and records acknowledgement or retry state.
- [ ] 8.5 Implement capped exponential backoff with jitter and indefinite retry while the fulfillment remains active; do not dead-letter buyer credential delivery after a fixed attempt count.
- [ ] 8.6 Add monotonic `credential_generation` handling so stale retries cannot replace newer credentials.
- [ ] 8.7 Keep fulfillment state separate from result-delivery state and expose metrics, alerts, audit history, oldest-undelivered age, and a manual replay operation.
- [ ] 8.8 Add tests for crash-before-send, crash-after-send, lost acknowledgement, duplicate delivery, storefront outage, credential refresh/rotation, stale generation, restart, and manual replay.

## 9. Cut over storefront orchestration

- [ ] 9.1 Replace host-shaped ordinary storefront reservation assumptions with the implemented POOLS-4 capacity-reservation claim and owning-site routing.
- [ ] 9.2 Replace direct `ExecutorActionEnvelope` submission and provider-job polling with `schedule_resource` followed by `begin_fulfillment` when the commercial workflow is ready.
- [ ] 9.3 Persist `capacity_reservation_id`, selected settlement resource, and returned `fulfillment_id` in storefront workflow state so negotiation and fulfillment resume after restart.
- [ ] 9.4 Consume pushed `SettlementResult` idempotently and deliver/retain buyer-facing credential state according to the storefront's security model.
- [ ] 9.5 Map VM-domain job/provider states to the shared fulfillment lifecycle invariant without leaking raw VM job status cross-domain.
- [ ] 9.6 Remove `create_vm_and_wait_with_credentials` and ordinary storefront polling/direct executor dispatch after all callers are migrated; tombstone deleted paths where repository workflow requires it.
- [ ] 9.7 Add storefront restart, duplicate result, site-routing, negotiation-resume, and end-to-end credential-delivery tests.

## 10. Cut over teardown and physical-resource reclamation

- [ ] 10.1 Add `begin_fulfillment_teardown(fulfillment_id)` as the whole-fulfillment teardown contract; keep `provisioned_resource_id` in the schema for a future per-resource teardown extension.
- [ ] 10.2 Resolve the backfilled or native fulfillment aggregate, prepare versioned teardown input, and persist teardown-pending state before provider submission.
- [ ] 10.3 Drive teardown submission, retry, status convergence, final resource reclamation, and capacity release entirely from provisioning-owned watchdog handlers.
- [ ] 10.4 Do not return physical capacity to scheduling until teardown succeeds or an explicit operator recovery action resolves the resource.
- [ ] 10.5 Replace the old `VmReleaseExecutor` direct path once backfilled and new fulfillments use settlement teardown; remove the legacy fallback rather than retaining a cutover marker.
- [ ] 10.6 Add idempotent repeated teardown, partial failure, restart, lost submission acknowledgement, backfilled VM, and final capacity-release tests.

## 11. Remove obsolete schema and compatibility paths

- [ ] 11.1 Remove superseded `allocation_id`, `SiteAllocation`, direct-host storefront placement, process-local settlement maps/locks, and obsolete executor/provider fields after migrations and callers are complete.
- [ ] 11.2 Reassess and remove/reduce storefront `fill_first`/`most_available` physical-placement behavior now that physical scheduling belongs to the provisioning service; retain only pre-reservation site/pool policy that remains meaningful.
- [ ] 11.3 Update container composition, package dependencies, wheel/reinit targets, Docker images, and deployment configuration for `kit/physical-settlement` and its watchdog/result-delivery workers.
- [ ] 11.4 Ensure logs, traces, exception payloads, and request logging redact credentials and prepared secret material.
- [ ] 11.5 Run repository-wide import, typing, migration, unit, integration, and end-to-end suites and fix all renamed-contract consumers.

## 12. Documentation and specification closure

- [ ] 12.1 Update `ARCHITECTURE.md` service map, terminology table, ID definitions, lifecycle ownership, transaction boundaries, recovery workers, pushed-result protocol, and teardown flow.
- [ ] 12.2 Update baseline `site-capacity` and `physical-provisioning` specs to incorporate completed POOLS-2/3/4/6/7 behavior when the change is archived.
- [ ] 12.3 Update VM provisioning/storefront README and operator documentation for migrations, watchdog health, result-delivery alerts, manual replay, and recovery procedures without lease-expiry sequencing instructions.
- [ ] 12.4 Verify the implementation against every POOLS-7 scenario and archive the OpenSpec change after validation.
