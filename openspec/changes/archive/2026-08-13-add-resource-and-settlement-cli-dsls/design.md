## Context

See `proposal.md` for motivation. The current buyer has a minimal repeatable `--filter name=value` parser plus VM-owned convenience flags that are converted directly to registry query parameters. Registry filter meaning already belongs to the signed filter specification and ETag. Settlement selection separately consumes deterministic `SettlementOption` envelopes through installed mechanism registrations, but normal buyer commands still carry Alkahest chain/token overrides and Stripe browser behavior.

Storefront publication has one composition over ready settlement registrations, yet its resource pricing input predates that composition. `_default_alkahest_payload` treats `min_price` as a human token amount and scales it by token decimals; `_stripe_listing_input` treats the same value as an integer currency-minor-unit amount. Persistent configuration, projected capacity, resource import, and CLI overrides therefore need a typed publication boundary rather than another precedence rule over `min_price`.

The change crosses core carriers, the registry client, settlement-runtime registration, mechanism kits, buyer plugins, and storefront publication. It must preserve core/domain dependency direction, schema-owned filter semantics, provider separation, exact option identity, and recovery from already accepted runs.

## Goals / Non-Goals

**Goals:**

- One dependency-light syntax/AST implementation used by both DSLs.
- Resource field meaning supplied exclusively by each registry's active filter specification.
- Settlement field meaning split between common immutable option fields and registration-owned qualified projections.
- Same-option correlation and ordered alternatives without a general boolean language.
- Normal commands free of chain-, token-, provider-, and browser-specific flags.
- Explicit, exactly normalized per-mechanism publication rates.
- Deterministic dry-run explanation before any market or financial mutation.
- A coordinated clean cutover with actionable migration for scripts, TOML pricing defaults, and resource imports.

**Non-Goals:**

- Add OR, NOT, parentheses, functions, arithmetic, interpolation, or a reusable general expression engine.
- Persist DSL strings as the canonical configuration or listing representation.
- Change registry HTTP routes, activate filter indexes, or add registry knowledge of settlement mechanisms.
- Add a new settlement mechanism, payment method, provider workflow, or option wire field.
- Make raw Stripe and Alkahest utilities behaviorally symmetric.
- Move negotiation-policy inputs such as opening/max price into either DSL.
- Preserve removed flags, command aliases, or mixed old/new precedence after activation.

## Decisions

### One syntax layer in `market_core`, two schema compilers

Add a dependency-light `market_core.query_dsl` module containing only the lexer/parser, frozen source-spanned AST values, comparison operators, scalar/list literal parsing, and generic field-descriptor validation. It imports no registry, role, domain, kit, CLI framework, or provider code.

`core/registry-client` converts a signed `FilterSpecResponse` into generic field descriptors and compiles a resource AST to canonical query parameters. `kit/settlement-runtime` converts common settlement fields plus each `MechanismRegistration`'s clause descriptors into the same descriptor contract and evaluates settlement ASTs over public option projections.

This adds `arkhai-core` as an exact internal dependency of `arkhai-core-registry-client` and `arkhai-kit-settlement-runtime`; both dependencies point downward. The parser stays in the existing carrier/helper distribution rather than creating a new package for a small pure module.

Alternatives rejected:

- Put both languages in `core/buyer`: storefront publication would depend upward on a buyer role.
- Put settlement syntax in `registry-client`: it would create an unrelated registry dependency in settlement runtime.
- Maintain two parsers: even a conformance corpus would leave duplicate fixes and error behavior.
- Add a parser library: the grammar is intentionally smaller than a general parser dependency and needs stable source-aware errors under repository control.

### Grammar is comparison-only and shell-independent

The shell passes one already-quoted query string. The lexer accepts identifiers (including dotted qualified names), comparison operators, JSON-style quoted strings, bare tokens, booleans, integers, decimals, and bracketed comma-separated lists. Whitespace around operators is accepted. `=` is the equality spelling; `in` and `notin` are the only multi-token operators. Field descriptors decide which operators and literal types are legal.

The parser returns comparisons in source order and never executes input. Unknown escapes, unmatched quotes/brackets, duplicate conflicting singleton fields, unsupported operators, and trailing tokens are source-positioned errors. Repeated comparisons are allowed only when the field descriptor declares them meaningful; otherwise duplicates fail instead of silently applying last-write-wins.

