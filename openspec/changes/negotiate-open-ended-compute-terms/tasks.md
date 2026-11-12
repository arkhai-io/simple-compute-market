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
together, reviewed as one round (`design.md`, "Implementation cadence"). Sections 5–11
are done; implementation resumes at section 12. Verification levels follow `docs/development/TESTING.md`;
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

- [x] 5.1 **Remove the amount-read guard (R6):** delete
  the guard's script and its JSON inventory under `scripts/`,
  their wiring in the `Makefile`, `scripts/check_change.py` and
  `scripts/tests/test_check_change.py`, and `amount_read_probe.py`. Cover each money
  consumer with a per-period Agreement instead (task 11.3).
  Done: the two scripts and the probe removed with `git rm`; the `Makefile`,
  `scripts/check_change.py` and `scripts/tests/test_check_change.py` are byte-identical
  to `origin/dev`'s again (`git diff origin/dev` on them is empty). The money-consumer
  tests are task 11.3's. `docs/attachments/negotiate-open-ended-compute-terms/reader-guard-checkpoint.md`
  still describes the removed guard as round-1 evidence; closeout's narrative
  compression decides its fate. Implemented; checked once 5.5 passes. Corrected in 5.5:
  that attachment cited the removed script, inventory, target and probe by path, which
  `AGENTS.md`'s cross-reference rule makes a blocking defect; it now says the guard was
  removed and names them without paths.
