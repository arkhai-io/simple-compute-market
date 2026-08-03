## 1. Reconcile landed projection foundations

- [x] 1.1 Verify independent site resource-pool and capacity-bucket producers, revisions/digests, pull endpoints, and in-memory storefront caches landed under POOLS-7.
- [x] 1.2 Remove rebuilt producer/polling/cache mechanics from this change and record remaining persistence/consumption scope in `proposal.md` and `design.md`.
- [x] 1.3 Resolve global versus site-scoped Resource Pool identity and record the durable/public key shape before schema work. **Resolved (2026-08-03, `design.md`, "Resolved Questions"): `pool_id` is a site-local operator slug, never made globally unique under POOLS-7. Every durable/public reference this change introduces must key on `(site_id, pool_id[, resource_id])`, never `pool_id` alone.**
- [x] 1.4 Inventory every `resources`, capacity-pool, CSV import, validator, publication, claim-building, admin, migration, and e2e reader; classify physical authority versus commercial/operational ownership. **Done (2026-08-03, `design.md`, "Local physical-authority inventory"): all eight tables classified; writers, readers, and the two independent listing-creation paths (operator/API-driven vs. CLI/reconciler-derived) traced; migration and e2e readers confirmed absent. One caveat carried forward: `compute_capacity_pools`/`compute_pool_members` show no external reader in this pass but were not checked against every admin response schema, so their zero-consumer status should be reconfirmed before Section 6 plans their removal.**

## 2. Surface per-site projection load state (revised 2026-08-03; no persistence layer)

**Revised in discussion 2026-08-03** (`design.md`, "Section 2 revised decision"): the originally planned durable persistence layer (migrations, repositories, seeded-cache restart recovery — old tasks 2.1–2.4, struck through below and kept for history per this repository's amend-don't-replace convention) is not being built. No production code consumes the projection caches yet, so the restart-time gap it targeted has no live consumer to protect; the one concrete operational need (the single-site e2e/Helm deployment, where the storefront may start before its site is reachable) is fully covered by the existing indefinite-retry poller plus observable status.

- [ ] 2.1 Add per-`(site_id, projection_kind)` load-state fields (`ProjectionState`, last-fetched time, last error) to the storefront's existing operator status surface (`system_service.get_health`/`/api/v1/system/status`), following the existing `resource_count`-diagnostic pattern rather than inventing new blocking/gating behavior. Report per site — one site's failure to load must not present as global degradation when other configured sites are healthy.
- [ ] 2.2 Confirm `site_projection_poller_loop` already retries indefinitely on a site that has never successfully loaded (not only on a previously-successful cache going stale), and add a test if this exact "never yet loaded" retry path is not already covered.
- [ ] 2.3 Document the "ignorance ≠ zero" requirement on Section 4's future projection consumer: `not_loaded`/`invalid`/`unavailable` states MUST NOT be treated as authoritative empty capacity. Promoted directly into `openspec/specs/site-capacity/spec.md` (see delta spec, "Per-site projection load-state visibility") so Section 4 planning inherits the constraint rather than rediscovering it.
- [ ] 2.4 Add focused tests: per-site/family status reporting reflects each `ProjectionState` correctly; one site's `unavailable` state does not affect another configured site's reported state; status reporting requires no new schema/migration (regression guard against silently reintroducing persistence).
- [ ] 2.5 Small follow-up, not blocking: confirm whether POOLS-7 task 2.3's "storefront-side connection-to-site identity ... process-local aggregation state" durability note is already satisfied by `AggregateCapacityClient._reservation_sites`'s existing documented cache-with-fallback design (`design.md`, "Related finding" under the revised decision) — likely a documentation-only closure against POOLS-7 rather than new work here; confirm scope before doing anything.

<details>
<summary>Original tasks 2.1–2.4 (persistence layer), superseded — kept for history</summary>

- [ ] ~~2.1 Add storefront migrations and repositories for trusted configured-site bindings and independent resource-pool/capacity-bucket generations.~~
- [ ] ~~2.2 Persist revision, digest, accepted value, fetched time, and stale/error state transactionally per `(site_id, projection_kind)`.~~
- [ ] ~~2.3 Load complete stored generations as stale on restart before polling and replace one family without mutating the other.~~
- [ ] ~~2.4 Add migration, restart, partial-refresh, malformed-payload, revision-reset, and stale-retention tests.~~

</details>

## 3. Project safe pool metadata

