## 0. Round-0 resource-shape mismatch guard (implemented, 2026-07-29)

Direct consequence of the Section 2 resolution on item 1 (round-0 shape
negotiation deferred, but silent mismatch is worse than loud rejection).

- [x] 0.1 Add `_reject_unsupported_resource_shape_request` to `sync_negotiation.py`: compares `provision_terms.compute_resource` against the listing's own shape across `arkhai_vms.DIMENSION_KEYS`; raises `OfferUnfulfillableError` on any disagreement.
- [x] 0.2 Wire the guard into `start_sync_negotiation`, after listing load/status check, before any seller policy runs.
- [x] 0.3 Update `start_sync_negotiation`'s docstring (was stale: "eventually compute spec") and `_place_capacity_hold`'s docstring (documents the intentional block per repository-owner direction on item 5/7) to describe current, real behavior.
- [x] 0.4 Add regression tests: mismatched shape rejected before seller policy runs; matching shape proceeds normally.
- [x] 0.5 Run the full test file plus three adjacent negotiation unit-test files; confirm no regressions (74 tests total).

## 1. Guard against silent shape-change loss on negotiation continuation -- REVERTED

**Reverted in full, repository-owner direction, 2026-07-29.** Preserved
here per `AGENTS.md`'s "preserve completed tasks; amend rather than
replace implementation history," not because any of it remains active.

- [x] 1.1 Confirm, by inspection, that `NegotiateContinueRequest`/`AdvanceRequest` use Pydantic's default (silent-drop) `extra` handling.
- [x] 1.2 ~~Set `model_config = {"extra": "forbid"}` on both models~~ -- reverted.
- [x] 1.3 ~~Add regression tests~~ -- reverted; test file deleted (tombstone: `core/storefront/tests/unit/test_negotiation_models_extra_fields.py`).
- [x] 1.4 Confirm no production or test call site constructs either model with fields beyond its declared set (still true; not itself reverted, just no longer load-bearing for anything).
- [x] 1.5 ~~Run `core/storefront/tests/unit/test_negotiation_sync.py` alongside the new tests~~ -- moot, reverted.
- [x] 1.6 Correction (repository-owner review, 2026-07-29): fixed the overclaiming docstrings/design record -- the guard protects top-level fields only, not content nested inside `proposal`; a future revised-terms field is a child of `proposal`, typed as the existing `ProvisionTerms` opaque envelope, never new core-level vocabulary. **This correction's substance (placement + core-vocabulary reasoning) remains valid and is retained in `design.md` for Section 2 planning even though the code it corrected is gone.**
- [x] 1.7 Full revert (repository-owner direction, 2026-07-29): `model_config = {"extra": "forbid"}` removed from both models; both restored to their pre-Section-1 form; regression test file deleted. `core_storefront` is unchanged from before this change opened.

## 2. Negotiate the capacity shape

Depends on `capacity-shape-pricing` and, for task 2.4's quantitative check,
`capacity-shape-envelope`. Section 2b is the
deployment boundary.

### 2a. The revised-terms field

- [x] 2.1 Re-verify `design.md`'s Context against the tree: the hook
      names in `NegotiationDomainHooks`, that continue/advance carry a typed
      `proposal`, that `hold_ttl_seconds` still defaults to 0, and that
      `build_vm_accepted_artifacts` still derives the order from the listing record.
- [x] 2.1a **Decision gate resolved: D-a through D-d, webapp owner 2026-11-06, pending maintainer review.** Registry listing-level `rate_structure`, verified by the retained seller proof; depends on `store-registry-listings-as-published`.
      Original gate: Decide where a buyer reads a listing's rate structure,
      and with what authority, per `design.md`'s "Where a buyer reads the rate
      structure is a decision gate", taking `store-registry-listings-as-published`'s
      accepted carrier policy as an input, and record the decision and reasoning in
      `design.md`. If the decision needs the registry to keep a listing-level field,
      record the dependency on that change here and in the campaign index before
      any task relying on it starts.
- [x] 2.2 Add the revised-shape field as a child of `proposal`, typed as the existing
      `ProvisionTerms` envelope, to the continue/advance request models. The
      envelope stays opaque to core; the VM codec decodes its payload as a
      family-grouped capability shape validated by `VM_CAPABILITY_SCHEMA`.
