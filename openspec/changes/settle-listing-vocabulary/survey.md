# Survey — settle the listing vocabulary

Output of tasks 1.1 through 1.6, published before editing. Counts exclude
`openspec/changes/` (this change's own documents and the downstream change documents
handled in section 7) and are full-identifier matches, per 1.1a.

## Retired-name inventory (1.1)

| Identifier | Occurrences | Files | Boundary class (1.2, 1.3) |
|---|---:|---:|---|
| `listing_mode` | 64 | 19 | Optional projected key; **keeps ingestion alias** |
| `LISTING_MODE_POLICY_TAG` | 7 | 2 | Internal (kit constant) |
| `raw_listing_mode` | 9 | 3 | Internal (kit reader) |
| `resolve_vm_listing_mode` | 17 | 6 | Internal (domain resolver) |
| `listing_mode_explanation` | 8 | 2 | Internal (reconciler row key) |
| `listing_mode_explanations` | 22 | 7 | **Admin-gated HTTP response field** |
| `executor_kind` | 648 | 103 | **Required claim wire + provisioning contract** |
| `EXECUTOR_KIND_CLAIM_KEY` | 6 | 2 | Internal (claim key constant) |
| `VM_EXECUTOR_KIND` | 39 | 6 | Internal |
| `_VM_EXECUTOR_KIND` | 7 | 3 | Internal |
| `offer_resource` | 473 | 137 | **Published listing shape + three filter specs + two columns** |
| `offer_resource_type` | 15 | 6 | Cosmetic response field; **dropped, not renamed** |
| `virtualization_type` | 86 | 53 | **Optional published field + filter + CLI flag** |
| `VirtualizationType` | 10 | 4 | Internal type name → `OfferingMode` |
| `offering_type` | 1 | 1 | Proposed only (`ROADMAP.md` prose) |

`offering_type` exists in exactly one place and it is documentation, not code. The
fourth name was never implemented; section 7.2 stops it from being.

## Grep-hazard measurements (1.1a)

Each hazard is measured rather than asserted, because the audit in 9.16 asserts zero
and a prefix search cannot reach it.

| Search | Prefix hits | Full-identifier hits | Over-report |
|---|---:|---:|---|
| `listing_mode` (`.py`) | 146 | 54 | 2.7× — absorbs `listing_model` (13) and `listing_mode_explanation(s)` |
| `vms.compute` | 35 | 33 | absorbs `arkhai_vms.compute_requirements` (2) |
| `offer` (bare word, `.py`) | 347 | n/a | matches `offer_resource` **and** the replacement `offering_mode` |

The `offer` row is the reason 9.16 audits `offer_resource` and the published-shape
attribute names specifically, rather than the bare word: searching `offer` reports
the settled vocabulary as if it were retired.

## The two uses of `vms.compute` (1.1b)

Not one name. Renaming both would change frozen binding identity.

| Use | Value | Disposition |
|---|---|---|
| Registry schema identity (`schema.id`, `VMS_SCHEMA_ID`) | `vms.compute` | → `compute.market` (5.1) |
| Domain identity in `e2e-tests` fixtures (`domain_identity=`) | `vms.compute` | **Leave.** Different axis |

The production domain identity is `compute.v1` (`VM_PROVISION_KIND` in
`domains/vms/domain/src/arkhai_vms/provision_terms.py`), and the durable listing
binding freezes it. The `e2e-tests` fixtures carrying `vms.compute` as a
`domain_identity` are therefore already inconsistent with production; that is
out of scope here and must not be swept into 5.1.

## Persisted uses (1.5)

Two kinds. A row backfill cannot touch a column name, and a column rename cannot
touch a key inside a payload.

### Column names — three renames, three databases, three frameworks

| Column | Database | Framework | Task |
|---|---|---|---|
| `capacity_reservations.executor_kind` | Compute provisioning service | `Migration("YYYYMMDD_NNN_…")`, latest `20260901_001_relay_reachable_hosts` | 6b.1 |
| `listings.offer_resource` | Registry | Alembic, latest `017_publisher_replay_leases` | 6b.1b |
| `listings.offer_resource` | Storefront (shared by both compute domains) | `core_storefront.sqlite_migrations`, latest `20260815_001_storefront_domain_bindings` | 6b.1c |

### Keys inside payloads — two backfills

| Key | Column | Why it cannot be left | Task |
|---|---|---|---|
| `executor_kind` | `settlement_records.scheduling_requirements` (`Column(JSON)`) | `settlement_repository._scheduling_matches` compares the stored dict structurally for settlement idempotency | 6b.2 |
| `virtualization_type` | Storefront `listings.offer_resource` payload | Written today by bare metal's `_migrate_common_domain_bindings`; read back by `listing_service` as the offering mode | 6b.3 |

## Retained `executor_` compounds (1.6)

Correct by the head-noun rule in `design.md` and
`openspec/specs/physical-provisioning/spec.md`. **Not pending work.** An auditor
dismisses these by rule rather than re-deriving the judgement per site.

| Name | Possessive reading |
|---|---|
| `executor_ref` | the executor's reference — where the abstraction locates what it acts on |
| `executor_target` | the target of an executor action |
| `ExecutorActionEnvelope` | an envelope for an executor action |
| `ExecutorAdapter`, `ExecutorAdapterRegistry` | the abstraction itself |
| `ExecutorLeaseService`, `ExecutorLeaseRegistration`, `ExecutorLeaseUpdate` | leases over executor actions |
| `UnsupportedExecutorActionError`, `ExecutorMismatchError` | errors of the abstraction |

Renaming these on a prefix match would touch roughly 300 further sites
(`executor_ref` 173, `executor_target` 126) across `kit/site`, both provisioning
adapters, and the bare-metal lease and release paths.

Contrast `executor_kind`: no possessive reading rescues it, because the kind of
executor simply *is* the mode. That is why it is the one compound that moves.

## Affected-capability inventory (1.4)

Every capability below has a delta in `specs/`. Task 8.6's assertion is only
meetable because this list is complete; a capability appearing here without a delta
is a stop condition, not something to narrow the assertion around.

| Capability | Why affected |
|---|---|
| `storefront-publication` | Cardinality hint scope; published shape and its offering-mode field |
| `registry-discovery` | Schema identity; listing shape key; offering-mode field and filter |
| `site-capacity` | The capacity claim's offering-mode field |
| `resource-pool-management` | Names the cardinality hint normatively |
| `physical-provisioning` | Release lookup and executor-adapter selection; the head-noun rule |
| `deployment-state` | Selects the compute filter specification by schema identity |
| `compute-provisioning-contract` | Seven versioned models carry the mode field |

`storefront-publication` also owns an architecture companion
(`architecture.md`) that names the published field; OpenSpec does not synchronize
companions, so 8.4 names it explicitly.

## Discovered during survey, not anticipated by the plan

**The cardinality resolver module is force-included into two wheels.** Renaming
`domains/vms/listings/listing_mode.py` requires updating the
`[tool.hatch.build.targets.wheel.force-include]` mapping in both
`domains/vms/buyer/pyproject.toml` and `domains/vms/storefront/pyproject.toml`.
Without it the module is absent from the built wheel and the failure appears at
install time rather than at test time, since the sibling path still resolves in a
source checkout. Task 4.6 is amended to name these two files.
