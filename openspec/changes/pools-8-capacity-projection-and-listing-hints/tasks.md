## 1. Reconcile landed projection foundations

- [x] 1.1 Verify independent site resource-pool and capacity-bucket producers, revisions/digests, pull endpoints, and in-memory storefront caches landed under POOLS-7.
- [x] 1.2 Remove rebuilt producer/polling/cache mechanics from this change and record remaining persistence/consumption scope in `proposal.md` and `design.md`.
- [ ] 1.3 Resolve global versus site-scoped Resource Pool identity and record the durable/public key shape before schema work.
- [ ] 1.4 Inventory every `resources`, capacity-pool, CSV import, validator, publication, claim-building, admin, migration, and e2e reader; classify physical authority versus commercial/operational ownership.

## 2. Persist projection generations

- [ ] 2.1 Add storefront migrations and repositories for trusted configured-site bindings and independent resource-pool/capacity-bucket generations.
- [ ] 2.2 Persist revision, digest, accepted value, fetched time, and stale/error state transactionally per `(site_id, projection_kind)`.
- [ ] 2.3 Load complete stored generations as stale on restart before polling and replace one family without mutating the other.
- [ ] 2.4 Add migration, restart, partial-refresh, malformed-payload, revision-reset, and stale-retention tests.

## 3. Project safe pool metadata

- [ ] 3.1 Define allowlisted pool label, enabled state, mechanism reference, and opaque policy-tag fields in the site resource-pool projection.
- [ ] 3.2 Advance revision/digest on projected metadata changes and prove credentials/provider secrets are redacted.
- [ ] 3.3 Preserve backward compatibility when older producers omit additive metadata.
- [ ] 3.4 Add producer/router/client/cache contract tests for old and new payloads.
- [ ] 3.5 Project the pool's configured VM size defaults (`default_vm_ram`, `default_vm_vcpus`, `default_vm_disk_size` -- `AnsiblePoolConfig`, currently persisted provisioning-service-side with no consumer outside the fulfillment-time three-tier precedence) as additive, allowlisted pool metadata, so a storefront can resolve a full four-dimension shape (GPU/vCPU/RAM/disk) at negotiation time instead of only GPU count. This is the identified prerequisite for negotiation round-0 payload enrichment (see `openspec/changes/negotiation-driven-capacity-resize`, opened 2026-07-29); that change's storefront-side consumption is explicitly out of scope here and depends on this projection existing first.

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