- [x] 2.3 Widen `kit/negotiation-runtime`'s `validate_continuation` contract so a
      domain sees the decoded revised shape, and carry the shape on `RoundRequest`
      and `RoundEvaluation` so `evaluate_round` and `agreement_terms` receive what
      the round proposed and what was agreed.
- [x] 2.4 Compose the VM `evaluate_round` in `design.md`'s order — admissibility,
      authoritative feasibility, commercial feasibility, pricing — with a distinct
      refusal reason for each, and a stated "not checked" for a check the domain
      does not compose. Implement the commercial feasibility guard here: a
      requested shape's categorical commitments (GPU model, region) checked by
      equality against the listing's, declining without a quote; the quantitative
      check is the envelope's predicate. Tests: a categorical mismatch declines
      without pricing; a shape outside the envelope declines before the guard runs.
      Promote "Seller feasibility precedes pricing" with this change's spec delta.
- [x] 2.5 Retire `_validate_vm_opening`'s shape-mismatch refusal: a round-0 shape
      differing from the listing is evaluated by the same composition rather than
      rejected. Delete the Section 0 regression tests that assert the refusal.
- [x] 2.6 Focused tests (existing suites plus the replayable fixture encounter;
      no new permanent acceptance tests): a revised shape is decoded and validated; an unreadable
      shape is refused at the boundary; each refusal reason surfaces distinctly; a
      round without a revised shape is evaluated against the previously agreed
      shape.

- [x] 2.6a Pin the seller-authenticated rate-structure digest at opening; refuse a
      later round or acceptance as `rate_structure_changed_reopen` on change
      (D-e). Focused test: shifted family rates preserve the listing total but
      change a revised shape's price; continuation and acceptance are refused.

### Section 2 implementation handoff

Checkpoint 2026-11-06 (partial implementation; not deployment-ready):

- Done: 2.1/2.1a reverified and D-a–D-e recorded. Default hold TTL remains
  zero; lane/example configuration opts into 900 seconds. D-e stores a canonical
  rate-structure digest in the immutable `message:rate-structure-pin` domain
  artifact, decoded by `VmMessage`. Continuation, buyer acceptance, and
  administrative acceptance check it before deciding or materializing artifacts.
  Exit skips commercial continuation validation and remains available.
- Focused evidence: 66 passed across the VM seller-hook, escrow-normalization,
  hold-cap, negotiate-controller and buyer-selection suites; 61 negotiation-runtime
  unit tests passed; all 60 VM-domain unit tests passed. The authorized
  shifted-family-rate test covers an unchanged advertised total with a different
  revised-shape price and refuses both counter and acceptance. Its exit case
  confirms the buyer can leave after repricing. The pin test uses real SQLite
  domain-artifact persistence (library integration); the buyer-selection suite
  exercises the buyer and served storefront over loopback (application integration).
  No deployed system/e2e run or independent story verification is claimed.
- Checks: `make check-packaging` passed; `make check-change
  CHANGE=negotiation-driven-capacity-resize` passed all 12 checks, including
  comment hygiene and pinned strict OpenSpec validation. No permanent-document
  promotion has been performed. The full suite is reserved for integration.
- Corrected attempts: the first change check caught history wording in the new
  exit-path comment; it was rewritten as a current invariant and the check passed.
  The first combined test command pointed at a nonexistent VM-domain `tests/unit`
  directory after its storefront and kit suites passed; rerunning the domain's
  declared `pytest -q` entry point passed all 60 tests.
- Remaining: 2.2–2.6, then 2.7–2.11 and their focused/integration evidence. No
  multiplier, rate rounding, floor, buyer wire conversion, or payment amount
  semantics have changed yet. 2.12–2.15 remain outside this requested slice unless
  a concrete dependency requires them. Promotion and archival remain post-review.
- Consumer work located: `arkhai_vms_negotiation.storefront_round` supplies the
  absolute reference; `market_policy.scalar_policies` bisects integers but its
  convergence tolerance can accept below a strict floor. The VM runtime's
  `_with_agreement`, `_accepted_selection_artifacts`, and settlement-stage context
  currently treat the scalar as base units. Core buyer acceptance compares the
  scalar directly to Agreement/obligation amounts, and both the VM client and
  core orchestration scale per-hour bounds by duration. These are actual
  consumers to repair, not rename. Shape revisions also need durable per-round
  terms: current negotiation messages persist scalar amounts, not revised shapes.