- [ ] 3.1 Define allowlisted pool label, enabled state, mechanism reference, opaque policy-tag fields, and a generic `pool_views: dict[str, Any]` field in the site resource-pool projection, mirroring the existing `publication_views` precedent (resource-level, same file) rather than adding any provider-shaped key names directly. `kit/site` must not know what any `pool_views` entry contains.
- [ ] 3.2 Advance revision/digest on projected metadata changes and prove credentials/provider secrets are redacted.
- [ ] 3.3 Preserve backward compatibility when older producers omit additive metadata.
- [ ] 3.4 Add producer/router/client/cache contract tests for old and new payloads.
- [ ] 3.5 Project the pool's configured VM size defaults (`default_vm_ram`, `default_vm_vcpus`, `default_vm_disk_size` -- `AnsiblePoolConfig`) as a versioned `vm.ansible_pool_defaults.v1` entry inside the additive, allowlisted, generic `pool_views` field (task 3.1) — not a flat VM-shaped key at the top level of pool metadata (`design.md`, "Resolved: `pool_views`, mirroring the existing `publication_views` precedent") — so a storefront can resolve a full four-dimension shape (GPU/vCPU/RAM/disk) at negotiation time instead of only GPU count. The shaping function lives in `vm_provisioning_adapter`'s own runtime module, matching how `project_bare_metal_resource` already builds the `bare_metal.v1` resource-level view from the bare-metal domain package rather than inline in `compute_provisioning_service`. **Correction (2026-08-03, matches `proposal.md`):** these fields are not currently persisted anywhere — they exist only on the fulfillment-time pydantic `AnsiblePoolConfig` model and are unreachable in practice because `AnsiblePoolConfigHandler`'s field allowlist rejects them if an operator tries to set them via the pool admin API. This task must add real persistence (schema column + handler wiring, following the existing `_migrate_ansible_jobs_contract_fields`-style additive-column migration pattern in `provisioning/compute/service/db/migrations.py`) as a prerequisite before there is anything to project. This is the identified prerequisite for negotiation round-0 payload enrichment (see `openspec/changes/negotiation-driven-capacity-resize`, opened 2026-07-29); that change's storefront-side consumption is explicitly out of scope here and depends on this projection existing first.

## 4. Map projections into commercial inventory

- [ ] 4.1 Choose and migrate the commercial overlay/mapping schema for `(site_id, pool_id, resource_id?)` to storefront listing/pricing/settlement state.
- [ ] 4.2 Backfill unambiguous current rows and quarantine ambiguous or unsupported local physical identities without deleting agreement history.
- [ ] 4.3 Reconcile complete projection generations into mapped publication candidates and close listings whose physical support disappears.
- [ ] 4.4 Switch VM claim construction to mapped projected identity and direct selected-site routing; add parity diagnostics before removing the old reader.
- [ ] 4.5 Add equivalent mapping/claim seams required by the bare-metal storefront without importing bare-metal models into core.
- [ ] 4.6 Prove projections never participate in live admission, assignment, or provider dispatch decisions.

## 5. Implement advisory hints

- [ ] 5.1 Define `listing_mode` and `max_reservation_hold_seconds` key constants and nonnegative hold validation in `kit/resource-pools`.
- [ ] 5.2 Add VM and bare-metal listing-mode enums/resolvers with structural defaults and operator-visible invalid-value explanations.
- [ ] 5.3 Add API-credit hint interpretation only if a concrete publication consumer exists; otherwise prove unknown values remain opaque and defer its enum.
- [ ] 5.4 Cap storefront acceptance-hold TTL by a valid projected preference without changing site-ledger admission rules.
- [ ] 5.5 Add focused domain resolver, unknown-tag, invalid-hold, old-producer, and non-cooperating-consumer tests.

## 6. Retire superseded local physical authority

- [ ] 6.1 Remove only physical-identity writers/readers proven replaced by projection mapping, including `resource_capacity_validator.py` if its final caller is gone.
- [ ] 6.2 Preserve pricing, accepted settlement mechanisms, negotiation/agreement history, transition idempotency, and operator metadata in explicitly owned storage.
- [ ] 6.3 Add compatibility diagnostics/migrations for existing deployments and a rollback path to the previous reader during staged rollout.
- [ ] 6.4 Run storefront unit/integration, publication, multi-site capacity, API-credit/bare-metal affected, migration, packaging, and e2e suites.

## 7. Permanent documentation promotion

- [ ] 7.1 Promote durable projection-generation and safe metadata contracts to `openspec/specs/site-capacity/spec.md` and `architecture.md`.
- [ ] 7.2 Promote commercial mapping, direct claim routing, and retirement boundaries to `openspec/specs/storefront-publication/spec.md` and `architecture.md`.
- [ ] 7.3 Promote domain-neutral hint keys and domain-owned values to `openspec/specs/resource-pool-management/spec.md` and `architecture.md`.
- [ ] 7.4 Update `docs/development/ARCHITECTURE.md` only if the accepted design changes repository-wide authority/topology, record all destinations in `design.md`, and run strict validation before archive.
