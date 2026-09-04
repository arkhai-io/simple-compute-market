## 1. Canonical registry URL

- [ ] 1.1 Inventory registry host/port/URL construction, wait probes, auth-key maps, Helm values, Compose, e2e, and operator overlays.
- [ ] 1.2 Select the canonical full URL value and define normalization plus bounded legacy host/port compatibility in `design.md`.
- [ ] 1.3 Update storefront runtime, wait initialization, publication, health, and auth lookup to consume one normalized URL.
- [ ] 1.4 Add focused TLS, path-prefix, trailing-slash, legacy-value, and conflicting-value tests.

## 2. Explicit deployment profiles

- [ ] 2.1 Default base/provider values to `registry.enabled=false` without synthesizing the in-release service URL.
- [ ] 2.2 Add explicit marketplace-operator, local development, and e2e overlays that enable the embedded registry and set its canonical URL.
- [ ] 2.3 Ensure disabled registry emits no Deployment, Service, PVC, migration job, wait target, or unresolved service reference.
- [ ] 2.4 Add Helm render tests for external provider, embedded operator, and each disabled/enabled role combination affected.

## 3. Compatibility and verification

- [ ] 3.1 Add actionable diagnostics for installations relying on implicit embedded behavior and document the explicit compatibility profile.
- [ ] 3.2 Run storefront config/startup/publication suites, Helm structural tests, local/e2e profile validation, and packaging checks.

## 4. Permanent promotion

- [ ] 4.1 Promote topology/default/URL behavior to `openspec/specs/deployment-state/spec.md` and rationale to `architecture.md`.
- [ ] 4.2 Update the role map in `docs/development/ARCHITECTURE.md` and operator-facing deployment values without duplicating generated resource inventories.
- [ ] 4.3 Record promotion in `design.md`, run strict validation, and archive before beginning the PostgreSQL rollout.

## 5. Closeout

Per `openspec/README.md#plan-closeout-requirements`.

- [ ] 5.1 **Comment hygiene.** Run `make check-comment-hygiene`, then direct-read the comments and docstrings this change touches for the fuzzier provenance-narration rule the target cannot catch mechanically.
- [ ] 5.2 **Import placement.** Review every import this change adds or touches and move it to module level where safe; retain a local import only against an observed circular import or a documented lazy-load reason, verified against the real suite.
- [ ] 5.3 **Documentation compliance.** Re-check this change's accepted decisions against `openspec/README.md`'s placement rules. It carries delta specs for `deployment-state`; confirm each landed in the owning `openspec/specs/<capability>/spec.md`, and that durable conceptual rationale sits in the companion `architecture.md` rather than only in `design.md`.
- [ ] 5.4 **Narrative compression.** Compress completed-task notes to final behavior, material validation evidence, unresolved or deferred work, and permanent-documentation destinations, moving durable rationale into `design.md` first.
- [ ] 5.5 **Roadmap currency.** This change sits under the lesser goal “Registry productionization”, which has no roadmap goal behind it, so it most likely owes `docs/development/ROADMAP.md` nothing. Confirm that and record the no-impact disposition explicitly rather than omitting the step.
- [ ] 5.6 **Campaign index currency.** Update this change's row, and its campaign's dependency graph, in `openspec/changes/README.md` to match its state at completion, or record the disposition here if its status and campaign placement are both unchanged.
- [ ] 5.7 **Promotion.** Add a design-promotion record, mapping every accepted decision to its exact permanent heading, and verify no production source references `openspec/changes/separate-marketplace-registry`.