- Not attempted: partial multiplier conversion. Changing only seller reference
  hooks would send basis points into payments and fail buyer Agreement checks.
  The registry carrier/proof implementation is a parallel dependency and is not
  present on this base; this branch does not implement it.

Continuation checkpoint 2026-11-06 (2.2–2.3; still not deployment-ready):

- The revised child is `proposal.provision_terms`, typed as the existing core
  `ProvisionTerms` envelope on continue and administrator advance. Its VM payload
  is a whole family-grouped shape, not a patch or a replacement for duration,
  start, or SSH credentials. Core preserves all other opaque proposal fields.
- `NegotiationDomainHooks.decode_revised_terms` decodes a revision against the
  previous terms; unsupported domains refuse it. The widened continuation hook
  receives the previous and decoded proposed terms. `RoundRequest.revised_terms`
  exposes the proposal; `RoundEvaluation.agreed_terms` supplies the seller's
  effective terms to `agreement_terms` and acceptance.
- `core/storefront/src/core_storefront/sqlite_client.py` records full effective
  terms with each transcript message; its additive migration is in
  `core/storefront/src/core_storefront/sqlite_migrations.py`. Resume reads the last
  seller-quoted terms, while the opening remains immutable. The VM decoder is in
  `domains/vms/storefront/src/market_storefront/negotiation_runtime.py`; it validates
  with the domain's capability schema before flattening for existing VM codecs.
  API-credit and bare-metal adapters accept the wider hook without enabling
  shape revisions. `typing-extensions` is explicitly declared for the typed wire
  dictionary and the affected consumer locks are refreshed.
- Focused evidence: 62 negotiation-runtime unit tests; 5 VM revision-decoder
  cases; 70 combined VM decoder, seller-hook, escrow-normalization, hold-cap and
  negotiate-controller cases; 52 bare-metal runtime/HTTP negotiation cases; 23
  API-credit unit/integration negotiation cases; all 233 core-storefront tests,
  with the changed SQLite binding suite rerun separately (14 passed). The
  SQLite case reloads per-round terms and an exact amount above 2^63 through a
  new client; the opaque runtime case reconstructs the runtime between revision,
  no-revision counter and acceptance. No deployed/e2e or independent verification
  is claimed. These are partial evidence for 2.6, which remains unticked.
- Checks: `make check-packaging` passes, and `make check-change
  CHANGE=negotiation-driven-capacity-resize` passes all 12 checks, including comment
  hygiene, documentation citations and pinned strict OpenSpec validation. No typing
  suite, deployed/e2e run, promotion or archival has been performed.
- Corrected attempts: packaging initially refused nine consumer locks after adding
  the direct `typing-extensions` dependency; `make lock` refreshed those locks and
  packaging passed. One VM test invocation used nonexistent shortened filenames
  and collected no tests; rerunning with the existing `test_sync_negotiation_*`
  filenames passed all 70 cases. No test failure is being carried forward.
- Reproduce the prepared first use with `make check-packaging`, then
  `make -C domains/vms/storefront reinit`, then from `domains/vms/storefront` run
  `uv run --frozen --no-sync pytest tests/unit/test_vm_revised_terms.py
  tests/unit/test_sync_negotiation_seller_round_hook.py -q`. This uses temporary
  SQLite state, deterministic development principals, and injected seller policy;
  no deployed storefront, chain or registry is prepared and no secret is needed.
- Next: 2.4–2.6, then 2.7–2.11. The old shape-change refusal deliberately remains
  until feasibility and pricing are composed; changing the shape is not yet a
  sellable product path. The scalar is still a base-unit amount, not a multiplier.
  No buyer, rounding, floor or payment-consumer conversion has been attempted.
  No PR, permanent promotion, archive, deployment boundary or package release is
  claimed at this checkpoint. The parallel registry carrier/proof dependency is
  still absent. Preserve the existing 2c boundary and resume from 2.4.

