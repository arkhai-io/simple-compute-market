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
- [x] 2.15 **Amended by the round-1 triage (owner record R13):** no buyer command
      could request a shape, so the run below could not have been made as written.
      Add a round-0 shape option to the VM buyer's `buy` and `negotiate` commands,
      filling `compute_resource` within the advertised cap (D10), and a stage in
      `e2e-tests/tests/e2e/roles/scenarios/vms/test_listing_shapes.py` after 07a that
      buys a smaller shape and asserts the reservation's dimensions and create-job
      sizing equal it, reusing 05a/05b's helpers. Validation's pipeline (the CI
      runner with Docker) and Helm parts observe it; the local Podman Compose
      include-path failure below stays out of scope.
      **Unobservable after a genuine VM-lane attempt; owner-authorized disposition.**
      One e2e run with a shape agreed below the listing's, asserting the VM
      built has the agreed shape. Fresh rebased images built with Podman 5.7.0 and
      the explicit native Compose 1.6.0 provider, but startup failed before readiness
      because included registry environment-file paths resolved against the wrong
      directory. No deployed assertion ran. Exact command, failure and cleanup:
      `docs/attachments/resize-shape-pricing/final-validation.md`.
      Treat this as the deployment boundary: incompatible in-flight negotiations
      must drain before upgrading or rolling back.
      **Observed:** validation 21's pipeline run 43090303156 at `77cee0783` passed
      stages 07a2–07a4 in the VM lane: `market buy --shape` reached ready, and the
      site's reservation and the create job held exactly the agreed smaller shape.
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

### Round-1 triage fixes (2026-11-11)

The implementation round's triage (review 02, validation 05, owner records 01 and
06) made every accepted fix in one pass against `30f7e4216`; another implementation
review follows the fix commit's validation. Before fixing, each point's code was
compared with `origin/spot-deals` (06 O1): none was rewritten there, so none was
deferred; R4, R5, R9 and R13 conflict with #351's later lines in the files they
share, which #351's triage resolves.

- **02 F1** — the administrator's settlement preview builds its order with
  `settlement_vm_order` when given an accepted negotiation, in both its held and
  fresh-reserve branches (`services/admin_settle_service.py`); a resized-deal unit
  regression covers both.
- **02 F2** — `tests/integration/test_revised_shape_client.py` drives a smaller-shape
  counter through the typed storefront client against the served shape-priced app
  and asserts the Agreement's terms, the plan's order and the stored Agreement.
- **01 R2** — `negotiation.multiplier_floor_bps` above 10,000 (or negative, or not
  an integer) is refused at VM storefront composition (`negotiation_multiplier_floor`).
- **01 R3** — the VM buyer's amount codec converts price bounds against its opening
  shape and refuses a payment above its ceiling, admitting the quote's one upward
  rounding (`negotiation_amounts.py`).
- **01 R4** — the buyer lifts `pricing.rate_structure` into its record's
  `rate_structure` at its registry boundary (`registry_listing.py`, `negotiate_cli.py`,
  `buy_cli.py`, `settlement_composition.accepted_listing_record`); `Listing` reads
  `pricing.rate_structure` when no top-level structure is stated.
- **01 R5** — core migration `20261111_001_publication_published_payload` adds
  `publications.published_payload_json`, written only by a successful publish
  (`_record_results`; reopen updates go through `_record_reopens` and keep it).
  `load_published_payloads` reads it; the VM runtime overlays the configured
  registries' last published `pricing.rate_structure` where it resolves the listing
  (`_as_last_published`), refusing `rate_structure_unpublished` and
  `rate_structure_divergent` at opening and at every validated round and acceptance,
  never at exit. `rate_structure_digest` moved to `arkhai_vms_negotiation.amounts`
  over `market_identity.canonical_json` (the package now declares
  `arkhai-kit-identity`; locks refreshed).
- **01 R6** — requested shapes above the advertised shape on any quantity refuse as
  `shape_exceeds_advertised`, at the feasibility position of `check_requested_shape`;
  the round's `shape_checks` says so. Two existing multiplier tests that revised
  above the advertised 4 vCPUs now revise to 3.
- **01 R9** — core migration `20261111_002_negotiation_negotiated_scalar` renames
  `negotiation_threads.agreed_price` to `negotiated_scalar`; the client's records,
  the negotiation summary and detail wire, `storefront_client.models`, the kit's
  `Acceptance.negotiated_scalar` and stage events, and every VM, bare-metal and
  API-credit storefront consumer follow. Money parameters (the settlement build
  context's `agreed_amount`, obligation builders, the buyer's outcome) keep their
  names. Three `docs/attachments` smoke scripts that call `commit_agreed_terms` were
  updated to the new keyword.
