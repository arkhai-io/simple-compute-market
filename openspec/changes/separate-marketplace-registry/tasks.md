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

- [x] 4.1 **Withdrawn** 2026-10-14: closeout does this — 5.9 writes the architecture companion by hand, and the archive in 5.11 writes the `deployment-state` spec its delta covers. As first planned: Promote topology/default/URL behavior to `openspec/specs/deployment-state/spec.md` and rationale to `architecture.md`.
- [ ] 4.2 Update the role map in `docs/development/ARCHITECTURE.md` and operator-facing deployment values without duplicating generated resource inventories.
- [x] 4.3 **Withdrawn** 2026-10-14: closeout does this — 5.9 records the promotion, 5.10 validates, and 5.11 archives, still before the PostgreSQL rollout begins. As first planned: Record promotion in `design.md`, run strict validation, and archive before beginning the PostgreSQL rollout.
- [ ] 4.4 **Comment hygiene and import placement, before the pre-closeout review.** Run `make check-comment-hygiene` and read the comments this change added for any that narrate the review or migration that introduced them; move each import the change added to module level unless a verified circular import or a recorded lazy-load reason keeps it local. Closeout only confirms both.

## 5. Closeout

Per `openspec/README.md#plan-closeout-requirements`.

- [ ] 5.1 **Comment hygiene — confirm.** Run `make check-comment-hygiene`, and read the comments this change added for any that narrate the review or migration that introduced them. Do not edit code here: anything to rewrite returns the change to implementation.
- [ ] 5.2 **Import placement — confirm.** Check the imports this change added for any still local without a recorded reason. One that should move returns the change to implementation.
- [ ] 5.3 **Documentation compliance.** Re-check this change's accepted decisions against `openspec/README.md`'s placement rules, and the permanent documents against the code they describe. Durable conceptual rationale for the `deployment-state` topology sits in its companion `architecture.md` rather than only in `design.md`.
- [ ] 5.4 **Narrative compression.** Compress completed-task notes to final behavior, material validation evidence, unresolved or deferred work, and permanent-documentation destinations, moving durable rationale into `design.md` first.
- [ ] 5.5 **Roadmap currency.** Update the affected goal's current state and gap mapping in `docs/development/ROADMAP.md`, or record that no goal is affected. This change sits under the lesser goal “Registry productionization”, which has no roadmap goal behind it, so it most likely owes the roadmap nothing; confirm that and record the no-impact disposition explicitly.
- [ ] 5.6 **Campaign index currency.** Update this change's row, and its campaign's dependency graph, in `openspec/changes/README.md`, or record that both are unchanged. Other rows' `Depends on` are left alone: archive cleanup releases dependents after the closeout gate.
- [ ] 5.7 **Packaging.** Run `make check-packaging` and resolve every failure it reports (a failure needing a code or lock change returns the change to implementation).
- [ ] 5.8 **End-to-end pipeline.** Record the passing run the latest validation names, its result, and the scenarios that exercise this change, or an explicit blocker naming its cause and the change that owns it, with the validations it gates treated as unrun.
- [ ] 5.9 **Promotion.** Write the permanent documents this change owes — `openspec/specs/deployment-state/architecture.md` (topology, default, and URL rationale), the role map in `docs/development/ARCHITECTURE.md`, and the operator-facing deployment values documentation, without duplicating generated resource inventories — and complete the design-promotion record, mapping every accepted decision to its exact permanent heading; verify no production source references this change's directory. A `spec.md` the deltas cover (`openspec/specs/deployment-state/spec.md`) is written by the archive in 5.11, not by hand; the record names it all the same.
- [ ] 5.10 **Documentation citations.** After promotion, run `make check-doc-citations CHANGE=separate-marketplace-registry` and resolve every match, then `openspec validate separate-marketplace-registry --strict`.
- [ ] 5.11 **Archival.** Last, once every other part is checked, and before the PostgreSQL rollout begins: `openspec archive separate-marketplace-registry -y` merges the deltas into `openspec/specs/` and moves the change under `openspec/changes/archive/`; point the index row at the archived directory, and run `openspec validate --specs --strict`.