- [x] 5.3 **The buyer's accepted-horizon check (review 04 F1, F2):** one pure function
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
  task 6.2's. Corrected in 5.5: the kit suite runs unit and library integration
  tests (its new cases are unit); the VM orchestrator case drives core's orchestrator
  with the seller transport and registry query patched, an orchestration path rather
  than a unit test in `TESTING.md`'s sense. 5.5 added the lower-level and untested
  seams' tests: `domains/vms/buyer/tests/test_accepted_horizon.py` (unit:
  `validate_buyer_acceptance` refusing out-of-bound, off-request and off-default
  horizons before the stage check; the per-listing validator binding its listing;
  `accepted_listing_record` keeping both bounds), two `test_buyer_client.py` cases
  (fresh negotiation refused against the given listing's bound; a resume held to the
  duration it opened with, through the file's patched transport), and core's
  `test_selected_option_negotiation.py` case for `acceptance_validator` alone and
  after the stage's check. The seams' rationale is in `design.md` D5.
- [x] 5.4 **The horizon floor and the acceptance hook (R9):** when the buyer names no
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
  passes. Corrected in 5.5: the kit suite is unit and library integration (the new
  cases are unit); the runway case asserts the refusal below 3000 seconds and the
  admission at 3000, not the last-instant approval clause of the spec scenario.
- [x] 5.5 **Verify the groundwork** (repository obligation: AGENTS.md "Tests and
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
  Done (2026-11-12), after `make dist`: `make -C kit/settlement-runtime test` (unit and
  library integration) 208 passed; `make -C domains/bare_metal/buyer test` (unit, the
  `buy` command with replaced factories) 37 passed; `make -C domains/vms/storefront test`
  unit 1180 passed, 1 skipped, application integration 575 passed;
  `make -C domains/bare_metal/storefront test` (unit and application integration) 611
  passed. The fresh-context compliance check found seven problems, fixed as the 5.1,
  5.3 and 5.4 corrections record: suite labels, the orchestration case's level, the
  runway claim, three seams without tests, the attachment's dead citations, the buyer
  check's seams without a decision or destination (now `design.md` D5 and the promotion
  record), and a test docstring naming a planned step. After the fixes `make -C
  domains/vms/buyer test` (unit; two cases through the file's patched seller transport)
  266 passed and `make -C core/buyer test` (unit) 170 passed. Its re-check found them
  resolved. Declined: its note that the new `test_buyer_client.py` and core cases
  patch module names, as each file's existing cases do — `TESTING.md` records that the
  CLIs other than bare metal's still replace imported names, and the new direct unit
  tests in `test_accepted_horizon.py` patch nothing; and its observation that the
  `validate_acceptance is validate_buyer_acceptance` test in `buyer_client.py` would
  skip a wrapped guard, since production passes only the default or None
  (`introduction_cli.py`). `make check-comment-hygiene` passed;
  `scripts/change-workflow run pre-commit negotiate-open-ended-compute-terms` passed
  every hook (`after-functional-change`, `pre-commit-functional` with `make
  check-packaging` and the whole `make test`, `pre-commit`), and again on the final
  state before the commit.

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
  CHANGE=negotiate-open-ended-compute-terms`, `make check-tasks`. The fresh-context
  compliance check and `scripts/change-workflow run pre-commit` then ran under 5.5.
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

- [x] 6.1 **The servicing declaration (D6; R15, R16, R19):** in
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
  Implemented, uncommitted (2026-11-12); checked once 6.4 passes. `rate_servicing.py`:
  `RateServicingDeclaration(mechanism, treatments, setup)`, treatments named as the
  payment authority names them (`charged`, `returned`, `prorated`, through
  `PARTIAL_PERIOD`); `RateServicing(declarations)` with `from_tables`, `select`
  (refusing absent or empty), `require(mechanism, treatments, setup=)` and
  `require_option`, which reads the option's entitlement and term-end treatments from
  its lifecycle and treats `setup_amount` beside a rate marker as a setup charge.
  `derive_rate_preset` checks the preset's treatments (the payer's `started_period`,
  the payee's and the term end's) and setup with `require` before the helper runs;
  the helper's `supports_setup_delivery_end` is kept, so setup needs both. The
  configuration: the seller's `[Settlement]` root takes `rate_servicing` (a buyer's
  refuses it), read into `SettlementConfig.rate_servicing`; the VM builder and bare
  metal's `from_raw_config` pass it to the composition's `rate_servicing`. Neither
  negotiation runtime needed a change: both already call `require_option`. Outside the
  plan's file list, as the configuration key requires: `kit/config`'s
  `settlement_fragment` adds the seller's `rate_servicing` to the generated values
  schema, and `make helm-values-schema` regenerated `helm/values.schema.json` and both
  storefront charts' schemas; both storefronts' values-schema tests name the key. The
  change's `recurring_publication_probe.py` uses the new declaration (not run here).
  `dependency-contracts.md`'s "Servicing handoff" names what spot's branch must follow.
  Corrected after the compliance check (2026-11-12): the table's shape had two
  hand-written copies, the loader's and the values schema's; it is now one typed model,
  `RateServicingTable` in `rate_servicing.py` (`treatments` a list of the authority's
  names as a `Literal`, `setup` a strict boolean, extra keys forbidden), which
  `from_tables` validates against and `settlement_fragment` renders with
  `model_fragment`, so the regenerated Helm schemas enumerate the treatment names.
  The seller-only table, its keys and its refusals are now in the change's
  settlement-configuration delta (a buyer-root scenario added) and in D6, which also
  records the integration worlds' fixtures at the composition ports no installed
  mechanism supplies. The builder path from a configured table to the composition is
  tested: `domains/vms/storefront/tests/unit/test_settlement_composition.py` and
  `domains/bare_metal/storefront/tests/test_app_composition.py`, each
  `test_the_configured_rate_servicing_declaration_is_the_compositions` (unit: the
  builder given a raw seller root with a `rate_servicing` table; the composition's
  declaration is the configuration's object and selects the declared treatments).
- [x] 6.2 **The served-storefront horizon and pin cases (D5; review 04 F1, F2), moved
  from 5.3:** with a declaration injected into the VM storefront's integration world, an
  application-integration case in
  `domains/vms/storefront/tests/integration/test_buyer_selection_negotiation.py` where a
  buyer omitting the horizon on a recurring option reaches acceptance through the served
  storefront and the buyer's `check_accepted_horizon` admits the signed default; and an
  F2 case at the pricing-pin boundary where a buyer that requested no duration passes
  `verify_pricing_acceptance` against the Agreement's resolved `duration_seconds`.
  Found while planning it: the production VM buyer client cannot open a
  recurring payments negotiation — `negotiate_with_seller` sizes its bounds with
  `priced_unit_count`, which projects through the installed buyer registry, and the
  installed payments projection refuses rate parameters (D2's projection). So the
  omitted-horizon case drives the served storefront through its typed client, as
  `horizon_probe.py`'s `exercise` does with an injected `billing`/`timing` and
  `ProposedPayments`, and runs `check_accepted_horizon` on the signed Agreement with
  the listing's bounds; the F2 case calls `verify_pricing_acceptance` with an
  injected per-period projection on a served shape-priced reply. Record this in the
  note as the case's actual reach.
  Done (2026-11-12), at that reach: two application-integration cases in
  `test_buyer_selection_negotiation.py` over `tests/recurring_world.py` (below, 6.3).
  `test_an_omitted_horizon_is_accepted_at_the_default_bound_the_buyer_checks` opens a
  recurring on-demand option with no duration through the buyer's typed
  `StorefrontClient` against the served app; the seller signs 7200 seconds (the pool's
  relative bound), the signed provision terms carry no duration, and
  `check_accepted_horizon` admits it with `requested_duration_seconds=None` against the
  served listing's bounds (its refusals are the unit suites' of 5.3).
  `test_a_buyer_that_named_no_duration_verifies_the_accepted_pricing` publishes a
  shape-priced recurring option (the pool's H100 family rate, the clause rateless,
  since a shape-priced listing refuses a clause's own rate), opens at 10000 basis
  points with no duration, and passes `verify_pricing_acceptance` on the served
  accepting reply, with the record `retained_pricing_record` keeps from the
  registry-shaped listing (the signed publication the existing shape-priced case
  builds, now its shared `_as_published` helper) and the world's per-period
  projection. The provision-duration comparison F2 made conditional would refuse it,
  since the signed provision terms carry no duration (read from the code, not run).
  Neither case runs the production buyer client or its core guard, for the reason above.
- [x] 6.3 **Permanent tests of the declaration (R2):** unit, in
  `kit/settlement-runtime/tests/unit/test_servicing.py` and `test_rate_publication.py`
  (grow its `FixtureHelper`): table parsing, absent and empty, an undeclared
  entitlement treatment, an undeclared term-end treatment, a setup charge without
  `setup`, a helper not supporting a declared treatment. Application integration through
  each storefront's typed client with real SQLite (VM
  `tests/integration/test_publication_loop.py`, bare-metal `test_http_publication_rates.py`
  and `test_http_negotiation.py`): publication omits the undeclared candidate while its
  reserved peer and capacity identity stay; a cached undeclared selection gets the signed
  409/refetch with no negotiation rows written.
  Unit part done, uncommitted: `kit/settlement-runtime/tests/unit/test_rate_servicing.py`
  (a new file: `test_servicing.py` already holds the servicing worker's tests) covers
  table parsing, absent/no-treatments/empty, malformed tables, a once option, declared
  admission, an undeclared entitlement and term-end treatment, setup without `setup`
  and either rate marker alone; `test_rate_publication.py`'s `FixtureHelper` takes
  supported treatments and setup support, with cases for each undeclared treatment and
  setup (the helper never builds an option), a declared charged term end, a declared treatment
  the helper cannot enforce and declared setup without the helper's support;
  `test_configuration.py` covers the seller root's table and the buyer's refusal;
  `kit/config`'s values-schema test covers both roles. Evidence on this state:
  `make -C kit/settlement-runtime test` (unit and library integration) 236 passed;
  `make -C kit/config test` (unit) 273 passed; after `make dist`, `make -C
  domains/vms/storefront test` unit 1180 passed, 1 skipped, application integration
  575 passed; `make -C domains/bare_metal/storefront test` 611 passed; `make
  check-comment-hygiene` passed. Application-integration cases not started: build a
  recurring world from `recurring_publication_probe.py`'s `vm`/`bare` factories (a real
  composition with `rate_servicing`, a fixture helper, `rate_term_projections` and the
  deadline port) as a shared module in each storefront's tests.
  Application-integration part done (2026-11-12). Each storefront's tests gain a
  `recurring_world.py`: the real settlement composition over the running app (VM:
  `publication_app` with a `VmSettlementComposition`; bare metal: `_derivation_runtime`
  with its composition replaced), with a mutable payments declaration, a fixture preset
  helper, the term timing and the pool's deadline injected, and one pool bounded at
  7200 seconds publishing a reserved Alkahest clause, a once payment, an on-demand and
  a spot preset. VM `test_publication_loop.py` and bare-metal
  `test_http_publication_rates.py`:
  `test_publication_omits_recurring_options_whose_treatments_are_undeclared` publishes
  four options under the full declaration, then, declaring `charged` alone, the next
  cycle keeps the listing's identity with exactly its reserved and once options and
  reports two `rate_servicing_undeclared` refusals naming the undeclared `returned`.
  VM `test_publication_loop.py` and bare-metal `test_http_negotiation.py`:
  `test_a_cached_recurring_selection_whose_treatment_is_withdrawn_is_refused` selects
  the published on-demand option after the declaration narrows: the typed client
  raises the signed 409 `settlement_option_withdrawn_refetch` naming the undeclared
  `returned`, and `negotiation_threads` is unchanged. The absent/empty declaration and
  the setup-charge refusal stay at unit level (one representative integration case per
  behaviour, `TESTING.md`). Changing the injected declaration mid-test stands for a
  restart under a narrower one: publication and negotiation share the one object the
  composition holds; the configured table reaching that object is the unit tests' of
  6.1's correction.
  Evidence on the final state, after `make dist` and `make helm-values-schema`: `make
  -C kit/settlement-runtime test` (unit and library integration) 237 passed; `make -C
  kit/config test` (unit) 273 passed; `make -C domains/vms/storefront test` unit 1181
  passed, 1 skipped, application integration 579 passed (the four new cases of 6.2 and
  6.3 among them); `make -C domains/bare_metal/storefront test` (unit and application
  integration) 614 passed; `make -C domains/vms/buyer test` (unit) 266 passed.
- [x] 6.4 **Verify:** `make dist`, then `make -C kit/settlement-runtime test` (unit and
  library integration),
  `make -C domains/vms/storefront test` (unit and application integration),
  `make -C domains/bare_metal/storefront test` (unit and application integration),
  `make -C domains/vms/buyer test` (unit), `make check-comment-hygiene` and
  `scripts/change-workflow run pre-commit negotiate-open-ended-compute-terms`.
  End-to-end: `vms/test_listing_shapes.py` and `bare_metal/test_bare_metal_publication.py`
  publish under the deployed compositions, which declare no servicing, so they show the
  declaration's dark default; none exercises an admitted declaration, and none is owed
  while no deployed composition declares one.
  Done (2026-11-12): every suite named passed, with `make -C kit/config test` added for
  the values-schema change; comment hygiene and every pre-commit hook passed (the
  section's "verification and handoff" notes below). End-to-end confirmed as stated: no
  marker in `e2e-tests/` exercises an admitted declaration; the two publication
  scenarios exercise the empty deployed declaration. No `Owed by validation:` evidence:
  no CI workflow a push alone produces bears on this section.

### Section 6 verification and handoff (2026-11-12)

- 6.4's evidence on the final code: `make dist`, then the suites in 6.3's last note (all
  passed); `make check-comment-hygiene` passed; `scripts/change-workflow run pre-commit
  negotiate-open-ended-compute-terms` passed every hook — `after-functional-change` exit
  0, `pre-commit-functional` exit 0 (`make check-packaging` and the whole `make test`),
  `pre-commit` exit 0 (index, tasks, skills, strict OpenSpec validation, `make
  check-repository` with its version-bump check against `dev`), and again, every hook
  passing, after `design.md`'s promotion row and these notes changed.
- The fresh-context compliance check found eight problems and six overstated claims;
  6.1's correction and 6.2/6.3's notes record the fixes. Its re-check found them
  resolved but two:
  - The integration worlds put fixtures at composition ports (the preset helper, term
    timing, billing projection, accepted payment data) rather than only at external
    I/O (`TESTING.md`, "Integration Tests"). No installed mechanism supplies those ports,
    and `tests/publication_app.py` already stands a composition double where the
    mechanism clients would. Kept, recorded in D6 and given a destination in its
    promotion row; whether `TESTING.md` should name the practice is the round's review's
    to judge.
  - Versions: no package this change touched is bumped against `dev` (settlement-runtime
    is 0.8.0 on both), though `RateServicing` changed incompatibly and `kit/config`'s
    `values_schema.py` now imports `RateServicingTable`, which a released 0.8.0 lacks,
    under its exact pin `arkhai-kit-settlement-runtime==0.8.0`. The repository's
    version-bump check passes, so 0.8.0 is presumably still unreleased on `dev`
    (`docs/development/RELEASING.md`, "Versioning policy": an unreleased version is not
    bumped again); the round's triage should confirm it, and if 0.8.0 is released, bump
    settlement-runtime a minor version and move that pin and the others on it.
- For the next sections: each storefront's `tests/recurring_world.py` is the recurring
  world the later integration cases (7.3's shared step, 8.3's deadline, 12.1, 12.2) can
  grow. The VM world's `published`/`pricing` arguments make a shape-priced listing; a
  shape-priced listing refuses a clause that states its own rate, so its recurring
  clause is rateless and the fixture helper quotes `SHAPE_RATE`. Both worlds hold the
  deadline at 1200 seconds through `delivery_deadline_for_pool`, which section 8's
  deadline source replaces. Running a single test file is denied here: the storefronts'
  `uv run pytest` cannot resolve their split environments, and only the whole `make -C
  <package> test`/`test-integration` targets run (about 30 seconds for VM integration,
  50 for bare metal). Each storefront environment must be reinstalled (its `test`
  target) after `make dist` before `make helm-values-schema`, which runs with
  `--no-sync` and otherwise renders the old `kit/config`.

### Section 6 session checkpoint (2026-11-12)

- The session that verified section 5 implemented 6.1 and 6.3's unit tests, then
  stopped at this verified point rather than compact: sections 5 and 6 together grew
  past what one session holds, the cadence's own risk. Nothing of section 6 is
  committed; its worktree changes are the section's.
- Restart: 6.3's application-integration cases, then 6.2 (see its note for the
  production client's limit), then 6.4: `make dist`, the suites it names,
  `make check-packaging` (the regenerated Helm schemas and `kit/config`'s change),
  the fresh-context compliance check over the section's diff from `dfa8871fb`, and
  `scripts/change-workflow run pre-commit negotiate-open-ended-compute-terms`.
- Never edit files while a background `make test` or `pre-commit` runs: the wheels it
  builds and the suites it reads can pick up a half-made edit.

## 7. One shared per-clause publication step and the penalty setting

Delivers D9's shared per-clause step (R26) and D3's configurable penalty multiple
(R11). Touches `kit/settlement-runtime` (`rate_publication.py`), both storefronts'
settlement compositions and `resolve_acceptance` hooks, and both storefronts'
configuration readers.

- [x] 7.1 **The shared per-clause step (D9; R26), from 5.9:** extract the per-clause
  publication step — deadline resolution, the recurring-or-once branch,
  `derive_rate_preset`, the diagnostics and the penalty setting — from
  `publication_artifacts` (VM `settlement_composition.py`) and `publication_payload`
  (bare-metal `settlement_composition.py`) into one function in
  `kit/settlement-runtime/src/market_settlement_runtime/rate_publication.py`, with the
  `compute` flag and the deadline lookup as parameters so it names no family. Both
  compositions call it; each `resolve_acceptance` hook keeps only its domain's artifact
  rebuilding over `resolve_horizon`. Behaviour is unchanged: the existing publication
  suites pass with their assertions unchanged.
  Done (2026-11-12): `ClausePublication` in `rate_publication.py`, a frozen dataclass of
  what is fixed per composition (registry, configuration, servicing declaration, preset
  helpers, dispute authorities and interfaces, `compute`, the penalty multiple, an
  injected clock) whose `publish(status, clause, *, resources, delivery_deadline,
  max_duration_seconds, available_until_utc, diagnose)` resolves the deadline through
  the `delivery_deadline` lookup, branches recurring (`derive_rate_preset`) or once
  (`registry.build_option` with the dispute, compute, deadline and clause resources),
  then admits each built option against the declaration and reports default-buyer
  refusals, returning `ClauseArtifacts`. A `clause` of `None` is VM's no-clauses path,
  built from the mechanism's section. Both compositions construct it inline in
  `publication_artifacts`/`publication_payload` and keep readiness, the enabled/ready
  filtering and, in bare metal, the `reserved_lease_bound_missing` hold before the step
  (section 9 retires it). The resolve-acceptance hooks were already only domain artifact
  rebuilding over `resolve_horizon`; nothing moved there. Two choices made to keep
  behaviour: the step publishes each option as its builder built it (VM's form; bare
  metal re-dumped its validated model, the same canonical option since its ID is checked
  against its payload), validation being the servicing check's `require_option`, which
  validates every option whole in production; and a builder returning no mapping raises
  `ValueError` (bare metal's) where VM raised `RuntimeError` — VM's listing creation
  converts both to `ValueError`, while `reconcile_settlement_options`, which no
  production path calls, now raises `ValueError` there; no installed builder returns
  anything but a mapping. VM's readiness no longer receives the deadline, dispute
  and compute keys, which no readiness reads (only the payments option builder does).
  The deadline lookup now runs per published clause rather than once per candidate.
  `clause` stays typed `Any`: `publication.py` imports `rate_publication`, so naming
  `SettlementPublicationClause` there would be a cycle. Existing suites: the only edit
  to them is `default_penalty_periods=24` on the two namespace compositions
  `tests/unit/test_settlement_publication.py` passes as `self`; no assertion changed.
- [x] 7.2 **The penalty setting (D3; R11), from 5.8:** replace the hard-coded
  `default_penalty_periods=24` with `[pricing].default_premature_stop_penalty_periods`
  (default 24), read in both storefronts' configuration and passed to the shared step;
  a penalty stated on a clause still wins. Validate it as a positive integer at load.
  Done (2026-11-12): `DEFAULT_PREMATURE_STOP_PENALTY_PERIODS = 24` and the shared
  setting type `PenaltyPeriods` (strict int, > 0) in `rate_publication.py`. VM:
  `utils/config.py` `default_premature_stop_penalty_periods()` reads the Dynaconf key,
  refused by key unless a positive integer, called among `server.py`'s startup refusals
  and by `build_vm_settlement_composition`, which sets the composition's new
  `default_penalty_periods`. Bare metal: `PricingSettings.default_premature_stop_penalty_periods:
  PenaltyPeriods = 24`, refused by `load_storefront_settings` naming the key; `runtime.py`
  passes it to `from_raw_config(default_penalty_periods=...)`. Both packaged
  `settings.toml` state 24. Outside the plan's file list, as the bare-metal settings model
  renders the chart's schema: `make helm-values-schema` regenerated
  `helm/charts/bare-metal-storefront/values.schema.json` (VM's `[pricing]` is untyped in
  its schema). The change's storefront-publication delta now states the startup refusal,
  with a scenario.
- [x] 7.3 **Permanent tests (R2):** unit, in `test_rate_publication.py`: the shared
  step's once and recurring branches, its diagnostics for a missing helper, undeclared
  servicing and an unbounded horizon, the default multiple, a configured multiple and a
  clause's own penalty winning; each storefront's configuration test for the setting's
  default, a configured value and a refused nonpositive one.
  Done (2026-11-12). Unit, `kit/settlement-runtime/tests/unit/test_rate_publication.py`
  (the step with a `MagicMock` registry and the file's `FixtureHelper`): a once clause
  built by the registry with exactly the composition's resources; a mechanism with no
  clause built without one; a once option lacking a deadline published with its
  default-buyer diagnostic; a built rate option the declaration withholds omitted; a
  recurring clause derived through its helper, never the registry; missing helper,
  undeclared servicing and unbounded horizon each omitted with its diagnostic; the
  default 24-period multiple, a configured 6, a clause's own `"0"` and `"1000"` winning,
  spot carrying none. Configuration, unit: VM `tests/unit/test_config_loader.py`
  (packaged and unstated default 24, a stated 6, and 0, -1, 1.5, `"24"`, `True` refused
  by key with no exception context); bare metal `tests/test_config_loader.py` (packaged
  default in the defaults test, a stated 6 through the files, 0, -3 and 1.5 refused by
  key). Bare metal's refusal is its startup path's, `load_storefront_settings`; VM's
  tests cover the reader, not its call among `server.py`'s startup refusals, which no
  test drives (the multiplier floor's call is untested the same way). Builder to composition, unit: VM `tests/unit/test_settlement_composition.py` and
  bare metal `tests/test_app_composition.py`,
  `test_the_configured_penalty_multiple_is_the_compositions` (bare metal through
  `build_runtime_from_configuration`). Added beyond the plan, application integration
  through each storefront's typed client over its `tests/recurring_world.py` (which
  gains a `default_penalty_periods` argument): VM `test_publication_loop.py` and
  bare-metal `test_http_publication_rates.py`,
  `test_an_on_demand_option_stating_no_penalty_publishes_the_configured_multiple`: under
  a multiple of 6 the published on-demand option carries 6 × 625000 and spot none, which
  proves the composition hands its multiple to the step (the composition is built by the
  world, so configuration reaching it is the unit tests').
- [x] 7.4 **Verify:** `make dist`, then `make -C kit/settlement-runtime test` (unit and
  library integration),
  `make -C domains/vms/storefront test` (unit and application integration, including
  `test_publication_loop.py`, `test_pool_overrides_api.py` and
  `test_listing_identity_carryover.py`), `make -C domains/bare_metal/storefront test`
  (unit and application integration), `make check-comment-hygiene` and
  `scripts/change-workflow run pre-commit negotiate-open-ended-compute-terms`.
  End-to-end: `vms/test_listing_shapes.py`, `bare_metal/test_bare_metal_publication.py`
  and the two reserved purchases read options the shared step now publishes; none
  exercises a recurring option or the penalty, and none is owed (the per-period gap row).
  Done (2026-11-12): `make dist`; `make -C kit/settlement-runtime test` (unit and library
  integration) 250 passed; `make -C domains/vms/storefront test` unit 1188 passed, 1
  skipped, application integration 580 passed (including `test_publication_loop.py`,
  `test_pool_overrides_api.py`, `test_listing_identity_carryover.py`); `make -C
  domains/bare_metal/storefront test` (unit and application integration) 620 passed,
  after `make helm-values-schema`; `make check-comment-hygiene` passed;
  `scripts/change-workflow run pre-commit negotiate-open-ended-compute-terms` passed every
  hook (see the handoff below). End-to-end confirmed as stated: no marker in
  `e2e-tests/` names a recurring option, a premature-stop penalty or the setting; the
  four scenarios exercise once and reserved options through the shared step's once
  branch. No `Owed by validation:` evidence: no CI workflow a push alone produces bears
  on this section.

### Section 7 verification and handoff (2026-11-12)

- Pre-commit on the section's code: `after-functional-change` exit 0 (nothing rebuilt),
  `pre-commit-functional` exit 0 (`make check-packaging` and the whole `make test`),
  `pre-commit` exit 0 (index, tasks, skills, strict OpenSpec validation, `make
  check-repository` with version bumps against `dev`). Rerun after the compliance fixes
  below, on the final code: every hook passed again, each exit 0.
- The fresh-context compliance check found nothing blocking. Fixed: `ClausePublication`'s
  docstring claimed every storefront composes it (API credits still calls
  `build_option` itself; it publishes no recurring option); 7.1's note overstated the
  `ValueError` conversion; 7.3's note now says VM's startup call of the reader is
  untested; the deployment guide's storefront-wide `[pricing]` keys
  (`docs/development/DEPLOYMENT_AND_CONFIG.md`) became a destination for the setting in
  D3's promotion row and task 13.9; a reflowed D9 line. Declined: nothing.
- For the next sections: section 8's deadline source belongs in `ClausePublication.publish`'s
  deadline resolution (today `effective_delivery_deadline(delivery_deadline())`), where
  the clause is at hand for its configured fallback; both compositions pass their
  `delivery_deadline_for_pool` bound to the candidate's site and pool as the lookup, so
  the precedence can live in the step without either composition changing. The
  payments builder's once-branch resources already carry `compute` and
  `delivery_deadline_seconds`; `arkhai_payments_option_builder` currently publishes the
  clause's own deadline only for non-compute options. Section 9 removes bare metal's
  `reserved_lease_bound_missing` hold, which sits in `publication_payload` just before
  the step's call. The recurring worlds take `default_penalty_periods`; tests construct
  the step with an injected `clock`.

## 8. The delivery deadline's source and the protected E2E purchases

Delivers D3's deadline source (R21) and returns both reserved-payment drivers to
protected purchases (R22). Touches `kit/arkhai-payments`, the shared per-clause step's
deadline parameter in both compositions, and `e2e-tests`.

- [x] 8.1 **The deadline's source (D3; R21), from 5.6:** the composition supplies the
  deadline to the shared step — the pool port's value when it gives one
  (`delivery_deadline_for_pool`), else the payments clause's configured
  `delivery_deadline_seconds`; `arkhai_payments_option_builder` in
  `kit/arkhai-payments/src/market_arkhai_payments/settlement_config.py` reads it for
  compute options again. A pool value takes precedence over the clause's.
  Done (2026-11-12). The clause's value is in its mechanism-owned input, which the
  shared step never parses, so the precedence sits where the mechanism reads it
  (recorded in `design.md` D3): `arkhai_payments_option_builder` takes the
  `delivery_deadline_seconds` resource (the pool's, which the step passes) for a compute
  option when it is not `None`, else its clause's own; a non-compute option still takes
  only its clause's. For recurring clauses, `RatePresetPricing` gains
  `delivery_deadline_seconds` (default `None`, refused unless positive whole seconds),
  the clause's value as the helper reads it, which `derive_rate_preset` uses only when
  the pool gives none. Neither composition changed: both already pass their
  `delivery_deadline_for_pool` bound to the candidate's site and pool. This adds a
  field to an interface spot consumes (`origin/spot-deals`' `PaymentsRatePresetHelper`
  constructs `RatePresetPricing` positionally for its first four fields, so the
  defaulted field does not break it); `dependency-contracts.md`'s servicing handoff
  names the one line spot's helper must add.
- [x] 8.2 **The protected E2E purchases (R22), from 5.6:** both reserved-payment drivers
  (`e2e-tests/tests/e2e/roles/scenarios/vms/purchase_driver.py`,
  `e2e-tests/tests/e2e/roles/scenarios/bare_metal/purchase_driver.py`) drop
  `--allow-unprotected-terms` and assert that the published `delivery_deadline_seconds`
  equals the configured value; `e2e-tests/tests/unit/test_dispute_coverage.py` returns
  to its earlier fixtures (task 4.4's reversal).
  Done (2026-11-12): both drivers no longer pass `--allow-unprotected-terms` and again
  assert `option.lifecycle["delivery_deadline_seconds"]` equals the configured value
  (VM: `delivery_deadline_seconds()`, the lane's `VM_DELIVERY_DEADLINE_SECONDS`; bare
  metal: `DELIVERY_DEADLINE_SECONDS`, which its pool override's payments clause states);
  `test_dispute_coverage.py`'s `_option_for` again publishes the clause's deadline and
  its refusal case is again an option with another allowance. `git diff 6f86ac5e6~1 --
  e2e-tests/tests/` is empty: the three files are as they were before round 1. In both
  lanes the deadline now publishes through 8.1's clause fallback, since no deployed
  composition supplies a pool deadline.
- [x] 8.3 **Permanent tests (R2):** unit: the payments builder emitting the configured
  deadline on a compute option and none where unconfigured
  (`kit/arkhai-payments/tests`); the deadline's resolution in both compositions — pool
  value, clause fallback, neither — through the shared step's lookup
  (`test_rate_publication.py` and each storefront's publication unit test); the e2e unit
  suites for the drivers (`e2e-tests/tests/unit/test_dispute_coverage.py`,
  `test_vm_purchase_driver.py`). Application integration through each storefront's typed
  client: a configured clause publishes its deadline on a hosted compute option and a
  default buyer's refusal no longer fires.
  Done (2026-11-12). Unit, `kit/arkhai-payments/tests/test_settlement_config.py`
  (`arkhai_payments_option_builder` called directly):
  `test_publication_builder_publishes_the_pool_deadline_else_the_clause_s` — a compute
  option takes the clause's 900 with no pool value, the pool's 1200 over the clause's,
  the pool's alone, and neither; a non-compute option takes its clause's, never the
  pool's; the deadline is never a settlement parameter. Unit,
  `kit/settlement-runtime/tests/unit/test_rate_publication.py` (the step with a
  `MagicMock` registry; `FixtureHelper` gains a clause `deadline`): a recurring option
  publishes the pool's 1200 over the clause's 600, else the clause's 600; with neither
  it publishes without the term and with the default buyer's "no delivery deadline"
  diagnostic; a once clause's builder is handed `None` when the pool gives none; a
  clause deadline of 0, -1, 1.5 or `"600"` is refused by `RatePresetPricing`. Unit,
  each composition's lookup: VM `tests/unit/test_settlement_publication.py` and bare
  metal `tests/test_app_composition.py`,
  `test_the_pool_port_s_deadline_for_the_candidate_reaches_the_option_builder` — the
  composition calls `delivery_deadline_for_pool` once with the candidate's site and pool
  and hands its value, or `None`, to the registry's builder with `compute` set (VM over
  the file's namespace composition with `build_option` replaced; bare metal through
  `from_raw_config` over a contact root, `build_option` wrapped). This departs from
  the plan's line: the composition unit tests prove only the pool's value or `None`
  reaching the builder, since the clause fallback is the mechanism's, not the
  composition's; the fallback and the neither case per domain are the integration
  cases' below, and the payments builder's own matrix above. The e2e unit suites
  (`make test-e2e-unit`) cover 8.2's fixtures. Application integration through each
  storefront's typed client over its `tests/recurring_world.py`, which gains
  `pool_deadline` (bare metal also `clause_deadline`; VM's `clauses()` takes the
  deadline) and whose fixture helper returns the clause's deadline as a mechanism's
  would: VM `tests/integration/test_publication_loop.py` and bare-metal
  `tests/test_http_publication_rates.py`,
  `test_a_clause_s_deadline_publishes_where_the_pool_supplies_none` — with no pool
  deadline, the once, on-demand and spot payment options each publish their clause's
  900 and the cycle reports no `default_buyer_refusal`; with no clause deadline either,
  none carries the term and the cycle reports three. The once option there is built by
  the real payments builder; the recurring ones by the world's fixture helper, since no
  installed mechanism supplies one.
- [x] 8.4 **Verify:** `make dist`, then `make -C kit/arkhai-payments test` (unit),
  `make -C kit/settlement-runtime test` (unit and library integration),
  `make -C domains/vms/storefront test`,
  `make -C domains/bare_metal/storefront test`, `make test-e2e-unit` (unit),
  `make check-comment-hygiene` and `scripts/change-workflow run pre-commit
  negotiate-open-ended-compute-terms`. End-to-end: `vms/test_vm_payment_purchase.py` and
  `bare_metal/test_bare_metal_payment_deal.py` run the protected purchases and assert the
  published deadline; validation's pipeline lanes (e2e-vm, e2e-bare-metal) are the
  evidence for this section.
  Done (2026-11-12), after `make dist`: `make -C kit/arkhai-payments test` (unit, with
  mypy, vectors and generated-model checks) 227 passed; `make -C kit/settlement-runtime
  test` (unit and library integration) 258 passed, rerun after the compliance fixes;
  `make -C domains/vms/storefront test` unit 1190 passed, 1 skipped, application
  integration 582 passed; `make -C domains/bare_metal/storefront test` (unit and
  application integration) 624 passed, rerun on the final code after a fresh `make
  dist`; `make test-e2e-unit` (unit) 896 passed, 1 skipped; `make check-comment-hygiene`
  and `make check-doc-citations CHANGE=negotiate-open-ended-compute-terms` passed;
  `scripts/change-workflow run pre-commit negotiate-open-ended-compute-terms` on the
  final state passed every hook — `after-functional-change` exit 0 (nothing rebuilt),
  `pre-commit-functional` exit 0 (`make check-packaging` and the whole `make test`),
  `pre-commit` exit 0 (index, tasks, skills, strict OpenSpec validation including the
  new `deal-lifecycle` delta, `make check-repository`). End-to-end confirmed as stated:
  the two purchase scenarios drive the drivers 8.2 restored, so they buy without a
  waiver and assert the published deadline, which in both lanes is the clause's (no
  deployed composition wires the pool port); validation's e2e-vm and e2e-bare-metal
  lanes are the evidence. No marker exercises a pool-supplied deadline or a recurring
  option's. No `Owed by validation:` evidence: validation dispatches those lanes itself,
  and no CI workflow a push alone produces bears on this section.

### Section 8 verification and handoff (2026-11-12)

- The fresh-context compliance check found one spec conflict (below), change documents
  still saying the composition supplies the clause's deadline (D3, D9, the
  "Reserved-purchase E2E" paragraph, the storefront-publication delta's title), a
  "yet" in both recurring worlds' docstrings, stale or ambiguous docstrings
  (`effective_delivery_deadline`, `ClausePublication.publish`, both composition tests)
  and an 8.3 note not saying it departs from its plan line; all fixed, and its re-check
  found each resolved and the new delta's text and scenarios complete. Declined: its
  inability to confirm spot's positional `RatePresetPricing` call, which `git show
  origin/spot-deals:kit/arkhai-payments/src/market_arkhai_payments/presets.py` confirms.
  `scripts/change-workflow openspec validate … --strict` was denied in this step;
  `pre-commit`'s own strict validation stood in for it.
- Outside the plan, found by the compliance check: the permanent
  `openspec/specs/deal-lifecycle/spec.md` required a compute option to omit the deadline
  wherever its site enforces none, which R21's clause fallback contradicts. The change
  now carries a MODIFIED `deal-lifecycle` delta of its two delivery-deadline
  requirements; `proposal.md`, D3's promotion row and task 13.9 name it. The round's
  review should confirm that amending this foundation-owned requirement is what R21
  meant; R21's own text names only storefront-publication and settlement-configuration.
  A MODIFIED delta keeps the requirement's title, "…is the site's availability term",
  which now names only half the rule; a RENAMED entry would fix it, for closeout to
  weigh.
- A deviation for the round's triage: R21's up-stack note says spot's helper "needs
  nothing new". It needs one line here — returning its clause's deadline through
  `RatePresetPricing.delivery_deadline_seconds` — because the shared step does not parse
  a mechanism's clause input (D3 records the rejected alternative, the step reading
  `mechanism_input["delivery_deadline_seconds"]`). Without that line a hosted recurring
  option takes only the pool's deadline. `dependency-contracts.md` names the line.
- Versions: `kit/arkhai-payments` (0.6.2) and `kit/settlement-runtime` (0.8.0) are
  unbumped against `dev`, though both changed here and in round 1; section 6's handoff
  already asks the triage to confirm whether 0.8.0 is released, and the same question
  holds for 0.6.2. The repository's version-bump check does not settle it: it refuses
  only a version moved by more than one step and leaves an unbumped package unchecked.
- For section 9: nothing in section 8 touches the clause resolver; the bare-metal
  `reserved_lease_bound_missing` hold still sits in `publication_payload` before the
  step's call. Both recurring worlds now take `pool_deadline` (bare metal also
  `clause_deadline`; VM's `clauses()` takes a deadline), and their fixture helpers read
  a clause's `delivery_deadline_seconds` as a mechanism would.

## 9. One clause source and one reserved-bound rule

Delivers D10's shared clause resolver (R28) and D5's reserved-bound rule in both domains
(R27). Touches `kit/resource-pools-contracts`, `domains/vms/listings`
(`pricing_resolution.py`, `reconciler.py`), the bare-metal storefront (`config.py`,
`publication_terms.py`, `publication.py`), the VM storefront's publication terms and
pool-override models, and `docs/operator-handbook.md`.

- [x] 9.1 **The shared clause resolver (D10; R28), from 5.9:** move clause and
  listing-term resolution out of `arkhai_vms_listings.pricing_resolution` into
  `kit/resource-pools-contracts` beside `capacity_bounds.py` and `raw_pricing`, taking
  the `gpu` key as data, resolving field by field in D10's order (override > per-model
  pool hint > the new pool-level `pricing.settlements` hint > per-model configuration >
  flat `[pricing]`), bounds in D5's order. Both domains call it; bare metal's
  `pricing.bare_metal.settlements` hint is replaced, with no compatibility path (D12);
  VM's family rates stay in VM. A v0.3.0 VM configuration or hint resolves as before.
  Done (2026-11-12): `kit/resource-pools-contracts/src/market_resource_pools_contracts/listing_terms.py`
  — `ListingTerms` (accepted escrows, settlements), `resolve_listing_terms(policy_tags, *,
  model_family, model, storefront_override, config_defaults_by_model, flat_default)` in
  D10's five tiers, each field whole, and the hint readers `model_hint`,
  `model_hint_terms`, `pool_hint_terms` (`pricing.settlements`, clauses only) and
  `model_hint_bounds` (strict). It does not resolve bounds: VM's `resolve_gpu_pricing`
  (still in `pricing_resolution.py`, now composition only) takes the settlement terms from
  it and composes the bounds through `resolve_capacity_bounds` with its v0.3.0 per-model
  tiers below the mode hint; bare metal keeps its per-pool bounds in `site_reading.py`
  (D10's added paragraph records why). Bare metal: `publication.py` resolves each
  candidate's clauses through the shared resolver with its machine's `gpu_model`, the
  family key read from `COMPUTE_CAPABILITY_SCHEMA`; `publication_terms.py` and its
  `pool_pricing_unreadable` hold are removed (`git rm`). Outside the plan's file list, as
  the fourth tier requires: `config.py` gains `[pricing.defaults.gpu.<model>].settlements`
  (`ModelPricingSettings`, `PricingDefaultsSettings`), `runtime.py` compiles them at
  startup (refusing naming the key) into `publication_clauses_by_model`, which
  `publication_composition.py` hands the cycle; `settings.toml` documents it; `make
  helm-values-schema` regenerated `helm/charts/bare-metal-storefront/values.schema.json`.
  A wrongly shaped hint field falls through in both domains (VM's released behaviour;
  D10). Versions, against `marketplace-v0.3.0` and `dev`: `arkhai-kit-resource-pools-contracts`
  0.3.0 and `arkhai-vms-listings` 0.8.0 are both released and unbumped on `dev`, so this
  section bumps them a minor each, to 0.4.0 (the new public module, and round 1's
  `capacity_bounds`, added without a bump) and 0.9.0 (the pool-level tier); the
  consumers' floors follow: `>=0.4.0` in VM listings and the bare-metal storefront,
  `arkhai-vms-listings>=0.9.0` in the VM storefront. Both storefronts are already
  0.28.0, unreleased.
- [x] 9.2 **The reserved-bound rule (D5; R27), from 5.9:** in both domains no positive
  relative maximum means no relative limit; retire `pool_lease_bound_missing` and
  `reserved_lease_bound_missing`, and add the bare-metal upgrade step (the replaced hint
  and the retired diagnostic) to `docs/operator-handbook.md`.
  Done (2026-11-12): bare metal's `_hold_unbounded_pools` (`pool_lease_bound_missing`)
  and the composition's `reserved_lease_bound_missing` skip are removed; a pool resolving
  no positive maximum publishes with `max_duration_seconds` null. VM already published
  so, and bare-metal negotiation already checks a duration only against a stated
  maximum (`negotiation.py`). Docstrings and `settings.toml`/`startup_refusal.py` prose
  follow. `docs/operator-handbook.md`, "What the upgrade from v0.3.0 changes", gains two
  bullets: v0.3.0 shipped the hold, so held pools now publish unbounded (set a default,
  override or hint to keep a ceiling); and bare metal now reads the pool's `pricing`
  hint, so a shared pool's VM clause hint reaches its bare-metal listings. The replaced
  `pricing.bare_metal.settlements` hint was never released (absent from
  `marketplace-v0.3.0`), so the step names the hint tiers bare metal now reads rather
  than a migration from it. `DEPLOYMENT_AND_CONFIG.md`'s bare-metal override bullet and
  `storefront-publication/architecture.md` still name the retired hold: closeout
  promotes them (D5 and D10's promotion rows, task 13.9).
- [x] 9.3 **Permanent tests (R2):** unit, in `kit/resource-pools-contracts/tests`: each
  tier of D10's order winning field by field, the pool-level hint, a v0.3.0 VM
  configuration and hint unchanged, bounds keeping D5's order; the moved
  `domains/vms/storefront/tests/unit/test_pricing_resolution.py` cases follow the
  resolver. Application integration through each storefront's typed client: a pool-level
  `pricing.settlements` hint publishes its clause in both domains; a reserved option
  publishes without a relative maximum in both domains.
  Done (2026-11-12). Unit, `kit/resource-pools-contracts/tests/unit/test_listing_terms.py`
  (the resolver called directly): each of the five tiers winning below the one above,
  field by field, a list resolved whole and an empty list stopping lower tiers, another
  model's hint ignored, a listing without a model, the family as data, every malformed
  hint level falling through, no pool-level accepted escrows, and `model_hint_bounds`
  stated, absent and refused. VM, `domains/vms/storefront/tests/unit/test_pricing_resolution.py`
  (unit, `resolve_gpu_pricing`): the moved order cases now live in the kit file; it keeps
  VM's composition — a released per-model hint and configuration resolving as before, the
  pool-level clauses below the model hint (and for a model-less shape), the mode hint
  above the per-model bound tiers, each bound tier above the next (override over mode
  hint, model hint over model configuration, model configuration over flat), strict
  bounds and retired keys. This departs from the plan's line: the v0.3.0 VM case and the
  bound order are VM unit tests, not the kit's, since the kit resolver resolves no bounds
  and knows no VM configuration. Bare metal, unit: `tests/test_publication_cycle.py`
  `test_each_machine_takes_its_clauses_from_the_highest_tier_stating_them` (the cycle with
  a recording payload builder: model hint and pool hint each over a configured model,
  model configuration over flat, flat, then an override replacing all); the two lease-bound cycle tests now assert publication with a
  null maximum and no hold; `tests/test_config_loader.py` (the per-model table read under
  the model's spelling); `tests/test_app_composition.py` (per-model clauses compiled and
  handed to the cycle by `build_publication_cycle`, and refused at startup naming the
  key). `tests/test_http_system.py`'s two status tests that leaned on the retired hold use
  an unresolvable pool's `pool_unresolvable` hold instead. Application integration
  through the typed admin client with real SQLite and the production cycle composition:
  bare metal `tests/test_http_publication_rates.py`
  `test_a_reserved_option_publishes_with_no_relative_maximum` (null maximum, the Alkahest
  escrow published, no hold) and `test_pool_level_clauses_publish_below_a_model_hint`
  (two machines in one pool, no configured clause: the A100 machine publishes the
  pool-level clauses, the default-model (H200) machine's empty model hint refuses it as
  `no_settlement_option`); VM `tests/integration/test_publication_loop.py`
  `test_a_reserved_option_publishes_with_no_relative_maximum` and
  `test_pool_level_clauses_publish_below_a_model_hint` (the GPU-less shape publishes the
  pool-level clause, the H100 shape's empty hint refuses it).
- [x] 9.4 **Verify:** `make dist`, then `make -C kit/resource-pools-contracts test`
  (unit), `make -C domains/vms/storefront test` (which tests `domains/vms/listings`;
  including `test_reconciler_derivation.py`, `test_reconciler_projection.py`,
  `test_pool_overrides_api.py`), `make -C domains/bare_metal/storefront test`,
  `make check-packaging` (the moved module changes package edges),
  `make check-comment-hygiene` and `scripts/change-workflow run pre-commit
  negotiate-open-ended-compute-terms`. End-to-end: `vms/test_listing_shapes.py`,
  `vms/test_pool_declared_offering_modes.py` and
  `bare_metal/test_bare_metal_publication.py` publish through the resolver; none sets a
  pool-level hint, and none is owed beyond them.
  Done (2026-11-12), after `make dist`: `make -C kit/resource-pools-contracts test`
  (unit) 449 passed; `make -C domains/vms/storefront test` unit 1189 passed, 1 skipped,
  application integration 584 passed (including `test_reconciler_derivation.py`,
  `test_reconciler_projection.py`, `test_pool_overrides_api.py` and the two new
  `test_publication_loop.py` cases); `make -C domains/bare_metal/storefront test` (unit
  and application integration) 629 passed, after `make helm-values-schema`; `make
  check-comment-hygiene` passed; `scripts/change-workflow run pre-commit
  negotiate-open-ended-compute-terms` on the final code passed every hook —
  `after-functional-change` exit 0 (relocking every project over contracts 0.4.0),
  `pre-commit-functional` exit 0 (`make check-packaging` and the whole `make test`),
  `pre-commit` exit 0. End-to-end confirmed as stated: the three scenarios publish
  through the resolver; no marker in `e2e-tests/` states a pool `pricing` hint for bare
  metal (its drivers state clauses by override) or a pool-level `pricing.settlements`;
  the bare-metal lanes configure their bounds, so none exercises the retired hold. No
  `Owed by validation:` evidence: no CI workflow a push alone produces bears on this
  section.

### Section 9 verification and handoff (2026-11-12)

- The fresh-context compliance check found one high finding: contracts 0.3.0 and
  `arkhai-vms-listings` 0.8.0 are the versions `marketplace-v0.3.0` released, so adding
  API under them was a versioning defect (round 1's `capacity_bounds` included); both
  are now bumped a minor (9.1's note). Its re-check found every fix holding and three
  wording slips, fixed: the model named in 9.3's note, "shipped" for round 1's
  unreleased `capacity_bounds`, and a parenthetical in the payload builder's docstring. Also fixed: stale comments in `reconciler.py` and
  `publication_composition.py`, a history phrase in `listing_terms.py`, a handbook clause
  naming a diagnostic v0.3.0 never had, VM bound-order coverage, a cycle test that did
  not exercise the pool hint over a configured model, integration docstrings claiming
  acceptance, D10's promotion row gaining `ARCHITECTURE.md`, and nits. Declined: VM's
  `GPU_FAMILY_KEY = "gpu"` literal (pre-existing; it is the value bare metal derives
  from the compute schema, and VM's family-rate code is keyed on it).
- For the round's triage, settling sections 6 and 8's version question by the release
  tag: `arkhai-kit-settlement-runtime` released 0.7.0, so 0.8.0 is unreleased and
  needs nothing; `arkhai-kit-arkhai-payments` released 0.6.1 and is 0.6.2 on `dev` (a
  patch), while section 8 added `RatePresetPricing.delivery_deadline_seconds`, new API,
  which by `docs/development/RELEASING.md` takes it to 0.7.0 with its exact pins;
  `arkhai-kit-config` released 0.5.1 and is 0.5.2 on `dev`, while section 6 added the
  seller's `rate_servicing` key to its generated schema — whether that is a minor is the
  triage's call. Left unchanged here: outside this section, and each moves exact pins.
- For the next sections: section 10 does not touch the resolver. A bare-metal candidate
  carries `resolved_clauses` from every tier now (the payload builder falls back to the
  flat clauses only when the cycle resolved none). Bare-metal integration cases that
  need the production cycle with a pool hint can use
  `test_http_publication_rates.py`'s `_composed` (over `_derivation_runtime`).

## 10. The buyer's per-term waivers and duration flags

Delivers D11 (R14, R18) in both buyers. Touches `kit/settlement-runtime`
(`buyer_terms.py`), the VM buyer (`buy_cli.py`, `negotiate_cli.py`,
`settlement_composition.py`) and the bare-metal buyer (`cli.py`,
`settlement_composition.py`). As built, also `rate_publication.py` (the named refusal
terms), the VM buyer's `cli_helpers.py` (the duration flags), and `buy_orchestrator.py`,
`buyer_client.py`, `deal_helpers.py` and `settle_cli.py` (the waivers reaching the
accepted disclosure on fresh, resumed and recovered runs), and bare metal's
`settlement_stages.py` (the reserved default).

- [x] 10.1 **Per-term waivers (D11; R14), from 5.7:** in both buyers, one flag per
  default refusal — `--allow-no-delivery-deadline`, `--allow-no-penalty`,
  `--allow-charged-preemption`, `--allow-charged-term-end` — with
  `--allow-unprotected-terms` as shorthand for all four, composed in `BuyerTermsPolicy`;
  the foundation's `allow_missing_delivery_deadline` is set only by the first or the
  shorthand; every waiver used is recorded in run metadata and named in the
  pre-approval disclosure. Codec, capability and authority checks are never waived.
  Done (2026-11-12). `rate_publication.py`: the refusals are named terms
  (`DefaultRefusal`: `no_delivery_deadline`, `no_penalty`, `charged_preemption`,
  `charged_term_end`) from `default_buyer_refused_terms`, worded once by
  `default_buyer_refusal`; `default_buyer_refusals`, which publication diagnoses with,
  keeps its strings. `buyer_terms.py`: `TERM_WAIVERS` (term, flag, help),
  `WAIVERS_BY_TERM`, `UNPROTECTED_TERMS_FLAG`/`_HELP`, `term_waivers(...)` (the shorthand
  expanding to all four), `waiver_flags` and `allows_missing_delivery_deadline`;
  `BuyerTermsPolicy(authority, waivers=...)` refuses only unwaived terms and refuses an
  unknown waiver; `lifecycle_disclosure(..., waivers=)` marks a waived refusal "waived
  by <flag>" and adds a "Waivers in force" row, in the no-adapter branch too. Both buyer
  compositions' `buyer_term_context(mechanism, waivers=)` set the foundation's
  `allow_missing_delivery_deadline` through `allows_missing_delivery_deadline`;
  `validate_authority` (bare metal) and `resolve_buyer_settlement_policy` (VM) take
  `waivers`. `market buy`, `market negotiate` and `bare-metal buy` declare the four flags
  and the shorthand from the kit's table; each run's `run_started` records
  `compute_term_waivers` (the flags in force, in the table's order), replacing round 1's
  `allow_unprotected_compute_terms` boolean, which nothing read and no release shipped;
  VM's `public_context` carries the same list. Both disclosures before approval name
  them, in both domains: the selected option's, and the accepted Agreement's (bare
  metal's `buy`; VM's `validate_buyer_acceptance`/`disclose_accepted_agreement`, given
  the waivers by `listing_acceptance_validator`, `make_legacy_negotiate_hook` and
  `buyer_client.negotiate_with_seller`). A resumed or recovered VM run reads them from
  its run log (`deal_helpers.recorded_waivers`, over the kit's `waivers_from_flags`,
  which refuses an unknown recorded flag): `buy --from`, `negotiate --from` and `settle
  --from`, and `buy`/`negotiate --from` refuse waiver flags. Corrected after the
  compliance check: the accepted disclosure first named no waiver, so the last block
  before approval showed a waived refusal unmarked, and `market settle --from` named
  none at all. The change's `buyer_terms_probe.py` follows the new signatures (not run
  here).
- [x] 10.2 **Durations (D11; R18), from 5.7:** `bare-metal buy` restores the
  3600-second default for reserved options only, shown as the buyer's default in the
  disclosure, never for recurring ones; VM's `market buy`/`negotiate` gain
  `--duration-seconds` beside `--duration-hours`, both together an error naming the
  conflict.
  Done (2026-11-12). Bare metal: `settlement_stages.py`
  `RESERVED_DEFAULT_DURATION_SECONDS = 3600` and `requested_duration(option, duration,
  registry=)`, which takes the buyer's duration, else 3600 where the mechanism's
  `project_billing` says `total`, else none; `buy` calls it before quoting, the
  disclosure's "Requested horizon" row says "this buyer's default for a reserved
  option" (`compute_disclosure(..., default_duration=)`), and `run_started` records
  `default_duration`. v0.3.0's default was the command option's own `3600`, not
  `BareMetalBuyerConfig.default_duration_seconds`, which nothing reads (the section's
  handoff records it for the triage).
  VM: `cli_helpers.requested_duration_seconds` resolves `--duration-seconds` or
  `--duration-hours`, refusing both together ("Pass --duration-seconds or
  --duration-hours, not both.") and a nonpositive value, as the first step of `buy` and
  `negotiate`, before identity, registry or resume handling; the two commands' later
  hours-only checks are removed.
- [x] 10.3 **Permanent tests (R2):** unit, in `kit/settlement-runtime/tests/unit`: each
  flag waiving exactly its refusal, the shorthand waiving all four, the foundation flag
  set only by the deadline waiver or the shorthand. Each buyer's CLI suites
  (`domains/vms/buyer/tests/test_buy_resume_cli.py`, `test_explain_cli.py`;
  `domains/bare_metal/buyer/tests`): the flags parsed, recorded in run metadata and named
  in the disclosure; the bare-metal reserved default shown as the buyer's and absent for
  a recurring option; both VM duration flags refused together.
  Done (2026-11-12). Unit, `kit/settlement-runtime/tests/unit/test_buyer_terms.py` (new;
  `BuyerTermsPolicy` over a real `AuthoritySelection` and the codec, with one option per
  refusal): each refused alone by a default buyer; each single flag waiving exactly its
  term and no other; the shorthand all four; a waiver not bypassing an unsupported
  treatment or a missing authority; the foundation allowance set only by the deadline
  waiver or the shorthand, and the codec still refusing a missing deadline when the
  policy's waiver is given without it; an unknown waiver refused; `waiver_flags`' order;
  the disclosure marking a waived refusal, naming waivers an option does not need and
  in the no-adapter branch, and naming none without waivers; a recorded run's flags
  reading back to its waivers, and an unknown recorded flag refused. Bare metal, the `buy`
  command through `CliRunner` (`tests/test_cli_completion.py`'s `_compose`, unit level):
  it replaces the four factories and also, as the file's existing cases do, the imported
  `load_bare_metal_buyer_config` and `negotiate_with_seller` and the `BUYER_STAGES` table
  with a stub stage, so the payment stage's own option and acceptance checks do not run
  — the module-name replacement `TESTING.md`'s command-module convention records as a
  gap (`docs/development/ROADMAP.md`); the payments registration, the rights policy, the
  codec and the run log are real. A reserved
  buy naming no duration negotiates 3600 seconds and its quote, shows the buyer's
  default and records it; a named duration is not shown as the default;
  `requested_duration` per billing basis (a stub `project_billing`: the installed
  payments projection bills once only, so a per-period basis stands for a mechanism
  billing a recurring option — the CLI itself cannot reach a recurring option today);
  an option without a deadline refused by name with no waiver or another term's,
  bought with its own waiver, with another, or the shorthand, each run's
  `compute_term_waivers` recorded and both the selected-option and the accepted
  disclosure marking the waived refusal and naming every flag; a run without waivers
  records none.
  `tests/test_buyer_composition.py`: `buyer_term_context`'s allowance only under the
  deadline waiver. VM, `tests/test_buy_resume_cli.py` (the CLI through `CliRunner`,
  with the registry query, `run_buy`, the negotiate hook factory and the user
  configuration replaced by module name, as the file's existing cases do — the same
  recorded gap, which the new cases extend rather than close): both duration flags
  refused, exit 2, before any identity read, for `buy` and `negotiate`; a nonpositive
  `--duration-seconds` refused for both; `buy --from` and `negotiate --from` refusing a
  waiver flag; a fresh `buy` with `--duration-seconds 5400` and two waivers, or the
  shorthand, records the duration and the waivers and names each in the selected-option
  disclosure (an Alkahest option, so through the no-adapter branch); the existing
  fresh-buy case now also asserts no waivers recorded or named.
  `tests/test_term_waivers.py` (new, unit, nothing replaced): the accepted disclosure
  marking a waived refusal over a real payments option and Agreement, and naming none
  without waivers; `listing_acceptance_validator` binding the waivers;
  `recorded_waivers` reading a real run log (two, none, not recorded) and refusing an
  unknown flag. `tests/test_vm_settlement_helpers.py`:
  `resolve_buyer_settlement_policy(waivers=)` hands the policy its waivers, the payments
  context its allowance only under the deadline waiver, and `public_context` the flags.
  Departs from the plan's line: nothing was added to `test_explain_cli.py`, which tests
  `market listing`; `market buy --explain` stops before the disclosure, and selection
  under waivers is the kit's tests'. No VM test drives a payments option through `market
  buy`'s selected-option disclosure (its fresh-buy world is Alkahest), `market
  negotiate`'s fresh waivers past the duration check, the resumes' hand-off of their
  recorded waivers (`buy --from`'s `resumed_waivers`, `negotiate --from`'s reassignment),
  `make_legacy_negotiate_hook(waivers=)`, or `market settle --from`'s call of
  `recorded_waivers`; the commands share the kit's table, `term_waivers`, the
  composition, `recorded_waivers` and `listing_acceptance_validator` the tests above
  cover. `tests/test_buyer_client.py`
  `test_the_accepted_disclosure_names_the_run_s_waivers` (unit, the file's patched
  seller transport) covers `negotiate_with_seller(waivers=)` reaching the accepted
  disclosure with and without a listing — the second added after the compliance
  re-check found the waivers bound only when a listing was given.
- [x] 10.4 **Verify:** `make dist`, then `make -C kit/settlement-runtime test` (unit and
  library integration),
  `make -C domains/vms/buyer test` (unit), `make -C domains/bare_metal/buyer test`
  (unit), `make -C core/buyer test` (unit), `make check-comment-hygiene` and
  `scripts/change-workflow run pre-commit negotiate-open-ended-compute-terms`.
  End-to-end: the reserved purchases buy without waivers since section 8; none passes a
  per-term flag, and none is owed, since a flag's effect is the buyer's own policy,
  which the unit suites prove.
  Done (2026-11-12), after `make dist`: `make -C kit/settlement-runtime test` (unit and
  library integration) 283 passed; `make -C domains/vms/buyer test` (unit) 286 passed;
  `make -C domains/bare_metal/buyer test` (unit) 53 passed; `make -C core/buyer test`
  (unit) 170 passed (run before the compliance fixes, which touched no core code);
  `make check-comment-hygiene` passed; `scripts/change-workflow run pre-commit
  negotiate-open-ended-compute-terms` passed every hook (see the handoff below).
  End-to-end confirmed as stated: no marker in `e2e-tests/` passes a waiver flag, or
  `--duration-seconds` to `market buy`/`negotiate` (the VM scenarios use
  `--duration-hours`); the bare-metal purchase driver names its duration with
  `--duration-seconds`, so the reserved default is not exercised deployed. The bare-metal and VM purchase
  scenarios run the commands whose flags changed, so validation's e2e-vm and
  e2e-bare-metal lanes show the commands still parse and buy without waivers. No
  `Owed by validation:` evidence: no CI workflow a push alone produces bears on this
  section.

### Section 10 verification and handoff (2026-11-12)

- The fresh-context compliance check found one medium finding: the accepted-Agreement
  disclosure, the last block before approval, named no waiver, and `market settle
  --from` named none at all. Fixed in both domains (10.1's correction). Its five low
  findings were also fixed: D11's promotion row gains `buyer-orchestration/architecture.md`;
  the 10.3 note now lists what `_compose` and the VM CLI tests replace; the kit test
  asserts each refusal's own wording; the test name; and this handoff records the
  unread configuration key (below). Its re-check found five more low findings, all
  fixed: the waivers bound only when a listing was given (now always, with a
  `buyer_client` case for both); the resume rules missing from the buyer-orchestration
  delta (a requirement sentence and the scenario "A resumed run keeps its waivers");
  the 10.3 note not listing every untested resume hand-off; a test name; and the
  section's file list. Declined: nothing.
- For the round's triage: `BareMetalBuyerConfig.default_duration_seconds`
  (`domains/bare_metal/buyer/src/arkhai_bare_metal_buyer/config.py`, default 3600) is
  validated and tested but read by nothing, in `marketplace-v0.3.0` as now: v0.3.0's
  3600-second default was `buy`'s option default, and this section restores it as
  `RESERVED_DEFAULT_DURATION_SECONDS`. A buyer who sets the key to 7200 still gets
  3600. Honouring it (the reserved default reading the key) or retiring it is a choice
  under D12, since a release shipped the key; this section left it, as R18 named the
  3600 default only.
- Versions: `kit/settlement-runtime` changed public API again (`BuyerTermsPolicy`'s
  `waivers` replacing `allow_unprotected_terms`, and the new names in `buyer_terms` and
  `rate_publication`); it is 0.8.0, unreleased (section 9's handoff), so it needs no
  bump. The VM and bare-metal buyers changed their commands; their versions are
  unbumped against `dev` here, as in the earlier sections, for the triage's version
  pass.
- For the next sections: 11.2 owns `default_buyer_refusals`' and `lifecycle_disclosure`'s
  remaining unit tests — `test_buyer_terms.py` now covers the waiver rows of
  `lifecycle_disclosure` and the policy, not the other disclosure rows or
  `present_payment`. `compute_disclosure(default_duration=)` is tested only through bare
  metal's `buy`. The change's `buyer_terms_probe.py` follows the new signatures but was
  not run; 12.3 decides its conversion.

## 11. Permanent unit tests of round 1's behaviour

Delivers R2's unit tests for round-1 behaviour no later section touches (D1, D2/D2a,
D5, D7) and R6's per-period money consumers. Touches tests only, in `core`,
`kit/alkahest`, `kit/arkhai-payments`, `kit/contact-exchange`,
`kit/resource-pools-contracts`, `kit/settlement-runtime`, both buyers and the VM
storefront.

- [x] 11.1 **The accessor and the projections (D2; R2):** `agreed_price` in
  `core/tests/unit/test_rate_helpers.py` and `test_settlement_options.py` — total and
  per-period, sub-hour periods, rounding upward once, the absolute amount fallback and
  refusal of a missing projector; each installed registration's projection (Alkahest,
  payments, contact) — once totals, unsupported rate parameters failing closed.
  Done (2026-11-12), all unit. Core, `test_rate_helpers.py` (`agreed_price` called
  directly with injected projections): a prepaid two-hour Agreement reads 5,000,000
  total; PT15M and PT1M Agreements read 625,000 and 41,667 per period, unchanged at a
  7200- or 172800-second horizon; a selected option without a projection refused; no
  option keeps its absolute amount; five projections contradicting their unit refused;
  an amount beyond uint256 refused. `test_settlement_options.py`: an acceptance-bound
  listing (by `listing_id` or a registry's `id`) must hold the exact selected option —
  another listing, none, or a repriced option refused. Departs from the plan's line:
  the accessor never rounds, so "rounding upward once" and the sub-hour quotes are VM's
  `quote_from_multiplier`, tested in `domains/vms/storefront/tests/unit/test_vm_multiplier.py`
  beside its existing quote tests (`domains/vms/negotiation` has no suite of its own):
  one period's price (625,000; 41,666.67 rounded
  up to 41,667) at a 7200- or 172800-second or omitted horizon, against 5,000,000 over
  a two-hour whole term; and `selected_billing_basis` taking the option's projection,
  a legacy raw escrow proposal a total without one. Projections, each registration's
  `project_billing` called directly: Alkahest (`kit/alkahest/tests/unit/test_settlement_config.py`)
  a total for a published accepted-escrow option (built by the file's builder helper)
  and an explicit negotiated proposal, refused with a `period`, with lifecycle terms or
  another schema; payments (`kit/arkhai-payments/tests/test_settlement_config.py`) a
  total for a once option, refused with `period`, `period` and `reserve_ahead_seconds`,
  or `setup_amount` (the strict parameter codec), or another schema; contact
  (`kit/contact-exchange/tests/unit/test_settlement_config.py`) a total for a rateless
  introduction, also through the registry's `agreed_price`, refused with a rate, an
  asset, foreign parameters or another schema.
- [x] 11.2 **Bounds, the buyer's policy and presentation (D5, D7; R2):** capacity-bound
  validation and tier selection in `kit/resource-pools-contracts/tests`;
  `default_buyer_refusals`, `lifecycle_disclosure` and `present_payment`'s registry checks
  (basis, asset, accepted money unchanged, missing presenter refused) in
  `kit/settlement-runtime/tests/unit`.
  Done (2026-11-12), all unit. `kit/resource-pools-contracts/tests/unit/test_capacity_bounds.py`
  (new): the absolute bound read as one Z timestamp from either UTC spelling or an aware
  datetime, keeping fractional seconds, and refused naive, offset, as text, as an epoch
  or null; a nonpositive relative bound meaning none and a non-integer refused; a tier's
  strict fields and extra keys refused; a pool hint read per offering mode, an absent
  mode empty, and six malformed hints each refused naming where, by both the reader and
  `validate_capacity_bounds`; `resolve_capacity_bounds` field by field from the highest
  stating tier (an override's absolute date over a hint's among them), and a stated 0
  masking the tiers below. (VM's per-model bound tiers are
  9.3's.) `kit/settlement-runtime/tests/unit/test_buyer_presentation.py` (new; options
  from `test_buyer_terms.py`'s fixtures, a fixture registration whose projection and
  presenter each test sets): `default_buyer_refusals` empty without an adapter and for
  once, on-demand and spot options, one wording per term, three terms in order on one
  option, and a zero penalty; `lifecycle_disclosure`'s deadline, each stopper's notice
  and treatment, term end, penalty ceiling and asset, buyer end and dispute rows for
  on-demand, the seller's notice stop for spot, the once option's "no entitled stop",
  the missing deadline beside its refusal, the no-adapter branch, and three mismatched
  contexts refused; `present_payment` returning a matching presentation, refusing one
  off the option's basis, period or asset or changing an accepted quote, and refusing a
  mechanism without a presenter or a projection. Added beyond the plan, for D7's
  display that both buyers share: `compute_disclosure` showing an accepted per-period
  Agreement over two days as one period's price with its reserve, horizon and end, a
  selected spot option with its omitted horizon and bounds, a whole-term option as a
  reserved total, and refusing an option other than the accepted one.
- [x] 11.3 **Every money consumer with a per-period Agreement (D2; R6):** mandate
  derivation (`kit/arkhai-payments/tests`), buyer caps and display, recovery and
  confirmation (`domains/vms/buyer/tests`, `domains/bare_metal/buyer/tests`), each driven
  with a per-period Agreement and asserting the money is read once, never scaled by
  duration or multiplier again.
  Done (2026-11-12), all unit. No installed mechanism bills per period (the installed
  payments projection refuses one, 11.1), so the buyers' per-period cases inject a
  projection: a fixture mechanism's option in VM's, the payments registration with its
  projection and presenter replaced in bare metal's. Mandate, `kit/arkhai-payments/tests/test_agreement.py`:
  the mandate's one part charges the accepted 10,000 at a 3600-, 7200- or 172800-second
  duration and stays bound. The mandate takes the installed projection, which no test
  can replace, so what is tested is that a payments option carrying `period` (625,000
  over two days, the option re-derived) is refused at all three entry points: no
  mandate policy and no settlement data ("lacks the terms a payments mandate needs"),
  and a stored once mandate re-checked against it fails as malformed, never compared.
  Each refusal is the projection's strict codec rejecting `period`; the policy's own
  guard against a per-period quote (`agreement.py`, `quote.unit != "total"`) is
  unreachable through the installed projection and untested. VM buyer, `tests/test_negotiation_amounts.py`
  (`amount_codec` and `priced_unit_count` with an injected projection): the payment is
  one period's price (250 a quarter hour; 16.67 rounded up to 17 a minute) at any
  horizon or none; the per-hour ceiling caps one period (200), refusing a larger accepted
  shape naming "800 per hour for 900s", at a two-day horizon; bounds scale by one period
  (0.25) whatever the horizon, a reserved selection by its duration, and refuse one
  without. `tests/test_per_period_acceptance.py` (new): `verify_pricing_acceptance`,
  which acceptance and a resumed run's `verify_recovered_pricing` call, over a record
  with a real seller-signed publication — a per-period Agreement at one period's quote
  admitted with no requested duration, one at 192 periods, the hourly rate or one unit
  off refused, and the period price refused when the projection reads it as a total;
  the confirmation (`_confirm_settlement_interactive`, the buyer declining on the
  isolated standard input of Click's test runner, no name replaced) showing a
  per-period charge and a two-hour total unscaled. The resumed run's evidence walk itself is not driven here. Core's escrow
  recovery read, `core/buyer/tests/unit/test_identity_recovery.py`: `exact_agreed_amount`
  refuses a per-period projection and an unprojected selected option. Bare metal,
  `tests/test_purchase_quote.py` (new; a payments registration with its projection and
  presenter replaced, through the registry both functions take): `purchase_quote` is one
  period's 625,000 at no, a two-hour or a two-day horizon; `require_quoted_agreement`
  admits the Agreement at that quote, refuses one at 192 or 48 periods or one unit off,
  refuses the period price where no quote says it is per period, and holds an explicitly
  requested horizon. Bare metal sets no ceiling, and its display is `compute_disclosure`,
  11.2's. Not covered: VM `market buy`'s or `bare-metal buy`'s own flow with a per-period
  option, which no installed mechanism reaches.
- [x] 11.4 **Verify:** `make dist`, then `make -C core test` (unit), `make -C
  kit/alkahest test`, `make -C kit/arkhai-payments test`, `make -C kit/contact-exchange
  test`, `make -C kit/resource-pools-contracts test`, `make -C kit/settlement-runtime
  test`, `make -C domains/vms/buyer test`, `make -C domains/bare_metal/buyer test` (all
  unit), `make check-comment-hygiene` and `scripts/change-workflow run pre-commit
  negotiate-open-ended-compute-terms`. End-to-end: none; no deployed run produces a
  per-period Agreement (the unowned gap in `openspec/changes/README.md`), so these unit
  tests are the money consumers' evidence.
  Done (2026-11-12), on the final tests: `make -C core test` (core unit 130, core buyer
  unit 170, core storefront 227, storefront client 68, all passed); `make -C kit/alkahest
  test` 465 passed; `make -C kit/arkhai-payments test` (with mypy, vectors and
  generated-model checks) 235 passed; `make -C kit/contact-exchange test` 146 passed;
  `make -C kit/resource-pools-contracts test` 478 passed; `make -C kit/settlement-runtime
  test` (unit and library integration) 302 passed; `make -C domains/vms/buyer test` 299
  passed; `make -C domains/bare_metal/buyer test` 63 passed; added for
  `test_vm_multiplier.py`, `make -C domains/vms/storefront test` unit 1192 passed, 1
  skipped, application integration 584 passed. Only tests changed, so no wheel changed;
  `make dist` ran before the pre-commit run. `make check-comment-hygiene` passed;
  `scripts/change-workflow run pre-commit negotiate-open-ended-compute-terms` passed
  every hook — `after-functional-change` exit 0 (nothing rebuilt),
  `pre-commit-functional` exit 0 (`make check-packaging` and the whole `make test`),
  `pre-commit` exit 0. End-to-end confirmed as stated: no marker in `e2e-tests/`
  produces a per-period Agreement. No `Owed by validation:` evidence: no CI workflow a
  push alone produces bears on this section.

### Section 11 verification and handoff (2026-11-12)

- The fresh-context compliance check found two medium, two low and three nits, all
  fixed: the VM confirmation test patched `typer.confirm` (a library name `TESTING.md`'s
  conventions forbid new tests to replace), now typing the decline on Click's isolated
  standard input; the 11.3 note claimed a per-period mandate case it did not run (now
  says what the strict codec's refusal proves, with `match=` on each refusal); the
  bare-metal test's docstring and the note's opening misnamed its fixture; a fixture
  address comment; an import group; the 11.1 note's placement reason; and the
  "absolute date overrides a hint" case added. Its re-check found every fix holding and
  one dropped space, restored (the payments suite rerun after it, 235 passed), and
  `scripts/change-workflow run pre-commit` passed every hook again on the final state.
  Declined: nothing.
- For the round's triage: the payments mandate policy's guard against a per-period
  quote (`kit/arkhai-payments/src/market_arkhai_payments/agreement.py`, `quote.unit !=
  "total"`) cannot be reached, since `_policy` takes the installed projection, which
  refuses any `period` first; it is defence in depth with no test. Making the
  projection injectable would let a test reach it; this section changes tests only.
- For section 12: `kit/settlement-runtime/tests/unit/test_buyer_presentation.py` and
  `domains/vms/buyer/tests/test_per_period_acceptance.py` import fixtures from sibling
  test modules (`test_buyer_terms.py`, `test_negotiation_amounts.py`; bare metal's
  `test_purchase_quote.py` from `test_cli_completion.py`). The VM file builds a real
  seller-signed publication record for `verify_pricing_acceptance` (`_signed_record`),
  a start for 12.2's pin cases at unit level; 12.2's own cases are application
  integration through the storefront. 12.3's probe conversion: `price_probe.py`,
  `billing_projection_probe.py` and `consumer_price_probe.py` are now covered by 11.1
  and 11.3's tests (the accessor, the installed projections, the per-period quote and
  codec, exact escrow recovery, the mandate's refusal and the confirmation), except the
  probes' retained-record round trip through `accepted_listing_record`, which 12.2
  owns.

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
  (D5, D6, D9, D10), `openspec/specs/buyer-orchestration/architecture.md` (D5's buyer-check
  seams, D7, D8, D11) and
  the bare-metal upgrade step in `docs/operator-handbook.md` (D5, D10; written in 9.2,
  confirmed here), the seller
  root's `rate_servicing` tables (D6), the storefront-wide
  `[pricing].default_premature_stop_penalty_periods` with its startup refusal (D3), and
  bare metal's clause tiers with `[pricing.defaults.gpu.<model>]` and its override
  bullet's retired `pool_lease_bound_missing` (D5, D10) in
  `docs/development/DEPLOYMENT_AND_CONFIG.md`. The archive
  merges the deltas into `negotiation-protocol`, `storefront-publication`,
  `resource-pool-management`, `settlement-configuration`, `buyer-orchestration` and
  `deal-lifecycle` specs; record destinations and identity decision outcomes. No new capability-index
  entry is needed.
- [ ] 13.10 **Documentation citations:** run
  `make check-doc-citations CHANGE=negotiate-open-ended-compute-terms`, resolve all
  matches, then `scripts/change-workflow openspec validate
  negotiate-open-ended-compute-terms --strict`.
- [ ] 13.11 **Archival:** last, run `scripts/change-workflow openspec archive
  negotiate-open-ended-compute-terms -y`, merging the deltas (no `--skip-specs`), and
  link the campaign row to the resulting archive.