- **01 R12** — `kit/policy` exports `amount_from_proposal` and `set_proposal_amount`;
  every importer uses them, with no alias.
- **01 R13** — `market buy` and `market negotiate` take `--shape`; stages 07a2–07a5 of
  `test_listing_shapes.py` buy a smaller shape, assert the reservation and the create
  job's sizing, and release the holds before 07b refreshes the listing. Unobserved
  until the fix commit's pipeline runs the VM lane.
- **06 O2, outside the plan** — `dev-env/Dockerfile` installs nothing; `compose.dev.yml`,
  `compose/external.yml` and the `dev-env` chart's probes call `cast block-number`, so
  the image build no longer reaches `archive.ubuntu.com`.
- Documents: design.md decisions numbered D1–D17 with the owner record's settlements,
  proposal's "Knowledge to promote" per decision, the spec deltas (ratio rule, floor
  bound, last-published pin, divergence, buyer ceiling, negotiated scalar, settlement
  money, the advertised-shape cap) and a new `storefront-publication` delta;
  `docs/operator-handbook.md`'s drain steps; the probe change's proposal and index
  row; this change's index row; three unowned-work rows.

Evidence (each suite at the levels `TESTING.md` defines; integration where a real
SQLite database or the served app is used):

- Focused: VM storefront admin-settle unit 16 passed; the F2 app integration case
  passed; VM buyer 247 passed (unit and CLI); core storefront 227 passed (unit and
  library integration, including both migrations' upgrade tests); kit/capacity-publication
  138, kit/policy 97, kit/negotiation-runtime 62, core/storefront-client 68, core/buyer
  168, bare-metal storefront 611, API-credit storefront 275, e2e unit 896 passed and 1
  skipped; `make -C helm test-render` passed.
- `make check-packaging` passed. `scripts/change-workflow run pre-commit` closed
  "[change-workflow] pre-commit at 30f7e4216…: passed, exit 0" after
  after-functional-change and pre-commit-functional passed (its `make test` included
  VM storefront unit 1177 passed and 1 skipped, integration 575 passed); its first
  run failed only on decision destinations (D7 and D8 shared a bullet), fixed.
- Fresh-context compliance check: fixed — the handbook's claim that every open thread
  is refused (flat-priced ones carry across; the refusal reasons named); "as before"
  in the fulfillment delta; the spec's "a failed republication changes nothing",
  false when registries diverge (divergence now specified); refusal reasons,
  migration ids and `--shape` missing from design.md; an out-of-order migration test;
  the smoke scripts' keyword. Declined — the new seller-round tests sit in
  `tests/unit/test_sync_negotiation_seller_round_hook.py` with real SQLite, as that
  file's existing cases do; the new buyer CLI tests patch core names, as every VM
  buyer CLI test does (ROADMAP's unowned "CLI tests replace … names inside core").
- Not proven here: the VM and API-credit pipeline lanes (the fix commit's validation),
  the image build without curl (same), and the deployed smaller-shape run (2.15).

Open for the next review: buyer prices derived from the listing rather than given
explicitly are the advertised whole-shape rate, so with a smaller `--shape` the
buyer's ceiling exceeds 1.0× of what it buys (payment still capped at that amount);
`docs/attachments/resize-shape-pricing/first_use.py` records no publication, so a
shape-priced opening there is now refused `rate_structure_unpublished`; PR #350's
"Door" line still says the release is reversible (R11; `gh` was denied in the triage
session).

### Round-2 triage fixes (2026-11-11)

The triage of review 14, validation 07 and owner's notes 13 (the round `30f7e4216`..
`e8b3099e9`) made every accepted fix in one pass against `e8b3099e9`. The open items
above are resolved: O1 and O2 below, and the PR #350 "Door" line was corrected by the
orchestrating session on the owner's word.

- **07 V2** — a shape-priced `market buy` failed before reaching the seller: the
  quote validated the buyer's registry record as a storefront `Listing`
  (`extract_initial_price_from_order`), which requires `seller_principal`, a field a
  registry's discovery record never carries (it states `publisher_principals`).
  `arkhai_vms_negotiation.amounts.shape_hourly_amount` now reads the selected
  option's advertised rate directly and refuses `shape_price_unavailable` when it
  states none; the seller's results are unchanged. The buyer's `registry_listing()`
  test fixture is now registry-shaped (no `seller_principal`; `publisher_id`,
  `publisher_principals`), so the `negotiate` and `buy` CLI cases reproduced V2 (6
  failed against the `e8b3099e9` wheel) and pass after the fix. Stages 07a2–07a5 and
  task 2.15 wait on the fix commit's pipeline.
- **07 V1** — the API-credit wheel-install tests installed a stale `arkhai-core 0.5.0`
  that uv had cached two weeks earlier for the same find-links path and filename,
  not the wheel the fixture had just built; the commit was not the cause.
  `domains/apicredits/tests/test_distribution_install.py` installs with `--refresh`.
- **13 O1** (a decision; D5) — with `--shape` and a price the buyer does not state,
  `buy` and `negotiate` derive it for the opening shape: each candidate's selected
  option rate is scaled by the composed-price ratio and rounded up
  (`negotiation_amounts.priced_at_opening_shape`), before core's derivation picks
  the cheapest; `buy` skips a candidate whose selected asset cannot price the shape.
  Core's `extract_seller_min_price` returns the exact integer rate rather than a
  float, which above 2^53 base units could round a derived ceiling below 10,000 bps.
  The spec delta gains the buyer requirement and a scenario.
- **13 O2** — `docs/attachments/resize-shape-pricing/first_use.py` enters the
  seller-hook fixture's store as the async generator it now is, records a
  successful publication wherever it stores or withdraws rates, and its `index.md`
  says so.
- **14 F1** — D12 and the proposal's non-goal distinguish the acceptance hold, once
  the shape is final, from a hold placed while the shape is negotiated.

Evidence (levels as `TESTING.md` defines them):

- Focused: VM buyer 256 passed (unit and CLI, including the registry-shaped
  regressions, derived prices under `--shape`, the 18-decimal rate and the skipped
  unpriceable candidate); core buyer unit 168 passed; API-credit buyer 35 passed;
  API-credit `test_distribution_install.py` 3 passed (wheel installation); VM
  storefront multiplier, seller-hook, initial-price and revised-shape-client suites
  62 passed (unit and library/app integration).
- `make check-packaging` passed (run twice, after each set of fixes).
- `scripts/change-workflow run pre-commit` closed "[change-workflow] pre-commit at
  e8b3099e9…: passed, exit 0", after after-functional-change and
  pre-commit-functional passed (VM storefront unit 1177 passed and 1 skipped,
  integration 575 passed; e2e unit 896 passed and 1 skipped) and every change check
  passed.
- Fresh-context compliance check: fixed — derived rates passed through a float in
  core's derivation (now exact); one unpriceable candidate aborted `buy` (now
  skipped); D5 said derivation reads the selected option's rate (`buy` without
  `--shape` reads the first accepted escrow; D5 reworded); the rateless-option
  refusal had no test; the spec line's wrap; a redundant fixture update; the helper's
  docstring; the proposal's hold wording. Declined — the derivation table's
  "advertised" column label now shows the scaled rate under `--shape`; it is core's
  label for the rate derivation anchored on, and relabelling it would teach core
  about shapes.