Slice A plan (2026-11-06):

- Resolve the requested shape's quantitative predicate in
  `services/negotiation_shapes.py` from the listing's durable site/pool, held pool
  hints, stored VM override, and parsed configured default, using the existing
  listing-shape/admissibility readers. Fail closed when policy cannot be resolved.
- Compose admissibility, explicitly uncomposed authoritative requested-shape probe
  ("not checked"), categorical commercial checks, and pricing in the VM runtime.
  The existing listing-source confirmation is not a requested-shape probe.
- Widen the VM seller hook only; evaluate the requested shape through the domain
  aggregator in the selected asset. Keep absolute base-unit scalar semantics and
  existing truncation until the 2b deployment boundary. Flat-priced listings stay
  shape-fixed. Retire the unconditional mismatch guard and its two regressions.
- Validate existing VM revised-term, seller-hook, reference-price, controller,
  escrow-normalization and hold suites, plus runtime regression and buyer-selection
  integration. Record a reproducible first-use packet with policy precedence and
  refusal-order observations. No new permanent acceptance tests are authorized.
- Permanent destinations remain the promotion record's negotiation-protocol
  feasibility/revision requirements; post-review promotion and the existing
  eleven-part closeout remain at the end of this plan.

Slice A handoff (2026-11-06; 2.4–2.6, still not deployment-ready):

- Done: the VM runtime resolves the advertised shape's quantitative policy from
  its durable site/pool, held hint, stored override and configured default.
  Admissibility and categorical commercial checks precede pricing; policy
  unavailable, inadmissible, commercial and pricing refusals are distinct.
  The authoritative requested-shape probe is **not checked**; listing-source
  confirmation is not substituted for it.
- The VM-specific seller hook receives the effective grouped shape. Its reference
  prices that shape in the selected asset via the domain aggregator, using the
  exact advertised/requested price ratio to retain the materialized base-unit
  scale. Round-zero partial flat requests normalize once; whole grouped revisions
  remain whole, and a no-revision round resumes the persisted seller-quoted shape.
  The unconditional shape-change guard and its two old regressions are removed;
  flat-priced listings remain shape-fixed. New permanent tests were not added.
- Evidence and runnable first-use setup:
  `docs/attachments/resize-shape-pricing/index.md` and its `first_use.py`.
  The prepared target is checkout-owned temporary SQLite, deterministic public
  development principals, a loaded fake pool projection and injected matching
  advertised-listing verdict. No secrets, deployed registry/site/chain, or
  persistent server are prepared. From the root run `make check-packaging`,
  `make -C domains/vms/storefront reinit`, then
  `(cd domains/vms/storefront && PYTHONPATH=src:. uv run --frozen --no-sync python ../../../docs/attachments/resize-shape-pricing/first_use.py)`.
- Validation: 94 existing focused VM and application-integration cases pass,
  including controller and loopback buyer-selection; 62 runtime cases pass.
  The encounter observes references 80 → 120 → 120 across opening, revision and
  no-revision resume, quantitative-before-categorical refusal, zero seller-hook
  calls for categorical mismatches, and override/hint/default precedence.
  `make check-packaging` and all 12 `make check-change` checks pass, including
  comment hygiene, citations and pinned strict OpenSpec validation. No typing,
  deployed/e2e, or independent story-verification result is claimed.
- Small repair: `cbe5510dc` skips reference pricing on exit; withdrawing prices
  cannot trap a buyer in an existing thread. The fixture encounter re-drives it.
- Restart at **2.7–2.11 as one deployment-boundary slice**. The scalar is still an
  absolute base-unit amount and retains existing truncation. Do not carry it into
  payment as basis points piecemeal: audit `_with_agreement`,
  `_accepted_selection_artifacts`, stage context, core buyer Agreement checks and
  VM/core duration-bound scaling noted in the earlier handoffs. Use the documented
  top-level PR #349 rate carrier on `registry-as-published`; do not duplicate its
  registry storage/proof work. Preserve the rate pin and the 2c artifact/claim
  boundary. No PR, release, promotion, archive or deployment is claimed here;
  the existing post-review closeout remains required for the final slice.

### Slice B handoff (2026-11-06; 2.7–2.11)

