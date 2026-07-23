## 1. Inventory and Classification

- [x] 1.1 Create the migration ledger schema with source reference, classification, destination, disposition rationale, evidence, and verification fields
- [x] 1.2 Inventory every heading and subheading in `ARCHITECTURE.md`, `TODO.md`, `design-remaining-work.md`, and `provisioning-migration-plan.md`
- [x] 1.3 Scan tracked repository-owned files for actionable TODO/FIXME markers using explicit generated, vendored, lock, migration-history, and OpenSpec archive exclusions
- [x] 1.4 Inventory repository links into the four legacy planning documents so redirects and destination links can be verified at cutover
- [x] 1.5 Classify every ledger entry as current behavior, proposed work, implemented history, operational guidance, deferred/conditional, duplicate, stale, or unresolved
- [x] 1.6 Record the source revision and reconcile contradictory or overlapping entries before writing destination artifacts

## 2. OpenSpec Project Configuration

- [x] 2.1 Add concise repository context to `openspec/config.yaml` covering architecture vocabulary, dependency direction, plugin boundaries, tooling, and focused verification
- [x] 2.2 Add artifact rules for proposal non-goals/capabilities, observable spec scenarios, compatibility-aware designs, and behavior-first task verification
- [x] 2.3 Verify the configured OpenSpec instructions expose the intended context and rules without embedding the legacy architecture document

## 3. Current-State Capability Specs

- [x] 3.1 Finalize the durable capability map and map every current-state ledger entry to exactly one owning capability or an explicit cross-capability reference
- [x] 3.2 Create and validate baseline specs for market composition, package boundaries, and role/plugin ownership using code and architecture-boundary tests as evidence
- [x] 3.3 Create and validate baseline specs for registry discovery, filter-spec behavior, publisher identity, and client compatibility
- [x] 3.4 Create and validate baseline specs for synchronous negotiation, deterministic terms derivation, policy hooks, and persisted protocol state
- [x] 3.5 Create and validate baseline specs for settlement plans, servicing, claims, heartbeats, and mechanism codecs
- [x] 3.6 Create and validate baseline specs for storefront publication, listing lifecycle, and domain runtime composition
- [x] 3.7 Create and validate baseline specs for site capacity, reservation semantics, event delivery, and multi-site aggregation
- [x] 3.8 Create and validate baseline specs for physical provisioning, scheduling, fulfillment providers, allocations, and lease lifecycle
- [x] 3.9 Create and validate baseline specs for buyer orchestration, domain plugins, aggregation, and run recovery
- [x] 3.10 Create and validate baseline specs for deployment topology, schema migration behavior, testing levels, and compatibility contracts
- [x] 3.11 Resolve or explicitly block every architecture claim that conflicts with code before marking the baseline complete

## 4. Pending and Historical Changes

- [x] 4.1 Define the normalized active-change catalog by splitting compound legacy programs at independent acceptance and archive boundaries
- [x] 4.2 Create linked changes for database migration execution/schema guards and registry Postgres rollout, preserving the external infrastructure dependency
- [x] 4.3 Split the market-core follow-ons into settlement-plan shapes, multi-domain capacity proof, storefront-client wire genericization, buyer residue, and publishing setup changes
- [x] 4.4 Create independent changes for gradual core typing, native provisioning launch, path-source removal, storefront DB pruning, and shared Dynaconf bootstrap
- [x] 4.5 Preserve filter side indexes, e2e extraction, and conditional client extraction with explicit activation conditions rather than implementation-ready status
- [x] 4.6 Create deployment and operator changes for shared marketplace registry topology, golden-image configuration, and any actionable documentation gaps
- [x] 4.7 Normalize site-resource lifecycle, host accounting, spot automation, and remaining provisioning migration work against the baseline specs without retaining landed tasks
- [x] 4.8 Reconcile POOLS-1 through POOLS-6 individually, moving landed behavior to specs/history and retaining only evidence-backed unfinished deltas
- [x] 4.9 Convert actionable inline markers into new changes or tasks on existing changes, and document the disposition of every excluded or stale marker
- [x] 4.10 Create archived changes only where completed design history remains useful; record ledger-only history for obsolete implementation sequencing
- [x] 4.11 Validate every active and archived change and ensure deferred, conditional, blocked, and unresolved states are explicit

## 5. Coverage Verification

- [x] 5.1 Verify every migration ledger row has one exact destination or an evidence-backed removal rationale
- [x] 5.2 Verify every destination spec requirement and change traces back to source material or newly documented code evidence
- [x] 5.3 Run OpenSpec validation across all baseline specs and created changes and resolve every error
- [x] 5.4 Run a final delta scan for headings, links, and TODO/FIXME markers added or changed since the recorded source revision
- [x] 5.5 Review the resulting capability and change indexes for discoverability, duplicate ownership, and oversized artifacts

## 6. Cutover and Documentation Cleanup

- [x] 6.1 Replace the monolithic architecture reference with a concise non-normative overview linking to capability specs and retained operational documentation
- [x] 6.2 Remove the flat TODO backlog after all active, deferred, conditional, implemented, and unresolved entries have verified destinations
- [x] 6.3 Remove or reduce `design-remaining-work.md` and `provisioning-migration-plan.md` after their decisions, deltas, and history are covered
- [x] 6.4 Update all inventoried repository links and contributor/AI entry points to the canonical OpenSpec artifacts
- [x] 6.5 Run focused documentation link checks, OpenSpec validation, and the reconciled TODO/FIXME scan against the cutover tree
- [x] 6.6 Archive `migrate-planning-to-openspec` only after the lossless-cutover scenarios pass and no legacy file remains a competing normative source