- Not run here: `first_use.py` itself (running a script was denied in the triage
  session; its calls were checked against the fixture's helpers and the runtime's
  overlay), and the VM pipeline lane's stages 07a2–07a5 (the fix commit's
  validation).

### Validation 21 triage fix (2026-11-11)

Validation 21 (pipeline run 43090303156 at `77cee0783`) passed 07a2–07a4, then failed
08b: the restated constrained shape was a new listing, judged against available
capacity, and the cycle reported `listing_shape_infeasible` with no L40S free. Stage
04's and 07a2's VMs were delivered, so 07a5's `admin_release_reservations` released
nothing (`released_count=0`): the site's `FulfillmentReleaseGuard` frees only a
torn-down or undispatched reservation. The fix, against `77cee0783`:

- **21 V1 (owner: option A)** — `test_listing_shapes.py` declares 3 GPUs, so one stays
  available after the two buys; 07a5 is removed, and the module docstring no longer
  says every hold is released or that publication judges only the declaration.
- **21 V1, outside the plan** — 01a, 08b and 09b filter the cycle's actions through
  `_pool_actions`, which matches a pool named at the action's top level (`hold`,
  `refuse`, `report`) as well as under `source` (`publish`, `fail`); before, 08b's
  failure message printed `[]` for the very `report` that explained it.
- 2.15 is ticked on validation 21's 07a2–07a4 pass. The VM lane, 08b included, is
  observed again by the fix commit's validation.