No `or` is needed in the resource DSL because set membership expresses one-field alternatives. No `or` is needed in settlement syntax because repeated `--settlement` clauses are the ordered alternative construct. This avoids ambiguous precedence and makes explanation linear.

### `--resource` is the normal discovery input

Affected `market listing list` and domain purchase commands accept at most one `--resource '<query>'`. Core generic listing commands and domain plugins feed the same parser/compiler rather than registering convenience flags. Empty or absent input means no resource constraints.

For each configured registry, the buyer retrieves the authenticated filter specification first, verifies its schema identity, parses once, and compiles against that registry's declarations. All selected compatible registries must accept the query; a per-registry vocabulary mismatch fails before listing requests rather than silently returning a partial market view. Each listing request carries that registry's ETag and canonical compiled parameters.

The resource compiler consumes declared filter names and aliases, not JSON paths or VM model attributes. A filter declaration may expose a friendly DSL alias such as `gpu_count` while compiling it to the existing `gpu_count_min` canonical query parameter. Evolving capacity vocabulary therefore changes the filter specification, not shared parser code.

The first cutover removes VM resource convenience flags and `-f/--filter`. They are not retained as AST-producing aliases because that would preserve multiple precedence and documentation surfaces indefinitely.

### Settlement clauses are typed option predicates with explicit ordering

Normal buyer commands accept repeatable:

```text
--settlement 'mechanism=stripe asset=usd stripe.method=card'
--settlement 'mechanism=alkahest asset=0x… alkahest.chain=base_sepolia'
```

One occurrence is one conjunction evaluated against one option. The complete clause either matches that option or does not; evaluation never flattens all options in a listing into independent field arrays. Clauses are evaluated in command order. Within the first clause that has survivors, configured mechanism priority and deterministic option identity order rank candidates; later clauses are ignored. With no explicit clauses, current compatibility plus configured priority remains unchanged.

Mechanism values may use a registered configuration key (`stripe`, `alkahest`) or canonical ID. Parsing normalizes both to the canonical ID before comparison or logging. An explicit clause still cannot select an uninstalled, disabled, role-inapplicable, or compatibility-rejected option.

Common buyer predicate fields in the initial contract are `mechanism`, `asset`, and `option_id`. Registrations contribute read-only qualified fields from listing data: initially `stripe.method`, `stripe.funds_flow`, `alkahest.chain`, and `alkahest.escrow_kind`. The registration descriptor includes role, type, allowed operators, and a pure option-to-scalar/list projector. A qualified field requires the matching mechanism. Missing projection values fail that predicate according to the declared rule.

Settlement clause evaluation performs no client construction, readiness check, RPC, token metadata lookup, or provider call. Rate comparison is not an initial buyer predicate because current options do not carry a mechanism-neutral asset scale and late-bound compatibility must remain resource-free. Negotiated price bounds remain negotiation-policy inputs.

Alternatives rejected:

- Flatten settlement fields into the resource DSL: array predicates could be satisfied by different options and the registry would acquire mechanism semantics.
- Use unqualified `method` or `chain`: future mechanisms would collide and shared code would need mechanism branches.
- Let clauses override enablement/readiness: this would turn selection syntax into hidden configuration and financial failover.

### Publication uses a typed carrier; only its CLI edge is DSL text

Introduce a role-neutral typed `SettlementPublicationClause` carried below the CLI with:

- canonical mechanism ID;
- asset;
- decimal rate text and `per` unit when priced;
- common public option inputs;
- a typed mechanism-owned public input mapping validated by the registration.

The repeatable storefront `--settlement` string compiles to this carrier. Persistent inputs do not store DSL strings:

- typed TOML pricing defaults use structured settlement clause tables;
- imported resource records use a JSON array of structured clause objects in a `settlements` field;
- internal projection/reconciliation paths pass validated carrier dictionaries/models.

Per-resource structured clauses replace command defaults for that resource; command clauses replace configured publication defaults; no layer merges partial clauses. This mirrors list-replacement semantics and prevents account/asset/rate fragments from different sources forming an option no source requested.

