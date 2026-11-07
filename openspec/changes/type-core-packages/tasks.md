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
- [ ] 4.4 **Comment hygiene and import placement, before the pre-closeout review.** Run `make check-comment-hygiene` and read the comments this change added for any that narrate the review or migration that introduced them; move each import the change added to module level unless a verified circular import or a recorded lazy-load reason keeps it local. Closeout only confirms both.

## 5. Closeout

Per `openspec/README.md#plan-closeout-requirements`.

- [ ] 5.1 **Comment hygiene — confirm.** Run `make check-comment-hygiene`, and read the comments this change added for any that narrate the review or migration that introduced them. Do not edit code here: anything to rewrite returns the change to implementation.
- [ ] 5.2 **Import placement — confirm.** Check the imports this change added for any still local without a recorded reason. One that should move returns the change to implementation.
- [ ] 5.3 **Documentation compliance.** Re-check this change's accepted decisions against `openspec/README.md`'s placement rules, and the permanent documents against the code they describe: durable conceptual rationale sits in the companion `architecture.md` rather than only in `design.md`, and no production source references `openspec/changes/type-core-packages`.
- [ ] 5.4 **Narrative compression.** Compress completed-task notes to final behavior, material validation evidence, unresolved or deferred work, and permanent-documentation destinations, moving durable rationale into `design.md` first.
- [ ] 5.5 **Roadmap currency.** Update the affected goal's current state and gap mapping in `docs/development/ROADMAP.md`, or record that no goal is affected. This change sits under the lesser goal “Package and release readiness”, which has no roadmap goal behind it, so it most likely owes the roadmap nothing; confirm that and record the no-impact disposition explicitly.
- [ ] 5.6 **Campaign index currency.** Update this change's row, and its campaign's dependency graph, in `openspec/changes/README.md`, or record that both are unchanged. Other rows' `Depends on` are left alone: archive cleanup releases dependents after the closeout gate.
- [ ] 5.7 **Packaging.** Run `make check-packaging` and resolve every failure it reports (a failure needing a code or lock change returns the change to implementation).
- [ ] 5.8 **End-to-end pipeline.** Record the passing run the latest validation names, its result, and the scenarios that exercise this change, or an explicit blocker naming its cause and the change that owns it, with the validations it gates treated as unrun.
- [ ] 5.9 **Promotion.** Write the permanent documents this change owes — the `market-composition`, `test-compatibility`, and `deployment-state` companion `architecture.md` files, and the releasing guidance naming the exact advertised typed distributions (4.2, 4.3) — and add a design-promotion record mapping every accepted decision to its exact permanent heading. The `spec.md` files the deltas cover (`deployment-state`, `market-composition`, `test-compatibility`) are written by the archive in 5.11, not by hand; the record names them all the same.
- [ ] 5.10 **Documentation citations.** After promotion, run `make check-doc-citations CHANGE=type-core-packages` and resolve every match, then `openspec validate type-core-packages --strict`.
- [ ] 5.11 **Archival.** Last, once every other part is checked: `openspec archive type-core-packages -y` merges the deltas into `openspec/specs/` and moves the change under `openspec/changes/archive/`; point the index row at the archived directory, and run `openspec validate --specs --strict`.