- Shape-priced scalar threads now carry integer basis points in `fields.amount`;
  `negotiation.multiplier_floor_bps` defaults to 10,000 and may be lowered
  explicitly. Bisection remains scalar and unchanged; sub-floor counter/accept
  decisions counter at the floor, and acceptance below the floor is refused.
- `arkhai_vms_negotiation.amounts` shares selected-asset quote derivation between
  seller and buyer. Exact rational arithmetic retains fractional base units until
  one final upward rounding; uint256 overflow refuses as `shape_price_overflow`.
  Flat-priced and hidden-reserve paths retain their existing exact/truncating
  semantics. **No existing truncation assertion was changed**, including
  `core/tests/unit/test_rate_helpers.py`: that generic legacy helper is not the
  multiplier quote contract.
- Consumer audit/conversion: VM seller references and proposal hooks carry bps;
  `_build_response_artifacts` converts before `_accepted_settlement_artifacts`,
  the settlement-stage context, escrow/hosted obligation construction and
  `_with_agreement`. Monetary escrow artifacts no longer overwrite the scalar
  terminal proposal. The core buyer codec validates Agreement/obligation amounts
  against the derived payment, not bps. VM direct-client and orchestration entry
  points supply that codec, bypassing duration scaling only for multiplier mode.
  Buyer outcomes keep monetary `agreed_amount` for aggregation, confirmation and
  settlement and record `negotiated_scalar` separately. Resume retains the rate
  carrier, exact integer prices, and effective shape revisions. Buyer escrow
  materialization and accepted-deal recovery already read the monetary outcome
  or Agreement and therefore require no scalar reinterpretation. Storefront
  transcript/detail scalars remain exact text-backed integers, not payments.
- Focused evidence: 121 VM cases pass (including 20 existing thread cases), including the new pure arithmetic and
  SQLite integration regressions and the served buyer in flat and shape-priced
  modes; 71 core buyer cases and 69 VM buyer cases pass; 49 unchanged policy and
  generic rate-helper cases pass. The large-payment integration reconstructs the
  runtime and SQLite client, then derives the identical payment above 2^63 from
  accepted shape, pinned rates, duration and bps. The buyer's unchanged bisection
  accepts the floor after the revision without re-anchoring. The replay observes
  reference 10,000 → 10,000 → 10,000 while derived quotes are 80 → 120 → 120.
- Corrected encounters: initial setup omitted `make dist`; verified wheelhouse
  preparation fixed it. Early test attempts used wrong filenames/response field
  names, and a shape-priced publication fixture retained a forbidden clause rate;
  corrected invocations and policy setup pass. Driving the real buyer exposed the
  escrow proposal overwrite; accepting a revised counter exposed an echoed revision
  instruction. Both are repaired and the focused encounters re-driven. Repeating
  sub-floor counters hits the existing bisection stale exit, so the observational
  script opens a fresh thread for subsequent refusal checks.
- Setup/evidence: `docs/attachments/resize-shape-pricing/index.md` and
  `first_use.py`. Required and prepared target: checkout-owned temporary SQLite,
  public deterministic development principals, loaded fake pool projection and
  injected advertised-listing source match. No secrets, deployed chain/registry/
  site, or resident server. From root run `make check-packaging`, then
  `make -C domains/vms/storefront reinit`, then
  `(cd domains/vms/storefront && PYTHONPATH=src:. uv run --frozen --no-sync python ../../../docs/attachments/resize-shape-pricing/first_use.py)`.
- Gates: `make check-packaging` and all twelve `make check-change
  CHANGE=negotiation-driven-capacity-resize CHANGE_BASE=6f387f0b3` checks pass,
  including comment hygiene and pinned strict OpenSpec validation. No typing,
  deployed/e2e, independent acceptance, promotion, archive or PR is claimed.
- **Restart at 2.12–2.16.** Prices are now monetary at settlement construction, but
  the settlement order and hold still use the listing's quantities: carry the
  agreed shape into both before deployment. Drain in-flight absolute-amount
  threads across the eventual deployment boundary. The parallel registry
  carrier/seller-proof contract remains a deployment dependency; no registry-side
  implementation or deployed proof-verification result is claimed here. Parent
  integration owns landing on `resize-multiplier`; this worker does not merge or
  push its parent's target branch. Preserve the existing post-review closeout.

