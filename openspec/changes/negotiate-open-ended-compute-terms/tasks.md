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
buyer rights policy and lifecycle disclosure. Task 4.1b adds mechanism-owned
numerical presentation, optional recurring horizon plumbing and accepted recovery
disclosure. Task 4.2 adds mixed-publication first use through both buyer commands. Task 4.3 runs focused application regressions and records failed E2E readiness as unobservable. Sections 1–4 were replayed onto dev as round 1 (`6f86ac5e6`).
The owner's record of round 1 (`reviews/01-implementation-owner.md`) stood in for
the design review this change never had; its decisions are in `design.md` D1–D12, and
the code they need, with review 04's F1 and F2, is round 2: first planned as section 5,
then split at the owner's direction into sections 5–12, one session each but 5 and 6
together, reviewed as one round (`design.md`, "Implementation cadence"). Implementation
resumes at 5.5. Verification levels follow `docs/development/TESTING.md`;
every behaviour this change adds gets permanent tests at the level it assigns (owner
record 01, R2).

## 1. Freeze dependency contracts and decision gates

- [x] 1.1 Reverify `negotiation-driven-capacity-resize`'s landed multiplier contract
  against `core/src/market_core/schemas.py` and `core/tests/unit/test_rate_helpers.py`.
  Record scalar, rounding and amount-range behavior before migrating readers. Resolve resize task
  2.1a's accepted rate-structure carrier before recovery/mandate reads; retain its bound evidence,
  never substitute a current listing after restart or repricing.
- [x] 1.2 With `agreed-evidence-and-early-termination`, once `kit/deal-lifecycle` exists,
  run a replayable regression diagnostic (section 5 converts it into a test, or drops
  it where a foundation suite covers it) that the option's top-level `lifecycle` round-trips through
  hosted publication, the registry carrier and both buyer commitment checks by the same
  codec (D4), and that an Alkahest option carries none and is refused if it does (the
  binding rule). Do not implement a mechanism-specific term codec. `placement-probe.md`
  records the rejected in-params placement; the nested-shape check there is the
  regression, not a decision gate.
- [x] 1.3 With the reconciled rate change (`spot-deals-through-arkhai-payments`),
  freeze the injected preset-helper interface (D3), `period`, `reserve_ahead_seconds`, separate setup pricing, accessor unit and
  servicing-declaration contracts. The option carries no maximum term: the horizon
  is resolved into `duration_seconds` at acceptance and the option's ID is unchanged
  from the registry to the Agreement (D5). Setup-bearing preset publication and acceptance were gated on the helper's declared setup capability, with valid setup-free options unaffected. Amended by the owner's round-1 review (record 01, R19): the delivery_end revision is already vendored in the mediation contract, so the gate is the servicing declaration's `setup` entry instead (task 5.5).

### Dependency-contract checkpoint (2026-11-06)

