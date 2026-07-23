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
