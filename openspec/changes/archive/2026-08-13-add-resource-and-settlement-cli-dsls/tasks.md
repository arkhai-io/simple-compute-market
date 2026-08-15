## 1. Shared query-language foundation

- [x] 1.1 Added the pure `market_core.query_dsl` lexer, source-spanned AST, typed descriptors, validation, and canonical rendering with focused parser and carrier-purity coverage.
- [x] 1.2 Added exact `arkhai-core==0.2.0` dependencies to registry-client and settlement-runtime, refreshed locks and reinit commands, and verified both installed environments import the shared DSL while carrier-purity checks pass.
- [x] 1.3 Added deterministic human/JSON field references and value-redacted positioned diagnostics covering ordering, quoting, duplicates, unknown fields, and malformed input.

## 2. Filter-spec-owned resource queries

- [x] 2.1 Extended registry filter declarations with validated `query_name`/`query_aliases`, added friendly names plus canonical aliases for all lower-bound VM filters, and covered duplicate/invalid vocabulary and the shipped spec.
- [x] 2.2 Added registry-client filter-spec descriptor conversion and resource-query compilation with typed operators, friendly/canonical aliases, exact wire encoding, schema and URL+ETag binding, fail-closed vocabulary checks, and sync/async 412 coverage; the full client suite and typing pass.
- [x] 2.3 Replaced core buyer `-f/--filter` passthrough with one value-redacting `--resource` query path; every selected authenticated registry now compiles its own URL+ETag-bound query before any listing request, and partial vocabulary matches or rotations fail closed.
- [x] 2.4 Replaced VM and API-credit listing/buy resource convenience flags and direct filter dictionaries with the shared query compiler, removed obsolete filter parsers/builders and raw query persistence/output, refreshed dependent-wheel reinit rules, and covered typed numeric/list/boolean compilation plus multi-registry rejection.

## 3. Settlement clause contracts and mechanism projections

- [x] 3.1 Extended `MechanismRegistration` and settlement configuration validation with role-scoped public clause descriptors/projectors plus strict typed publication-input models/hooks; duplicate, unqualified, secret-like, and cross-role declarations fail registration, and fingerprints include the public field/input schemas.
- [x] 3.2 Added settlement-runtime clause compilation and exact-option evaluation for common and mechanism-owned fields, canonical mechanism aliases, missing rules, ordered alternatives, compatibility admission, mechanism priority, and deterministic option identity ordering; cross-option, empty-clause, disabled/incompatible, and multi-listing ordering tests pass.
- [x] 3.3 Registered pure `stripe.method`/`stripe.funds_flow` and `alkahest.chain`/`alkahest.escrow_kind` listing projections plus strict public publication inputs; both kit suites cover qualification, projector immutability, option-ID stability, and secret-canary rejection.
- [x] 3.4 Replaced VM listing, negotiation, and fresh-buy settlement asset/option selection with repeatable `--settlement` clauses, preserved no-clause priority, applied clause order across listings before mechanism priority, rejected clauses on resume, and removed obsolete selector help/branches.

## 4. Buyer action policy, explanation, and utility namespaces

- [x] 4.1 Added one fresh/resume `open|print|fail` action policy with terminal-aware defaults, confirmation-only `--yes`, stable action-required exits, URL non-persistence, and focused policy/CLI coverage.
- [x] 4.2 Added deterministic mutation-free human/JSON `--explain` plans for generic and VM discovery, resource, settlement, and selection stages; tests prove the path stops before run persistence, negotiation, prerequisite resolution, RPC, hosted action retrieval, and financial mutation.
- [x] 4.3 Moved raw Alkahest escrow utilities to `market settlement alkahest escrow`, removed legacy aliases, and verified command composition, help, plugin registration, and unchanged mechanism behavior.
- [x] 4.4 Removed settle-time chain/token overrides; recovery now derives the pinned mechanism, option, escrow, chain, asset scale, operation identity, provisioning terms, and prices from the accepted run and rejects current-config reinterpretation.

