## Why

The buyer and storefront CLIs expose a growing mixture of domain filters, settlement selectors, mechanism prerequisites, and interaction controls as unrelated flags. Alkahest and hosted Stripe now share one settlement-option lifecycle, but normal CLI use still leaks mechanism-specific concepts, and dual publication interprets the same `min_price` value in incompatible whole-token versus fiat-minor-unit scales.

## What Changes

- Add two small, typed CLI languages:
  - a resource-query DSL compiled against the active registry filter specification;
  - a repeatable settlement-clause DSL that constrains and orders exact `SettlementOption` candidates without bypassing installed/enabled compatibility.
- Keep both grammars deliberately small: space-separated comparisons, implicit conjunction, typed scalars/lists, and the filter operators `=`, `!=`, `<`, `<=`, `>`, `>=`, `in`, and `notin`; omit general boolean expressions and parentheses.
- Make repeated settlement clauses ordered pre-acceptance alternatives. Every predicate in one clause MUST match the same option; accepted Terms still pin one exact option and never fail over afterward.
- Let settlement registrations contribute only allowlisted, typed, mechanism-qualified clause fields such as `stripe.method` or `alkahest.chain`. Common parser and policy code continue to own grammar, ordering, exact option identity, and safe diagnostics without interpreting opaque mechanism parameters.
- Use the settlement DSL for normal buyer selection and seller publication. Publication rates are decimal human units of the named asset and are normalized exactly once by the selected mechanism; one untyped `min_price` value no longer feeds both token-decimal and fiat-minor-unit interpretations.
- Keep persistent trust, identity, wallet, chain, account, readiness, and secret configuration in typed TOML/profile configuration rather than DSL strings.
- Replace provider-specific normal-path interaction flags with one mechanism-neutral buyer-action policy: `--action open|print|fail`. The policy applies identically on fresh buy and resume and never persists transient action URLs.
- Move raw mechanism utilities outside normal purchase/publication paths under explicit command namespaces, including Alkahest escrow inspection/mutation under `market settlement alkahest ...` and hosted utilities under `market settlement stripe ...`. Preserve the seller's existing common `settlement status` plus genuinely asymmetric `settlement <mechanism>` operations such as Stripe onboarding and Alkahest readiness checks.
- Add `--explain` output that reports the parsed queries, registry-pushed predicates, local settlement constraints, per-stage survivor counts, and sanitized rejection reasons.
- **BREAKING:** replace VM convenience filter flags and repeatable `--filter name=value` inputs on affected discovery/purchase commands with the resource-query DSL.
- **BREAKING:** replace `--settlement-asset`, `--settlement-option-id`, normal-path `--chain`/`--token-contract`/`--token-decimals`, and `--no-browser` with settlement clauses, late-bound typed configuration, and `--action`.
- **BREAKING:** remove legacy Alkahest overrides from `market settle`; resume derives the mechanism and immutable inputs from the accepted run. Relocate raw `market escrow` utilities to the Alkahest namespace without aliases.
- Do not change settlement provider behavior, accepted-plan wire formats, registry HTTP routes, financial custody, onboarding requirements, or post-acceptance recovery semantics.

## Capabilities

### New Capabilities

- `cli-query-language`: Defines the resource and settlement DSL grammars, typed ASTs, validation, ordered-clause semantics, unit handling, explanation output, and clean CLI cutover.

### Modified Capabilities

- `buyer-orchestration`: Normal discovery and purchase consume the two DSLs, use one mechanism-neutral buyer-action policy, report incompatibility by stage, and keep raw mechanism utilities out of the normal path.
- `registry-discovery`: Buyer resource queries compile only through the active filter-spec vocabulary and preserve ETag-bound query meaning while exposing which predicates were pushed to the registry.
- `settlement-configuration`: Installed mechanism registrations contribute typed, public-safe settlement-clause fields and namespaced utilities without moving trust, credentials, readiness, or provider administration into the DSL.
- `storefront-publication`: Normal publication consumes typed settlement clauses, derives options only from enabled ready registrations, and normalizes explicitly asset-scoped human rates without sharing one ambiguous price across mechanisms.

## Impact

- Buyer CLI and plugin composition: `core/buyer`, `core/registry-client`, `domains/vms/buyer`, and VM listing presentation/tests.
- Shared settlement grammar and registration metadata: `kit/settlement-runtime`, `kit/alkahest`, and `kit/hosted-settlement`.
- Seller publication and command organization: `domains/vms/storefront`, resource CSV/import surfaces, generated help, configuration examples, and role documentation.
- Registry filter-spec consumption and query construction change; registry routes and persistence do not.
- CLI scripts must migrate at the coordinated release boundary because old flags and command aliases are removed.
- Package metadata, generated completions/help, review-wheelhouse scope, and affected buyer/storefront images must include the final parser ownership without introducing a new upward dependency.

## Permanent documentation impact

- [x] `docs/development/ARCHITECTURE.md` — record the two-DSL boundary, schema authority, and normal-path versus mechanism-utility ownership.
- [x] Existing subsystem specifications — `buyer-orchestration`, `registry-discovery`, `settlement-configuration`, and `storefront-publication`.
- [x] New subsystem specification — `openspec/specs/cli-query-language/{spec,architecture}.md`.
- [ ] No permanent documentation change.

### Knowledge to promote

- Resource query meaning is filter-spec-owned and ETag-bound; the buyer parser does not invent domain fields — `openspec/specs/cli-query-language/` and `openspec/specs/registry-discovery/`.
- Settlement clauses are ordered pre-acceptance alternatives over exact options, with same-option predicate correlation and registration-owned qualified fields — `openspec/specs/cli-query-language/`, `openspec/specs/buyer-orchestration/`, and `openspec/specs/settlement-configuration/`.
- Persistent prerequisites remain typed configuration, while raw provider/chain utilities live under mechanism namespaces — `openspec/specs/settlement-configuration/architecture.md` and `docs/development/ARCHITECTURE.md`.
- Published rates use explicit asset-scoped human units and one mechanism-owned normalization step — `openspec/specs/storefront-publication/{spec,architecture}.md`.

## Dependencies and Related Changes

- `structured-capacity-requirements` and `publish-multidimensional-listing-shape` may evolve the resource vocabulary; the resource DSL therefore consumes declared filter-spec names rather than freezing VM field names in shared code.
- `index-registry-filters` remains deferred. DSL compilation and explainability do not activate database indexes or change filter semantics.
- The completed settlement-configuration cutover supplies the mechanism registry, typed configuration, priority, and namespaced seller command structure this change extends.
- No external provider or hosted-settlement release is required unless a future mechanism adds new clause fields; current Stripe and Alkahest projections use already-public listing data.
