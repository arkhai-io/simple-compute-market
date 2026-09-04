## 1. Restore advertised baseline

- [ ] 1.1 Fix the current `arkhai-core` typecheck without broad ignores or weakening its exported contract.
- [ ] 1.2 Confirm registry-client typecheck and define supported public modules for both advertised packages.
- [ ] 1.3 Add built-wheel `py.typed` content and clean installed-consumer fixtures for both packages.

## 2. Ratchet public packages

- [ ] 2.1 Type and mark `core/storefront-client`, including request/response carriers and error behavior.
- [ ] 2.2 Type core buyer public policy/client boundaries after the buyer-preference change is archived.
- [ ] 2.3 Type core storefront schema-opaque public contracts without importing domain compositions.
- [ ] 2.4 Type the registry public shell last with narrow third-party/framework adapters.
- [ ] 2.5 Decide and record whether `kit/site` is in scope; if not, open or reference a separate kit typing change rather than silently adding it.

## 3. Shared checks and CI

- [ ] 3.1 Add shared pragmatic defaults and independently runnable package overrides without reducing stricter existing checks.
- [ ] 3.2 Add package checks to the aggregate target only when focused checks, runtime tests, and wheel fixtures pass.
- [ ] 3.3 Add the aggregate target to CI and retain import/dependency-boundary diagnostics.

## 4. Verify and promote

- [ ] 4.1 Run all included typechecks, runtime/conformance suites, wheel builds/inspection, and clean consumer fixtures.
- [ ] 4.2 Promote public typing ownership to `market-composition`, check requirements to `test-compatibility`, and marker behavior to `deployment-state` specs/architecture companions.
- [ ] 4.3 Update releasing guidance with the exact advertised typed distributions, record promotion in `design.md`, and run strict validation before archive.

## 5. Closeout

Per `openspec/README.md#plan-closeout-requirements`.

- [ ] 5.1 **Comment hygiene.** Run `make check-comment-hygiene`, then direct-read the comments and docstrings this change touches for the fuzzier provenance-narration rule the target cannot catch mechanically.
- [ ] 5.2 **Import placement.** Review every import this change adds or touches and move it to module level where safe; retain a local import only against an observed circular import or a documented lazy-load reason, verified against the real suite.
- [ ] 5.3 **Documentation compliance.** Re-check this change's accepted decisions against `openspec/README.md`'s placement rules. It carries delta specs for `deployment-state`, `market-composition`, `test-compatibility`; confirm each landed in the owning `openspec/specs/<capability>/spec.md`, and that durable conceptual rationale sits in the companion `architecture.md` rather than only in `design.md`.
- [ ] 5.4 **Narrative compression.** Compress completed-task notes to final behavior, material validation evidence, unresolved or deferred work, and permanent-documentation destinations, moving durable rationale into `design.md` first.
- [ ] 5.5 **Roadmap currency.** This change sits under the lesser goal “Package and release readiness”, which has no roadmap goal behind it, so it most likely owes `docs/development/ROADMAP.md` nothing. Confirm that and record the no-impact disposition explicitly rather than omitting the step.
- [ ] 5.6 **Campaign index currency.** Update this change's row, and its campaign's dependency graph, in `openspec/changes/README.md` to match its state at completion, or record the disposition here if its status and campaign placement are both unchanged.
- [ ] 5.7 **Promotion.** Add a design-promotion record, mapping every accepted decision to its exact permanent heading, and verify no production source references `openspec/changes/type-core-packages`.