## 5. Typed storefront publication and exact rates

- [x] 5.1 Added the role-neutral `SettlementPublicationClause`, strict common/mechanism inputs, canonical IDs, decimal-text rates/units, and JSON/TOML/unknown-field/no-float coverage.
- [x] 5.2 Added complete-clause storefront config defaults and generated templates while keeping trust, wallet, chain, account, readiness, and secrets outside publication clauses.
- [x] 5.3 Added structured per-resource `settlements` arrays through CSV import, SQLite projection, reconciliation, and stable listing identity with whole-list resource-over-command-over-config precedence and malformed-record rejection.
- [x] 5.4 Replaced `min_price` option synthesis with repeatable typed `--settlement` publication clauses and registered builders; `min_price` remains negotiation-only and readiness suppresses mechanisms independently.
- [x] 5.5 Added exact Decimal-based Stripe currency-minor and Alkahest token-base normalization with explicit scale resolution and rejection of fractional, unsupported, zero/negative, and implicitly rounded rates.
- [x] 5.6 Added restrictive atomic TOML/CSV publication migration preview, check, write, backup, rollback, conflict, and idempotence paths; only unambiguous single-mechanism legacy inputs auto-convert.

## 6. End-to-end behavior and compatibility evidence

- [x] 6.1 Covered registry-to-buyer typed comparisons, aliases, ETag binding/rotation, heterogeneous vocabulary rejection, zero-resource results, and the distinct no-compatible-settlement explanation.
- [x] 6.2 Covered correlated dual-mechanism predicates, ordered alternatives, disabled/incompatible choices, no-clause priority, acceptance pinning, resume, and no cross-mechanism fallback or reinterpretation.
- [x] 6.3 Covered publication defaults/overrides, per-resource clauses, independent readiness, exact Stripe/Alkahest rates, deterministic identities, persistence, reconciliation, and representative migration outcomes.
- [x] 6.4 Verified removed flags and aliases, new resource/settlement/action/explain surfaces, mechanism namespaces, help, completions, and installed-wheel CLI behavior through package, staged E2E, binary, and storefront-image smoke.

## 7. Permanent documentation promotion

- [x] 7.1 Added permanent `cli-query-language` behavior/architecture and capability-index entries for grammar, descriptor authority, correlation, units, action policy, explanation, and non-goals.
- [x] 7.2 Promoted verified behavior and rationale into buyer-orchestration, registry-discovery, settlement-configuration, and storefront-publication specs and architecture companions.
- [x] 7.3 Updated repository architecture, deployment/configuration, and roadmap current-state documentation; existing testing jurisdiction already owns the exercised evidence levels, so `TESTING.md` required no change.
- [x] 7.4 Updated buyer/seller/bare-metal quickstarts, generated role configuration, command examples, and operational guidance; audited domain-authoring guidance and removed stale flags and ambiguous pricing examples.

## 8. Verification and packaging

- [x] 8.1 Passed focused lint, unit, and targeted strict typing across core buyer/storefront/registry-client, settlement/configuration kits, VM buyer/storefront, and review-scope tooling.
- [x] 8.2 Passed registry/buyer/storefront/settlement/migration/publication integrations, 61 staged E2E contract tests, release/deployment packaging checks, review-wheelhouse construction, buyer binary and storefront image builds, and installed CLI smoke.
- [x] 8.3 Passed strict change, dependent hosted-settlement change, and permanent-spec validation. The root Makefile has no `check` target; named lint, package, Helm, comment-hygiene, focused/integration/E2E, typing, wheelhouse, binary, and image checks cover the repository-owned boundary. Real Stripe/provider and live deployment lanes remain external.

## 9. Closeout

- [x] 9.1 Completed closeout: comment hygiene passed; changed local imports were promoted unless deliberately lazy at an optional/cycle boundary; completed notes were compressed; accepted decisions were promoted to permanent specs, architecture, deployment/configuration, quickstarts, capability index, and roadmap; the design-promotion record names exact destinations and migration/validation evidence.
