# Tasks — open-ended compute terms

Implementation started on the stacked resize and registry branches. The partial
2.1 checkpoints add the quote carrier/accessor, VM pricing-proof retention,
installed billing projections and period-aware VM multiplier derivation.
Signed-acceptance evidence enforcement, accepted consumer migration and the
fail-closed direct-read guard are implemented through 2.1c. Task 2.2 adds validated
listing bounds and both storefronts' resolution/persistence/publication carriers.
Task 2.3 adds injected recurring publication. Task 3.1 adds the shared servicing
declaration and publication/cached-acceptance gates. Tasks 3.2–3.3 add acceptance-time
horizon checks and qualify the terms-owned declaration doors. Task 4.1a adds shared
buyer rights policy and lifecycle disclosure; the rest of buyer first use and
closeout remains pending. Verification levels follow
`docs/development/TESTING.md`. New acceptance test implementation requires the
maintainer's approval; the scenarios below are the intended contract, not tests
added by this reconciliation.

## 1. Freeze dependency contracts and decision gates

- [x] 1.1 Reverify `negotiation-driven-capacity-resize`'s landed multiplier contract
  against `core/src/market_core/schemas.py` and `core/tests/unit/test_rate_helpers.py`.
  Record scalar, rounding and amount-range behavior before migrating readers. Resolve resize task
  2.1a's accepted rate-structure carrier before recovery/mandate reads; retain its bound evidence,
  never substitute a current listing after restart or repricing.
- [x] 1.2 With `agreed-evidence-and-early-termination`, once `kit/deal-lifecycle` exists,
  run a replayable regression diagnostic (rather than a new permanent acceptance
  test, per the standing owner instruction) that the option's top-level `lifecycle` round-trips through
  hosted publication, the registry carrier and both buyer commitment checks by the same
  codec (D4), and that an Alkahest option carries none and is refused if it does (the
  binding rule). Do not implement a mechanism-specific term codec. `placement-probe.md`
  records the rejected in-params placement; the nested-shape check there is the
  regression, not a decision gate.
- [x] 1.3 With the reconciled rate change (`spot-deals-through-arkhai-payments`),
  freeze the injected preset-helper interface (D3), `period`, `reserve_ahead_seconds`, separate setup pricing, accessor unit and
  servicing-declaration contracts. The option carries no maximum term: the horizon
  is resolved into `duration_seconds` at acceptance and the option's ID is unchanged
  from the registry to the Agreement (D5). Setup-bearing preset publication and acceptance wait for foundation 12.1's delivery_end revision and vectors, not another payments wire change; preserve valid setup-free options while it is pending.

### Dependency-contract checkpoint (2026-11-06)