### 2b. The multiplier

Slice B plan (2026-11-06):

- Centralize exact shape/duration/multiplier quote arithmetic in
  `domains/vms/negotiation/src/arkhai_vms_negotiation/amounts.py`, reused by
  seller hooks and buyer conversion. Round only the final quote upward and
  reject uint256 overflow. Keep legacy flat/hidden-reserve paths unchanged;
  the delta applies where a listing has a resolvable rate structure.
- Convert the VM seller reference and enforce one configurable multiplier floor;
  keep kit bisection scalar and shape-independent. Convert accepted amounts
  before VM settlement context, escrow, hosted obligation and Agreement creation.
- Add a schema-opaque scalar/payment codec seam to core buyer negotiation and
  orchestration; VM adapters supply the listing-aware codec. Preserve monetary
  outcome/settlement amounts while transcripts retain the negotiated scalar.
  Carry the registry listing through CLI, orchestration and resume records.
- Exercise focused exact arithmetic, convergence, persistence and existing buyer
  and seller regression suites. Permanent destinations remain the design-promotion
  record; the existing post-review closeout applies after 2c, not this checkpoint.

- [x] 2.7 Reinterpret the negotiated reference quantity as a multiplier in basis
      points over the advertised minimum rate structure, through the
      `reference_amount`, `amount_from_proposal`, and `proposal_from_amount` hooks.
      Every intermediate value is an exact integer or `Decimal`; the quote rounds up;
      a quote exceeding the asset's amount type is refused.
- [x] 2.8 Audit every consumer that assumed the negotiated scalar was an amount in
      an asset's base units — the escrow and hosted obligation construction paths
      first, since a missed consumer surfaces as a wrong on-chain amount. This is an
      audit, not a rename.
- [x] 2.9 Express the seller's floor once as a multiplier bound (default 10,000)
      and confirm it applies to a shape never explicitly priced; a policy may lower
      it explicitly.
- [x] 2.10 Confirm `bisection_middleware` converges unchanged on the reinterpreted
      quantity, and that a shape change between rounds does not re-anchor bounds.
- [x] 2.11 Focused tests: concession comparability across a shape change; floor
      applied to an unanticipated shape; agreed terms yield one derivable price;
      a base-unit amount above 2^63 survives a full round trip through persistence
      and the hooks unchanged.

### 2c. The agreed shape reaches the claim

Slice C plan (2026-11-06):

- Centralize a non-mutating agreed-order snapshot in
  `services/vm_job_spec_service.py`; replace the whole quantitative/GPU shape,
  preserving the listing's capacity identity and sale terms. Omitted families
  must not inherit advertised quantities.
- Persist that snapshot in every accepted settlement plan's `vm.v1` service
  terms via `negotiation_runtime.py`. The current mechanism-stage composition
  separates `build_vm_accepted_artifacts` from provision-term decoding, so the
  shared VM acceptance composition attaches the order after mechanism artifacts
  are built. Holds derive their claim through the same snapshot builder.
- Make `settlement_composition.py` and `payment_settlement.py` use the accepted
  order for delivery facts; legacy plans lacking it derive the order from the
  accepted provision terms, never from advertised quantities alone.
- Add the specified smaller-shape regression to `tests/integration/test_vm_multiplier.py`:
  real SQLite negotiation, signed site API and real ledger, hold and fresh-reserve
  paths, whole revisions dropping GPUs, durable plan and committed dimensions.
  Run existing planner, hold, settlement/payment, and provider sizing suites.
- Record a deployed smaller-shape run separately from in-process evidence;
  confirm hygiene/import placement and packaging. Permanent destinations remain
  the design-promotion record. The eleven-part closeout below applies after review;
  promotion and archive do not precede that review.

- [x] 2.12 Write the agreed shape into the settlement order's `listing_resource`
      quantities in `build_vm_accepted_artifacts`, so
      `compute_capacity_claim_from_order` reserves what was agreed. Confirm
      `vm_fulfillment_planner` and `encode_compute_lease` need no change.