The common settlement parser validates syntax and common fields. The chosen mechanism registration validates and normalizes its publication inputs, then its existing option builder derives the deterministic option. A clause never enables a mechanism or bypasses readiness.

### Rates are decimal human asset units normalized once

Publication syntax uses `rate=<decimal>/<unit>` and requires `asset`, for example:

```text
mechanism=stripe asset=usd rate=2/hour stripe.method=card
mechanism=alkahest asset=0x… rate=2/hour alkahest.chain=base_sepolia
```

The carrier retains the decimal as text/`Decimal`, never binary float. The mechanism builder resolves authoritative scale it already owns at publication time: the supported currency exponent for hosted fiat or token decimals for Alkahest. It computes `decimal × 10**scale`, rejects a non-integral result, and writes the resulting integer string into `RateValue`. Zero, negative, priceless, and missing-rate rules remain mechanism/role declared; there is no global rounding.

`min_price` may remain a negotiation-policy floor, but it no longer constructs settlement options. Existing `token` and `min_price` resource fields cannot supply two mechanisms. New structured publication defaults and per-resource clauses are the only settlement-option pricing input after cutover.

A migration command previews effective old publication inputs. It can generate one structured clause only when exactly one enabled mechanism makes the old interpretation unambiguous. Dual-mechanism, per-row, hidden-reserve, or conflicting populations are reported as explicit manual conflicts; the tool never guesses whether `2` meant two dollars, two cents, or two tokens. Write mode validates the complete result, requires backup, and uses existing restrictive atomic config migration machinery. Resource CSV migration has check/write/backup behavior and converts only unambiguous rows.

Alternatives rejected:

- Add one global unit convention to `min_price`: it would silently change one existing mechanism.
- Put raw minor/base values in the user DSL: technically uniform but preserves poor and error-prone UX.
- Add asset scale to `SettlementOption`: unnecessary for publication-only normalization and would change option identity/wire contracts.

### Interaction policy is an enum, not a provider flag

`market buy` and `market settle --from` accept `--action open|print|fail`, defaulting to `open` only in an interactive terminal and `print` in a noninteractive terminal unless explicitly supplied. `--yes` controls confirmation only and does not override `--action`. `fail` exits with a stable action-required code after persisting only resumable opaque action metadata.

The action handler is mechanism-neutral and consumes the existing optional public action shape. The CLI never persists URLs. `--no-browser` is removed rather than translated indefinitely.

### Normal lifecycle and raw utilities have different command ownership

Normal commands select or recover an accepted obligation and derive all immutable mechanism inputs from the option/run:

```text
market buy
market settle --from <run>
```

Raw operations move below registered mechanism namespaces. Existing buyer `market escrow create|show|reclaim` becomes:

```text
market settlement alkahest escrow create|show|reclaim
```

No alias remains. Hosted buyer utilities are added under `market settlement stripe` only when a real hosted-client operation exists; no empty symmetry command is invented. Seller commands retain:

```text
market-storefront settlement status
market-storefront settlement stripe onboard|status
market-storefront settlement alkahest check
```

Mechanism command registration lives with the mechanism/domain composition that owns its resources. Namespace placement does not create another runtime or allow raw utilities to reinterpret accepted state.

### `--explain` is a mutation-free staged plan

`market listing list` and `market buy` accept `--explain`. They parse and compile the resource query, retrieve listings, apply public settlement compatibility and clauses, and render:

1. filter-spec schema/version/ETag per registry;
2. canonical resource AST and registry parameters;
3. canonical settlement clauses;
4. candidate counts after resource retrieval, installed/enabled compatibility, each clause, and policy ordering;
5. stable sanitized rejection categories;
6. selected option ID when deterministic selection reaches one candidate.

Explain mode stops before negotiation, prerequisite resolution, action retrieval, chain/provider calls, or persistence of a buy run. Stable machine-readable JSON accompanies human output. It reports semantic pushdown only and never claims a physical index or query plan.

### No registry settlement pushdown in the initial version

Resource predicates compile to current registry filters. Settlement clauses evaluate locally after listings return because the active filter vocabulary has no correlated same-array-element operator. Adding several independent JSONPath filters would be incorrect for listings with multiple options.

