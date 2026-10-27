## 1. Finalize shared contracts and package skeleton

- [x] 1.0 Verify `pools-6-multidimensional-fair-scheduling` has landed and `Host` (or its replacement) carries real memory/disk/vCPU capacity fields before proceeding past task 1. `proposal.md` lists this as a blocking prerequisite for reservation-admission work (tasks 2 and 4) — this task exists so the plan fails loudly rather than silently proceeding without it if implementation ever starts out of the intended POOLS-6-then-POOLS-7 order. **Resolved: built deliberately on `pools-6` pass 1 (the dimensions map); pass 2 (per-dimension `Host` fields) stays `pools-6` scope (design.md, "Dependency on POOLS-6").**
- [x] 1.1 Create `kit/fulfillment` using repository-standard Python kit packaging, Makefile, tests, typing marker, and distribution/reinit conventions.
- [x] 1.2 Define globally unique opaque ID value types for `capacity_reservation_id`, `fulfillment_id`, `provisioned_resource_id`, `settlement_resource_id`, and `result_id`; evaluate UUIDv7 against repository conventions and document the selected format. **Resolved: UUIDv7 via the `uuid6` package (design.md, "Final planning decisions").**
- [x] 1.3 Decide and document whether routing/integrity requires an explicit site-plus-pool composite reference in addition to globally unique `pool_id` and explicit `site_id`. **Resolved: not needed (design.md, "Final planning decisions").**
- [x] 1.4 Move domain-neutral fulfillment request/resource types, `PhysicalSettlementScheduler`, and `DeterministicRoundRobinPolicy` into the new kit without introducing VM/storefront dependencies.
- [x] 1.5 Remove provisioning commercial identity from shared contracts: delete `agreement_id` and rename `allocation_id` to `capacity_reservation_id` across new interfaces.
- [x] 1.6 Add versioned payload envelopes for prepared provider create/teardown inputs, provider metadata, and `SettlementResult`; prohibit unversioned cross-domain generic dictionaries. (Envelope shape only this section — concrete payload kinds land with the sections that need them, per envelopes.py's docstring.)
- [x] 1.7 Add package-boundary/import tests proving dependency direction and carrier purity.

### Section 1 correction pass

- [x] 1.8 Rename the shared package to `kit/fulfillment` / `arkhai-kit-fulfillment` / `market_fulfillment` and update touched consumers.
- [x] 1.9 Move `FulfillmentProvider`, `ProviderRegistry`, and provider-neutral lifecycle contracts from `kit/resource-pools` into `kit/fulfillment`; remove the reverse lower-layer dependency.
- [x] 1.10 Keep pure carrier modules separate from operational scheduler modules and document the foundation → authority → fulfillment dependency hierarchy.
- [x] 1.11 Keep opaque UUIDv7 string identifiers; do not introduce explicit wrapper types.
- [x] 1.12 Require non-empty envelope kinds, positive versions, typed payload validation, JSON round trips, and immutable envelopes.
- [x] 1.13 Add `py.typed` and verify the built fulfillment wheel contains it.
- [x] 1.14 Remove newly introduced editable sibling-path dependencies from touched projects and consume internal packages from `.dist`.
- [x] 1.15 Make the aggregate kit test target build prerequisite wheels and run every kit suite, including site, resource-pools, and fulfillment.
- [x] 1.16 Expand package-boundary tests to include type-only imports and lower-layer kit constraints.
- [x] 1.17 Replace removed or renamed paths with review-only tombstones and remove production comments referring to tombstones. Manual deletion remains required after review.
- [x] 1.18 Update `ARCHITECTURE.md` and POOLS-7 design/proposal with package ownership, dependency direction, wheel conventions, and terminology.

### Section 1 documentation-system retrofit

- [x] Preserve the completed Section 1 task history and add this retrofit as a separate completed workstream.
- [x] Add root `AGENTS.md` with discuss/plan/implement, documentation-promotion, production-comment, wheel, validation, and tombstone rules.
- [x] Expand `openspec/README.md` with permanent-vs-change placement rules, subsystem-spec structure, documentation-impact declarations, promotion records, and completion criteria.
- [x] Rebuild `docs/development/ARCHITECTURE.md` as the current repository-wide map for system shape, package layers, authorities, vocabulary, major flows, deployment, packaging, and tests.
- [x] Add `openspec/specs/fulfillment/spec.md` and promote approved POOLS scheduling/provider/identifier/envelope decisions into it.
- [x] Cross-link site-capacity, resource-pool-management, physical-provisioning, and deployment-state specs to the fulfillment and wheel-development boundaries they own.
- [x] Add the POOLS-7 design-promotion record mapping accepted decisions to permanent documentation.
- [x] Replace Section 1 changelog/task/change-document comments and docstrings with present-tense rationale and stable spec references.

### Section 1 validation corrections

- [x] Replace stale `allocation_id` local references in fulfillment teardown and status paths with `capacity_reservation_id`.
- [x] Configure the isolated VM lease-lifecycle test ledger with the same `gpu_count` claim alias used by the production composition root.
- [x] Re-run the affected fulfillment and lease-lifecycle tests as part of repository validation.

## 2. Reshape site capacity and identifiers

- [x] 2.1 Rename `SiteAllocation` and related APIs/models/columns to `CapacityReservation` / `capacity_reservation_id` across `kit/site`, provisioning services, clients, fixtures, and tests. **Done: `kit/site` (canonical), `kit/fulfillment`, `provisioning/compute` (+ service), `domains/bare_metal`, `domains/vms` (storefront + provisioning adapter/client), `core/storefront` (+ client), `domains/apicredits`, and e2e tests. Current-schema migrations rename the live reservation tables and columns while historical migrations retain the schema names they originally created. Unrelated allocation concepts such as `allocation_mode` and storefront-local compute-allocation bookkeeping remain unchanged.**
- [x] 2.2 Implement the approved breaking separation of host identity, resource-pool membership, reservable capacity, and nullable settlement-resource assignment; retire `SiteResource` and obsolete fields where the final model replaces them. Includes retiring the storefront's host/resource sync push in favor of deriving `site_resource_pools` from the provisioning service's own `Host`/`ResourcePool` tables.
- [x] 2.3 **Rescoped during code review (2026-07-22):** this is not `kit/site`/`kit/resource-pools` schema work. Provisioning-owned single-site databases must not redundantly store storefront-owned `site_id`. The remaining durability gap is storefront-side connection-to-site identity, currently held only in process-local aggregation state; complete or relocate this task with the durable storefront persistence work in Section 3 / POOLS-8 rather than solving it piecemeal here. **Resolved (2026-08-03): no code needed.** `AggregateCapacityClient._reservation_sites` is a soft, re-derivable cache: a miss, including after restart, asks every site and re-learns the answer. POOLS-8 confirmed no consumer needs stronger durability and used the same pattern for per-site projection load state.
- [x] 2.4 Extract one shared feasibility predicate used by reservation-time admission and scheduling-time eligibility. **Done: `kit/site` owns the canonical feasibility view and pure predicate; reservation admission and `kit/fulfillment` scheduling consume the same normalized resource facts.**
- [x] 2.5 Make ledger unit-claim aliases configurable rather than VM-specific, and remove the scheduler's default VM-flavored `resource_kind` fallback. **Done as part of Section 1 task 1.4.**
- [x] 2.6 Reject scheduling requirements that exceed the capacity reservation in any governed dimension while permitting smaller shapes. **Done in the fulfillment scheduler; dimensions absent from the reservation are not governed by this comparison.**
- [x] 2.7 Add migration and unit tests for uniqueness, host-granular feasibility, and the shared predicate. **Shared-predicate and reservation-bound tests landed here; migration, final-schema, public-contract, and round-trip coverage were completed by 2.14–2.20 and 2.36. Storefront site-identity durability: see 2.3.**

### Section 2 code-review correction plan

- [x] 2.8 Define one canonical, immutable resource-feasibility view owned by `kit/site`. Include resource kind, governed available dimensions, normalized matchable attributes, and authoritative identity/membership facts such as `resource_id`, `pool_id`, subtype, value, and units. Keep the shared predicate pure and independent of ORM models.
- [x] 2.9 Make reservation admission and fulfillment scheduling consume the same canonical feasibility view; remove scheduler interpretation of raw resource `attributes` and keep task 2.4 incomplete until both paths share the representation.
- [x] 2.10 Reorder provisioning database initialization so service-owned migrations run before current-schema table creation. Remove the rename migration's need to drop a newly created `capacity_reservations` table; fail visibly on an ambiguous state where both legacy and current tables already exist rather than attempting recovery in this change.
- [x] 2.11 Correct touched production comments and docstrings to describe present intent, invariants, and schema conditions. Remove POOLS identifiers, `design.md` references, tombstone references, and migration-chronology wording from production code.
- [x] 2.12 Promote the accepted `site_id` ownership and trust-boundary decision: provisioning site-capacity persistence does not redundantly store storefront-owned site identity, and a counterparty may not self-assert that identity. Update `openspec/specs/site-capacity/spec.md`, the applicable storefront aggregation specification, and `docs/development/ARCHITECTURE.md` where the rule is repository-wide.
- [x] 2.13 Remove the blank-only edit to `openspec/specs/resource-pool-management/spec.md` and clean trailing blank-line/EOF whitespace in all files touched by Section 2.
- [x] 2.14 Add canonical-view parity tests covering top-level matchable facts such as `resource_subtype`, explicit `resource_id`, and authoritative `pool_id` through both reservation admission and scheduling.
- [x] 2.15 Add SQLite migration assertions for current constraints and operational indexes after the rename, including primary keys, unique constraints, foreign keys, and query-critical indexes. PostgreSQL support and validation remain out of scope.
- [x] 2.16 Add public API/client contract tests for renamed request and response fields. Assert the approved breaking contract rather than retaining legacy `allocation_id` aliases.
- [x] 2.17 Add a persistence round-trip test that creates a capacity reservation through the public boundary, reconstructs or restarts the owning service, and then retrieves and advances it by `capacity_reservation_id`.
- [x] 2.18 Add fresh-database tests proving initialization creates only current table/column names and does not manufacture a legacy/current duplicate-table collision.
- [x] 2.19 Add numeric-dimension validation tests for zero, negative, nonnumeric, boolean, and mixed numeric inputs at the lowest authoritative validation boundary and through the public request path.
- [x] 2.20 Run focused site, fulfillment, and provisioning suites plus the repository-standard aggregate kit validation. Record environmental dependency-resolution failures separately from repository test failures.
- [x] 2.21 Amend the POOLS-7 design-promotion record so every accepted Section 2 decision maps to permanent current-state documentation; do not mark the record complete while any material decision points back only to `openspec/changes`.

### Remaining Section 2 implementation plan

- [x] 2.22 Remove provisioning-private placement/accounting identifiers from storefront-facing `CapacityReservation` contracts, persistence, clients, fixtures, and tests. Preserve only durable negotiation facts such as `capacity_reservation_id`, status, expiry, reserved dimensions, and other approved metadata.
- [x] 2.23 Introduce the provisioning-private `CapacityBucket` model with opaque `capacity_bucket_id`, one bucket per VM host, `backing_resource_id`, owning resource-pool reference, normalized total/available dimensions, and matchable attributes. Enforce the current invariant that each host belongs to one resource pool.
- [x] 2.24 Introduce `CapacityReservationDebit` as the current reservation-to-bucket mapping, including governed debited dimensions and uniqueness rules that prevent duplicate current mappings. Keep debit identity and bucket identity private to the provisioning authority.
- [x] 2.25 Update reservation admission to select an eligible internal `CapacityBucket`, atomically create the reservation and its current debit, and prevent overcommitment using authoritative bucket balances.
- [x] 2.26 Update scheduling rebinding to atomically validate a replacement bucket, replace the current `CapacityReservationDebit`, release the prior bucket dimensions, debit the replacement dimensions, and assign `settlement_resource_id`. Preserve approved smaller-shape scheduling behavior.
- [x] 2.27 Define and implement `site_resource_pools` **Done: the compute provisioning mount derives the allowlisted inventory projection directly from authoritative `Host` rows and the storefront push path is retired.** as the storefront projection of site-to-resource-pool membership and the physical inventory fields required to create individual-resource listings. Derive it from authoritative provisioning `Host` and `ResourcePool` data; remove the storefront-authored host/resource push synchronization path.
- [x] 2.28 Define and implement `site_capacity_buckets` as the vertically grouped storefront capacity projection. Group physical resources by canonical listing/feasibility criteria and normalized currently available dimensions, expose `resource_count`, and compute a deterministic digest-derived `capacity_group_key` without exposing internal capacity-bucket IDs or duplicating physical-resource ID lists.
- [x] 2.29 Define independent revision-and-digest identities and lightweight version endpoints for `site_resource_pools` and `site_capacity_buckets`. Canonicalize records, keys, numeric values, null/absence semantics, and excluded volatile fields before hashing.
- [x] 2.30 Implement storefront startup loading **Done: the VM storefront loads both site projections after provisioning preflight and installs complete in-memory generations atomically.** and in-memory caching for both projections. Build and validate each replacement generation off to the side, atomically swap it into active use, and distinguish not-loaded, loaded-empty, stale, unavailable, and invalid states. Durable recovery remains Section 3 scope.
- [x] 2.31 Add independent polling loops **Done: one production polling loop independently checks and refreshes both projection families while retaining stale complete generations.** for the two projection identities. Retain the last complete generation on polling or refresh failure, coalesce concurrent refreshes, and expose freshness/last-error state without treating failure as empty capacity.
- [x] 2.32 Add bounded reactive drift checks **Done: topology-sensitive HTTP failures trigger a coalesced capacity-projection drift check without retrying the state-changing request.** for topology-sensitive reservation and scheduling failures. Recheck only the relevant projection identity, resync when it changed, avoid refresh storms, and do not retry state-changing requests without an established idempotency contract.
- [x] 2.33 Implement the SQLite **Done: migration validates replacement buckets and held-reservation debits, then retires `site_resources`; current ORM and repositories use only the replacement model.** create-copy-validate-switch-retire cutover from `SiteResource`: create final tables, derive authoritative inventory and host-level capacity buckets, map active reservations to current debit rows, reconstruct available capacity from totals minus active debits, validate references and nonnegative balances, switch repositories, and retire the legacy table only after all checks succeed. Fail visibly on unmappable or inconsistent legacy rows rather than guessing.
- [x] 2.34 Add schema, migration, and repository tests **Done: model, migration, atomicity, rebinding, reconstruction, and final-schema assertions cover the replacement model.** for host-to-pool uniqueness, one bucket per VM host, current-debit uniqueness, reservation/debit atomicity, rebinding, capacity reconstruction, unmappable legacy rows, and final retirement of `SiteResource`.
- [x] 2.35 Add projection contract tests **Done: projection, cache, polling, stale-retention, authoritative-inventory, and reactive-refresh behavior are covered at their lowest meaningful boundaries.** covering independent revisions/digests, deterministic grouping keys, canonical hashing, vertical regrouping after reservations, grouping-criteria joins to `site_resource_pools`, individual-resource listing fidelity, atomic cache replacement, stale-cache behavior, polling coalescing, and topology-sensitive reactive refresh.
- [x] 2.36 Complete the previously open validation tasks 2.14-2.20 against the final models and public contracts, run repository-standard focused and aggregate suites, and record environment failures separately from repository failures.
- [x] 2.37 Promote final durable Section 2 behavior into `openspec/specs/site-capacity/spec.md`, `openspec/specs/resource-pool-management/spec.md`, `openspec/specs/storefront-publication/spec.md`, `openspec/specs/fulfillment/spec.md`, and `docs/development/ARCHITECTURE.md` as appropriate. Complete the design-promotion record with exact permanent locations and remove temporary migration/changelog commentary from production code.

### Section 2 post-review cleanup

- [x] Fixed on review: a stale-base-file artifact that had reverted `design.md`'s `site_id` trust-boundary correction (now repoints at the implemented `storefront-publication` spec requirement); a duplicated `ARCHITECTURE.md` "Site inventory" header (merged); a stale `design.md`-referencing comment in `kit/fulfillment/scheduler.py`; dead code (`sync_site_resources` and its two tests, superseded by task 2.27's projection path); and missing test coverage for `refresh_after_topology_error` (drift-detected, no-drift, and no-observed-identity-fallback cases).

## 3. Add shared settlement persistence