- [x] 2.13 Rewrite `_place_capacity_hold`'s claim to come from the acceptance's
      agreed order rather than `listing_record`, so a non-zero `hold_ttl_seconds`
      deployment holds the agreed shape. No resize is placed here; record that
      `negotiation-time-capacity-hold` owns `resize_reservation`'s first call.
- [x] 2.14 Focused tests: a negotiation agreeing a shape smaller than the listing's
      reserves the smaller shape; the committed reservation's dimensions match the
      agreed shape; the fulfillment request derives from the reservation.
- [ ] 2.15 **Unobservable after a genuine VM-lane attempt; owner-authorized disposition.**
      One e2e run with a shape agreed below the listing's, asserting the VM
      built has the agreed shape. Fresh rebased images built with Podman 5.7.0 and
      the explicit native Compose 1.6.0 provider, but startup failed before readiness
      because included registry environment-file paths resolved against the wrong
      directory. No deployed assertion ran. Exact command, failure and cleanup:
      `docs/attachments/resize-shape-pricing/final-validation.md`.
      Treat this as the deployment boundary: incompatible in-flight negotiations
      must drain before upgrading or rolling back.
- [x] 2.16 **Comment hygiene and import placement, before the pre-closeout review.** Run
      `make check-comment-hygiene` and read the comments this change added for any that
      narrate the review or migration that introduced them; move each import the change
      added to module level unless a verified circular import or a recorded lazy-load
      reason keeps it local. Closeout only confirms both.

### Slice C checkpoint (2026-11-06; 2.12–2.14 and 2.16)

- `8bc8b1f75` records the whole agreed shape in every plan's VM order and
  derives acceptance holds from the same builder. Escrow and hosted-payment
  settlement consume that order for delivery facts; legacy plans derive it from
  accepted provision terms. Published listings stay unchanged. The planner and
  lease encoder need no change; provisioning already sizes from the committed
  reservation. No reservation resize was introduced.
- `cb5c8c83e` fixes a payment consumer found at that boundary: hosted settlement
  must not compare the monetary Agreement with the basis-point `agreed_price`.
  The payments kit already verifies that the exact Agreement derives its stored
  mandate. The existing receipt/delivery regression now exercises different
  scalar and payment values; mismatched mandates still refuse.
- Evidence and reproducible first use:
  `docs/attachments/resize-shape-pricing/index.md`. 122 focused storefront cases
  and the fixture encounter pass; 52 existing provider-plan cases pass. After the
  payment repair, all 31 payment/lifecycle/multiplier cases pass. Packaging,
  all twelve change checks (including strict OpenSpec), comment/import checks,
  and architecture-exception ownership pass. No typing or deployed e2e result
  is claimed.
- Corrected setup: durable `VmMessage` metadata is not a provision payload, so
  order construction extracts only its decoded shape; capacity composition
  requires a real `CapacityRuntime`, now composed over the signed site API and
  real ledger in the regression. These attempts are fixed, not carried failures.
- **Remaining: 2.15 and post-review closeout.** No stack was started: `docker`
  is absent here; Podman compose selected an unconfigured mise provider shim.
  Use the existing VM lane or workflow on a prepared Docker host; extend the
  shape-priced stage in `e2e-tests/tests/e2e/roles/scenarios/vms/test_listing_shapes.py`
  to negotiate below the listing, then check reservation and create-job sizing.
  Its existing stage only checks publication of family rates, not a resized deal.
  PR #349 remains the registry carrier/seller-proof dependency. The in-process
  regression is not a substitute for this deployment evidence.
- Rebase/integration onto current `origin/dev`, final change validation, and the
  PR remain outstanding at this checkpoint. Preserve promotion/archive until
  review; do not tick closeout from implementation checks alone. The PR must
  open with Decisions to review: D-d, D-e, and draining incompatible in-flight
  negotiations at deploy; cite dependency PR #349. No PR has been opened and no
  release/deployment or independent acceptance is claimed.

### Final section 2 handoff (2026-11-06)

- Rebased all eight implementation/checkpoint commits cleanly onto `origin/dev`
  at `20aa47dfe`. Section 2 implementation is ready for review; 2.15 remains
  explicitly unobservable, not passed, under the owner's fallback instruction.