A future filter specification may declare one atomic settlement-option predicate with correlated semantics. The generic resource compiler can then push it without changing DSL grammar, but this change does not design or index that server feature. `index-registry-filters` remains independently deferred.

## Risks / Trade-offs

- **[Breaking flag removal disrupts scripts]** → Ship generated before/after help, a deterministic migration reference, exact replacement examples, and fail unknown old flags with the new DSL/namespace command; do not silently accept them.
- **[A small grammar grows into a policy language]** → Keep grammar comparison-only; new meaning requires typed field descriptors, not syntax features.
- **[Different registries expose different vocabularies]** → Compile against every selected filter spec and fail before partial discovery with per-registry diagnostics.
- **[Mechanism projections leak provider details]** → Require namespaced allowlists, pure listing-only projectors, secret canaries, and sanitized explain snapshots.
- **[Same-option correlation regresses]** → Evaluate each clause against one parsed option object and cover multi-option cross-product counterexamples.
- **[Rate migration guesses wrong units]** → Auto-convert only a single unambiguous mechanism; report dual/per-row conflicts and require explicit structured clauses.
- **[Action default surprises automation]** → Noninteractive default is `print`; automation can require `fail`, and `--yes` never changes action policy.
- **[New core helper becomes domain-aware]** → Keep AST/descriptor types generic and enforce core import purity/package-content tests.
- **[DSL and generated help drift]** → Generate field/reference output from the same descriptors consumed by validation.

## Migration Plan

1. Release the parser, descriptor contracts, query/reference rendering, and migration tooling before removing old commands from deployed images.
2. Preview resource/TOML/CSV publication migration. Automatically convert only single-mechanism unambiguous inputs; resolve every reported dual-mechanism or per-resource conflict with explicit structured clauses.
3. Update scripts and automation from named resource flags to `--resource`, settlement selectors to repeatable `--settlement`, `--no-browser` to `--action`, and raw escrow commands to `market settlement alkahest escrow`.
4. Build and stage all affected wheels/images together. Verify generated CLI help, completions, filter-spec compilation, exact option wires, and recovery of pre-cutover accepted runs.
5. Quiesce publication and new buys, back up/migrate publication config and resource imports, deploy the clean-cutover CLI set, inspect `--explain` and settlement status, then resume.
6. Existing listings, accepted Terms, option identities, run logs, registry rows, and settlement journals require no data migration. Pre-cutover runs resume through their accepted mechanism without old override flags.

Before new publication/buy activity, rollback restores config/resource backups and the previous coordinated wheels/images/scripts. After activity resumes, the option and accepted-plan wires remain compatible, so operational recovery continues from accepted state; configuration and automation roll forward rather than reintroducing old flag aliases.

## Design promotion record

| Accepted decision | Permanent location |
|---|---|
| Two comparison-only DSLs share syntax but retain separate schema authorities | `openspec/specs/cli-query-language/{spec,architecture}.md`; `docs/development/ARCHITECTURE.md` |
| Resource fields are filter-spec/ETag owned | `openspec/specs/{cli-query-language,registry-discovery}/{spec,architecture}.md` |
| Settlement clauses are correlated ordered alternatives with registration-owned qualified fields | `openspec/specs/{cli-query-language,buyer-orchestration,settlement-configuration}/{spec,architecture}.md` |
| Publication rates are explicit human asset quantities normalized once per mechanism | `openspec/specs/{cli-query-language,storefront-publication}/{spec,architecture}.md` |
| Normal lifecycle commands exclude raw mechanism controls; utilities are namespaced | `openspec/specs/{cli-query-language,settlement-configuration}/{spec,architecture}.md`; `docs/development/ARCHITECTURE.md` |
| Explain mode is deterministic, sanitized, and mutation-free | `openspec/specs/cli-query-language/{spec,architecture}.md`; buyer role documentation |
| Publication migration is restrictive, backed up, atomic, and refuses ambiguous dual-mechanism prices | `openspec/specs/{storefront-publication,settlement-configuration}/{spec,architecture}.md`; `docs/development/DEPLOYMENT_AND_CONFIG.md` |
| Roadmap assessment: no listed open gap or goal boundary changes; this completes CLI/configuration behavior inside existing settlement and discovery capabilities | No `docs/development/ROADMAP.md` update required |