Evidence (levels as `TESTING.md` defines them):

- Focused: `test_listing_shapes.py` collects its 27 stages; e2e unit 896 passed and 1
  skipped. The scenario itself runs only against a stack: the fix commit's pipeline.
- `scripts/change-workflow run pre-commit` closed "[change-workflow] pre-commit at
  77cee0783…: passed, exit 0", after after-functional-change and
  pre-commit-functional passed (`make check-packaging`, then `make test`: VM storefront
  unit 1177 passed and 1 skipped, integration 575 passed) and every change check
  passed.
- Fresh-context compliance check: fixed — the module docstring's closing claim that
  publication judges only the declaration (the reconciler judges a backed pool against
  availability); `_pool_actions`' docstring omitted `fail` and `refuse` and did not say
  closes and refreshes are excluded; the `DECLARED` comment named "stage 07" for 07a2;
  this note was missing. Earlier notes citing 07a2–07a5 are history and stand.

### Pre-closeout triage fix (2026-11-11)

Review 27 (pre-closeout, at `58491f7c1`) found a gap in the published-rate pin
(01 R5). The fix, against `58491f7c1`:

- **27 F1 (owner: alternative b)** — after an upgrade no publication carries a
  retained payload, so a first refresh that one registry accepted and another
  refused let `_as_last_published` price from the accepting registry alone while
  the other still served the old rates. A configured registry with a publication
  row of the listing but no retained payload now counts as divergent while another
  registry's structure is known, for a shape-priced listing
  (`rate_structure_divergent`); a registry with no row is still ignored. The runtime
  reads the repository's existing `load_publications` beside
  `load_published_payloads`; no schema or wire change. D9, the negotiation-protocol
  delta (a sentence and a scenario) and the operator handbook's upgrade section say
  so. origin/spot-deals (`8619e1c1e`) carries an earlier version of this change
  without the published-payload overlay, so no later change rewrote this code; its
  `negotiate-open-ended-compute-terms` buyer-side digest check will meet the new
  `_as_last_published` when that stack is rebuilt on this change.

Evidence (levels as `TESTING.md` defines them):

- Focused: `test_sync_negotiation_seller_round_hook.py` 19 passed (unit), with
  three new cases: the partial first refresh refuses until the unseen registry
  accepts (it fails without the fix), a flat-priced listing negotiates beside an
  unseen registry (it fails without the shape-priced guard), and a registry never
  sent the listing does not block. VM storefront unit and integration suites
  matching negotiation, seller-round, publication and rate: 392 passed, 1 skipped.
- `scripts/change-workflow run pre-commit` closed "[change-workflow] pre-commit at
  58491f7c1…: passed, exit 0", after after-functional-change and
  pre-commit-functional passed (`make check-packaging`, then `make test`: VM
  storefront unit 1180 passed and 1 skipped, integration 575 passed) and every
  change check passed.
- Fresh-context compliance check: fixed — the handbook said convergence lifts
  every such refusal, but convergence resends only to a registry whose last
  publish failed (a pre-upgrade `published` row waits until the listing next
  changes; D9 and the handbook now say so, a cost the owner was shown with
  alternative b); no test covered the flat-priced exemption (added); D9 left out
  the shape-priced qualifier; the delta's sentence implied the registry had
  accepted a publish (reworded to any publication record without a retained
  payload); two unwrapped lines.
- Not run here: `first_use.py` (running it was refused in this session; it records
  every publish at all configured registries, so the new rule leaves it
  unaffected), and the pipeline (see 3.8's note).

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
      *Note (27 F2, owner's disposition):* GitHub Actions ends every e2e.yml dispatch
      of this branch in `startup_failure` before any job starts (validation 22), and
      the owner waived validation's pipeline part for the rest of the change (log
      seq 48). That waiver does not discharge this part. At closeout's HEAD, run the
      pipeline's lanes locally against their compose stacks — `make -C e2e-tests
      test-e2e-vm`, `test-e2e-bare-metal` and `test-e2e-apicredits`, the targets
      e2e.yml runs — and record each lane's result and the scenarios exercising
      this change (`e2e_listing_shapes`, stage 08b included; `e2e_non_erc20_settlement`;
      the `compute_deal_stages` helper's deals) as the evidence, naming the Actions
      startup failure as why the pipeline itself did not run. If the local lanes
      cannot run, the owner waives the evidence: record the blocker — Actions
      `startup_failure`, cause not visible, owned by no change in this repository —
      with the pipeline-gated scenarios unrun, and proceed to archival.
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