- Fresh suffixed VM-lane images built successfully. With the explicit native
  Podman Compose provider, startup failed on included registry environment-file
  path resolution before readiness. No scenario ran against the unready stack;
  the isolated project and the build's leftover Anvil process were cleaned up.
- Final validation and prepared first-use setup are recorded in
  `docs/attachments/resize-shape-pricing/final-validation.md`; packaging,
  all twelve change checks, architecture-exception ownership, 144 focused VM,
  62 runtime, 25 core-buyer, 69 VM-buyer, 52 provider-sizing, 14 core-storefront,
  97 policy and 18 legacy rate-helper cases pass (481 total). Explicit pinned
  `openspec validate negotiation-driven-capacity-resize --strict` also passes.
- PR #349 remains the registry carrier/seller-proof dependency. D-d, D-e,
  the hosted-payment fix (`cb5c8c83e`, rebased as `30d370e4e`), and the requirement
  to drain incompatible negotiations are explicit PR review items. Promotion
  and archival remain post-review; none of the closeout items below is ticked
  by these implementation checks alone.

## 3. Closeout

Per `openspec/README.md#plan-closeout-requirements`. This change's implementation predates the closeout task becoming a planning requirement. The parts are recorded here so each carries an explicit disposition rather than an assumed one; confirm and tick each rather than treating the change as closed.

- [ ] 3.1 **Comment hygiene — confirm.** Run `make check-comment-hygiene`, and read
      the comments this change added for any that narrate the review or migration that
      introduced them. Do not edit code here: anything to rewrite returns the change to
      implementation.
- [ ] 3.2 **Import placement — confirm.** Check the imports this change added for any
      still local without a recorded reason. One that should move returns the change to
      implementation.
- [ ] 3.3 **Documentation compliance.** Re-check this change's accepted decisions
      against `openspec/README.md`'s placement rules, and the permanent documents
      against the code they describe. Every material decision in `design.md` has a
      permanent destination or an explicit temporary, superseded, or rejected
      classification, and no production source references
      `openspec/changes/negotiation-driven-capacity-resize`.
- [ ] 3.4 **Narrative compression.** Compress completed-task notes to final behavior,
      material validation evidence, unresolved or deferred work, and
      permanent-documentation destinations, moving durable rationale into `design.md`
      first.
- [ ] 3.5 **Roadmap currency.** Update the affected goal's current state and gap
      mapping in `docs/development/ROADMAP.md`, or record that no goal is affected.
      Expected: the “Negotiate full compute capability, not GPU count alone” goal's
      current-state description and gap-to-change mapping change, and the
      design-promotion record names that update.
- [ ] 3.6 **Campaign index currency.** Update this change's row, and its campaign's
      dependency graph, in `openspec/changes/README.md`, or record that both are
      unchanged. Other rows' `Depends on` are left alone: archive cleanup releases
      dependents after the closeout gate.
- [ ] 3.7 **Packaging.** Run `make check-packaging` and resolve every failure it
      reports (a failure needing a code or lock change returns the change to
      implementation).
- [ ] 3.8 **End-to-end pipeline.** Record the passing run the latest validation names,
      its result, and the scenarios that exercise this change (the run with a shape
      agreed below the listing's, 2.15), or an explicit blocker naming its cause and
      the change that owns it, with the validations it gates treated as unrun.
- [ ] 3.9 **Promotion.** Write the permanent documents this change owes —
      `docs/development/ARCHITECTURE.md`, "Discovery and negotiation" (what a round
      negotiates) — and complete the design-promotion record, mapping every accepted
      decision to its exact permanent heading. A `spec.md` the deltas cover
      (`negotiation-protocol`, `vm-storefront-fulfillment`) is written by the archive
      in 3.11, not by hand; the record names it all the same.
- [ ] 3.10 **Documentation citations.** After promotion, run
      `make check-doc-citations CHANGE=negotiation-driven-capacity-resize` and resolve
      every match, then `openspec validate negotiation-driven-capacity-resize --strict`.
- [ ] 3.11 **Archival.** Last, once every other part is checked: `openspec archive
      negotiation-driven-capacity-resize -y` merges the deltas into `openspec/specs/`
      and moves the change under `openspec/changes/archive/`; point the index row at the
      archived directory, and run `openspec validate --specs --strict`.
