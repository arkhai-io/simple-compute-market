# Tasks — open-ended compute terms

Round 1 was sections 1–4, replayed onto dev as `6f86ac5e6`. The owner's record of
round 1 (`reviews/01-implementation-owner.md`) stood in for the design review this
change never had; its decisions are `design.md` D1–D12, and the code they need, with
review 04's F1 and F2, is round 2: sections 5–12, one session each but 5 and 6
together, reviewed as one round (`design.md`, "Implementation cadence"). Section 12a,
the version pass the first closeout attempt found owed, is round 3, whose validation
and review the owner waived. Section 12b, the code two of the owner's answers to the
second closeout attempt's questions need (13.3's note), is round 4, validated and
reviewed. Verification levels follow `docs/development/TESTING.md`; every behaviour
this change adds gets permanent tests at the level it assigns (owner record 01, R2).
Round 1's notes below are compressed to their outcome; where round 2 replaced a
behaviour, the later task says so. Round 1's checkpoint packets — setups, focused
results and probe replays, as observed — are under
`docs/attachments/negotiate-open-ended-compute-terms/`.

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

### Section 1 outcome (2026-11-06)

- Base `ba77a3b30` (`resize-multiplier`, PR #350), merging `registry-as-published`
  (PR #349) as `faa339eea`; D-a–D-e accepted for implementation.
- 1.1: resize writes the derived monetary amount to `Agreement.amount` and keeps the
  multiplier in the transcript and `negotiation_threads.agreed_price`. The owner kept
  that carrier (D2a, later owner record 01, R3). Contract verification and the 1.3
  handoff are in `dependency-contracts.md`; evidence in the `dependency-contract.md`
  packet (core `test_rate_helpers.py`/`test_settlement_options.py` 21 passed, VM
  `test_vm_multiplier.py` 8 passed, `make check-packaging` and `make check-change`
  passed).
- 1.2: hosted once builder → registry carrier → shared codec → Agreement and both
  buyers' pre-approval checks passed in an invocation-owned app with real SQLite;
  Alkahest with no lifecycle admitted, with lifecycle refused (`codec-contract.md`
  packet; existing foundation, payments, registry, VM and bare-metal suites passed).
  `codec_probe.py`'s conversion is 12.3's.

### Round-1 slices (2026-11-07)

Each slice's packet under `docs/attachments/negotiate-open-ended-compute-terms/`
records its setup, focused suites (all passing) and probe replay; the decisions they
implement are D2–D7 as `design.md` states them now.

- 2.1 (`price-checkpoint.md`, `billing-projection-checkpoint.md`,
  `acceptance-pin-checkpoint.md`, `reader-guard-checkpoint.md`): core's unit-bearing
  accessor and mechanism-owned `project_billing`; VM's retained pricing record; the
  signed-acceptance pricing pin (D2b) verified before acceptance and on recovery; every
  accepted financial reader migrated. Round 1's fail-closed amount-read guard was
  removed in round 2 (5.1; owner record 01, R6), and its packet says so. A
  `pricing_record.py` extraction keeps the proof-retention helper out of the buyer
  composition, avoiding an import cycle.
- 2.2 (`capacity-bounds-checkpoint.md`): strict per-mode bound hints, independent tier
  precedence, the nullable absolute-bound column and republication on the same
  identity, with the projection-aware override check. Bare metal's positive-maximum
  reserved hold, kept then, was retired in round 2 (9.2; R27).
- 2.3 (`recurring-publication-checkpoint.md`): per-clause recurring presets through an
  injected helper, the 24-period penalty default, runway and unbounded-horizon
  omissions and seller diagnostics. Its `pricing.bare_metal.settlements` hint was
  replaced by the shared resolver (9.1; R28), its deadline source by the clause
  fallback (8.1; R21), its fractional-default refusal by the floor (5.4; R9).
- 3.1 (`servicing-declaration-checkpoint.md`): the publication and cached-acceptance
  gates. Its revision/`published`/`proposed`-lane declaration was replaced by the
  treatments table (6.1; R15, R16, R19).
- 3.2–3.3 (`horizon-acceptance-checkpoint.md`): one fixed acceptance instant and the
  `resolve_acceptance` hook on all four paths, `resolve_horizon` in
  `kit/settlement-runtime`, whole-second recurring starts and the runway; only VM's
  round-zero and rate-pin fallbacks removed. Bare metal's fixture stops at the no-write
  opening plan, since its rate-mandate capture is spot's.
- 4.1a (`buyer-rights-checkpoint.md`): `BuyerTermsPolicy` over `AuthoritySelection` and
  `default_buyer_refusals`, codec-derived lifecycle disclosure on stderr. Its single
  `--allow-unprotected-terms` waiver was split into per-term waivers (10.1; R14).
- 4.1b (`buyer-presentation-checkpoint.md`): `present_payment`, the optional recurring
  horizon and accepted-recovery disclosure. Two kept schema-opaque negotiation fixtures
  omit the production acceptance callback, since their synthetic Alkahest-tagged
  options are not real escrow parameters. Bare metal's implicit one-hour default,
  removed then, was restored for reserved options (10.2; R18) and made configurable
  (12b.3).

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
  The guard was removed by 5.1 (owner record 01, R6); the permanent tests are 11.1 and
  11.3's.
- [x] 2.2 Add validated relative/UTC absolute hints in `kit/resource-pools-contracts`,
  models in `domains/vms/domain/src/arkhai_vms` and
  `domains/bare_metal/src/arkhai_bare_metal`, and both storefronts' override/default
  resolution. Keep bounds on the listing, not on each option. Carry/clear the absolute
  term through shared storefront persistence and existing opaque registry publication;
  use the pool-override kit's existing live fetch to validate cross-tier conflicts before
  writes. Verify pure validation and tier precedence in the package unit suites;
  no new network calls or lease changes here.
  Permanent tests: 11.2 (pure) and 12.3 (application integration).
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
  The deadline source became the clause fallback (8.1); the publication step was shared
  (7.1).

## 3. Servicing doors and acceptance

- [x] 3.1 In `kit/settlement-runtime` define the composition-owned declaration agreed
  with the rate adapter. Wire both storefronts' publication and acceptance checks;
  reject cached recurring options before acceptance persistence. Unit verification
  covers published/proposed contract selection and lane-only opt-in; app integration
  uses each storefront's typed client and real persistence to prove the cached-option
  refusal has no acceptance side effect.
  The declaration's form was replaced by 6.1.
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
  Requalified under the treatments table by 6.3 and 12b.1.

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

### Mixed-selection and integration outcome (2026-11-07)

- 4.1/4.2: both buyer commands select a mixed publication's reserved, on-demand and
  spot peers with both bounds, omitted and shorter horizons and default disclosure; VM
  also selects Alkahest, shown as making no delivery promise; bare metal's payments-only
  buy command admits the Alkahest peer in its shared policy without a fabricated stage.
  Proposed mechanism ports are diagnostic only (`mixed-selection-checkpoint.md`;
  `mixed_selection_probe.py` stays as evidence, 12.3).
- 4.3: VM storefront application targets 140, VM buyer 215, bare-metal 185 passed;
  packaging, `make check-change` and strict OpenSpec validation passed. The local E2E
  attempt with the prescribed Podman provider failed before readiness on the Compose
  assembly gap recorded in `openspec/changes/README.md`; that "unobservable" disposition
  was replaced (owner record 01, R23): the E2E evidence is validation's, whose pipeline
  run 43118309706 at `6f86ac5e6` ran the VM and bare-metal lanes (validation 05), and an
  unrun lane at closeout is a blocker.
- Rebased onto `origin/dev` (`cf4db5b7f`) with the dependency merges preserved, then
  replayed onto dev as round 1 on the review branch the owner chose. No architecture
  exception belongs to this change.

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
- Workflow maintenance outside the scope, small and read-only (pre-closeout review 36,
  F1): `adf435188` adds `Bash(git config --get-regexp remote)` to triage's allowlist in
  `.claude/change-steps.toml`. Round 1's triage was denied that call while checking
  whether this clone names a `workspace` remote, and the owner decided to add it to the
  step table once the round was triaged.
- V1 fix (validation 05 V1, owner record 01 R4's adaptation, made in the triage):
  `domains/vms/buyer/src/arkhai_vms_buyer/pricing_record.py` retains the listing's
  `pricing` object, compares it whole with the signed publication body, requires the
  lifted `rate_structure` to equal the body's `pricing.rate_structure`, and digests
  that for the round pin; its permanent tests are 12.2 and 12.3's. Evidence: VM
  storefront integration 575 passed, including the `…reaches_acceptance[True]` case
  that failed at `6f86ac5e6`; VM buyer 256 passed; `scripts/change-workflow run
  pre-commit` passed every hook on the final state. One `make test` run failed once on
  the `test_change_clone.py::test_the_bootstrap_failed` workflow-tooling flake
  (`ChildProcessError: No child processes`), unrelated to this diff; its rerun and the
  targets it left unrun passed.
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
  Done: the scripts and probe removed; the `Makefile`, `scripts/check_change.py` and
  `scripts/tests/test_check_change.py` match `origin/dev` again (reverted with the Edit
  tool after `git checkout origin/dev -- <paths>` was denied, which the owner
  accepted). `reader-guard-checkpoint.md` says the guard was removed and names its
  files without paths.
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
  servicing declaration 6.1 reshapes.
  Done: `check_accepted_horizon` with the shared `bound_seconds`/`parse_utc`, which
  `resolve_horizon` and `derive_rate_preset` also use. Bare metal calls it in `buy`'s
  `validate_acceptance` after the quote check (a refusal ends the run as
  `agreement_off_quote` before approval). VM: `validate_buyer_acceptance` takes the
  listing and requested duration; `negotiate_with_seller` binds them (a resume binds
  the seller's round-zero echo of the buyer's terms), and core-orchestrated `market buy`
  binds them per match through the new `acceptance_validator` factory on core's
  `make_negotiate_hook`, since core's guard sees only the outcome.
  `accepted_listing_record` keeps both bounds. F2: a provision duration is compared
  only when present. Seams' rationale: `design.md` D5. Tests (unit unless noted):
  `kit/settlement-runtime` `test_horizon.py`; VM `test_accepted_horizon.py`, two
  `test_buyer_client.py` cases through the file's patched transport and
  `test_buy_orchestrator.py` (an orchestration path, core's orchestrator with the seller
  transport and registry query patched); bare metal's four refusals before approval;
  core's `test_selected_option_negotiation.py` `acceptance_validator` cases. One VM
  orchestrator fixture advertising 3600 under a 7200-second deal now advertises 7200.
- [x] 5.4 **The horizon floor and the acceptance hook (R9):** when the buyer names no
  horizon and the limiting bound is a fractional-second `available_until_utc`, floor the
  default horizon to whole seconds instead of refusing, at acceptance
  (`resolve_horizon`) and at publication (R10).
  Done through the one `bound_seconds` both call. Tests (unit): `test_horizon.py` binds
  72000 seconds under a bound 72000.4 seconds away and covers the runway's 50-minute
  case (refusal below 3000 seconds, admission at 3000; not the spec scenario's
  last-instant approval clause), the refusals and a nonpositive bound;
  `test_rate_publication.py` floors the published default and reports no-runway and
  unbounded candidates.
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
  Done (2026-11-12), after `make dist`: settlement-runtime 208, VM buyer 266, bare-metal
  buyer 37, core buyer 170, VM storefront unit 1180 (1 skipped) and integration 575,
  bare-metal storefront 611, all passed; `make check-comment-hygiene` and every
  pre-commit hook passed. The compliance check's seven findings (suite labels, a level,
  the runway claim, three untested seams, the attachment's dead citations, the buyer
  check's missing decision and destination, a docstring naming a planned step) were
  fixed.

### Round-2 session note (2026-11-12)

- The first round-2 session took 5.1, 5.3 and 5.4 and stopped at a verified point;
  the owner returned the change to planning to split section 5 into one-session
  sections (`design.md`, "Implementation cadence").
- Rebuild before testing a consumer of a changed kit: the domains install kits from
  wheels, so `make dist`, then each package's `make -C <package> test`; `uv run
  pytest` in a buyer or storefront directory does not resolve its split environments.
  Never edit files while a background `make test` or `pre-commit` runs.

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
  Done (2026-11-12): `RateServicingDeclaration(mechanism, treatments, setup)`, the
  treatments named as the payment authority names them; `RateServicing` with
  `from_tables`, `select`, `require` and `require_option` (reading the option's
  entitlement and term-end treatments, and `setup_amount` beside a rate marker as a
  setup charge); `derive_rate_preset` checks treatments and setup before the helper
  runs, and setup also needs the helper's `supports_setup_delivery_end`. One typed
  model, `RateServicingTable`, is what the loader validates and the values schema
  renders. The seller's `[Settlement]` root takes `rate_servicing` (a buyer's refuses
  it); both builders pass it to the composition; neither negotiation runtime changed.
  Outside the plan's file list, as the key requires: `kit/config`'s
  `settlement_fragment` and the regenerated Helm schemas. Unit tests: each storefront's
  `test_the_configured_rate_servicing_declaration_is_the_compositions`.
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
  Done (2026-11-12) at that reach, as
  `test_an_omitted_horizon_is_accepted_at_the_default_bound_the_buyer_checks` and
  `test_a_buyer_that_named_no_duration_verifies_the_accepted_pricing`. Both stood
  fixtures at unimplemented recurring ports and were carried to
  `spot-deals-through-arkhai-payments` by 12b.2 (D6); their lowest-level replacements
  are 12b.1's.
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
  Done (2026-11-12). Unit: `test_rate_servicing.py` (new; `test_servicing.py` holds the
  servicing worker's tests) — parsing, absent/empty, malformed tables, each undeclared
  treatment, setup, either rate marker alone; `test_rate_publication.py`'s
  `FixtureHelper` cases for undeclared treatments and setup, a declared treatment the
  helper cannot enforce, declared setup without helper support; `test_configuration.py`
  and `kit/config`'s values-schema test. The application-integration cases built on each
  storefront's `tests/recurring_world.py` stood fixtures at unimplemented ports and were
  carried by 12b.2; the cached-selection door is tested again without them by 12b.1's
  `test_selected_rate_servicing.py` and the round-4 triage's typed-client test.
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
  Done (2026-11-12), after `make dist` and `make helm-values-schema`: settlement-runtime
  237, `kit/config` 273, VM storefront unit 1181 (1 skipped) and integration 579,
  bare-metal storefront 614, VM buyer 266, all passed; comment hygiene and every
  pre-commit hook passed. The compliance check's findings were fixed; its open question
  on the integration worlds' port fixtures was settled at closeout (D6, 12b). No
  `Owed by validation:` evidence: no CI workflow a push alone produces bears on this
  section.

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
  Done (2026-11-12): `ClausePublication`, a frozen dataclass of what is fixed per
  composition, whose `publish(...)` resolves the deadline, branches recurring
  (`derive_rate_preset`) or once (`registry.build_option`), admits each option against
  the declaration and reports default-buyer refusals. A `clause` of `None` is VM's
  no-clauses path. Readiness and clause filtering stay the compositions'. The step
  publishes each option as its builder built it; a builder returning no mapping raises
  `ValueError`, which VM's listing creation already raised; VM's readiness no longer
  receives keys only the payments builder reads; the deadline lookup runs per published
  clause. Existing suites passed unchanged but for `default_penalty_periods=24` on two
  namespace compositions.
- [x] 7.2 **The penalty setting (D3; R11), from 5.8:** replace the hard-coded
  `default_penalty_periods=24` with `[pricing].default_premature_stop_penalty_periods`
  (default 24), read in both storefronts' configuration and passed to the shared step;
  a penalty stated on a clause still wins. Validate it as a positive integer at load.
  Done (2026-11-12): `DEFAULT_PREMATURE_STOP_PENALTY_PERIODS` and `PenaltyPeriods` in
  `rate_publication.py`; VM's `default_premature_stop_penalty_periods()` among
  `server.py`'s startup refusals; bare metal's `PricingSettings` field refused by
  `load_storefront_settings`; both packaged `settings.toml` state 24; the bare-metal
  chart schema regenerated. The storefront-publication delta states the startup refusal.
- [x] 7.3 **Permanent tests (R2):** unit, in `test_rate_publication.py`: the shared
  step's once and recurring branches, its diagnostics for a missing helper, undeclared
  servicing and an unbounded horizon, the default multiple, a configured multiple and a
  clause's own penalty winning; each storefront's configuration test for the setting's
  default, a configured value and a refused nonpositive one.
  Done (2026-11-12). Unit: `test_rate_publication.py` (both branches, each omission
  diagnostic, default and configured multiples, a clause's `"0"` and `"1000"` winning,
  spot none); each storefront's configuration loader tests (VM's cover the reader, not
  its call among `server.py`'s refusals, which no test drives); each composition's
  `test_the_configured_penalty_multiple_is_the_compositions`. The application-integration
  case added beyond the plan stood on the recurring world and was carried by 12b.2.
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
  Done (2026-11-12): settlement-runtime 250, VM storefront unit 1188 (1 skipped) and
  integration 580, bare-metal storefront 620, all passed; comment hygiene and every
  pre-commit hook passed; the compliance check's findings were fixed. No `Owed by
  validation:` evidence: no CI workflow a push alone produces bears on this section.

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
  Done (2026-11-12), with the precedence where the mechanism reads its clause (D3):
  the payments builder takes the pool's `delivery_deadline_seconds` resource for a
  compute option when not `None`, else its clause's; `RatePresetPricing` gains
  `delivery_deadline_seconds`, which `derive_rate_preset` takes only when the pool
  gives none. Neither composition changed. Spot's positional `RatePresetPricing` call
  is unaffected; `dependency-contracts.md` names the one line its helper adds.
- [x] 8.2 **The protected E2E purchases (R22), from 5.6:** both reserved-payment drivers
  (`e2e-tests/tests/e2e/roles/scenarios/vms/purchase_driver.py`,
  `e2e-tests/tests/e2e/roles/scenarios/bare_metal/purchase_driver.py`) drop
  `--allow-unprotected-terms` and assert that the published `delivery_deadline_seconds`
  equals the configured value; `e2e-tests/tests/unit/test_dispute_coverage.py` returns
  to its earlier fixtures (task 4.4's reversal).
  Done (2026-11-12): the three files are as before round 1 (`git diff 6f86ac5e6~1 --
  e2e-tests/tests/` empty). Both lanes publish the clause's deadline, since no deployed
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
  Done (2026-11-12). Unit: `kit/arkhai-payments` `test_publication_builder_publishes_the_pool_deadline_else_the_clause_s`;
  `test_rate_publication.py` (pool over clause, clause alone, neither with its
  diagnostic, invalid clause deadlines refused); each composition's
  `test_the_pool_port_s_deadline_for_the_candidate_reaches_the_option_builder` (only
  the pool's value or `None` reaching the builder, since the fallback is the
  mechanism's); `make test-e2e-unit` for 8.2. The application-integration case's once
  half was rewritten without the recurring world by 12b.1
  (`test_a_once_payment_option_publishes_its_clause_s_deadline_where_the_pool_supplies_none`,
  both storefronts); its recurring half was carried by 12b.2.
- [x] 8.4 **Verify:** `make dist`, then `make -C kit/arkhai-payments test` (unit),
  `make -C kit/settlement-runtime test` (unit and library integration),
  `make -C domains/vms/storefront test`,
  `make -C domains/bare_metal/storefront test`, `make test-e2e-unit` (unit),
  `make check-comment-hygiene` and `scripts/change-workflow run pre-commit
  negotiate-open-ended-compute-terms`. End-to-end: `vms/test_vm_payment_purchase.py` and
  `bare_metal/test_bare_metal_payment_deal.py` run the protected purchases and assert the
  published deadline; validation's pipeline lanes (e2e-vm, e2e-bare-metal) are the
  evidence for this section.
  Done (2026-11-12): arkhai-payments 227, settlement-runtime 258, VM storefront unit 1190
  (1 skipped) and integration 582, bare-metal storefront 624, e2e unit 896 (1 skipped),
  all passed; comment hygiene, citations and every pre-commit hook passed. The
  compliance check found the permanent `deal-lifecycle` requirement contradicting R21's
  clause fallback; the change carries a `deal-lifecycle` delta of its two
  delivery-deadline requirements, renamed at closeout (13.3). No `Owed by validation:`
  evidence: validation dispatches those lanes itself, and no CI workflow a push alone
  produces bears on this section.

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
  Done (2026-11-12): `market_resource_pools_contracts.listing_terms` (`ListingTerms`,
  `resolve_listing_terms` over D10's five tiers, the hint readers and strict
  `model_hint_bounds`). It resolves no bounds: VM composes its v0.3.0 per-model bound
  tiers below the mode hint, bare metal keeps per-pool bounds (D10). Bare metal resolves
  each candidate's clauses with its machine's `gpu_model`, the family key read from
  `COMPUTE_CAPABILITY_SCHEMA`; `publication_terms.py` and its `pool_pricing_unreadable`
  hold are removed. Outside the plan's file list, for the fourth tier: bare metal's
  `[pricing.defaults.gpu.<model>].settlements`, compiled at startup, with its
  `settings.toml` and chart schema. A wrongly shaped hint field falls through in both
  domains. Versions: contracts 0.3.0 → 0.4.0 and `arkhai-vms-listings` 0.8.0 → 0.9.0
  (both released at `marketplace-v0.3.0`), consumers' floors raised.
- [x] 9.2 **The reserved-bound rule (D5; R27), from 5.9:** in both domains no positive
  relative maximum means no relative limit; retire `pool_lease_bound_missing` and
  `reserved_lease_bound_missing`, and add the bare-metal upgrade step (the replaced hint
  and the retired diagnostic) to `docs/operator-handbook.md`.
  Done (2026-11-12): both holds removed; a bare-metal pool resolving no positive maximum
  publishes with `max_duration_seconds` null, as VM did. `docs/operator-handbook.md`,
  "What the upgrade from v0.3.0 changes", gains the two bullets (held pools publish
  unbounded; bare metal reads the pool's `pricing` hint). The replaced hint was never
  released, so no migration step names it. `DEPLOYMENT_AND_CONFIG.md`'s bare-metal
  override bullet and `storefront-publication/architecture.md` are promoted at closeout
  (13.9).
- [x] 9.3 **Permanent tests (R2):** unit, in `kit/resource-pools-contracts/tests`: each
  tier of D10's order winning field by field, the pool-level hint, a v0.3.0 VM
  configuration and hint unchanged, bounds keeping D5's order; the moved
  `domains/vms/storefront/tests/unit/test_pricing_resolution.py` cases follow the
  resolver. Application integration through each storefront's typed client: a pool-level
  `pricing.settlements` hint publishes its clause in both domains; a reserved option
  publishes without a relative maximum in both domains.
  Done (2026-11-12). Unit: `test_listing_terms.py` (each tier, whole lists, malformed
  hints falling through, `model_hint_bounds`); VM `test_pricing_resolution.py` keeps the
  v0.3.0 configuration and bound-tier cases, since the kit resolves no bounds (a
  departure from the plan's line); bare metal's cycle, configuration and composition
  tests. Application integration through the typed admin client with real SQLite, both
  storefronts: `test_a_reserved_option_publishes_with_no_relative_maximum` and
  `test_pool_level_clauses_publish_below_a_model_hint`.
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
  Done (2026-11-12): contracts 449, VM storefront unit 1189 (1 skipped) and integration
  584, bare-metal storefront 629, all passed; comment hygiene and every pre-commit hook
  passed. The compliance check's high finding (API added under released versions) was
  fixed by 9.1's bumps; the rest were fixed but VM's pre-existing `GPU_FAMILY_KEY`
  literal, declined. No `Owed by validation:` evidence: no CI workflow a push alone
  produces bears on this section.

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
  Done (2026-11-12): the named refusal terms in `rate_publication.py`; `buyer_terms.py`'s
  `TERM_WAIVERS` table, `term_waivers`, `waiver_flags`, `allows_missing_delivery_deadline`
  and `waivers_from_flags`; `BuyerTermsPolicy(authority, waivers=...)`;
  `lifecycle_disclosure(..., waivers=)` marking a waived refusal and listing "Waivers in
  force". The three commands declare the flags from the table; `run_started` records
  `compute_term_waivers`, replacing round 1's unreleased boolean. Both disclosures before
  approval name them in both domains (the accepted one after the compliance check). A
  resumed or recovered VM run reads them from its run log (`recorded_waivers`), and
  `buy`/`negotiate --from` refuse waiver flags.
- [x] 10.2 **Durations (D11; R18), from 5.7:** `bare-metal buy` restores the
  3600-second default for reserved options only, shown as the buyer's default in the
  disclosure, never for recurring ones; VM's `market buy`/`negotiate` gain
  `--duration-seconds` beside `--duration-hours`, both together an error naming the
  conflict.
  Done (2026-11-12): bare metal's `requested_duration(option, duration, registry=)`
  takes the buyer's duration, else the default where the mechanism's `project_billing`
  says `total`, else none; the disclosure's "Requested horizon" row says it is the
  buyer's default and `run_started` records `default_duration`. The constant default was
  replaced by the configured `default_duration_seconds` in 12b.3. VM's
  `cli_helpers.requested_duration_seconds` refuses both flags together and a nonpositive
  value, first, before identity, registry or resume handling.
- [x] 10.3 **Permanent tests (R2):** unit, in `kit/settlement-runtime/tests/unit`: each
  flag waiving exactly its refusal, the shorthand waiving all four, the foundation flag
  set only by the deadline waiver or the shorthand. Each buyer's CLI suites
  (`domains/vms/buyer/tests/test_buy_resume_cli.py`, `test_explain_cli.py`;
  `domains/bare_metal/buyer/tests`): the flags parsed, recorded in run metadata and named
  in the disclosure; the bare-metal reserved default shown as the buyer's and absent for
  a recurring option; both VM duration flags refused together.
  Done (2026-11-12), unit. `test_buyer_terms.py` (new): each refusal alone, each flag
  waiving exactly its term, the shorthand, waivers not bypassing codec or authority, the
  foundation allowance, unknown waivers, the disclosure rows, recorded flags read back.
  Bare metal's `buy` through `CliRunner` (`test_cli_completion.py`'s `_compose`, which
  replaces imported names as the file's cases do — the command-module gap
  `docs/development/ROADMAP.md` records): the reserved default, `requested_duration` per
  billing basis, waivers recorded and named in both disclosures; `test_buyer_composition.py`.
  VM: `test_buy_resume_cli.py` (both duration flags refused before any identity read, a
  nonpositive `--duration-seconds`, resumes refusing waiver flags, fresh waivers recorded
  and named), `test_term_waivers.py` (new), `test_vm_settlement_helpers.py`,
  `test_buyer_client.py`'s accepted-disclosure case. Not added to `test_explain_cli.py`
  (it tests `market listing`). Not driven by a VM test: a payments option through `market
  buy`'s selected-option disclosure, `negotiate`'s fresh waivers past the duration check,
  the resumes' hand-off of recorded waivers, `make_legacy_negotiate_hook(waivers=)` and
  `market settle --from`'s call of `recorded_waivers`; the pieces they share are tested.
- [x] 10.4 **Verify:** `make dist`, then `make -C kit/settlement-runtime test` (unit and
  library integration),
  `make -C domains/vms/buyer test` (unit), `make -C domains/bare_metal/buyer test`
  (unit), `make -C core/buyer test` (unit), `make check-comment-hygiene` and
  `scripts/change-workflow run pre-commit negotiate-open-ended-compute-terms`.
  End-to-end: the reserved purchases buy without waivers since section 8; none passes a
  per-term flag, and none is owed, since a flag's effect is the buyer's own policy,
  which the unit suites prove.
  Done (2026-11-12): settlement-runtime 283, VM buyer 286, bare-metal buyer 53, core
  buyer 170, all passed; comment hygiene and every pre-commit hook passed; the
  compliance check's findings were fixed. No marker in `e2e-tests/` passes a waiver
  flag or VM's `--duration-seconds`; bare metal's driver names its duration. No `Owed
  by validation:` evidence: no CI workflow a push alone produces bears on this section.
  The unread `BareMetalBuyerConfig.default_duration_seconds` this section left for the
  triage was settled at closeout: honoured (D11, 12b.3).

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
  Done (2026-11-12), unit. Core: the accessor's total and per-period reads (5,000,000;
  625,000; 41,667) at any horizon, refusals of a missing or contradictory projection
  and of an amount beyond uint256, and the acceptance-bound listing's membership check.
  Rounding upward once is VM's `quote_from_multiplier` (the accessor never rounds),
  tested in `domains/vms/storefront/tests/unit/test_vm_multiplier.py`. Each
  registration's `project_billing`: Alkahest, payments and contact totals and their
  refusals.
- [x] 11.2 **Bounds, the buyer's policy and presentation (D5, D7; R2):** capacity-bound
  validation and tier selection in `kit/resource-pools-contracts/tests`;
  `default_buyer_refusals`, `lifecycle_disclosure` and `present_payment`'s registry checks
  (basis, asset, accepted money unchanged, missing presenter refused) in
  `kit/settlement-runtime/tests/unit`.
  Done (2026-11-12), unit: `test_capacity_bounds.py` (new: strict UTC and relative
  parsing, per-mode hints, malformed hints refused naming where, tier resolution and
  masking); `test_buyer_presentation.py` (new: `default_buyer_refusals`,
  `lifecycle_disclosure`'s rows, `present_payment`'s checks, and beyond the plan
  `compute_disclosure`'s per-period, spot and reserved displays).
- [x] 11.3 **Every money consumer with a per-period Agreement (D2; R6):** mandate
  derivation (`kit/arkhai-payments/tests`), buyer caps and display, recovery and
  confirmation (`domains/vms/buyer/tests`, `domains/bare_metal/buyer/tests`), each driven
  with a per-period Agreement and asserting the money is read once, never scaled by
  duration or multiplier again.
  Done (2026-11-12), unit. The buyers inject a per-period projection, since none is
  installed. Mandate (`test_agreement.py`): the one part charges the accepted amount at
  any duration, and a payments option carrying `period` is refused at all three entry
  points by the projection's strict codec; the mandate policy's own non-total guard is
  unreachable and untested (`design.md` D2). VM: `test_negotiation_amounts.py` (one
  period's payment, the per-hour ceiling and bounds per period), `test_per_period_acceptance.py`
  (new: `verify_pricing_acceptance` over a real seller-signed publication, and the
  confirmation showing per-period and total charges unscaled); core's
  `test_identity_recovery.py` (`exact_agreed_amount` refusing a per-period or
  unprojected option); bare metal `test_purchase_quote.py` (new). Not covered: `market
  buy`'s or `bare-metal buy`'s own flow with a per-period option, which no installed
  mechanism reaches.
- [x] 11.4 **Verify:** `make dist`, then `make -C core test` (unit), `make -C
  kit/alkahest test`, `make -C kit/arkhai-payments test`, `make -C kit/contact-exchange
  test`, `make -C kit/resource-pools-contracts test`, `make -C kit/settlement-runtime
  test`, `make -C domains/vms/buyer test`, `make -C domains/bare_metal/buyer test` (all
  unit), `make check-comment-hygiene` and `scripts/change-workflow run pre-commit
  negotiate-open-ended-compute-terms`. End-to-end: none; no deployed run produces a
  per-period Agreement (the unowned gap in `openspec/changes/README.md`), so these unit
  tests are the money consumers' evidence.
  Done (2026-11-12): core 130/170/227/68, alkahest 465, arkhai-payments 235,
  contact-exchange 146, resource-pools-contracts 478, settlement-runtime 302, VM buyer
  299, bare-metal buyer 63, VM storefront unit 1192 (1 skipped) and integration 584, all
  passed; comment hygiene and every pre-commit hook passed; the compliance check's
  findings were fixed (the VM confirmation test types its decline rather than patching
  `typer.confirm`). No `Owed by validation:` evidence: no CI workflow a push alone
  produces bears on this section.

## 12. Permanent integration tests, the retained pricing record and the round's validation

Delivers R2's application-integration tests of round 1's behaviour (D1, D5, D2b), R4's
pin tests and the retained-record confirmation (D2b), the probes' conversion (R2, R7),
and the round's validation. Touches the VM and bare-metal storefronts' integration
suites, the VM buyer and the change's probes.

- [x] 12.1 **Publication and acceptance through the typed client (D1, D5; R2):** each
  storefront with real SQLite: mixed publication on one capacity identity (reserved,
  on-demand, spot with an injected declaration); a horizon refusal naming the minimum
  that passes the runway.
  Done (2026-11-12) as
  `test_one_listing_offers_reserved_on_demand_and_spot_on_its_capacity_identity` and
  `test_a_horizon_leaving_no_runway_is_refused_naming_the_minimum_that_passes` in both
  storefronts, over the recurring world. Both stood fixtures at unimplemented ports and
  were carried by 12b.2; their lowest-level replacements are 12b.1's (the three-class
  derivation and `test_the_horizon_leaves_no_runway`).
- [x] 12.2 **The retained pricing record and pin tests (D2b; R4), from 5.10:** confirm no
  other buyer read compares a top-level `rate_structure` with a signed body (the
  triage's V1 fix covered `pricing_record.py`); application integration through the VM
  storefront's typed client: pin production and verification against a dev-shaped
  publication whose `pricing` object carries the rate structure, a changed pin refused,
  and a legacy record without proof failing closed for multiplier pricing.
  Done (2026-11-12). Only `pricing_record.py` compares with a signed body; every other
  buyer read is of the lifted copy `domain_listing_record` makes. Application
  integration, VM `test_the_signed_pricing_pin_binds_the_registry_publication_at_acceptance_and_on_resume`:
  the production buyer client over loopback against the served storefront, opening
  below the listed rate so the seller counters, a publication proof signed in the test
  with the seller's key (no registry runs), every archived reply naming the published
  digest, the acceptance's `pricing_pin` binding the multiplier, the kept record
  verifying again as a resume does, a changed pin refused and a record without proof
  failing closed. The negotiated option is the shape-priced pool's Alkahest option (6.2:
  the production client cannot open a recurring payments negotiation).
- [x] 12.3 **The probes (R2, R7):** convert the change's probes under
  `openspec/changes/negotiate-open-ended-compute-terms/` that drive real seams into
  tests at the level `docs/development/TESTING.md` assigns, where 11.1–12.2 and sections
  6–10 do not already cover them; task 1.2's codec probe becomes a test or is dropped
  where a `kit/deal-lifecycle` suite covers the round trip. The rest stay as closeout
  evidence; record which went where in this task's note.
  Done (2026-11-12). Converted: `capacity_bounds_probe.py`'s app paths into VM
  `test_each_capacity_bound_resolves_from_its_own_tier_onto_the_published_listing` and
  `test_withdrawn_capacity_bounds_are_cleared_from_the_listing_and_its_publication`, and
  bare metal's first of them (application integration); `acceptance_pin_probe.py`'s
  record and archive checks into the VM buyer's `test_pricing_record.py` (new, unit).
  Dropped as covered: `codec_probe.py` (by `kit/deal-lifecycle` `test_terms.py`,
  payments' `test_agreement.py` and the published-option tests), `price_probe.py`,
  `billing_projection_probe.py` and `consumer_price_probe.py` (11.1, 11.3, 12.2),
  `seller_pin_probe.py` (12.2 and `test_vm_multiplier.py`), `horizon_probe.py`
  (`test_horizon.py` and 12b.1's replacements), `recurring_publication_probe.py`
  (sections 6–8's unit tests), `buyer_terms_probe.py` (10.3, 11.2). Stay as evidence:
  `mixed_selection_probe.py` and `buyer_presentation_probe.py`'s `market settle --from`
  replay (they replace names inside the commands, which no new test may), and
  `registry_codec_probe.py` with `codec_probe.py`'s registry leg: no test sends a full
  `early_termination`/`adjudication` through a real registry, which carries an option as
  opaque JSON. The buyer commands' first use of a mixed listing has no permanent test of
  its own: the command-module seams `docs/development/ROADMAP.md` records. No probe file
  was removed; the round-1 attachments cite them, and closeout (13.4) decides both.
- [x] 12.4 **Verify the section:** `make dist`, then `make -C domains/vms/storefront test`
  and `make -C domains/bare_metal/storefront test` (unit and application integration),
  `make -C domains/vms/buyer test` (unit), and any suite 12.3's conversions land in.
  Done (2026-11-12): VM storefront unit 1192 (1 skipped) and integration 589, bare-metal
  storefront 632, VM buyer 315, all passed after the compliance fixes. Outside the plan:
  the VM storefront's `dev` group declares `arkhai-core-buyer`, which its tests import,
  relocked by `make lock`.
- [x] 12.5 **Validate the round (R23), from 5.11:** every suite sections 5–12 named,
  `make check-packaging`, `make check-comment-hygiene`, `make check-architecture-change
  CHANGE=negotiate-open-ended-compute-terms` and `scripts/change-workflow run pre-commit
  negotiate-open-ended-compute-terms`. End-to-end: validation's VM and bare-metal lanes —
  the pipeline, or a locally deployed stack where the owner waives the pipeline part —
  covering the protected purchases (`vms/test_vm_payment_purchase.py`,
  `bare_metal/test_bare_metal_payment_deal.py`) and the VM listing-shape lane
  (`vms/test_listing_shapes.py`); an unrun lane is a blocker at closeout.
  Done locally (2026-11-12): every pre-commit hook passed, `make test` covering every
  package suite sections 5–12 named; a second run hit the
  `test_change_clone.py::test_the_bootstrap_failed` workflow-tooling flake once, unrelated
  to this diff, and its rerun and the targets it left unrun passed. Comment hygiene and
  `make check-architecture-change` passed (the change owns no architecture row).
  End-to-end is validation's pipeline lanes. No `Owed by validation:` evidence: no CI
  workflow a push alone produces bears on this section.

### Section 12 handoff (2026-11-12)

- The compliance check's medium findings were fixed (the counter in 12.2's case,
  `registry_codec_probe.py` kept as evidence with its gap stated, pure refusals moved to
  unit level), as were its low findings. Declined: importing helpers from sibling test
  modules (these suites' practice), and a duplicate test helper.
- Round 2 (sections 5–12) was validated (validations 30 and 35), reviewed (review 28)
  and triaged.

## 12a. The version pass

Delivers the package versions, exact pins, lower bounds and locks
`docs/development/RELEASING.md`, "Versioning policy", requires for the sources this
change edits (repository obligation; found at the first closeout attempt, `tasks.md`
13.7's note; D12 for the release-compatibility principle). Touches the `pyproject.toml`
and lock of each package bumped and of each package pinning one: `core`, `core/buyer`,
`kit/alkahest`, `kit/negotiation-runtime`, `kit/arkhai-payments`, `kit/config`,
`domains/vms/domain`, `domains/vms/negotiation`, `domains/bare_metal`,
`domains/apicredits/buyer`, and their consumers. Changes no source behaviour. Planned
at the owner's direction (2026-11-12) as round 3, a one-section round whose validation
and implementation review are waived (`design.md`, "Implementation cadence").

- [x] 12a.1 **Audit against the policy's base:** measure every package whose sources
  the change edits against its version on `origin/dev`, the branch it merges into, as
  the policy says, starting from 13.7's list: still at the released version —
  `arkhai-core` 0.5.0, `arkhai-kit-alkahest` 0.11.0, `arkhai-kit-negotiation-runtime`
  0.5.2, `arkhai-vms` 0.8.0, `arkhai-bare-metal` 0.15.0, `arkhai-vms-negotiation` 0.6.0,
  `arkhai-apicredits-buyer` 0.8.0; patch-bumped on `dev` while this change adds API —
  `arkhai-kit-arkhai-payments` 0.6.2, `arkhai-core-buyer` 0.6.2, `arkhai-kit-config`
  0.5.2. Confirm no other package the diff from `origin/dev` touches was missed. For
  each, record in this task's note the bump the policy gives (minor for new public API
  or, before 1.0.0, an incompatible change; patch for a fix or internal change) and
  why, including the `arkhai-kit-config` schema table, which 13.7 left to this round.
  A package already bumped on `dev` is bumped again only where the change needs a
  larger bump than it has.
  Done (2026-11-12), against `origin/dev` at `07af25d57` with `marketplace-v0.3.0` as
  the last release; the diff's sources touch 21 packages. Bumped:
  - minor, for new public API: `arkhai-core` 0.6.0, `arkhai-kit-alkahest` 0.12.0,
    `arkhai-kit-negotiation-runtime` 0.6.0 (also carrying `dev`'s unbumped incompatible
    `negotiated_scalar` rename), `arkhai-vms` 0.9.0, `arkhai-bare-metal` 0.16.0 (also a
    wire change), `arkhai-vms-negotiation` 0.7.0, `arkhai-kit-arkhai-payments` 0.7.0,
    `arkhai-core-buyer` 0.7.0, `arkhai-kit-config` 0.6.0 (the seller's `rate_servicing`
    table is a new configuration surface, not a fix);
  - minor, for `dev`'s unbumped edits their first release carries, with the change's
    moved `arkhai-core` pin: `arkhai-core-registry-client` 0.13.0 (`extra`) and
    `arkhai-kit-policy` 0.7.0 (`amount_from_proposal`, `set_proposal_amount`);
  - patch: `arkhai-apicredits-buyer` 0.8.1 (internal).

  Not bumped again: `arkhai-vms-listings` 0.9.0 and contracts 0.4.0 (9.1), and the
  packages `dev` already bumped by at least a minor (core-storefront, settlement-runtime,
  contact-exchange, pool-overrides, resource-pools, both compute buyers and storefronts,
  core-registry, apicredits-storefront). `dev`'s unbumped edits to
  `arkhai-core-storefront-client` and `arkhai-apicredits-domain`, which this change does
  not touch, are an unowned gap in `openspec/changes/README.md`.
- [x] 12a.2 **Bump and move the pins:** set each version 12a.1 records in its
  `pyproject.toml`; move every exact pin on a bumped package (13.7 names those on
  `arkhai-core`, `arkhai-kit-negotiation-runtime`, `arkhai-kit-arkhai-payments` and
  `arkhai-core-buyer`) and raise the lower bound of each consumer that imports the new
  API (the `>=0.11.0` bounds on `arkhai-kit-alkahest` in the API-credits and VM buyers,
  and any other consumer of an API this change added).
  Done (2026-11-12): every exact pin on a bumped package moved, and the lower bound of
  each consumer whose edited code imports the new API — or calls it through a
  registration given a new member (`project_billing`, `present_payment`) — raised to the
  version 12a.1 sets. Outside the plan, for the same reason: core-storefront's
  registry-client bound (`extra`) and the API-credits storefront's policy bound.
  Consumers whose sources the change does not edit keep their bounds. Fresh-context
  checks found two bounds left low over three passes; all were corrected before the
  final relock.
- [x] 12a.3 **Relock:** `make dist`, then refresh every lock the bumps and pins change,
  as `docs/development/BUILD_AND_PACKAGING.md` directs, deriving each from its project.
  Done (2026-11-12): `make lock` exit 0, rewriting 42 locks; none edited by hand.
- [x] 12a.4 **Verify:** `make check-packaging` (locks current with their projects and
  the wheels, layers, dependencies), `make check-version-bumps CHANGE_BASE=dev` (no
  version more than one SemVer step from the merge-base), `make check-comment-hygiene`
  and `scripts/change-workflow run pre-commit negotiate-open-ended-compute-terms`, whose
  functional hooks run the packaging check and every suite (unit, library integration
  and application integration) against the relocked environments. End-to-end: none; the
  pass changes no behaviour any scenario observes, and the owner waived this round's
  validation, so none is owed.
  Done (2026-11-12): every pre-commit hook passed on the final tree (`make lock`
  unchanged, `make check-packaging`, the whole `make test`, and the change checks with
  version bumps and comment hygiene); `make check-version-bumps CHANGE_BASE=dev` and
  `make check-comment-hygiene` passed. No `Owed by validation:` line applies.
  The audit method, for a later pass: list the packages whose `src/` the diff from
  `origin/dev` touches; compare each version at the release tag, on `origin/dev` and at
  `HEAD`; check `dev`'s unbumped edits since the release in every package the pass bumps
  or a moved pin forces it to bump; raise the bounds of consumers whose edited code
  imports that API or calls it through a mechanism registration.

## 12b. Closeout's fixes: no fixture-port storefront tests, the configured reserved default

Delivers the code two of the owner's answers to 13.3's questions need (13.3's note):
the storefront integration tests standing fixtures at unimplemented composition ports
leave this change (D6; `docs/development/TESTING.md`, "Integration Tests"), and
`bare-metal buy` gives a reserved option its configured `default_duration_seconds`
(D11; the `buyer-orchestration` delta's "Recurring purchase may omit a horizon").
Touches both storefronts' tests, `openspec/changes/spot-deals-through-arkhai-payments/`
(the carried copies), and the bare-metal buyer (`settlement_stages.py`, `cli.py`, its
composition and tests). Planned at the owner's direction (2026-11-12) as round 4, a
one-section round whose validation and implementation review are owed (`design.md`,
"Implementation cadence").

- [x] 12b.1 **Sort the fixture-port cases (D6):** for each of the fourteen tests 13.3's
  note lists — VM `tests/integration/test_publication_loop.py` (5),
  `tests/integration/test_buyer_selection_negotiation.py` (3), bare-metal
  `tests/test_http_publication_rates.py` (4) and `tests/test_http_negotiation.py` (2) —
  decide whether its behaviour needs a recurring encoder, term timing or a billing
  projection (the ports `tests/recurring_world.py` fixes in each storefront). A case that
  needs none (a once option's clause deadline, perhaps) is rewritten in place without the
  world; a case that needs one is carried. For each carried case, name the lowest-level
  test that still proves its door without a fixture (the publication omission, the
  cached-selection refusal, the penalty multiple, the clause deadline, the omitted
  horizon at the default bound, the unrequested-duration pricing check, the runway
  refusal naming the minimum) — `kit/settlement-runtime/tests/unit` (`test_servicing.py`,
  `test_rate_publication.py`, `test_horizon.py`), the buyers' unit suites — and add one
  where none exists. Record the sorting in this task's note.
  Done (2026-11-12). All fourteen are carried, since each publishes a recurring option.
  The once half of the clause-deadline case needs no port and is rewritten in place in
  both storefronts as
  `test_a_once_payment_option_publishes_its_clause_s_deadline_where_the_pool_supplies_none`
  (the real registry and payments once builder, a dispute authority, and as deployed no
  declaration, helper or pool deadline). The lowest-level test of each carried door:
  - publication omission: `test_rate_publication.py`
    (`test_an_undeclared_treatment_or_setup_omits_the_recurring_candidate`,
    `test_a_built_rate_option_the_servicing_declaration_withholds_is_omitted`) and
    `test_rate_servicing.py`;
  - the three classes on one listing:
    `test_a_declared_preset_is_encoded_with_the_selected_declaration`,
    `test_a_recurring_clause_is_derived_through_its_helper_and_never_the_registry`;
  - the penalty multiple:
    `test_on_demand_with_no_stated_penalty_takes_the_default_multiple_of_its_period_price`,
    `test_a_configured_multiple_replaces_the_default`, `test_spot_carries_no_default_penalty`;
  - a recurring option's clause deadline:
    `test_a_recurring_option_publishes_the_pool_s_deadline_else_its_clause_s`,
    `test_a_recurring_option_with_neither_deadline_publishes_with_its_diagnostic`;
  - the omitted horizon at the default bound: `test_horizon.py`
    (`test_an_omitted_recurring_horizon_binds_the_earliest_bound_at_a_whole_second_start`,
    `test_the_buyer_accepts_the_default_bound_for_an_omitted_horizon`);
  - the unrequested-duration pricing check: the VM buyer's
    `test_accepted_per_period_money_matches_one_signed_period_quote`;
  - the runway refusal naming the minimum: `test_the_horizon_leaves_no_runway`;
  - the cached-selection refusal: neither storefront's door reads a port first, so each
    gains `test_selected_rate_servicing.py` (VM `tests/unit/`, bare metal `tests/`),
    driving the real negotiation runtime over a real database whose listing record is
    seeded with a rate option as service-internal state, refusing under a narrowed
    declaration and under none with nothing kept. The signed HTTP answer is tested
    through each app since the round-4 triage (below).
- [x] 12b.2 **Carry and delete (D6):** copy each carried test, with the world module it
  uses, into `openspec/changes/spot-deals-through-arkhai-payments/carried-tests/`
  (`vms/` and `bare_metal/`), with a `README.md` saying what each case proves, which
  ports it needs, and that the change installing them restores the cases to the
  storefront suites once its code stands at those ports; add one line to that change's
  row Notes in `openspec/changes/README.md` pointing at the directory. Then delete the
  carried tests from the storefront suites, and each `tests/recurring_world.py` once
  nothing imports it; remove helpers only they used.
  Done (2026-11-12): `carried-tests/vms/` and `carried-tests/bare_metal/` hold each
  world module and the carried cases with their helpers; `carried-tests/README.md` gives
  each case's proof, storefronts and remaining lowest-level test, and the restore
  obligation; the spot row's Notes link it. The carried tests, both world modules and
  the helpers only they used are gone from the suites; nothing in `domains/` names
  `recurring_world`. Earlier notes citing a carried test now say it was carried.
- [x] 12b.3 **The configured reserved default (D11):** `bare-metal buy` gives a reserved
  option without a duration the loaded `BareMetalBuyerConfig.default_duration_seconds`
  in place of `RESERVED_DEFAULT_DURATION_SECONDS` in
  `domains/bare_metal/buyer/src/arkhai_bare_metal_buyer/settlement_stages.py`, still
  shown as the buyer's default and never applied to a recurring option; the
  `--duration-seconds` help in `cli.py` names the configured default instead of 3600.
  Unit tests in `domains/bare_metal/buyer/tests`: a configured value reaching the
  disclosure and the provision terms, the 3600 default when unconfigured, and a recurring
  option ignoring it. Confirm with `make check-version-bumps CHANGE_BASE=dev` that
  `arkhai-bare-metal-buyer`'s 0.8.0 on `dev` already carries the bump this needs.
  Done (2026-11-12): `requested_duration` takes a required `default_duration_seconds`,
  which `buy_bare_metal` passes from the loaded configuration; the constant is gone and
  the help names the key. Unit tests in `test_cli_completion.py`:
  `test_a_reserved_buy_naming_no_duration_requests_the_buyer_s_configured_default`
  (unconfigured 3600; a configured 5400 reaching the provision terms, quote, disclosure
  and run log) and `test_the_reserved_default_never_applies_to_a_recurring_option`. Bare-metal
  buyer 64 passed; `make check-version-bumps CHANGE_BASE=dev` OK (0.8.0 against 0.7.2
  released).
- [x] 12b.4 **Verify:** `make dist`, then `make -C domains/vms/storefront test` (unit
  and application integration through its typed client), `make -C
  domains/bare_metal/storefront test` (unit and application integration),
  `make -C kit/settlement-runtime test` (unit), `make -C domains/bare_metal/buyer test`
  (unit), `make check-comment-hygiene` and `scripts/change-workflow run pre-commit
  negotiate-open-ended-compute-terms`, whose functional hooks run the packaging check and
  every suite. End-to-end: `bare_metal/test_bare_metal_payment_deal.py` buys a reserved
  option with an explicit `--duration-seconds`, so it does not exercise the configured
  default; no scenario drives a recurring option (the per-period gap row), and none is
  owed — the default is the buyer's own resolution, which the unit tests prove.
  Done (2026-11-12): VM storefront unit 1194 (1 skipped) and integration 582, bare-metal
  storefront 629, settlement-runtime 302, bare-metal buyer 64, all passed; comment
  hygiene, version bumps and every pre-commit hook passed (a first run caught "no
  longer" in a docstring that went with a reverted refactor). The compliance check's
  gap — the cached-selection door untested at the storefronts — was fixed by 12b.1's
  door tests, with no storefront source change. No `Owed by validation:` line applies.

### Round-4 triage fixes (2026-11-12)

Review 49, validation 50 (passed), owner record 48 (no notes) and orchestrator
observation 51, all at `1fce75a13`.

- **49 F1 (fix, accepted by the owner):** each storefront's app suite gains
  `test_a_cached_rate_option_whose_treatment_is_withdrawn_is_refused_through_the_app`
  (bare metal `tests/test_http_negotiation.py`, VM
  `tests/integration/test_publication_loop.py`): a seeded rate option returning the last
  period, payments composed through the real registry with only `charged` declared and no
  recurring port, selected through the buyer's typed client, refused with the signed 409
  `settlement_option_withdrawn_refetch` and no negotiation written. With `returned` also
  declared each fails past the gate, so the gate is what it proves.
- **51 R1 (none, by the owner):** the computation reads any section whose title
  contains "closeout" as the closeout section (`scripts/change_workflow/next_step.py`,
  `Section.closeout`), which is why it skipped 12b as a round. It is not recorded as a
  gap. The owner will revisit it after this change merges to `dev`.
- Exit, on the owner's word: validate the fix commit, then closeout resumes at 13.3,
  with no further implementation review and no pre-closeout review.
- Evidence: bare-metal storefront 630, VM storefront integration 583, both passed;
  comment hygiene and every pre-commit hook passed (VM unit 1194, 1 skipped). Fix commit
  `052150004`; validation 57 passed (e2e.yml run 43303151315).

## 13. Closeout

Documentation-only, in `openspec/README.md#plan-closeout-requirements` order;
anything requiring code returns to implementation. Former numbers 6.1–6.11 are now
13.1–13.11.

Closeout ran three times on 2026-11-12. The first, at `7be0d48b8`, confirmed 13.1 and
13.2 and stopped at 13.7 for a version pass (section 12a). The second, at `1738eec49`,
stopped in 13.3 because two of the owner's answers needed code (section 12b). The
third, at `052150004` after validation 57 passed, completed 13.3–13.11 and archived
the change.

- [x] 13.1 **Comment hygiene:** run `make check-comment-hygiene`; confirm the comments
  rounds 1 and 2 added describe current invariants, not change provenance.
  Confirmed (2026-11-12): `make check-comment-hygiene` passed. I read the comments and
  docstrings the change added in `.py`, `.toml`, `.yml` and `.yaml` files against
  `origin/dev`. None names a review, round, owner record, decision number or migration.
  The only matches for "legacy" describe a current data shape: a raw escrow acceptance
  that names no option. Reconfirmed at `052150004`: `make check-comment-hygiene`
  passed, and the comments sections 12a and 12b added name no review, round, owner
  record or change.
- [x] 13.2 **Import placement:** confirm the imports the change added are module-level
  unless an experimentally verified circularity or deliberate lazy-load reason is
  recorded, including those of the modules sections 7 and 9 moved.
  Confirmed (2026-11-12): the production diff against `origin/dev` adds exactly one
  function-local import. It is in `domains/vms/buyer/src/arkhai_vms_buyer/deal_helpers.py`
  `load_deal_context`, which widens an existing local import of
  `.settlement_composition` to also take `buyer_settlement_registry`. The adjacent
  comment keeps the composition import-cycle reason. Every other import the change
  added is module-level, including those in `listing_terms.py` and `rate_publication.py`.
  The probes under the change directory are not production code. Reconfirmed at
  `052150004`: the diff from `1738eec49` (sections 12a, 12b and round 4's fix) adds no
  function-local import.
- [x] 13.3 **Documentation compliance:** classify D1–D12, including the horizon as the
  Agreement's refinement; verify each permanent home and no duplicated codec/authority
  ownership. Confirm or move D10's shared clause resolver out of
  `kit/resource-pools-contracts`.
  The owner's answers to the four questions the second attempt put (2026-11-12):
  - The resolver stays in `kit/resource-pools-contracts`: `listing_terms` takes the
    family key as data and names no compute concept (D10). `ARCHITECTURE.md`'s "Kit
    areas" now names it, and distinguishes it from the offering-mode resolver in
    `hints.py`.
  - `TESTING.md` stays as written, so the storefront tests built on fixtures at the
    unimplemented recurring ports left this change (D6). Section 12b carried them to
    `spot-deals-through-arkhai-payments` and kept a lowest-level test of each door
    (12b.1).
  - The `deal-lifecycle` delta's requirement is renamed by a RENAMED entry, "The
    delivery deadline is the availability term the site or the clause sets".
  - `bare-metal buy` honours its configured `default_duration_seconds` (D11), which
    section 12b implemented (12b.3).

  Classification (2026-11-12, at `052150004`): D1–D12 are all permanent and
  implemented, and none is temporary or superseded. The round-1 forms round 2
  replaced are rejected alternatives in `design.md`, not promoted: the amount-read
  guard, the revision/lane declaration, the blanket waiver, refusing a fractional
  default, bare metal's reserved hold and its family-keyed hint. The horizon as the
  Agreement's `duration_seconds`, with no option term, is D5's, normative in
  `negotiation-protocol` through the delta. Each decision's home follows
  `openspec/README.md#documentation-placement`:
  - normative behaviour goes in the six deltas;
  - rationale goes in the companions of `storefront-publication`,
    `buyer-orchestration`, `negotiation-protocol`, `settlement-configuration` and
    `resource-pool-management`;
  - the repository-wide authority row, the flow paragraph, the family rule and the
    kit placement go in `ARCHITECTURE.md`;
  - the compatibility principle goes in `RELEASING.md`;
  - configuration goes in `DEPLOYMENT_AND_CONFIG.md`;
  - the upgrade steps go in the operator handbook.

  Codec and authority ownership is not duplicated. The lifecycle codec, the
  `settles_through` mapping, the authority checks and option identity stay
  `deal-lifecycle`'s; this change's deltas and documents refer to them, and its
  `deal-lifecycle` delta amends only the deadline's source. Corrections the record
  needed:
  - D1's spec home is `storefront-publication`, where the delta carries it, not
    `negotiation-protocol`.
  - D7, D8 and D9 carry nothing into `settlement-configuration/spec.md`: the
    presenter is `buyer-orchestration`'s requirement, setup admission
    `storefront-publication`'s, and the mechanism hooks are explained in that
    capability's companion.
  - D10 adds no `resource-pool-management` requirement, since that spec leaves
    `pricing` values to the reading domain; the resolver's home is explained in its
    companion instead.

  Code-described documents I found stale and corrected:
  - the retired `pool_lease_bound_missing` hold, in the `storefront-publication`
    companion, `DEPLOYMENT_AND_CONFIG.md` (startup and the bare-metal override
    bullets) and `docs/bare-metal-seller-quickstart.md`;
  - the bare-metal override write check, which reads the live capacity-bound hint as
    well as configuration;
  - the bare-metal override's `available_until_utc` term.
- [x] 13.4 **Narrative compression:** reduce completed-task notes to behavior, material
  evidence, residual work and permanent destinations; retain reasoning in design. Fold
  `design.md`'s dated implementation sections into D1–D12 and remove their narrative;
  decide the fate of the round-1 checkpoint attachments under
  `docs/attachments/negotiate-open-ended-compute-terms/`, including
  `reader-guard-checkpoint.md`, which describes the removed guard.
  Done (2026-11-12). Sections 1–12b's notes are reduced to final behaviour, evidence,
  deferrals and destinations (2687 to about 1300 lines). Each round-1 slice that
  round 2 replaced keeps a one-line pointer to the task that replaced it. Every task
  line, owner and review citation, out-of-scope repair and the "Round-1 triage" notes
  are kept. Before deleting, the reasoning the notes alone held was moved into
  `design.md`: the production VM client's recurring limit (D6), the unreachable
  mandate guard (D2), and spot's helper obligation and the `deal-lifecycle` amendment
  (D3). `design.md`'s sixteen dated sections were folded into D2, D2b, D3, D5, D6, D7
  and D9 and then removed (1112 to 788 lines). Their superseded round-1 forms became
  rejected alternatives. "Round-1 triage" keeps the R-number map, the pre-round-1
  reconciliation, the cadence and Part B.

  The attachments stay where they are, as dated round-1 evidence: the files say when
  each was observed, and `design.md` ("Round-1 triage") and an unowned row in the
  campaign index cite them. Moving them into the change directory, to archive with
  it, was preferred, but no closeout tool can move or delete a file: `git mv` was
  denied in this run, and Edit and Write cannot remove one.
  `reader-guard-checkpoint.md` already says the guard was removed.
- [x] 13.5 **Roadmap currency:** in `docs/development/ROADMAP.md`, close Goal 8's gap
  row "No listing can say how a deal is billed or whether the seller may end it…" and
  update the goal's current state; keep the default-horizon admission row unowned;
  record the disposition in the promotion record.
  Done (2026-11-12):
  - Goal 8's row is now an archived row linking the archive, saying what landed and
    what its closeout showed.
  - Goal 8's current state gains a paragraph on the dark terms: bounds, classes, the
    per-clause step, the deadline and penalty, the horizon, the unit and pin, the
    buyers' display and waivers, and the undeclared servicing.
  - Goal 5's default-horizon row stays unowned and cites
    `negotiation-protocol`'s "Compute horizons bind both seller bounds" instead of
    this change's D5.

  Recorded in the promotion record.
- [x] 13.6 **Campaign index currency:** update this change's row and its place in the
  Goal 8 dependency graph in `openspec/changes/README.md`, keep or retire the three
  unowned gap rows under "Unowned work found by `negotiate-open-ended-compute-terms`"
  as what landed decides, and run `scripts/change-workflow run pre-commit
  negotiate-open-ended-compute-terms`, whose default checks include the change index.
  Done (2026-11-12):
  - The row is `in closeout`, its Notes rewritten for closeout and its links
    pointing at the archive (13.11).
  - The Goal 8 graph is unchanged. The change keeps its place, and its dependents'
    edges and every other row's `Depends on` and status stay as they are until
    archive cleanup.
  - The unowned table now has four rows, since the version pass added one, and all
    stay, because nothing this change landed closes them: the `listing_hash`
    mismatch, the bare-metal buyer's missing Alkahest stage, the missing per-period
    end-to-end run, and the two packages owing bumps.
  - The per-period run row now names only `spot-deals-through-arkhai-payments`'
    planning.
  - 51 R1's tooling observation stays out of the index, as the owner decided.

  `scripts/change-workflow check index` passed after the edit, and again after the
  archive (13.11).
- [x] 13.7 **Packaging:** run `make check-packaging` and
  `make check-architecture-change CHANGE=negotiate-open-ended-compute-terms`; resolve
  all failures/owned exceptions. If the change touched `.agents/`, `.claude/` or
  `.codex/`, confirm the agent-skills check of `scripts/change-workflow run pre-commit`
  passes.
  The first closeout's run, at `7be0d48b8`, passed its checks but found ten packages
  edited without the bump `docs/development/RELEASING.md`, "Versioning policy",
  requires; neither check compares versions with the last release. Section 12a was the
  version pass, and its notes list each package.

  Passed at `052150004` (2026-11-12):
  - `scripts/change-workflow run pre-archive negotiate-open-ended-compute-terms`
    exited 0. That covers `make check-packaging` (locks, wheels, layers, scope,
    dependencies, kinds) and `make check-architecture-change`, which reports that the
    change owns no architecture row. The wheels built at the bumped versions, among
    them `arkhai-core` 0.6.0 and `arkhai-core-buyer` 0.7.0.
  - The change touched `.claude/` (the triage allowlist rule noted under "Round-1
    triage"), so the skills check ran in `scripts/change-workflow run pre-commit`
    (13.10), and passed.
- [x] 13.8 **End-to-end pipeline:** record the pipeline run/result and the scenarios
  exercising this change: `vms/test_listing_shapes.py`, `vms/test_vm_payment_purchase.py`
  and `bare_metal/test_bare_metal_payment_deal.py` (protected purchases asserting the
  published deadline), and `bare_metal/test_bare_metal_publication.py`. Materialization
  and startup/continuation pipeline evidence belongs to spot and convergence,
  respectively, not this change's closeout. Readiness/dependency failures are explicit
  blockers, never passing evidence or live-deployment claims.
  Recorded (2026-11-12) from validation 57, at `052150004`, the pre-closeout `HEAD`.
  Closeout changes no code, so the evidence describes the code the closeout commit
  carries:
  - **Pipeline:** e2e.yml run 43303151315 succeeded. Its jobs e2e-vm, e2e-apicredits,
    native-ansible-gate and e2e-bare-metal all succeeded.
  - **Scenarios:** the run's `actions.log` shows the four named scenarios running
    under the jobs that succeeded: `vms/test_listing_shapes.py` and
    `vms/test_vm_payment_purchase.py` in e2e-vm, and
    `bare_metal/test_bare_metal_payment_deal.py` and
    `bare_metal/test_bare_metal_publication.py` in e2e-bare-metal. The two
    purchases buy through the default buyer with no waiver, asserting the published
    deadline (8.2).
  - **Local and Helm:** validation 57's local part passed (check-packaging and
    `make test`), and its Helm part passed in its validation namespace. Helm cannot
    serve the payment scenarios, which only the pipeline runs.
  - **CI:** none owed. No section names an `Owed by validation:` observation, and
    validation 57 records CI as not owed.

  No readiness or dependency failure occurred. This is lane evidence against the
  in-lane payments double. It claims no live deployment and no recurring servicing,
  since no end-to-end run produces a per-period Agreement (an unowned row).
- [x] 13.9 **Promotion:** promote D1–D12 to the destinations in `design.md`'s
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
  Done (2026-11-12). The promotion record in `design.md` names every destination by
  anchor. Written at closeout:
  - **`ARCHITECTURE.md`:**
    - "Discovery and negotiation": derived classes, the horizon as the Agreement's,
      the unit-bearing accessor and the pricing pin.
    - The authority row for the rates a multiplier-priced deal is held to.
    - "Family kits": the sibling-domains rule, with the per-clause step and the
      resolver as its instances.
    - "Kit areas": the contracts package's `capacity_bounds` and `listing_terms`.
  - **`RELEASING.md`, "Versioning policy":** compatibility owed to what a release
    shipped.
  - **`storefront-publication` companion:** a "Compute terms of sale" section (two
    capacity bounds, the per-clause step, the servicing declaration and why no
    storefront integration test drives a recurring option, the clause source), with
    its "Missing defaults" and bare-metal override paragraphs corrected.
  - **`buyer-orchestration` companion:** "Compute terms before approval" (the
    horizon check and `acceptance_validator`, the bounds a resumed run keeps, the
    presenter, what the display claims, one waiver table and the run log's
    waivers, duration and the billing projection, the payments-only bare-metal
    buyer).
  - **`negotiation-protocol` companion:** the agreed price and its unit, and
    acceptance resolving the domain's terms once.
  - **`settlement-configuration` companion:** the mechanism-owned projections and
    the declaration, under "Registration and ownership".
  - **`resource-pool-management` companion:** "Capacity bounds and listing terms",
    and the capacity-bound hints among the checks the typed models make.
  - **`DEPLOYMENT_AND_CONFIG.md`:**
    - the penalty multiple's startup refusal, and no hold for a missing maximum;
    - the storefront-wide terms list;
    - the five clause tiers, the capacity-bound tiers and the default penalty, under
      the pool overrides section;
    - the bare-metal override's terms and live-hint write check;
    - the seller's `[Settlement.rate_servicing]` tables.
  - **`docs/bare-metal-seller-quickstart.md`:** the retired hold.

  Confirmed, written in implementation: the operator handbook's "Bare-metal lease
  bounds" and "Bare-metal clauses from the pool's `pricing` hint" upgrade steps.
  Identity decision outcomes: no stored class, the option ID unchanged by the
  horizon, and option identity covering `lifecycle` as the foundation's codec defines
  it. The archive merges the six deltas (13.11), and `openspec/specs/README.md`
  needs no entry.
- [x] 13.10 **Documentation citations:** run
  `make check-doc-citations CHANGE=negotiate-open-ended-compute-terms`, resolve all
  matches, then `scripts/change-workflow openspec validate
  negotiate-open-ended-compute-terms --strict`.
  Passed (2026-11-12, after promotion):
  - `scripts/change-workflow run pre-commit negotiate-open-ended-compute-terms`
    exited 0: the index, tasks and skills checks, `openspec validate --strict`
    ("Change 'negotiate-open-ended-compute-terms' is valid"), and
    `make check-repository`, whose documentation citations, history wording,
    decision destinations, version bumps, local imports and capability index all
    passed.
  - The change has six deltas, so validation applies.
- [x] 13.11 **Archival:** last, run `scripts/change-workflow openspec archive
  negotiate-open-ended-compute-terms -y`, merging the deltas (no `--skip-specs`), and
  link the campaign row to the resulting archive.
  Done (2026-11-12). No permanent spec held the deltas' requirements beforehand, so
  they were merged rather than skipped. The archive moved the change to
  `openspec/changes/archive/2026-11-12-negotiate-open-ended-compute-terms/` and merged
  26 added requirements, 3 modified and 1 renamed:
  - `buyer-orchestration`: 9 added.
  - `deal-lifecycle`: the delivery-deadline requirement renamed and modified, and
    "Lifecycle terms are part of the selected option" modified.
  - `negotiation-protocol`: 7 added.
  - `resource-pool-management`: 1 added.
  - `settlement-configuration`: 2 added.
  - `storefront-publication`: 7 added, and "A storefront that cannot publish refuses
    to start" modified.

  The archive reported the 13.9 and 13.11 checkboxes still open; both are checked
  here. I read each merged spec's diff: every requirement appears once, as its delta
  states it, and the only lines removed are the replaced deadline wording and the
  retired lease-bound hold. After the archive:
  - the campaign row and its placement-probe link point at the archive, and
    `ROADMAP.md`'s Goal 8 row links it;
  - the round-1 attachments' probe paths point at the archived directory;
  - `scripts/change-workflow check index` and
    `scripts/change-workflow run pre-commit negotiate-open-ended-compute-terms`, which
    validates every specification strictly, passed.
