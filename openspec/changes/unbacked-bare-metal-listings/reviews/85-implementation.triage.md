# Triage — 85-implementation — unbacked-bare-metal-listings

Reviewed commit: `da1929a6e5acbb5b976cabedd3c8267b4da3aad3`, which was `HEAD` at triage and
is the commit `88-validation.md` validated, so the records are one round. Triaged together
with `88-validation.md`, the owner's notes `82-implementation-owner.md` (no notes) and
`91-implementation-owner.md` (O1), and the orchestrating session's observations
`73-orchestrator.md`, `77-orchestrator.md`, and `83-orchestrator.md`. The fixes are made
against `da1929a`.

Presented in the order F1, F9, 88 V1, 91 O1, F5, F6, F7, F8, F2, F3, F4, F10, F11, F12,
F13, F14, F15, F16, F17, then the orchestrator's points: F9's choice decides V1, and F1 is
the one blocking finding.

### F1 — A VM counter selecting an unpriced option is accepted at the counter's amount against the opening's priced option

- **Lens / basis / severity:** consistency / specification / blocking (as the reviewer's)
- **Position:** partly. The defect is real: `accept_unpriced_selection` judged the latest
  proposal, so a counter selecting an unpriced option was accepted at its own amount while
  the acceptance settled the opening's priced option. The reviewer's broader remedy of
  refusing a counter that changes the option is not needed; judging the pinned opening is
  the fix the `negotiation-protocol` delta already implies.
- **Proposed outcome:** fix — `accept_unpriced_selection` and `accept_exact_listing`'s
  selection branch judge, and accept, the pinned opening; a kit unit case and a VM
  typed-client case showing the defect, written before the fix; no new refusal of counters
  that change the option.
- **Owner disposition:** agreed.
- **Result:** fixed in `kit/policy`'s `scalar_policies.py`. The VM case
  (`test_negotiate_controller.py` `TestCounterNamingAnotherOption`) answered `accept`
  against the old kit and refuses now; kit unit cases in `test_selection_scalar.py`. The
  `negotiation-protocol` delta gains "A counter selects an unpriced option after a priced
  opening". Recorded in `tasks.md` Section 8's round-1 note.

### F9 — A VM create with supplied escrows and no clauses still publishes the caller's `demands` unchecked

- **Lens / basis / severity:** consistency / specification / should (as the reviewer's)
- **Position:** partly. The gap is real (Section 3 recorded it for this triage). The fix
  is a choice between real alternatives, so it was presented as a decision.
- **Proposed outcome:** decision — (a) refuse supplied `demands` and derive the conditions
  for supplied escrows under readiness, recorded in D19; or (b) derive when none is sent
  and refuse a mismatch. I recommended (a).
- **Owner disposition:** (a). Then: "Leave demands on the request model and refuse when
  supplied. If for some reason we need the listings to support paying a different seller
  address than the storefronts configuration that will be a new feature/openspec change."
  The owner has no intention of removing demands from buyer-side negotiation; changing the
  wire format to remove demand as a concept is out of scope.
- **Result:** VM's create derives every published escrow's condition from the storefront's
  `[Settlement.alkahest]` configuration (`demands_for_published_escrows`) and refuses a
  request carrying `demands` with 400. The create request keeps its `demands` field; the
  listing's `demands` and a buyer proposal's `demand` are unchanged on the wire. D19
  records it; the `storefront-publication` delta gains the supplied-escrow and
  refused-demands scenarios; Section 5's round-1 note. Ledger entry appended.

### F5 — Plan-form verification still looks up the escrow codec in the current address book

- **Lens / basis / severity:** consistency / specification / should (as the reviewer's)
- **Position:** partly. True that verification finds the codec through the current address
  book; recording the kind in the plan would only move the stall to collection, which reads
  the same address configuration.
- **Proposed outcome:** decision — for the codec, (a) record the escrow kind in the plan,
  or (b) keep the lookup, narrow the delta, and record the limit beside D19's; for unpinned
  pre-release deals, (i) a cutover recorded in D18 naming the bare-metal revalidation
  stall, or (ii) a default-kind lookup for zero-address plans. I recommended (b) and (i).
- **Owner disposition:** "b. bare-metal hasn't yet been released yet as a domain so
  migration concerns are moot."
- **Result:** D16 records the codec limit and the rejected plan field; the
  `settlement-servicing` delta's guarantee is narrowed to what verification can honour, with
  a scenario moving the arbiter after acceptance; D18 records the unpinned deals as a
  cutover affecting no deployed bare-metal deal, with no stall note. The verification
  module's docstring states the limit. Section 7's round-1 note. Ledger entry appended for
  the owner's added context.

### F6 — The materialization chokepoint doesn't hold an escrow to the listing's accepted entry

- **Lens / basis / severity:** consistency / specification / should (as the reviewer's)
- **Position:** agree. Bare metal lets a seller omit `escrow_shape_guard`, and nothing
  beneath it held the escrow's token to the listing's entry.
- **Proposed outcome:** fix — the seller-side kit entry points refuse an escrow outside the
  listing's `accepted_escrows` or with literal fields differing from its entry. After the
  owner asked whether enforcing beneath an omitted guard overrides the seller's preference,
  presented as a decision: (a) the kit holds the plan to the listing's accepted entry, with
  the principle recorded in D18; (b) bare metal always runs its default guards; (c) qualify
  the delta. I recommended (a).
- **Owner disposition:** "a+b."
- **Result:** `require_accepted_escrow` in `market_alkahest.release_authorization`, run by
  `authorize_escrow_proposal` (`escrow_not_in_accepted_set`, `escrow_field_mismatch`); bare
  metal's `REQUIRED_SELLER_GUARDS` gains `escrow_shape_guard` and its default policies are
  `("listed_price",)`. D18 records the principle (what can settle is the listing's; policies
  decide only within it); the `negotiation-protocol` delta's text and token scenario. Kit
  unit and bare-metal typed-client tests. Section 8's round-1 note. Ledger entry appended.

### F7 — Alkahest can read as ready on a chain that has no client

- **Lens / basis / severity:** consistency / specification / should (as the reviewer's)
- **Position:** partly. A chain with no client cannot settle, so it must read unreachable;
  a configurable probe endpoint for a provider serving websocket and HTTP apart is not
  needed, only documented.
- **Proposed outcome:** fix — such a chain reads `alkahest.chain_unreachable` whatever its
  HTTP calls show, with a kit unit case; the `ws`→`http` mapping documented in the probe's
  docstring and, at closeout, `DEPLOYMENT_AND_CONFIG.md`.
- **Owner disposition:** "Agree with you over the reviewer."
- **Result:** fixed in `chain_probe.py`; D19 bullet; the `settlement-configuration` delta's
  text and scenario; 23.9 names the `DEPLOYMENT_AND_CONFIG.md` sentence. Section 4's
  round-1 note.

### F8 — Client construction inside the probe has no time limit and can wedge the loop, its pause, and the seed

- **Lens / basis / severity:** consistency / specification / should (as the reviewer's)
- **Position:** agree.
- **Proposed outcome:** fix — bound construction by the RPC timeout, recording
  `alkahest.chain_unreachable` on timeout and discarding a late result, with a kit unit case
  of a hung constructor beside a healthy chain.
- **Owner disposition:** agreed.
- **Result:** `_construct_missing_client` runs the constructor in a worker thread under
  `asyncio.wait_for`; D19 note; kit unit case. Section 4's round-1 note.

### F2 — The credits lane's evidence for the seed depends on winning a timing race, and one cited scenario can't be evidence

- **Lens / basis / severity:** testing / guidance / should (as the reviewer's)
- **Position:** agree.
- **Proposed outcome:** fix — the credits scenario steps `alkahest-chain-probe` and
  `listing-seed` through a credits-storefront administrator fixture before discovery; 6.6's
  evidence line names only `e2e_credits_deal`.
- **Owner disposition:** agreed.
- **Result:** done (`test_credits_deal_buyer_cli.py`, the API-credit conftest, the lane's
  `config-docker.yml` naming the storefront's identifier and the dev-env development
  administrator credential already committed); 6.6 corrected. Unrun here: the pipeline is
  the evidence. Section 6's round-1 note.

### F3 — The chain probe's production wiring is untested in VM and API credits, and the seam the tests need is missing

- **Lens / basis / severity:** testing / guidance / should (as the reviewer's)
- **Position:** agree.
- **Proposed outcome:** fix — a composition override for the probe's JSON-RPC transport
  and client constructor in each storefront, and one application-integration test per
  storefront running the real composition and registered loop; the module patch and the
  hand-built doubles go.
- **Owner disposition:** agreed.
- **Result:** seams added: VM's `VmCompositionSeams` gains the constructor and the JSON-RPC
  call, API credits gains `ApiCreditCompositionSeams`, bare metal's runtime builder takes
  `chain_json_rpc`, and `build_alkahest_clients` takes `constructor=`. API credits'
  test runs the started application through `StorefrontClient`, and the module patches
  went. Bare metal's runs the configured runtime's registered loop and status. VM's is at
  the composition boundary rather than the started application: VM has no harness that
  starts its whole application with injected seams, so its test drives the real
  `_build_settlement_composition` and the registered loop step; a started-application test
  would need that harness first. Section 4's round-1 note records the levels.

### F4 — The buyer-orchestration delta and D17/D18 describe what was planned, not what was built

- **Lens / basis / severity:** documentation / evidence / should (as the reviewer's)
- **Position:** agree.
- **Proposed outcome:** edit — the delta's resume sentence and scenario to the recorded
  accepted proposal, recorded conditions, and exact Agreement amount; D17's plan-check
  bullet to the funding-time port; D18's rationale sentence.
- **Owner disposition:** agreed.
- **Result:** made in `design.md` D17 and D18 and the `buyer-orchestration` delta. Section
  9's round-1 note.

### F10 — Status readiness and publication disagree for multi-chain sellers, and one unreachable chain withdraws Alkahest on all of them

- **Lens / basis / severity:** direction / judgement / minor (as the reviewer's)
- **Position:** partly. Status and publication judged different chains in each storefront;
  per-chain readiness would change the readiness contract every mechanism shares.
- **Proposed outcome:** fix — VM's status over its configured clauses, plus a closeout task
  for the companion. After the owner asked for one evaluation rather than three, revised:
  one rule in the existing preflight — with no publication input readiness judges every
  configured chain, every storefront's status asks that way, and publication keeps judging a
  candidate's own chains — plus the closeout task.
- **Owner disposition:** "I'd like to find a way to unify how this is evaluated rather than
  support 3 different implementations." Then agreed to the revised fix.
- **Result:** `_selected_chain_names` judges every configured chain with no publication
  input, `default_chain` selecting nothing there; bare metal's status passes `clauses=()`.
  D19 bullet; the `settlement-configuration` delta's text and two scenarios; 23.9 names the
  companion sentence and the all-chains-together limit. Tests in kit, API credits, and bare
  metal. Section 4's round-1 note. Ledger entry appended.

### F11 — Re-bumping packages already bumped and unreleased in this change is churn with no policy

- **Lens / basis / severity:** direction / judgement / minor (as the reviewer's)
- **Position:** agree.
- **Proposed outcome:** fix — the once-per-change rule in `RELEASING.md`, applied from here
  on, leaving the bumps already made.
- **Owner disposition:** "Agreed. Honestly version bumps are harmless but it is unnecessary
  churn we can avoid with this policy."
- **Result:** `docs/development/RELEASING.md` states the rule. Applied to this round: every
  package the fixes touch already carries a minor bump over `dev`, so none is bumped again.

### F12 — A buyer funds its derivation without the skew check when the seller sends no plan

- **Lens / basis / severity:** direction / judgement / minor (as the reviewer's)
- **Position:** partly. A seller accepts an escrow only with its plan, so a reply without
  one is a protocol breach, and funding then skips the one skew check.
- **Proposed outcome:** fix — both funding paths refuse such an acceptance as
  `seller_plan_missing`, with core and kit unit cases; edit the delta with F4's amendment.
- **Owner disposition:** agreed.
- **Result:** `core/buyer`'s `_settle_one` and `kit/alkahest`'s
  `derive_accepted_escrow_terms`; the delta's requirement and scenario. The VM buyer's unit
  fixtures now carry the seller's plan their stubbed derivation funds. Section 9's round-1
  note.

### F13 — The seed's "found" path and site resolution are untested

- **Lens / basis / severity:** testing / judgement / minor (as the reviewer's)
- **Position:** agree; checking it found the lookup read one page only.
- **Proposed outcome:** fix — `_listing_for` pages; an application-integration case of a
  second seed step finding the listing and registering nothing; unit cases for site
  resolution.
- **Owner disposition:** agreed.
- **Result:** done. Section 6's round-1 note.

### F14 — `require_deliverable_release_model` is still exported and documented as a startup check the delta now forbids

- **Lens / basis / severity:** documentation / specification / minor (as the reviewer's)
- **Position:** agree.
- **Proposed outcome:** fix — delete it, its export, tests, and docstring alternative; and,
  for Section 7's question, delete the listing form `verify_escrow_for_settlement`, its
  exports, and its VM re-export, carrying its release-authorization cases onto
  `authorize_escrow_proposal`.
- **Owner disposition:** agreed.
- **Result:** both removed with their tests and helpers; the VM shim re-exports only the plan
  form. Sections 3 and 7's round-1 notes. `domains/vms/storefront/tests/unit/test_listing_token_extraction.py`,
  which tested only the removed form's token extraction, is deleted, by the orchestrating
  session on the owner's word, since this step could not delete files.

### F15 — Section 10's handoff note misstates how a failure mid-stream is handled

- **Lens / basis / severity:** documentation / evidence / minor (as the reviewer's)
- **Position:** agree.
- **Proposed outcome:** edit — correct the note; no code change.
- **Owner disposition:** agreed.
- **Result:** Section 10's handoff note rewritten.

### F16 — The 503 leaves out the chain when a clause relies on the default chain

- **Lens / basis / severity:** consistency / specification / minor (as the reviewer's)
- **Position:** agree, as presented; making the fix showed the premise false.
- **Proposed outcome:** fix — name a clause with no chain under the default chain, with an
  application-integration case.
- **Owner disposition:** agreed.
- **Result:** no change made. An Alkahest publication clause must name its chain:
  `AlkahestPublicationInput.chain` is required (`kit/alkahest/src/market_alkahest/settlement_config.py:57`,
  strict, `extra="forbid"`), so a clause naming none is refused when it compiles, before
  readiness and the 503 are reached. No clause can rely on the default chain, so no 503 can
  omit one. Reported to the owner with this outcome; the disposition stands as recorded.

### F17 — A VM continuation after an option is repriced is decided against a zero reference

- **Lens / basis / severity:** consistency / specification / minor (as the reviewer's)
- **Position:** agree.
- **Proposed outcome:** decision — (a) VM's round hook refuses a continuation whose pinned
  option is gone, naming it, with the domain difference recorded at closeout; or (b) VM
  continues against the opening's listing record as bare metal does. I recommended (a).
- **Owner disposition:** "a. But b should be recorded as another unowned item if no other
  openspec change owns this already. This is another unification issue."
- **Result:** VM's round hook refuses with `pinned_option_withdrawn`; D16 records it; the
  `negotiation-protocol` delta's scenario; a VM typed-client test. No change owns (b), so
  23.5 adds it to `ROADMAP.md`'s Goal 4 as an unowned row at closeout. Section 8's round-1
  note. Ledger entry appended.

The accepted fixes are committed as `e15a5b2` ("unbacked-bare-metal-listings: round 1
triage fixes"), not pushed.

## Next

Another round — "Yes, it merits another review round."