- Base: `ba77a3b30` (`resize-multiplier`, PR #350); merged
  `registry-as-published` (PR #349) as `faa339eea`. D-a–D-e remain accepted
  for implementation. Implementation started before a design review; the owner's
  round-1 record later reviewed the design in its place.
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
  evidence.
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
  projections. This is a temporary diagnostic, not proof of supported hosted
  recurring mandates.
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
  The initial diagnostic fixture lacked
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

- D2b binds the multiplier and D-e's published rate-structure digest, not a digest
  of a new seller snapshot (settled in owner record 01, R4). The DB-listing meaning
  of `Agreement.listing_hash` is unchanged; its mismatch to the published document is
  an unowned gap in `openspec/changes/README.md` (R5).
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
  seller pin production and HTTP-carrier round trips. No assertions were weakened;
  these are invocation-local diagnostics, not deployed E2E.
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
  Kept expectations follow deliberate D5 semantics.
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
  Existing app/fixture seams follow the new contract.
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
  A separate fixture repair gives the kept shape-priced
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
  pass. No assertions weakened.
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
  check-change and pinned strict OpenSpec validation pass. No assertions weakened.
- At this checkpoint the next slice was **4.1b** (now completed below), leaving
  4.1 unchecked pending full selection qualification: optional recurring horizons and the
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

### Buyer numerical-presentation checkpoint (2026-11-07)

- Completed 4.1b: `MechanismRegistration.present_payment` supplies a validated
  numerical quote, separate setup once charge and initial reserve. The registry
  checks its asset/billing basis and exact equality to an accepted accessor quote.
  Neutral buyers do not read payment period/setup/reserve fields. Missing presenters
  refuse; installed payments remain strictly once-only with zero separate setup/reserve.
- Both buyers disclose derived class, unit-bearing price, unchanged asking-rate unit,
  separate setup/reserve, listing bounds and requested horizon. Accepted disclosure
  uses retained Agreement money/start/unrounded horizon/end, never current listings.
  VM recovery renders it before dispatch to any approval effects. Bare-metal has no
  separate resumed-approval command; its fresh accepted stage shows the same rows.
- Omitted duration reaches recurring selection/provision intent; reserved quotes
  require an explicit duration rather than inventing an hour. VM's per-match unit
  count uses one projected period, not recurring lease hours; the multiplier codec
  accepts an omitted horizon. Bare-metal quote/acceptance checks carry per-period
  money/unit alongside totals, checking any explicitly requested horizon unchanged.
- Replay/setup/evidence: `docs/attachments/negotiate-open-ended-compute-terms/buyer-presentation-checkpoint.md`.
  Proposed ports qualify numerical disclosure/pricing only, not hosted rate execution.
- Existing regressions: settlement runtime 175 passed; VM buyer 215 passed;
  bare-metal buyer 32 passed; affected core buyer orchestration/selection 25 passed;
  Alkahest registration 84 passed; payments configuration/agreement/buyer 51 passed.
  Both proposed presentation replays pass. Targeted mypy passes for two shared
  presentation/disclosure modules. Packaging, check-change (including comment/import
  hygiene and citations) and pinned strict OpenSpec validation pass. The duration
  assertion follows the new contract, and two schema-opaque fixture callbacks are
  explicitly scoped as recorded in design.
- **Restart at 4.2.** Prepare the full mixed-listing publication/selection fixture in
  each buyer, including reserved/on-demand/spot, both bounds, omitted and shorter
  horizons, displayed treatments and cached-option refusal. Inject proposed mechanism
  pricing/presentation and timing/capability ports at composition; do not add a neutral
  payment-field parser or enable installed recurring servicing. The committed 4.1b
  replay is a starting surface, not completion of that full CLI selection exercise.
- Then 4.3: affected app-integration suites, existing VM listing-shape and both-domain
  reserved compute E2E scenarios. Use the prescribed Podman provider, readiness-check
  before driving and record any unobservable lane exactly. Section 5 remains after
  review; no promotion or archival has occurred. PR #351 stays draft.

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
    published rate-structure digest (settled in owner record 01, R4).
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
  compute presets use `last_boundary` (returned), refused where the mechanism cannot
  enforce it. Amended by the owner's round-1 review (record 01, R13): `returned` is
  already vendored, so no interim charged term end is recommended, and admission by the
  servicing declaration's qualified treatments is task 5.5. Remove only VM's
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
option is shown as making no delivery promise, not refused for lacking one (D3). What
was proved for bare metal is narrower (owner record 01, R20): its buy command uses the
hosted options, and its shared policy admits the Alkahest peer; the bare-metal buyer has
no Alkahest purchase, an unowned gap in `openspec/changes/README.md`.

- [x] 4.1 Update both buyer CLIs and policies: optional recurring horizon, required
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
  - [x] 4.1b Expose optional recurring/required reserved duration and complete
    class/price-unit/setup/reserve/bounds/effective-horizon display on fresh and
    resumed approval paths. Verify selected/accepted/displayed pricing agreement
    using proposed injected mechanism ports without enabling deployed rate servicing.
- [x] 4.2 Prepare committed publication/selection fixtures with reserved/on-demand/spot
  candidate options and both bounds in each domain, using injected proposed declarations
  rather than requiring runnable rate or mediation services. Start at each buyer's selection
  surface and observe omitted/shorter horizon, displayed treatments and cached-option refusal.
  Consumer lane qualification of all three doors belongs to spot/convergence/activation,
  not a prerequisite to this terms archive. Keep proposed fixture evidence distinct from
  runtime rate/live-hosted evidence; readiness-check any actual lane before driving it.
- [x] 4.3 Run affected package unit/app-integration suites, existing VM listing-shape
  scenarios in `e2e-tests/tests/e2e/roles/scenarios/vms/test_listing_shapes.py` and
  existing reserved compute deal scenarios in both domains (rate consumer scenarios are not
  this archive's gate). Record exact targets/results and disclose
  dependency-gated runs. Run `make check-change CHANGE=negotiate-open-ended-compute-terms`
  and pinned strict OpenSpec validation before pre-closeout review.

### Mixed-selection and integration checkpoint (2026-11-07)

- 4.1/4.2: both actual buyer commands select a mixed publication's reserved/on-demand/spot peers, with both bounds, omitted/2401-second horizons and default rights/disclosure. VM additionally selects Alkahest and shows no delivery promise. Bare metal's installed payment buy command has no Alkahest purchase stage; its shared rights/disclosure admits the option without inventing a stage. Proposed mechanism ports remain diagnostic only. Cached signed refusals and acceptance artifacts replay alongside publication.
- Committed setup, exact entry points/results and limits: `docs/attachments/negotiate-open-ended-compute-terms/mixed-selection-checkpoint.md`. The kept bare-metal reserved buyer integration now explicitly requests its intended 3600 seconds; assertions unchanged.
- 4.3: VM storefront application targets 140 passed; VM buyer 215 passed; bare-metal buyer 32 passed. Bare-metal targets initially found the missing-duration fixture; repaired payment-client target 16 passed, final combined rerun **185 passed**. Packaging, check-change and pinned strict OpenSpec validation pass.
- E2E readiness with the required Podman provider fails before any service starts: VM included env file resolves outside the checkout; bare metal raises `RuntimeError: volume [domains/bare_metal/../../shared-env] not defined in top level`. The packet preserves exact commands/errors (host prefix redacted under public-content rules). Listing-shape and both reserved-deal scenarios are **unobservable/unrun**, not passed. The existing campaign Compose-assembly gap records the reproduction. No resources remain.
- Rebased with preserved dependency merge onto `origin/dev` (`cf4db5b7f`). Conflict resolution keeps dev's workflow pre-commit delegation and this change's Agreement amount guard; the existing check-runner suite passes (18). Final packaging and both-domain focused tests/first use are re-run against fresh locked wheels after rebase. `make check-change CHANGE=negotiate-open-ended-compute-terms CHANGE_BASE=origin/dev`, comment hygiene, architecture-change, citations and pinned strict OpenSpec validation pass. No architecture exception belongs to this change.
- The workflow route was reconciled when sections 1–4 were replayed onto dev as round 1, on the review branch the owner chose; the restart is section 5.
- Task 4.3 is checked for the required attempt/disclosure, not E2E success. Its "unobservable" disposition is replaced (owner record 01, R23): the E2E evidence comes from validation, whose pipeline run 43118309706 at `6f86ac5e6` ran the VM and bare-metal lanes (validation 05), and an unrun lane at closeout is a blocker. Keep installed recurring servicing disabled.

- [x] 4.4 Align the canonical VM and bare-metal reserved-payment purchase drivers
  with the absent effective pool deadline: explicitly opt into unprotected terms,
  assert no published delivery promise, and retain dispute/payment/delivery/release
  checks. Update the existing dispute-coverage fixture and run its focused suite,
  packaging, comment hygiene and E2E qualification. Reversed by the owner's round-1
  review (record 01, R21, R22): the composition now supplies the deadline (D3), and
  task 5.6 returns both drivers to protected purchases.

### Round-1 triage (2026-11-12)

- Reviews and evidence triaged together: review 04 (F1, F2), validation 05 (V1) and
  the owner's record 01 (R1–R30, C1–C11). The decisions are `design.md` D1–D12; its
  "Round-1 triage" section maps each R point to its decision and records Part B's
  contradictions as amendments for the Goal 8 replan, not this change.
- Small repairs outside the scope, each understood and small beside the change
  (owner record 01, R24): VM confirmation scaling an already-total payment by duration
  a second time; Alkahest's projector accepting explicit negotiated `EscrowProposal`
  parameters; the bare-metal introduction fixture using a rateless current option;
  `docs/development/RELEASING.md` listing `arkhai-kit-resource-pools-contracts` for
  `arkhai-vms`; the VM architecture test permitting core carriers, where #350's
  import-guard alignment was kept at the replay.
- V1 fix (validation 05 V1, owner record 01 R4's adaptation, made in the triage):
  `domains/vms/buyer/src/arkhai_vms_buyer/pricing_record.py` retains the listing's
  `pricing` object, compares it whole with the signed publication body, requires the
  lifted `rate_structure` to equal the body's `pricing.rate_structure`, and digests
  that for the round pin. R4's permanent tests are task 5.2. Evidence: VM storefront
  integration suite (integration, `make -C domains/vms/storefront test-integration`)
  575 passed, including `test_buyer_selection_negotiation.py::…reaches_acceptance[True]`,
  which failed at `6f86ac5e6`; VM buyer suite (unit,
  `make -C domains/vms/buyer test`) 256 passed. `scripts/change-workflow run pre-commit`:
  `after-functional-change` passed, exit 0; `pre-commit-functional` ran `make
  check-packaging` (passed) and `make test`, which passed every suite through
  `test-e2e-unit` and then failed once in `test-release-tooling` on
  `scripts/tests/test_change_clone.py::test_the_bootstrap_failed`
  (`ChildProcessError: No child processes` waiting on its spawned bootstrap), a
  workflow-tooling flake unrelated to this diff: rerun, `make test-release-tooling`
  passed 2868, and the targets the failure left unrun (`test-deployment-packaging`,
  `test-frp-grant-admission`, `test-lane-double-controls`, `test-payments-lane-double`,
  `test-mediation-lane-double`) all passed; `pre-commit` passed, exit 0 (index, tasks,
  skills, strict OpenSpec validation, `make check-repository`). The fresh-context
  compliance check found nothing blocking; its findings were fixed: completed tasks 1.3
  and 3.2 keep their text with amendment notes, the shared clause source states that a
  clause list still resolves whole, the ledger lines name record 01, and the proposal's
  Impact and D12's destination heading were corrected. A second
  `scripts/change-workflow run pre-commit` on the final state passed every hook:
  `after-functional-change` exit 0, `pre-commit-functional` exit 0 (`make
  check-packaging` and the whole `make test`, `test-release-tooling` 2868 passed), and
  `pre-commit` exit 0. The commit's validation runs every local suite and the e2e-vm
  lane.
- Documentation corrections the record assigns to the triage (R30's cadence): the
  index row and "pending maintainer review" banners (R1); the `listing_hash` and
  bare-metal Alkahest gap rows (R5, R20); the vendoring premises (R13, R19); the
  tracker sentence in the Compose gap row and the Goal 8 stack's fix-pass attachment,
  whose provenance belongs in Git history (R23); the spec deltas (R25); the `design.md` decisions and `proposal.md`'s scope
  and "Knowledge to promote" (R30).

## 5. Round 2 groundwork: the guard's removal, the buyer's horizon check and the floor

Delivers the work round 2's first session implemented: the amount-read guard removed
(D2, R6), the buyer's accepted-horizon check (D5, review 04 F1, F2) and the floored
default horizon (D5, R9). Touches `scripts/`, the `Makefile`,
`kit/settlement-runtime`, `core/buyer`, both buyers and both storefronts.

Replanned against the reviewed design (2026-11-12). Round 2 — the owner's corrections,
the permanent tests and the review's fixes — was planned as one section 5; its first
session found it larger than one session holds, and the owner returned the change to
planning to split it (`design.md`, "Implementation cadence"). Sections 5–12 are round 2,
reviewed as one implementation round. Each task names the decision it implements;
`design.md` holds the rationale. Before changing an interface
`spot-deals-through-arkhai-payments` consumes, compare with `origin/spot-deals`; its
triage follows. Every section adds the permanent tests of the behaviour it changes at
the level `docs/development/TESTING.md` assigns (R2); sections 11 and 12 add those of
round 1's behaviour that no later section touches.

Former numbers, which earlier notes, the checked tasks' amendments and the reviews
cite: 5.1, 5.3 and 5.4 keep theirs, and 5.3's served-storefront integration case and
its F2 pin-boundary case moved to 6.2; 5.2's tests are split by behaviour across 6.3,
7.3, 8.3, 9.3, 10.3, section 11 and 12.1–12.3; 5.5 → 6.1; 5.6 → 8.1 and 8.2; 5.7 → 10.1
and 10.2; 5.8 → 7.2; 5.9 → 7.1, 9.1 and 9.2; 5.10 → 12.2; 5.11 → 12.5. Section 5's own
verification is the new 5.5.

- [ ] 5.1 **Remove the amount-read guard (R6):** delete
  the guard's script and its JSON inventory under `scripts/`,
  their wiring in the `Makefile`, `scripts/check_change.py` and
  `scripts/tests/test_check_change.py`, and `amount_read_probe.py`. Cover each money
  consumer with a per-period Agreement instead (task 11.3).
  Done: the two scripts and the probe removed with `git rm`; the `Makefile`,
  `scripts/check_change.py` and `scripts/tests/test_check_change.py` are byte-identical
  to `origin/dev`'s again (`git diff origin/dev` on them is empty). The money-consumer
  tests are task 11.3's. `docs/attachments/negotiate-open-ended-compute-terms/reader-guard-checkpoint.md`
  still describes the removed guard as round-1 evidence; closeout's narrative
  compression decides its fate. Implemented; checked once 5.5 passes.
- [ ] 5.3 **The buyer's accepted-horizon check (review 04 F1, F2):** one pure function
  in `kit/settlement-runtime/src/market_settlement_runtime/horizon.py`, sharing
  `resolve_horizon`'s bound arithmetic, taking the Agreement's `start_utc` and
  `duration_seconds`, the buyer's requested horizon and the selected listing's
  `max_duration_seconds` and `available_until_utc`. It refuses a duration above either
  bound at that start, holds an explicit horizon to the request and an omitted one to the
  default bound (floored per R9). Both buyers call it before payment approval: the VM
  accepted-listing seam (`settlement_composition.py`, `validate_buyer_acceptance`) and
  bare metal's acceptance check (`cli.py`, `validate_acceptance`). In the VM buyer's
  `verify_pricing_acceptance`, compare the provision duration with the Agreement's only
  when the buyer requested one (F2). Test at each buyer's acceptance boundary: a signed
  21-hour duration under a 20-hour bound and an end past `available_until_utc`.
  Replanned (2026-11-12): the production-client integration case where an omitted VM
  horizon reaches acceptance, and an F2 case at the pricing-pin boundary, are task 6.2,
  since both need a recurring option in the VM storefront's integration world, whose
  servicing declaration 6.1 reshapes. Implemented; checked once 5.5 passes.
  `check_accepted_horizon` and
  the shared `bound_seconds`/`parse_utc` arithmetic are in `horizon.py`, which
  `resolve_horizon` and `derive_rate_preset` now also use. Bare metal calls it inside
  `buy`'s `validate_acceptance`, after the quote check, so a refusal ends the run as
  `agreement_off_quote` before approval. VM: `validate_buyer_acceptance` takes the
  listing and requested duration; `buyer_client.negotiate_with_seller` binds them when
  it runs the purchase guard with a listing (a resume opens with the seller's echo of
  the buyer's terms), and the core-orchestrated `market buy` path binds them per match
  through a new `acceptance_validator` factory on core's `make_negotiate_hook` (the
  core guard receives only the outcome, so the listing had no other way in).
  `accepted_listing_record` now retains both bounds, so a resumed run checks against
  what was advertised. F2: `verify_pricing_acceptance` compares a provision duration
  only when one is present. Evidence: `make -C kit/settlement-runtime test` (unit)
  208 passed, including `tests/unit/test_horizon.py`'s buyer-check cases (21-hour
  signed duration under a 20-hour bound, end past availability, explicit/omitted
  requests); `make -C domains/vms/buyer test` (unit; `test_buy_orchestrator.py`
  drives the core orchestrator and the VM composition with a stubbed seller
  transport) 258 passed, including two new refusals before any escrow; `make -C
  domains/bare_metal/buyer test` (unit; the `buy` command with replaced factories)
  37 passed, including four new refusals before approval; `make -C core/buyer test`
  (unit) 168 passed. One kept VM orchestrator fixture advertised a 3600-second bound
  under a 7200-second deal; the check now refuses that, so the fixture advertises
  7200. The production-client integration case and the F2 pin-boundary case are
  task 6.2's.
- [ ] 5.4 **The horizon floor and the acceptance hook (R9):** when the buyer names no
  horizon and the limiting bound is a fractional-second `available_until_utc`, floor the
  default horizon to whole seconds instead of refusing, at acceptance
  (`resolve_horizon`) and at publication (R10).
  Done through the one `bound_seconds` both call (a `timedelta`'s normalized days and
  seconds floor it). Evidence: `make -C kit/settlement-runtime test` (unit) 208 passed:
  `test_horizon.py` binds 72000 seconds under a bound 72000.4 seconds away and covers
  the runway's 50-minute spec case, the refusals and a nonpositive relative bound;
  the new `test_rate_publication.py` floors the published default horizon the same
  way and reports no-runway and unbounded candidates. Its `FixtureHelper` is the
  start of the derivation tests 6.3, 7.3 and 8.3 grow. Implemented; checked once 5.5
  passes.
- [ ] 5.5 **Verify the groundwork** (repository obligation: AGENTS.md "Tests and
  diagnostics"; the implementation skill's compliance check). The work is committed in
  `999f2f4d8` without its compliance check or pre-commit run. Rerun on the current
  state: `make -C kit/settlement-runtime test` (unit), `make -C domains/vms/buyer test`
  (unit), `make -C domains/bare_metal/buyer test` (unit), `make -C core/buyer test`
  (unit), `make -C domains/vms/storefront test` (unit and application integration
  through its typed client), `make -C domains/bare_metal/storefront test` (unit and
  application integration), each after `make dist`; then the fresh-context compliance
  check over the section's diff from `adf435188`, `make check-packaging`,
  `make check-comment-hygiene` and `scripts/change-workflow run pre-commit
  negotiate-open-ended-compute-terms`. Fix what they find, then check 5.1, 5.3 and 5.4.
  End-to-end: the reserved purchases (`vms/test_vm_payment_purchase.py`,
  `bare_metal/test_bare_metal_payment_deal.py` under
  `e2e-tests/tests/e2e/roles/scenarios/`) pass through the buyer's accepted-horizon
  check with an explicit reserved duration; none exercises an omitted recurring horizon,
  since no deployed composition publishes a per-period option (the unowned gap in
  `openspec/changes/README.md`), and none is owed by this section.

### Round-2 session checkpoint (2026-11-12)

- One session took 5.1, 5.3 (all but its integration case) and 5.4, then stopped at
  this verified point rather than compact: section 5 spans about a dozen packages and
  every task below is a slice of comparable size, more than one session holds.
- The owner chose to return the change to planning (2026-11-12) to split section 5
  into sections that each fit one session, still reviewed as one round. The work is
  committed as one work-in-progress commit with no task checked: 5.1 and 5.4 are
  implemented and their evidence passes, 5.3 lacks its integration case. The replan
  decides where these land; their notes above give the evidence. The owner accepted
  the Edit-tool reversion of the `Makefile`, `scripts/check_change.py` and
  `scripts/tests/test_check_change.py` after `git checkout origin/dev -- <paths>` was
  denied.
- Also passing on this state: `make -C domains/vms/storefront test` (unit 1180
  passed, 1 skipped; integration 575 passed), `make -C domains/bare_metal/storefront
  test` (611 passed), `make check-comment-hygiene`, `make check-doc-citations
  CHANGE=negotiate-open-ended-compute-terms`, `make check-tasks`. Not yet run: the
  fresh-context compliance check and `scripts/change-workflow run pre-commit`.
- Rebuild before testing a consumer of a changed kit: the domains install kits from
  wheels, so `make dist` first, then each package's `make -C <package> test`, which
  reinstalls them. Run a package's tests through its `make` target; `uv run pytest`
  in a buyer directory fails to resolve its split environments.
- Restart, as replanned: 5.5 verifies and checks this work, then section 6 reshapes
  `RateServicing` and writes 5.3's moved integration and pin cases (6.2), in the same
  session. `kit/settlement-runtime/tests/unit/test_rate_publication.py`'s
  `FixtureHelper` is the place to grow the derivation tests of sections 6–8 (servicing,
  setup gate, penalty multiple, deadline); `test_horizon.py` already covers
  `resolve_horizon` and the runway.

## 6. The servicing declaration and the omitted horizon at the served storefront

Delivers D6's treatments table (R15, R16, R19) at the publication and cached-acceptance
doors, and the served-storefront cases review 04's F1 and F2 left owed (D5). Touches
`kit/settlement-runtime` (`rate_servicing.py`, `rate_publication.py`), both storefronts'
settlement compositions, negotiation runtimes and configuration, and their tests.

- [ ] 6.1 **The servicing declaration (D6; R15, R16, R19):** in
  `kit/settlement-runtime/src/market_settlement_runtime/rate_servicing.py`, replace
  `RateServicing`'s revision map, `published`/`proposed` status and `proposed_lane`
  with a table per mechanism of qualified `settles_through` treatments and `setup`
  (`[settlement.rate_servicing.<mechanism>]`), absent or empty meaning none. Publication
  (both compositions' publication paths:
  `domains/vms/storefront/src/market_storefront/settlement_composition.py`,
  `domains/bare_metal/storefront/src/arkhai_bare_metal_storefront/settlement_composition.py`)
  and cached-acceptance refusal before persistence (both `negotiation_runtime.py`) refuse
  an option naming any undeclared treatment on an entitlement or at the term end, or a
  setup charge without `setup`, keeping the withdrawn-option/refetch outcome; the same
  contract is what spot's materialization reads (`dependency-contracts.md`, "Servicing
  handoff"), which this change does not implement. Admit only where the helper supports
  a treatment and the composition declares it. Deployed compositions declare nothing;
  accepted-deal continuation never reads the declaration. Remove the lane opt-in and its
  fixtures' proposed-revision form.
- [ ] 6.2 **The served-storefront horizon and pin cases (D5; review 04 F1, F2), moved
  from 5.3:** with a declaration injected into the VM storefront's integration world, an
  application-integration case in
  `domains/vms/storefront/tests/integration/test_buyer_selection_negotiation.py` where a
  buyer omitting the horizon on a recurring option reaches acceptance through the served
  storefront and the buyer's `check_accepted_horizon` admits the signed default; and an
  F2 case at the pricing-pin boundary where a buyer that requested no duration passes
  `verify_pricing_acceptance` against the Agreement's resolved `duration_seconds`.
- [ ] 6.3 **Permanent tests of the declaration (R2):** unit, in
  `kit/settlement-runtime/tests/unit/test_servicing.py` and `test_rate_publication.py`
  (grow its `FixtureHelper`): table parsing, absent and empty, an undeclared
  entitlement treatment, an undeclared term-end treatment, a setup charge without
  `setup`, a helper not supporting a declared treatment. Application integration through
  each storefront's typed client with real SQLite (VM
  `tests/integration/test_publication_loop.py`, bare-metal `test_http_publication_rates.py`
  and `test_http_negotiation.py`): publication omits the undeclared candidate while its
  reserved peer and capacity identity stay; a cached undeclared selection gets the signed
  409/refetch with no negotiation rows written.
- [ ] 6.4 **Verify:** `make dist`, then `make -C kit/settlement-runtime test` (unit),
  `make -C domains/vms/storefront test` (unit and application integration),
  `make -C domains/bare_metal/storefront test` (unit and application integration),
  `make -C domains/vms/buyer test` (unit), `make check-comment-hygiene` and
  `scripts/change-workflow run pre-commit negotiate-open-ended-compute-terms`.
  End-to-end: `vms/test_listing_shapes.py` and `bare_metal/test_bare_metal_publication.py`
  publish under the deployed compositions, which declare no servicing, so they show the
  declaration's dark default; none exercises an admitted declaration, and none is owed
  while no deployed composition declares one.

## 7. One shared per-clause publication step and the penalty setting

Delivers D9's shared per-clause step (R26) and D3's configurable penalty multiple
(R11). Touches `kit/settlement-runtime` (`rate_publication.py`), both storefronts'
settlement compositions and `resolve_acceptance` hooks, and both storefronts'
configuration readers.

- [ ] 7.1 **The shared per-clause step (D9; R26), from 5.9:** extract the per-clause
  publication step — deadline resolution, the recurring-or-once branch,
  `derive_rate_preset`, the diagnostics and the penalty setting — from
  `publication_artifacts` (VM `settlement_composition.py`) and `publication_payload`
  (bare-metal `settlement_composition.py`) into one function in
  `kit/settlement-runtime/src/market_settlement_runtime/rate_publication.py`, with the
  `compute` flag and the deadline lookup as parameters so it names no family. Both
  compositions call it; each `resolve_acceptance` hook keeps only its domain's artifact
  rebuilding over `resolve_horizon`. Behaviour is unchanged: the existing publication
  suites pass with their assertions unchanged.
- [ ] 7.2 **The penalty setting (D3; R11), from 5.8:** replace the hard-coded
  `default_penalty_periods=24` with `[pricing].default_premature_stop_penalty_periods`
  (default 24), read in both storefronts' configuration and passed to the shared step;
  a penalty stated on a clause still wins. Validate it as a positive integer at load.
- [ ] 7.3 **Permanent tests (R2):** unit, in `test_rate_publication.py`: the shared
  step's once and recurring branches, its diagnostics for a missing helper, undeclared
  servicing and an unbounded horizon, the default multiple, a configured multiple and a
  clause's own penalty winning; each storefront's configuration test for the setting's
  default, a configured value and a refused nonpositive one.
- [ ] 7.4 **Verify:** `make dist`, then `make -C kit/settlement-runtime test` (unit),
  `make -C domains/vms/storefront test` (unit and application integration, including
  `test_publication_loop.py`, `test_pool_overrides_api.py` and
  `test_listing_identity_carryover.py`), `make -C domains/bare_metal/storefront test`
  (unit and application integration), `make check-comment-hygiene` and
  `scripts/change-workflow run pre-commit negotiate-open-ended-compute-terms`.
  End-to-end: `vms/test_listing_shapes.py`, `bare_metal/test_bare_metal_publication.py`
  and the two reserved purchases read options the shared step now publishes; none
  exercises a recurring option or the penalty, and none is owed (the per-period gap row).

## 8. The delivery deadline's source and the protected E2E purchases

Delivers D3's deadline source (R21) and returns both reserved-payment drivers to
protected purchases (R22). Touches `kit/arkhai-payments`, the shared per-clause step's
deadline parameter in both compositions, and `e2e-tests`.

- [ ] 8.1 **The deadline's source (D3; R21), from 5.6:** the composition supplies the
  deadline to the shared step — the pool port's value when it gives one
  (`delivery_deadline_for_pool`), else the payments clause's configured
  `delivery_deadline_seconds`; `arkhai_payments_option_builder` in
  `kit/arkhai-payments/src/market_arkhai_payments/settlement_config.py` reads it for
  compute options again. A pool value takes precedence over the clause's.
- [ ] 8.2 **The protected E2E purchases (R22), from 5.6:** both reserved-payment drivers
  (`e2e-tests/tests/e2e/roles/scenarios/vms/purchase_driver.py`,
  `e2e-tests/tests/e2e/roles/scenarios/bare_metal/purchase_driver.py`) drop
  `--allow-unprotected-terms` and assert that the published `delivery_deadline_seconds`
  equals the configured value; `e2e-tests/tests/unit/test_dispute_coverage.py` returns
  to its earlier fixtures (task 4.4's reversal).
- [ ] 8.3 **Permanent tests (R2):** unit: the payments builder emitting the configured
  deadline on a compute option and none where unconfigured
  (`kit/arkhai-payments/tests`); the deadline's resolution in both compositions — pool
  value, clause fallback, neither — through the shared step's lookup
  (`test_rate_publication.py` and each storefront's publication unit test); the e2e unit
  suites for the drivers (`e2e-tests/tests/unit/test_dispute_coverage.py`,
  `test_vm_purchase_driver.py`). Application integration through each storefront's typed
  client: a configured clause publishes its deadline on a hosted compute option and a
  default buyer's refusal no longer fires.
- [ ] 8.4 **Verify:** `make dist`, then `make -C kit/arkhai-payments test` (unit),
  `make -C kit/settlement-runtime test` (unit), `make -C domains/vms/storefront test`,
  `make -C domains/bare_metal/storefront test`, `make test-e2e-unit` (unit),
  `make check-comment-hygiene` and `scripts/change-workflow run pre-commit
  negotiate-open-ended-compute-terms`. End-to-end: `vms/test_vm_payment_purchase.py` and
  `bare_metal/test_bare_metal_payment_deal.py` run the protected purchases and assert the
  published deadline; validation's pipeline lanes (e2e-vm, e2e-bare-metal) are the
  evidence for this section.

## 9. One clause source and one reserved-bound rule

Delivers D10's shared clause resolver (R28) and D5's reserved-bound rule in both domains
(R27). Touches `kit/resource-pools-contracts`, `domains/vms/listings`
(`pricing_resolution.py`, `reconciler.py`), the bare-metal storefront (`config.py`,
`publication_terms.py`, `publication.py`), the VM storefront's publication terms and
pool-override models, and `docs/operator-handbook.md`.

- [ ] 9.1 **The shared clause resolver (D10; R28), from 5.9:** move clause and
  listing-term resolution out of `arkhai_vms_listings.pricing_resolution` into
  `kit/resource-pools-contracts` beside `capacity_bounds.py` and `raw_pricing`, taking
  the `gpu` key as data, resolving field by field in D10's order (override > per-model
  pool hint > the new pool-level `pricing.settlements` hint > per-model configuration >
  flat `[pricing]`), bounds in D5's order. Both domains call it; bare metal's
  `pricing.bare_metal.settlements` hint is replaced, with no compatibility path (D12);
  VM's family rates stay in VM. A v0.3.0 VM configuration or hint resolves as before.
- [ ] 9.2 **The reserved-bound rule (D5; R27), from 5.9:** in both domains no positive
  relative maximum means no relative limit; retire `pool_lease_bound_missing` and
  `reserved_lease_bound_missing`, and add the bare-metal upgrade step (the replaced hint
  and the retired diagnostic) to `docs/operator-handbook.md`.
- [ ] 9.3 **Permanent tests (R2):** unit, in `kit/resource-pools-contracts/tests`: each
  tier of D10's order winning field by field, the pool-level hint, a v0.3.0 VM
  configuration and hint unchanged, bounds keeping D5's order; the moved
  `domains/vms/storefront/tests/unit/test_pricing_resolution.py` cases follow the
  resolver. Application integration through each storefront's typed client: a pool-level
  `pricing.settlements` hint publishes its clause in both domains; a reserved option
  publishes without a relative maximum in both domains.
- [ ] 9.4 **Verify:** `make dist`, then `make -C kit/resource-pools-contracts test`
  (unit), `make -C domains/vms/storefront test` (which tests `domains/vms/listings`;
  including `test_reconciler_derivation.py`, `test_reconciler_projection.py`,
  `test_pool_overrides_api.py`), `make -C domains/bare_metal/storefront test`,
  `make check-packaging` (the moved module changes package edges),
  `make check-comment-hygiene` and `scripts/change-workflow run pre-commit
  negotiate-open-ended-compute-terms`. End-to-end: `vms/test_listing_shapes.py`,
  `vms/test_pool_declared_offering_modes.py` and
  `bare_metal/test_bare_metal_publication.py` publish through the resolver; none sets a
  pool-level hint, and none is owed beyond them.

## 10. The buyer's per-term waivers and duration flags

Delivers D11 (R14, R18) in both buyers. Touches `kit/settlement-runtime`
(`buyer_terms.py`), the VM buyer (`buy_cli.py`, `negotiate_cli.py`,
`settlement_composition.py`) and the bare-metal buyer (`cli.py`,
`settlement_composition.py`).

- [ ] 10.1 **Per-term waivers (D11; R14), from 5.7:** in both buyers, one flag per
  default refusal — `--allow-no-delivery-deadline`, `--allow-no-penalty`,
  `--allow-charged-preemption`, `--allow-charged-term-end` — with
  `--allow-unprotected-terms` as shorthand for all four, composed in `BuyerTermsPolicy`;
  the foundation's `allow_missing_delivery_deadline` is set only by the first or the
  shorthand; every waiver used is recorded in run metadata and named in the
  pre-approval disclosure. Codec, capability and authority checks are never waived.
- [ ] 10.2 **Durations (D11; R18), from 5.7:** `bare-metal buy` restores the
  3600-second default for reserved options only, shown as the buyer's default in the
  disclosure, never for recurring ones; VM's `market buy`/`negotiate` gain
  `--duration-seconds` beside `--duration-hours`, both together an error naming the
  conflict.
- [ ] 10.3 **Permanent tests (R2):** unit, in `kit/settlement-runtime/tests/unit`: each
  flag waiving exactly its refusal, the shorthand waiving all four, the foundation flag
  set only by the deadline waiver or the shorthand. Each buyer's CLI suites
  (`domains/vms/buyer/tests/test_buy_resume_cli.py`, `test_explain_cli.py`;
  `domains/bare_metal/buyer/tests`): the flags parsed, recorded in run metadata and named
  in the disclosure; the bare-metal reserved default shown as the buyer's and absent for
  a recurring option; both VM duration flags refused together.
- [ ] 10.4 **Verify:** `make dist`, then `make -C kit/settlement-runtime test` (unit),
  `make -C domains/vms/buyer test` (unit), `make -C domains/bare_metal/buyer test`
  (unit), `make -C core/buyer test` (unit), `make check-comment-hygiene` and
  `scripts/change-workflow run pre-commit negotiate-open-ended-compute-terms`.
  End-to-end: the reserved purchases buy without waivers since section 8; none passes a
  per-term flag, and none is owed, since a flag's effect is the buyer's own policy,
  which the unit suites prove.

## 11. Permanent unit tests of round 1's behaviour

Delivers R2's unit tests for round-1 behaviour no later section touches (D1, D2/D2a,
D5, D7) and R6's per-period money consumers. Touches tests only, in `core`,
`kit/alkahest`, `kit/arkhai-payments`, `kit/contact-exchange`,
`kit/resource-pools-contracts`, `kit/settlement-runtime`, both buyers and the VM
storefront.

- [ ] 11.1 **The accessor and the projections (D2; R2):** `agreed_price` in
  `core/tests/unit/test_rate_helpers.py` and `test_settlement_options.py` — total and
  per-period, sub-hour periods, rounding upward once, the absolute amount fallback and
  refusal of a missing projector; each installed registration's projection (Alkahest,
  payments, contact) — once totals, unsupported rate parameters failing closed.
- [ ] 11.2 **Bounds, the buyer's policy and presentation (D5, D7; R2):** capacity-bound
  validation and tier selection in `kit/resource-pools-contracts/tests`;
  `default_buyer_refusals`, `lifecycle_disclosure` and `present_payment`'s registry checks
  (basis, asset, accepted money unchanged, missing presenter refused) in
  `kit/settlement-runtime/tests/unit`.
- [ ] 11.3 **Every money consumer with a per-period Agreement (D2; R6):** mandate
  derivation (`kit/arkhai-payments/tests`), buyer caps and display, recovery and
  confirmation (`domains/vms/buyer/tests`, `domains/bare_metal/buyer/tests`), each driven
  with a per-period Agreement and asserting the money is read once, never scaled by
  duration or multiplier again.
- [ ] 11.4 **Verify:** `make dist`, then `make -C core test` (unit), `make -C
  kit/alkahest test`, `make -C kit/arkhai-payments test`, `make -C kit/contact-exchange
  test`, `make -C kit/resource-pools-contracts test`, `make -C kit/settlement-runtime
  test`, `make -C domains/vms/buyer test`, `make -C domains/bare_metal/buyer test` (all
  unit), `make check-comment-hygiene` and `scripts/change-workflow run pre-commit
  negotiate-open-ended-compute-terms`. End-to-end: none; no deployed run produces a
  per-period Agreement (the unowned gap in `openspec/changes/README.md`), so these unit
  tests are the money consumers' evidence.

## 12. Permanent integration tests, the retained pricing record and the round's validation

Delivers R2's application-integration tests of round 1's behaviour (D1, D5, D2b), R4's
pin tests and the retained-record confirmation (D2b), the probes' conversion (R2, R7),
and the round's validation. Touches the VM and bare-metal storefronts' integration
suites, the VM buyer and the change's probes.

- [ ] 12.1 **Publication and acceptance through the typed client (D1, D5; R2):** each
  storefront with real SQLite: mixed publication on one capacity identity (reserved,
  on-demand, spot with an injected declaration); a horizon refusal naming the minimum
  that passes the runway.
- [ ] 12.2 **The retained pricing record and pin tests (D2b; R4), from 5.10:** confirm no
  other buyer read compares a top-level `rate_structure` with a signed body (the
  triage's V1 fix covered `pricing_record.py`); application integration through the VM
  storefront's typed client: pin production and verification against a dev-shaped
  publication whose `pricing` object carries the rate structure, a changed pin refused,
  and a legacy record without proof failing closed for multiplier pricing.
- [ ] 12.3 **The probes (R2, R7):** convert the change's probes under
  `openspec/changes/negotiate-open-ended-compute-terms/` that drive real seams into
  tests at the level `docs/development/TESTING.md` assigns, where 11.1–12.2 and sections
  6–10 do not already cover them; task 1.2's codec probe becomes a test or is dropped
  where a `kit/deal-lifecycle` suite covers the round trip. The rest stay as closeout
  evidence; record which went where in this task's note.
- [ ] 12.4 **Verify the section:** `make dist`, then `make -C domains/vms/storefront test`
  and `make -C domains/bare_metal/storefront test` (unit and application integration),
  `make -C domains/vms/buyer test` (unit), and any suite 12.3's conversions land in.
- [ ] 12.5 **Validate the round (R23), from 5.11:** every suite sections 5–12 named,
  `make check-packaging`, `make check-comment-hygiene`, `make check-architecture-change
  CHANGE=negotiate-open-ended-compute-terms` and `scripts/change-workflow run pre-commit
  negotiate-open-ended-compute-terms`. End-to-end: validation's VM and bare-metal lanes —
  the pipeline, or a locally deployed stack where the owner waives the pipeline part —
  covering the protected purchases (`vms/test_vm_payment_purchase.py`,
  `bare_metal/test_bare_metal_payment_deal.py`) and the VM listing-shape lane
  (`vms/test_listing_shapes.py`); an unrun lane is a blocker at closeout.

## 13. Closeout

Documentation-only, in `openspec/README.md#plan-closeout-requirements` order;
anything requiring code returns to implementation. Former numbers 6.1–6.11 are now
13.1–13.11.

- [ ] 13.1 **Comment hygiene:** run `make check-comment-hygiene`; confirm the comments
  rounds 1 and 2 added describe current invariants, not change provenance.
- [ ] 13.2 **Import placement:** confirm the imports the change added are module-level
  unless an experimentally verified circularity or deliberate lazy-load reason is
  recorded, including those of the modules sections 7 and 9 moved.
- [ ] 13.3 **Documentation compliance:** classify D1–D12, including the horizon as the
  Agreement's refinement; verify each permanent home and no duplicated codec/authority
  ownership. Confirm or move D10's shared clause resolver out of
  `kit/resource-pools-contracts`.
- [ ] 13.4 **Narrative compression:** reduce completed-task notes to behavior, material
  evidence, residual work and permanent destinations; retain reasoning in design. Fold
  `design.md`'s dated implementation sections into D1–D12 and remove their narrative;
  decide the fate of the round-1 checkpoint attachments under
  `docs/attachments/negotiate-open-ended-compute-terms/`, including
  `reader-guard-checkpoint.md`, which describes the removed guard.
- [ ] 13.5 **Roadmap currency:** in `docs/development/ROADMAP.md`, close Goal 8's gap
  row "No listing can say how a deal is billed or whether the seller may end it…" and
  update the goal's current state; keep the default-horizon admission row unowned;
  record the disposition in the promotion record.
- [ ] 13.6 **Campaign index currency:** update this change's row and its place in the
  Goal 8 dependency graph in `openspec/changes/README.md`, keep or retire the three
  unowned gap rows under "Unowned work found by `negotiate-open-ended-compute-terms`"
  as what landed decides, and run `scripts/change-workflow run pre-commit
  negotiate-open-ended-compute-terms`, whose default checks include the change index.
- [ ] 13.7 **Packaging:** run `make check-packaging` and
  `make check-architecture-change CHANGE=negotiate-open-ended-compute-terms`; resolve
  all failures/owned exceptions. If the change touched `.agents/`, `.claude/` or
  `.codex/`, confirm the agent-skills check of `scripts/change-workflow run pre-commit`
  passes.
- [ ] 13.8 **End-to-end pipeline:** record the pipeline run/result and the scenarios
  exercising this change: `vms/test_listing_shapes.py`, `vms/test_vm_payment_purchase.py`
  and `bare_metal/test_bare_metal_payment_deal.py` (protected purchases asserting the
  published deadline), and `bare_metal/test_bare_metal_publication.py`. Materialization
  and startup/continuation pipeline evidence belongs to spot and convergence,
  respectively, not this change's closeout. Readiness/dependency failures are explicit
  blockers, never passing evidence or live-deployment claims.
- [ ] 13.9 **Promotion:** promote D1–D12 to the destinations in `design.md`'s
  "Design promotion record": `docs/development/ARCHITECTURE.md` (D1, D2/D2a/D2b with the
  authority description; D12 under "Family kits"), `docs/development/RELEASING.md`
  ("Versioning policy", D12), `openspec/specs/storefront-publication/architecture.md`
  (D5, D6, D9, D10), `openspec/specs/buyer-orchestration/architecture.md` (D7, D8) and
  the bare-metal upgrade step in `docs/operator-handbook.md` (D5, D10). The archive
  merges the deltas into `negotiation-protocol`, `storefront-publication`,
  `resource-pool-management`, `settlement-configuration` and `buyer-orchestration`
  specs; record destinations and identity decision outcomes. No new capability-index
  entry is needed.
- [ ] 13.10 **Documentation citations:** run
  `make check-doc-citations CHANGE=negotiate-open-ended-compute-terms`, resolve all
  matches, then `scripts/change-workflow openspec validate
  negotiate-open-ended-compute-terms --strict`.
- [ ] 13.11 **Archival:** last, run `scripts/change-workflow openspec archive
  negotiate-open-ended-compute-terms -y`, merging the deltas (no `--skip-specs`), and
  link the campaign row to the resulting archive.