- [x] 3.1 Define shared SQLAlchemy mappings, on a new `market_fulfillment`-owned declarative `Base` (mounted by the compute provisioning service's `db/models.py` alongside `market_site`'s and `market_resource_pools`' metadata, following the existing re-export pattern), for one settlement/fulfillment aggregate row per `capacity_reservation_id` (primary key), `ProvisionedResource` outputs, and recovery-claim fields. No result-delivery outbox and no separate `SettlementResult` model in v1 — `get_fulfillment_result` (section 8) is a read-time projection over the aggregate and its `ProvisionedResource` rows, not a persisted result object; see `design.md`, "Section 3 settlement persistence design decisions," "No persisted `SettlementResult`." The aggregate carries: `fulfillment_id` (nullable until accepted, unique, generated on first transition past `assigned`); `market`; `scheduling_requirements` and `fulfillment_request` as two separately-persisted, independently-immutable-once-written fields (see 3.4); `resource_id` constraint (if supplied), `settlement_resource_id`/`pool_id`/`provider`/resource attributes once assigned; `prepared_create_operation`/`prepared_teardown_operation` as `VersionedEnvelope`-typed JSON columns (extending the existing `market_fulfillment.envelopes` pattern, not a second versioning mechanism — see design.md); `provider_metadata`/`teardown_provider_metadata`; `state`; recovery-claim columns (`claimed_by`, `claim_expires_at`, attempt counter) directly on this row, not a separate claims table; timestamps. **Done: `market_fulfillment/db.py` (`settlement_records`, `provisioned_resources`), mounted by the provisioning service's database initialization.**
- [x] 3.2 Implement generic SQLAlchemy repositories using caller-supplied sessions so site-capacity and settlement changes can share one transaction. This requires new session-accepting entry points on `CapacityLedgerService` (`kit/site`), not just the new fulfillment-side repository — see `design.md`, "Ledger additions needed for one atomic scheduling transaction": add `lock_reservation(db, capacity_reservation_id)` (new; no existing read takes a row lock), `assign_settlement_resource_in_session(db, ...)` (extract the existing self-managed-session method's already-`db`-parameterized internals as a core, keep the public method as a thin wrapper), and `backing_resource_id_in_session(db, capacity_reservation_id)` (public exposure of the existing private `_backing_resource_id`). These are `kit/site` changes consumed by the Section 4 scheduler, not `kit/fulfillment` changes, and belong in this task's file list for that reason. **Done: `SettlementRepository` (caller-supplied `Session`, never commits); `kit/site`'s ledger gained the three session-scoped entry points, its public methods wrapping them. Section 4's `schedule_resource` composes them into one transaction.**
- [x] 3.3 Define fulfillment, provider-command, teardown, and abandonment states plus a compact table-driven transition validator. No separate result-delivery state machine in v1 (see 3.1). **Done: `SettlementRecordState` and the table-driven `validate_transition`.**
- [x] 3.4 Persist two separate canonical request shapes, each with its own equivalence scope, and enforce one fulfillment aggregate per `capacity_reservation_id`: `scheduling_requirements` (the normalized `SettlementRequirement` evaluated by `schedule_resource`) and `fulfillment_request` (the domain-specific payload `begin_fulfillment` accepts, distinct from scheduling requirements — see design.md, "Two separate persisted requirement shapes"). Compare by structural equality on the persisted, canonicalized JSON — no hash/digest fingerprint, unlike Section 2's projection digests, which solve a different problem (cross-process drift detection, not single-aggregate idempotency). **Done: two JSON columns, compared independently by `schedule` and `accept_fulfillment`.**
- [x] 3.5 Implement equivalent retry return and conflicting retry rejection before provider submission, for both equivalence scopes from 3.4 independently: a `schedule_resource` retry compares `market` + `scheduling_requirements`, with any supplied `resource_id` constraint checked separately for consistency against the stored `settlement_resource_id`; a `begin_fulfillment` retry compares `market` + `fulfillment_request` only, since the resource is loaded from the row rather than supplied by the caller (task 5.5). Note this closes a real gap in the current in-memory scheduler, which only checks `resource_id` consistency on retry and does not compare requirements at all — not a preservation of existing behavior. **Done at the repository layer (`schedule`, `accept_fulfillment`); Sections 4 and 5 wired the scheduler and fulfillment call sites to it.**
- [x] 3.6 Model one fulfillment to many `ProvisionedResource` rows with aggregate status; leave per-resource teardown unexposed unless a current caller requires it. **Done: `ProvisionedResource` and its repository methods.**
- [x] 3.7 Add repository, concurrency, state-transition, and canonicalization tests. **Done: `kit/fulfillment`'s `test_settlement_db.py`, `test_transitions.py`, `test_repository.py` (both equivalence scopes, conflicts, provisioned resources, recovery claims); `kit/site`'s `test_settlement_assignment.py` (shared transaction, rollback, lock).**
- [x] 3.8 Promote the aggregate's identity shape (`capacity_reservation_id` as primary key, `fulfillment_id` as a generated column), the two-equivalence-scope idempotency rule, the recovery-claim-on-row-not-separate-table shape, and the "no persisted `SettlementResult`" decision into `openspec/specs/fulfillment/spec.md`; add the design-promotion record entries once implemented. **Done: `openspec/specs/fulfillment/spec.md#durable-settlement-persistence` and `openspec/specs/site-capacity/spec.md#relationship-to-fulfillment-scheduling`.**

### Section 3 code-review correction plan

- [x] 3.9 Preserve `market` as immutable scheduling identity. On the first `accept_fulfillment` call, reject a market that differs from the market persisted by `schedule`; do not overwrite the aggregate's market while accepting fulfillment. Add a regression test for first-acceptance mismatch and retain equivalent-retry/conflicting-retry coverage. Permanent documentation: amend `openspec/specs/fulfillment/spec.md#durable-settlement-persistence` so the fulfillment-equivalence rule explicitly states that the accepted request must match the already-scheduled market.
- [x] 3.10 Make fulfillment acceptance concurrency-safe by locking the existing settlement row before checking or writing `fulfillment_id` and `fulfillment_request`. The provisioning service is SQLite-only; implement and test the strongest transaction behavior SQLite supports, document the single-database locking limitation honestly, and ensure concurrent callers cannot return two durable fulfillment identities. Keep initial scheduling's primary-key uniqueness as the aggregate-creation guard and translate an insert race into the normal equivalent/conflicting repository outcome where SQLite exposes such a race. Permanent documentation: describe the repository's SQLite transaction/locking contract in `openspec/specs/fulfillment/spec.md`; do not claim PostgreSQL-style row-lock semantics.
- [x] 3.11 Rename and narrow the Section 3 recovery helper so it is explicitly a single-worker SQLite persistence primitive rather than the final multi-replica claim algorithm. Update its docstring and tests to state the current guarantee. Amend Section 6 tasks to replace it with the final recovery acquisition workflow and to validate non-overlap under the actual provisioning-service execution model. Permanent documentation: keep only the durable claim-column and lease model in `openspec/specs/fulfillment/spec.md`; defer operational recovery-claim semantics to the Section 6 implementation and its permanent current-state documentation.
- [x] 3.12 Retain the domain-agnostic `transition(..., **lifecycle_updates)` interface, but restrict updates to kit-owned mutable lifecycle fields: prepared create/teardown operation envelopes, provider/teardown metadata, and failure fields. Reject aggregate identity, scheduling identity, fulfillment idempotency fields, state, recovery-claim fields, database-managed timestamps, and unknown/misspelled fields before mutating the in-memory row. Add tests for every allowed category, representative forbidden fields, `state`, claim fields, unknown fields, and rejection-before-state-mutation. Permanent documentation: add the shared mutable-versus-immutable aggregate field boundary to `openspec/specs/fulfillment/spec.md#durable-settlement-persistence`.
- [x] 3.13 Document the canonical-input contract: repository callers must provide validated canonical Pydantic models/envelopes before persistence; the repository compares their JSON-compatible structural form and does not canonicalize arbitrary dictionaries. Add focused tests for the canonical model forms the public APIs permit, including omitted-versus-explicit defaults and nested envelope round trips where applicable. Permanent documentation: update `openspec/specs/fulfillment/spec.md#durable-settlement-persistence` and the relevant request/envelope requirements.
- [x] 3.14 Add service-level schema validation without introducing migration scripts for these new tables. Test that provisioning database initialization mounts the fulfillment metadata, creates only the current tables and constraints, is idempotent on rerun, preserves foreign keys and query-critical indexes, and passes the service's final schema check. SQLite is the supported database for this service; PostgreSQL validation remains out of scope. Permanent documentation: update evidence only; no migration-history commentary belongs in permanent specifications.
- [x] 3.15 Remove references to active change documents (`design.md`, POOLS-7, or task chronology) from production docstrings/comments and stable test guidance. Replace broader-context references with stable anchors in `openspec/specs/fulfillment/spec.md`, `openspec/specs/site-capacity/spec.md`, or `docs/development/ARCHITECTURE.md` as appropriate. Review every Section 3-touched production file for present-tense intent and invariant wording.
- [x] 3.16 Correct Section 3 validation claims. Added an independent-session, file-backed SQLite fulfillment-acceptance race test and retained sequential single-worker lease tests as a distinct category. **`test_concurrent_sqlite_acceptance_returns_one_fulfillment_identity` passes in the full `kit/fulfillment` suite; it was first claimed on source compilation alone and confirmed by a real run in the final review pass.**
- [x] 3.17 Complete the Section 3 design-promotion record after implementation, mapping immutable market identity, SQLite concurrency guarantees, the narrowed recovery helper, lifecycle-update restrictions, and the canonical-caller contract to their exact permanent documentation locations. The promotion record must describe accepted durable decisions; temporary implementation notes remain in this change only.

## 4. Implement atomic scheduling

Resolved during the discuss phase (2026-07-23; see `design.md`, "Section 4
scheduling implementation — design questions") and binding on this plan:
`schedule_resource` is a convenience operation whose purpose is to fold what
would otherwise be several separate storefront/provisioning round trips,
each with its own error taxonomy, into one call with one commit/rollback
boundary — so the storefront never has to build compensating error handling
for a partially-completed schedule. Every subtask below implements that
decision; none of tasks 4.1–4.4 may be implemented as separate
self-committing calls glued together in the scheduler, the way today's
`select_resource`/`_eligible_candidates` are.

- [x] 4.1 Replace process-local scheduler assignment and round-robin state with database-backed selection and deterministic persisted fairness state where required.
  - [x] 4.1.1 Add a `SchedulingCursor` model to `kit/fulfillment/src/market_fulfillment/db.py`, table `scheduling_cursors`, primary key `resource_kind`, columns `last_pool_id` (nullable string) and `last_resource_by_pool` (JSON map of pool id to last-selected resource id). One row per `resource_kind`; a buyer negotiates for one `resource_kind` per reservation, so fairness is isolated per `resource_kind` rather than globally or per finer key (design.md, item 2). **Done.**
  - [x] 4.1.2 Change `SettlementSchedulingPolicy.select` (`kit/fulfillment/src/market_fulfillment/scheduling.py`) to a pure function of explicit inputs: `select(requirement, candidates, cursor) -> tuple[SettlementCandidate, cursor]`. No database or session access in this module or in `round_robin_policy.py` — the protocol must remain unit-testable without a database. **Done: `SchedulingCursorState` carries the value; purity held by `test_only_scheduler_and_ids_modules_import_the_two_allowed_kit_dependencies`.**
  - [x] 4.1.3 Rewrite `DeterministicRoundRobinPolicy` (`round_robin_policy.py`) to the new pure signature: read `cursor.last_pool_id`/`cursor.last_resource_by_pool` instead of instance attributes, return the selected candidate plus a new cursor value, and stop mutating `self`. The class becomes stateless and safe to share across concurrent calls. **Done.**
  - [x] 4.1.4 Add `SettlementRepository` methods (`kit/fulfillment/src/market_fulfillment/repository.py`) to read and upsert one cursor row within a caller-supplied session: `get_cursor_in_session(db, resource_kind) -> SchedulingCursor` (creates a zero-value row on first use, so callers never handle "no cursor yet" as a distinct case) and `save_cursor_in_session(db, resource_kind, last_pool_id, last_resource_by_pool)`. **Done.**
  - [x] 4.1.5 Document the cursor's concurrency contract honestly: `schedule_resource`'s `BEGIN IMMEDIATE` transaction (task 4.3) reserves SQLite's single-writer slot before the cursor row is read, so concurrent `schedule_resource` calls for the same `resource_kind` serialize at the database level. This is the same SQLite single-writer guarantee already documented for fulfillment acceptance in Section 3, not a claim of portable row-lock semantics, and not a reason to add lock-owner/lock-time columns to this table now — that lock/lease shape (mirroring the aggregate's recovery-claim columns) is the fallback only if a future non-SQLite or genuinely multi-writer deployment needs it. **Done: `begin_sqlite_write_transaction`'s documentation; promoted by 4.8.1.**

- [x] 4.2 Add the two new session-scoped read methods `schedule_resource` composes, replacing today's self-committing enumeration:
  - [x] 4.2.1 `CapacityLedgerService.iter_scheduling_candidates_in_session(db, *, resource_kind, exclude_reservation_id) -> list[ResourceFeasibilityView]` (`kit/site/src/market_site/ledger.py`): every enabled `CapacityBucket` of the given `resource_kind`, built through the existing `_resource_feasibility_view`/`resource_satisfies_requirement` path, with `exclude_reservation_id`'s own current `CapacityReservationDebit` credited back into `available` — replacing the ad hoc credit-back today's `PhysicalSettlementScheduler._eligible_candidates` performs over a dict payload. Generalizes `_find_candidate`'s session-scoped, debit-aware availability computation from "return the first match" to "return every match." **Done, with the same window and host-conflict handling as admission, so the two cannot diverge.**
  - [x] 4.2.2 `ResourcePoolService.list_pools_in_session(db, *, enabled_only=True) -> list[ResourcePool]` (`kit/resource-pools/src/market_resource_pools/service.py`): session-scoped twin of the existing self-managed `list_pools`, so pool enablement can be checked inside the same transaction as reservation locking and settlement-record creation instead of a separate, differently-timed read. **Done; unlike `list_pools`, attaches no `provider_config` and expunges nothing.**
  - [x] 4.2.3 Remove `PhysicalSettlementScheduler._eligible_candidates`'s `attributes.get("pool_id")` fallback **only after** 4.2.4 lands, not as part of this task — see the verified finding in `design.md` item 5: the fallback is not dead. `kit/fulfillment/tests/unit/test_scheduler.py`'s own resource helpers rely on it exclusively today (they never pass a real `pool_id` column), and `kit/site/tests/unit/test_ledger.py::test_attribute_view_prefers_real_pool_id_over_attributes_json` documents it as an intentionally still-open transitional behavior. Do not fold its removal into the same commit as the candidate-enumeration rewrite for an unrelated reason. **The fallback went away with the 4.2.1 rewrite rather than as its own step (design.md, "Rationale moved from task notes at closeout", 4.2.3).**
  - [x] 4.2.4 Update `kit/fulfillment/tests/unit/test_scheduler.py`'s `_resource`/`_resource_with_capacity` helpers to pass a real `pool_id=` column argument (matching how production resources are actually registered post-Section-2) instead of `attributes={"pool_id": pool_id}`. Confirm no other test or fixture still registers pool membership through attributes only before 4.2.3's removal is attempted; if one is found, it is new evidence for this design record, not something to silently work around. **Done; no other kit test relies on attributes-only pool registration.**

- [x] 4.3 Implement `schedule_resource(capacity_reservation_id, market, requirements, resource_id=None)` as one atomic transaction on `PhysicalSettlementScheduler`, replacing `select_resource`'s in-memory implementation:
  - [x] 4.3.1 Wire `session_factory` into `PhysicalSettlementScheduler.__init__` for real (today's constructor accepts and immediately discards it — `del session_factory`). Open a `BEGIN IMMEDIATE` session (same helper Section 3 introduced for fulfillment acceptance) at the start of `schedule_resource`. **Done, through the now-public `begin_sqlite_write_transaction`.**
  - [x] 4.3.2 `CapacityLedgerService.lock_reservation(db, capacity_reservation_id)` to lock and validate the reservation (existence, active state, TTL not expired, market/requirements consistency with `deal_ref`), replacing today's separate self-committing `_require_valid_reservation`. **Done; unchanged validation, read through `reservation_payload_in_session` over the locked row.**
  - [x] 4.3.3 Call `SettlementRepository.schedule(...)`'s equivalence check first (existing-row idempotent-retry-or-conflict, unchanged from Section 3) before doing any new selection work, so an equivalent retry short-circuits without touching candidates, cursor, or capacity rebind. **Done.**
  - [x] 4.3.4 For a first-time schedule, call `iter_scheduling_candidates_in_session` (4.2.1) and `list_pools_in_session` (4.2.2) inside the same session, intersect on enabled pool membership exactly as today's `_eligible_candidates` does, and build the `SettlementRequirement` via the existing `_requirement` logic (dimensions-exceed-reservation rejection, `resource_kind` resolution) unchanged. **Done.**
  - [x] 4.3.5 If `request.resource_id` is set, verify it is among the eligible candidates (unchanged rule: explicit resource bypasses policy but not eligibility) and skip the cursor entirely — explicit selection must not read or advance it, per the existing spec scenario "Explicit resource is ineligible" and the unstated-but-implied "explicit resource does not consume a fairness turn." **Done and tested (`test_explicit_resource_does_not_advance_or_consume_cursor`).**
  - [x] 4.3.6 Otherwise, load the `resource_kind`'s cursor via `get_cursor_in_session` (4.1.4), call the pure `DeterministicRoundRobinPolicy.select(...)` (4.1.2/4.1.3), and write the returned cursor back via `save_cursor_in_session` in the same transaction. **Done.**
  - [x] 4.3.7 If the selected resource differs from the resource the reservation's own `reserve()` call originally bound (fairness reassignment among equally-eligible resources — see design.md's "`SiteResource` is retired" `Option A` decision), call `assign_settlement_resource_in_session` to atomically rebind capacity before creating the settlement row. **Done.**
  - [x] 4.3.8 Call `SettlementRepository.schedule(...)` to create (or return, on the equivalence path already checked in 4.3.3) the `assigned` settlement row, then commit the whole transaction. **Done.**
  - [x] 4.3.9 On any exception before commit, ensure the session rolls back in full — no partial cursor advance, no partial capacity rebind, and no orphaned settlement row — proving out the "one commit/rollback boundary" property this task exists for. **Done: `test_failed_schedule_leaves_no_partial_cursor_or_settlement_state`.**

- [x] 4.4 Reject unknown reservation/pool/resource identifiers rather than forwarding, reinterpreting, or trying another site — unchanged in substance from the original task, now implemented as part of 4.3.2/4.3.4/4.3.5's checks against the locked reservation and the session-scoped candidate/pool enumerations rather than against the removed self-committing calls. **Done: `test_unknown_reservation_is_rejected`, `test_resource_without_pool_is_not_schedulable`, and their siblings.**

- [x] 4.5 Add `resize_reservation` to `CapacityLedgerService` (`kit/site/src/market_site/ledger.py`) per `design.md`'s corrected design: one atomic transaction that locks the old reservation, releases it, re-evaluates candidacy for the new shape against a view where the old hold is already released, reserves the new shape, and invokes an optional `on_supersede: SettlementAbandonmentHook | None` hook before commit — never two independently-committed `release()`/`reserve()` calls, and never a direct `market_site → market_fulfillment` import. Ships as a single self-managed-session method with no `_in_session` twin (design.md, item 3 — nothing in this change composes it into a larger transaction; add the twin later only if a real co-transactional caller appears).
  - [x] 4.5.1 Define `SettlementAbandonmentHook` as a `Protocol` in `market_site` (no fulfillment types referenced): `def __call__(self, db: Session, capacity_reservation_id: str) -> None`. **Done.**
  - [x] 4.5.2 Thread the same hook shape into `CapacityLedgerService.__init__` as an optional constructor parameter, invoked unconditionally (no existence pre-check — design.md, item 4) from three sites: `_expire_stale_holds` (TTL-hold lapse), `release()` (terminal release), and `resize_reservation`'s supersede step. The concrete `market_fulfillment` implementation owns deciding whether there is anything to abandon. **Done, as a constructor dependency rather than a per-call parameter (design.md, "Rationale moved from task notes at closeout", 4.5.2).**
  - [x] 4.5.3 Implement the concrete hook in `market_fulfillment` (repository or a small composition-facing wrapper): look up the `SettlementRecord` for the given `capacity_reservation_id`; if none exists, or it is not in `assigned` state, no-op; otherwise transition it to `abandoned` via `validate_transition`, in the same session the caller passed in. **Done as `SettlementRepository.abandon_if_assigned`.**
  - [x] 4.5.4 Compose the concrete hook in `compute_provisioning_service/container.py`, passed to `capacity_ledger_service`'s constructor alongside the existing wiring, even though no HTTP caller reaches `resize_reservation` yet (design.md, item 4 — matches the `pools-2`/`pools-3` precedent of shipping ahead of a real caller). **Done. First verified only by static review; confirmed through the real container by `test_scheduling_composition.py` (4.13).**

- [x] 4.6 Atomically abandon assigned-but-unfulfilled settlements and release/supersede their capacity during lease lifecycle events; add watchdog reconciliation. With 4.5's hook wired into `_expire_stale_holds` and `release()`, the existing `LeaseLifecycleService`/`_expire_stale_holds` sweeps already reach every capacity-reclaiming path (design.md, item 4 — confirmed by inspection that `LeaseLifecycleService` never bypasses `CapacityLedgerService.release()`); this task is validation that the wiring actually fires end-to-end, not new reconciliation machinery. No separate watchdog is added. **Confirmed by `kit/site`'s hook-invocation tests; the lease-lifecycle reach rests on a code trace, not an integration test (design.md, "Rationale moved from task notes at closeout", 4.6).**

- [x] 4.7 Add race, retry, rollback, expiry, supersession, and multi-replica scheduling tests:
  - [x] 4.7.1 `kit/fulfillment/tests/unit/test_scheduler.py`: equivalent-retry short-circuit before touching candidates/cursor; conflicting retry rejected; explicit-resource path does not read or advance the cursor; full-transaction rollback leaves no partial cursor/rebind/settlement-row state on a mid-transaction failure. **Done: `test_retry_is_idempotent_and_does_not_rerun_policy`, `test_conflicting_schedule_retry_is_rejected`, `test_explicit_resource_does_not_advance_or_consume_cursor`, `test_failed_schedule_leaves_no_partial_cursor_or_settlement_state`.**
  - [x] 4.7.2 New cursor-focused tests: cursor persists across a fresh `PhysicalSettlementScheduler` instance; two `resource_kind`s scheduling concurrently do not perturb each other's cursor. **Done: `test_cursor_persists_across_a_fresh_scheduler_instance`, `test_cursor_is_isolated_per_resource_kind`. The persisted stale-cursor case was left as a recorded gap and closed by 4.12.**
  - [x] 4.7.3 `kit/site/tests/unit/test_ledger.py`: `resize_reservation`'s release-then-reserve availability visibility, full rollback on new-shape unavailability leaving the old reservation untouched, and the hook firing exactly once inside the same transaction on success. **Done: `test_resize_reservation_supersedes_with_a_new_id`, `test_resize_reservation_sees_capacity_the_old_hold_was_consuming`, `test_resize_reservation_rolls_back_fully_when_new_shape_is_unavailable`, `test_resize_reservation_of_unknown_or_unheld_reservation_is_a_no_op`.**
  - [x] 4.7.4 Hook-invocation tests proving `_expire_stale_holds`, `release()`, and successful `resize_reservation` call the configured hook according to the permanent site-capacity contract. Amend the release coverage so an already-terminal idempotent release still invokes the hook while producing no duplicate capacity mutation or event; retain rollback coverage proving a failed resize does not leak hook-visible settlement changes. **Done: `test_ledger.py`'s `test_release_invokes_the_abandonment_hook_unconditionally`, `test_expired_hold_lapse_invokes_the_abandonment_hook`, `test_resize_reservation_invokes_the_abandonment_hook_for_the_old_reservation`, `test_resize_reservation_rollback_does_not_invoke_the_abandonment_hook`, `test_no_hook_configured_is_a_silent_no_op`. The checkbox had drifted behind the code; confirmed in the final review pass.**
  - [x] 4.7.5 `kit/fulfillment/tests/unit/test_repository.py` or a new module: test `SettlementRepository.abandon_if_assigned` directly against real `SettlementRecord` rows. Cover `assigned -> abandoned`, no row, already `abandoned`, post-assignment lifecycle states, repeated invocation, commit persistence, and caller rollback restoring `assigned`. Assert the method never commits the caller-supplied session. **Done: `test_settlement_repository.py`'s `test_abandon_if_assigned_transitions_only_assigned_rows`, `test_abandon_if_assigned_obeys_caller_rollback`, `test_abandon_if_assigned_preserves_post_assignment_state`. The checkbox had drifted behind the code.**
  - [x] 4.7.6 Service-level test in `provisioning/compute/service/tests` proving `schedule_resource` end-to-end against the composed container: reservation lock, candidate enumeration, cursor read/write, optional rebind, and settlement-row creation all commit or all roll back together. **Done with 4.13: `test_scheduling_composition.py`.**

- [x] 4.8 Promote Section 4's accepted decisions into permanent documentation and this change's design-promotion record. **Done.**
  - [x] 4.8.1 `openspec/specs/fulfillment/spec.md`: add the `resource_kind`-scoped round-robin fairness boundary as a normative statement under "Scheduling and assignment"; document `schedule_resource`'s one-transaction contract; extend the SQLite single-writer concurrency-contract language to cover cursor read/update. **Done: `openspec/specs/fulfillment/spec.md#requirement-scheduling-and-assignment`.**
  - [x] 4.8.2 `openspec/specs/site-capacity/spec.md`: document `resize_reservation`'s atomic supersede contract and the `SettlementAbandonmentHook` protocol/call sites as current-state ledger behavior. **Done, as "Reservation supersede and settlement abandonment", since replaced by "Reservation supersede and the release guard" (`bare-metal-mock-provisioned-deal`).**
  - [x] 4.8.3 Add design-promotion record entries (table at the end of `design.md`) for: resource_kind-scoped cursor durability, `schedule_resource`'s single-transaction contract, `resize_reservation`'s self-managed-session shape, and the unconditional abandonment-hook call sites. **Done.**
  - [x] 4.8.4 Remove change-document/task-number references from any Section 4 production code comments before considering the section implemented, per `AGENTS.md`'s comment rules. **Done: no such references in Section 4 production files.**

### Section 4 code-review correction plan

- [x] 4.9 Correct terminal-release abandonment semantics. Reorder `CapacityLedgerService.release()` so every valid release call invokes `SettlementAbandonmentHook`, including an already `released` or `force_released` idempotent retry, while retaining the existing no-duplicate-capacity-mutation and no-duplicate-event behavior. Keep fulfillment-state interpretation inside the concrete hook; `market_site` must not pre-check whether a settlement exists or whether it is still `assigned`.

- [x] 4.10 Introduce a narrow scheduling persistence interface before adding concurrency instrumentation. The scheduler must depend on one transaction-scoped capability rather than directly coordinating broad services plus a raw session.
  - [x] 4.10.1 Define a `SchedulingUnitOfWork`/`SchedulingTransaction` protocol in `kit/fulfillment` whose transaction context owns the SQLite write transaction and exposes only scheduling-safe operations: reservation lock/projection, equivalent-assignment lookup, eligible candidate enumeration, enabled-pool enumeration, cursor load/save, capacity rebind, and settlement assignment creation.
  - [x] 4.10.2 Implement the SQLAlchemy-backed adapter by composing the existing `CapacityLedgerService`, `ResourcePoolService`, and `SettlementRepository` over one caller-owned `Session`. Do not split `SettlementRepository` or the settlement table in this correction pass; repository-view separation is explicitly deferred until the existing DAL becomes materially harder to maintain.
  - [x] 4.10.3 Refactor `PhysicalSettlementScheduler.schedule_resource` to orchestrate policy and validation through this interface. The scheduler must not receive or reach self-committing service methods, and the persistence adapter must not absorb policy selection, request validation, or retry-semantics decisions.
  - [x] 4.10.4 Preserve the existing one-transaction behavior and error taxonomy. Add focused tests proving an injected transaction implementation can observe cursor persistence and transaction completion without adding production-only test hooks. **Done: `test_scheduler.py`'s three independent-session tests inject a `transaction_type=` subclass through the unit of work's constructor; no production test seam.**

- [x] 4.11 Add deterministic independent-session SQLite concurrency tests using option A: a test-only implementation/subclass of the narrow scheduling persistence adapter plus explicit `threading.Event` barriers.
  - [x] 4.11.1 Use a file-backed SQLite database, separate engines/connections or independently created sessions, `check_same_thread=False`, and an explicit nonzero busy timeout. Do not use a shared in-memory `StaticPool` database as evidence of independent-session writer behavior.
  - [x] 4.11.2 Commit case: establish transaction A as the first `BEGIN IMMEDIATE` writer, pause it after cursor/assignment mutation but before commit, start transaction B, and prove by barrier ordering that B cannot read/advance the cursor until A commits. Then assert distinct deterministic fairness turns, both assignments, and the final cursor.
  - [x] 4.11.3 Rollback case: pause transaction A after its writes, force a controlled failure and rollback, then allow B to continue. Assert A leaves no settlement, capacity rebind, or cursor advance; B receives the original first fairness turn; and the database remains usable. **Correction: marked done before any such test existed. The final review pass added `test_independent_sessions_rollback_leaves_no_partial_state_for_next_writer`.**
  - [x] 4.11.4 Keep the tests deterministic: explicitly establish which transaction owns the writer slot, synchronize at semantic adapter operations, use bounded waits only to prevent hangs, and never assert correctness from wall-clock timing or an uncontrolled natural race. **Confirmed: barriers at named adapter operations with bounded waits, no sleeps.**
  - [x] 4.11.5 Add interleaved independent-session coverage proving separate `resource_kind` cursor rows do not perturb one another. Describe this as SQLite independent-session serialization, not portable row locking or process-level multi-replica proof. **Done: `test_interleaved_independent_sessions_do_not_perturb_other_resource_kind_cursors` (design.md, "Rationale moved from task notes at closeout", 4.11.5).**

- [x] 4.12 Add a persisted stale-cursor integration test. Seed `scheduling_cursors` with a deleted or disabled `last_pool_id` and a deleted or ineligible last resource for an otherwise active pool; schedule through a fresh scheduler/unit-of-work instance; assert deterministic recovery from the first sorted eligible pool/resource and durable cursor replacement. Do not require pruning harmless historical map entries in Section 4.

- [x] 4.13 Add the production-composition transaction test in `provisioning/compute/service/tests`.
  - [x] 4.13.1 Build the real dependency-injector container and verify the scheduler, site ledger, resource-pool service, settlement repository, abandonment hook, and scheduling unit of work resolve to one effective database/session-factory boundary. **Done: `test_scheduling_composition.py::test_real_container_resolves_scheduling_dependencies_to_one_boundary`, overriding only `session_factory`.**
  - [x] 4.13.2 Exercise a successful schedule through production wiring and assert reservation locking, candidate enumeration, cursor update, optional rebind, and settlement creation commit together. **Done in the same test.**
  - [x] 4.13.3 Inject a controlled failure after both site-capacity and fulfillment persistence have mutated and assert all participating tables roll back together. Prefer this behavioral rollback proof over relying only on object-identity assertions. **Done: `test_real_container_composed_schedule_rolls_back_all_participating_tables`, which first advances the cursor so the rebind is a real site-capacity write.**

- [x] 4.14 Promote the reusable concurrency-test strategy into permanent documentation.
  - [x] 4.14.1 Add a repository-wide testing principle to `docs/development/ARCHITECTURE.md`: database-concurrency tests must use independent sessions/connections, explicit synchronization at semantic transaction boundaries, deterministic ownership ordering, bounded deadlock protection, and final persisted-state assertions rather than uncontrolled races or elapsed-time expectations.
  - [x] 4.14.2 Keep SQLite-specific single-writer details in the applicable authoritative subsystem specification, `openspec/specs/fulfillment/spec.md`, including that `BEGIN IMMEDIATE` serialization is the current guarantee and is not represented as portable row-lock semantics.
  - [x] 4.14.3 Review `openspec/specs/site-capacity/spec.md` for the unconditional release-hook correction. No text change was required: the existing contract already assigns fulfillment-state interpretation to the hook and requires invocation regardless of whether an assignment exists; implementation and tests were aligned to that durable rule.
  - [x] 4.14.4 Amend the Section 4 design-promotion record in `design.md` to map the narrow scheduling persistence boundary and deterministic database-concurrency testing principle to their permanent documentation locations.

- [x] 4.14.5 Repair the compute-service domain import boundary regression exposed during Section 4 validation. Route bare-metal capacity projection through `bare_metal_provisioning_adapter.runtime` rather than importing `arkhai_bare_metal` from the generic service, and retain the existing AST boundary test as validation evidence. This is a validation-driven correction to an existing repository boundary, not a new POOLS-7 subsystem design decision.

- [x] 4.15 Complete Section 4 validation and closure.
  - [x] 4.15.1 Run focused `kit/site`, `kit/resource-pools`, and `kit/fulfillment` suites using the repository-standard `.dist` dependency path. **Done: `cd kit && make dist && make test` passed.**
  - [x] 4.15.2 Run the `provisioning/compute/service` suite, including the real-container composition and rollback tests. **Done: `make test-provisioning` passed.**
  - [x] 4.15.3 Run the repository-standard aggregate kit validation and any touched provisioning validation target. Record dependency-bundle or environment failures separately from repository failures and do not mark this task complete based on static review or `py_compile` alone. **Done. The VM storefront and buyer suites could not run in that environment, for a documented dependency-index limit (design.md, "Rationale moved from task notes at closeout", 4.15.3); every suite Section 4's code could affect passed.**
  - [x] 4.15.4 Reconcile tasks 4.7.4–4.7.6 and 4.9–4.15 only after the implementation and required suites pass; then replace this correction-plan status with a truthful Section 4 completion statement. **Done.**

**Section 4 complete.** Verified by running suites, not static review. Two false or drifted marks were corrected: 4.7.4/4.7.5 were already satisfied, and 4.11.3 had no test until one was added. `make check-comment-hygiene` passed; the pass also fixed ten unrelated violations (design.md, "Rationale moved from task notes at closeout").

## 5. Implement fulfillment acceptance and provider preparation

**Resequenced** (see `design.md`, "Section 5/6/7 resequencing decision"): this section was originally task-numbered 6 and planned to implement third; it now runs second so the durable `begin_fulfillment` operation and the prepare/dispatch provider split exist before migration/backfill is attempted.

**Scope boundary (design.md, "Section 5 ... resolved design decisions"):** this section is provisioning-service-internal only. Capacity reservation already exists (`CapacityLedgerService.reserve()`); full storefront-side orchestration (reserve → `schedule_resource` → `begin_fulfillment` → poll status/result) is Section 9 scope; teardown *dispatch calling* (`begin_fulfillment_teardown`) is Section 10 scope. This section builds `prepare_teardown`/`dispatch_teardown` on the provider interface alongside `prepare_create`/`dispatch_create` ahead of that caller, matching the `pools-2`/`pools-3` precedent of shipping capability ahead of a real caller.

- [x] 5.1 Add `ResourcePoolService.get_pool_in_session(db, pool_id) -> ResourcePool | None` (`kit/resource-pools/src/market_resource_pools/service.py`), exposing the existing private `_require_pool` session-scoped helper as a public entry point, mirroring the `list_pools_in_session` precedent (task 4.2.2). This closes the same "prepared work must be frozen, not live-re-read" gap Section 4 closed for scheduling — without it, `prepare_create`'s pool-config read would happen outside the transaction that locks the settlement row and writes the prepared operation. Permanent documentation: `openspec/specs/resource-pool-management/spec.md`.

- [x] 5.2 Split `FulfillmentProvider` (`kit/fulfillment/src/market_fulfillment/provider.py`) into synchronous pure preparation and asynchronous dispatch: `prepare_create(request, resource, pool_config) -> VersionedEnvelope`, `dispatch_create(prepared) -> FulfillmentResult`, `prepare_teardown(settlement_result, pool_config) -> VersionedEnvelope`, and `dispatch_teardown(prepared) -> FulfillmentResult`, replacing `create`/`teardown` on the abstract base. `get_status` is unchanged. `resource` continues to mean the full provider-neutral `SettlementResource` model; any bare identifier is named `settlement_resource_id`. Teardown receives the durable provider-neutral settlement result (including selected resource, provisioned-resource outputs, and versioned provider metadata) so the concrete provider can identify exactly what it created without leaking Ansible fields into shared orchestration. `AnsibleFulfillmentProvider` (only implementer today) owns validation and interpretation of its teardown metadata. Neither preparation method holds or calls `ResourcePoolService`; `pool_config` is supplied by the caller. Permanent documentation: `openspec/specs/fulfillment/spec.md#requirement-scheduling-and-assignment`, `openspec/specs/fulfillment/spec.md#durable-settlement-persistence`, and `openspec/specs/fulfillment/architecture.md` (provider-neutral result handoff and adapter-owned metadata interpretation).

- [x] 5.3 Define concrete versioned-envelope payload kinds `"vm.ansible.create.v1"`/`"vm.ansible.teardown.v1"` (`domains/vms/provisioning/adapter`), each with a dedicated, validated Pydantic payload model — not a raw `dataclasses.asdict(AnsibleJobParams)` dump — satisfying the existing versioned-envelope typed/explicitly-validated-payload requirement on both write and read. The provider axis is embedded in the kind name deliberately (a future non-Ansible provider mints its own kind with an unrelated payload shape). `fulfillment_request` (the storefront-supplied payload) is unchanged — still the domain-neutral `VmFulfillmentRequirements` shape; the storefront never sees this envelope. Permanent documentation: `openspec/specs/fulfillment/spec.md#requirement-versioned-envelopes`.

- [x] 5.4 Define a `FulfillmentUnitOfWork` protocol in `kit/fulfillment`, following the Section 4 `SchedulingUnitOfWork` precedent, narrowed to fulfillment acceptance's smaller surface. It must expose: (a) lock/lookup and independent equivalence checking through `SettlementRepository.accept_fulfillment`; (b) an acceptance decision that distinguishes `newly_accepted` and `dispatch_required`, rather than returning an undifferentiated row; (c) the session-scoped pool-config read from 5.1; (d) writing `prepared_create_operation`/`prepared_teardown_operation` with `dispatch_pending`/`teardown_dispatch_pending`; and (e) an idempotent second-transaction acknowledgement operation that stores normalized provider metadata and transitions `dispatch_pending` to `dispatching`. Equivalent metadata returns the existing row; conflicting provider job identity raises a lifecycle conflict without rewriting existing metadata. Implement the SQLAlchemy-backed adapter composing `SettlementRepository` and `ResourcePoolService` over one caller-owned session. Permanent documentation: `openspec/specs/fulfillment/spec.md#durable-settlement-persistence` and `openspec/specs/fulfillment/architecture.md` (two-transaction acknowledgement gap and recovery model).

- [x] 5.5 Implement the durable `begin_fulfillment(capacity_reservation_id, market, fulfillment_request)` orchestrator in `kit/fulfillment` (new module; e.g. alongside `scheduler.py`), retiring `compute_provisioning_service/services/fulfillment_service.py`'s in-memory `FulfillmentService`/`FulfillmentEntry` entirely rather than adapting it in place. Transaction 1: open `BEGIN IMMEDIATE` through `FulfillmentUnitOfWork`; load the persisted scheduled resource rather than accepting a caller-supplied resource; accept or equivalence-check the fulfillment request; read pool configuration in the same session; prepare the provider input; persist the immutable prepared envelope and `dispatch_pending`; commit. Dispatch only when the acceptance decision says it is required: newly accepted work and equivalent retries still in `dispatch_pending` without acknowledged provider metadata dispatch; equivalent retries in `dispatching` or any later lifecycle state return the existing fulfillment without redispatch. After successful provider submission, transaction 2 idempotently persists normalized provider metadata and transitions to `dispatching`. A failure before transaction 1 commits rejects the operation. A recoverable dispatch or acknowledgement failure after durable acceptance leaves the aggregate accepted in `dispatch_pending` and returns the accepted fulfillment view rather than making acceptance appear rejected; terminal/non-recoverable provider input errors remain explicit failures. `begin_fulfillment` never calls the scheduler and returns a durable provider-neutral acceptance view containing at least `fulfillment_id`, `capacity_reservation_id`, and current aggregate state. Update `compute_provisioning_service/container.py` wiring to compose the relocated orchestrator instead of the retired in-memory service. Permanent documentation: `openspec/specs/fulfillment/spec.md#durable-settlement-persistence`, `openspec/specs/fulfillment/spec.md#durable-settlement-persistence`, `openspec/specs/fulfillment/architecture.md` (acceptance versus dispatch acknowledgement), and `docs/development/ARCHITECTURE.md#package-and-dependency-layers`.

- [x] 5.6 Submit Ansible create/teardown through `ExecutorActionEnvelope` with deterministic `idempotency_key=f"{capacity_reservation_id}:create"`/`f"{capacity_reservation_id}:teardown"`, reusing `AnsibleJobService.submit`'s existing `contract=` dedup mechanism (already implemented and tested; not new work). Construct the envelope with `deal_ref={}` — no commercial/deal identity is read, forwarded, or newly threaded through this path. **Do not** remove `deal_ref` from `ExecutorActionEnvelope`, `JobAccepted`, `ProvisioningJob`, `LeaseRegistration`/`LeaseView`, or the `AnsibleJob.deal_ref` column in this task — those remain load-bearing for the still-active legacy direct-dispatch path (`ComputeContractService.submit_action`, `BareMetalComputeAdapter.submit`, `register_lease`) until Section 9 retires its callers; full removal is explicitly Section 11 scope (already covers "obsolete executor/provider fields"). Permanent documentation: `openspec/specs/fulfillment/spec.md#requirement-physical-settlement-request` (no commercial identity crosses this boundary).

- [x] 5.7 Persist provider job identity and normalized provider metadata in `provider_metadata`/`teardown_provider_metadata` without exposing VM-specific job state as the cross-domain lifecycle contract. Keep the shared persistence column provider-neutral, but require each concrete adapter to validate its metadata with a typed internal model before writing or reading it. For newly accepted VM fulfillments, the normalized create metadata must retain the durable executor job identity and exact teardown identity required by `AnsibleFulfillmentProvider`; shared orchestration must not know those field names or reconstruct them from storefront state. This metadata remains distinct from the immutable versioned prepared-operation columns. Permanent documentation: `openspec/specs/fulfillment/spec.md#durable-settlement-persistence` and `openspec/specs/fulfillment/architecture.md`.

- [x] 5.8 Add focused and concurrency tests for: equivalent/conflicting `begin_fulfillment` retries; equivalent retry in `dispatch_pending` redispatching the persisted prepared operation; equivalent retry after provider acknowledgement returning without dispatch; dispatch failure after acceptance returning the accepted view while preserving `dispatch_pending`; acknowledgement write failure and deterministic recovery by executor idempotency key; identical versus conflicting provider-metadata acknowledgement; pool-config mutation after acceptance not changing prepared/dispatched input; duplicate submission races; create/teardown command deduplication; and deterministic independent-session `FulfillmentUnitOfWork` commit/rollback cases using file-backed SQLite and explicit `threading.Event` barriers.

  5.10's tests cover the retry, redispatch, acknowledgement, and idempotency-key cases. The final review pass added the other three:

  - `test_fulfillment.py::test_independent_sessions_serialize_fulfillment_acceptance_deterministically`: two threads on file-backed SQLite; the second `BEGIN IMMEDIATE` waits for the first.
  - `test_fulfillment_api.py::TestPoolConfigFrozenAtAcceptance`: a pool edit after acceptance leaves the prepared operation unchanged.
  - `test_fulfillment_api.py::TestAcknowledgementFailureRecovery`: after a failed acknowledgement, the retry reuses the same Ansible job.

- [x] 5.9 Expose a public side-effect-free dry-run endpoint with the same request signature as `begin_fulfillment(capacity_reservation_id, market, fulfillment_request)`. It must load the same already-scheduled aggregate and selected resource, resolve the same provider, read current pool configuration, and run the same parsing and `prepare_create` validation path, while performing no lifecycle transition, prepared-operation write, provider dispatch, or other durable side effect. Return a provider-neutral validation result rather than the internal prepared envelope. Document that the preview is non-binding because live pool configuration can change before actual acceptance. Teardown dry-run is deferred until the Section 10 teardown endpoint exists. Permanent documentation: `openspec/specs/fulfillment/spec.md#requirement-fulfillment-validation`.

- [x] 5.10 Add integration coverage that reads persisted prepared Ansible create and teardown inputs and verifies `vm_host`, `vm_target`, every VM create field, provider configuration snapshot, exact teardown identity derived from the durable settlement result, and that `deal_ref` is empty in every envelope this path constructs. Also verify that shared orchestration treats provider metadata opaquely and that malformed or contradictory Ansible metadata is rejected by `AnsibleFulfillmentProvider` rather than guessed.

  `test_fulfillment_api.py` drives `/fulfillment/validate` and `/begin` against real SQLite and a real job service (only `AnsibleService` mocked). It found and fixed a double-`BEGIN IMMEDIATE` bug (design.md, "Section 5 task 5.10 — integration coverage found and fixed a real transaction bug"). Teardown was covered through the provider directly; Section 10 added the endpoint.

- [x] 5.11 Correct `SettlementRepository.select_pending_for_single_worker`'s docstring (`kit/fulfillment/src/market_fulfillment/repository.py`) to describe the single-worker-vs-final-recovery-workflow distinction in stable terms with no OpenSpec section/task reference, per `AGENTS.md`'s production-comment rules — not merely renumbered from the stale "Section 7" it currently reads.

- [x] 5.12 Promote this section's accepted decisions into `openspec/specs/fulfillment/spec.md`, `openspec/specs/fulfillment/architecture.md`, `openspec/specs/resource-pool-management/spec.md`, and `docs/development/ARCHITECTURE.md` at the exact destinations named in tasks 5.1–5.9. Permanent documentation must describe the current acceptance, retry, two-transaction acknowledgement, dry-run, provider-neutral result handoff, and adapter-owned metadata contracts rather than the history of this change. Complete the Section 5 design-promotion record once each destination is written.

## 6. Add provisioning-owned recovery and lifecycle convergence

**Resequenced** (see `design.md`, "Section 5/6/7 resequencing decision"): this section was originally task-numbered 7 and planned to implement last; it now runs third, immediately after fulfillment acceptance (Section 5) and before migration/backfill (Section 7), so backfilled rows have a live convergence sweep to observe them rather than sitting frozen until this section eventually lands.

**Resolved during the discuss phase (see `design.md`, "Section 6 recovery and lifecycle convergence — resolved").** The eight items resolved there govern every subtask below: concurrent-claim safety under SQLite's single-writer contract, not a distributed multi-replica protocol; one watchdog running four handler passes, not five independent watchdogs; `resolve_provisioned_resources` called only once, at confirmed-success convergence, never at submission time; unbounded retry with backoff and jitter, never an attempt-count-triggered terminal state; and abandonment reconciliation closed as a no-op rather than built. A `dev`-branch implementation of this section was evaluated and reverted during this discussion (see `dev-branch-migration-notes.md`); nothing below depends on it.

- [x] 6.0 Replace `SettlementRepository.select_pending_for_single_worker` (task 3.11's documented placeholder) with `claim_pending(db, *, states, limit, lease_seconds, worker_id, now=None) -> list[SettlementRecord]`, a self-contained recovery-claim primitive that opens and commits its own `begin_sqlite_write_transaction`-guarded session rather than depending on a caller-supplied open transaction: select eligible rows, write the claim fields (`claimed_by`, `claim_expires_at`, increment `attempt_count`), and commit in one short transaction, releasing SQLite's writer slot before the caller does anything else. Add `clear_claim(db, capacity_reservation_id, *, worker_id) -> None`, a no-op if the row is no longer claimed by `worker_id` (so a slow worker can't clear a lease a faster one has since reclaimed). Retain `select_pending_for_single_worker`'s existing tests as coverage of the underlying lease-expiry/reclaim SQL shape, and add the independent-session, file-backed SQLite proof task 4.11/5.8 established as precedent: two real threads racing `claim_pending` against the same eligible rows, proving no row is ever returned to both. Permanent documentation: `openspec/specs/fulfillment/spec.md#durable-settlement-persistence` — describe this as the current recovery-claim mechanism (retire the "single-worker placeholder" language task 3.11 introduced) and state the SQLite single-writer concurrency contract honestly, per `design.md`'s Section 6 item 1.

- [x] 6.1 Implement `FulfillmentConvergenceWatchdog` in `compute_provisioning_service/services/fulfillment_convergence_watchdog.py` — one asyncio-timer class, composed once in `container.py`/`app_runtime.py` lifespan startup alongside `LeaseWatchdog`/`CapacityReservationWatchdog` (same constructor/`run()` shape and settings-lookup convention, e.g. `fulfillment_convergence_watchdog_poll_interval_seconds`). Each cycle runs the four handler passes from 6.2 in order, sharing this one timer rather than each owning its own. Per-row exponential backoff with jitter, keyed off `attempt_count`: extend `AnsibleJobService._calculate_retry_delay`'s existing formula (`retry_backoff_initial_seconds`/`_multiplier`/`_max_seconds`) with a new jitter setting (e.g. `_jitter_fraction`, applied as `delay * (1 ± jitter_fraction * random())`), and use the resulting delay as the lease length passed to `claim_pending` rather than a fixed lease. No database transaction is ever open while awaiting a provider call — every handler's shape is claim (short transaction) → external call outside any transaction → apply outcome (second short transaction), per `design.md`'s Section 6 item 5. Permanent documentation: `docs/development/ARCHITECTURE.md` (service composition — add this watchdog alongside the two existing ones).

- [x] 6.2 Add the four handler passes `FulfillmentConvergenceWatchdog` runs each cycle. Each is an independently callable, independently testable function/method — not something that requires the watchdog's asyncio loop to exercise in tests.
  - 6.2.1 Create-submission recovery: claim `dispatch_pending` rows lacking acknowledged provider metadata (6.0); call `provider.dispatch_create(prepared_create_operation)` per row outside any transaction — redispatch is safe via the executor's existing `idempotency_key` dedup (task 5.6), the same path `begin_fulfillment` already uses. On success, acknowledge and transition to `dispatching` (task 5.4's existing acknowledgement operation) and `clear_claim`. On failure, leave the row claimed; the next cycle's `claim_pending` call picks it up once the backoff-extended lease lapses.
  - 6.2.2 Create-status convergence: claim `dispatching` rows; call `provider.get_status(...)` per row outside any transaction. On `succeeded`, call `resolve_provisioned_resources` (6.3) and transition to `active`. On `failed`, transition to `failed` with the provider's failure detail. On `pending`, leave the row claimed with an extended lease. `clear_claim` on every terminal outcome.
  - 6.2.3 Teardown-submission recovery: same shape as 6.2.1 for `teardown_dispatch_pending` rows and `provider.dispatch_teardown(prepared_teardown_operation)`, transitioning to `tearing_down` on success.
  - 6.2.4 Teardown-status convergence: same shape as 6.2.2 for `tearing_down` rows. On `succeeded`, update every existing `ProvisionedResource` row for this `capacity_reservation_id` (no new rows — see 6.3) and transition to `torn_down`. On `failed`, transition to `teardown_failed` — not terminal; eligible for 6.2.3 recovery again, per the existing state comment in `db.py`.

  Permanent documentation: `openspec/specs/fulfillment/spec.md#durable-settlement-persistence` (recovery semantics per state) and `openspec/specs/fulfillment/architecture.md` (handler responsibilities).

- [x] 6.3 Add `FulfillmentProvider.resolve_provisioned_resources(provider_metadata: dict[str, Any]) -> tuple[str, ...]`, a new abstract method on the provider protocol — pure and synchronous, no I/O. Called by 6.2.2 exactly once, only when `get_status` reports `succeeded`, never earlier: a `ProvisionedResource` row must never represent a resource whose creation might still fail. Implement it for `AnsibleFulfillmentProvider` by decoding `vm_target` from the already-persisted `AnsibleFulfillmentMetadata` — known since dispatch acknowledgement (task 5.7), not something that requires the job to have completed. 6.2.2 calls `SettlementRepository.add_provisioned_resource` (existing, task 3.6) once per returned ref. 6.2.4 does not call this method; add a new repository method (e.g. `mark_provisioned_resources_torn_down(db, capacity_reservation_id) -> None`) that updates the `status` of the rows 6.2.2 already created, rather than resolving anything new. Permanent documentation: `openspec/specs/fulfillment/spec.md#durable-settlement-persistence` (provisioned-resource output timing) and the `FulfillmentProvider` protocol docstring in `provider.py`.

**Correction:** 6.0–6.3 were initially marked complete without the test coverage their own text requires, and with two related gaps, closed by 6.3.1–6.3.3 before 6.4–6.8 (which build directly on `claim_pending`/`FulfillmentConvergenceWatchdog`) began.

- [x] 6.3.1 Remove `SettlementRepository.select_pending_for_single_worker` (superseded by `claim_pending`, task 6.0) and its now-orphaned tests (`test_single_worker_selection_claims_matching_unclaimed_rows`, `test_single_worker_selection_skips_rows_with_a_live_claim`, `test_single_worker_selection_reclaims_rows_with_an_expired_claim`) from `test_settlement_repository.py`. Port their lease-expiry/reclaim assertions onto `claim_pending` — task 6.0's own text already called for retaining this coverage against the new method, not the old one.
- [x] 6.3.2 Add the concurrent-claim proof task 6.0 specified and never got: two real threads, independent sessions, file-backed SQLite (same technique as tasks 4.11/5.8), racing `claim_pending` against the same eligible rows, proving no row is ever claimed by both.
- [x] 6.3.3 Add test coverage for `clear_claim`, `mark_provisioned_resources_torn_down`, and `FulfillmentConvergenceWatchdog` (currently zero tests reference the watchdog module at all). At minimum one test per handler (`dispatch_pending_creates`, `converge_creates`, `dispatch_pending_teardowns`, `converge_teardowns`) covering: the success path; a provider exception leaving the claim intact for the next cycle; and `_with_owned_record`'s stale-claim discard (a second worker's claim on the same row invalidates a first worker's in-flight outcome, which must be silently dropped, not applied).
- [x] 6.3.4 Add a unique constraint on `ProvisionedResource(capacity_reservation_id, domain_resource_ref)`. `add_provisioned_resource`'s existing query-then-insert dedup is the primary idempotency mechanism (task 3.6); this constraint is the durable backstop against a genuine concurrent double-insert racing that check, not a replacement for it. Requires a schema migration alongside `db.py`'s model change.
- [x] 6.3.5 In `_converge_create_record`, catch `ProviderConfigInvalidError` from `resolve_provisioned_resources` specifically — not the surrounding generic exception handler — and transition to `failed` with a diagnostic `failure_reason` (e.g. `"invalid_provisioned_resource_metadata"`). Provider-reported success with unresolvable resource identity is a non-recoverable condition: the persisted metadata never changes between retries, so falling into the general retry path leaves the row backing off forever behind indistinguishable-from-healthy diagnostics, never actually converging. Every other exception at this call site continues through the existing general retry path unchanged.
- [x] 6.3.6 Split dedicated `fulfillment_convergence_backoff_initial_seconds`/`_multiplier`/`_max_seconds`/`_jitter_fraction` settings out from `retry_backoff_*`, which `AnsibleJobService` already owns for job-resubmission backoff — an accidental coupling identified in code review: one operator knob was controlling two unrelated retry loops (job-level resubmission within one convergence attempt vs. claim-lease length across convergence cycles). Move these settings' default values into `config.yml` rather than `settings.toml`, per this section's own established config-layering convention (`settings.toml` carries structure/documentation only; defaults live in the YAML layer so Helm/Compose overrides don't need to translate TOML).
- [x] 6.3.7 Correct the Section 6 entry in `design.md`'s implementation-promotion record: the fulfillment-convergence-worker composition note was written to `openspec/specs/fulfillment/spec.md#fulfillment-convergence-worker` during implementation (subsystem-specific behavior belongs in `openspec/specs`, not repository-wide `ARCHITECTURE.md`), not `docs/development/ARCHITECTURE.md#runtime-service-map` as currently recorded there.

- [x] 6.4 Prove recovery correctness across restart, transient provider failure, and worker death, using the same independent-session/file-backed-SQLite technique as 6.3.2 rather than real process/subprocess management, which this codebase has no existing pattern for and which task 6.7's tests should not be the first to introduce:
  - 6.4.1 Worker-death simulation: commit a claim via `claim_pending` and never apply an outcome (the same shape a crash between claim and provider call produces); prove the row is invisible to further claims until `claim_expires_at` lapses, and reclaimable by a fresh `claim_pending` call the moment it does — no operator intervention required.
  - 6.4.2 Restart simulation: construct a fresh `FulfillmentConvergenceWatchdog`/session against the same file-backed SQLite database mid-cycle and prove it resumes from durable `SettlementRecord` state alone, with no dependency on the previous instance's in-memory state.
  - 6.4.3 Transient-failure retry: a `provider.dispatch_create`/`get_status` call that raises leaves the row retryable with backoff (verified via `attempt_count` and `claim_expires_at` growth across repeated claims), never transitioning to a terminal state on its own. Confirmed against both the atomic outcome-application contract already documented in `openspec/specs/fulfillment/spec.md#durable-settlement-persistence` (`_with_owned_record`'s expected-state-and-claim-owner check) and the unbounded-retry posture from `design.md`'s Section 6 item 4 — this task proves what's already implemented and documented, it does not change either.
  - This is distinct from, and does not change, `LeaseLifecycleService`'s own `release_failed`/force-release mechanism for capacity-reservation-level release.

- [x] 6.5 Add operator-facing recovery diagnostics as a single method (e.g. `SettlementRepository.recovery_diagnostics(db) -> RecoveryDiagnostics`), reporting, per relevant lifecycle state: total non-terminal row count; currently-claimed row count; expired-but-unclaimed row count (a transient query result surfaced for trend-watching, not itself an error condition); oldest row age from `created_at`; `attempt_count` distribution (at minimum max, reasonable to bucket); and terminal `failed`/`teardown_failed` counts. The schema stores only the aggregate's current state and latest failure, not a history of transient per-attempt provider-call failures — that remains covered by `attempt_count` and retry age, not a separate durable event log; a durable per-attempt history is materially larger scope than this task justifies and is not part of it. `FulfillmentConvergenceWatchdog` logs this once per cycle (structured logging), not once per row.

- [x] 6.6 Close task 6.2's originally-planned fifth handler — abandonment reconciliation — as a no-op rather than implementing it. Per `design.md`'s Section 6 item 7: `SettlementAbandonmentHook` (Section 4, tasks 4.5.1–4.5.4) already fires synchronously and unconditionally, in the same transaction as the capacity mutation, from every capacity-reclaiming path (`_expire_stale_holds`, `release()`, `resize_reservation`'s supersede step) — there is no commit-ordering gap for a periodic sweep to close. Documentation-only: no production no-op function, no new tests. Record the accepted decision in the design-promotion record (6.8).

- [x] 6.7 Add tests covering: the 6.3.2/6.4 concurrent-claim and crash/restart proofs (if not already landed by those tasks); the 6.3.4 unique-constraint idempotent-insert guarantee (concurrent `add_provisioned_resource` calls for the same `capacity_reservation_id`/`domain_resource_ref` produce exactly one row); the 6.3.5 `ProviderConfigInvalidError` terminal-failure path; backoff/jitter determinism via `Backoff.random_source` (a fixed injected `Random` produces a reproducible delay sequence; two different injected sources produce different sequences for the same `attempt_count`); and eventual convergence (a row that fails N times then succeeds reaches its terminal state; no row is left permanently stuck absent an explicit terminal provider result or the 6.3.5 non-recoverable path). Cover both create and teardown paths.

- [x] 6.8 Complete the Section 6 design-promotion record, mapping every accepted decision — including the 6.3.1–6.3.7 follow-ups and the 6.4–6.7 resolutions above — to its permanent documentation location (see `design.md`'s Section 6 permanent-documentation-impact table, corrected by 6.3.7). Remove references to this change's `design.md`/task chronology from any production docstrings/comments touched by this section, per the repository-wide rule task 3.15 established (the `app_runtime.py` comment fix from code review is the model to match elsewhere in this section's code).

**Correction: external code review found two real correctness gaps in 6.4–6.8's implementation (both confirmed and fixed), plus several documentation and test-quality issues, also fixed. Recorded here since they landed after 6.4–6.8 were first checked off:**

- [x] 6.9 Fix `_with_owned_record`'s outcome-application race: acquire SQLite's write reservation before reading and checking ownership, not after. A plain SELECT does not open a SQLite-level transaction on its own, so the original check-then-write sequence let a worker whose lease had already been reclaimed still commit a stale outcome on top of the new owner's claim. Added a permanent regression test using the same controlled-timing technique that confirmed the bug (see `design.md`'s Section 6 promotion record for the full account). `claim_pending`'s callers now catch the resulting `OperationalError` under genuine contention and defer to the next cycle rather than aborting the whole cycle.
- [x] 6.10 Implement the `teardown_failed` retry the spec/`db.py` state comment already documented but nothing performed: `requeue_teardown_failures`, a distinct step (the transition table only allows `teardown_failed -> teardown_dispatch_pending`, not directly to `tearing_down`) run at the start of each cycle, so a freshly-requeued row is picked up by `dispatch_pending_teardowns` the same cycle.
- [x] 6.11 Fix `recovery_diagnostics`'s `expired_unclaimed` field name — it counts rows that **are** claimed with a lapsed lease, not unclaimed rows; renamed to `expired_claims`. Isolate `_log_diagnostics` failures from the operational cycle result. Give `Backoff.random_source` a field factory (one generator per instance) instead of constructing a new `Random()` every call when unset. Make `FulfillmentConvergenceWatchdog`'s `worker_id` constructor-injectable instead of only internally generated.
- [x] 6.12 Fix test-quality gaps: the backoff-growth test asserted only that later timestamps were larger (which wall-clock drift alone could satisfy even with a broken/constant lease), and never exercised the actual watchdog dispatch path against a failing provider — rewritten to call `dispatch_pending_creates()` against a real failing `_StubProvider` and assert real deltas against a captured baseline, not just ordering. Removed `Task 6.x`/`tasks.md` references from test docstrings and comments.
- [x] 6.13 Fix stale/contradictory permanent documentation: `openspec/specs/fulfillment/spec.md` referenced the pre-rename `test_repository.py` path; `openspec/specs/fulfillment/architecture.md` still described scheduler assignments, policy cursors, and the fulfillment registry as process-local with "no durable generic Settlement Record aggregate" — contradicting the system this change built, predating even Section 6. Rewrote the architecture doc's persistence section to describe the current durable model and point at this section's spec text.

**Code-review follow-up tasks:**

- [x] 6.14 Replace `recovery_diagnostics`'s raw nested-dict return with a typed model (`RecoveryDiagnostics`/`RecoveryStateDiagnostics`, roughly as task 6.5's own text suggested) to prevent drift between repository output, logging, tests, and any future status endpoint.
- [x] 6.15 Decide and document explicitly whether `recovery_diagnostics`'s oldest-row-age and max-attempt-count are meant to be per-state (matching `total`/`claimed`/`expired_claims`) or global across all non-terminal states (the current, undocumented implementation choice) — the review correctly noted this is inconsistent and unresolved, not just unclearly named.
- [x] 6.16 `recovery_diagnostics` runs roughly a dozen queries per watchdog cycle (several per state, plus global aggregates); collapse into one or two grouped SQL aggregate queries. Not urgent at current scale per the review's own assessment, but worth doing before this is under real load.
- [x] 6.17 Add a test asserting the diagnostics logging contract directly: exactly one structured log event per completed cycle, none per row, and an event still emitted on a cycle with zero non-terminal rows.


## 7. Migrate existing hosts and active leases

**Resequenced** (see `design.md`, "Section 5/6/7 resequencing decision"): this section was originally task-numbered 5 and planned to implement first; it now runs last of the three, after the durable fulfillment-acceptance path (Section 5) and recovery/convergence (Section 6) it depends on both exist and are proven against freshly-created rows.

**Design resolved** (see `design.md`, "Section 7 (migrate existing hosts and active leases) — resolved design decisions"): this is a pre-release cutover. Legacy VM leases and their known Ansible operations are the safety-critical source; POOLS-only reservation states were never shipped. Migration is validation-only on failure, never speculative repair, and all Section 7 writes are atomic across the complete candidate set.

- [x] 7.1 Section 2's migrations (`_migrate_resource_pools_and_hosts_pool_id`, `_migrate_capacity_model_cutover` — `_migrate_site_resources_pool_id`, `_migrate_capacity_buckets_and_current_debits`, `_migrate_retire_site_resources`) already create the default resource pool and migrate every existing host and pool-membership/resource-capacity record. No new host/pool/bucket/debit migration work remains here.
- [x] 7.2 Add a versioned compute-service migration in `provisioning/compute/service/src/compute_provisioning_service/db/migrations.py` that enumerates nonterminal legacy VM leases and joins them to capacity reservations, hosts/resource-pool membership, pool provider configuration, and existing settlement/provisioned-resource rows. Treat the lease as authoritative for candidate enumeration; unmatched pre-release reservations may be discarded and must not obscure a lease.
- [x] 7.3 State mapping and provider-preparation extracted into a pure compiler; `_migrate_legacy_vm_leases_to_fulfillment` no longer performs either itself.
  - [x] 7.3.1 The kit's `backfill.py` holds the shared draft, error, and compiler types; the VM adapter's `legacy_backfill.py` holds the VM compiler and `prepare_historical_vm_teardown`. The extraction found a gap 7.7 had missed: a live target with no known `create_job_id` failed opaquely deep in the provider stack, and the compiler now rejects it with `LegacyBackfillValidationError`.
  - [x] 7.3.2 `_apply_legacy_vm_lease_backfill(connection, ...)` owns enumeration, dedup, conflict comparison, and the atomic write, so tests call it directly without the once-per-migration gate.
- [x] 7.4 Derive one canonical aggregate per candidate: preserve/generate the `capacity_reservation_id` and `fulfillment_id` required by the current schema; resolve `settlement_resource_id`, `pool_id`, provider, and selected-resource attributes from the migrated host; validate `vm_target`/`executor_target`; create a `ProvisionedResource` for active and teardown-related rows; and preserve known create/teardown job identifiers in provider metadata.
- [x] 7.5 Build `prepared_teardown_operation` through the current VM/Ansible provider contract rather than hand-assembling provider JSON: construct the canonical provider-neutral settlement result, resolve the snapshotted `AnsiblePoolConfig`, call `prepare_teardown`, and persist its `VersionedEnvelope`. Historical create request/prepared-create data may be absent based on lifecycle state; do not add an origin/backfill field or any runtime branch on migration provenance.
- [x] 7.6 Enforce create replay safety. A historical `provisioning` lease must have a usable known create job and remain `dispatching` so recovery observes it. A known failed job may use normal provider retry behavior later, but migration must never submit or schedule a replacement create operation because the prior job identity was lost or ambiguous.
- [x] 7.7 Add minimal fail-loud validation for missing host, non-unique or missing pool/resource resolution, missing usable VM Ansible configuration, missing/conflicting VM target, missing required create/teardown job identity, duplicate candidate identity, and conflicting existing aggregate/output rows. Accept exactly equivalent target rows for idempotent reruns; never overwrite conflicts or implement repair/reconciliation behavior. **Extended:** now also rejects a live target with no known create job identity (see 7.3.1).
- [x] 7.8 Make the complete backfill atomic: derive and validate every candidate before commit, insert all settlement and provisioned-resource rows in one database transaction, and roll back every Section 7 write on any failure. Ensure the migration is safely rerunnable with no partially migrated population visible.
- [x] 7.9 Full scenario matrix covered:
  - [x] 7.9.1 `provisioning/compute/service/tests/unit/services/test_legacy_vm_fulfillment_backfill.py` — compiler-level unit tests (no engine): provisioning with tracked create job, active lease, releasing before/with teardown dispatch, failed teardown, missing host/pool/provider, missing pool config, conflicting `vm_target`/`executor_target`, missing create job (provisioning and live-target cases), unsupported status.
  - [x] 7.9.2 `provisioning/compute/service/tests/unit/test_legacy_vm_lease_migration.py` — DB-level tests calling `_apply_legacy_vm_lease_backfill` directly: terminal/expired skip, unmatched-reservation tolerance, equivalent rerun, whole-migration rollback, and conflicting duplicate covering every field the equivalence check compares — different `create_job_id`, different teardown job ID, missing `prepared_teardown_operation`, missing `ProvisionedResource` row, `ProvisionedResource` row with a different `domain_resource_ref`, and multiple `ProvisionedResource` rows. The last six were added when review found the conflict check compared only four coarse fields (design.md, "Third code-review pass").
  - [x] 7.9.3 Covered by `test_provisioning_without_tracked_create_job_is_rejected` and `test_live_target_without_known_create_job_is_rejected` in 7.9.1 — both assert `LegacyBackfillValidationError`, never a dispatched create.
- [x] 7.10 `provisioning/compute/service/tests/unit/services/test_fulfillment_convergence_after_legacy_backfill.py` runs `run_migrations` against a populated pre-migration schema producing one backfilled row in each of `dispatching`, `teardown_dispatch_pending`, `tearing_down`, and `teardown_failed`, then drives `FulfillmentConvergenceWatchdog.converge_creates`/`dispatch_pending_teardowns`/`converge_teardowns`/`requeue_teardown_failures` (and a full `run_cycle` loop) against them and asserts each converges to `active`/`torn_down` exactly as a natively-created row would.
- [x] 7.11 Promote durable design knowledge during implementation:
  - `openspec/specs/fulfillment/spec.md`: historical lifecycle mapping as current aggregate semantics, known-job observation, state-based required inputs, idempotent rerun/conflict behavior, and no speculative create fallback.
  - `openspec/specs/fulfillment/architecture.md`: why active lease/provider-operation continuity outranks unused pre-release reservations and why the cutover is all-or-nothing.
  - `openspec/specs/physical-provisioning/spec.md` and its architecture companion: VM/Ansible target derivation, provider metadata preservation, and teardown-envelope preparation through the current provider contract.
  - `docs/development/ARCHITECTURE.md`: repository-wide authority and transaction rule for atomic legacy-lease-to-fulfillment cutover.
- [x] 7.12 Complete the active change's design-promotion record with the exact permanent headings used above, and ensure production code/comments mention only present invariants and stable permanent documentation—not Section 7, POOLS-7, migration chronology, or backfill provenance.

### Section 7 correction pass

- [x] 7.13 Promotion record relocated into `design.md`'s "Section 7 implementation promotion record". **Validation:** the three Section 7 test modules ran, and the `kit/fulfillment` and provisioning service suites passed; review's rerun/conflict gap is fixed (7.9.2).
- [x] 7.14 Added the missing "Permanent documentation impact" checklist to `proposal.md`.
- [x] 7.15 Normalize a legacy `vm_leases` table that predates optional teardown-job tracking before enumerating fulfillment candidates. The full migration-replay fixture omits `vm_remove_job_id` and proves the cutover succeeds; the permanent scenario lives in `openspec/specs/fulfillment/spec.md#requirement-existing-lease-continuity-during-fulfillment-cutover`.

## 8. Implement pull-based fulfillment status and result queries

Push-based `SettlementResult` delivery was designed (see `design.md`,
"`SettlementResult` delivery: pull for v1, push deferred to a separate
change") but requires a new provisioning→storefront authenticated
channel that does not exist yet. Building that channel is split out to
`replace-polling-with-authenticated-push` (separate change, not yet started)
rather than built here, to avoid scope creep into an already-large
change. This section implements pull instead, over the existing
storefront→provisioning auth direction — durable persistence (section 3)
is unaffected; only the delivery transport differs from the original
design.

**Resolved during the discuss phase (see `design.md`, "Section 8
pull-based status/result and live credentials — resolved design
decisions").** Six items resolved there govern the subtasks below:
credentials are fetched through a new stateless, provider-neutral
`FulfillmentProvider.fetch_credentials` method with no claim/lease and no
rotation bookkeeping (candidate claim/lease/rotation shape from
`dev-branch-migration-notes.md` rejected as solving a problem this
codebase doesn't have); `credential_generation` is dropped from scope
entirely rather than shipped as a dead field; a live credential fetch is
attempted only when the aggregate is `active`, never any other state;
credential-fetch failure on an otherwise-healthy `active` fulfillment is
its own stable-error-taxonomy category, distinct from a create/status
failure; and the result contract is a real versioned envelope
(`fulfillment.result.v1`).

**Correction (post-implementation review):** the discuss-phase
credential-keying decision originally recorded here — one credential per
`ProvisionedResource`, addressed by `domain_resource_ref` — was implemented
as first written, then rejected on review and replaced. The shipped design
associates credentials with outputs many-to-many through the
fulfillment-owned `provisioned_resource_id`, with `domain_resource_ref`
removed rather than kept as a second identifier. See tasks 8.9/8.10 below,
`design.md`'s "Section 8 review corrections accepted for planning," and
`openspec/specs/fulfillment/spec.md` for the shipped shape. The subtask
notes immediately below (8.2, 8.3, 8.8) predate that correction and
describe the rejected `CredentialSet`/per-resource design; they are kept
as implementation history but are superseded by 8.9/8.10.

Former task 8.5 (per-caller ownership enforcement) is **out of this
section's scope** and moves to `service-identity-signing`
(new change), which gives the provisioning service
real per-request caller identity. `StorefrontAuthMiddleware`'s single
shared `admin_api_key` has exactly one trusted caller by construction, so
there is no caller identity for an ownership check to compare against
today; see that change's `design.md` for the accepted shape. Section 8
ships against the existing single-tenant trust model and adopts real
per-caller enforcement once that change lands.

- [x] 8.1 Implement `get_fulfillment_status(fulfillment_id)`, reading directly from the durable fulfillment aggregate (section 3) — no separate outbox or delivery-acknowledgement state, and no provider/Ansible call of any kind; a read reflects current state on demand from the repository alone. **Done: `FulfillmentOrchestrator.get_fulfillment_status`; `GET /fulfillment/{fulfillment_id}/status`.**
- [x] 8.2 Implement `get_fulfillment_result(fulfillment_id)`, returning the normalized result contract as a `fulfillment.result.v1` versioned envelope (`fulfillment_id`, `capacity_reservation_id`, aggregate state, provisioned-resource outputs, failure details) without persisting credentials. Non-`active` states return the envelope with empty/null credential and provisioned-resource-output fields rather than an error — the aggregate's current state and failure detail are still meaningful before or after `active`. **Done: `get_fulfillment_result` (`results.py`); `GET /fulfillment/{fulfillment_id}/result`. As shipped after 8.9, the envelope carries an optional versioned `domain_result`.**
- [x] 8.3 Add `FulfillmentProvider.fetch_credentials(...)` (new abstract method, alongside `resolve_provisioned_resources`; async, since it performs provider I/O). `get_fulfillment_result` calls it directly and unconditionally when, and only when, the aggregate is `active` — no claim, no lease, no generation-advancement side effect, since there is nothing durable being coordinated or mutated. Transmit credentials only in that response over the authenticated channel and do not persist them afterward. **Done: `fetch_credentials(provider_metadata, provisioned_resources) -> VersionedEnvelope[Any]`, the adapter owning the nested payload (8.9). The read transaction closes before the provider call (design.md, "Section 8 implementation confirmation").**
- [x] 8.4 Add a `credential_fetch_failed` category to the stable error taxonomy (`openspec/specs/fulfillment/spec.md#requirement-stable-error-taxonomy`) for a live credential-fetch failure on an `active` fulfillment, distinct from create/status/teardown failure categories, so the storefront can retry the read rather than treat it as a workload failure. **Done: `CredentialFetchFailedError`, mapped to HTTP 503 `credential_fetch_failed`.**
- [x] 8.5 Add an existence-only check rejecting a query for an unknown `fulfillment_id`/`capacity_reservation_id` (i.e., not present in this provisioning service's own database). This is not a per-caller ownership check — `StorefrontAuthMiddleware` admits exactly one trusted caller today, so there is no second caller identity to distinguish. Structure the check so `service-identity-signing`'s later `owner_principal` comparison can replace it without reshaping the endpoint. **Done through 8.1/8.2: an unknown identifier is 404 `fulfillment_not_found`. Per design.md's Section 8 record (amended 2026-08-06), no successor now adds a per-record ownership check.**
- [x] 8.6 Add tests for: query after process restart, query for a fulfillment that never reaches `active` (empty credentials/outputs, no provider call attempted), repeated queries returning consistent state, a live credential-fetch failure surfacing `credential_fetch_failed` while the aggregate state is unaffected, and query for an unknown identifier. **Done.** `kit/fulfillment`'s `test_fulfillment.py`/`test_results.py` cover no-provider-call reads, every non-`active` state's empty result, the `active` projection with a live fetch, `CredentialFetchFailedError` leaving state unchanged, unknown identifiers, and the envelope. `test_fulfillment_api.py::TestStatusAndResultQueries` covers the same over HTTP against credentials the job pipeline wrote. Narrowed at the time: restart was a fresh instance against the same database, not a process restart, and repeated reads had no dedicated test; 8.13 added both.
- [x] 8.7 Record `replace-polling-with-authenticated-push` as a named follow-on in this change's implementation notes/README so its dependency on this section's durable persistence layer and `fulfillment.result.v1` envelope (not needing to be redesigned) is visible to whoever picks it up. Also record `service-identity-signing` as the follow-on that upgrades 8.5's existence check to real per-caller ownership enforcement. **Done:** both edges are in `openspec/changes/README.md`.
- [x] 8.8 Promote this section's accepted decisions — the provider-neutral `fetch_credentials` contract, `active`-only credential fetch gating, the `fulfillment.result.v1` envelope shape, the `credential_fetch_failed` error category, and the credential-resolution boundary — into `openspec/specs/fulfillment/spec.md` and `architecture.md`, and complete this section's design-promotion record. **Done:** `openspec/specs/fulfillment/spec.md`'s "Fulfillment status and result queries", "Provider contract", and "Stable error taxonomy". The VM payload went to physical-provisioning's "VM fulfillment result payload", since replaced by "Delivery says how to reach what was provisioned" (`bare-metal-mock-provisioned-deal`).

8.1–8.8 predate the review that changed the credential and result shape; 8.9–8.15 below are Section 8's final state.

### Section 8 correction tasks

- [x] 8.9 Replace the generic credential/result shape with a provider-neutral outer `fulfillment.result.v1` envelope carrying a versioned domain payload. Define the VM-domain payload and `VmFulfillmentCredential` in the VM/compute boundary, preserve all credential material as response-only data, and model credential-to-output association as many-to-many through `provisioned_resource_id`. **Permanent documentation:** `openspec/specs/fulfillment/spec.md` for the generic envelope/provider boundary; the authoritative VM provisioning specification for the VM payload and credential fields.
- [x] 8.10 Remove `domain_resource_ref` from the generic `ProvisionedResource` persistence and result contracts, including its uniqueness assumptions and migrations. Continue to use globally unique `provisioned_resource_id` for fulfillment-owned output identity; retain `vm_host`, `vm_target`, job IDs, and other provider-operational identifiers only in versioned provider metadata or prepared teardown input. Update all repositories, adapters, tests, and backfill paths consistently. **Permanent documentation:** `openspec/specs/fulfillment/spec.md#durable-settlement-persistence`; `openspec/specs/fulfillment/architecture.md` for the identifier ownership boundary; `docs/development/ARCHITECTURE.md` only if the repository-wide vocabulary table currently names this identifier.
- [x] 8.11 Define active-result consistency and failure semantics in code and tests: every active result read performs a fresh credential lookup; durable aggregate/output fields remain stable unless the aggregate changes; credential equality across reads is not guaranteed; result reads do not mutate fulfillment state; and any required credential-fetch failure rejects the whole result with `credential_fetch_failed` rather than returning a partial security result. **Permanent documentation:** `openspec/specs/fulfillment/spec.md#requirement-fulfillment-status-and-result-queries`; `openspec/specs/fulfillment/architecture.md`. **Done:** five tests in `test_fulfillment.py` (fresh fetch per read, stable durable fields, no write, unexpected exceptions rejected whole). Promoted to the spec's "Fulfillment status and result queries" and "Provider contract" and the companion's "Fulfillment result ownership".
- [x] 8.12 Keep expected metadata/provider/credential-store exception classification in each adapter, add a defensive orchestration wrapper for unexpected provider exceptions, and emit only safe structured diagnostics (`fulfillment_id`, provider identity, stable error category) without raw provider metadata or credential material. Add focused Ansible adapter tests for malformed metadata, missing/null job identity, missing job, credential-store failure, multiple credential roles, and unexpected exceptions. **Permanent documentation:** `openspec/specs/fulfillment/spec.md#requirement-provider-contract`; `openspec/specs/fulfillment/architecture.md`.
- [x] 8.13 Strengthen result-query validation with dedicated tests: fresh service composition against the same file-backed SQLite database after disposing the first composition; repeated status and non-active result reads; repeated active result reads asserting stable durable fields and fresh provider calls without credential-equality assumptions; multi-resource/multi-credential many-to-many association; provider I/O occurring after the read transaction closes; and aggregate state remaining unchanged on credential-fetch failure. **Done:** repeated-read tests, a transaction-closed-before-I/O assertion, and a two-resource/two-credential association test; output identity derivation centralized in `market_fulfillment.ids`. `test_fresh_service_composition_reads_status_and_result_from_same_file_database` now lives in `kit/fulfillment/tests/integration/test_fulfillment_restart.py`.
- [x] 8.14 Make the HTTP result contract explicitly typed for FastAPI/OpenAPI, remove stale comments claiming credential fetch is unimplemented or credentials are always empty, and ensure production comments describe only current invariants. Build and inspect the fulfillment wheel, install it through the repository-standard review path, verify `market_fulfillment/results.py` and the domain payload are packaged, and run the affected compute API tests against installed artifacts. **Done:** typed `response_model` on the result route; stale comments removed; the wheel packaged the adapter's result module (since removed by `bare-metal-mock-provisioned-deal`). Suite evidence is 8.15's.

**Correction (fix loop):** 8.9, 8.10, 8.12, and 8.13 were marked done on a diff that did not run against the real service. Five bugs were found and fixed (design.md, "Section 8 correction tasks — fix-loop debugging record").

- [x] 8.15 Run the repository-standard wheel-based build/install/test path for `kit/fulfillment` and `provisioning/compute/service` against the post-fix-loop code, and run `openspec validate --all --strict`. **Done in the final review pass:** `kit/fulfillment` and `make test-provisioning` passed on the wheel path. Strict validation ran for the first time: the change validated, and it exposed structural errors in five permanent specs, which 12.2 fixed. Section 8's own text had made this task a gate for Section 9, and Section 9 began before it closed (proposal.md, "Knowledge to promote").

**Section 8 complete.**

## 9. Cut over storefront orchestration

- [x] 9.0 Add the server endpoint, shared client contracts, and storefront-side
  routing that `schedule_resource` needs before any storefront cutover can
  begin — identified during this section's design review (`design.md`,
  "Section 9 design review"); none of 9.1–9.7 as originally written account
  for this work, and 9.2 cannot be implemented without it.
  - [x] 9.0.1 Add `POST /fulfillment/schedule` to
    `provisioning/compute/service/src/compute_provisioning_service/controllers/fulfillment_controller.py`,
    wrapping `PhysicalSettlementScheduler.schedule_resource` the same way
    `/begin` wraps `FulfillmentOrchestrator.begin_fulfillment` — same
    404/409/422 error-mapping conventions as the existing routes
    (`SettlementEntityNotFoundError`/`NoEligibleSettlementResourceError`/etc.).
    **Done,** also mapping `CapacityReservationExpiredError` and
    `SettlementRequestMismatchError` to 409; `TestScheduleEndpoint`. Promoted
    by 9.8.1.
  - [x] 9.0.2 Move `FulfillmentRequestBody`, `FulfillmentAcceptanceResponse`,
    `FulfillmentStatusResponse`, `FulfillmentValidationResponse` out of
    `fulfillment_controller.py` (server-only today) into
    `provisioning/compute/src/compute_provisioning/contracts.py`, matching
    every sibling contract already there (`ExecutorActionEnvelope`,
    `ProvisioningJob`, `LeaseRegistration`, ...). Add a new
    `FulfillmentScheduleRequest`/`FulfillmentScheduleResponse` pair for
    9.0.1's route. Each new/moved model gets a `contract_version` field via
    `VersionedContractModel`, independent of and not collapsed into
    `market_fulfillment`'s own `VersionedEnvelope`/`schema_version` axis —
    two deliberately separate version concepts (design.md, item 3).
    `fulfillment_controller.py` imports these from `compute_provisioning`
    rather than declaring local duplicates. **Done;** `compute_provisioning`
    depends on `arkhai-kit-fulfillment` for `VersionedEnvelope` and
    re-exports the six models.
  - [x] 9.0.3 Add `schedule`, `begin_fulfillment`, `get_fulfillment_status`,
    `get_fulfillment_result` methods to `ComputeProvisioningClient`
    (`provisioning/compute/src/compute_provisioning/client.py`), calling
    9.0.1/existing routes with 9.0.2's contracts. `ComputeProvisioningClient`
    is not renamed and not split — verified during the design review that
    every model in `contracts.py` is free of dimension/shape coupling
    (`ram_gb`/`vcpu_count`/`gpu_count`/`dimensions` do not appear anywhere in
    that file), and `openspec/specs/physical-provisioning/spec.md`'s
    "Compute-owned caller contract" requirement already documents
    `fulfillment` as one of the generic surfaces this client is meant to
    cover, alongside job/lease/capacity. Permanent documentation
    destination: `openspec/specs/compute-provisioning-contract/spec.md`, new
    requirement(s) alongside "Versioned executor action submission" and
    "Allocation-backed lease control". **Done,** as `schedule_resource`
    (the kit's name) and the other three, with the protocol extended.
    Promoted by 9.8.2.
  - [x] 9.0.4 Add a new sibling aggregator (module/class name decided at
    implementation time, e.g. `AggregateComputeProvisioningClient`) mapping
    site name → `ComputeProvisioningClient` instance, in
    `market_storefront/services/capacity_client.py` or a new
    `core_storefront` module if the shape turns out domain-neutral once
    written. Routes the four new calls the same way
    `AggregateCapacityClient` routes `commit`/`release`: owning-site cache
    hit first, fan-out to the rest on a cold cache (idempotent-retry
    contract from Sections 3/4 makes a wrong-site try before the right one
    safe, just slower). Do **not** add these methods to
    `AggregateCapacityClient`/`RemoteCapacityClient` themselves — both are
    deliberately scoped to the `CapacityClient` protocol's
    `/api/v1/capacity` site-ledger surface only. **Done as
    `AggregateFulfillmentClient` in `market_storefront/services/capacity_client.py`,**
    built by `build_fulfillment_client`. `core_storefront` cannot host it:
    core may not depend on `compute_provisioning`. Status and result take an
    optional `capacity_reservation_id` for routing, since the shared cache is
    keyed by it. `test_aggregate_fulfillment_client.py`.
  - [x] 9.0.5 Promote `AggregateCapacityClient._reservation_sites`
    (`core_storefront/aggregation.py`) from private, class-owned state to a
    shared mapping object the composition root
    (`market_storefront/services/capacity_client.py`'s `_aggregate_for`)
    constructs once and passes to both the capacity aggregator and 9.0.4's
    new aggregator, so a `capacity_reservation_id`'s learned site is not
    tracked twice. No dedicated subsystem spec currently documents
    `core_storefront`'s storefront-side capacity aggregation at all (checked:
    no `openspec/specs/*` file references `AggregateCapacityClient` or
    `core_storefront/aggregation`); this decision's durable rationale is
    documented in the module's own docstring, matching that file's existing
    style, not promoted into a new spec file for this one mechanism.
    **Done:** an optional `reservation_sites` argument and property;
    `build_fulfillment_client` reads the same instance.
  - [x] 9.0.6 Add `fulfillment_id` (physical-provisioning aggregate identity)
    to `ARCHITECTURE.md`'s "Shared vocabulary and identities" table
    alongside a new `fulfillment_uid` entry (on-chain settlement-claim
    identity, already used throughout the storefront but never documented
    there), with a one-line note distinguishing them. Keep `fulfillment_id`
    bare when persisted in 9.3 below — no column rename to
    `provisioning_fulfillment_id` (design.md, item 3 — tried first, not
    committed permanently). **Done:** `ARCHITECTURE.md`'s identifiers
    section distinguishes `fulfillment_uid` from `fulfillment_id`.

  **Validation:** 9.0's suites ran against source only, with environment
  gaps disclosed (design.md, "Rationale moved from task notes at closeout",
  9.0); wheel-based validation came with 8.15.


- [x] 9.1 Replace host-shaped ordinary storefront reservation assumptions with the implemented POOLS-4 capacity-reservation claim and owning-site routing. **Correction (design review):** the claim-shape half of this task is already done — `vm_job_spec_service.compute_capacity_claim_from_order` already builds a pool/resource/dimension-shaped claim, not `required_attributes=("vm_host",)`. What remains under this task number is narrower: confirm no other call site still assumes a bare `vm_host`-only claim, and that owning-site routing (9.0.4/9.0.5) is wired before 9.2 needs it. The actual `vm_host`-direct-to-executor hand-off this task's original text was really describing is 9.2's concern, not this one's. **Done:** the only `vm_host`-dependent dispatch left was the hand-off 9.2 replaced; the other references were inventory matching or an admin dry run.
- [x] 9.2 Replace direct `ExecutorActionEnvelope` submission and provider-job polling with `schedule_resource` followed by `begin_fulfillment` when the commercial workflow is ready, using 9.0's new client methods. Use `market="vms"` (design.md, item 6 — matches the existing integration test and the `domains/vms` package name; no other convention documented anywhere). **Do not remove the `_register_vm_lease_with_settings`/`register_lease` call site as part of this task** — traced during the design review: it writes `offering_mode`/`executor_target`/`executor_ref` onto the same `CapacityReservation` row `LeaseLifecycleService`/`VmReleaseExecutor.submit_release` reads to route and act on release. Removing it here would strand every VM fulfilled through this new path with no way for the watchdog to find or route its teardown at all. Leave `register_lease` calling as before. **Update (Section 10):** `register_lease` stayed as the release trigger; 10.7 found `executor_ref` droppable but `executor_target` load-bearing. `bare-metal-mock-provisioned-deal` later removed lease registration entirely.

  **Done.** Building the request surfaced four parity gaps, each fixed: connectivity (a `connectivity` request field, since deleted by the fix for pre-closeout review 17 F1), optional VM sizing with pool defaults, and the credential and connection fields the result had dropped (design.md, "Section 9 implementation confirmation" and "Rationale moved from task notes at closeout", 9.2). Comments citing task numbers were rewritten.

  **Storefront-side rewiring.** `_do_provision` runs `schedule_resource` →
  `begin_fulfillment` → poll status → result through the unchanged
  `provision_vm` seam, mapping the result back to the shape
  `fulfill_vm_obligation` expects. The VM storefront depends on
  `arkhai-kit-fulfillment`, and its `reinit` refreshes that kit and its two
  transitive kits; the root `Makefile`'s `dist-*` targets gained the kit
  build as a prerequisite. A real `make test` caught the transitive `reinit`
  gap the sandbox could not (design.md, "Rationale moved from task notes at
  closeout", 9.2). Evidence: `test_fulfillment_provisioning.py`, verified
  then with `alkahest_py` stubbed.
- [x] 9.3 Persist `capacity_reservation_id`, selected settlement resource, and returned `fulfillment_id` in storefront workflow state so negotiation and fulfillment resume after restart. **Done.**

  **Correction (external review):** the task text overclaimed. The identifiers were persisted as each became known, but nothing read them back to resume after restart; 9.9–9.18 built recovery (design.md, "Section 9 reconciled status"). Fixes from that review: `reserve()` became idempotent by escrow, persistence retries and escalates (`persist_escrow_fields_with_retry`), `fulfillment_id` reached the three settlement responses, and a callback writing `fulfillment_id` into `provisioning_job_id` was corrected. Evidence: `test_sqlite_client_escrow_fulfillment_identity.py` and `test_fulfillment_provisioning.py`; the three `serialize_settlement_job` tests were disclosed as unrun at the time (design.md, "Rationale moved from task notes at closeout", 9.3).
- [x] 9.4 Poll `get_fulfillment_status`/`get_fulfillment_result` (pull-based, per section 8) at appropriate points in the storefront's workflow and deliver/retain buyer-facing credential state according to the storefront's security model. **Done in 9.2's `_do_provision`:** poll to terminal, fetch the result once, and hand it to the unchanged credential storage (`granted_to="self"`), so the storefront's security model and the timing of credential availability are unchanged.
- [x] 9.5 Map VM-domain job/provider states to the shared fulfillment lifecycle invariant without leaking raw VM job status cross-domain. **Already satisfied:** the storefront reads only the kit's `SettlementRecordState`, never `AnsibleJob.status`, and escrow status stays generic.
- [x] 9.6 Remove `create_vm_and_wait_with_credentials` and ordinary storefront polling/direct executor dispatch after all callers are migrated; tombstone deleted paths where repository workflow requires it. **Done:** `provisioning_orchestration_service.py` and its test file had no other callers and were tombstoned; the one lease-registration test still in use moved to `test_fulfillment_service.py`, which passed with `alkahest_py` stubbed.
- [x] 9.7 Add storefront restart, duplicate result, site-routing, negotiation-resume, and end-to-end credential-delivery tests. **Done.**

  **Correction (external review):** the restart and negotiation-resume claim overstated the evidence: identifier round-trips and cold-cache fan-out are prerequisites for recovery, not recovery, which 9.9–9.18 built. Standing evidence: site routing, `test_aggregate_fulfillment_client.py`; duplicate result and credential delivery through the real `_do_provision`, `test_fulfillment_service.py`'s `test_do_provision_end_to_end_delivers_credentials_for_storage` and `test_do_provision_result_fetch_is_safe_to_repeat` (design.md, "Rationale moved from task notes at closeout", 9.7).
- [x] 9.8 Promote Section 9's accepted decisions into permanent documentation and complete this section's design-promotion record, per the destinations identified during planning: **Done.**
  - [x] 9.8.1 `openspec/specs/fulfillment/spec.md`: document `POST /fulfillment/schedule`'s HTTP contract (9.0.1) alongside the existing validate/begin/status/result requirement prose. **Done:** `openspec/specs/fulfillment/spec.md#requirement-scheduling-and-assignment`.
  - [x] 9.8.2 `openspec/specs/compute-provisioning-contract/spec.md`: add requirement(s) for the new client-side fulfillment scheduling/acceptance surface (9.0.2/9.0.3), alongside "Versioned executor action submission" and "Allocation-backed lease control." **Done:** `openspec/specs/compute-provisioning-contract/spec.md#requirement-fulfillment-scheduling-and-acceptance`.
  - [x] 9.8.3 `docs/development/ARCHITECTURE.md`: add `fulfillment_id`/`fulfillment_uid` to "Shared vocabulary and identities" (9.0.6). **Done in 9.0.6, confirmed still correct.**
  - [x] 9.8.4 Add design-promotion record entries (table at the end of `design.md`) for: the `/fulfillment/schedule` endpoint, the moved/added client contracts, the sibling aggregator and shared routing-cache decision (recorded as a code-docstring destination, not a new spec — see 9.0.5), and the `fulfillment_id`/`fulfillment_uid` vocabulary entries. **Done:** design.md's "Section 9 completed design-promotion record" and "Section 9 implementation confirmation".
  - [x] 9.8.5 Remove change-document/task-number references from any Section 9 production code comments before considering the section implemented, per `AGENTS.md`'s comment rules. **Done** for `POOLS-7`/`pools-7`; review then found other change-document references this sweep missed, since fixed (design.md, "Section 9 reconciled status").


### Section 9 recovery completion plan

The completed 9.0–9.8 tasks above remain implementation history. The following tasks close the recovery capability that their original restart language assumed but did not implement.

- [x] 9.9 Define and persist the versioned VM storefront fulfillment-context envelope before the first recoverable external mutation. Include the exact normalized `FulfillmentRequestBody.fulfillment_request`, generated `vm_target`, accepted listing/order references, lease timing inputs, required SSH/connectivity inputs, and a bounded chain-scan origin. Do not persist response credentials in this envelope. Add fresh-schema migration, existing-schema migration, round-trip, unsupported-kind/version, redaction, and partial-update tests. **Permanent documentation:** the VM storefront/adapter-scoped specification for envelope ownership and recovery semantics; `openspec/specs/fulfillment/spec.md` only for any generic envelope invariant not already present.

- [x] 9.10 Refactor the existing storefront VM settlement sequence into shared, replay-safe convergence operations used by both the foreground settlement task and recovery worker. Preserve the current blocking foreground behavior. Pass `escrow_uid` explicitly into `_do_provision` and remove `deal_ref` from the durable fulfillment seam. Leave `vm_host` unchanged and record its cleanup under Section 10. Keep post-acceptance persistence failures bounded, loudly logged, and nonfatal to an otherwise deliverable VM. **Permanent documentation:** VM storefront/adapter-scoped fulfillment and recovery requirements; current production docstrings describe only present intent and stable invariants.

- [x] 9.11 Add durable, cross-process escrow convergence coordination. Inventory existing compare-and-set or worker-claim primitives first; reuse one when it provides expiry and restart recovery, otherwise add a renewable escrow processing lease with owner and expiry fields. Prove that foreground execution and the background sweep cannot concurrently perform the same non-idempotent phase, that an expired claim is recoverable, and that one blocked escrow does not prevent progress for others. Do not use a process-local lock as the correctness boundary. **Permanent documentation:** VM storefront/adapter-scoped worker/concurrency requirement; `docs/development/ARCHITECTURE.md` only if this establishes a repository-wide worker-coordination rule.

- [x] 9.12 Implement the dedicated storefront fulfillment-convergence runtime and register it through `start_storefront_background_task`. The loop owns its own `SQLiteClient`, scans bounded batches of every nonterminal primary VM escrow (including rows with no persisted reservation/fulfillment identity), claims work durably, and invokes one independently testable convergence pass per escrow. Keep it separate from `claims_engine_loop` and `negotiation_watchdog_loop`. Add startup-registration, cancellation, per-row isolation, sweep-bounding, and restart tests. **Permanent documentation:** VM storefront/adapter-scoped startup-worker and lifecycle ownership requirements.

- [x] 9.13 Reconcile physical fulfillment from the earliest safe boundary. Recover or create the escrow-idempotent capacity reservation; equivalently schedule the resource; equivalently begin fulfillment from the persisted exact request; skip schedule/begin when `fulfillment_id` is already known; poll nonterminal state without failure; fetch active results; and apply the existing terminal failure policy. Persist recovered IDs/checkpoints with bounded retry without abandoning live delivery solely because storefront-local persistence failed. Add crash-window tests before/after reserve, schedule, begin, fulfillment-ID persistence, status polling, and result retrieval, using fresh service/client composition rather than reusing process-local caches. **Permanent documentation:** VM storefront/adapter-scoped convergence state machine; existing site-capacity and fulfillment specs remain authoritative for reserve/schedule/begin idempotency.

- [x] 9.14 Extract and converge all required post-physical settlement effects through the shared state machine: capacity lease refresh/commit behavior still required before Section 10, credential storage, provisioning-service lease registration still required by the legacy teardown compatibility path, shutdown scheduling as best effort, on-chain fulfillment, listing update, durable `fulfillment_uid`, escrow readiness, and settlement-claim creation. Define which persisted fields or authoritative queries prove each phase complete. Add recovery tests after each external side effect, duplicate-result tests, credential non-duplication tests, and a test proving `ready` is not written before required commercial settlement effects complete. **Permanent documentation:** VM storefront/adapter-scoped full-convergence requirement; settlement/claims permanent specs for any cross-subsystem invariant changed.

- [x] 9.15 Make ambiguous on-chain compute-fulfillment outcomes duplicate-safe without blocking POOLS-7 on an external Alkahest release. The VM settlement adapter adopts a matching attestation when the installed client exposes a supported query surface. When no such surface exists, recovery records the submission-intent checkpoint, refuses blind resubmission, leaves the escrow pending, and logs an operator-visible reconciliation condition. Investigation of `alkahest-py==1.1.2` confirmed that its compiled extension contains log-scanning internals but exposes neither the provider nor a bounded `refUID` query. Repository-owned raw RPC/EAS scanning was therefore not added because it would require unstable assumptions about external ABIs, deployment addresses, and network behavior. A supported generic query API is deferred to `alkahest-py` or `kit/alkahest`. Tests cover matching-attestation adoption and refusal to resubmit without a query surface. **Permanent documentation:** `openspec/specs/vm-storefront-fulfillment/spec.md#requirement-ambiguous-on-chain-submission-safety`.

- [x] 9.16 Preserve aggregate routing parity while validating recovery use. Reuse `AggregateCapacityClient`/`AggregateFulfillmentClient` cold-cache fan-out in the recovery worker and keep the existing broad exception fallback policy unchanged for both siblings. Add recovery tests proving a fresh aggregate composition locates the owning site. Record typed error classification as deferred aggregation-wide work rather than changing only the fulfillment sibling. **Permanent documentation:** VM storefront/adapter-scoped aggregate routing requirement.

- [x] 9.17 Reconcile Section 9 documentation and promotion records. Create or expand the broader VM storefront/adapter-scoped permanent specification rather than a recovery-only spec; promote the delivery-over-bookkeeping priority, versioned context, worker ownership, full convergence, chain reconciliation, and routing behavior. Update `proposal.md`, `design.md`, and this task list to one consistent current status. Replace the earlier code-docstring-only promotion destinations for material storefront persistence/routing/recovery decisions. Preserve implementation history but remove contradictory completion claims. Perform a broad production-reference sweep for `openspec/changes`, active change names, task/section numbering, migration commentary, and tombstone references. **Permanent documentation:** exact headings recorded in the Section 9 design-promotion table after implementation.

- [x] 9.18 Complete the Section 9 validation gate before beginning Section 10. Wheelhouse validation passed the focused recovery set (43 tests), `core/storefront` (67 tests), and the VM storefront suite available in the review environment (770 passed, 1 skipped). The repository owner then ran root `make test` successfully, including VM storefront unit tests (627 passed, 1 skipped), VM storefront integration tests (145 passed), both Alkahest integration tests, and all other repository suites. The OpenSpec CLI is absent from both validation environments; strict validation is explicitly waived for this section rather than recorded as a repository failure. Final artifacts contain only updated files in repository structure. Section 10 may begin. **Permanent documentation:** this validation record and the completed Section 9 promotion record in `design.md`.

**Deferred follow-up:** moving ordinary VM fulfillment to an explicitly asynchronous initiate/converge product model requires a new OpenSpec change after POOLS-7. It is not part of Section 9, 10, or 11. Typed site-fallback error classification is likewise deferred as an aggregation-wide correction affecting both aggregate clients.

### Section 9 post-completion correction (after external code review)

Task 9.18's validation gate was declared satisfied on a green suite that, on external review, was found not to exercise the composed seam these two corrections fix. Recorded here as their own tasks, not folded into 9.9–9.18's history, since the completion record for those tasks stands as originally written and this correction is what actually closes the gate.

- [x] 9.19 Fix `vm_target` ownership: `fulfill_vm_obligation` generates it once and must be the single source of truth from generation through persistence, physical fulfillment, and lease registration. **Done:** `_build_vm_fulfillment_context` returned an unassigned local `vm_target` that the caller unpacked over the generated value, replacing it with `None` on every call; `vm_target` became a required parameter and left the return tuple. (Provisioning now names the guest, and this requirement was removed by `bare-metal-mock-provisioned-deal`.)
- [x] 9.20 Add regression coverage that exercises the real, composed seam this bug lived in, not a mocked-over version of it. **Done:** `test_generated_vm_target_survives_context_fulfillment_and_lease_registration` drives the real `fulfill_vm_obligation`; it failed before 9.19 and passes after. 9.18's suite missed the bug because every test at that seam either passed `vm_target` as a literal or mocked the callee without validating arguments.
- [x] 9.21 Replace `find_compute_fulfillments`'s speculative Alkahest method probing (`find_obligations_by_ref`/`get_obligations_by_ref`/`find_attestations_by_ref`) with an explicit, injectable query capability, since none of those three names exist anywhere in `kit/alkahest`'s actual client interface (confirmed by repository-wide search — only `get_obligation(client, uid)`, a lookup by already-known uid, exists; nothing resembling a search-by-reference query). **Done:** an explicit `query_fulfillments` parameter; production passes none, so the safe-pending fallback triggers on a missing capability rather than on guessed names.
- [x] 9.22 Update `test_fulfillment_reconciliation.py` to match the new explicit-capability design rather than a hand-constructed mock exposing one of the removed guessed method names. **Done:** the adoption test injects the query; the fallback test was already correct.
- [x] 9.23 File the upstream capability this repository cannot supply on its own as its own OpenSpec change, rather than leaving the gap implicit. **Done:** `openspec/changes/add-alkahest-attestation-reference-query/proposal.md` — scopes the missing capability (a bounded, reference-UID-based attestation query) as owned by `alkahest-py`/`kit/alkahest`, not by this repository, with the concrete downstream integration work that becomes possible once it exists.
- [x] 9.24 Give every requirement in `openspec/specs/vm-storefront-fulfillment/spec.md` at least one `#### Scenario:`, matching every other spec in this repository (`fulfillment`, `physical-provisioning`, `site-capacity`, `compute-provisioning-contract` all pair every requirement with scenarios; this new spec, as first written, had none). **Done** for all seven requirements.

**Validation:** the five touched storefront test modules passed; the owner's root `make test` (9.18) remained the baseline, and strict validation stayed waived until 8.15 ran it.

### Section 9 implementation history

Tasks 9.9–9.18 were implemented across several passes (initial recovery envelope/worker plumbing, pre-acceptance replay, post-physical convergence, then a wheelhouse-validated run fixing one phase-ordering defect: an escrow with an already-durable `fulfillment_id` no longer re-runs resource scheduling or requires the pre-acceptance envelope). Each intermediate pass's own progress notes are superseded by 9.18's completion record above and are not reproduced here. Tasks 9.19–9.24 (the post-completion correction) are similarly complete as recorded in their own entries above, not repeated here.


## 10. Cut over teardown and physical-resource reclamation

### Section 10 planning note

The task list below supersedes the original 10.1–10.6 drafting after design review (`design.md`, "Section 10 design review"). The original items assumed `VmReleaseExecutor`/`LeaseLifecycleService` would be removed from VM's release path and that capacity release needed a new home. Repository inspection during review found the durable teardown state machine and `FulfillmentConvergenceWatchdog`'s dispatch/converge passes already implemented and already running with no caller, and established that `LeaseLifecycleService` should remain the sole trigger and capacity-release owner for both VM and bare-metal, with the fulfillment aggregate entered only as the seam `VmReleaseExecutor` and a small `ReleaseJobPort` routing layer cross. Items are renumbered here; none of the original items had been started (all were `[ ]`), so this is a plan amendment, not a correction of completed work.

- [x] 10.1 Add `begin_fulfillment_teardown(fulfillment_id)` to `FulfillmentOrchestrator` as the whole-fulfillment teardown entrypoint: resolve the aggregate by `fulfillment_id`, reject unless `active`, reuse an already-prepared `prepared_teardown_operation`/`teardown_provider_metadata` when present (backfilled rows — idempotent, no re-preparation) or call `provider.prepare_teardown` and persist it when absent (native rows reaching teardown for the first time), then transition `active → teardown_dispatch_pending`. No inline provider dispatch — `FulfillmentConvergenceWatchdog.dispatch_pending_teardowns`/`converge_teardowns` (already implemented) own dispatch and convergence from there. Keep `provisioned_resource_id` in the schema as-is; no schema change is needed for this task (it already exists as `ProvisionedResource.provisioned_resource_id`, a future per-resource teardown extension point). **Done:** `FulfillmentOrchestrator.begin_fulfillment_teardown` and the transaction's `begin_teardown`; `test_fulfillment.py`, `test_fulfillment_persistence.py`.
- [x] 10.2 Expose `begin_fulfillment_teardown` through the compute provisioning service's fulfillment controller/client, and confirm backfilled rows (`legacy_backfill.py` output) and native rows resolve through the same lookup with no special-casing beyond 10.1's already-prepared check. **Done:** `POST /fulfillment/{fulfillment_id}/begin-teardown`, with `begin`'s response shape and error mapping; backfilled and native rows share the lookup. The client method, first deferred, was added by 10.11.
- [x] 10.3 Add a kind-routed `ReleaseJobPort` (mirroring the existing `ExecutorReleaseDispatcher` submission-side pattern) so `LeaseLifecycleService._process_releasing_reservation`'s `get_job(job_id)` call routes by the reservation's `offering_mode`: bare-metal keeps resolving through the existing shared `job_service`/`AsyncJobQueue`, unchanged; VM resolves by reading the `SettlementRecord` teardown state for the given `fulfillment_id` (`torn_down` → succeeded, `teardown_failed` → failed, otherwise pending) via `FulfillmentOrchestrator.get_fulfillment_status` or the settlement repository directly. **Done:** `ReleaseJobPort`/`ReleaseJobDispatcher` in `compute_provisioning/release.py`, routed by `offering_mode`. Wiring it in exposed and fixed a `"direct-release"` sentinel regression (design.md, "Rationale moved from task notes at closeout", 10.3). (`bare-metal-mock-provisioned-deal` later replaced per-mode release with one provider-neutral executor.)
- [x] 10.4 Replace `VmReleaseExecutor.submit_release`'s direct Ansible `vm_remove` job submission with: resolve `fulfillment_id` for the reservation's `capacity_reservation_id`, call `begin_fulfillment_teardown(fulfillment_id)`, return `fulfillment_id` as the job id consumed by 10.3's dispatcher. `LeaseLifecycleService`, `LeaseWatchdog`, `_finish_release`, and the admin recovery endpoints (`retry_release`, `force_release`, `release_oversight`) are unchanged — this task touches only the submission leaf, not the trigger, polling loop, or capacity-release call site. **Done:** `VmReleaseExecutor` and `VmFulfillmentReleaseJobPort` in `vm_provisioning_adapter/release.py`. The circular dependency (`FulfillmentOrchestrator` → provider registry → the VM adapter bundle) was first broken with a lazy module-global accessor, which 10.9 replaced with a composition-bound port (design.md, "Section 10 completed design-promotion record" and "Rationale moved from task notes at closeout", 10.4). `test_ledger_lease_lifecycle.py`'s VM tests were rewritten for the new mechanism; the suites passed.
- [x] 10.5 Do not return physical capacity to scheduling until teardown succeeds or an explicit operator recovery action resolves the resource. This is already true today (`_finish_release` only runs after confirmed job completion) and remains true once 10.3/10.4 land, since `_finish_release` is unchanged and 10.3's VM route only reports `succeeded` once `SettlementRecord.state == torn_down`. Add a regression test asserting capacity is not released while the aggregate is `teardown_dispatch_pending`/`tearing_down`/`teardown_failed`. **Done:** `test_ledger_lease_lifecycle.py`'s `test_releasing_reservation_past_grace_marks_release_failed`, `test_releasing_reservation_within_grace_skips`, `test_failed_vm_remove_marks_release_failed_without_notification` (capacity held while tearing down or failed), and `test_expired_ledger_lease_releases_locally_and_notifies` (released only at `torn_down`).
- [x] 10.6 No buyer-initiated early-termination business flow exists yet in the VM storefront (confirmed — this is bottom-up infrastructure work, not wiring an existing flow). Scope is limited to exposing the capability for that future flow to use. **Done:** `terminate_vm_lease` in `fulfillment_service.py`, through `ComputeProvisioningClient.terminate_lease` (design.md, "Rationale moved from task notes at closeout", 10.6). No new endpoint and no invented caller.
- [x] 10.7 `_register_vm_lease_with_settings` stops passing `executor_ref` to `register_lease`. **Corrected during implementation:** this path never sent `executor_ref`, so nothing was removed; `executor_target` stays (design.md, "Rationale moved from task notes at closeout", 10.7). The test that showed it, `test_contract_register_lease_never_sends_executor_ref_and_it_self_heals`, also exposed a pre-existing defect, fixed with the owner's agreement: the contract lease view did not translate `"leased"`, so every real `register_lease` call failed validation (design.md, "Addendum: pre-existing `LeaseState` serialization bug"). `test_contract_lease_view_serializes_every_reachable_reservation_state` covers it.
- [x] 10.8 Add idempotent repeated teardown, partial failure, restart, lost submission acknowledgement, backfilled VM, kind-routed `ReleaseJobPort` (both VM and bare-metal routes), `terminate_lease`-triggered teardown, and final capacity-release tests. **Done.** Repeated, partial-failure, and backfilled teardown: `test_fulfillment.py`. Capacity gating: 10.5. Dispatcher routing: `provisioning/compute/tests/unit/test_release.py`. Termination: `test_provisioning_client_endpoint_coverage.py::test_terminate_lease_uses_client_contract`. Teardown restart and worker death, which were missing: `test_fresh_watchdog_resumes_a_teardown_from_durable_state_after_restart` and `test_worker_death_leaves_a_reclaimable_teardown_row_not_a_stuck_one` (design.md, "Rationale moved from task notes at closeout", 10.8).

### Section 10 post-implementation correction tasks

The completed 10.1–10.8 entries above are preserved as implementation history.
The following tasks supersede the earlier Section 10 completion statement and
must close before Section 11 begins.

- [x] 10.9 Replace the module-global/lazy `resolved_fulfillment_service` bridge with a narrow fulfillment-teardown port supplied by the composition root. The VM release adapter must not depend on application-global initialization order or on the complete `FulfillmentOrchestrator`. Remove the superseded production comments and promotion-record claim that the service locator is an accepted composition technique. **Permanent documentation:** `openspec/specs/physical-provisioning/spec.md` for the release/teardown boundary; `docs/development/ARCHITECTURE.md` only if the repository-wide composition/dependency map requires clarification.
- [x] 10.10 Preserve release-submission failure taxonomy. Translate only enumerated domain outcomes in `VmReleaseExecutor`; allow unexpected composition, persistence, and programming failures to propagate to `LeaseLifecycleService`'s existing `release_submit_error` handling. Add tests for missing aggregate, invalid aggregate state, unavailable teardown port, and unexpected repository failure, asserting distinct persisted diagnostics where the contract distinguishes them. **Permanent documentation:** `openspec/specs/physical-provisioning/spec.md` for observable failure/recovery behavior; implementation-specific exception classes remain in code.
- [x] 10.11 Add `begin_fulfillment_teardown(fulfillment_id)` to `ComputeProvisioningClientProtocol` and `ComputeProvisioningClient`. Add an integration test that creates or resolves an active fulfillment aggregate and invokes `POST /fulfillment/{fulfillment_id}/begin-teardown` through the client, including idempotent repeated invocation and HTTP error mapping for unknown/conflicting aggregates. Reopen task 10.2 until this is complete. **Permanent documentation:** `openspec/specs/fulfillment/spec.md` HTTP/client contract section.
- [x] 10.12 Decide and implement one authoritative reservation-state-to-lease-state projection. Preferred direction: a pure helper or shared mapping in the `compute_provisioning` contract package consumed by both `compute_contract_controller` and the VM `leases_controller`; confirm the package boundary before implementation. Remove the knowingly duplicated controller tables and update the e2e `DealLease` helper so it does not maintain a third partial mapping. Add a test proving every reachable `ReservationState` has one valid `LeaseState` projection across both API surfaces. **Permanent documentation:** update `openspec/specs/compute-provisioning-contract/spec.md` only if it documents lease-state vocabulary; otherwise the enum/helper is the authoritative code contract and no new prose requirement is needed.
- [x] 10.13 Add the permanent invariant separating lease-release retry ownership from fulfillment-teardown retry ownership: lease lifecycle owns `releasing`/`released` and final capacity return; fulfillment convergence owns dispatch/requeue/recovery of teardown states; lease retry re-observes the same fulfillment aggregate and never creates a second teardown operation. Include scenarios for `teardown_failed`, convergence requeue, operator lease retry, and capacity remaining held until `torn_down`. **Permanent documentation:** `openspec/specs/physical-provisioning/spec.md`, cross-referencing `openspec/specs/fulfillment/spec.md` teardown convergence.
- [x] 10.14 Rewrite the VM full-deal e2e teardown phases to the current storefront/provisioning relationship. Remove assumptions that the lease-facing release id is an Ansible job id, stop calling `SyncProvisioningClient.get_job()`/`wait_for_job()` with a `fulfillment_id`, and assert the composed durable path: lease expiration or termination → reservation `releasing` → fulfillment `teardown_dispatch_pending`/`tearing_down` with capacity held → provider completion → fulfillment `torn_down` → lease `released` and capacity available. Inventory existing mock/admin controls first; if none can deterministically pause and step fulfillment convergence, add a mock-profile test control rather than relying on background timing. Update all stale stage names, comments, and docstrings that describe Section 10 as a future direct `vm_destroy` change. **Permanent documentation:** no e2e implementation detail belongs in permanent specs; the durable state/capacity invariants map to physical-provisioning and fulfillment specs. **Done:** stages 10a–11b of `test_full_deal.py` and `test_full_deal_buyer_cli.py` already implemented this sequence, hidden behind a failing stage 08b that `refactor-e2e-fulfillment-lifecycle` fixed. E2E run 38741626285 on `dev` passed stages 08b–11b (2026-10-15). The owner had deferred this task to after Section 11; that deferral is superseded (design.md, "Rationale moved from task notes at closeout", 10.14).
- [x] 10.15 Add a migration-produced backfill integration path: create representative pre-POOLS VM lease/settlement data, run the actual legacy backfill/migration entrypoint, initiate teardown through the public client, converge provider teardown, and prove final lease/capacity release. Do not substitute a hand-constructed row for this test. **Permanent documentation:** migration behavior remains in the active change; only resulting current-state backfilled/native equivalence belongs in `openspec/specs/fulfillment/spec.md`. **Done:** `test_legacy_backfill_teardown.py` runs the real backfill entrypoint on a seeded pre-cutover lease, then teardown and two lease cycles to `released` with capacity returned (convergence simulated; the watchdog has its own suite).
- [x] 10.16 Rebuild the Section 10 design-promotion record after 10.9–10.15. Map the fulfillment-id-as-release-tracking-id seam, kind-routed status lookup, two-state-machine retry invariant, client contract, capacity-hold rule, and backfilled/native equivalence to exact permanent headings. Remove superseded rows and mark Section 10 complete only after focused suites, ~~the rewritten full-deal e2e path~~ (deferred per 10.14's note above), root `make test`, and available strict OpenSpec validation pass. Section 11 remains blocked until this gate is complete. **Done:** design.md's "Section 10 rebuilt design-promotion record". The e2e path is 10.14's.

**Correction (Section 10 verification):** 10.9–10.13 were first marked done without running the suite. A working environment then found three did not meet their own criteria, each completed:

- **10.10** had none of its four failure-taxonomy tests; they were added to `test_ledger_lease_lifecycle.py`. The bare-propagation design needed no change, since the persisted `failure_message` already distinguishes the cases.
- **10.11**'s only test monkeypatched the orchestrator; it now drives a real aggregate through the app, with the 404 and 409 cases.
- **10.12** left `compute_contract_controller.py` on its own dead `_LEASE_STATUS` dict beside the shared projection it imported; the dict is gone.

10.13 was accurate as written, and cross-referenced with the overlapping "Site-backed release lifecycle" paragraph. The provisioning suites passed together at the end.

**Section 10 complete.**

## 11. Remove obsolete schema and compatibility paths

### Section 11 planning note (2026-07-30)

The task list below supersedes the original 11.1–11.6 drafting after the
discuss-phase review recorded in `design.md`'s "Section 11 design review."
That review found several of the original items already satisfied by
Sections 2–10 and a concurrent change, found one item unsafe to execute as
written, resolved one item's scope by explicit decision, redesigned one
item against vocabulary that didn't exist when it was first drafted, and
resolved the one item added since (`vm_host`) into a concrete plan. None of
the original items had been started (all were `[ ]`), so this is a plan
amendment, not a correction of completed work. 11.2's and 11.6's numbers are
kept; 11.1 is split into its three actually-distinct components rather than
treated as one removal task, since the discuss phase found each component
resolves differently (two already done, one dropped, one explicitly
retained). 11.6 is expanded into concrete subtasks matching its now-decided
design.

- [x] 11.1 Close out `allocation_id`/`SiteAllocation`, direct-host storefront
      placement, process-local settlement maps/locks, `deal_ref`, and
      `register_resource` — three different outcomes, not one removal:
  - (a) **Confirm, don't remove:** re-verify at implementation time that
    `allocation_id`/`SiteAllocation` have no remaining production
    references outside the historical rename migrations and the unrelated
    `compute_allocations` table (`design.md` item 1), and that direct-host
    storefront placement and process-local settlement maps/locks have no
    remaining call sites, without touching
    `vm_provisioning_adapter/controllers/vms_controller.py` (a permanent,
    unrelated admin API — `design.md` item 2). If inspection finds
    anything new, fix it here; do not assume the discuss-phase pass is
    still accurate without re-checking.
  - (b) **Drop `deal_ref` removal from scope entirely** (`design.md` item
    4, accepted 2026-07-30): no code change. `ExecutorActionEnvelope`/
    `JobAccepted`/`ProvisioningJob`/`LeaseRegistration`/`LeaseView`/
    `LifecycleEvent`/`AnsibleJob.deal_ref` all stay. Do not remove any of
    them under this task.
  - (c) **Exclude `register_resource` from removal** (`design.md` item 5):
    no code change. `kit/site`'s `PUT /capacity/resources/{resource_id}`
    and `CapacityLedgerService.register_resource` stay — `apicredits_storefront/startup.py`'s
    `_register_seed_quota` is a live, load-bearing caller. Do not remove
    this endpoint under this task or describe it as obsolete in any
    permanent documentation this change writes.
  - **Permanent documentation:** none. All three outcomes restore or
    confirm already-documented intent; nothing here is new normative
    behavior.
  - **Done (2026-07-30):** re-verified all three at implementation time,
    after 11.2/11.4/11.6's code changes had already landed, not before —
    (a) confirmed zero remaining `SiteAllocation`/stray `allocation_id`
    references, zero direct-dispatch call sites, `vms_controller.py`
    untouched; (b) confirmed `deal_ref` still present on all five contract
    classes, no removal attempted; (c) confirmed `register_resource` and
    `apicredits_storefront`'s live call to it are both still present and
    unchanged. No code changes were needed for any of the three.
- [x] 11.2 Fix `most_available`'s claim-blindness bug using the corrected
      design in `design.md` item 3 — **not** the stale 2026-07-17 sketch
      referenced by this task's original text, which predates the actual
      `pool_id`/`resource_id`/`dimensions` claim shape and the
      multidimensional `available`/`capacity` row shape and would not work
      if implemented as originally written. Concretely, in
      `core/storefront/src/core_storefront/aggregation.py`:
  - Rewrite `_resource_matches_claim(row, claim)` to check `pool_id`/
    `resource_id` pins by equality and a `dimensions` map by per-dimension
    sufficiency against `row["available"]`, falling back to comparing
    `row["available_units"]` against a legacy `units`/`gpu_count` claim
    when `dimensions` is absent (the shape `apicredits` still sends).
  - Thread `claim` through `_site_available_units` (it's already received
    by `most_available` — only the inner helper is claim-blind today) so
    the sum only counts rows the claim could actually be served from.
  - Do not restructure `fill_first`/`most_available` beyond this, and do
    not resolve the separate, already-flagged "Site fallback after
    POOLS-4" question — out of this task's scope per `design.md`.
  - **Tests:** a claim scoped by `pool_id`, one scoped by `resource_id`, a
    multidimensional claim where only some candidate rows have sufficient
    `available` in every requested dimension, the legacy single-quantity
    claim shape, and a regression test pinning the original bug (a claim
    that should exclude a high-`available_units`-but-wrong-pool row from
    ranking).
  - **Permanent documentation:** none beyond the fix itself and an in-code
    comment pointing at this task and `design.md` item 3 — this restores
    the behavior the 2026-07-17 section already documented as intended,
    it isn't new normative behavior.
  - **Done.** `_resource_matches_claim` implemented as designed and
    later renamed `_coarse_resource_matches_claim` (see the 2026-07-30
    update below); `test_aggregation.py` covers pool/resource/dimension/
    legacy-unit matching and the original claim-blindness regression.
  - **Update (2026-07-30, code review): extended, not replaced.** Review
    found the coarse matcher still ignores categorical claim attributes
    (`region`, `gpu_model`) that VM claims already emit and site admission
    already checks — not an incorrect-admission risk, but avoidable
    failed probe/reserve attempts. Resolved via dependency injection
    rather than moving matching logic into `core`; see `design.md`'s
    "Task 11.2 alternatives" for why the other two options were rejected.
    Final behavior: `core/storefront/aggregation.py` exposes a
    `ClaimMatcher` type and takes an injectable matcher (default
    `_coarse_resource_matches_claim`, documented as intentionally
    partial); `kit/site` exposes `dict_resource_satisfies_claim`, a thin
    adapter delegating to its own existing pure parsing/matching
    functions and requiring `unit_claim_keys` explicitly (VM's ledger is
    composed with `("units", "gpu_count")`, not the module default);
    `capacity_client.py` injects it specifically when placement is
    `most_available`; `vm_job_spec_service.py` adds
    `resource_type="compute.gpu"` to every claim, verified to match what
    `ComputeGpuResourceAdapter` actually registers. Fixed a test-double
    gap this exposed: `fake_site.py`'s `FakeSite` didn't understand
    `resource_type` as a special claim key.
    Validation: `test_dict_resource_satisfies_claim.py` sweeps the
    matcher against the authoritative admission path; the touched suites
    passed except two Alkahest integration cases needing a toolchain the
    environment lacked.
  - **Permanent documentation:** none — the injected-matcher design is
    implementation technique, not new externally-observable behavior;
    recorded as in-code docstrings on `ClaimMatcher`/
    `dict_resource_satisfies_claim`.
- [x] 11.3 Confirm the composition/wheel/reinit/Docker/deployment wiring for
      `kit/fulfillment` found already satisfied in `design.md` item 8 —
      `kit/Makefile`'s `dist`/`test` targets, both consumers' `reinit`
      targets, the Dockerfile's transitive wheel install, the in-process
      `FulfillmentConvergenceWatchdog` composition and its config-gated
      defaults, and the Helm deployment's `Recreate`/PVC topology — still
      holds at implementation time. No new work is expected; this was
      inspected, not executed against a live build, so treat this as a
      verification pass and fix anything inspection missed rather than
      skip it as already proven. The CI-matrix gap flagged by
      `fix-vm-fulfillment-capacity-boundary`'s own design.md (missing
      packages, staging-only trigger) is explicitly not this task's scope —
      leave it where that change left it.
  - **Permanent documentation:** none expected; confirmation of existing
    composition, not new behavior.
  - **Done (2026-07-30):** re-verified all five sub-claims after 11.6's
    schema/migration changes landed — `kit/Makefile`'s dist/test chains,
    both consumers' `reinit` targets, the watchdog's in-process
    composition and config-gated defaults, and the Helm deployment's
    `Recreate` strategy all still hold, unaffected by the `vm_host`
    migration (a schema-internal change with no composition/deployment
    surface). No code changes were needed.
- [x] 11.4 Fix the confirmed credential-leak gap found in `design.md` item 10
      rather than the generic audit this task originally described — the
      application-level HTTP/log surfaces were checked and are already
      clean (admin-key middleware, `CredentialFetchFailedError`'s HTTP
      mapping, `job.logs`' three persistence sites, `_extract_and_store_credentials`'s
      sanitization); the real gap is at the Ansible execution layer:
  - [x] 11.4.1 Add `no_log: true` to `vm-create.yml`'s two password-generating
    `set_fact` tasks (`tenant_password`, `root_password`), matching the
    pattern `vm-reset-password.yml`'s equivalent tasks already use.
    **Done, expanded to six tasks total** on discovering three more
    unprotected credential-bearing tasks in the same file: a third
    `root_password` `set_fact` (golden-image path), the SSH `shell` task
    embedding `{{ tenant_password }}` directly in its command line, and
    both `vm_creation_data:` tasks building the full `authentication`
    block. The two "Display VM creation result" `debug: msg:` tasks had
    their inline password interpolation replaced with a pointer to the
    credentials API instead of blanket `no_log`.
  - [x] 11.4.2 Route `ansible_service.py`'s per-line debug logging through
    `job_service.py`'s existing `_redact_logs` scrubber. **Done**; the
    scrubber was centralized into a new shared `redact_ansible_output()`
    in `ansible_service.py`, with `job_service.py`'s `_redact_logs`
    delegating to it. Also found and fixed: the regex only matched
    unescaped `"password": "..."`; Ansible can render a `debug: msg:`'d
    JSON string backslash-escaped depending on `stdout_callback`/
    `callback_result_format` — strengthened to match both forms.
    `json-output.yml`'s own `debug:` tasks are the literal transport
    `_extract_ansible_json` parses and deliberately do **not** get
    `no_log` (confirmed reading `_extract_ansible_json`: doing so would
    break credential/result delivery entirely) — that data reaches the
    same two protected consumers by other paths.
  - [x] 11.4.3 Change `vm_fulfillment_service.py`'s order-logging call to
    log an explicit allowlist instead of the whole object. **Done** —
    logs `type(order).__name__` and sorted top-level key names only,
    never values.
  - [x] 11.4.4 **Tests.** New/strengthened coverage across
    `test_job_service.py` (`TestRedactLogs`, +2 cases),
    `test_ansible_service.py` (`TestRedactAnsibleOutput` +
    `TestStreamingDebugLoggingIsRedacted`, 6 cases — one drives
    `wait_for_playbook` against a real subprocess since `select.select()`
    needs genuine file descriptors), and
    `test_vm_management_contracts.py` (+2 cases, including an explicit
    pin that `json-output.yml`'s transport tasks must **not** carry
    `no_log`). All passed.
  - **Permanent documentation:** none — restores the "credentials must
    not leak into logs" posture the codebase already partially implements
    (Section 8's principle, `openspec/specs/fulfillment/spec.md`); not
    new normative behavior. The shared `redact_ansible_output` location
    and the `json-output.yml` exception are recorded as in-code
    docstrings.
- [x] 11.5 Run the suite inventory recorded in `design.md` item 9:
  - Root `make test` (chains through `test-core`, `test-kits` — includes
    `kit/fulfillment` — `test-provisioning`, `test-provisioning-iac`,
    `test-registry`, `test-storefront`, `test-vms-buyer`,
    `test-apicredits`/`test-apicredits-middleware`).
  - `e2e-tests`' own suite via its own `Makefile`/`reinit` — confirmed
    genuinely decoupled from `compute_provisioning`/`kit/fulfillment`
    (it wraps the provisioning HTTP surface with its own
    `e2e-tests/src/e2e_harness/provisioning_test_client.py`, not
    `ComputeProvisioningClient`), so no reinit change is needed there.
  - A fresh-database migration pass per touched service (no single
    repository-wide "run all migrations" target exists) plus the existing
    per-section migration test coverage (Sections 2, 3, 7 in particular).
  - The typing checks that exist today (`core`, `core/registry`,
    `core/registry-client`'s `mypy` targets) — **run what exists; do not
    add `mypy` configuration to `kit/fulfillment`, `kit/site`,
    `kit/resource-pools`, `provisioning/compute`(`/service`), or any
    touched `domains/*` package as part of this task.** None of them have
    typing checks configured today, and adding them is materially larger,
    unscoped work `design.md` item 9 deliberately did not fold into this
    task. Disclose this gap in the delivery summary rather than silently
    treating "typing" as satisfied.
  - `openspec validate --all --strict` — disclose as unavailable if it
    still is, consistent with every validation pass since Section 8;
    don't silently re-attempt it as if this were new information.
  - Fix any renamed-contract consumers the suite run surfaces. Static
    search during the discuss phase found no remaining `.select_resource(`
    or direct `provider.create(`/`provider.teardown(` call sites, but that
    is not a substitute for actually running the suites in an environment
    with every internal wheel installed.
  - **Permanent documentation:** none from the run itself; any behavioral
    fix the run surfaces gets its own permanent-documentation destination
    named when it's made, per the usual rule.
  - **Done (2026-07-30).** Eighteen package suites passed in an
    assembled multi-package environment. Four failures, none this
    change's: two from installed versions differing from the pins (fixed
    by installing the pins; design.md, "Suite-run failure root causes"),
    two `test_alkahest.py` cases needing a Node.js/Rust/Foundry toolchain.
    - **Typing checks run:** `typecheck-core` (1 pre-existing error,
      untouched file), `typecheck-core-registry-client` (clean),
      `core/registry`'s `mypy src/` (30 pre-existing errors, all in files
      this change never touched) — disclosed, not fixed under this task.
    - **Not run:** `core/registry`'s own pytest suite (unrelated deep
      dependency chain), `e2e-tests` (needs a live two-service stack),
      `openspec validate --all --strict` (unavailable, unchanged since
      Section 8).
    - No renamed-contract consumers found beyond what 11.2/11.4/11.6
      already caught during their own implementation.
- [x] 11.6 Migrate `CapacityReservation.vm_host` into `executor_ref`, per the
      decision in `design.md` item 7. Scoped strictly to `vm_host` —
      `vm_target`, `create_job_id`, and `vm_remove_job_id` are explicitly
      out of scope and stay as dedicated columns.
  - [x] 11.6.1–11.6.5 **Done.** `reserve()`, the settlement-resource
    rebind path, and `resize_reservation`'s internal re-reserve all write
    `executor_ref={"vm_host": ...}` (merged, not overwritten) via a new
    shared `_executor_ref_for_resource` helper. `attach_lease`/
    `update_lease_fields` no longer accept `vm_host=`.
    `find_active_lease_by_vm_target` filters via
    `func.json_extract(executor_ref, '$.vm_host')`.
    `_reservation_payload`'s `"vm_host"` key now reads from
    `executor_ref` — byte-compatible for every consumer outside `kit/site`.
    The dedicated column is dropped from the SQLAlchemy model.
  - [x] 11.6.6 **Done.** Migration backfills `executor_ref` (merge, not
    overwrite) then drops the column, using a deterministic table-rebuild
    (not a best-effort `DROP COLUMN` attempt — see the 2026-07-30 update
    in `design.md`'s "Task 11.6 implementation notes").
  - [x] 11.6.7 **Tests, done.** New coverage for `reserve()`'s
    `executor_ref` derivation and for `find_active_lease_by_vm_target`
    (previously **no test coverage at all**). New migration test file
    `test_vm_host_executor_ref_migration.py`.
  - [x] 11.6.8 **Follow-up: `vm_target` also fully retired**, not just
    `vm_host` — see `design.md` for why the task's original scoping was
    wrong and what that surfaced (a real bare-metal payload-scoping bug,
    now fixed and tested).
  - [x] 11.6.9 **Follow-up: migration consolidation** — four migrations
    folded into the existing cutover migration rather than registered
    separately; see `design.md` for the safety verification.
  - **Final validation:** `kit/site`, `kit/fulfillment`, and the
    provisioning service suites passed.
  - **Permanent documentation:** none needed — checked
    `openspec/specs/site-capacity/spec.md`, `physical-provisioning/spec.md`,
    and `ARCHITECTURE.md` for now-stale `vm_host` mentions; all remaining
    mentions describe the still-true payload-level contract (the
    `vm_host` key still exists, still stripped at the storefront
    boundary) or an unrelated `vm_host` concept (the VM Ansible adapter's
    own fulfillment metadata).

### Section 11 code-review correction and API-credits modernization plan (opened 2026-07-30)

The completed entries above are preserved as implementation history. Code review
found two blocking defects and accepted a bounded Section 11 expansion. Section
11 remains open until the tasks below are implemented and validated.

- [x] 11.7 Correct VM exact-matcher composition and public kit API.
  - [x] 11.7.1 Export `dict_resource_satisfies_claim` from the public
    `market_site` package surface; VM composition must not import the adapter
    from the ledger implementation module.
  - [x] 11.7.2 Bind the VM composition matcher with
    `unit_claim_keys=("units", "gpu_count")`, using one VM-owned constant shared
    with authoritative ledger construction where practical.
  - [x] 11.7.3 Add a behavioral aggregate-client test proving a top-level
    `{"gpu_count": 2}` claim ranks a ten-unit matching site ahead of a two-unit
    matching site. Do not satisfy this acceptance criterion only by inspecting
    `functools.partial` keywords.
  - [x] 11.7.4 Retain `resource_type="compute.gpu"` as the current site-inventory
    discriminator and add/retain behavior coverage for resource-type mismatch;
    do not introduce buyer-facing offering vocabulary in this section.
  - [x] 11.7.5 Rename the function-local `required_attributes` variable in VM
    job-spec construction to `capacity_claim`; keep the serialized
    `required_attributes` key unchanged.
  - **Done (2026-07-30).** `market_site/__init__.py` now exports
    `dict_resource_satisfies_claim`; `capacity_client.py` imports from the
    public surface. `VM_UNIT_CLAIM_KEYS = ("units", "gpu_count")` bound
    into the injected matcher via `functools.partial` (can't be a shared
    Python object with `container.py`'s copy — separate deployables, HTTP
    boundary). Added a behavioral ranking test through a real
    `AggregateCapacityClient` — this exposed and fixed a real, separate
    bug: `FakeSite`'s snapshot response never included the `available`
    dimensions dict, so any test exercising an injected exact matcher
    against it was silently meaningless until fixed. Renamed the local
    variable in `vm_job_spec_service.py` to `capacity_claim`; the
    serialized `"required_attributes"` wire key is untouched (real
    external/persisted blast radius, correctly out of scope).
    Tests: `core/storefront` 20/20, `kit/site` 135/135 (22 new,
    equivalence-swept against the authoritative admission path — also
    caught that VM's ledger is composed with `("units", "gpu_count")`,
    not the module default), VM storefront unit 640/640 + integration
    146/148 (2 known, unrelated alkahest gaps).
  - **Permanent documentation after review acceptance:**
    `openspec/specs/market-composition/architecture.md`, "Composition from above
    and below"; `openspec/specs/site-capacity/architecture.md`, projected
    feasibility matching; `docs/development/ARCHITECTURE.md#storefront-capacity-boundary`.

- [x] 11.8 Make the SQLite reservation-table rebuild foreign-key safe.
  - [x] 11.8.1 Perform the rebuild on one dedicated connection using SQLite's
    offline-rebuild sequence: preserve the prior `foreign_keys` setting, disable
    enforcement before the migration transaction, rebuild/copy/drop/rename, run
    `PRAGMA foreign_key_check`, commit, and restore the prior setting.
  - [x] 11.8.2 Narrow the helper's name/documented guarantees to the schema shape
    it actually preserves, or extend it so every claimed constraint/index/trigger
    property is faithfully recreated. Prefer a reservation-table-specific helper
    over a misleading generic abstraction.
  - [x] 11.8.3 Add a migration regression fixture containing a
    `capacity_reservations` parent and `capacity_reservation_debits` child with
    `PRAGMA foreign_keys=ON`; assert both rows survive, the relationship remains
    valid, and `PRAGMA foreign_key_check` is empty.
  - [x] 11.8.4 Exercise the registered public migration path against the intended
    pre-cutover schema, not only private migration helpers.
  - **Done (2026-07-30).** `_drop_columns_via_table_rebuild` follows
    SQLite's documented offline-schema-change procedure on one dedicated
    connection. Chose 11.8.2's "extend" option over "narrow": kept the
    helper generic (`PRAGMA table_info`-driven) but added explicit
    guards — raises `NotImplementedError` if the target table has
    triggers, views, or outbound foreign keys, rather than silently
    mishandling them (confirmed `capacity_reservations` has none).
    Writing the FK-cascade fixture (11.8.3) caught a real bug in the
    first implementation — index capture was happening after the rename
    instead of before, matching zero indexes — and surfaced an unrelated
    debugging detour, both recorded in `design.md`. New tests: the
    FK-cascade fixture, a trigger/view refusal test, and a public
    `run_migrations()` entrypoint test (11.8.4) that simulates a database
    that never recorded the cutover migration, rather than calling the
    private migration function directly. Full suite:
    `provisioning/compute/service` (unit+integration) 547/547,
    migration-specific suite 27/27.
  - **Permanent documentation after review acceptance:** deployment/schema
    migration procedure in `openspec/specs/deployment-state/spec.md`; the
    executor-reference current-state rule in `openspec/specs/site-capacity/spec.md`
    if not already covered by its opaque reservation contract.

- [x] 11.9 Modernize API-credit package installation and Docker/reinit assembly.
  - [x] 11.9.1 Remove relative editable sibling sources such as `../../core` and
    repository-root `pythonpath`/`dev-mode-dirs` dependencies from API-credit
    packages where wheel installation replaces them.
  - [x] 11.9.2 Add or align dist-wheel and reinit targets for the API-credit
    domain, buyer, storefront, service, and new client package. Reinit must build
    the repository wheels first and install them into isolated virtual
    environments.
  - [x] 11.9.3 Update Docker build/install paths so builds consume the same wheel
    artifacts rather than relying on source-tree-relative editable imports.
  - [x] 11.9.4 Add wheel import and Docker-context validation covering each
    API-credit executable/package.
  - **Done (2026-07-30).** The wheel-building infrastructure already
    existed and was correctly wired; the deployed container path (both
    Dockerfiles already used `--no-sources --find-links /.dist`) was
    already correct. The real, narrower problem was local dev/reinit
    consistency: removed the domain package's `[tool.uv.sources]`
    editable overrides, pinned `arkhai-apicredits-domain` to `>=0.1.0` in
    storefront/buyer (confirmed correctly absent from `service`'s
    dependencies), added it to storefront/buyer's `reinit` targets, and
    removed the now-unneeded repo-root `pythonpath` fallbacks (left
    buyer's own `dev-mode-dirs` alone — a different, legitimate
    mechanism, not the sibling-dependency workaround this task targets).
    Extended `test_distribution.py`: strengthened version-constraint
    assertions and added a real build-install-import test for the
    `service` wheel (previously untested; building it surfaced a missing
    transitive dependency in the test fixture, fixed). Also found and
    fixed a pre-existing gap: `domains/apicredits/Makefile`'s `test`
    target never actually ran the domain-level `tests/` directory at
    all — added a `test-domain` target and wired it in.
  - **Permanent documentation after review acceptance:**
    `docs/development/ARCHITECTURE.md#build-packaging-and-initialization` and
    `#package-and-dependency-layers`; API-credit subsystem architecture for its
    package/client map.

- [x] 11.10 Add service-owned ordered migrations to the API-credit service.
  - [x] 11.10.1 Introduce an ordered SQLite migration registry and schema-migration
    tracking table owned by the API-credit service. Do not add a standalone
    migration CLI in this task.
  - [x] 11.10.2 Move schema evolution away from startup-only
    `Base.metadata.create_all`; retain `create_all` only where appropriate for an
    empty bootstrap and make startup verify expected schema version/drift.
  - [x] 11.10.3 **Corrected (2026-08-01):** this subtask's original
    wording ("deployment init wiring... following the compute service's
    established deployment pattern") described work that was never
    implemented and was never actually satisfiable — this service has no
    Kubernetes deployment topology to attach an init container to (no
    Helm chart at all today), later confirmed by 11.14.3's explicit
    exclusion of exactly this. What was actually built: `run_migrations()`
    runs in-process at application startup, before the app serves
    requests, inside `container.py`'s composition. The checkbox stays
    `[x]` because the underlying need is genuinely met; the original
    task description's framing was wrong, not the implementation.
  - [x] 11.10.4 **Corrected (2026-08-01):** no deployment-init contract
    tests exist or should be claimed — there is no deployment-init step
    to contract-test. `test_migrations.py` covers fresh bootstrap,
    idempotent rerun, two old-schema-fixture tests adopting a database
    created via the pre-migration `create_all()`-only startup,
    `check_schema_version`'s drift detection, and the SQLite-only engine
    guard.
  - **Done (2026-07-30), corrected (2026-08-01).** `db/migrations.py`
    mirrors `compute_provisioning_service`'s shape (`Migration`,
    `SchemaDriftError`, `apply_schema_migrations`, `check_schema_version`)
    scoped down: no CLI, `_MIGRATIONS` started empty (11.14 later
    replaced it with a real baseline migration). `run_migrations()`
    replaces bare `create_all`; `create_db_engine`'s untested non-SQLite
    branch removed for an explicit `ValueError`; `init_db` removed
    outright (one caller, so a compatibility alias would have been pure
    clutter) rather than kept as a deprecated shim. The record originally
    described in-process startup migration as provisional ("kept ready
    for when it gains a deployment topology") — corrected: it's this
    service's actual, current behavior for its actual, current
    deployment topology, not a placeholder. Full suite: 24/24 (14
    pre-existing + 9 new + 1 from 11.14's later baseline migration).
  - **Explicitly carried forward, not resolved here (repository-owner
    direction):** this service needs a Helm chart and the migration call
    refactored into a Kubernetes init container, the same way the VM
    domain's provisioning service already works, once it gains a
    Kubernetes deployment topology to attach one to. Tracked here, not
    deferred to a new OpenSpec change.
  - **Permanent documentation after review acceptance:**
    `openspec/specs/deployment-state/spec.md`, service schema initialization;
    API-credit subsystem specification/architecture.

- [x] 11.11 Add a typed capacity-administration client.
  - [x] 11.11.1 Define a client package/surface for operator resource
    registration and update, separate from buyer-facing reservation/probe use.
  - [x] 11.11.2 Centralize request/response models, authentication, timeout
    behavior, and stable error translation for the existing capacity resource
    administration endpoints.
  - [x] 11.11.3 Replace API-credit storefront's direct
    `PUT /api/v1/capacity/resources/{resource_id}` construction with the injected
    client. Preserve the live endpoint and current behavior.
  - [x] 11.11.4 Add service-contract and caller-composition tests.
  - **Done (2026-07-30).** New package `kit/site-client`
    (`arkhai-kit-site-client`, module `market_site_client`) — a kit-layer
    sibling to `kit/site`, mirroring the established `core/storefront` +
    `core/storefront-client` pattern rather than extending
    `RemoteCapacityClient` (documented as read/reserve/commit-only,
    deliberately never the operator-write path).
    `SiteCapacityAdminClient.register_resource` wraps
    `PUT /api/v1/capacity/resources/{resource_id}`, with an independently
    defined request model (kept in sync by hand with `kit/site`'s
    server-side one rather than importing its full SQLAlchemy
    implementation). `SiteCapacityAdminClientError` mirrors
    `core/storefront-client`'s `StorefrontClientError` pattern. Wired
    into `kit/Makefile`'s dist/test chains and
    `domains/apicredits/storefront`'s dependencies/reinit.
    `apicredits_storefront/startup.py`'s `_register_seed_quota` now
    constructs this client instead of raw `httpx.AsyncClient` — live
    endpoint and request body unchanged, confirmed by a new
    caller-composition test. Tests: 5 in `kit/site-client`, 2 new
    caller-composition tests (this function had **no test coverage at
    all** before).
  - **Permanent documentation after review acceptance:**
    `openspec/specs/site-capacity/spec.md`, capacity administration surface;
    `docs/development/ARCHITECTURE.md#site-authority`.

- [x] 11.12 Add an API-credits-domain service client.
  - [x] 11.12.1 Introduce a domain-owned client package for issue, lookup, revoke,
    and balance-adjustment/compensation operations currently expressed as raw
    URLs in settlement callers.
  - [x] 11.12.2 Provide typed models, one reusable configured HTTP client,
    authentication/timeouts, and stable domain error translation.
  - [x] 11.12.3 Inject the client into settlement/issuance callers and remove
    direct URL construction and per-operation ad hoc `httpx.AsyncClient` usage.
    Preserve current issuance and compensation behavior; do not redesign their
    durability in this task.
  - [x] 11.12.4 Add client contract, error mapping, and caller composition tests.
  - **Done (2026-07-30), corrected (2026-07-30).** New
    `domains/apicredits/settlement/credits_client.py`: `CreditsServiceClient`,
    one class holding `service_url`/`admin_key` and exposing all five
    operations as methods, replacing five independent free functions
    each building their own `httpx.AsyncClient`. `CreditsServiceError`
    unchanged in shape. **First pass under-delivered 11.12.3**: kept
    `issuance.py`'s free functions as thin wrappers constructing a client
    internally, but the actual callers (`fulfillment.py`,
    `keys_lookup.py`) still called the free functions, not the client —
    correctly flagged on review as not what 11.12.3 asked for.
    **Corrected**: `fulfillment.py` and `keys_lookup.py` now construct
    and call `CreditsServiceClient` directly. With every real caller
    confirmed migrated (checked the full blast radius first), deleted
    `issuance.py` outright rather than keep it as a pointless indirection
    layer with no remaining callers, updating `settlement/__init__.py`'s
    exports and the domain wheel's force-include list to match. Required
    updating three existing tests that monkeypatched the free-function
    names directly — now patch `CreditsServiceClient`'s methods as class
    attributes. Added direct test coverage for `lookup_key_record`,
    which had **no coverage at all** before (only ever exercised through
    a test that monkeypatched the whole function away). Full suite after
    the correction: domain 15/15, storefront 51/51, buyer 16/16, service
    23/23.
  - **Permanent documentation after review acceptance:** API-credit subsystem
    spec/architecture; `docs/development/ARCHITECTURE.md#package-and-dependency-layers`
    only if repository-wide client ownership guidance needs clarification.

- [x] 11.13 Amend Section 11 documentation and close review validation.
  - [x] 11.13.1 Preserve the superseded hardcoded-matcher discussion in
    `design.md` and append the accepted injected-matcher decision, projection
    boundary, alias requirement, `resource_type` interpretation, and deferred
    cross-domain requirement-vocabulary change.
  - [x] 11.13.2 Correct proposal/task status so Section 11 is not described as
    complete while 11.7–11.12 remain open.
  - [x] 11.13.3 Correct production docstring references to exact stable permanent
    headings and remove migration/changelog commentary from production code.
  - [x] 11.13.4 Run focused suites for every task, API-credit package/service
    suites, wheel import checks, migration entrypoint tests, Docker/deployment
    contract tests, root validation available in the repository environment, and
    disclose any unavailable e2e/OpenSpec checks.
  - [x] 11.13.5 After implementation stabilizes and review accepts it, promote the
    durable decisions to the exact permanent destinations recorded in
    `design.md` and complete the Section 11 design-promotion record.
  - **Done (2026-07-30), except 11.13.5 — deliberately deferred, not
    incomplete (see the promotion record at the end of this section).**
    11.13.1: confirmed already present in `design.md` via the applied
    code-review planning diff. 11.13.2: `proposal.md`'s Section 11 status
    corrected. 11.13.3: swept every file this section touched for
    task-number/review-history references — found and fixed one real
    violation. 11.13.4: every touched package's suite passed except two
    Alkahest integration cases needing a toolchain. Disclosed as unrun:
    `core/registry`'s suite, `e2e-tests`, strict validation, and the
    API-credit `make dist` chain (its tests ran directly, not from
    wheels). 11.13.5 was completed by 11.18.6.

**Explicitly deferred to a new OpenSpec change** (`structured-capacity-requirements`,
opened 2026-07-31): nested buyer-facing `requirements`, normalization into
generic dimensions/attributes, canonical `ResourceRequirement`/`CapacityClaim`
naming, compatibility migration of the wire/persisted `required_attributes`
key, buyer-facing offering vocabulary. **Still unassigned to any change:**
background-task supervision, core watchdog changes, generic remote-capacity
assembly, durable API-credit issuance/compensation, quota-release
compensation, and exact API-credit matcher adoption.

### Section 11 second code-review correction plan (opened 2026-07-31)

The completed implementation entries above remain preserved as history. The
second review accepted the following bounded corrections and explicitly skipped
a deployment-topology redesign, startup-lifecycle tests, a new client protocol,
capacity-admin caller expansion, and core-layer refactors. Section 11 remains
open until the accepted corrections below are implemented and validated.

**Correction (2026-08-01):** this plan arrived as an external review upload
marking 11.16.1, 11.16.3, 11.17.2, 11.18.1, 11.18.3, and 11.18.4 done on files
that were unchanged; they were unchecked, then implemented. The upload also
restored a dead `issuance.py` and reverted part of `proposal.md`, both
reconciled.

- [x] 11.14 Make the API-credit migration registry exercise real ordered state.
  - [x] 11.14.1 Register a durable API-credit baseline/adoption migration, or
    rename and document the current mechanism as a migration-registry bootstrap.
    The chosen design must give `check_schema_version()` a non-empty expected
    version and must not imply schema-drift guarantees that an empty registry
    cannot provide.
  - [x] 11.14.2 Add ordered migration tests proving deterministic execution,
    durable migration-ID recording, idempotent reruns, failed-migration
    non-recording, preservation of earlier successful migrations, and
    incomplete-sequence detection.
  - [x] 11.14.3 Keep migrations in-process for the current API-credit deployment
    topology. Do not add a standalone migration CLI, Kubernetes init container,
    deployment split, or startup-lifecycle contract tests in this correction.
  - **Permanent documentation after review acceptance:** API-credit subsystem
    specification/architecture for schema ownership and current startup behavior;
    `openspec/specs/deployment-state/spec.md` only for repository-wide SQLite
    migration invariants that genuinely apply today.

- [x] 11.15 Finish API-credit client composition and HTTP-contract validation.
  - [x] 11.15.1 Construct `CreditsServiceClient` at the API-credit composition
    boundary and inject/reuse it in settlement and key-lookup services rather
    than constructing concrete clients inside operation functions. Preserve the
    current concrete client type; do not introduce a new client `Protocol` in
    this task.
  - [x] 11.15.2 Add client-level HTTP contract tests for every supported
    operation: URL/path, admin authentication header, timeout/configuration,
    request body, successful response parsing, transport failures, HTTP failures,
    not-found behavior where applicable, and rollback operation sequencing.
  - [x] 11.15.3 Keep the typed capacity-administration caller behavior unchanged;
    no additional startup caller-composition expansion is required by this
    correction.
  - **Permanent documentation after review acceptance:** API-credit subsystem
    architecture for the domain-owned service-client boundary and composition
    ownership.

- [x] 11.16 Tighten production boundaries and comments.
  - [x] 11.16.1 Replace the long `VM_UNIT_CLAIM_KEYS` implementation-history
    commentary with a concise present-state invariant that it must match the VM
    capacity authority's legacy aliases. Keep the full rationale in this change's
    design record.
  - [x] 11.16.2 Validate every interpolated SQLite identifier used by the generic
    table-rebuild helper against a strict identifier rule, or narrow the helper
    to fixed reservation-table identifiers. Preserve the accepted foreign-key
    safety and schema-feature guards.
  - [x] 11.16.3 Remove future-oriented, migration-chronology, comparison, and
    changelog-style prose from API-credit migration production modules.
    Production documentation must describe current startup, versioning, and
    failure invariants only.
  - **Done (2026-08-01).** 11.16.1: `VM_UNIT_CLAIM_KEYS`'s docstring cut
    from a 15-line rationale to 5 lines stating only the current invariant
    (must match `container.py`'s composed value) and the one-sentence
    reason it can't be a shared import (domain-neutral service, separate
    deployables); the full alternatives discussion already lives in
    `design.md`. Also removed a reference to "this change's design.md"
    from the docstring itself — production code shouldn't point at
    discuss-phase documents even when the pointer would have been
    accurate. 11.16.2: added `_validate_sql_identifier` (a strict
    `^[A-Za-z_][A-Za-z0-9_]*$` check) applied to `table_name`,
    `columns_to_drop`, and every column name read back from `PRAGMA
    table_info` before any of them are interpolated into raw SQL — kept
    the helper generic rather than narrowing it, consistent with 11.8.2's
    earlier decision. New tests: rejecting an unsafe table name, an
    unsafe column name, and the validator's own accept/reject boundary
    (8 rejection cases including a SQL-injection-shaped string, quotes,
    spaces, a leading digit, and empty string). 11.16.3: rewrote both
    `db/migrations.py`'s module docstring and `check_schema_version`'s
    own docstring — removed the "unlike `compute_provisioning_service`"
    comparison and, in both places, "kept ready for when this service
    gains a deployment topology" — a hypothetical future scenario stated
    as though it were current rationale. Both now describe only what the
    module does and how migrations actually run today. Full suite:
    `provisioning/compute/service` 550/550 (16 new: 3 for 11.16.2 plus
    the 13 pre-existing migration tests), `domains/apicredits/service`
    24/24.

- [x] 11.17 Strengthen API-credit wheel and import isolation.
  - [x] 11.17.1 Remove remaining repository-root `pythonpath`, `dev-mode-dirs`,
    editable sibling sources, or equivalent source-tree fallbacks where wheel
    installation now makes them unnecessary. Document any retained exception
    with a current package-local reason.
  - [x] 11.17.2 Add architecture/distribution tests that reject relative editable
    internal dependencies and prove API-credit packages import in isolated
    environments using only built internal wheels.
  - [x] 11.17.3 Validate the API-credit Docker build contexts or equivalent
    packaging assembly so no hidden repository-relative dependency is required.
  - **Done (2026-08-01).** 11.17.2:
    `test_no_apicredits_project_declares_an_internal_editable_source`.
    11.17.3: the storefront image imported the domain from a raw
    `COPY domains/` rather than its wheel; the copy is gone, and
    `test_storefront_domain_imports_resolve_without_a_raw_source_copy`
    holds the wheel-only import (design.md, "Rationale moved from task
    notes at closeout", 11.17). A real `docker build` was not run then;
    the pipeline's image builds have since exercised it.
  - **Permanent documentation after review acceptance:**
    `docs/development/ARCHITECTURE.md#package-and-dependency-layers` and
    `#build-packaging-and-initialization`; API-credit subsystem package map.

- [x] 11.18 Reconcile Section 11 documentation and validation records.
  - [x] 11.18.1 Amend task 11.10's completion record: distinguish the completed
    in-process migration-registry bootstrap from deployment-init and startup-drift
    work that was not implemented. Do not claim deployment-init contract tests.
  - [x] 11.18.2 Amend `proposal.md` so Section 11 remains under review while
    tasks 11.14–11.18 are open.
  - [x] 11.18.3 Shorten completed-task notes to final behavior, material validation
    evidence, unresolved/deferred work, and permanent documentation destinations;
    retain detailed alternatives and review rationale in `design.md`.
  - [x] 11.18.4 Correct production documentation to reference exact stable
    permanent headings and remove speculative statements such as utilities being
    kept ready for a hypothetical future deployment topology.
  - [x] 11.18.5 Run the focused migration, client, packaging, wheel-import, and
    SQLite-rebuild suites added by 11.14–11.17, plus the existing affected
    package suites. Disclose unavailable repository-wide e2e or strict OpenSpec
    validation rather than marking it complete.
  - [x] 11.18.6 Keep permanent design promotion open until implementation is
    stable and accepted in code review; then complete the existing Section 11
    promotion record using the destinations already identified in `design.md`.
  - **11.18.1 done (2026-08-01):** 11.10.3/11.10.4's checkboxes and text
    corrected directly in that task's own record (see 11.10 above) rather
    than only summarized here — the original subtask wording ("deployment
    init wiring," "deployment-init contract tests") described work that
    was never implemented and, per 11.14.3, was later explicitly excluded
    from scope entirely. The record now says plainly what was built
    (in-process startup migration) instead of implying a deployment step
    that doesn't exist.
  - **11.18.3 done (2026-08-01).** Shortened every completed-task note in
    11.1–11.13 to final behavior, material validation evidence,
    unresolved/deferred work, and permanent-documentation destinations.
    Detailed alternatives, debugging narratives, and review rationale
    that weren't already in `design.md` were moved there first (the
    core-vs-kit layering decision behind 11.2, the suite-run failure root
    causes behind 11.5, the `vm_target` retirement and migration-
    consolidation reasoning behind 11.6, and the FK-cascade debugging
    detour behind 11.8), not simply deleted.
  - **11.18.4 done (2026-08-01):** covered by 11.16.3's work above
    (`db/migrations.py`'s two docstrings) — no other production module
    touched by this correction pass had the same pattern (checked
    `credits_client.py`, `credits_service_client.py`, and
    `kit/site-client`'s `client.py`; all clean).
  - **11.18.5 done (2026-08-01).** Every touched package's suite passed.
    Disclosed as unrun then: `e2e-tests`, strict validation, and a real
    Docker build.

**Explicitly skipped in this correction:** API-credit deployment-init/CLI work,
startup-lifecycle contract tests, a new credits-client protocol, additional
capacity-admin caller tests, background-task supervision, core watchdog changes,
and generic remote-capacity composition extraction.

## Section 11 design promotion record

Completed 2026-08-01. Most of Section 11 was schema-internal removal or
implementation restructuring with no new externally-observable behavior,
so most tasks correctly promote nothing. The decisions below are the
ones that needed a permanent home outside this change directory.

| Accepted decision | Permanent location |
|---|---|
| Domain-injected exact `ClaimMatcher` composes with the core-layer aggregator's coarse default, without moving site-specific matching into `core` | `openspec/specs/site-capacity/architecture.md#projected-feasibility-matching` |
| `executor_ref`-carried domain-specific physical-placement fields (e.g. `vm_host`) are backing physical-resource identifiers under the opaque-reservation rule | Already covered generically by `openspec/specs/site-capacity/spec.md`'s existing requirement — confirmed by inspection, no edit needed |
| API-credit service: composed, reused `CreditsServiceClient`; typed `SiteCapacityAdminClient` for operator writes, distinct from buyer-facing `RemoteCapacityClient` | `openspec/specs/api-credits/architecture.md#implementation-composition`; `docs/development/ARCHITECTURE.md#site-authority` |
| API-credit service: in-process startup migration is a valid instantiation of service-owned migration history for a service without a separate-deployment-step topology, not an exception to the general rule | `openspec/specs/deployment-state/spec.md`'s "Service-owned migration history" requirement, new scenario |
| API-credit packages resolve internal dependencies from built wheels only, matching the repository-wide rule already stated | `docs/development/ARCHITECTURE.md#build-packaging-and-initialization` (already covers this generically; API-credit domain brought into compliance, not new policy) |

**Not promoted, and why:** the generic SQLite table-rebuild helper's
foreign-key safety and identifier validation (11.8, 11.16.2) are
implementation-technique correctness properties of a migration helper,
not observable subsystem behavior — recorded as in-code docstrings,
matching how this document already treats similar implementation-
location decisions. The `VM_UNIT_CLAIM_KEYS` duplication rationale
(11.16.1) is likewise implementation technique, not new normative
behavior. The Docker build-context fix (11.17.3) restores an existing,
already-stated wheel-only policy rather than establishing new policy.

## 12. Documentation and specification closure

- [x] 12.1 Update `ARCHITECTURE.md` service map, terminology table, ID definitions, lifecycle ownership, transaction boundaries, recovery workers, pull-based status/result query contract, and teardown flow. Note `replace-polling-with-authenticated-push` as planned future work, not implemented by this change. **Done:** `ARCHITECTURE.md`'s "Identifiers" (a table split mid-way that had dropped the `pool_id` row was repaired), "Fulfillment status and results", "Release" (rewritten from the pre-Section-10 model), "Recovery workers" (new), the runtime service map, and the authority table.
- [x] 12.2 Update baseline `site-capacity` and `physical-provisioning` specs to incorporate completed POOLS-2/3/4/6/7 behavior when the change is archived. **Done.** Strict validation (8.15) showed requirements stranded after a `##` companion header, where OpenSpec cannot see them, in `resource-pool-management`, `physical-provisioning`, and `fulfillment`, plus missing scenarios and MUST/SHALL wording. All fixed; `fulfillment/spec.md`'s two companion headers became bold lead-ins keeping their `#fulfillment-convergence-worker` and `#durable-settlement-persistence` anchors, which code and documents cite. A stale "process-local" scheduler claim in `physical-provisioning/spec.md` was corrected. The five specs then validated clean. The requirements the deltas add are written by the archive (13.11).
- [x] 12.3 Update compute provisioning service, VM adapter, storefront, and operator documentation for migrations, watchdog health, status/result query usage, and recovery procedures without lease-expiry sequencing instructions. **Done.** The repository has no separate runbooks, so the specs and companions were checked. `physical-provisioning/architecture.md`'s "Proof-driven release" was rewritten to the two-owner split, and a false "no durable recovery aggregate" limit removed. Already accurate: the VM storefront and fulfillment companions, `DEPLOYMENT_AND_CONFIG.md`'s "Migrations at startup", and the provider-operation correlation section (now "Provider operation correlation"). Query usage and watchdog health: `fulfillment/spec.md`'s "Fulfillment status and result queries" and convergence worker, and `ARCHITECTURE.md`'s "Recovery workers".
- [x] 12.4 Verify the implementation against every POOLS-7 scenario and archive the OpenSpec change after validation. `proposal.md`'s "Permanent documentation impact" checklist (task 7.14) was added during Section 7 review rather than deferred here; confirmed it still reflects reality against the final Section 8-11 state. A "Blocked" note here, waiting on an end-to-end result, is superseded by the 2026-10-27 verification below.
      **Verification against the delta scenarios (2026-10-27).**
      - **End-to-end.** This supersedes the "Blocked" paragraph above: a passing result
        now exists. Validation `reviews/03-validation.md`
        ran commit `02319877e` and passed every part: local, Helm (scenario pod exit
        0), and pipeline run 40495699817 with all three lanes green.
        - That record does not match scenarios to log lines. The run's own log does.
          `.snapshot/e2e-logs/40495699817/actions.log`, `e2e-vm` lane, under marker
          `e2e_deal`, shows `test_full_deal.py`'s stages 00 to 11b running:
          - 09a: the provisioning job succeeds;
          - 09b: settlement ready, with credentials;
          - 10b: the lease cycle records the `fulfillment_id`;
          - 11a: convergence dispatches teardown while capacity stays held;
          - 11b: provider completion releases the lease and capacity.
        - The lane's total is "134 passed, 162 deselected", with none failed. That is
          the live-services confirmation this task and 10.14 were waiting on.
        - Archival is closeout's 13.11, not this task's.
      - **Scenarios.** The 24 scenarios in `specs/physical-provisioning/spec.md` (20)
        and `specs/site-capacity/spec.md` (4) were mapped to the tests that exercise
        them at HEAD. Levels below:
        - "application integration" is the service's app over ASGI, as `TESTING.md`
          defines it;
        - "library integration" is a kit library against real SQLite;
        - "service, real SQLite" marks a service's own components against real SQLite
          without the app, which `TESTING.md` does not name as a level.
      - **Asserted in full (nine):**
        - Equivalent fulfillment retry:
          `test_fulfillment_api.py::TestARepeatedBeginAdoptsTheAcceptedFulfillment`
          (application integration).
        - Crash during assignment:
          `test_scheduling_composition.py::test_real_container_composed_schedule_rolls_back_all_participating_tables`
          (service, real SQLite, through the real DI container).
        - Recovery retries create submission:
          `test_fulfillment_api.py::TestAcknowledgementFailureRecovery`
          (application-composed) and
          `test_job_fulfillment_migration.py::test_an_unrecorded_create_job_is_found_by_its_contract_and_redispatch_finds_it`.
        - Worker dies after claiming: `test_fulfillment_convergence.py`'s
          `test_worker_death_leaves_a_reclaimable_*` and
          `test_concurrent_reclaim_cannot_be_clobbered_by_a_stale_outcome` (service,
          real SQLite).
        - Result query for a completed fulfillment:
          `test_fulfillment_api.py::TestStatusAndResultQueries::test_result_on_an_active_fulfillment_includes_live_credentials`.
        - Repeated result queries: `kit/fulfillment/tests/unit/test_fulfillment.py`'s
          `test_get_fulfillment_result_does_not_mutate_fulfillment_state` and its
          siblings (unit, fakes).
        - Reservation expires before fulfillment:
          `test_lease_release_api.py::test_a_lease_whose_fulfillment_never_began_is_released_directly`.
        - Existing active VM:
          `test_legacy_backfill_teardown.py::test_pre_cutover_vm_lease_backfills_and_tears_down_to_release`.
        - Ambiguous active VM mapping: `test_legacy_vm_lease_migration.py`'s
          conflict and rollback tests (service, real SQLite, under `unit/`).
      - **Asserted in all but one point:**
        - "Process restarts after acceptance": a fresh watchdog resumes from the
          durable state, but the handlers are called directly rather than through
          its periodic loop.
        - "Unknown owning authority": the rejection is asserted. That nothing is
          forwarded holds only because the site has no forwarding path.
        - "Existing host migration": the migration still places every existing host
          in `default` through the column default, ahead of the backfill. It now
          refuses a database whose `default` pool is missing instead of creating the
          pool (`_migrate_resource_pools_and_hosts_pool_id`). The requirement holds
          for every database the chain accepts. "Before" is not itself asserted.
      - **Behaviour the code no longer has, so the delta would promote a false
        requirement at archive:**
        - "Credentials rotate between two queries" and the `credential_generation`
          clause of "Credentials are fetched on read". This change dropped the field
          itself (Section 8 decisions, above), and no `.py` file names it.
      - **Requirement text that is not system behaviour:**
        - "Broad capacity schema cleanup" opens "POOLS-7 MUST perform the approved
          breaking rename".
        - "Unambiguous capacity reservation identity" ends with "Planning MUST review
          whether site-plus-pool composite identity is additionally required".
        - Both would land in `openspec/specs/site-capacity/spec.md` at archive as
          written.
      - **Holds, but has no production trigger or is only partly tested:**
        - "Reservation requirements change": nothing mutates an assignment in place.
          `resize_reservation` supersedes and is tested at library level
          (`kit/site/tests/integration/test_ledger.py`'s `resize_*` tests), but has no
          production caller. No test schedules the superseding reservation.
          `openspec/specs/site-capacity/spec.md`'s "Reservation supersede and the
          release guard" already states the current rule.
        - "Reservation routed to owning site": every production caller names its
          `site_id`. Targeted status and terminate calls are shown not to fall back
          (`domains/vms/storefront/tests/integration/test_site_trust.py`). Targeted
          schedule, begin, and result calls are not. `AggregateFulfillmentClient`
          still falls back across sites when no `site_id` is given
          (`market_storefront/services/capacity_client.py`, `_route_order`).
      - **Covered only in part:**
        - "Conflicting fulfillment retry": the job count after a conflict is not
          asserted, and `begin` cannot carry a resource or provider.
        - "Resource selected before fulfillment": "no provider command" is not
          asserted.
        - "Multi-resource fulfillment representation": unit fakes only; nothing
          persists two outputs.
        - "Pool configuration changes after acceptance": the frozen payload and the
          retry are proven in separate tests.
        - "Recovery retries teardown submission": a deterministic key plus generic
          contract dedup, but no redispatched-teardown test.
        - "Status query after process restart": a fresh composition reads durable
          state (now `kit/fulfillment/tests/integration/test_fulfillment_restart.py`),
          but nothing restarts mid-lifecycle.
        - "Smaller scheduled shape" and "Scheduling exceeds reservation": "without
          increasing" and "before assignment" are not asserted.
        - "Fulfillment succeeds but is never queried": inferred only.
      - **What this means for closeout.** Closeout's 13.9 note says this change's
        delta specs "remain compatible and promote as written". The two groups
        "Behaviour the code no longer has" and "Requirement text that is not system
        behaviour" contradict that. The owner chose to reconcile them here
        (2026-10-27), applying decisions already recorded rather than making new ones:
        - `specs/physical-provisioning/spec.md`: the `credential_generation` sentence
          and the "Credentials rotate between two queries" scenario are removed,
          following this change's Section 8 decision to drop the field. "Durable
          fulfillment status and result queries" no longer names
          `replace-polling-with-authenticated-push` as "not yet started"; it says the
          service does not push results and the guarantee does not depend on push.
          That falls under the same rule against change names in permanent specs.
        - `specs/site-capacity/spec.md`: "Broad capacity schema cleanup" ("POOLS-7
          MUST perform…") is restated as "Capacity schema separation", the current
          schema rule, and keeps its "Existing host migration" scenario. The
          "Planning MUST review…" sentence is deleted from "Unambiguous capacity
          reservation identity".

        Every other delta requirement holds as written. The partial coverage is
        recorded for the pre-closeout review; it is not a defect in the delta.
        `make check-change` (strict OpenSpec validation included) passes after the
        edits.
      - **A further divergence, outside the delta.** `openspec/specs/physical-provisioning/spec.md`
        says leftover `connectivity` content is "opaque metadata the adapter forwards
        unchanged". The VM fulfillment plan validates the field and never reads it
        (`vm_fulfillment_plan.py`). The model also still declares relay fields that
        the same spec says `connectivity` must not carry.
      - **Resolved (2026-10-27, pre-closeout review 17 F1, owner's alternative A).**
        A VM request carrying `connectivity` is now refused rather than stored. See
        `design.md`'s "Pre-closeout review 17 F1" for the decision.
        - `VmConnectivitySettings` and the request's `connectivity` field are
          deleted (`vm_provisioning_adapter/models/fulfillment_model.py`). The
          request's `extra="forbid"` refuses the field at preparation, inside the
          acceptance transaction, so a refused request is never stored.
        - Paired migrations remove `connectivity` from stored VM requests, sharing
          field-removal helpers with the guest-name pair:
          - provisioning: `20261027_001_vm_fulfillment_request_carries_no_connectivity`;
          - VM storefront, over `escrows.fulfillment_context`:
            `20261027_001_fulfillment_context_carries_no_connectivity`.

          Prepared operations, provider metadata, and the storefront's
          `vm_delivery_records` are not touched. The delivery table arrived after
          the storefront stopped sending the field, so it cannot hold one.
        - Delta specs: MODIFIED `physical-provisioning` "Ansible fulfillment
          adapter" (the refusal and its scenario) and MODIFIED
          `vm-storefront-fulfillment` "The storefront does not select buyer access
          infrastructure".
        - Tests:
          - unit: `test_vm_fulfillment_plan.py::test_a_request_naming_a_relay_is_refused_before_a_port_is_leased`;
          - application integration, through `ComputeProvisioningClient`:
            `test_fulfillment_api.py`'s `test_a_request_naming_a_relay_is_invalid`
            and `TestARequestNamingARelayIsRefused` (422; no fulfillment, request,
            or job stored);
          - service, real SQLite: `test_vm_fulfillment_request_migration.py`'s
            connectivity tests, plus the migration-ID set in `test_database.py`;
          - storefront integration: `test_fulfillment_context_migration.py`'s
            connectivity test.
        - Evidence:
          - `make check-packaging`: passed.
          - `make test-provisioning`: unit 658 passed, application integration 536
            passed.
          - `make test-provisioning-adapter`: 37 passed.
          - `make test-storefront`: unit 1103 passed with 1 skipped; integration
            449 passed.
          - `make test`: passed (exit 0).
          - `make check-change`: passed (comment hygiene, citations, task list,
            change index, strict OpenSpec validation).
        - Fresh-context check of the diff against `a3103948a` found no blocker.
          - Fixed:
            - placeholder comments added to the new test fixtures;
            - the guest-name wrapper's docstring no longer claims a version check;
            - `design.md` corrected where it still described
              `VmConnectivitySettings` as standing;
            - the storefront migration's docstring no longer calls the escrow copy
              the replayed one. Recovery replays `vm_delivery_records`.
          - Declined:
            - a test that the storefront migration is registered in
              `VM_MIGRATIONS`, a gap the guest-name migration shares;
            - rewording the guest-name pair's replay wording, which predates this
              fix.
          - Dropped: a draft storefront scenario that described a migration step
            rather than current behaviour.
- [x] 12.5 **Comment hygiene and import placement, before the pre-closeout review.** Run
      `make check-comment-hygiene` and read the comments this change added for any that
      narrate the review or migration that introduced them; move each import the change
      added to module level unless a verified circular import or a recorded lazy-load
      reason keeps it local. Closeout only confirms both.
      **Done (2026-10-27).** The change's code landed on `dev` as its section pull
      requests. "Added by this change" was therefore read from `git diff 3e8c33554~1
      9b2bd3fe2`, the first section commit's parent through the promotion record,
      restricted to what still exists at HEAD.
      - That range also carries other work merged to `dev` in the same weeks. The
        comment rewrites were attributed one by one with `git blame`/`git log -S`.
        The import moves were taken from the range as a whole, so a few may predate
        this change, such as one of the two `resource_feasibility_view` imports in
        `test_resource_satisfies_requirement.py`.
      - **Comments.** `make check-comment-hygiene` passes. The narrative markers it
        cannot catch were swept with grep across the tree: "review/finding",
        "previously/originally/used to/no longer", "now lives/now acquires",
        "gap/the fix", "for now/not yet/yet", "first pass", "POOLS". The
        fresh-context check found more, with "yet" phrasings and retired class names
        the grep missed. Every one this change added was rewritten as current
        invariants or current names:
        - `fulfillment_convergence.py`: the `_claim` and `_with_owned_record`
          docstrings.
        - `db/migrations.py`: the `settlement_resource_id` docstring's "no production
          caller exists yet".
        - `kit/site`'s `resize_reservation` docstring: "no caller uses this method
          yet", and the retired `AnsibleFulfillmentProvider.prepare_create`, now
          `VmFulfillmentPlan.prepare_create`.
        - `kit/site`'s held-reservation lookup docstring ("a future caller ... a
          not-yet-built direct-resource-reservation path").
        - `core_storefront/sqlite_client.py`: the `escrows` schema comment and
          `update_escrow`'s docstring. Both said the three fulfillment-identity
          columns let a caller resume by escrow after a restart, but nothing does.
        - `vm_job_spec_service.py`'s resource-type comment ("needs to carry yet").
        - The VM storefront's `terminate_vm_lease` docstring
          (`market_storefront/services/fulfillment_service.py`).
        - `VmConnectivitySettings`'s docstring and field comment. They now say what
          is true: the plan never reads the field, and a request cannot select a
          relay. They had said the settings were storefront-configured "for now",
          and that the remote port is leased by the service.
        - Tests:
          - `test_fulfillment_convergence.py`: the "code review finding" header and
            three docstrings.
          - `test_compute_contract_api.py`.
          - `test_fulfillment_api.py`: five references to the retired
            `AnsibleFulfillmentProvider`, now `JobFulfillmentProvider`, and
            `TestTeardownPreparation`'s "no HTTP path to exercise yet". The teardown
            endpoint exists.
          - The API-credit service's `test_migrations.py`: two docstrings written
            while there were no migrations and no deployment step.
          - `test_legacy_backfill_teardown.py`: "pre-POOLS" and "new teardown path".
          - `kit/site/tests/integration/test_ledger.py`: two docstrings.
          - `test_vm_job_spec_service.py`.
          - The VM storefront's `test_fulfillment_service.py`. One comment wrongly
            said nothing reads the identifiers back; restart convergence does, from
            the delivery row.
          - `test_capacity_reservation_boundary.py` ("the fix didn't overcorrect").
          - `test_sqlite_client_escrow_fulfillment_identity.py`. Its docstring no
            longer claims resumption reads the escrow row; it reads the delivery row.
      - **Imports.** Every indented import the range added and HEAD still has is now at
        module level. None hit a circular import: the full suite passes with them
        moved.
        - Production code:
          - `db/database.py`: `FulfillmentBase`, `SiteBase`, and the adjacent
            `PoolsBase` and `VmBase`. `VmBase` had stayed local under a comment
            saying the module imports without the optional VM adapter. That was
            false, since `db.migrations`, which `database.py` imports, already
            imports `vm_provisioning_adapter.db` at module level. The comment is
            removed.
          - `db/migrations.py`: `FulfillmentBase`, `LegacyBackfillValidationError`,
            the VM legacy-backfill compiler, `SiteBase`, and the adjacent
            `PoolsBase`.
          - The API-credit storefront's `credits_service_client.py` (`config`).
          - The API-credit storefront's `startup.py` (`SiteCapacityAdminClient`). Its
            test had patched the `market_site_client` module attribute that the local
            import read at call time. `TESTING.md` forbids patching module-level
            imports, so `_register_seed_quota` now takes the client's `transport`, and
            `test_startup_seed_quota.py` passes an `httpx.MockTransport` instead of
            patching the client class. It still patches `_capacity_authority_site`
            and the container's signer, as it did before.
        - Tests:
          - provisioning service: `conftest.py` (the three metadata bases,
            `PhysicalSettlementScheduler`, `FulfillmentOrchestrator`,
            `SqlAlchemyFulfillmentUnitOfWork`), `test_fulfillment_api.py`,
            `test_compute_contract_api.py`, `test_legacy_backfill_teardown.py`,
            `test_fulfillment_convergence.py`, `test_vm_host_executor_ref_migration.py`;
          - `kit/fulfillment`: `test_fulfillment.py`;
          - `kit/site`: `test_dict_resource_satisfies_claim.py`,
            `test_resource_satisfies_requirement.py`, `test_settlement_assignment.py`;
          - `core/storefront`: `test_sqlite_client_escrow_fulfillment_identity.py`;
          - the VM storefront: `test_vm_job_spec_service.py`,
            `test_remote_capacity_client.py`, `test_fulfillment_resume_runtime.py`;
          - the API-credit storefront: `test_keys_lookup.py`,
            `test_startup_seed_quota.py`;
          - the API-credit service: `tests/integration/test_migrations.py` (`SiteBase`
            six times, the migrations module twice). The file moved out of
            `src/tests/unit/` after the change's range, which is why the range-based
            search first missed it.
        - Left as they are: `test_fulfillment_provisioning.py`'s `alkahest_py` probe
          inside `try`, which is an availability check, and
          `market_fulfillment/provider.py`'s `TYPE_CHECKING` import, which is
          module-level.
      - **Test placement.** `TESTING.md` moves a touched library test that uses a real
        database from `unit/` to `integration/`. Three moved:
        - `kit/site/tests/unit/test_settlement_assignment.py` to
          `kit/site/tests/integration/`;
        - `core/storefront/tests/unit/test_sqlite_client_escrow_fulfillment_identity.py`
          to `core/storefront/tests/integration/`;
        - `kit/fulfillment`'s file-database restart test, out of
          `tests/unit/test_fulfillment.py` into the new
          `tests/integration/test_fulfillment_restart.py`, with its own provider fake.
      - **Seen, not this change's, left alone.**
        - `kit/site/tests/integration/test_ledger.py`'s "documented pass-1 scope ...
          before this change" comment, from the multidimensional-capacity change's
          first pass.
        - The provisioning service's `pyproject.toml` declares the VM adapter under
          the optional `adapters` extra. The migration history imports the adapter at
          module level, so the service cannot start without it.
        - The `escrows` table's `capacity_reservation_id`, `settlement_resource_id`,
          and `fulfillment_id` columns are written by no production code. VM keeps
          the identity on its delivery record (`persist_delivery_fields_with_retry`).
          Whether to drop the columns is a schema decision, not comment work.
        - `reviews/03-validation.md`'s coverage table lists `test_credits_payment_deal`
          as passed. Run 40495699817's log shows all three of its tests skipped
          (`actions.log`, `e2e-apicredits`: "1 passed, 3 skipped").
      - **Also fixed.** Two rows of `design.md`'s Section 9 promotion table (around
        `VmConnectivitySettings` and the sizing precedence) named a file and a model
        that no longer exist. Each now carries a dated correction for closeout's
        13.9. The rest of the table is closeout's to re-check.
        `make check-change` reported two unresolvable citations in this change's
        `design.md`. One was the full-deal scenario's path written with its middle
        directories elided. The other was the connectivity-terms change, now archived as
        `openspec/changes/archive/2026-09-25-add-buyer-vm-connectivity-terms/`. Both
        now point at real paths.
      - **Evidence.** `make test` passed. Among its suites:
        - the provisioning service: unit 658 passed, application integration 527
          passed;
        - `kit/site`: 289 passed;
        - `kit/fulfillment`: 171 passed;
        - `core/storefront`: 217 passed, 2 skipped;
        - the VM storefront: unit 1103 passed, 1 skipped; integration 448 passed;
        - the API-credit storefront: 184 passed.

        These are the counts after the fixes, unchanged by the test moves. The edited
        source was exercised: each package under test installs editable.
        `make check-packaging` passed, including the architecture layer, scope,
        dependency, and kind rules. `make check-change` passed.
      - **End-to-end.** Validation 03 ran the commit before these edits. Moving imports
        to module level changes what the provisioning service, its migrate entrypoint,
        and the API-credit storefront load at start. The next validation's pipeline
        is therefore the evidence for this section:
        - `e2e-vm` (`e2e_deal` and the rest of its markers);
        - `e2e-apicredits` (`e2e_credits_deal`). Its storefront's startup registers
          the seed quota through the moved import. `e2e_credits_payment_deal` was a
          blocked skip in run 40495699817, with no payments target configured, so it
          is not evidence here;
        - `e2e-bare-metal`, whose stack runs the same provisioning service.

        No `e2e-tests/` marker exercises the comment rewrites.
      - **Round fixes (2026-10-27, implementation review 07).**
        - 07 F1, the owner's alternative A: the delta requirement that credentials
          are never persisted anywhere contradicted the job authority's `credentials`
          table, which the permanent requirement "Compute provisioning owns the job
          and host authorities" already requires. It is restated as "Credentials
          stay with the job authority and are read on demand". The same false claim
          is corrected in `openspec/specs/fulfillment/spec.md` (the "No persisted
          `SettlementResult`" paragraph) and in `docs/development/ARCHITECTURE.md`'s
          "Fulfillment status and results". `design.md` carries a dated correction.
          `openspec/specs/physical-provisioning/architecture.md`'s "Durable jobs,
          transient workers" now names the job record as the credential store and
          records two current limits:
          - the envelopes are plain JSON, and no job row is ever deleted;
          - an operator's VM password reset stores its new credentials against the
            reset job, which the fulfillment result does not read.

          The fresh-context check found the reset path. It also showed that
          `design.md`'s earlier "never rotated by this codebase" is not quite true.
        - 07 F2: `provisioning/compute/service/tests/integration/test_fulfillment_api.py`
          now sends every status, result, schedule and begin call through
          `ComputeProvisioningClient`. The five 404 and 422 cases assert
          `ComputeProvisioningError.status_code`, and the raw transport and
          `begin_raw` are gone. Their docstrings had claimed a typed client cannot
          observe a status code, which was false.
        - 07 F3: closeout's 13.8 no longer says that no end-to-end result exists.
        - **Evidence.** All checks passed:
          - the provisioning service suites (`make test-provisioning`): unit 658
            passed, application integration 527 passed;
          - `make test`;
          - `make check-packaging`, layer, scope, dependency and kind rules included;
          - `make check-change`.

          The fresh-context check of the diff against `cdb244466` raised:
          - the reset path, which is now fixed in the wording above;
          - the bare-metal provider's use of the same job-backed provider, now named
            in `ARCHITECTURE.md`.

          Declined:
          - the substring match on `fulfillment_not_found` in the rejection cases.
            The client flattens `detail` into its message, so that is what it
            exposes.
          - things that predate this round and were left alone: an unused `FastAPI`
            import, three function-local `container` re-imports in the same file,
            and a narrating comment above the conflicting-retry assertion.
        - **End-to-end.** These fixes change no production code, so the fix commit's
          validation confirms them against an unchanged pipeline.

## 13. Closeout

Per `openspec/README.md#plan-closeout-requirements`.

- [x] 13.1 **Comment hygiene — confirm.** Run `make check-comment-hygiene`, and read
      the comments this change added for any that narrate the review or migration that
      introduced them. Do not edit code here: anything to rewrite returns the change to
      implementation.
      **Confirmed (2026-10-27).** `make check-comment-hygiene` passes. 12.5 swept the
      change's comments; pre-closeout review 28 read the ones the last round added. A
      grep of the Python added since `02319877e` for narrating markers finds one hit, a
      test fixture describing its data ("a VM lease still active"), which is not
      history. No production file names this change.
- [x] 13.2 **Import placement — confirm.** Check the imports this change added for any
      still local without a recorded reason. One that should move returns the change to
      implementation.
      **Confirmed (2026-10-27).** 12.5 moved every indented import the change added to
      module level, with the full suite passing. The Python added since `02319877e`
      adds no indented import, and review 28 found none without a reason.
- [x] 13.3 **Documentation compliance.** Re-check this change's accepted decisions
      against `openspec/README.md`'s placement rules, and the permanent documents
      against the code they describe. It carries delta specs for
      `physical-provisioning`, `site-capacity`, and `vm-storefront-fulfillment` (the
      last added by the fix for review 17 F1, named here per review 28 F1); confirm
      durable conceptual rationale sits in the companion `architecture.md` rather than
      only in `design.md`.
      **Done (2026-10-27).** Each section's decisions were checked against their
      destinations; the result is `design.md`'s "Closeout design-promotion record".
      Conceptual rationale sits in the companions: `fulfillment/architecture.md`
      (scheduling boundary, acceptance, legacy cutover, result ownership),
      `physical-provisioning/architecture.md` (job credential store, proof-driven
      release, provider operation correlation), and `site-capacity/architecture.md`
      (resize, projected matching). Three corrections:
      - The `physical-provisioning` delta's "Provisioning-owned lifecycle
        convergence" required a "multi-replica-safe" claim mechanism. Section 6 item 1
        decided that phrase means safety under concurrent claim attempts, serialized by
        SQLite's single writer, and `fulfillment/spec.md` says it is not a distributed
        multi-replica protocol. The delta now says so, applying that decision.
      - `ARCHITECTURE.md`'s "Fulfillment status and results" named
        `replace-polling-with-authenticated-push` as planned work. It now states the
        current fact, that provisioning does not notify the storefront of results, and
        names no change; and a garbled clause about the job-backed provider reads
        correctly.
      - Section-record anchors renamed or removed by later archived changes are
        mapped to current headings in the closeout record.
- [x] 13.4 **Narrative compression.** Compress completed-task notes to final behavior,
      material validation evidence, unresolved or deferred work, and
      permanent-documentation destinations, moving durable rationale into `design.md`
      first.
      **Done (2026-10-27).** Sections 1–12 notes shortened, from 309 KB to 237 KB.
      Removed: interim statuses later overtaken, interim test counts, file-path
      recitals, and fix-loop narratives. Kept: task statements, final evidence,
      12.4's scenario-to-test mapping and 12.5 in full, and every correction recording
      that a task was marked done without meeting its criteria (4.7.4, 4.7.5, 4.11.3,
      9.3, 9.7, 10.10–10.12) or a gate was not honoured (8.15). Rationale not already in
      `design.md` moved to its "Rationale moved from task notes at closeout" section
      (4.2.3, 4.5.2, 4.6, 4.7.2, 4.11.5, 4.15.3, Section 4's comment fixes, 9.0, 9.2,
      9.3, 9.7, 10.3, 10.4, 10.6, 10.7, 10.8, 10.14, 11.17). Section 11 was already
      compressed by 11.18.3 and was only trimmed.
- [x] 13.5 **Roadmap currency.** Update the affected goal's current state and gap
      mapping in `docs/development/ROADMAP.md`, or record that no goal is affected.
      This change sits under the lesser goal "POOLS capacity and fulfillment
      foundation", which has no roadmap goal behind it, so it most likely owes the
      roadmap nothing; confirm that and record the no-impact disposition explicitly.
      **No goal affected (2026-10-27).** No roadmap goal names this change or maps a
      gap to it. Goal 1's current state already says the provisioning service is
      authoritative for scheduling and the fulfillment lifecycle, which this change
      made true. `ROADMAP.md` is unchanged.
- [x] 13.6 **Campaign index currency.** Update this change's row, and its campaign's
      dependency graph, in `openspec/changes/README.md`, or record that both are
      unchanged. Other rows' `Depends on` are left alone: archive cleanup releases
      dependents after the closeout gate.
      **Done (2026-10-27).** The row is `in closeout`, its notes rewritten for
      closeout, and after 13.11 it links the archived directory. The POOLS campaign
      graph is unchanged. `pools-6-fair-scheduling-policy`,
      `replace-polling-with-authenticated-push`, and
      `market-platform-compute-40-multi-domain-proof` keep this change in `Depends on`
      until archive cleanup. `make check-change-index` passes.
- [x] 13.7 **Packaging.** Run `make check-packaging` and resolve every failure it
      reports (a failure needing a code or lock change returns the change to
      implementation).
      **Passed (2026-10-27).** `make check-packaging`: every lock, install, Python
      version, layer, scope, dependency and kind rule holds.
      `make check-architecture-change`: the change owns no architecture row. The last
      rounds touched no `.agents/`, `.claude/` or `.codex/` path, so
      `make check-agent-skills` was not owed; `make check-change` runs it and passes.
- [x] 13.8 **End-to-end pipeline.** Record the passing run the latest validation names,
      its result, and the scenarios that exercise this change, or an explicit blocker
      naming its cause and the change that owns it, with the validations it gates
      treated as unrun. Validations 03 (run 40495699817, `02319877e`) and 08 (run
      40505352410, `cdb244466`) passed, with `test_full_deal` stages 00 to 11b on the
      VM lane. Closeout records the run of the latest validation, which must name
      `HEAD` or an ancestor from which `HEAD` changes only `openspec/` and `docs/`.
      **Recorded (2026-10-27).** Validation 27 (`reviews/27-validation.md`) passed
      every part at `a6376b8bc`, the pre-closeout commit. `HEAD` before closeout,
      `c9b2a96e1`, changes only `openspec/` paths from it, and closeout changes only
      `openspec/` and `docs/`, so the run describes the code this commit carries.
      - Pipeline run 40534579682, success:
        - `e2e-vm`: 134 passed, 162 deselected. `e2e_deal`'s `test_full_deal` stages
          00 to 11b exercise scheduling, durable fulfillment, pulled credentials, the
          lease cycle's `fulfillment_id`, convergence teardown with capacity held, and
          release on teardown.
        - `e2e-bare-metal`: 51 passed, 3 skipped. It runs the same provisioning
          service.
        - `e2e-apicredits`: 1 passed, 3 skipped; `e2e_credits_deal` covers the
          storefront startup's seed-quota registration.
        - The skips are the payment-deal tests, for want of a payments target, and are
          not evidence for this change.
      - Helm: the scenario pod exited 0. Local `check-packaging` and `make test`
        passed.
      - CI: no section owed a workflow observation (`ci not owed`).
- [x] 13.9 **Promotion.** Write the permanent documents this change owes — those
      12.1–12.3 and the section design-promotion records name — and complete the
      design-promotion record, mapping every accepted decision to its exact permanent
      heading, and verify no production source references
      `openspec/changes/pools-7-storefront-fulfillment-cutover`. A `spec.md` the deltas cover
      (`physical-provisioning`, `site-capacity`, `vm-storefront-fulfillment`) is written
      by the archive in 13.11, not by hand; the record names it all the same, and 13.11
      checks the merged text of each.
      *Superseded decisions (2026-10-05, `bare-metal-mock-provisioned-deal` 5B.8):*
      - Do not promote the following as current behaviour; record each as superseded by
        that change instead:
        - the VM-branded lease surface (`/api/v1/leases`, its `PATCH` update, and the
          by-escrow lookup) and bare metal's lease surface;
        - per-offering-mode release executors and their dispatchers;
        - `offering_mode` on lease registration.
      - The replacements: one family lease surface keyed by reservation id, release
        decided by the fulfillment aggregate's state through a site-side release guard,
        and registration written once by executor target.
      - This change's own delta specs (atomic abandonment and release, scheduling,
        fulfillment identity) remain compatible and promote as written.
        *Amended 2026-10-27 (task 12.4):* they promote as reconciled in 12.4.
        `credential_generation` is gone, and "Capacity schema separation" replaces
        "Broad capacity schema cleanup".
      **Done (2026-10-27).** The permanent documents 12.1–12.3 named were written
      then. Closeout edited `docs/development/ARCHITECTURE.md`'s "Fulfillment status
      and results" (13.3). `openspec/specs/README.md` lacked a row for
      `vm-storefront-fulfillment`; the closeout triage added it (35 F1). `design.md`'s "Closeout design-promotion
      record" maps every accepted decision to a heading that resolves, and records the
      three superseded decisions above as superseded by `bare-metal-mock-provisioned-deal`,
      with the current requirements that replace them. No file outside
      `openspec/changes/` names this change. The deltas merge at archive (13.11): the
      14 ADDED requirements appear in no permanent spec, and the two MODIFIED
      requirements, "Ansible fulfillment adapter" and "The storefront does not select
      buyer access infrastructure", exist under those headings; so the archive runs
      without `--skip-specs`.
- [x] 13.10 **Documentation citations.** After promotion, run
      `make check-doc-citations CHANGE=pools-7-storefront-fulfillment-cutover` and resolve every
      match, then `openspec validate pools-7-storefront-fulfillment-cutover --strict`.
      **Passed (2026-10-27).** `make check-change` after promotion: comment hygiene,
      agent skills, documentation citations, task list, change index, and strict
      `openspec validate` with the pinned validator all pass. The citations check
      tests paths only; the heading anchors in the closeout promotion record were
      checked against each target's headings and explicit anchors by hand.
- [x] 13.11 **Archival.** Last, once every other part is checked: `openspec archive
      pools-7-storefront-fulfillment-cutover -y` merges the deltas into `openspec/specs/` and
      moves the change under `openspec/changes/archive/`; point the index row at the
      archived directory, and run `openspec validate --specs --strict`.
      **Done (2026-10-27).** `openspec archive -y` with the pinned 1.14.0 validator,
      without `--skip-specs` (13.9), moved the change to
      `openspec/changes/archive/2026-10-27-pools-7-storefront-fulfillment-cutover/`
      and merged 14 added and 2 modified requirements: 11 added and "Ansible
      fulfillment adapter" modified in `physical-provisioning/spec.md`, 3 added in
      `site-capacity/spec.md`, and "The storefront does not select buyer access
      infrastructure" modified in `vm-storefront-fulfillment/spec.md`. The diff of
      each was read: every requirement appears once, as its delta stated, and nothing
      else changed. The index row links the archived directory and stays `in
      closeout` until archive cleanup. `make check-change` on the archived change,
      which runs `openspec validate --specs --strict`, passes.