- Base: `ba77a3b30` (`resize-multiplier`, PR #350); merged
  `registry-as-published` (PR #349) as `faa339eea`. D-a–D-e remain accepted
  for implementation, pending maintainer review. The webapp owner authorized
  implementation before design review; the campaign row records that disposition.
- At this initial checkpoint, task 1.1 was exercised but left unchecked because the observed contract
  contradicts D2: resize negotiates basis points but writes the **derived monetary
  total** to `Agreement.amount`. The multiplier remains in the transcript and
  `negotiation_threads.agreed_price`. `design.md`'s dependency re-verification
  records the decision needed before changing this signed carrier.
- Focused evidence: `make dist-ci` passed; core's existing `test_rate_helpers.py`
  and `test_settlement_options.py` passed (21 tests); VM storefront's existing
  unit and library-integration `test_vm_multiplier.py` files passed (8 tests).
  The latter uses real SQLite and runtime calls, not the application's HTTP client.
  Exact commands/results are in
  `docs/attachments/negotiate-open-ended-compute-terms/dependency-contract.md`.
  `make check-packaging`, `make check-change CHANGE=negotiate-open-ended-compute-terms`
  and pinned strict OpenSpec validation passed. The change check initially
  refused missing D1–D8 destination bullets; commit `7cb03533e` names the already
  planned post-review destinations without promoting behavior.
- At this initial checkpoint, no tests were added, no production readers migrated,
  and tasks 1.2 onward had not started. No deployment/E2E or closeout evidence is claimed.
- Initial restart point (resolved by D2a below): resolve the scalar-versus-money question in design D2, update
  its delta and tasks to the chosen contract, then finish 1.1 and proceed to 1.2.
  Do not divide or multiply the current Agreement amount as if it were basis
  points. Use `make dist-ci` and the focused commands in the evidence packet
  to recreate the local package environments; they are not committed state.

### D2a continuation (2026-11-06)

- The webapp owner resolved the checkpoint: keep `Agreement.amount` monetary;
  transcript state keeps the multiplier. D2a and the negotiation delta record
  pre-acceptance per-period derivation and accepted-evidence verification on
  recovery/mandate checks. Maintainer review is pending on the PR.
- 1.1 contract verification and 1.3 consumer handoff are recorded in
  `dependency-contracts.md`. Actual accepted snapshot/proof retention and verification
  before recovery/mandate reads remain in 2.1; the existing field subset is not
  sufficient evidence and is not claimed otherwise.
- 1.2 evidence: hosted once builder → neutral carrier → shared codec → exact
  Agreement and both domain pre-approval checks pass; actual registry publication,
  readback and historical seller-signature verification pass in an invocation-owned
  in-process app with real SQLite. Alkahest with no lifecycle is admitted, while
  attaching lifecycle is refused. Early-termination identity/round-trip is structural
  only, not a claim of hosted recurring support. The probes are temporary change
  evidence, not new permanent acceptance tests.
- Existing focused suites passed: lifecycle terms (unit, 47), payments agreement/
  buyer/config (unit, 51), registry listings (application integration through its
  typed client, 17), VM stage-dispatch/orchestrator (unit, 21), bare-metal composition/
  recovery (unit and controlled in-process application paths, 15). The bare-metal
  invocation initially inherited an unsupported SOCKS proxy; clearing proxy variables
  for that invocation made it pass without changing code or installing a dependency.
- `make check-packaging` and `make check-change
  CHANGE=negotiate-open-ended-compute-terms` passed. No product code, live approval,
  or deployment is claimed. Exact setup/probe commands and limits:
  `docs/attachments/negotiate-open-ended-compute-terms/codec-contract.md`.
- No deployed E2E marker proves these dark, injected contracts yet. Section 4.3
  names the existing listing/reserved system regressions; rate consumer evidence
  remains owned by spot. No push-only workflow evidence is owed for section 1's
  contract freeze. Independent implementation review remains pending.
- Resume at 2.1: implement the accessor without reinterpreting monetary Agreement
  amounts; preserve verified acceptance evidence before migrating recovery readers,
  then migrate both domains and install the fail-closed direct-read guard. Work
  through 2.2 onward in order. Promotion and archival remain post-review.

### Partial 2.1 checkpoint (2026-11-07)

- Added core `PriceBasis`, `AgreedPrice` and `agreed_price`. The accessor returns
  accepted money without recomputing it; selected options require an explicit,
  mechanism-owned `project_billing` callback. Core never reads a mechanism's period.
  A supplied acceptance-bound listing must contain the exact selected option and
  matching listing identity. This correspondence check is not authentication.
- For rate-structured listings, both VM buyer recording paths now retain seller publication bytes, complete
  authenticated request, publisher trust/provenance and existing pricing fields
  together, with a deep copy. Existing logs are not backfilled from current listings.
  Retention alone does not establish verified accepted pricing evidence.
- `price_probe.py` exercises the actual VM acceptance-record hook, JSON recovery,
  historical seller-signature verification and isolation from later source edits.
  It also drives the core accessor with prepaid and injected sub-hour recurring
  projections. This is a temporary diagnostic, not a new permanent acceptance test
  or proof of supported hosted recurring mandates.
- Focused validation and replay instructions:
  `docs/attachments/negotiate-open-ended-compute-terms/price-checkpoint.md`.
  No deployed first use, E2E, promotion, archival or independent review is claimed.
- **Restart at the remainder of 2.1**, not 2.2: wire billing projection through
  installed mechanism registrations/compositions (once mechanisms explicitly total;
  rate projection belongs to its adapter). Verify retained seller publication at its
  signed timestamp against accepted trust, listing identity/context, rate structure
  and exact selected option. Bind and verify the transcript multiplier and signed
  acceptance/Agreement before migrating recovery and buyer mandate readers. Preserve
  the original accepted snapshot; never use a fresh listing or rewrite old logs.
  Then migrate both domains' readers/caps/VM checks/rate adapter and add the fail-closed
  repository guard. The accessor by itself authenticates none of these inputs.
  Pre-acceptance recurring amount derivation also remains unimplemented.
- Keep 2.1 unchecked until its consumers and guard are complete. All later tasks
  remain in their existing order; promotion and archival remain post-review. This
  is an authorized session checkpoint, not completion of the terms feature.

### Billing-projection continuation checkpoint (2026-11-07)

- Completed the projection/derivation slice 2.1a below. Installed Alkahest,
  payments and contact registrations explicitly project their supported once/rateless
  options as totals; missing projectors and unsupported payment rate parameters
  fail closed. Projection is independent of current offer enablement/readiness.
- VM buyer scalar conversion, seller policy/reference evaluation and final
  monetary derivation now accept a mechanism-owned billing projection. Injected
  rate projections evaluate one period, not the horizon, rounding upward once;
  hosted rates are still unsupported and no offers are enabled. Flat absolute
  quotes retain existing truncation. A small `pricing_record.py` extraction keeps
  the shared proof-retention helper independent of the buyer composition and avoids
  an import cycle when the amount codec uses its installed registry.
- Evidence and fresh-checkout replay: `docs/attachments/negotiate-open-ended-compute-terms/billing-projection-checkpoint.md`.
  Runtime/Alkahest/contact configuration unit suites passed (66/84/37); payments
  unit suites passed (51) and mypy checked 22 files; VM buyer unit suites passed (45);
  VM storefront unit and real-SQLite runtime suites passed (19); core unit suites
  passed (21). `make check-packaging`, `make check-change` for this change and pinned
  strict OpenSpec validation passed. No E2E marker proves the injected recurring
  projection or acceptance-proof binding; deployed listing/reserved regressions
  remain in 4.3. No push-only evidence is owed for this slice.
  No permanent acceptance tests were added. The initial diagnostic fixture lacked
  required seller/pool identity; the corrected fixture passes. An existing helper
  caller exposed a new mandatory projector argument; preserving the helper's default
  installed projection repaired that regression.
- **Restart at 2.1b, not 2.2.** Resolve the acceptance-bound pricing carrier question
  in `design.md` before claiming seller-proof/transcript-price authentication.
  The current Agreement hash commits the full seller database listing representation,
  not the buyer's retained publication/subset. Resize's rate pin is seller-local.
  Merely verifying a publication signature does not bind that publication to this
  acceptance. Keep monetary Agreement semantics and D-a–D-e unchanged.
- 2.1c then finishes reader/cap/check migration and the direct-read guard. Mandate
  and recovery readers have deliberately not been migrated before evidence enforcement.
  Parent 2.1 and all later tasks stay unchecked. No deployment/E2E, independent review,
  promotion, archival or final integration rebase is claimed; PR #351 stays draft.

### Signed-acceptance pin checkpoint (2026-11-07)

- D2b is decided by webapp owner 2026-11-06, pending maintainer review, and listed
  in PR #351's Decisions to review. It binds the multiplier and D-e's published
  rate-structure digest, not a digest of a new seller snapshot. The DB-listing
  meaning of `Agreement.listing_hash` is unchanged, with its mismatch to the
  published document retained for maintainer follow-up.
- Opening, continuation counters and acceptance now expose that one digest;
  acceptance includes `pricing_pin` in the signed response. Core's HTTP carriers
  preserve it. VM amount-codec validators authenticate the retained publication,
  exact pricing inputs/option and transcript multiplier/monetary Agreement before
  acceptance observation and stage validation. Recovery re-verifies retained
  seller response and buyer request signatures/context against exact Agreement
  bytes before stage enrichment. No current listing or seller-returned snapshot
  supplies pricing; missing historical evidence fails closed for multiplier deals.
- Retention includes the listing's storefront URL and seller principal so the
  accepted pricing snapshot remains parseable by the VM listing-price helper.
  Rateless/exact selections do not acquire a fictitious negotiated multiplier.
- Replay and focused evidence: `docs/attachments/negotiate-open-ended-compute-terms/acceptance-pin-checkpoint.md`.
  The committed diagnostics exercise installed once pricing, injected PT1M pricing,
  signed immediate and continuation acceptance recovery, refusal cases, real-SQLite
  seller pin production and HTTP-carrier round trips. No permanent tests were added
  or assertions weakened; these are invocation-local diagnostics, not deployed E2E.
- **Restart at 2.1c, not 2.2:** finish both-domain readers/caps/check migration,
  mandate-reader migration and the fail-closed direct-read guard. Parent 2.1 and
  all later tasks stay unchecked. PR stays draft. Hosted recurring execution,
  independent review, final rebase, promotion and archival remain unclaimed.

### Reader/guard continuation checkpoint (2026-11-07)

- Completed 2.1c and parent 2.1: accepted financial readers use unit-bearing
  quotes; escrow recovery explicitly requires total; payments mandate/buyer
  re-verification uses its installed projection. Generic negotiation's raw
  Agreement equality check is classified as a transport/expected-money invariant,
  not a financial interpretation. No hosted recurring adapter is enabled.
- The fail-closed AST guard inventories production amount reads, including
  key/getter/reflection aliases and wrapper bodies, with expression/count/reason
  classifications. It runs in packaging and change checks. Unknown reads and
  stale classifications refuse the check. Diagnostics, focused results and exact
  fresh-checkout recipes: `docs/attachments/negotiate-open-ended-compute-terms/reader-guard-checkpoint.md`.
- Existing Alkahest explicit-proposal acceptances needed their own projector
  shape alongside published accepted-escrow selections. That compatibility repair
  passes the existing signed HTTP settlement/recovery suite. Kept test fixtures
  now provide the explicit total projector and required payment payee; no new
  permanent tests were added and no assertions were weakened.
- A separate small repair corrects VM confirmation's second duration scaling of
  an already-total accepted payment and the resumed escrow's hourly label. The
  committed consumer probe drives/declines that confirmation; 54 existing VM
  buyer regressions and packaging/change checks pass. This does not complete
  4.1's broader lifecycle/recurring disclosure.
- **Restart at 2.2**, then continue in order. Listing bounds, publication,
  servicing doors, horizon acceptance and complete buyer disclosure are not yet
  implemented. PR #351 stays draft; independent review, final rebase, promotion
  and archival remain pending. No deployed E2E or live approval is claimed.

### Capacity-bound checkpoint (2026-11-07)

- Completed 2.2: strict per-mode pool hints, UTC/listing/override validation,
  independent bound precedence, null-by-default storage migration and republication
  on the same identity. VM retains its legacy per-model hint/default tiers below
  the new mode hint; malformed bounds hold instead of falling through. Bare metal's
  positive relative reserved-bound admission and conflict diagnostic remain intact.
- Shared pool-override contributions judge projection-dependent term conflicts
  against the write's already-fetched live generation before persistence, not a
  stale held generation. Both bounds can be withdrawn from persisted VM listings.
- Focused regression, first-use and typing evidence, exact setup, resolved probe
  mistakes and limits: `docs/attachments/negotiate-open-ended-compute-terms/capacity-bounds-checkpoint.md`.
  No permanent tests added; kept expectations follow deliberate D5 semantics.
- **Restart at 2.3**, then continue in order. No recurring helper, servicing
  declaration/gates, horizon acceptance, complete buyer disclosure or deployed E2E
  is implemented/claimed by this slice. Bare-metal listing decoding now merges
  listing-level bounds; 3.2 still owes horizon enforcement against both of them.
  PR #351 remains draft; final rebase, independent review, post-review promotion and
  archival remain pending. No external resources or resident servers are retained.
- Fresh setup: `make dist-ci`, then the per-package `make reinit` and
  probe/suite commands in the evidence packet. Committed locks and generated
  bare-metal configuration schema are refreshed; ignored environments are not setup.

### Recurring-publication checkpoint (2026-11-07)

- Completed 2.3: structured per-clause recurring presets, neutral injected helper,
  24-period on-demand penalty recommendation/override, shared-codec validation,
  default-horizon/runway omissions and durable seller diagnostics in both domains.
  Billing combinations do not change capacity/shape identity. Bare-metal clauses
  resolve override > mode-specific pricing hint > configured clauses; absolute-only
  recurrence does not admit reserved options without their positive relative maximum.
- Both compositions consume an injected effective pool-facts deadline reader.
  No such live port is supplied on this base: absence publishes no promise and
  names the default-buyer refusal; raw clause values are not substituted. The
  hosted recurring helper remains absent in deployed compositions. Returned
  treatments and setup fail closed when the injected helper cannot enforce them.
- Reproducible signed administrator publication/read setup, mixed options,
  penalty override, missing helper, runway, unbounded/absolute-only horizons,
  unsupported treatments/setup, evidence/results and resolved attempts:
  `docs/attachments/negotiate-open-ended-compute-terms/recurring-publication-checkpoint.md`.
  No permanent tests added. Existing app/fixture seams follow the new contract.
- Two small encountered baseline repairs are separate commits: the VM architecture
  test now permits core carriers as the permanent layering rule does (retaining
  role/composition bans), and the bare-metal introduction fixture uses a rateless
  current option instead of an obsolete priced carrier. Assertions over actual
  introduction settle/fulfillment outcomes remain intact.
- **Restart at 3.1**, defining the composition-owned servicing declaration and
  publication/cached-acceptance gates; then 3.2 horizon acceptance, 3.3 declaration
  qualification, section 4 buyer disclosure/first use/validation, and section 5.
  `default_buyer_refusals` in the neutral publication module is the policy seam
  section 4 must reuse, not duplicate. The helper's actual names are recorded in
  `dependency-contracts.md`. 3.1 still must add its declaration input/gate.
- PR #351 stays draft. No acceptance guarantee, hosted materialization, real
  provisioning or deployed E2E is claimed. Final rebase/review, post-review
  promotion and archive remain pending. No external resources or resident servers
  are retained. Fresh setup remains `make dist-ci`, per-package `make reinit`,
  then the two committed probe commands in the evidence packet.

### Servicing-declaration checkpoint (2026-11-07)

- Completed 3.1: composition-owned required contract revisions and current
  published/proposed declarations, exact test-lane opt-in, and one shared selector
  consumed by both storefronts' publication and negotiation compositions. A rate
  marker requires the declaration even if its peer marker is malformed. The
  mechanism still owns wire parsing; no live contract revision is invented here.
- Both typed buyer surfaces refuse cached recurring selections after withdrawal,
  wrong revision or wrong lane with signed 409/refetch and no negotiation writes.
  Publication omits recurring peers but retains reserved peers and capacity identity.
  Published and explicitly opted-in proposed fixture declarations admit publication.
  Final artifact building rechecks the same gate before acceptance persistence.
- The injected preset request carries the selected declaration to the encoder.
  Spot consumes this selector for materialization; convergence owns accepted-deal
  continuation. Neither is implemented or claimed by this checkpoint. Deployed
  compositions remain undeclared; accepted once-deal servicing regressions pass.
- Setup, replayable fixtures, exact focused targets/results and limits:
  `docs/attachments/negotiate-open-ended-compute-terms/servicing-declaration-checkpoint.md`.
  No permanent tests added. A separate fixture repair gives the kept shape-priced
  buyer integration scenario a signed as-published body and publisher trust rather
  than weakening D2b's accepted-pricing verification.
- **Restart at 3.2**: acceptance-time resolved start/bounds, optional recurring
  horizon, whole-second starts and runway; remove only VM's round-zero fallback.
  Then 3.3 records the already committed declaration fixture qualification after
  3.2's integration, followed by section 4 buyer disclosure/validation and section 5.
  Reuse `RateServicing` and `default_buyer_refusals`; do not duplicate either gate.
- PR #351 remains draft. No final rebase, review, deployed E2E, promotion or archive
  is claimed. No external resources or resident servers remain. Recreate wheels
  and environments and run both committed probe commands in the evidence packet.

### Horizon-acceptance checkpoint (2026-11-07)

- Completed 3.2: one fixed acceptance clock feeds a domain-owned final terms hook
  before artifacts/writes on all acceptance paths. Both domains bind the finite
  default/explicit horizon, both listing bounds, whole-second recurring starts and
  exact approval-expiry runway. Missing reserved duration is refused; only VM's
  negotiation/default and rate-pin fallbacks were removed, not delivery/recovery.
- `kit/settlement-runtime/.../horizon.py` owns the pure bound/runway resolver.
  Both domains' message/provision codecs permit omission; their storefront runtime,
  policy/composition files supply selection, timing projection and Agreement/physical
  artifacts. `kit/negotiation-runtime/.../runtime.py` remains schema-opaque.
  Foundation validation owns term-end treatments and fails closed on unsupported
  returned treatment. No deployed timing projection or rate declaration is added.
- Completed 3.3: the committed proposed/published/absent declaration fixtures
  requalify publication and cached acceptance after horizon integration. Selector,
  accessor and timing handoffs are in `dependency-contracts.md`; spot owns the
  materialization consumer, convergence owns startup/continuation. Neither is
  required to archive terms, and neither is claimed by these fixtures.
- Replayable setup, exact targets/results and evidence limits:
  `docs/attachments/negotiate-open-ended-compute-terms/horizon-acceptance-checkpoint.md`.
  Kit suites: 62/175 passed; VM/bare domain suites: 60/224 passed; VM storefront
  selected policy/app suites: 70 passed; bare storefront: 106 passed. Targeted
  horizon typing, `make check-packaging`, `make check-change
  CHANGE=negotiate-open-ended-compute-terms` and pinned strict OpenSpec validation
  pass. No permanent tests added or assertions weakened.
- The VM fixture commits signed resolved horizon artifacts with an injected data
  placeholder. Bare metal validates valid Agreement/physical artifacts through the
  no-write opening plan: its actual rate-mandate capture remains spot-owned and
  rejects a placeholder. Both typed buyer surfaces prove invalid horizons and
  cached declaration withdrawals leave negotiation rows unchanged. These are not
  live hosted rate/mandate/provisioning guarantees.
- **Restart at 4.1**: both buyer CLIs/policies must expose optional recurring horizons,
  retain required reserved duration and show D7's codec-derived disclosures. Reuse
  `default_buyer_refusals` and `RateServicing`; do not duplicate codec or timing
  parsing. Then 4.2 buyer selection fixtures, 4.3 affected/E2E validation and section 5.
- PR #351 remains draft. Final rebase/review, deployed E2E, post-review promotion
  and archival remain pending. No external resources or resident servers remain.
  Recreate wheels/environments and run both committed `--acceptance` probe commands.

### Buyer-rights/disclosure checkpoint (2026-11-07)

- Completed 4.1a: both buyers compose `BuyerTermsPolicy` over foundation authority
  selection and the same `default_buyer_refusals` used by publication diagnostics.
  `--allow-unprotected-terms` explicitly waives the recommendations for one fresh
  buy/negotiation, never malformed terms, unaccepted authorities or unsupported
  mechanism capabilities. The choice is recorded in fresh run metadata.
- Shared `lifecycle_disclosure` decodes exact selected/accepted lifecycle values.
  Fresh selection and acceptance output names delivery promises, each stopper's
  notice/treatment, term-end treatment, penalty ceiling/asset/collectibility,
  authority/window/hold cap, evidence retention and stop-then-hint semantics.
  No-adapter options are shown as making no lifecycle delivery promise. Output is
  visible without a confirmation prompt and goes to stderr, preserving JSON stdout.
- Reproducible proposed rights fixture and exact results/limits:
  `docs/attachments/negotiate-open-ended-compute-terms/buyer-rights-checkpoint.md`.
  The fixture consumes each buyer's actual context factory, injecting proposed
  rate capabilities only for shared rights-policy/disclosure qualification. It is
  not a full CLI rate buy, mandate or hosted service readiness claim.
- Existing suites: settlement runtime 175 passed, VM buyer 215 passed (including
  18 focused buy/explain/standalone-dispatch tests), bare-metal buyer 32 passed.
  Targeted typing is one shared module, not repository-wide typing. Packaging,
  check-change and pinned strict OpenSpec validation pass. No permanent tests added
  and no assertions weakened.
- **Restart at 4.1b**, leaving 4.1 unchecked: optional recurring horizons and the
  class/unit-bearing price/setup/reserve/bounds/effective-horizon display remain.
  Inspect VM's early duration requirements, `unit_count` and amount-codec calls,
  plus bare metal's `purchase_quote`/`require_quoted_agreement` total-only paths;
  carry omission through without inventing a reserved duration. Payment projections
  deliberately remain once-only. Any proposed recurring presentation/pricing port
  must be mechanism-owned and injected, not a storefront/buyer parser of payment
  fields or a claim that hosted rate support has landed. Complete recovery's
  pre-approval disclosure in the same price/horizon continuation.
- Then do 4.2 full buyer selection fixtures, 4.3 affected/E2E validation and section 5.
  No E2E lane, final rebase, review/promotion or archival was performed at this
  checkpoint. PR #351 remains draft. No external resources or resident servers remain.

## 2. Quote and capacity terms

- [x] 2.1 In `core/src/market_core/schemas.py` implement the unit-bearing accessor;
  migrate both domains' policy/reference readers, buyer caps, VM checks and the rate
  adapter to it. Add the fail-closed guard under `scripts/`, integrated into the
  existing check targets. Verify at unit level with `core/tests/unit/test_rate_helpers.py`
  and `test_settlement_options.py`: whole-term, sub-hour recurring, rounding, absolute
  amount fallback, accepted recovery and the guard's rejected direct reads.
  - [x] 2.1a Wire mechanism-owned billing projections through installed registrations
    and VM buyer/seller multiplier derivation. Verify once totals, fail-closed
    unsupported projections and injected sub-hour period quotes using the committed
    diagnostic and existing configuration/multiplier/buyer suites.
  - [x] 2.1b Implement D2b's signed-acceptance pin binding the multiplier and D-e's
    published rate-structure digest (owner decided 2026-11-06; maintainer review pending).
    Implement historical seller-proof,
    exact option/context, transcript multiplier and accepted Agreement verification
    before recovery or buyer mandate reads. Never substitute a current listing.
  - [x] 2.1c Migrate remaining both-domain policy/reference/cap/amount readers and
    mandate checks, and integrate the fail-closed direct-read guard. Keep 2.1 unchecked
    until all three slices and its focused validation pass.
- [x] 2.2 Add validated relative/UTC absolute hints in `kit/resource-pools-contracts`,
  models in `domains/vms/domain/src/arkhai_vms` and
  `domains/bare_metal/src/arkhai_bare_metal`, and both storefronts' override/default
  resolution. Keep bounds on the listing, not on each option. Carry/clear the absolute
  term through shared storefront persistence and existing opaque registry publication;
  use the pool-override kit's existing live fetch to validate cross-tier conflicts before
  writes. Verify pure validation and tier precedence in the package unit suites;
  no new network calls or lease changes here.
- [x] 2.3 In both storefront publication adapters, emit separately priced options on
  existing listing identities using the foundation codec and injected preset helper; include
  premature_stop_penalty, recommended on-demand default 24 periods' price with seller override,
  and `delivery_deadline_seconds` from the pool's effective value, read like the bound hints, on
  every compute option (none when the pool enforces none; the diagnostic names the refusal). Apply D5's
  runway inequality to the default horizon and report a failing default as a close reason.
  Missing hosted helper omits recurring candidates. Omit unbounded
  recurring candidates with diagnostics. Consume, do not redo, the foundation's
  Alkahest release-model migration. Unit targets: both domain suites and
  `domains/vms/storefront/tests/unit`; app-integration targets: VM
  `tests/integration/test_publication_loop.py`, `test_pool_overrides_api.py`,
  `test_listing_identity_carryover.py` and the bare-metal storefront integration
  suite. Prove mixed options preserve capacity identity and valid reserved options.

## 3. Servicing doors and acceptance

- [x] 3.1 In `kit/settlement-runtime` define the composition-owned declaration agreed
  with the rate adapter. Wire both storefronts' publication and acceptance checks;
  reject cached recurring options before acceptance persistence. Unit verification
  covers published/proposed contract selection and lane-only opt-in; app integration
  uses each storefront's typed client and real persistence to prove the cached-option
  refusal has no acceptance side effect.
- [x] 3.2 In both negotiation runtimes/policies, resolve start/bounds before final
  signature per D5, resolving the horizon into `duration_seconds`; require whole-second recurring starts,
  refusing fractional values without rewriting accepted bytes; bind equal duration/max term
  without rounding, require at least one whole period for recurring horizons, refuse a
  recurring horizon that fails D5's runway inequality naming the minimum that passes
  (verify: "The horizon leaves no runway"), and
  refuse expired/excessive horizons and missing reserved duration. Carry term-end
  `settles_through` into payments `end.partialPeriod` through the foundation codec;
  compute presets use returned and fail closed until vendored. Interim recommendation:
  absolute end with a charged final partial period disclosed in the option. Remove only VM's
  round-zero fallback here. Unit targets: domain terms/policy suites;
  app integration: `domains/vms/storefront/tests/integration/test_buyer_selection_negotiation.py`
  and bare-metal negotiation tests. `unify-compute-delivery-path` gates using the same
  accepted start/end on resume and provisioning; do not duplicate its window logic.
- [x] 3.3 Verify this change's declaration seam using injected published/proposed/absent
  declarations and stable lane identity: publication omits and cached acceptance refuses
  undeclared servicing before persistence. Commit reproducible fixtures for those two gates.
  Handoff declaration/accessor contracts after 1.3, 2.1 and 3.1 to spot materialization;
  spot owns its restart/refusal tests and evidence, convergence owns startup/continuation
  tests and evidence. Do not wait for either consumer to close this task or archive this change.
  Deployed recurring offers remain disabled until the consuming gates pass.

## 4. Buyer first use and focused validation

First use includes one mixed listing per domain with a hosted on-demand option carrying
`delivery_deadline_seconds` and an Alkahest reserved option carrying no `lifecycle`,
selected by a default buyer: the hosted option is checked for the term and the Alkahest
option is shown as making no delivery promise, not refused for lacking one (D3).

- [ ] 4.1 Update both buyer CLIs and policies: optional recurring horizon, required
  reserved duration and D7's display of class/price unit/setup/reserve/terms, including
  per-stopper and term-end `settles_through`, premature-stop penalty amount/asset/cap,
  the delivery deadline as seconds after approval, recommended default acceptance refusal of
  on-demand without positive penalty and of a compute option whose mechanism has a lifecycle
  adapter without a delivery deadline (explicit buyer opt-out; an option without an adapter
  is shown as making no delivery promise), unrounded effective horizon and
  stop-then-hint semantics. Use
  accepted codec values; never promise a reserve-ahead loss cap. Unit targets:
  `domains/vms/buyer/tests/test_buy_resume_cli.py`, `test_explain_cli.py` and
  `domains/bare_metal/buyer/tests`. Integration verifies displayed/approved values
  agree with selected terms and the fixture-derived expected mandate; live rate
  materialization evidence belongs to spot and does not gate this task.
  - [x] 4.1a Compose the shared default-buyer rights recommendations in both buyer
    policies, provide a run-scoped explicit opt-out and render codec-derived
    lifecycle disclosure at fresh selection/acceptance, including no-adapter promises.
  - [ ] 4.1b Expose optional recurring/required reserved duration and complete
    class/price-unit/setup/reserve/bounds/effective-horizon display on fresh and
    resumed approval paths. Verify selected/accepted/displayed pricing agreement
    using proposed injected mechanism ports without enabling deployed rate servicing.
- [ ] 4.2 Prepare committed publication/selection fixtures with reserved/on-demand/spot
  candidate options and both bounds in each domain, using injected proposed declarations
  rather than requiring runnable rate or mediation services. Start at each buyer's selection
  surface and observe omitted/shorter horizon, displayed treatments and cached-option refusal.
  Consumer lane qualification of all three doors belongs to spot/convergence/activation,
  not a prerequisite to this terms archive. Keep proposed fixture evidence distinct from
  runtime rate/live-hosted evidence; readiness-check any actual lane before driving it.
- [ ] 4.3 Run affected package unit/app-integration suites, existing VM listing-shape
  scenarios in `e2e-tests/tests/e2e/roles/scenarios/vms/test_listing_shapes.py` and
  existing reserved compute deal scenarios in both domains (rate consumer scenarios are not
  this archive's gate). Record exact targets/results and disclose
  dependency-gated runs. Run `make check-change CHANGE=negotiate-open-ended-compute-terms`
  and pinned strict OpenSpec validation before pre-closeout review.

## 5. Closeout

Documentation-only, in `openspec/README.md#plan-closeout-requirements` order;
anything requiring code returns to implementation. These are future implementation
closeout tasks, not authorization to promote unimplemented behavior now.

- [ ] 5.1 **Comment hygiene:** run `make check-comment-hygiene`; confirm touched
  comments describe current invariants, not change provenance.
- [ ] 5.2 **Import placement:** confirm touched imports are module-level unless an
  experimentally verified circularity or deliberate lazy-load reason is recorded.
- [ ] 5.3 **Documentation compliance:** classify D1–D8, including the horizon as the Agreement's
  refinement; verify each permanent home and no duplicated codec/authority ownership.
- [ ] 5.4 **Narrative compression:** reduce completed-task notes to behavior, material
  evidence, residual work and permanent destinations; retain reasoning in design.
- [ ] 5.5 **Roadmap currency:** update Goal 8 terms/display/bounds gap and current state
  in `docs/development/ROADMAP.md`; record the disposition in the promotion record.
- [ ] 5.6 **Campaign index currency:** update this row/dependency graph in
  `openspec/changes/README.md` and run `make check-change-index`. The integrating
  owner coordinates the shared campaign; this reconciliation supplies row text only.
- [ ] 5.7 **Packaging:** run `make check-packaging` and
  `make check-architecture-change CHANGE=negotiate-open-ended-compute-terms`; resolve
  all failures/owned exceptions. Run agent-skill checks if instructions were touched.
- [ ] 5.8 **End-to-end pipeline:** record the pipeline run/result and scenarios proving
  both domains' classes, bounds, display and the declaration/publication/acceptance gates.
  Materialization and startup/continuation pipeline evidence belongs to spot and convergence,
  respectively, not this change's closeout. Readiness/dependency
  failures are explicit blockers, never passing evidence or live-deployment claims.
- [ ] 5.9 **Promotion:** after code review, promote D1–D8 to the destinations in the
  design-promotion table, including publication/buyer architecture companions and
  architecture vocabulary. Archive merges deltas into negotiation, publication,
  resource-pool, settlement-configuration and buyer specs; record destinations and
  identity decision outcomes. No new capability-index entry is needed.
- [ ] 5.10 **Documentation citations:** run
  `make check-doc-citations CHANGE=negotiate-open-ended-compute-terms`, resolve all
  matches, then `bunx @fission-ai/openspec@1.14.0 validate negotiate-open-ended-compute-terms --strict`.
- [ ] 5.11 **Archival:** last, run
  `bunx @fission-ai/openspec@1.14.0 archive negotiate-open-ended-compute-terms -y`
  and link the campaign row to the resulting archive.
