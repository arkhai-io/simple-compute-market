# Tasks — hosted compute rate parts and seller notice

The owner's design discussion recorded in round 1's owner record stood in for this
change's design review. Round 1 implemented sections 1–4 with task 2.7; round 2
implements sections 4A, 4B, 4C, 4D, 4E, 4F, 5 and 6, each committed on its own,
reviewed and validated together; pre-closeout and closeout follow. Task 4B.5 returned
the change to design; sections 4C–4F were planned against the design its return
settled and design review 18's triage refined (D12–D16, D6a's watchdog status). No section
implements another verifier, continuation daemon or site renewal policy. Section 5
returned the change to design again; section 5 and tasks 4F.7, 6.3 and 7.3–7.9 were
replanned against the design that return settled (D17–D26) and design review 35's
triage refined (D18's renamed requirement, D6a's narrowed probe and bound).

Verification levels follow docs/development/TESTING.md. Every behaviour lands with
permanent tests at the level that proves it, with the fix or feature it covers.
Checked tasks in sections 1–3 record delivered library interfaces and focused
validation; the enumerated full qualification matrix remains section 6 work, not
evidence claimed by those checkmarks. Full pipeline evidence is required at
closeout, not as a substitute for focused tests.

## 1. Confirm dependency gates and freeze the consumer interface

Files: kit/arkhai-payments/schema/SOURCE.md, schema/payments.schema.json,
test-vectors/payments.json; the lifecycle adapter protocols supplied by the
foundation; this design's D1–D7.

- [x] 1.1 Confirm agreed-evidence-and-early-termination supplies the codec, command
      contracts, hosted once adapter, evidence-store/journal seam, per-part contract
      vendoring and round-2 verified-snapshot interface. Record the actual schema
      and vector hashes. Gate task 3.5 on foundation 10.4, 10.5 and 12.3;
      gate task 4.5 on foundation 7.5 round 2, after 12.3 and 13.3.
      Do not edit generated models to mimic an unvendored contract.
- [x] 1.2 Confirm negotiate-open-ended-compute-terms supplies the price accessor
      with its period unit, common term shape, listing bounds and two front-door
      servicing gates. Gate on terms 1.3/2.1/2.2/3.1/3.2 resolving the horizon into
      `duration_seconds` before signature, including whole-second rate starts. Freeze period plus reserve_ahead_seconds and the recommended setup_amount shape with that consumer. Rate derivation reads the accepted per-period money through
      `agreed_price` over the signed monetary amount; no separate rate-structure
      carrier is needed, and the current listing is never read.
- [x] 1.3 Freeze operation descriptors, consume the foundation-owned versioned
      activation envelope (including site activation reference/instant), verified rate
      observations and rate re-anchoring output for convergence. Foundation
      in-process contract fakes cover kit library integration; the HTTP lane
      doubles gate only lane/e2e execution. No kit depends on runnable tooling.
- [x] 1.4 Obtain or explicitly gate on published signed snapshot/start/mixed-part
      vectors and partial-reversal-before/after-stop traces. Identify missing
      authority conformance evidence without replacing it with a double claim.
      Verify explicit partialPeriod on rate stop entries and rate ends and dispute
      chosen-entry payloads in the published contract. The published schema requires an inert returned partialPeriod on once ends too; preserve the foundation encoding (see dependency-contracts.md).
      Confirm delivery_end remains a dispute intent/request and mediation's
      published standard self-penalty uses its own chosen stop entry with returned.
      Producer evidence gates that package; there is no seller restitution entry
      or several-stop-entries-per-account dependency. Freeze timestamp precision
      and per-end partialPeriod/late-start semantics with the vendored contract.
      Undeclared terms fail closed; never hand-edit generated models. The
      authority, not SCM, computes a returned/prorated partial period at the
      unchanged absolute end.

Validation: published-contract conformance using kit/arkhai-payments check-vectors
and check-generated targets. The foundation owns proof implementation/negative
signature fixtures. No e2e is claimed here; unresolved dependencies stop the
section they gate.

## 2. Rate parameters, mandate derivation and both-domain presets

Files: kit/arkhai-payments/src/market_arkhai_payments/mandates.py, buyer.py,
settlement_config.py, seller.py and a preset helper beside mandates.py;
kit/arkhai-payments/tests/test_mandates.py, test_buyer.py,
test_settlement_config.py; both domains' storefront settlement_composition.py,
publication configuration/builders and their focused publication suites.

- [x] 2.1 Add paired period/reserve_ahead_seconds validation, fixed-unit/positive
      constraints, optional setup_amount, the finite term requirement and
      early_termination.settles_through as the only term-end input, whole-second
      rate Agreement start at materialization and
      partialPeriod capability check. Reject fractional rate starts rather than
      rewriting signed Agreement bytes; once-only rounding stays unchanged.
      Keep approval_window distinct from adjudication. Carry foundation's premature_stop_penalty
      through the injected preset helper, encoding only the value supplied by terms;
      terms alone resolves preset defaults and seller overrides. In
      kit/arkhai-payments/src/market_arkhai_payments/settlement_config.py add public
      arkhai_payments.period and billing-kind projections, with the typed missing-period
      representation agreed with discovery task 1.2. Verify once-only, rate and mixed
      setup/rate projection in test_settlement_config.py. Entitled notice pays none;
      emergency without notice pays the capped mediation penalty, never a seller payment-adapter correction.
      A setup-bearing preset is gated by the servicing declaration's setup flag, not another payments wire change; rate-only opt-out remains available. Verify malformed pairs, calendar periods, setup opt-out and insufficient lead.
- [x] 2.2 Derive setup-once then rate deterministically through the accessor and
      codec. Include rate end, afterStop hold, maxHoldExtension and exact per-part
      authorities/notices. Require partialPeriod on rate stop entries and rate
      ends; retain the inert once-end field required by the published schema;
      dispute rate stop is {account, notice: PT0S, partialPeriod: chosen} and its
      stop event supplies treatment. Keep rate start payee-only and seller stop
      entries only for accepted entitlements: spot notice, none on on-demand.
      Derive no restitution entry or implicit favourable-payee stop privilege;
      once-only options without early-termination entitlements authorize no start/stop.
      Verify setup's encoded end is Agreement start, effectively clamped to approval if later, and absolute
      capacity bounds are never extended after late activation/start. Map early_termination.settles_through
      through the foundation codec to end.partialPeriod: preset last_boundary.
      Refuse undeclared terms rather than round term durations or downgrade.
- [x] 2.3 Extend the buyer's exact mandate check for mixed parts, ordering, price,
      asset, hold, cap and stop authorities. Verify explicit zero payer notice is
      preserved exactly. Use the foundation's notice_seconds/settles_through
      authority mapping; reject retired exposure_seconds and stop+exposure.
      Consume the terms-owned buyer acceptance policy: by default refuse payee
      entitlement or term end unless settles_through is last_boundary, naming the
      offending term. Verify explicit buyer opt-in can accept started_period;
      do not mistake an exact mandate match for policy acceptance. Refuse extra
      seller stop entries not derived from entitlements. Do not claim on-demand
      prevents physical preemption: the premature-stop penalty and a buyer case over
      held money (bond reserved) are the remedy; the seller's own exit is the
      mechanically ruled self-penalty.
- [x] 2.4 Supply setup-bearing on-demand/spot presets with explicit setup pricing
      and seller opt-out: the setup part is an ordinary once part ending at the
      later of the Agreement start and approval, owed from approval; verify that a
      buyer's stop before activation leaves it with the seller and that the
      seller's self-penalty for non-delivery returns it. A setup amount is the
      seller's choice in both domains, with no default in either. Bind all terms
      into option identity; invent no amount or minimum-spend gate.
- [x] 2.5 Supply the preset helper to the terms-owned VM/bare-metal publication
      adapters through their injected preset-helper interface; helper availability
      gates rate emission, not the terms change's archive. Do not implement generic
      option emission a second time. Prove
      accepted option plus bound rate structure survive repricing before
      materialization/restart; preserve reserved/API-credit once behavior.
- [x] 2.6 Add the materialization servicing-declaration gate: refuse undeclared
      rate servicing, including for accepted options after declaration withdrawal.
      The terms change retains publication/acceptance gate ownership.
- [x] 2.7 Both compute buyers' payments term contexts take the stoppable rate part
      and the contract's partial-period set from the buyer helper,
      `market_arkhai_payments.buyer.approvable_terms`; `SUPPORTED_PARTIAL_PERIODS`
      in mandates.py is the one set mandate derivation, buyer lifecycle validation
      and the preset context read. Without it both buyers dropped every spot and
      on-demand option ("early_termination requires a stoppable part") and `market
      buy` printed "No listings matched" with exit 0. Authority selection now keeps
      each distinct refusal; VM `buy`, `negotiate` and `listing list` print them
      when nothing was selectable, and `buy` exits 2. Tests: payments
      test_buyer_term_context.py (the presets' options pass only with the helper's
      context), deal-lifecycle test_selection.py, VM
      test_recurring_option_selection.py, bare-metal test_recurring_options.py. An in-process VM `market buy` trial
      with a fixture-only servicing declaration selected, disclosed, negotiated,
      validated acceptance and approved both options, then stopped at commit: the
      buyer lifecycle builds the once-only payment adapter for a rate mandate,
      which the rate buyer-end work (task 4.5) replaces.

Validation: unit targets test_mandates.py, test_buyer.py and
test_settlement_config.py; vector conformance for mixed and rate mandates;
application-integration targets under domains/vms/storefront/tests/integration
and domains/bare_metal/storefront/tests/integration for each publication adapter.
Run kit/arkhai-payments typecheck and the affected domain typing targets.
No running continuation is required for these option/approval seams.

## 3. Stateless rate adapter and authority-enforced period treatment

Files: kit/arkhai-payments/src/market_arkhai_payments/client.py, the foundation's
hosted adapter module and new operations.py, and the foundation-owned seller-half
exceptional-end dispatch/dispute-adapter seam for filing integration;
kit/arkhai-payments/tests/test_client.py, test_seller.py and
tests/integration/ for real journal consumers injected at the public adapter seam.
Journal persistence itself belongs to convergence.

- [x] 3.1 Translate rate start, entitled stop/notice and partial reverse into
      explicit per-part commands with operation-derived stable keys. Require
      the foundation's versioned activation envelope after verified site activation. Delivery
      authorization remains pure; implement the separate start_billing effect using
      the end service's sole stable operation key. End service journals key and
      activated evidence before I/O; delivery stores only its reference. Derive
      per-part keys from that intent, never a second keyed start. Missing,
      malformed or mismatched evidence refuses before effects. Verify lost response
      and identical retry against the in-process contract fake; changed-content
      key reuse is refused by caller journal comparison; pass its descriptor/digest
      to the stateless adapter for comparison, with authority refusal as backstop.
- [x] 3.2 Expose verified per-part start/pendingStop/stop, funded-through, extension
      refs, releaseAt and event ordering to lifecycle read/watch. Verify exhaustion
      and maximum-term causes, missing pre-start funding as unknown, and refusal to
      use unverified/regressing snapshots through the foundation verifier.
- [x] 3.3 Export immutable operation descriptors for caller write-before-call,
      then resolve unknown from authority events before another monetary delta.
      Implement D4's refusal classification, including transaction_stopped start
      failure, read-before-insufficient-funds reconciliation and matured shortfall.
- [x] 3.4 Map settles_through to partialPeriod through the foundation codec:
      started_period/charged, last_boundary/returned, stop/prorated. Gate each
      value on the servicing declaration at publication, acceptance and
      materialization. Qualify boundary/no-start/terms stops,
      superseded and equal-time requests from authority vectors; compute no
      local end-correction delta or clawback. Periods stay reserved until their
      end or part stop; afterStop payout is unchanged. Negotiation decides entitled
      stop treatment; the exceptional-end self-penalty instead always stops rates
      returned through mediation's own chosen entry. SCM seller presets
      offer last_boundary, and the terms-owned buyer policy refuses other payee
      or term-end treatments by default, with an explicit buyer override.
      Verify human rulings state treatment; delivery_end preserves payer notice and
      treatment. delivery_end is the dispute intent for mediation's only
      mechanical criterion: payee filing or valid concurrence under mapping/time/replay guards, including receipt-backed payer claims; other cases stay triaged.
- [x] 3.5 Verify the hosted adapter against foundation 10.4, 10.5 and 12.3's
      journaled delivery_end filing path and qualified mediation mapping. Consume
      deal-lifecycle's “A seller's exceptional end is a dispute filing”; do not
      reimplement seller filing or journal ownership. Observe filing response-loss/
      read/retry, spot emergency filing, on-demand returned treatment and capped
      penalty after refunds. Verify no seller payment calls, exceptional-end payment
      operation, direct-payment fallback or second correction journal. Report missing
      dispute intent/request/mapping or producer qualification to foundation.
- [x] 3.6 Implement the pure rate authorize hook for commit/dispatch/start/disclose
      under D4's phase table and settlement-servicing delta. Return reason,
      operation identity and verified provenance with allow/refuse/pending. Verify
      absent/unreachable/unverified/regressing evidence, wrong phase/deal, initial
      reservations without fundedThrough, future versus effective stop, exhaustion,
      unknown start and disclose-before-start with the shared clock-injected
      in-process authority engine. Convergence composes this hook; it must not
      interpret hosted fields or implement the payment decision itself.

Validation: unit derivation/serialization cases, shared vector conformance and
library integration with in-process contract fakes for unknown retry, per-stopper
partialPeriod, winning-record attribution, independent discounts, partial reversal
before/after stop and held-money extensions. Lane HTTP doubles test deployed wiring,
not kit library behavior. Verify no mechanism import of kit/deal-servicing
or either domain with make check-architecture. Do not replicate the foundation's
cryptographic proof test matrix.

## Sections 1–3 implementation result and restart

- Delivered `mandates.py`, `agreement.py`, `presets.py`, `settlement_config.py`,
  `operations.py` and `rate_adapter.py` in the payments kit; buyer/seller gates and
  both compute `settlement_composition.py` integrations. No installed recurring
  servicing declaration was enabled.
- Reused the shared DeliveryEvidence, lifecycle codec, snapshot verifier, foundation
  dispute filing and authority fixture. Rate descriptors require caller-persisted
  digests; disclosure can consume the journaled start outcome with its operation
  identity. Neutral per-part observations distinguish stop requests from winning
  final stops; watch observes notice maturity independently of its event cursor and
  retains the first observation on replay.
- Focused evidence: payments 221, lifecycle servicing 63, mediation 77, VM
  publication/payment integration 104, bare-metal publication/payment integration 21
  pass; published vector/generated checks, kit typing and composition-file
  typechecks pass (bare metal skips untyped-import diagnostics for existing unmarked
  dependencies); `make check-packaging`, comment hygiene, amount-read inventory,
  change index and pinned OpenSpec strict validation pass. Permanent rate regression
  coverage is section 4's. The packet and exact commands are in
  `docs/attachments/spot-deals-sections-1-3/index.md`; `make dist-ci && make -C
  kit/arkhai-payments first-use-rate` reproduces the fixture with no secrets or
  resident services.
- E2E did not run in this slice (no Docker). Validation's compose lanes and local
  Helm part are the end-to-end evidence; a lane unrun at closeout is a blocker, not a
  pass.
- Promotion to the owning permanent specs/companions, architecture/configuration
  docs, roadmap and campaign index is closeout's; this slice updated only the kit
  README.

## 4. Seller notice command and operator first use

Files: kit/deal-lifecycle-contracts command/outcome models and route contracts,
kit/deal-lifecycle-client typed methods, the hosted adapter's notice admission;
domains/vms/storefront/src/market_storefront/cli.py and operator command group;
domains/bare_metal/storefront/src/arkhai_bare_metal_storefront/cli.py and
admin_cli.py; kit/deal-lifecycle-buyer and each domain's canonical buyer end verbs.
Reuse the foundation's command identity/recovery contract; do not add a
second preemption endpoint or a local payment-stop scheduler.

- [x] 4.1 Admit notice against the accepted payee entitlement and adapter support,
      preserve its command operation identity, and immediately submit stop
      with explicit parts and optional at. Return the authority's effective time
      and pending/unknown/refused status. Verify current listing edits cannot
      grant or revoke the accepted permission.
- [x] 4.2 Surface verified pendingStop in lifecycle read/list. Preserve an earlier
      buyer stop, immutable retry identity and the authority's notice minimum.
      On-demand refusal points to delivery_end only for seller non-delivery,
      not a self-interested override or automatic seller-fault filing after a lawful end.
- [x] 4.3 Add the typed notice method and recommended deals preempt CLI verb to
      both domains, taking negotiation ID, operation key and optional --at.
      Delegate through lifecycle submit and its existing seller authentication.
      Output authority status/time, including unknown; do not report local
      command acceptance as an authoritative scheduled end.
- [x] 4.4 Prepare committed first-use configuration/examples for both domains
      under the lane profile, with paired on-demand/spot options, explicit authority
      entries, test mode and double selector. Document one runnable invocation per
      domain that lands on its preemption surface. Before convergence, use
      lane-only approval/command fixtures and assert delivery refuses without the
      rate hook; do not commit/deliver an unserviced live rate option. This
      fixture is the explicit lane-only door exception. As built, the fixtures
      commit started_period and their buyer accepts charged terms; task 4B.3
      moves them to the shipped presets with default buyers.
- [x] 4.5 Re-drive both domains' canonical rate buyer end: stop then hint, keep
      service during nonzero payer notice, and end through watch at effective
      stop. Consume foundation 7.5 round 2 (after 12.3 and 13.3) and
      buyer-orchestration's “The buyer's end is backed by its own stop or a case”
      for immediate surrender and outage handling; do not implement those paths here.
      Coordinate rate notice display.
- 4.5a The buyer's watchdog, which round 1 deferred on MVP grounds, is restored and
      moves to task 4B.6.
- [x] 4.6 Verify the foundation-owned VM admin route delegates notice for a lawful
      entitled stop and files delivery_end for seller-caused emergency failure,
      including spot hardware failure. The authorized foundation selector amendment
      is a separate commit; it reuses notice admission and the existing failure path.
- [x] 4.7 Add permanent lowest-level coverage for rate mandate derivation, buyer
      exact re-derivation, pure authorization phases, refusal classification,
      start/stop/reverse identities and verified observations; seller notice and
      both domains' normal end/explicit-surrender command wiring. Keep examples
      as first-use entry points.

Validation: lifecycle client/contract unit suites; application-integration at each
storefront for seller authentication, accepted-option admission, refusal before
adapter effect and response-loss read; each domain's focused operator CLI suite.
Buyer-half and canonical buyer-CLI cases re-drive priced notice, explicit immediate
surrender, hint failure, payment-authority outage and both-authorities-down retry.
First use runs deals preempt against a double-backed approved spot fixture and
reads pending stop while asserting delivery is refused without the rate hook.
Before convergence lands, this proves command and authority record, not teardown.

## Section 4 implementation result and restart

- 4.1–4.3: accepted-entitlement notice uses the existing administrator-authenticated
  submit route, durable command identity and per-part stop descriptors. Async/sync
  clients and both `deals preempt` verbs retain verified pending/final stops in
  read/list and recover lost responses without postponing an earlier payer stop.
  Application tests prove current listing edits can neither grant nor revoke accepted
  notice rights.
- 4.4: `domains/vms/storefront/examples/preempt.lane.toml` was the lane-only
  approval/command profile for both domains (4B.3 moved it to the kit and the shipped
  presets): paired options, explicit authority, in-process doubles, test mode, setup
  opt-out and explicit charged-term buyer acceptance. Both first-use commands passed;
  the default buyer refuses charged terms, and materialization without the rate hook
  refuses. Setup and observations: `docs/attachments/spot-deals-section-4/index.md`.
- 4.5: ordinary rate end journals the payer stop, then hints, retaining service
  during notice. Both compositions select the rate adapter; VM `end` and bare-metal
  `teardown` (`end` since 4B.2) default to normal end, `--end-now-regardless`
  selecting immediate surrender. Escalation reuses the original stop; unknown stop,
  hint loss and restart preserve independent progress. Application tests observe the
  effective stop through watch; deployed rate delivery/teardown is convergence's.
- 4.5a was deferred on MVP grounds and no watchdog was built; the owner restored it
  (task 4B.6, built as section 4F).
- 4.6: selector commit `a0ae6148d` adds `interruption_kind=preemption|failure` beside
  the free-text reason. Rate requests must state it; once-only omission keeps failure
  for existing callers. Lawful preemption requires the accepted payee entitlement and
  delegates notice; failure ends delivery and files for spot and on-demand, with no
  automatic rate self-penalty. Both typed admin clients expose the selector and
  operation key; the storefront CLI has no interrupt verb.
- Permanent coverage (4.7): exact setup/rate derivation and buyer comparison,
  authorization's phase table and immutable activation bindings, start/stop/reverse
  keys, unknown-response recovery, refusal classes, verified pending/final stop
  records and fixed settled figures after held reversal. Seller and buyer application
  tests use real SQLite, signed typed clients and injected authority doubles;
  canonical command tests use their own module's factory seams.
- Validation: payments 266, servicing 70, contracts 37, lifecycle client 2, buyer
  half 22; focused VM storefront 157 and bare-metal storefront 46; buyer suites and
  packaging results in the evidence index. Payments, servicing and buyer-half typing,
  published vectors and generated checks pass. Compose VM run
  `PROVISIONING_MODE=mock mise exec -- make -C e2e-tests test-e2e-vm` exits **2**:
  290 pass, 2 skip, one failure in the explicitly excluded retained `rate_structure`
  pricing mismatch
  (`test_listing_shapes.py::TestStage07_ShapePricing::test_07a2_market_buy_buys_a_smaller_shape_and_reaches_ready`),
  unchanged.
- Fixture and environment mistakes found on the way changed no production behaviour.
- Not claimed by section 4: an installed recurring delivery declaration, the
  self-penalty remedy, the watchdog or live qualification.

## Section 4 follow-up corrections

- [x] Runway: acceptance horizon and payment mandate derivation share `minimum_rate_duration_seconds`. A start 3600 seconds after acceptance with a 60-second approval window, 30-second delivery deadline and 60-second period requires a 90-second duration. The previous mandate function admitted 89 seconds; the regression covers below/at/above the bound for early and late starts. Settlement-runtime 182 and payments 272 tests pass; payment typing, vectors and generated checks pass.

- [x] Refusal classification: the vendored `ApiErrorCode` enum defines every code named by D4, including request_id_reused and hold_not_reversible. Their HTTP 409 responses now require repair through structured command-error classification. HTTP 409 insufficient_funds at approval raises exported `PaymentApprovalInsufficientFunds` with funding guidance before polling. Server responses retain unknown/generic API failure rather than claiming a funding refusal. Payments 277 tests, typing, vectors and generated checks pass.

## Round 1 triage fixes

The round's triage (`reviews/02-implementation.triage.md`, with the owner record
`reviews/01-implementation-owner.md`) made the fixes that turn the build green; each
names the owner-record point it carries out.

- [x] R4, materialization from the declaration: `PaymentSettlementData.for_agreement`
      calls `require_option` on the composition's `RateServicing` for the Agreement's
      selected option, so an undeclared treatment or setup charge refuses with
      `RateServicingUnavailable` and `settlement_option_withdrawn_refetch`; the
      contract-revision and proposed/live checks are gone. `PaymentsRatePresetHelper.build`
      checks only that it was handed its own mechanism's declaration;
      `rate_contract_revision` is removed from the public API. `examples/rate.py`,
      `market_arkhai_payments.fixtures.recurring_options` and the VM `preempt.py`
      example build the new declaration naming exactly the treatments and setup their
      options use.
- [x] R5, the four failing tests rewritten as positive per-period tests:
      `test_agreement.py` derives one rate part charging one period's price for a
      multi-period term, with no once part and nothing equal to a term total, and a
      stored once mandate refuses to bind it; a new case refuses undeclared, other-
      treatment and no-setup declarations at materialization. `test_settlement_config.py`
      projects complete pairs (with and without setup) as `per_period` and refuses a
      lone period, a lone reserve and setup without a rate, naming the pairing rule.
- [x] R14, shared composition wiring: `market_arkhai_payments.presets.payments_rate_wiring`
      supplies the helper and timing projection both compositions install when the
      caller passes none (an explicit mapping, empty included, replaces them);
      `servicing_stage(..., rate_servicing=)` constructs the stage with the
      composition's declaration instead of assigning it after construction.
- [x] R16, the freshness window: the rate `authorize` decides on a snapshot whose
      `observedAt` lags the storefront's clock by at most `snapshot_freshness_seconds`
      (a new `[Settlement.arkhai_payments]` field, default 5, at most 300; the Helm
      values schemas were regenerated); bounds stay checked at the storefront's `now`.
      The seller stage passes the configured window to the rate adapter.
- [x] R17, approval under the run's policy: `PaymentApproval` applies the terms
      policy's waivers to the default refusals and no longer re-ranks the authority,
      which approval cannot do without the listing's registry (selection ranked it, and
      the exact mandate check binds it). The VM buyer's `payment_buyer` passes the
      settlement policy's `BuyerTermsPolicy`; the bare-metal buyer's `payment_approval`
      takes the run's policy, built by the new `buyer_terms_policy`, which
      `validate_authority` also uses.
- [x] R21 #20 and #40: `pricing()` returns the clause's `delivery_deadline_seconds`;
      `settlement_config.clause_rate_minor_units` is the one minor-unit conversion for
      the option builder, `pricing()` and `build()`, refusing a rate finer than the
      asset's precision.

Evidence, all at HEAD with the fixes, after `make dist`:

- Unit (payments kit): `make -C kit/arkhai-payments test` — mypy clean over 28
  files, vectors and generated models current, 318 passed (was 287 passed, 5 failed,
  9 typing errors). New: `tests/test_presets.py` (deadline, one conversion,
  precision refusal), freshness-window and skew cases in `test_rate_adapter.py`,
  waived/unwaived approval in `test_rate_mandates.py`.
- Unit and application (buyers): VM buyer 323 passed, including
  `test_recurring_option_selection.py` (had failed at collection) and the new
  `test_payment_approval_waivers.py`; bare-metal buyer 68 passed (was 66 and 2
  failed), the waiver test asserting the run's policy reaches approval.
- Unit and application (storefronts): bare-metal 631 passed; VM 1194 unit (1
  skipped) and 591 integration passed. Both compositions' declaration tests assert
  the stage carries the composition's declaration and the kit's wiring is installed.
- Not run here: the two first-use examples (`examples/rate.py`,
  `examples/preempt.py`); `rate.py` is type-checked with the kit. Both run in the
  suites since (4B.3, 6.6).
- Round 1's function-local imports in `domains/vms/storefront/examples/preempt.py`
  and `tests/integration/test_spot_notice.py` moved to module level. R3's removal of
  deal-lifecycle's "Returned treatment is not expressible" scenario is a REMOVED
  requirement with an ADDED successor, since a MODIFIED block cannot drop a scenario.
- The compliance check (against `dab8d06b8`) fixed: `preempt.py` passing the removed
  `allow_unprotected_terms` (now per-term `waivers`: the charged term end and, on
  spot, the charged payee stop); two spacing slips; a VM composition comment
  claiming an invariant only the factory keeps; untested seams — the configured
  window reaching the seller stage's adapter, the setting's bounds, `build()`
  refusing another mechanism's declaration, the wiring reading authorities at each
  projection (payments kit 323, VM `test_spot_notice.py` and
  `test_settlement_composition.py` 23 passed). Declined: moving the two new test
  files into `unit/`/`integration/`, since both packages' test roots are flat.
- `make test`'s release tooling found the published packages' table (now
  `docs/guidance/repository/published-packages.md`) missing
  `arkhai-kit-deal-lifecycle-client` for both storefronts, a runtime dependency since
  section 4; the rows now list it.
- `scripts/change-workflow run pre-commit` at `dab8d06b8`: after-functional-change,
  pre-commit-functional (every suite) and pre-commit (the change checks) passed.

## 4A. Payments kit and contracts

Files: kit/arkhai-payments (adapter.py, rate_adapter.py, operations.py, seller.py,
buyer.py, mandates.py, settlement_config.py, presets.py and their tests);
kit/deal-lifecycle/src/market_deal_lifecycle/adapters.py (the protocol);
kit/deal-lifecycle-contracts (models and version); kit/deal-lifecycle-buyer and both
buyers' adapter construction; docs/guidance/engineering/versioning.md;
openspec/changes/README.md (the staged-rename gap row). Owner record points R9, R12,
R13, R15 and R19.

- [x] 4A.1 One payments transaction adapter by composition (D11): implement the
      foundation's `PaymentAdapter` protocol from shared components (mandate binding,
      verified snapshot reads, reverse, event projection, refusal classification,
      descriptor recording) and per-part-kind behaviour (`once`: reverse, extend,
      observations; `rate`: start, stop, notice, observations, the `authorize`
      phases). A once-only mandate's `start_billing` is a no-op. Remove `_allow_rate`,
      the class choice in the seller stage and both buyers, and the stop path's
      pre-read. The protocol's `authorize` gains an optional journaled billing-start
      argument and `start_billing` takes `OperationKeys`.
      As built: `market_arkhai_payments.adapter.PaymentAdapter` is the one adapter;
      shared parts in `transaction.py` (`VerifiedSnapshots`, `record_descriptors`,
      `classify_failure`, `recorded_by`), rate behaviour in `rate_parts.py`
      (`RateParts`, renamed from `rate_adapter.py`; no adapter class), composed in
      when the mandate has a rate part. `RatePaymentAdapter`, `_allow_rate`,
      `operations_digest` and the class choices are gone. The protocol is
      `authorize(phase, evidence, billing: JournaledBillingStart | None = None)` and
      `start_billing(keys: OperationKeys, evidence)`; `OnceDeliveryPolicy`, the
      Alkahest adapter and end service follow. End service builds the keys over its
      own `SQLiteOperationStore` and passes the journaled billing start at disclosure
      only. Every pre-read is gone, the once reverse's too; D4's repeated-stop rule
      applies after the send. Tests: payments `test_payment_adapter.py` (unit: a mixed
      mandate, a once-only no-op billing start, once-only refusal of every rate
      command, a changed stop retry refused before any call, a seller stop answered
      by the payer's earlier winning stop), `test_rate_adapter.py` (unit);
      deal-lifecycle `test_adapters.py`, Alkahest `test_payment_adapter.py` (unit);
      servicing `test_end.py` (library integration, real SQLite: the billing keys'
      store refuses a changed digest; only disclosure receives the journaled billing
      start, with its key and recorded result).
- [x] 4A.2 Descriptor recording through the caller's operation store (D4): every
      monetary rate call (start, `start_billing`, stop, notice, reverse) requires
      `OperationKeys.store` and records each descriptor's digest with
      `check_and_record` under a part-derived key before any I/O; remove the
      `journaled_digest` parameter; keep `PaymentOperation` and `describe()` exported.
      Tests: a changed retry is refused before any authority call; an identical
      retry reuses its request identity.
      As built: the key is `keys.part_event(part, "<kind>-descriptor")`; a rate
      deal's operations refuse without a store. A once-only reverse records when a
      store is supplied (`submit_payment` always does) and otherwise relies on the
      authority's `request_id_reused`: the seller's refund
      (`PaymentSellerStage.reverse_now`) holds no store and calls the synchronous
      `submit_now`, which refuses a rate deal. Tests, unit: `test_rate_adapter.py`
      (changed reverse refused with no `reverse` call; identical start retry resends
      one request identity), `test_payment_adapter.py` (changed stop retry: no send,
      no read).
- [x] 4A.3 Stop requests stay distinct, wire-compatible (D10): the lifecycle `read`
      and `list` routes omit empty `parts` and null `settles_through`; minor-bump
      `kit/deal-lifecycle-contracts`; a test validates a once-deal read against the
      0.1.0 model. Add D10's requirement to the deal-lifecycle and
      settlement-servicing deltas.
      As built: `ReleasedReadShape` in the contracts drops
      `PaymentEvent.settles_through`, `AuthorityView.parts` and `DealSummary.parts`
      at their defaults when dumped (D10); contracts 0.1.0 → 0.2.0. Tests: contracts
      `test_released_reads.py` (unit, against `released_0_1_0.py`, a frozen copy of
      0.1.0's read and list models: a once-deal read and list validate, a 0.2.0
      reader restores them exactly, a rate observation is refused by 0.1.0). Deltas:
      deal-lifecycle "Stop requests are distinct from final stops, readable by
      released clients"; settlement-servicing "Rate stop requests are projected apart
      from final stops".
- [x] 4A.4 The staged `approval_window` rename, release N (D9): readers of
      `arkhai.payments.v1` option parameters accept `window` and `approval_window` as
      one term and refuse both; rate options write `approval_window`; once options keep
      writing `window`; the `arkhai_payments.approval_window` discovery field replaces
      the duplicate projection, `arkhai_payments.window` kept for once options. The
      alias carries a comment stating its invariant. Add the staged-rename rule to
      the versioning policy in the owner's wording, since moved with that policy to
      `docs/guidance/engineering/versioning.md` (design.md's promotion
      record), and one unowned gap row in `openspec/changes/README.md` for release
      N+1 (once writers switch) and N+2 (alias removed), joined by task 4B.2's
      `teardown` alias removal. A registry acceptance test proves rate options
      carrying `approval_window` pass the registry. Add D9 to the
      settlement-configuration delta.
      As built: `PaymentsOptionParams.one_approval_term` refuses a document giving
      both names a value (even agreeing); `approval_term` reads either; a null names
      neither, since VM publication dumps its validated clause input with the unset
      name as null. The once builder writes `window` whatever its clause named;
      `arkhai_payments.window` projects only for once options. No released document
      carried both (`approval_window` is new since `dev`). The gap row is under
      "Unowned work found by `spot-deals-through-arkhai-payments`", joined by 4B.2's
      alias removal. Tests: payments `test_approval_window.py` (unit); registry
      `test_listings.py::test_rate_option_naming_approval_window_round_trips`
      (application integration, through its typed client). Rate fixtures carrying
      both names corrected: payments `rate_terms.py`, VM `test_lifecycle_admin.py`,
      bare-metal `test_spot_notice.py`.
- [x] 4A.5 Kit-level tests (R19): the preset helper (setup, encoding, asset
      mismatch, beyond `tests/test_presets.py`); the watch's final-stop recording
      (`kit/deal-servicing`, unit); the composed adapter (a mixed mandate in one
      adapter, a once-only `start_billing` no-op); the alias; the 0.1.0
      compatibility. Add D11's requirement to the settlement-servicing delta.
      As built: `test_presets.py` gains encoding under the option identity with and
      without setup, `approval_window` written whichever name the clause used, the
      asset-mismatch refusal and the timing projection (unit). The watch's final-stop
      recording is `kit/deal-servicing/tests/integration/test_final_stop.py`, library
      integration since the watch persists through real SQLite (a pending request
      records no end; a maturity with no new sequence records once; a changed replay
      is refused). Deltas: settlement-servicing "One payments transaction adapter
      serves every part kind by composition"; deal-lifecycle's MODIFIED "Neutral
      delivery decisions delegate payment interpretation" for the protocol.

Validation: payments, servicing, lifecycle, contracts and buyer-half unit suites and
typing; both buyers' and both storefronts' suites (the adapter is constructed in
each); `make check-architecture`.

## Section 4A notes and handoff

- Versions, each one step from `dev`: `arkhai-kit-deal-lifecycle-contracts` 0.2.0,
  `arkhai-kit-deal-lifecycle` 0.4.0 (protocol), `arkhai-kit-arkhai-payments` 0.8.0
  (`RatePaymentAdapter` and `operations_digest` removed), `arkhai-kit-deal-servicing`
  0.3.0, `arkhai-kit-alkahest` 0.13.0. The bare-metal storefront's and buyer's exact
  `arkhai-payments` pins moved to 0.8.0; the VM storefront, VM buyer and compute
  delivery raised their bounds to it. Every package implementing or calling the
  protocol raised its bound to deal-lifecycle 0.4.0, and the composers of end service
  and the Alkahest adapter (both storefronts, compute delivery) to deal-servicing
  0.3.0 and Alkahest 0.13.0. Domain packages whose bounds moved keep their versions.
- The event projection rule (D10), whole-part reverse inference for every once part
  and refusal reasons beginning with the authority's code (D11) were decided here;
  the seller's refund classification matches the code.
- End-to-end scenarios exercising this section once deployed: the once-deal payment
  scenarios on the composed adapter's once path and the lifecycle read wire —
  `e2e_vm_payment_deal`, the six `e2e_vm_dispute_*`, `e2e_vm_payment_purchase`,
  `e2e_bare_metal_payment_deal`, `e2e_credits_payment_deal`. None exercises a rate
  deal; 4B.5 adds the recurring purchase. Owed by validation: none.
- `build-constraints.txt` at the repository root (the build-requirement pins every
  `uv build` reads through `UV_BUILD_CONSTRAINT`) is committed with this section,
  byte-identical to `dev`'s (`cd2506b76`), on the owner's direction: this branch's
  builds need it, and the merge sees two identical adds.
- Evidence: payments kit `make test` (mypy 29 files, vectors, generated models) 345;
  deal-lifecycle 82; contracts 40; servicing 74; Alkahest 465; buyer half 22; compute
  delivery 126; VM buyer 323; bare-metal buyer 68; bare-metal storefront 631; VM
  storefront 1194 unit (1 skipped) and 591 integration, after `test_spot_notice.py`
  was corrected to the new retry (two sends under one request identity, one recorded
  stop); registry round-trip tests 2; `make check-architecture` and `make
  check-comment-hygiene` pass. The payments first-use examples were not run here
  (6.6 ran them).
- The compliance check fixed: stale locks and unrun storefront suites; composers'
  lower bounds below the new protocol; two overstated `test_end.py` claims; planned
  behaviour and a version note in the deltas; decisions only in these notes (now
  D10 and D11); docstrings claiming recording for every operation; "still" in a
  comment; no test of the post-send repeated-stop rule (added); a test importing
  another module's private helper. Declined: moving the kit's tests into
  `unit/`/`integration/`, a whole-root restructuring recorded as an unowned gap row
  in `openspec/changes/README.md`; a route-level test of the read omission, since the
  routes dump these models and the model test proves the shape.

## 4B. Surfaces, fixtures and lanes

Tasks 4B.5 (the recurring-purchase E2E) and 4B.6 (the buyer's watchdog), unstarted,
were replanned against the reviewed design as sections 4E and 4F; 4B.1–4B.4 stand as
built.

Files: kit/deal-servicing (seller half), both storefronts' administrator routes and
typed admin clients, kit/deal-lifecycle-buyer, both buyers' end verbs and `buy`,
kit/arkhai-payments fixtures and a shared kit location for the preempt example,
`carried-tests/` and the modules it names, both compute lanes' E2E scenarios. Owner
record points R6, R11, R18, R20, R21 #48 and task 4.5a.

- [x] 4B.1 Administrator interrupt classification in kit (D6): move the kind-to-command
      classification (preemption → `notice`, refused without a payee entitlement;
      failure → end delivery and file `delivery_end`; the reason requirement) into
      `kit/deal-servicing`'s seller half; VM's route calls it; bare metal gains the
      route and its typed admin client. Tests at unit (kit classification) and
      application (bare metal's route). Name the capability owning bare metal's route
      and add the requirement to its delta and to deal-lifecycle's.
      As built: `market_deal_servicing.seller` gains `interrupt_command` (the pure
      classification, raising `InterruptRefused`, a `ValueError`, before any effect),
      `interrupt_operation_key` (derived from the request when the caller sends none,
      the digest VM's route derived) and `SellerServicing.interrupt` (the
      administrator evidence item under the operation's key, then notice, or the
      journaled operator end with filing and the injected `physical` drive side by
      side), returning `InterruptResult(kind, outcome, delivery)` with its
      `settlement_action`. A rate deal is recognised by `SellerDeal.once_only`, the
      committed projection (D15). VM's `VmDealLifecycle.interrupt` and route delegate
      to it. Bare metal gains `POST /api/v1/admin/deals/{negotiation_id}/interrupt`
      (payments deals only; 409 for another mechanism, 400 for a caller-supplied
      time) with `BareMetalInterruptDealRequest`/`Response`; the canonical
      `StorefrontClient.admin_interrupt_deal`, sync and async, already signs it and
      exposes kind and key, so it is bare metal's typed admin client unchanged.
      Deltas: compute-delivery "Both compute storefronts mount the administrator
      interrupt route"; deal-lifecycle's "Administrator interruption explicitly
      classifies its cause" names the kit classification and the attribution
      refusal, and its MODIFIED "Lifecycle routes are authenticated per role" defers
      to it. Tests: deal-servicing `tests/unit/test_interrupt.py` (unit: each kind,
      the once-only default, every refusal, the derived key); bare-metal storefront
      `tests/integration/test_admin_interrupt.py` (application integration through
      the canonical client: a preemption's dry run records nothing and its send
      leaves a pending stop, no end or filing; a failure records the operator end and
      journals a `delivery_end` filing, cause payee; a same-key retry changing the
      reason is 409; a caller-supplied time 400; an unclassifiable request 409,
      nothing recorded). Untested: the 409 for a non-payments deal (the harness
      composes no Alkahest deal). VM's `test_lifecycle_admin.py` passes unchanged.
- [x] 4B.2 The canonical `end` verb (D6a): `bare-metal end` joins `market end`,
      registered from shared buyer code; `bare-metal teardown` is a deprecated alias
      printing a notice naming `end` for one release (its removal joins task 4A.4's
      gap row); once-only end behaviour as `teardown` had it in v0.3.0 is preserved.
      As built: `market_deal_lifecycle_buyer.commands.register_end_command` registers
      `end` (and an optional deprecated alias) from an `EndTarget` the domain opens
      per run; `end_deal` ends, reads the delivery back once and polls to
      `--wait-timeout`; `end_exit_code` keeps VM's exit rule. Run options accept
      `--from`, `--run`, `--run-id` and `-r`; `--config` where the domain reads one
      (bare metal). Output is VM's shape (`progress`, `delivery_view`,
      `capacity_released`, `delivery_read_error`); both domains log `delivery_end`
      and `delivery_end_observed`. `bare-metal teardown` prints its notice on stderr
      and keeps the output its callers parse: progress alone on stdout, exit 0
      whatever the outcome. Additive beside v0.3.0: the progress's `mode` and `hint`,
      a `ValueError` exiting 2 through `BadParameter`, the alias's run-log events. A
      once-only end still goes through `BuyerLifecycle.end`, the `end_delivery`
      v0.3.0's `teardown` called. `arkhai-kit-deal-lifecycle-buyer` 0.1.0 → 0.2.0;
      both buyers and `e2e-tests` raised their bound. The e2e bare-metal purchase and
      real-host scenario run `end` and read `result["progress"]`;
      `RECOVERY_COMMANDS` names `end`. Deltas: buyer-orchestration MODIFIED "Compute
      buyers end delivery through the canonical lifecycle client";
      test-compatibility MODIFIED for the two bare-metal purchase requirements;
      deal-lifecycle's rate buyer end names the shared verb. `TESTING.md`,
      `e2e-tests/README.md`, `VALIDATION_RUNBOOK.md` and the kit README name `end`;
      the deal-lifecycle and buyer-orchestration companions are closeout's. Tests:
      buyer half `tests/unit/test_end_command.py` (unit: one read without a wait, a
      fake-time wait to release, an unavailable read, the exit rule, the alias's
      output and exit code); bare-metal buyer `test_rate_end_cli.py` (unit, both
      verbs through the `end_target` factory with a mocked lifecycle, the notice only
      on the alias); VM `test_rate_end_cli.py` unchanged; the bare-metal storefront's
      `test_the_buy_command_settles_over_a_run_log_a_later_command_reloads`
      (application integration, the real buyer CLI) runs `teardown` twice over a
      once-only deal through the real `end_target` and run log: the once-only end,
      the progress-only shape and exit 0. VM's test patches `end_context`, beneath
      its real `end_target`. No test reads the recorded run-log events back.
- [x] 4B.3 Fixtures on the shipped presets (D8): 4.4's fixtures use the shipped presets
      with default buyers under a lane declaration listing `returned`; the charged
      variant is a separate observation using the per-term waiver, not
      `allow_unprotected_terms`; move `preempt.py` and `preempt.lane.toml` from
      `domains/vms/storefront/examples` to a shared kit location, and update
      `docs/attachments/spot-deals-section-4/index.md`.
      As built: `kit/deal-servicing/examples/preempt_first_use.py` and its
      `preempt.lane.toml`, in the kit's `first-use` target. The declaration lists
      `charged` and `returned`: the shipped presets return on the payee's stop and at
      the term end, and the payer's stop charges its started period, which the check
      reads too. A default buyer approves both shipped options; the charged spot
      variant is refused by a default buyer and approved by one waiving
      `charged_term_end` and `charged_preemption`. A kit cannot import a domain, so
      the first use drives `SyncSellerLifecycleClient.notice`, which both `deals
      preempt` verbs delegate to; both CLIs' delegation stays proven by the VM
      storefront's `tests/integration/test_spot_notice.py`, which drives each
      domain's `deals preempt`. 6.1 moved the examples to `USD/6`. The
      `one_seller_stop` count was dropped, since 4A's identical retry resends.
      `arkhai-core-storefront-client` joins the kit's dev group (the seller client
      signs through it). Test:
      `kit/deal-servicing/tests/integration/test_preempt_first_use.py` (library
      integration: the entry point's `main` on its profile, real SQLite, in-process
      routes).
- [x] 4B.4 Restore the carried tests: every case in `carried-tests/` returns to the
      module its file names, each `recurring_world` reduced to the injected servicing
      declaration and the pool's delivery deadline (the helper, timing projection,
      billing projection and payments stage are the installed ones). Where a world's
      fixture helper encoded differently from the installed one, correct the restored
      assertion only to settled behaviour and raise anything else. Delete
      `carried-tests/` and the index row's sentence about the storefront tests it
      holds once empty.
      As built: `tests/recurring_world.py` returns to each storefront without its
      fixture helper, term timing, billing projection or accepted-data placeholder;
      each world supplies only what a deployment configures: the declaration (one
      mutable mapping behind one `RateServicing`, which publication, acceptance and
      the stage read), the pool's deadline and the penalty multiple. The VM world
      leaves `rate_preset_helpers` and `rate_term_projections` unset, so
      `VmSettlementComposition` installs `payments_rate_wiring`, and leaves
      `project_billing` to the registry's default. `VmSettlementComposition` builds
      no stage of its own (bare metal's does, in `__post_init__`), so the VM world
      builds it with `servicing_stage(..., rate_servicing=)`, the call
      `build_vm_settlement_composition` makes; no VM test would notice if the root
      stopped making it. Building the stage in VM's composition is a production
      change left for the round's review. `tests/publication_app.py` hands the
      composition's `arkhai_payments_stage` to the negotiation runtime, as
      `server.py` does. The VM world keeps `accepted_obligation_dispatch={payments:
      None}`, the composition's own entry (only contact exchange registers a
      builder). The bare-metal world sets `rate_preset_helpers=None` and
      `rate_term_projections=None` so `__post_init__` reinstalls the kit's wiring
      over the world's dispute policy (copied wiring would read the authorities of
      the policy it was built with).
      No restored assertion needed correcting: the installed helper writes
      `approval_window` where the fixture wrote `window`, changing option IDs and
      settlement bytes no case asserts. One input changed: the VM shape-priced case's
      `verify_pricing_acceptance` takes `buyer_settlement_registry().project_billing`
      for the fixture `billing`, and its carried comment that the installed
      projection refuses rate parameters was dropped (it projects a complete pair
      `per_period`). That case passes the helper's explicit-price check because
      publication composes the clause's rate from the family rates first, so the
      fixture's `SHAPE_RATE` fallback was never needed.
      Placement: VM `test_publication_loop.py` five cases and
      `test_buyer_selection_negotiation.py` three; bare-metal
      `test_http_publication_rates.py` four and `test_http_negotiation.py` two. Each
      restored deadline case replaces its module's once-only
      `test_a_once_payment_option_publishes_its_clause_s_deadline_where_the_pool_supplies_none`
      (it covers the once option too), with bare metal's payments fixtures that
      served only that test. The two
      `test_a_cached_rate_option_whose_treatment_is_withdrawn_is_refused_through_the_app`
      tests' docstrings no longer claim no mechanism publishes a rate option.
      `carried-tests/` and the index row's "Holds the storefront tests …" sentence
      are removed.
      Raised, not changed: those two seeded tests keep their database-seeded option
      (R6), though publication now reaches that state and each duplicates a restored
      case at the same level; removing them is the triage's call.
      Tests, application integration (each storefront app through its typed clients,
      real SQLite, the installed encoder and term timing): bare metal's restored cases
      reach publication and the selection door only (both its negotiation cases are
      refusals); the VM world also reaches acceptance in two buyer-selection cases and
      half the third. VM storefront integration 598 passed (was 591: nine restored
      items added, two parametrized once-deadline items removed); bare-metal
      storefront 641 passed (was 636: seven added, two removed); every restored item
      PASSED in the verbose output.

Validation: deal-servicing, buyer-half and both buyers' unit suites; both storefronts'
application suites.

## Section 4B notes and handoff

- On the owner's accepted split, 4B.1–4B.3 and 4B.4 were each committed on their
  own; 4B.5 and 4B.6 were replanned as sections 4E and 4F.
- End-to-end scenarios exercising 4B.4: none. It restores storefront tests and
  changes no deployed behaviour. Owed by validation: none.
- Evidence for 4B.4: the suites in its task note; `scripts/change-workflow run
  pre-commit` passed all three hooks, again after the compliance check's fixes (VM
  storefront integration 598, bare-metal storefront 641).
- 4B.4's compliance check found no blocking breach. Fixed: the VM world's docstring
  claiming the composition installs the stage and billing projection; a restored
  cached case comparing a row count where the carried case compared rows (rows
  again, with the carried `_negotiation_rows`); the shape-priced case's changed
  input and dropped comment, now disclosed; note claims broader than the tests
  (narrowed); the seeded tests' docstrings no longer claiming `TESTING.md`'s
  service-internal-setup exception (the tests kept per R6, raised for the triage);
  the VM stage built by the world, recorded as a production follow-up. Declined:
  folding the seeded tests' modules' duplicate payments constants and composition
  helpers into the world, which would rewrite tests R6 keeps unchanged.
- Running tests: a plain `uv run pytest` in a kit or the VM storefront relocks
  against PyPI's released internal packages (it rewrote the buyer half's lock to
  contracts 0.1.0) or fails to resolve. Use `make -C <package> test` (or
  `test-unit`/`test-integration`; the VM storefront's whole `test-integration`),
  after `make dist` when a kit changed; for the bare-metal storefront, `uv run
  pytest <files>` after `make -C domains/bare_metal/storefront reinit` works.
- End-to-end scenarios exercising 4B.1–4B.3 once deployed: `e2e_vm_payment_deal` and
  `e2e_vm_dispute_lost_filing` call the VM interrupt route, now over the kit
  classification; `e2e_bare_metal_payment_deal` and `e2e_bare_metal_qualification`
  end their purchases with `market bare-metal end` and read its `progress`;
  `e2e_bare_metal_deal`, which no lane selects (it needs a real host), recovers with
  `end` too. No lane scenario calls bare metal's new interrupt route or a rate deal.
  Owed by validation: none.
- Evidence for 4B.1–4B.3, after `make dist` and relocking: deal-servicing 86; buyer
  half 27; VM buyer 323; bare-metal buyer 71; VM storefront 1194 unit (1 skipped)
  and 591 integration; bare-metal storefront 636. `scripts/change-workflow run
  pre-commit` passed all three hooks; its first run had failed on the bare-metal
  storefront's buy-and-teardown test, which parses `teardown`'s progress-only output
  (the alias now keeps it), and on MODIFIED deltas missing permanent scenarios (now
  carried).
- 4B.5 returned the change to design: its premise, that the scenario observes
  delivery refused without the rate continuation, held nowhere in the code. Once a
  lane declared rate treatments, materialization, the storefront's settle, the shared
  path's authorization (`RateParts.authorize`) and end service's `start_billing`
  would deliver and start a recurring purchase, with no rate hook to refuse at; VM's
  `approve_rate` comment ("the installed delivery hook stays closed") described a
  fixture that skips delivery (corrected by 4C.5). Design settled the end-service
  door, the scenario's shape and its buyer-stop cleanup (D12–D16), with the options
  weighed there.
- `bare-metal-and-credits-domain-stacks` has a buyer-orchestration delta requiring
  `market bare-metal teardown --from <run_id>`; whichever of the two changes lands
  second reconciles it with `end` and the alias.
- 4B.1–4B.3's compliance check, declined: a third copy of the run-on-a-thread helper
  (`_run` in the buyer half beside each domain's `run_sync`), since moving the
  domains' other commands onto it is outside these tasks; bare metal's route
  answering 422 for VM's Alkahest payout fields, which it does not model, where VM
  answers 400; the canonical `admin_interrupt_deal` returning a dict, as every admin
  method of that client does; the first use's `market_core` and
  `market_settlement_runtime` arriving through the payments kit rather than the dev
  group.

## 4C. End service refuses a rate deal it cannot service

Delivers end service's refusal to commit a rate deal while it services no rate deals,
the refusal code that carries it and the repair reason the compute delivery path
reports (D12, D13, D14's code and reason, D15). Requirements: deal-lifecycle MODIFIED
"Neutral delivery decisions delegate payment interpretation" (its refusal paragraph,
"A rate deal is committed before rate servicing exists", "A once-only deal is
committed"); compute-delivery MODIFIED "Delivery is driven one deal at a time and
reports where it stands" and "Protected steps are authorized and admitted".

Files: kit/deal-lifecycle/src/market_deal_lifecycle/delivery.py
(`DeliveryAuthorization`) and its unit tests; kit/deal-servicing/src/market_deal_servicing/end.py
(`EndService.authorize_delivery`) and tests/integration (`test_end.py` or a new
`test_rate_refusal.py`), with any kit test or example that registers a `SellerDeal`
without `once_only` and drives a commit; domains/compute/delivery/src/compute_delivery/outcome.py
(`RepairReason`) and path.py (`_authorized`), tests/integration/test_drive_delivery.py;
both storefronts' recurring worlds and settlement tests for the application cases;
any storefront code matching or serializing `RepairReason`;
domains/vms/storefront/tests/integration/test_lifecycle_admin.py (`approve_rate`'s
comment); package versions per `docs/guidance/repository/package-versions.md`,
"Versioning policy".

- [x] 4C.1 The refusal code (D14): `DeliveryAuthorization` gains an optional closed
      `code` (`"rate_servicing_unavailable"`), absent by default. Every existing
      producer (the composed payments adapter, `OnceDeliveryPolicy`, Alkahest's once
      adapter, end service's own answers) leaves it absent. A journaled authorization
      acknowledgement recorded without the key still validates. Tests, unit in
      `kit/deal-lifecycle`: an answer without a code validates and omits nothing it
      carried; a stored acknowledgement without the key reads; an unknown code is
      refused. `arkhai-kit-deal-lifecycle` is already one step from `dev` (4A); bump
      only if the version-bump check asks.
      As built: `market_deal_lifecycle.delivery.RefusalCode` and
      `DeliveryAuthorization.code`. A codeless answer dumps without the key (a wrap
      serializer), because end service refuses a re-acknowledgement that differs from
      its journal, so an authorization journaled before this release must still
      compare equal. Tests: `kit/deal-lifecycle/tests/unit/test_delivery_authorization.py`
      (unit, 4 cases: the codeless dump equals its input; a stored acknowledgement
      without the key reads and re-dumps unchanged; a coded refusal round-trips; an
      unknown code is refused). `make -C kit/deal-lifecycle test` 86 passed (was 82).
      No version bump was needed.
- [x] 4C.2 The door (D12, D13, D15): `EndService.authorize_delivery`, for the commit
      phase only, reads the deal's committed seller projection
      (`SellerSession(conn).read`) before it asks the payment adapter. A projection
      that is not once-only (`SellerDeal.once_only`, `False` when unset) is refused
      with the code and the reason "rate servicing is not composed in this
      storefront"; a missing projection is refused with no code. Neither does I/O or
      calls the adapter, and both are journaled and acknowledged as every other
      authorization is, so the answer is durable with its operation identity. The
      refusal is unconditional: no seam, switch or injected servicer lifts it (D13).
      Its comment states the invariant locally — end service watches no rate deal's
      stops or funding, so a delivered rate deal would run unserviced — and points at
      `openspec/specs/deal-lifecycle/spec.md`, naming no change. Tests, library
      integration in `kit/deal-servicing` (real SQLite, a spy adapter): a rate
      projection's commit is refused with the code, the adapter is never called, and
      the refusal is journaled; a once-only projection's commit reaches the adapter
      and its answer carries no code; a missing projection is refused without the
      code. Kit tests and examples that register a `SellerDeal` without `once_only`
      and drive a commit set it.
      As built: for the commit phase, `EndService.authorize_delivery` reads the
      projection before the adapter-absent check and the adapter, and hands a refusal
      to `_authorize_delivery` in place of the adapter's answer, so it passes the same
      commitment and admission checks and is journaled under
      `<negotiation>:commit:<revision>` (`EndService._unserviceable` holds the rule
      and its comment). Admission overriding an answer (an end due, a stale revision)
      clears its code. The projection moved to `market_deal_servicing.projection`
      (`SellerDeal`, `read_seller_deal`), re-exported by `seller.py`, since
      `seller.py` imports `end.py` and `journal.py`, which both read it (a circular
      import otherwise); `SellerSession.read` delegates to it. The kit's rig and
      every example already registered `once_only=True`; none drives a commit. Tests:
      `kit/deal-servicing/tests/integration/test_rate_refusal.py` (library
      integration, real SQLite, a spy adapter): a projection never stating
      `once_only` is refused with the code, the adapter never called, the refusal the
      only journaled intent and a second ask answered alike; a once-only commit
      reaches the adapter and its journaled answer has no `code` key; a deal with no
      projection is refused without the code; dispatch is not refused at the door;
      admission overriding the refusal (an end due: "delivery ended"; a stale
      revision: pending) carries no code. `make -C kit/deal-servicing test` 92 passed
      (was 86).
      Outside the plan: VM's `delivery_records.register_delivery` registered every
      deal `once_only=True`; it now reads the mandate's parts for a payments deal, as
      bare metal's `register_agreement` and `VmDealLifecycle.register` did. The value
      was latent (VM registers payments deals through `VmDealLifecycle.register`
      first, and `register_delivery` returns early once a record exists); no test
      exercises the corrected branch.
- [x] 4C.3 The repair reason (D14): `RepairReason.RATE_SERVICING_UNAVAILABLE`
      (`"rate_servicing_unavailable"`); `_authorized` maps a refusal carrying the code,
      when no end is due, to `repair_required(rate_servicing_unavailable)` with the
      authorization's operation identity as its evidence reference; every other
      refusal keeps `no_accepted_deal`. Its docstring and the module docstring's
      account of reasons follow. Search both storefronts for code that matches or
      serializes the closed set and extend it. Tests, library integration in
      `domains/compute/delivery` (real end service and SQLite): a deal registered not
      once-only drives to `repair_required(rate_servicing_unavailable)`, the capacity
      fake records no reserve and no billing intent is journaled, and a second drive
      asks again with the same answer; a once-only deal drives as before.
      As built: `RepairReason.RATE_SERVICING_UNAVAILABLE`; `_authorized` maps the
      coded refusal, when no end is due, with the authorization's journaled identity
      as the outcome's `evidence_ref`; the docstrings say so. Neither storefront
      matches the closed set (both log `outcome.reason.value`). The rig's `register`
      registers the seller projection too (once-only by default), and the hosted
      once-only payment test registers its own, since a deal with no projection is
      refused. Tests: `domains/compute/delivery/tests/integration/test_drive_delivery.py`
      (library integration, real end service and SQLite):
      `test_a_rate_deal_end_service_cannot_service_waits_in_repair_with_nothing_reserved`
      (repair with the reason; no reservation, site call, adapter ask, billing intent
      or end; a second drive answers alike with one journaled authorization) and
      `test_a_once_only_deal_beside_a_refused_rate_deal_drives_as_before` (in one
      journal, the rate deal refused, then the once-only deal converges). `make -C
      domains/compute/delivery test` 128 passed (was 126).
- [x] 4C.4 The refusal through each served storefront (D12): one application-integration
      case per storefront, through its typed clients over real SQLite with the
      installed recurring wiring and a declaration listing `charged` and `returned`:
      a recurring deal is approved against the in-process payments engine and settled
      with its verified receipt, and its delivery is deferred — no capacity reserve,
      no fulfillment, no rate `start` at the engine. Extend the storefront's recurring
      world (VM `domains/vms/storefront/tests/recurring_world.py`, bare metal
      `domains/bare_metal/storefront/tests/recurring_world.py`), which 4B.4 left
      reaching acceptance on VM and publication on bare metal; where a world cannot
      reach settlement, extend it rather than seed the database (`TESTING.md`).
      As built, both through the buyer's typed client from publication to settlement,
      nothing seeded: the buyer negotiates the published on-demand option, its
      mandate is funded and approved at the in-process engine
      (`FakePaymentsClient.engine`), and the buyer settles. VM's world gains
      `settlement(world)`, composing the payments coordinator and deal lifecycle as
      `build_vm_settlement_composition` does, over the world's declaration, with the
      engine as the stage's client and site and provisioning doubles injected
      (`tests.delivery_fakes`), and mounting the settle routes; bare metal's world
      gains a `payments` parameter (`payments_client_for_owner`). "Installed
      recurring wiring" covers publication, acceptance and the stage's declaration.
      Tests, application integration: VM and bare metal
      `tests/integration/test_rate_delivery_refusal.py`, each
      `test_a_settled_recurring_deal_is_not_delivered_while_rate_servicing_is_not_composed`:
      the receipt verifies and the servicing record is committed; the journaled
      commit authorization is the coded refusal; no billing intent and no submit at
      the engine; VM's acceptance holds unchanged, none leased, its delivery record
      `provisioning` with no reservation or fulfillment; bare metal's settle answers
      `planning` and its fulfillment row is `planning` with neither. VM storefront
      1194 unit (1 skipped) and 599 integration passed (was 598); bare-metal
      storefront 642 (was 641).
- [x] 4C.5 Correction 3 of the design discussion: `approve_rate`'s comment in VM's
      `test_lifecycle_admin.py` states what its fixture does (it skips delivery), not
      an installed delivery hook.
      As built: the docstring says the fixture approves and registers the rate deal and
      marks it started in the delivery double without any drive, so the refusal is
      never reached there.
- [x] 4C.6 Verify: after `make dist`, `make -C kit/deal-lifecycle test-unit`,
      `make -C kit/deal-servicing test`, `make -C domains/compute/delivery test`,
      `make -C domains/vms/storefront test`, the bare-metal storefront's suite (after
      its `reinit`, as section 4B's notes say), each changed package's typecheck, then
      `scripts/change-workflow run pre-commit`. Record the counts and every new case
      by name in the section's notes.
      End-to-end: none exercises the refusal until section 4E. The once-only payment
      scenarios `e2e_vm_payment_deal`, `e2e_vm_payment_purchase` and
      `e2e_bare_metal_payment_deal` cross the changed commit authorization and must
      stay green; validation's pipeline reads them.
      Owed by validation: none.
      As built: `kit/deal-lifecycle` has no `test-unit` target (`test` ran its unit
      suite); counts are in each task's note. The typecheck was not run: `make -C
      kit/deal-servicing typecheck` was denied to the step, and the other packages
      have no target (round 2's triage made the kit's `test` run it; section 5's
      notes). `scripts/change-workflow run pre-commit` passed all three hooks, again
      after the compliance check's fixes. End-to-end confirmed: none exercises the
      refusal until section 4E; the once-only payment scenarios named above cross the
      changed commit authorization.

## Section 4C notes and handoff

- The compliance check found no layering, import, test-level or packaging breach.
  Fixed: the repair reason's docstring claiming a later drive commits (now "each
  drive asks end service again"); `projection.py` claiming admission reads the
  projection (4D's work); history wording in `DeliveryAuthorization`'s docstring;
  the bare-metal case passing vacuously on an absent fulfillment row and never
  reading the settle's answer (both asserted); the coded refusal through an
  admission override untested (two kit cases); the compute-delivery "beside it" case
  running alone (it drives a refused rate deal first); undisclosed run results and
  settle doubles; a private `_PAYMENTS_SERVICE` import (now the world's public
  `PAYMENTS_SERVICE`).
- For convergence, found by that check and not changed here: the refusal is
  journaled as a done authorization under `<negotiation>:commit:<revision>`, the
  identity the payments adapter and `OnceDeliveryPolicy` answer under. A storefront
  that later services the deal and answers allow at the same revision would be
  refused by `EndSession.acknowledge` ("completed intent cannot change"). D14's
  "delivers it on its next drive" assumes that cannot happen; convergence, which
  replaces the refusal (D13), decides how a refused deal's next commit is keyed.
- `EndSession.admit` has many callers (the compute delivery path, VM's
  `deal_lifecycle.py` and `failure_actions.py`, bare metal's `lifecycle.py`), so 4D's
  barrier sits inside `admit`.

## 4D. The deadline barrier

Delivers D14's "An earlier buyer stop wins over the deadline" (design review 18 F2):
for a deal that is not once-only, admission records the delivery-deadline end and its
filing only after a payment observation made at or after the deadline shows no
earlier lawful end, and both domains' recovery reads the payment authority before it
admits a missed deadline. Requirements: deal-lifecycle MODIFIED "Neutral delivery
decisions delegate payment interpretation" (its barrier paragraph, "A refused rate deal
passes its delivery deadline", "A buyer stops while the storefront is down", "The
payment authority is unreadable at the deadline"); compute-delivery MODIFIED "An
undelivered deal is handed to the end operation with classified evidence".

Files: kit/deal-servicing/src/market_deal_servicing/journal.py (`EndSession.admit`'s
missed-deadline branch, `_deadline_failure`), watch.py (`DealWatch` records the
instant of each successful payment observation), schema.py (the storefront chain's
migration, if the instant needs a column or table), seller.py (`SellerServicing.watch`
and `read`); domains/vms/storefront/src/market_storefront/deal_lifecycle.py (the
lifecycle cycle's `admit_deadline` and its order against `seller.watch`);
domains/bare_metal/storefront/src/arkhai_bare_metal_storefront/lifecycle.py (recovery's
order of `recover_delivery` against `seller.read`); their tests.

- [x] 4D.1 The payment observation instant (D14): `DealWatch` records, durably and in
      the transaction that journals what the observation showed, the storefront-clock
      instant of each successful verified payment observation of a deal, so a final
      stop the observation carried is recorded no later than its instant. A failed or
      unverifiable read records nothing. Use the storefront chain's migration
      (`market_deal_servicing.schema`) if a column or table is needed. Test, library
      integration: a successful poll records its instant with any final stop it
      carried; a failed read leaves the earlier instant.
      As built: a new table, `servicing_payment_observations` (negotiation,
      commitment, `observed_at`), written by `WatchSession.record_payment_observation`
      (keeping the latest instant) at the end of `DealWatch._observe`'s transaction,
      after every final stop the view carried, and read by
      `EndSession.payment_observed_at`. The instant is the watch's clock read before
      the read is sent. A non-accepted view returns before the transaction; a refused
      view (a `ValueError` inside it) rolls the instant back with everything else.
      The table is its own schema set (`PAYMENT_OBSERVATIONS_SCHEMA`,
      `create_payment_observations`, plain `CREATE TABLE`; D14), an ordinary
      migration appended to each chain (`20261115_001_vm_payment_observations`,
      `bare-metal-storefront-0019-payment-observations`); a database that already
      holds it fails it. The kit's rig, `test_filing_owner_recovery`'s rig, both kit
      examples and the compute-delivery rig apply it beside `create_schema`
      (`test_review_fix_a`'s rig, with no payment adapter, and VM's chain-migrated
      `fulfillment_fixtures` do not). Tests:
      `kit/deal-servicing/tests/integration/test_deadline_barrier.py` (library
      integration, real SQLite, a stand-in adapter):
      `test_a_successful_poll_records_the_instant_it_began_with_the_stop_it_carried`
      and `test_a_failed_or_refused_read_leaves_the_earlier_instant` (an `Unknown`
      read and a view changing a recorded stop); `test_servicing_schema.py`'s
      `test_a_table_added_since_is_its_own_set_that_tolerates_nothing`.
- [x] 4D.2 The barrier (D14): `EndSession.admit`'s missed-deadline branch, for a deal
      whose committed seller projection is not once-only, records the
      `delivery-deadline` end and journals its filing only when the latest recorded
      payment observation was made at or after the deadline; a lawful end selected
      effective at or before the deadline still wins, as today. Without such an
      observation it records nothing, files nothing and admits no protected phase;
      choose the `Admission` answer that says so and state the choice in the
      section's notes (any new status is internal to `kit/deal-servicing` and its one
      caller, the compute delivery path, which must then leave the deal where it is).
      A once-only deal, or one with no seller projection (no seller-half registration,
      so no payment watch observes it), keeps the released rule. Tests, library
      integration (real SQLite): the three delta scenarios — a deadline admitted after
      a post-deadline observation files seller non-delivery; a payer stop effective
      before the deadline and recorded by a post-deadline observation wins with no
      filing; with only pre-deadline observations, or an unreadable authority, nothing
      is recorded or filed and a later drive after a successful read admits the
      deadline — and a once-only deal past its deadline files as before.
      As built: `EndSession._deadline_unobserved` (with the rule's comment) holds the
      barrier, checked after the existing selected-end rule, so an end selected
      effective at or before the deadline still wins first. The answer is a new
      `Admission` status, `awaiting_observation`, at the unchanged revision (D14 and
      the deal-lifecycle delta, which modifies "Admission shares the end-service
      transaction and revision"). End service's `_authorize_delivery` keeps an answer
      that admits nothing (the coded commit refusal stays the journaled answer) and
      turns an allow into pending; the compute delivery path's first drive and
      activation answer pending (`ComputeDeliveryPath._not_admitted`, which also
      carries the stale-revision case); `available`, `begin_billing` and VM's
      `admit_delivery` already treat anything not admitted as such; other storefront
      callers ignore the answer. Tests, library integration in `kit/deal-servicing`
      (`test_deadline_barrier.py`, real SQLite):
      `test_a_deadline_admitted_after_a_post_deadline_observation_files_seller_non_delivery`,
      `test_a_payer_stop_before_the_deadline_recorded_after_it_wins_with_no_filing`,
      `test_without_a_post_deadline_observation_nothing_is_recorded_until_a_successful_read`,
      `test_a_once_only_deal_past_its_deadline_files_as_before`,
      `test_a_deal_with_no_seller_projection_keeps_the_deadline_rule`,
      `test_an_allow_is_pending_while_the_deadline_awaits_an_observation` and
      `test_the_coded_commit_refusal_stands_while_the_deadline_awaits_an_observation`;
      `make -C kit/deal-servicing test` 102 passed (was 92). In
      `domains/compute/delivery` (`test_drive_delivery.py`, library integration):
      `test_a_refused_rate_deal_past_its_deadline_stays_in_repair_until_a_payment_observation`
      (in repair with nothing recorded until an observation, then ended at the
      deadline with its filing, nothing reserved) and
      `test_a_rate_deal_first_driven_past_its_deadline_is_pending_with_nothing_begun`;
      130 passed (was 128).
- [x] 4D.3 Recovery reads the authority first (D14): VM's lifecycle cycle polls the
      payment watch before `admit_deadline`; bare metal's recovery reads the authority
      (`seller.read`) before `recover_delivery` admits; `SellerServicing.watch`
      dispatches no deadline filing journaled by its own poll before that poll
      completes. Confirm, with a test, that each domain's recovery reaches a refused
      rate deal after its deadline (VM's cycle admits every registered deal; bare
      metal's `recover_delivery` returns early unless the delivery progress is
      `unstarted` or `active`), and add the drive where one does not (D14, "Planning
      confirms …").
      As built: VM's `VmDealLifecycle.cycle` runs the seller watch first for each
      deal, then `admit_deadline`, and dispatches filings after the site corrections
      (`seller.dispatch_filings`), so a deadline filing dispatches in the cycle that
      journals it; no test observes that dispatch (the world has no dispute
      credential, so the filing reports repair). Bare metal's
      `BareMetalLifecycle.cycle` reads the authority (`seller.read`, for a verified
      commitment, `BareMetalLifecycle.committed`) before `recover_delivery`, and no
      longer after `reconcile_local`. `SellerServicing.watch` already dispatches
      filings before its poll: confirmed, unchanged. The barrier holds whatever the
      order; the order makes a missed deadline admitted in the cycle that observes it
      rather than a later one. Both recoveries reach a refused rate deal past its
      deadline (VM's `admit_deadline` admits every registered deal; bare metal's
      `recover_delivery` drives it, its progress `unstarted` while refused, and
      `reconcile_local` admits every committed deal). Bare metal's lifecycle clock is
      now injectable (`BareMetalStorefrontRuntime.lifecycle_clock`, wall time by
      default), as VM's already was. Test: 4D.4's second case in each storefront,
      `test_recovery_after_the_deadline_records_seller_non_delivery_for_a_refused_rate_deal`
      (application integration: one recovery cycle of the restarted app, through the
      admin client, records the deadline's seller non-delivery with its filing), the
      case that depends on the order; the buyer-stop case passes in either order.
- [x] 4D.4 The storefront down across the deadline: one application-integration case
      per storefront, through its typed clients and real SQLite with the in-process
      payments engine: a refused rate deal's buyer stops at the engine before the
      deadline while the storefront app is stopped, so no hint arrives; the app
      restarts after the deadline and its recovery runs; the deal's read shows the
      payer's end and no `delivery_end` filing is journaled. Build on 4C.4's worlds.
      As built, in each storefront's `tests/integration/test_rate_delivery_refusal.py`:
      `test_a_buyer_stop_while_the_storefront_is_down_wins_over_the_deadline_at_recovery`.
      4C.4's flow settles the refused deal and the world closes; the payer's stop is
      submitted at the engine (effective 60 s after the commitment, before the
      deadline); a new world opens over the same `tmp_path`, database and engine with
      its lifecycle clock 60 s past the deadline (VM `settlement(world, payments=,
      clock=)`; bare metal `recurring_world(..., clock=)`); recovery runs through the
      admin client (`admin_run_lifecycle_cycle`: VM `settlement-servicing`, bare
      metal `delivery-recovery`); the storefront reopens at wall time and the buyer's
      typed `LifecycleClient` read shows the payer's end at the stop's instant and no
      filings. The read cannot be made of the storefront whose clock runs past the
      deadline, since signed lifecycle requests and answers are refused beyond their
      allowed skew in both directions. VM's world composes an idle settlement worker
      (`_NoSettlementJobs`) so its servicing loop runs, mounts the lifecycle routes
      and opens the buyer's client; bare metal's world opens the buyer's client, and
      `test_publication_cycle.alkahest_publication` tolerates a restart. VM storefront
      1194 unit (1 skipped) and 601 integration passed (was 599); bare-metal
      storefront 644 (was 642).
- [x] 4D.5 compute-delivery's "An undelivered deal is handed to the end operation"
      names the site's refusal: confirm `path.py` sends an authorization refusal to
      repair and only a site refusal to `record_end`, and that no docstring says
      otherwise.
      As built: confirmed by reading. Every `_hand_off` follows a site refusal or an
      observed failure (reserve or commit refused, provisioning failed, the window
      elapsed, activation lapsed); `_authorized` sends a refusal to the end hand-off
      only when an end is due, otherwise to repair, and its docstring says so. No
      docstring changed.
- [x] 4D.6 Verify: after `make dist`, `make -C kit/deal-servicing test`,
      `make -C domains/compute/delivery test`, `make -C domains/vms/storefront test`,
      the bare-metal storefront's suite, typecheck of each changed package, then
      `scripts/change-workflow run pre-commit`; counts and new cases by name in the
      notes.
      End-to-end: no lane scenario crosses a delivery deadline; section 4E's scenarios
      end by the buyer's stop and hint before it. The once-only payment scenarios
      named in 4C.6 cross the changed recovery order and must stay green.
      Owed by validation: none.
      As built: counts and cases are in each task's note. The typecheck was not run
      (denied to the step, as in 4C.6). `scripts/change-workflow run pre-commit`
      passed all three hooks, again after each round of the compliance check's fixes.
      End-to-end, confirmed by reading, not by a run: no scenario crosses a delivery
      deadline; the once-only payment scenarios `e2e_vm_payment_deal`,
      `e2e_vm_payment_purchase` and `e2e_bare_metal_payment_deal` cross the changed
      recovery order and the new migration, and validation's pipeline runs them.

## Section 4D notes and handoff

- The compliance check (two runs) found no layering, import, comment-hygiene or
  packaging breach. Fixed: the new admission status contradicting the permanent
  admission requirement (the delta now modifies it) and, with the observation table,
  recorded only here (now D14 and its promotion row); restart cases reading through
  in-process objects (now the buyer's typed client); the stop case's comment claiming
  to show the recovery order; a dead dispute instant in `DealWatch.poll`;
  `_not_admitted`'s wording; the untested allow-to-pending branch (case added); the
  stale migration list in `docs/development/DEPLOYMENT_AND_CONFIG.md` and schema
  section of `kit/deal-servicing/README.md` (both updated); `_record_failure`'s and
  bare metal's `reconcile_local` comments ignoring the barrier's exception; the delta
  omitting that a deal with no seller projection keeps the deadline rule; note
  wordings. Declined: none.
- Outside the plan, from that check: bare metal's `reconcile_local` no longer
  records the term end while admission holds a deadline for a payment observation.
  The deadline is capped at the term end, so at equality a lawful terms end
  recorded during an authority outage would have been selected in place of seller
  non-delivery. Unreachable while every rate commit is refused and recovery reads
  the authority first; no test exercises it. Also outside the plan: bare metal's
  lifecycle clock became a runtime field (4D.3); production keeps wall time.
- `awaiting_observation` is internal to `kit/deal-servicing` and the compute
  delivery path; no storefront matches it (D14 records why not `retry` or `ended`).
- For convergence: under the barrier, end service turns an allow into pending at the
  same revision. A phase allowed and journaled before the deadline and asked again
  at the same revision after it would then be refused by `EndSession.acknowledge`
  ("completed intent cannot change"). No rate deal reaches an allow today, since
  every commit is refused; convergence, which lifts the refusal, decides how a
  re-asked phase under the barrier answers.
- The observation instant is the storefront's clock before the read is sent. A
  payments read checks no snapshot age (only rate `authorize` applies the freshness
  window), and the in-process engine's snapshot is read fresh, so the instant is a
  lower bound on what the authority had recorded. If a snapshot source ever serves
  a cached view, the instant should become the snapshot's own observation time
  checked against the storefront clock.
- Restarting a storefront in a test: open a second `recurring_world` over the same
  `tmp_path` (VM with `settlement(world, payments=, clock=)`; bare metal
  `recurring_world(tmp_path, payments=, clock=)`), passing the same
  `FakePaymentsClient`, which plays the payments service across the restart.

## 4E. The recurring-purchase E2E

Delivers one recurring purchase per compute lane through approval and commit, refused
at commit and ended by the buyer (D16, D8's E2E). Replans task 4B.5. Requirements:
test-compatibility "A recurring purchase runs end to end in each compute lane" ("A
buyer approves a recurring option", "The buyer's stop ends the refused deal", "Command
first use precedes continuation").

Files: two new scenario modules, `test_vm_recurring_purchase.py` beside the VM
scenarios and `test_bare_metal_recurring_purchase.py` beside the bare-metal ones
(e2e-tests/tests/e2e/roles/scenarios/), the shared buyer-purchase stages and drivers
they reuse; e2e-tests/pyproject.toml
(markers); e2e-tests/Makefile (each lane's `E2E_MODULE` selection); the compute lanes'
storefront configuration under e2e-tests/config and the local Helm values that carry
it; openspec/changes/README.md (the gap row).

- [x] 4E.1 The lane's recurring offer (D16 step 1): each compute lane's storefront
      configuration declares `[Settlement.rate_servicing.arkhai_payments] treatments =
      ["charged", "returned"]`, in the lane's configuration only, with a comment that
      it is a lane fixture and no shipped default. The seller publishes a recurring
      option — a bare-metal pool override, VM's listing creation — through a payments
      clause carrying `recurring: {period, reserve_ahead_seconds}`, its approval
      window leaving runway: approval window + delivery deadline + one period within
      `max_duration_seconds` (VM's purchase helper's `P7D` does not fit a one-hour
      listing). The shipped presets carry no setup charge.
      As built: the declaration, with its comment, is in
      `domains/vms/storefront/storefront.bob.lane.toml` (the VM lane's Bob) and
      `domains/bare_metal/storefront/storefront.dev.toml` (the bare-metal lane's
      storefront, also its development stack's; no other file mounts it). The local
      Helm values carry nothing: validation's Helm part selects no payment scenario
      (`HELM_SCENARIOS` in `scripts/validate_slice.py`), and `helm/local-values.yaml`
      says the release serves none. One clause builder serves both domains,
      `recurring_settlement` in
      `e2e-tests/tests/e2e/roles/helpers/recurring_purchase_stages.py`: USD 1.00 an
      hour, `recurring: {period: PT15M, reserve_ahead_seconds: 900}`,
      `approval_window: PT5M`, the lane's 300-second delivery deadline and the run's
      dispute coverage, no setup and no payee notice (the shipped on-demand preset).
      Runway 300 + 300 + 900 = 1500 s fits each listing's maximum (VM's listing 3600;
      bare metal's pool states none, so the lane's `default_max_duration_seconds`,
      86400) and each buyer's 3600-second request. A 900-second reserve ahead of a
      900-second period reserves one period, so 250000 USD/6 base units is the
      receipt's gross, the displayed initial reserve and the payer's drop;
      `Recurring04` asserts the gross a positive multiple of one period's price equal
      to the drop, `Recurring06` the displayed reserve equal to the gross; neither
      pins the count. VM's `VmRecurringPurchaseDriver.listing_settlement` and bare
      metal's `BareMetalRecurringPurchaseDriver.pool_settlement` return it (bare
      metal's purchase driver now builds its override's settlement there, unchanged
      for the payment deal). VM's listing has its own resource, host, pool and GPU
      model (`kvm-recurring-purchase`, `compute-e2e-recurring-purchase-pool`,
      `compute-e2e-recurring-purchase-001`, `RTX 4070`); bare metal's driver makes a
      per-run pool and machine. `e2e-tests/tests/unit/test_domain_stack_configuration.py`
      strips `rate_servicing` with the lane's other payments additions and asserts
      Bob's profile carries none.
- [x] 4E.2 VM scenario, marker `e2e_vm_recurring_purchase`, and bare-metal scenario,
      marker `e2e_bare_metal_recurring_purchase`, each through the shared purchase
      stages with the shipped `buy` and a default buyer (D16 steps 2–4):
      - asserts the published per-period price; the pre-approval display the buyer
        prints on stderr (`MarketRun.stderr()`: "Accepted price … per_period", "Setup
        once charge", "Initial reserve", "Maximum accepted end"); and the approved
        mandate's single rate part charging one period's price, from the payments
        double's records;
      - after commit, asserts the deal never becomes available, the site holds no
        reservation for it and the double records no rate `start`; asserts the repair
        reason only where a storefront interface already exposes it (4C's tests prove
        it otherwise);
      - ends the deal by the buyer's own `end` (the payer's stop and hint), asserts
        the payer's available balance restored, and asserts the seller's lifecycle
        read shows the payer's end and no `delivery_end` filing — the run does not
        wait for the delivery deadline (D16 step 4);
      - leaves no hold, mock rule or held loop, whether it passes or fails;
      - is labelled lane-double evidence in its marker description.
      Register both markers in `e2e-tests/pyproject.toml` and each lane's selection in
      `e2e-tests/Makefile`.
      As built: the stages are defined once in
      `e2e-tests/tests/e2e/roles/helpers/recurring_purchase_stages.py`, beside the
      clause builder, `check_recurring_option`, `RecurringPurchaseState`, the
      `RecurringPurchaseDriver` protocol (the purchase driver plus `servicing_loop`,
      `close_purchase_run` and `lifecycle_read`) and the cleanup. Both modules,
      `scenarios/vms/test_vm_recurring_purchase.py` and
      `scenarios/bare_metal/test_bare_metal_recurring_purchase.py`, declare the
      readiness stages, their listing stage (VM listing creation; bare metal a
      publication pass), `Purchase01`–`Purchase03` and then:
      - `Recurring04_MandateApproved`: from the run's events (`accepted_purchase`),
        the Agreement names the discovered listing and option; the mandate is exactly
        one `rate` part of 250000 USD/6 per `PT15M`; the double's snapshot and
        receipt verify against the trusted keys bound to that Agreement and mandate;
        the receipt's part reserves whole periods of that price; the payer's
        available fell by exactly the receipt's gross.
      - `Recurring05_CommitRefused`: after one step of the servicing loop (VM
        `settlement-servicing`, bare metal `delivery-recovery`), the buyer's
        lifecycle read names the committed transaction with progress not `active`, no
        end and no filing; the site lists no reservation for the negotiation but its
        acceptance hold, `<negotiation>:hold`, still `reserved` (VM's, where the lane
        sets a hold TTL; validation 58 V1); the double's part has no `started` and no
        `start` event. The repair reason is asserted nowhere: no storefront interface
        exposes it (both only log it), so 4C's library tests prove it.
      - `Recurring06` (renamed
        `test_r06_the_purchase_command_showed_the_accepted_money` by review 44 F3):
        the driver ends the purchase command — VM's `market buy`, still polling, is
        asserted to have polled, never read `ready` and recorded no end, then
        stopped; bare metal's ended at commit, successful with `run_ended` agreed and
        the machine still free — then its stderr holds the disclosure title and the
        rows `Accepted price: 250000 minor units of USD/6 per_period (PT15M, 900
        seconds)`, `Setup once charge: 0 minor units of USD/6`, `Initial reserve:
        <the receipt's gross> minor units of USD/6;` and `Maximum accepted end: <the
        Agreement's start plus its duration>`. That they precede approval is each
        buyer's own test. `MarketRun.stderr()` reads only an ended process, hence
        VM's stop first.
      - `Recurring07_BuyerEnds`: the canonical `end` (`market end --from`, `market
        bare-metal end --run-id`) exits 0 with progress `normal_stop` and payment
        `accepted`; the double's part is stopped with cause `payer`, never started,
        nothing held or reserved; the lifecycle read shows the end with cause `payer`
        and no filing.
      - `Recurring08_PayerBalanceRestored`: the payer's available equals what
        `Purchase01` read.
      The per-period price is asserted on the published option (Purchase02 runs
      `check_recurring_option`: period, reserve, approval window, no setup,
      `compute_rate_total` over one period equal to 250000, the on-demand
      entitlements, a positive penalty and the deadline). Cleanup
      (`recurring_purchase_cleanup`, plus bare metal's pool override removal) stops a
      running purchase command and, when the run log records an approved payment and
      `Recurring07` recorded no end, runs the buyer's `end`, resuming any stop
      `Recurring07` journaled. No mock rule is armed; the holds are the lane's module
      holds, released after cleanup. Both marker descriptions begin "Lane-double
      evidence"; VM's marker joins `E2E_MODULE`, bare metal's
      `E2E_BARE_METAL_MODULE`. `e2e-tests/tests/unit/test_recurring_purchase_stages.py`
      (unit, 9 cases, read from source) holds both modules to the stage order and
      checks every field a stage reads is written earlier and declared.
      `docs/development/TESTING.md` and `e2e-tests/README.md` describe the
      scenarios. `buyer_purchase_stages.py` gains the shared `accepted_purchase` (the
      body `Purchase04` had) and `available_balances` (its private `_available`,
      renamed). `e2e-tests/pyproject.toml` declares
      `arkhai-kit-deal-lifecycle-client` and `arkhai-kit-identity`, which the payment
      scenarios already imported undeclared.
- [x] 4E.3 Close the gap row "No end-to-end run produces a per-period Agreement …"
      under "Unowned work found by `negotiate-open-ended-compute-terms`" in
      `openspec/changes/README.md`: the scenarios produce a per-period Agreement and
      assert the money a buyer is shown and approves; convergence extends them
      through delivery.
      As built: the row is removed; its closure rests on validation's lane runs of
      the two scenarios, a failing run the triage's to weigh against reopening it.
- [x] 4E.4 Verify: `make -C e2e-tests test-unit`, collection of each marker in its
      lane's selection (the harness's collect-only run over `E2E_MODULE`), then
      `scripts/change-workflow run pre-commit`, whose `make check-repository` covers
      the new modules' hygiene. The lane runs are
      validation's, not this session's.
      End-to-end: `e2e_vm_recurring_purchase` (VM lane) and
      `e2e_bare_metal_recurring_purchase` (bare-metal lane), run by validation's
      compose lanes, its local Helm part and the pipeline; a lane unrun at closeout is
      a blocker, not a pass (D8).
      Owed by validation: none.
      As built: `make -C e2e-tests test-unit` 911 passed, 1 skipped (the new
      module's 9 cases, `test_scenario_cleanup_order.py` and `test_scenario_holds.py`
      over both new modules, and `test_scenario_lane_holds.py`, whose `--setup-plan`
      collects each lane's selection). Collection (`make -C e2e-tests test-module`,
      `PYTEST_ARGS=--collect-only`): the VM module's 17 stages under
      `docker,payments-lane,vms-lane`; the bare-metal lane's 115 items, the new
      module's 17 among them, under `docker,payments-lane,bare-metal-lane`.
      Pre-commit: the section's notes.
      End-to-end, corrected: the two markers run in the compose lanes and the
      pipeline only; the local Helm part selects no payment scenario.

## Section 4E notes and handoff

- The stages rest on, from reading the code: VM's listing creation publishing a
  recurring clause through the preset helper (wrong at first; 45 V1 below); the
  commit of a refused rate deal answered `Accepted` in both domains, so `market buy`
  records `settlement_submitted` and `market bare-metal buy` `run_ended` agreed; VM's
  settle status for it non-terminal, so `market buy` polls until stopped (a terminal
  `failed` would end it, which `close_purchase_run` reports); the buyer's hint making
  each storefront read the authority (`seller.read` in both `peer` calls), recording
  the payer's final stop, and the double stopping an unstarted rate part with zero
  payer notice at once and crediting the whole reservation back
  (`fixtures/authority.py`, `_stop`).
- Outside the plan: a payments purchase that ran out of its wait ended in an
  uncaught `TimeoutError` with no `run_ended`, in both buyers; recorded as an unowned
  gap row, then fixed in 4F and the row removed (section 4F notes). It is why VM's
  scenario stops `market buy` rather than letting a short `--settlement-timeout`
  end it.
- Pre-commit passed all three hooks, twice, the second after the compliance fixes
  (`make lock` relocked `e2e-tests/uv.lock` for the two declared dependencies; `make
  test` includes the bare-metal chart's render of `storefront.dev.toml` through its
  values schema); `make -C e2e-tests test-unit` 911 passed, 1 skipped, after the
  fixes too.
- The compliance check found no layering or comment-hygiene breach and no assertion
  the producing code would contradict. Fixed: 4E.2 left unchecked; the pre-commit
  evidence unrecorded; the VM lane test not holding the declaration to the lane;
  "still" in both configuration comments; `Recurring04` copying `Purchase04`'s
  correlation and `_available` (now shared); two imported distributions undeclared;
  import order in both drivers; overstated notes. Declined: reusing VM's
  `payment_deal.lifecycle_read` in `VmRecurringPurchaseDriver`, since it signs with a
  hard-coded `eip191` where the purchase profile reads the buyer's configured scheme,
  and importing it would pull a scenario module (`test_full_deal`) into a driver.
  Left for closeout: `openspec/specs/test-compatibility/architecture.md` says a
  purchase checks gross equal to the Agreement's price, which the recurring purchase
  does not.
- For convergence, which extends the scenarios through delivery: `Recurring05`
  then asserts the opposite, and `Recurring06`'s VM branch would see `ready`.
  The stage set is defined once, so it changes there.
- End-to-end scenarios exercising this section: `e2e_vm_recurring_purchase` (VM
  lane) and `e2e_bare_metal_recurring_purchase` (bare-metal lane). They also
  exercise sections 4A (the composed adapter's rate path, the stop request and
  final stop), 4B.2 (`bare-metal end`) and 4C (the refusal); none exercises 4D's
  barrier, since the payer's end precedes the deadline. Owed by validation: none.
- Round 2 triage fix, validation 45 V1: the first pipeline run (43728489504) failed
  VM's `e2e_vm_recurring_purchase` at stage 03: listing creation answered 400
  `invalid publication input for 'arkhai.payments.v1'`; bare metal passed. VM's
  listing derivation compiles a clause, replaces its mechanism input with the
  validated model's dump, then compiles it again; `PaymentsOptionParams`' `window`
  kept its `P7D` default beside a given `approval_window` (4A.4), so the dump named
  both and the second parse refused it (a VM once clause naming `approval_window`
  failed alike; bare metal parses its overrides once). Fixed in
  `kit/arkhai-payments/src/market_arkhai_payments/mandates.py`: a wrap serializer
  leaves `window` out of a dump when `approval_window` is set; every option writer
  already excluded `window`, so no option ID or once dump changes. Tests: payments
  `test_approval_window.py` (unit: a dump given `approval_window` validates again,
  python and JSON modes; one given `window` is unchanged); VM storefront
  `test_publication_loop.py::test_a_clause_naming_approval_window_publishes_through_listing_derivation`,
  once and recurring (application integration; with the serializer disabled it
  fails with the lane's message).
- Round 2 triage fix, review 44 F3: `Recurring06` asserted the disclosure's rows on
  stderr, not their order before approval, while its name and messages said "before
  approval". The order is proved at each buyer: bare metal's
  `test_cli_completion.py::test_the_accepted_agreement_is_shown_before_the_payment_is_approved`
  (unit: stderr lines and the settlement stage's call in one order); VM's
  `test_buy_orchestrator.py::test_the_accepted_agreement_is_shown_before_the_settlement_stage_pays`
  (unit), whose stage is Alkahest's escrow creation, so it proves `run_buy` enters
  the settle hook, whatever the stage, only after the negotiate hook's acceptance
  check disclosed. The stage is renamed
  `test_r06_the_purchase_command_showed_the_accepted_money`; its messages, the state
  field's comment, `TESTING.md`, `e2e-tests/README.md`, both marker descriptions,
  the test-compatibility delta's scenario and D16 claim only what it reads.
- Round 2 fix's triage fix, validation 58 V1: the pipeline (43748946611) failed VM's
  `Recurring05`: the site listed the negotiation's reservation `reserved` under
  `<negotiation>:hold`, VM's acceptance hold (the lane's Bob sets
  `capacity.hold_ttl_seconds = 900`), which end service's refusal before delivery
  leaves untouched to lapse at its TTL, as the compute-delivery delta and 4C's tests
  specify; bare metal places no acceptance hold and passed. The owner chose to
  correct the assertion rather than release the hold on refusal (D14). `Recurring05`
  asserts every reservation listed for the negotiation is its acceptance hold, still
  `reserved` (none placed under `:settlement`, committed or leased); its docstring,
  D14, D16 step 3, the test-compatibility delta's scenario, 4E.2's note, VM's marker
  description, `e2e-tests/README.md` and `TESTING.md` agree. No production code
  changed. Checks: `make -C e2e-tests test-unit` 911 passed, 1 skipped (unit);
  pre-commit passed all three hooks. The compliance check confirmed the assertion in
  both lanes (a committed hold turns `leased`; delivery's own reservation is keyed
  `:settlement`) and fixed wordings. Declined: admitting a hold that lapsed before
  the stage (`released`, `hold_expired`), since the lane reaches it within seconds
  of negotiation and the hold's TTL is 900 s.

## 4F. The buyer's watchdog

Delivers D6a's watchdog, its status resting on a fresh last probe (design review 18
F1). Replans task 4B.6. Requirement: deal-lifecycle's watchdog requirement, added
here. Tasks 4F.2 and 4F.5 were replanned after the section's first session found that
no rate deal reaches `available` while end service refuses its commit (D12, D13; the
section's notes): the loop is proven without a delivered deal, and the delivered-deal
cases move to convergence (D6a, D8).

Files: kit/deal-lifecycle-buyer (the probe loop, the per-deal opt-in, interval,
threshold and last-probe instant beside `BuyerEndJournal` in `FileEvidenceStore`'s
SQLite file, `store.py`; the status the buyer half composes beside
`BuyerLifecycle.read`; the shared deal-read registration in `commands.py`) and its
unit and integration tests; both buyers' `buy` commands
(domains/vms/buyer/src/arkhai_vms_buyer/buy_cli.py, the bare-metal buyer's `cli.py`
and `settlement_stages.py`), their per-domain probes, `end_target` openers and deal
reads; both buyers' suites; both storefronts' integration suites for the real-`buy`
cases; openspec/changes/spot-deals-through-arkhai-payments/specs/deal-lifecycle/spec.md;
openspec/changes/README.md (convergence's row).

- [x] 4F.1 The loop (D6a): a probe loop in `kit/deal-lifecycle-buyer` with a
      per-domain injected probe (the VM's or host's reachability on the disclosed
      address and credential kind; the kit learns no credential format). After
      `threshold` consecutive failed probes it sends the buyer's ordinary entitled stop
      and `hint` through the rate buyer end, journals the probe evidence it acted on,
      and exits; it exits also when the deal ends by another path or the buyer stops
      it. Defaults are conservative.
      As built: `watch_deal` in
      `kit/deal-lifecycle-buyer/src/market_deal_lifecycle_buyer/watchdog.py`. A probe
      is an async callable answering whether the access answered; an exception or one
      outlasting `probe_timeout_seconds` fails. At the threshold it journals a
      `WatchdogStop` (the failed probes with their instants), kept as a
      `watchdog_probe_failures` buyer-observation evidence item, then sends
      `BuyerLifecycle.end` (the rate buyer end), resent under its one key every
      interval until the payment outcome is accepted or rejected; a restarted loop
      sends nothing once the journaled end's payment is accepted or rejected and
      otherwise resumes that one end, with no probe (`BuyerEndJournal.read`, added).
      Probes start on a fixed schedule, one every interval from the loop's start. It
      refuses a once-only deal. `deal_ended`: the buyer's own end journal holds an
      end, the authority's read shows a final stop, or the storefront's read shows a
      recorded end or a release, each read independently. The buyer stops it with
      Ctrl-C. Defaults: interval 60 s, threshold 5, probe timeout 10 s (bound 310 s).
      `tcp_reachable` is the shared probe body (a TCP connect to the disclosed SSH
      endpoint; host and port only, no credential).
      Correction (4F.7): the ended-check, first run ahead of the probe, now runs
      beside it, each cut off at the probe timeout, which never exceeds the interval.
- [x] 4F.2 The commands (D6a): an opt-in flag on both domains' `buy`, which then stays
      in the foreground from `available` until the stop is sent, the deal ends or the
      buyer stops it; bare metal's `buy`, which returns at commit, polls the deal's
      delivery read until `available` (or its timeout) when the opt-in is given. The
      opt-in, interval and threshold are persisted per deal in the buyer's store; each
      domain's resume of a buy run (VM `market buy --from <run>`, through
      `_run_resume_from`; one added to bare metal's `buy`, which has none) re-enters
      the loop where the deal still runs. The display states the conditional bound
      `interval × threshold + probe timeout`, only while the monitor runs. The deal
      read (D6a): register a shared read verb from the buyer half beside
      `register_end_command`, opening the run's deal through the domain's `end_target`
      seam; VM gains `market delivery --run`, and bare metal's `delivery --run-id`
      moves onto the registration, keeping its options and output with the status
      added. Each domain's resume and read accept the run spellings `end` accepts.
      As built: the buyer half's `commands.py` gives both domains `--watchdog`,
      `--watchdog-interval` and `--watchdog-threshold`, `run_monitor` (opens the
      run's deal through the domain's seam, refuses a once-only deal, prints
      `bound_notice` only when the loop starts, logs `watchdog_started`/
      `watchdog_exited`, runs the loop on the main thread so Ctrl-C reaches it),
      `wait_until_available` (bare metal's poll until progress `active`),
      `register_read_command` and `RUN_SPELLINGS` (`--from`, `--run`, `--run-id`,
      `-r`, also `end`'s). `WatchdogJournal` (table `buyer_watchdogs`) sits beside
      `BuyerEndJournal` in `FileEvidenceStore`'s file, which deletes its row with the
      deal's evidence; `BuyerLifecycle` takes it as `watchdog=` from both
      compositions (`store.watchdog`).
      VM (`buy_cli.py`): the opt-in is persisted at the payments settle hook's
      `payment_approved` event, before commit; after `ready`, `_watch` runs the
      monitor for an opted-in deal, its probe built from `connection_details`;
      `--from` (also `--run`, `--run-id`, `-r`) re-enters it after settling;
      `--watchdog` with `--from` is refused, since the resume uses the persisted
      opt-in. Seams: `watchdog_journal`, `watchdog_target`, `watchdog_probe`.
      `end_cli.py` registers `market delivery`.
      Bare metal (`cli.py`): the opt-in is persisted before approval; after commit the
      purchase JSON prints, then `_deliver_and_watch` polls until available or
      `--delivery-timeout-seconds` (default 600, `--poll-interval` 5), prints a
      second JSON line (`available`, `watchdog`) and exits 4 if never available.
      `buy --from <run>` (listing, `--option-id` and `--ssh-public-key` now required
      only for a new purchase) re-enters the wait and monitor of a committed run that
      opted in, and prints `watchdog: null` for one that never did. The probe reads
      the host's access once when the monitor starts, so a storefront outage never
      reads as the host's loss. Seams: `end_target`, `watchdog_journal`,
      `watchdog_probe`. `delivery` moved onto `register_read_command` with `--run-id`
      and `--config`; `_lifecycle_for_run` is removed.
- [x] 4F.3 The status (D6a, design review 18 F1): every probe, passed or failed,
      records its instant per deal beside the opt-in. The buyer's read shows
      `monitored` while `now − last probe ≤ interval + probe timeout` plus a small
      fixed grace, `stopped` once the watchdog journaled its stop, and `unmonitored`
      otherwise, a deal never opted in included. The buyer half computes it when it
      composes the buyer's read; it is no field of `LifecycleRead` or any lifecycle
      wire model, and the storefront neither sees nor reports it.
      As built: `watchdog_status` and `watchdog_view` in `watchdog.py` (grace
      `GRACE_SECONDS = 5`); `BuyerLifecycle.buyer_read` returns the lifecycle read's
      JSON with `"watchdog": {"status", "last_probe_at"}` beside it, which the
      shared read verb prints. `LifecycleRead` and the wire models are unchanged.
- [x] 4F.4 The requirement: add D6a's watchdog, with the status rule, to the
      deal-lifecycle delta as an ADDED requirement with scenarios for the threshold
      stop, the stale last probe and the restart.
      As built: "The buyer's watchdog bounds detection only while it runs", with
      scenarios "The threshold of failed probes is reached", "The last probe is
      stale" and "A restarted run resumes the watchdog". `watchdog.py`'s module
      docstring cites it by that heading.
- [x] 4F.5 Verify, without a delivered deal (D6a):
      - unit, in the buyer half with a clock-injected probe fake: threshold reached, no
        stop below it, one stop and one journal entry at it, idempotent on restart, and
        `unmonitored` once the last probe is older than `interval + probe timeout` plus
        the grace;
      - library integration, one per domain buyer: the domain's real buyer lifecycle
        composition with the composed payments adapter over the in-process payments
        engine (`FakePaymentsClient`'s engine) and an approved rate mandate, the
        storefront peer unreachable and an injected probe failing: exactly one payer
        stop at the engine, one journaled stop with its probe evidence, and a restarted
        loop that sends nothing more;
      - CLI cases in each buyer's suite over the injected lifecycle and probe seams
        `test_rate_end_cli.py` uses (unit, as 4B.2 levelled those): the opt-in flag,
        its interval and threshold persisted per deal, the resume re-entering the loop,
        the bound shown only while the monitor runs, and the read's `monitored`,
        `unmonitored` and `stopped` after a kill and a resume;
      - application integration, one per storefront in its integration suite beside
        the existing real-buyer-CLI test: the real `buy` with the opt-in against the
        composed storefront on a recurring option, whose commit end service refuses;
        the opt-in is persisted, no probe runs and no stop is sent, the command exits
        at its timeout, and the deal read shows `unmonitored` — the opt-in alone never
        reads as protection.
      Then both buyers' suites, the buyer half's, typecheck,
      `scripts/change-workflow run pre-commit`.
      End-to-end: none; no lane scenario runs `buy` with the opt-in, and none is owed
      here.
      Owed by validation: none.
      As built, each in fake time (a probe raising `TimeoutError` stands for one the
      bounded wait cut off; the commands' waits run on an injected `WaitClock`):
      - unit, `kit/deal-lifecycle-buyer/tests/unit/test_watchdog.py` (15 cases, the
        lifecycle and journal doubled): one stop and three journaled probes at the
        threshold; a passing probe resets the count; probes on the fixed schedule
        however long each takes; a stop not landed resent every interval;
        `deal_ended` from the buyer's own end and an authority final stop, not from a
        running authority with the storefront down; `tcp_reachable` against a
        loopback listener and a closed port; a timed-out probe fails; a restart after
        a landed stop sends and probes nothing, one before it resumes that stop; a
        once-only deal refused; the status rule at the freshness edge; the bound;
        `run_monitor` stating the bound (with the acknowledgement and priced notice)
        only when the loop starts; the interrupt's message before and after the stop
        is journaled; a journaled stop resumed with no probe and no bound. Library
        integration, `tests/integration/test_watchdog_journal.py`: the opt-in, probe
        instant and first stop survive a reopen of the SQLite file; the read shows
        each status; a repeated opt-in keeps the stop; the deal's deletion removes the
        row. Buyer half: 43 passed.
      - library integration, `test_watchdog_rate_stop.py` in each buyer: the domain's
        `buyer_lifecycle` with the composed adapter over `FakePaymentsClient`'s
        engine holding a mandate approved at the engine's clock (the fake's own
        `approve` signs at a fixed 2027 instant, past the deal's term), the
        storefront on the discard port, a probe raising `ConnectionRefusedError`: one
        `submit_event`, the unstarted rate part stopped with cause `payer`, the hint
        `unknown`, the three probes journaled and kept as evidence, and a restarted
        loop that probes and sends nothing more.
      - CLI cases, unit, over each command module's seams. Bare metal,
        `domains/bare_metal/buyer/tests/test_watchdog_cli.py` (7 cases): `buy --from`
        re-enters the loop and states the bound; a deal never available waits out its
        timeout (7 reads over 30 s) with no bound, probe or stop; a journaled stop is
        carried with the storefront unreadable, no wait and no probe; an ended deal
        reports `ended`, exit 0; a run never opted in runs nothing; a resume naming a
        listing is refused; the read through the real `BuyerLifecycle.buyer_read`
        shows `unmonitored` before and after the opt-in, `monitored` after a resumed
        loop's passing probe, `unmonitored` once it is stale and `stopped` after a
        resumed loop stops. `test_run_log_recovery.py` gains the fresh `buy
        --watchdog --watchdog-interval 7 --watchdog-threshold 2`: the settings
        persisted before `payment_approved`, exit 4 at the delivery timeout, no probe,
        no bound. VM, `TestBuyWatchdog` in
        `domains/vms/buyer/tests/test_buy_resume_cli.py` (7 cases): the fresh opt-in
        persisted with the bound shown and the loop exiting when the deal ends by
        another path; a run not ready keeps its opt-in and opens nothing; no opt-in,
        nothing persisted; `buy --run-id` re-enters and stops; `--watchdog` with
        `--from` refused; the real probe factory over a disclosed endpoint and its
        refusal of a delivery naming none; a journaled stop carried with no settle or
        probe; the `market delivery --run` read sequence. They replace only
        `buy_cli`'s factories (`buy_orchestration`, `settle_resumption` and
        `run_negotiation_id` added). Not covered by a test: bare metal's real
        `watchdog_probe` factory (an `access` read, then `tcp_reachable`) and VM's
        payments resume ending `timeout` (`PaymentsBuyerStage.resume` has no seam
        short of patching its imports).
      - application integration, `tests/integration/test_watchdog_buy.py` in each
        storefront: the real `buy --watchdog` against the composed storefront on
        loopback, on the published on-demand option, approving at the shared engine:
        the commit is accepted and the deal never reads `active` (bare metal:
        purchase JSON `committed`, then `available: false`; VM: settle status
        `provisioning`); exit 4 at the timeout (bare metal's delivery wait in fake
        time through `wait_clock`; VM's `--settlement-timeout 0`); no "Watchdog
        running", no `submit_event`, the opt-in journaled with no probe or stop, and
        the read `unmonitored`. The refusal's code is asserted only by 4C's library
        tests. Bare metal's `recurring_world` gains `serve=True` (uvicorn's lifespan,
        clients over the port); VM's runs uvicorn on the test's own loop
        (`loopback.served`), since a thread's loop closes before the world's teardown
        awaits the storefront's delivery task. VM's replaces identity, registry
        discovery, core's `fetch_listing_dict` and `payment_buyer` by name, as its
        docstring lists.
      Suites: buyer half 43; VM buyer 331; bare-metal buyer 81; the storefronts' in
      pre-commit's `make test` (section notes). No typecheck target exists for these
      packages.
- [x] 4F.6 Transfer (D6a, D8): the delivered-deal cases — the real `buy` with the
      opt-in from `available`, access lost with the storefront stopped yielding a
      single buyer stop, a killed command reading `unmonitored` once its last probe
      goes stale, the resumed run reading `monitored` — are convergence's, beside its
      rows 1 and 2. Name them in `converge-ongoing-compute-leases`' row Notes in
      `openspec/changes/README.md`; closeout's 7.8 records the transfer.
      As built: named in that row's Notes.
- [x] 4F.7 Narrow the stated bound (D6a, design review 35 F2; deal-lifecycle's
      watchdog requirement, "the one failure it covers"). Wherever the watchdog's
      bound is stated, it covers one failure, the deal's disclosed SSH endpoint no
      longer accepting connections, and detection runs from that loss, not from a
      "lost resource", "lost VM" or "lost host". The probes already test only that
      reachability and use no credential, so no probe changes. Files:
      `kit/deal-lifecycle-buyer/src/market_deal_lifecycle_buyer/commands.py`
      (`watchdog_option`'s help and `bound_notice`), `watchdog.py`'s module docstring,
      `domains/vms/buyer/src/arkhai_vms_buyer/buy_cli.py`'s module docstring, and the
      bare-metal buyer's `cli.py` `buy` docstring; any test asserting the notice's text.
      Verify: `kit/deal-lifecycle-buyer`'s unit suite and both buyers' suites (unit),
      with a unit case asserting `bound_notice` names the endpoint accepting
      connections and states the bound only while the command runs.
      End-to-end: none exercises the watchdog (4F.6 moved the delivered-deal cases to
      convergence). Owed by validation: none.
      As built: every statement of the bound — `watchdog_option`'s help,
      `bound_notice`, `watchdog.py`'s module docstring (which adds that an endpoint
      accepting connections while the workload or login fails passes every probe),
      `WatchdogSettings.bound_seconds`'s docstring, VM `buy_cli.py`'s module
      docstring, bare metal's `buy` docstring and, beyond the named files,
      `docs/development/ROADMAP.md`'s accepted-limitations paragraph — names the
      disclosed SSH endpoint ceasing to accept connections and counts detection from
      that loss; `watch_deal`'s docstring and `Probe`'s comment say "SSH endpoint".
      `buyer_terms.py`'s honest-crash acknowledgement states no bound and is
      unchanged.
      Outside the plan, a defect in 4F.1's loop that made the bound false, found by
      the compliance check: each round ran the ended-check before the probe, each cut
      off at the probe timeout, so a hanging storefront read delayed every probe
      (detection up to `interval × threshold + 2 × probe timeout`), and an interval
      shorter than the timeout ran rounds back to back. Now the ended-check runs
      beside the probe (`asyncio.gather`); `WatchdogSettings` refuses a probe timeout
      longer than its interval; the opt-in (`watchdog_settings`) shortens the
      10-second default to a shorter interval, which `--watchdog-interval`'s help
      states. A round in which the deal has ended also runs its probe, discarded and
      not recorded. The rule is in D6a, the delta's watchdog requirement and the
      promotion record's watchdog row.
      Unit, `kit/deal-lifecycle-buyer/tests/unit/test_watchdog.py`:
      `test_the_stated_bound_covers_the_ssh_endpoint_accepting_connections_only_while_the_command_runs`
      (the endpoint named, the bound's value, "only while this command runs"),
      `test_the_opt_in_shortens_the_probe_timeout_to_an_interval_below_it`,
      `test_the_ended_check_runs_beside_the_probe_never_ahead_of_it` (an ended-check
      that yields once sees the probe already started, every round; no test drives a
      read to its timeout, so a hanging read's cutoff is `asyncio.wait_for`'s, not
      shown here); the bound test refuses `WatchdogSettings(7, 2, 10)`. VM's
      `TestBuyWatchdog` fresh opt-in expects the persisted (7, 2, 7), "at most 21
      seconds" and the ended round's one discarded probe; the domain suites assert
      only notice fragments ("at most N seconds", "only while this command runs").
      Buyer half 46 passed; after `make dist`, VM buyer 331 and bare-metal buyer 81
      (unit).

## Section 4F notes and handoff

- Returned to planning before any code was written: 4F.5's application cases
  expected the real `buy` to run the loop from `available` and probe the disclosed
  access, which no rate deal reaches while end service refuses its commit (D12,
  D13: VM's settle stays `provisioning`, bare metal's `buy` returns at commit, and
  disclosure needs a verified rate `start`), and the watchdog is rate-only by D6a's
  purpose. Planning amended 4F.2, 4F.5 and 4F.6, moving the delivered-deal cases to
  convergence (D6a). Rejected then: letting the watchdog apply to once-only payment
  deals, which do reach `available`, since `BuyerLifecycle.end` surrenders and files
  a case there, outside D6a's purpose; and a test-only storefront composition that
  skips the refusal, since D13 allows no seam and such a case would not run against
  the composed storefront.
- 4F.7: the wording correction, and outside the plan the loop fix that makes the
  corrected bound hold (4F.7's note). No probe body or status rule changed.
  End-to-end scenarios exercising it: none (4F.6). Owed by validation: none.
- Limits of the bound left as they are, from 4F.7's second compliance check: where
  the probe timeout equals the interval (every interval of 10 s or less), a round
  whose probe times out lasts the interval plus milliseconds of scheduling and the
  probe instant's SQLite commit, which can accumulate over consecutive timed-out
  rounds, beneath the whole seconds the bound is stated in. And the loop's
  synchronous SQLite reads and writes (`deal_ended`'s `end_journal.read`,
  `record_probe`) are not cut off: a lock another process holds on the buyer's store
  can delay a probe's start by up to SQLite's 30-second busy timeout. Either errs
  toward `unmonitored`, never a false `monitored`. Convergence, which first runs the
  watchdog against delivered deals, is where a tighter schedule would be planned.
- Outside the plan, fixed and recorded here: a payments purchase that ran out of its
  wait ended in an uncaught `TimeoutError` (the unowned gap row 4E recorded, now
  removed from `openspec/changes/README.md`). VM's payments settle hook
  (`arkhai_payments.py`) ends the run `timeout`, exit 4, as its Alkahest hook does;
  VM's payments resume (`PaymentsBuyerStage.resume`) ends it `timeout`, exit 7, its
  not-ready exit; bare metal's `buy` ends its commit wait `timeout`, exit 4
  (`UNAVAILABLE_EXIT_CODE`). The VM storefront case relies on the first and
  `test_run_log_recovery.py` covers the bare-metal commit; no test covers VM's
  resume. VM's payments settle keeps the lifecycle client's own per-request timeout
  rather than its whole wait (as bare metal's takes its configured one), so a wait
  nearly spent still sends its commit. `buyer_commands.BuyerCommands` sets
  `ARKHAI_BUYER_PROFILE_STORE` under the test's directory, so the bare-metal
  storefront's buyer-command tests keep no evidence under the real home directory.
- Seams added for fake time: the buyer half's `WaitClock` (`now`, `monotonic`,
  `sleep`), taken by `run_monitor` and `wait_until_available` and built by each buyer
  command through `wait_clock()`; bare metal's `PaymentStage.settle` takes it for the
  commit loop. VM's settle poll (core's `wait_for_settlement`) has no clock seam, so
  the VM storefront case asks for a deadline of now.
- A resume carries a journaled stop before anything else: VM's `buy --from` checks
  for one (`_carry_journaled_stop`, through the `run_negotiation_id` factory) before
  settling, and bare metal's before its availability wait, since a settle, a wait or
  a probe would each need the storefront the watchdog exists to outlast.
- For convergence, which runs the watchdog from `available`: the probe in each domain
  is a TCP connect to the disclosed SSH endpoint (VM's `connection_details`, bare
  metal's `access` read once at the monitor's start). `deal_ended` reads the buyer's
  end journal, the payment authority and the storefront each interval, which the
  lane double serves.
  VM's `_watch` runs only after `ready`, so a VM deal that becomes available after
  `buy` gave up is monitored only by `buy --from`.
- Left for closeout: `watchdog.py`'s module docstring cites deal-lifecycle's "The
  buyer's watchdog bounds detection only while it runs", which resolves once the
  delta archives; promotion of D6a's watchdog (the promotion record's row) to
  `deal-lifecycle` `spec.md` and `buyer-orchestration` `architecture.md`; and the
  buyer documentation of `--watchdog`, `buy --from` on bare metal and `market
  delivery`.
- Compliance checks, two over the implementation and two over 4F.7. Fixed: a resume
  skipping a journaled stop while the storefront is down; real waits in tests (now
  fake time or a deadline of now); unrecorded outside-plan fixes and VM's resume
  still raising `TimeoutError`; the resumed loop's `monitored` untested;
  `arkhai-kit-deal-lifecycle-buyer` undeclared in both storefronts' dev groups; the
  bound text missing acknowledgement and priced notice, and the help missing the
  bound; the interrupt message claiming nothing was sent after a journaled stop;
  probes spaced by interval plus probe and read time (now the fixed schedule); a
  stop not landed ending the loop (now resent until it lands); untested paths
  (`tcp_reachable`, VM's probe factory, the interrupt messages, `deal_ended`'s
  branches); VM's cases patching imported names (now `buy_cli` factories,
  `run_buy` and `run_settle_from_log` included); `wait_clock` missing from
  TESTING's list; the storefront cases' claim that they observe the refusal; a
  resume of an ended deal reporting it never available (now `ended`, exit 0); a
  resume ignoring purchase options it now refuses (`--duration-seconds` with the
  rest); for 4F.7, the loop defect, the probe-timeout rule without a home (now D6a,
  the delta and the promotion record), statements of the bound short of "disclosed
  SSH endpoint", ROADMAP's statement, a test name overstating the concurrency test
  and a passing-probe case relying on a swallowed `IndexError`; and comment, docstring
  and note wordings. Declined: calling `BuyerLifecycle._deal` from the watchdog
  (`ending.py` already does within the package); splitting the buyer packages' flat
  test roots, since TESTING's "Test File Layout" binds services and kit libraries,
  and a domain buyer package is neither; the VM storefront case's replacements in
  core and other modules, which its docstring states with ROADMAP's gap; the
  citation to the delta's heading (closeout's); the millisecond overrun and uncut
  SQLite calls (the limits above).
- Pre-commit: the final runs for the implementation and for 4F.7 passed all three
  hooks (`make test`: buyer half 46, VM buyer 331, bare-metal buyer 81, VM storefront
  integration 602 and bare-metal storefront 645, each storefront with its
  `test_watchdog_buy.py`). Earlier runs failed only VM's storefront case (its zero
  settle timeout also cut off the commit's transport, fixed) and history wording.
- End-to-end scenarios exercising this section: none; no lane scenario runs `buy`
  with `--watchdog`, and convergence owns the delivered-deal cases (4F.6). The
  recurring-purchase scenarios still exercise `market bare-metal end` and `market end`,
  which now share `RUN_SPELLINGS`. Owed by validation: none.
- Round 2 triage fix, review 44 F1: a stop the payment authority refused
  (`Rejected`, final under its operation key: `end_rate` never resubmits it) ended
  the loop as `stopped`; bare metal's `buy` printed `"watchdog": "stopped"` and
  exited 0. Now `WatchdogOutcome.of_stop` gives a `rejected` reason, fresh or
  resumed; `run_monitor` says the authority refused the stop, gives its reason, says
  the deal is not stopped and billing continues, and names `end
  --end-now-regardless` without taking it; both `buy` commands exit
  `WATCHDOG_REJECTED_EXIT_CODE` (1), as `end` does on a stop not accepted (VM's
  `_exit_on_refused_stop` in `buy_cli.py`, bare metal's in `cli.py`, its JSON
  reporting `"rejected"`). The read keeps `stopped` (journaled) beside the payment
  state (D6a); the deal-lifecycle delta gains the read's meaning of `stopped` and the
  scenario "The payment authority refuses the watchdog's stop". Tests (unit): buyer
  half `test_watchdog.py` (a refused stop `rejected`, not resent; a restart finding
  one sends nothing; the message); bare metal `test_watchdog_cli.py` (fresh and
  resumed, JSON and exit 1); VM `test_buy_resume_cli.py` (a fresh buy and a resume
  exit 1). The `--watchdog-threshold` help and VM's `buy_cli` docstring no longer
  say the watchdog "stops" the deal.
- Round 2 triage fix, review 44 F2: the schedule ran on the wall clock, so a
  backward step postponed the next probe by the step. `watch_deal` takes
  `monotonic` for its schedule (`run_monitor` passes `WaitClock.monotonic`);
  instants are still stamped with `now`. Test (unit): `test_watchdog.py`, a wall
  clock set back an hour after the first probe leaves probes at 0, 30 and 60
  monotonic seconds. The read's wall-clock freshness limitation is accepted in D6a.

## 5. Receipt identity cutover

Replanned against the design section 5's return settled (D17–D26) and design review
35's triage refined: a receipt identity change is a drained cutover with no
re-anchoring, so this section withdraws the work in progress committed as
`9a3e6cbb3` and keeps only `pinned_snapshot_verifier`'s binding (D22). The superseded
tasks 5.2 and 5.3 (configured overlap and re-anchoring evidence; durable anchor
replacement and the retirement inventory) are replaced by 5.4–5.6; none was checked.
Requirements: settlement-configuration's "A receipt identity change is a cutover";
settlement-servicing's "Snapshot verification accepts configured identity history".

Files: kit/arkhai-payments/src/market_arkhai_payments/ (`receipts.py`, `adapter.py`,
`seller.py`, `settlement_config.py`, `__init__.py`; `reanchoring.py` deleted),
kit/arkhai-payments/README.md, kit/arkhai-payments/tests/ (`test_reanchoring.py`
deleted; `test_settlement_config.py`; a new `test_receipt_identity_cutover.py`),
domains/bare_metal/storefront/tests/test_http_settlement.py,
docs/development/DEPLOYMENT_AND_CONFIG.md.

- 5.1 The lane-only proposed declaration is dropped: the servicing declaration is
      treatments and a setup flag (D7), and identity is the receipt verifier's.
- [x] 5.4 Withdraw the work in progress (D17, D18, D19, D20, D22, D23). Restore to
      their content at `a547604e7`: `receipts.py` (no `anchor`, `_anchors` or
      `snapshot_signer`), `settlement_config.py` (the foundation's validation only:
      the current `service_identity` listed, retiring entries dated; no
      one-current or no-duplicate rule) and its test file, and the
      `receipt_identities` paragraph of `DEPLOYMENT_AND_CONFIG.md`. Delete
      `reanchoring.py` and `test_reanchoring.py`, drop their exports from
      `__init__.py`, and remove the README's "Receipt key rotation and
      re-anchoring". In `seller.py` remove every `anchor` parameter (`payment_adapter`,
      `check_receipt(_now)`, `receipt_matches`, the `snapshot_verifier` factory's
      third argument) and `reanchoring_evidence_now`, so `receipt_matches` is again
      `verify_receipt` under `config.receipt_trust`. Keep (D22): `adapter.py`'s
      `pinned_snapshot_verifier` binding `config.receipt_trust`, without `anchor`,
      its docstring saying it binds the configured current and retiring identities;
      and the stage's `_verifier_for` delegating to it. Remove the remaining
      `openspec/changes/README.md` reference only if implementation finds one: the
      design already replaced section 5's buyer gap row (D24).
      Verify: `git diff a547604e7 -- kit/arkhai-payments docs/development/DEPLOYMENT_AND_CONFIG.md`
      shows only the D22 binding and the tests of 5.5; `make -C kit/arkhai-payments test`
      (mypy, vectors, generated models and the unit suite) passes.
      As built: `receipts.py`, `settlement_config.py`, `test_settlement_config.py`,
      `__init__.py` and `DEPLOYMENT_AND_CONFIG.md` show no difference from
      `a547604e7` (each checked with `git diff`); `reanchoring.py` and
      `test_reanchoring.py` are removed. `seller.py` differs only by `_verifier_for`
      returning `pinned_snapshot_verifier(agreement, data, self.config)` (with its
      import; `verify_snapshot`'s dropped); `adapter.py` only by
      `pinned_snapshot_verifier` binding `config.receipt_trust`, its docstring naming
      the configured current and retiring identities and that a deal approved under
      an identity absent from the configuration does not verify. The README differs
      in two sentences beyond the removed section, both describing D22's binding:
      `stage.payment_adapter` verifies "under the configured receipt identities; its
      verifier factory can be injected" (not "for key rotation"), and
      `pinned_snapshot_verifier(agreement, data, config)` binds the configured
      identities, so a deal approved under an unlisted identity stops verifying and a
      key change drains open deals first, pointing to the deployment guide.
      `openspec/changes/README.md` held no section-5 reference to remove. `make -C
      kit/arkhai-payments test`: mypy clean on 29 files, vectors and generated models
      current, 348 passed (unit, with 5.5's three).
- [x] 5.5 Prove the kept binding and the cutover at the kit (D18, D22, D17).
      `test_receipt_identity_cutover.py` (unit, over the kit's clock-injected
      `PaymentsAuthority` engine signing under two keys through `FakePaymentsClient`,
      receipts from `build_signed_receipt`, deterministic development keys commented
      as such): with an overlap configuration, `pinned_snapshot_verifier` and the
      stage's verifier both accept a current-key snapshot embedding a receipt the
      configured retiring identity signed within its window (settlement-servicing's
      scenario "A current-key snapshot attests a retiring identity's receipt"); with a
      configuration naming only the new identity, `pinned_snapshot_verifier`,
      `check_receipt_now` and `receipt_matches` each refuse the deal the old identity
      approved, although a new-key snapshot embeds its receipt
      (settlement-configuration's scenario "A deal approved under a removed
      identity"); a configuration without `receipt_identities` trusts
      `service_identity` alone, as before.
      Verify: `make -C kit/arkhai-payments test`.
      As built: `kit/arkhai-payments/tests/test_receipt_identity_cutover.py`, three
      unit cases over `approved()`'s engine (`FakePaymentsClient`, approving under
      `SERVICE`, then `engine.signer` switched to a second development key at `NOW +
      20`): (1) overlap configuration (new identity current from `NOW + 10`, the old
      retiring until `NOW + 600`): `pinned_snapshot_verifier` accepts the new-key
      snapshot embedding the old receipt, and the stage answers `check_receipt_now`
      `ReceiptVerified`, its adapter's `read` `Accepted` and `receipt_matches` true;
      that `a547604e7`'s binding (`service_identity` alone) would fail the first
      assertion is reasoned from its code, not run; (2) only the new identity
      configured: `pinned_snapshot_verifier`, `check_receipt_now` (`ReceiptInvalid`),
      the adapter's `read` and `receipt_matches` (the engine's receipt and a
      `build_signed_receipt` one) each refuse; (3) no `receipt_identities`:
      `receipt_trust` is `service_identity` alone; a `SERVICE` snapshot and receipt
      verify, the other key's do not. 348 passed.
- [x] 5.6 Prove the cutover in a running storefront (D17). In
      `domains/bare_metal/storefront/tests/test_http_settlement.py` (integration: the
      storefront's settlement and fulfillment services over its real SQLite database,
      with `FakePaymentsClient` at the payments boundary), beside
      `test_payment_evidence_gates_replay_and_rechecks_receipt_after_restart`: a deal
      verified and delivered under the old identity, then the storefront restarted
      with a configuration naming only the new identity, refuses its stored receipt
      at the fulfillment status and a repeated settle request ("stored payment
      receipt does not prove this Agreement" or "is invalid"), with no second
      reservation or provisioning call.
      Verify: the bare-metal storefront's suite; `scripts/change-workflow run pre-commit`.
      End-to-end: none rotates a receipt key. Every payments scenario
      (`e2e_vm_payment_deal`, `e2e_vm_payment_purchase`, the six `e2e_vm_dispute_*`,
      `e2e_bare_metal_payment_deal`, `e2e_credits_payment_deal` and both recurring
      purchases) crosses the stage's verifier and `verify_snapshot`, which behave as
      at `a547604e7` but for `pinned_snapshot_verifier`'s binding, unchanged for a
      configuration without `receipt_identities`. Owed by validation: none.
      As built: `test_a_receipt_identity_cutover_refuses_a_deal_the_removed_identity_approved`,
      beside the restart test (integration: the settlement and fulfillment services
      over the migrated SQLite file, capacity and provisioning doubled,
      `FakePaymentsClient` serving the old-key receipt): the deal verifies (200) and
      reads `active` with one reservation and one provisioning call; the runtime is
      rebuilt over a new `SQLiteClient` on the same file with a composition trusting
      only a new development identity (`_payment_composition`, extracted from
      `_payment_deal`): the fulfillment status raises "stored payment receipt is
      invalid", a repeated settle raises `SettlementRequestError` "stored payment
      receipt does not prove this Agreement", and the counts stay at one. The rebuild
      is in-process, not a process restart, and the services are called directly, as
      the restart test does, not through the app's typed client. Bare-metal
      storefront suite 646 passed in the section's pre-commit run.

## Section 5 notes and handoff

- **Implemented as replanned (5.4–5.6), every task checked.** No permanent spec or
  architecture document changed: the deltas carry D17 and D18, and the deployment
  guide's cutover paragraph (its `receipt_identities` paragraph is the foundation's,
  and its payments paragraph already calls a key change a cutover; draining or
  refunding first, D17, and buyers updating before approving, D26) and
  settlement-servicing's architecture are closeout's promotion (7.9). No lane
  configuration changed. End-to-end scenarios exercising the section: the payments
  scenarios 5.6 names cross the stage's verifier and `verify_snapshot`, which
  behave as at `a547604e7` for every lane configuration, none of which lists
  `receipt_identities`; none rotates a key. Owed by validation: none.
- Pre-commit at the section's end passed all three hooks (`make test`: payments kit
  348, bare-metal storefront 646 with the cutover case).
- The compliance check found no layering, packaging, comment or import breach, and
  the withdrawal complete with only D22's binding surviving; two note claims
  corrected. Declined, for the round's review: rewording `receipts.py`'s module
  docstring ("retiring keys may verify historical receipts but cannot re-anchor
  them"), restored verbatim and still true (a retiring key's snapshot attests no
  embedded receipt); and tests of the configuration rules D22 keeps (the current
  identity listed, retiring entries dated), which `a547604e7` had none of.
- **The withdrawn first session.** It built re-anchoring (`9a3e6cbb3`: a persisted
  anchor threaded through `verify_snapshot`, `pinned_snapshot_verifier`, the stage's
  adapter, receipt check and `receipt_matches`; a one-current-identity validator;
  `reanchoring_evidence`, `record_reanchoring`, `reanchored_snapshot` and
  `retirement_inventory`; payments 355 passed) and returned the change to design:
  the shared verifier accepts an old receipt only while its issuer is a configured
  pin, so once the retiring pin is removed every later snapshot of a re-anchored
  deal, the seller stage's receipt check and stored-receipt revalidation are
  refused, and D7's re-anchoring could not remove the dependence without changing
  the shared verifier or redefining removal. Design settled a drained cutover
  (D17–D26), answering its questions: anchor or retained pin (D17), a verifier
  change (D18), buyers (D19), `reverse_now` and refunds (D23, D17), convergence's
  obligation (D21). None of that session's "As built", instructions for
  convergence, buyer gap row or references to "… bounded identity history" (now "…
  configured identity history", D18) stand; only `pinned_snapshot_verifier`'s
  binding of `config.receipt_trust` is kept (D22, 5.4).
- Round 2 triage fix outside the plan, the orchestrating session's observation 46
  R1: `make -C kit/deal-servicing typecheck`, planned by 4C and 4D, was denied to
  every step, and no gate ran it (the kit's `test` ran pytest alone). Its `test`
  now depends on `typecheck`, as the payments kit's does, so pre-commit's `make
  test` type-checks it; its first run found one error, the unannotated unpacking of
  `asyncio.gather(..., return_exceptions=True)` in `seller.py`'s administrator end,
  now annotated. The never-run first-use examples became task 6.6.
- Round 2 triage's checks, over the fixes under 4E, 4F and here, after `make dist`:
  payments kit `make test` 351 (unit); buyer half 49 (unit); bare-metal buyer 84
  (unit); VM buyer 334 (unit); deal-servicing `make test` with its typecheck, 102
  (unit and library integration); VM storefront `test_publication_loop.py` and
  `test_watchdog_buy.py` 87 (application integration); `make -C e2e-tests
  test-unit` 911 passed, 1 skipped; pre-commit passed all three hooks. The
  compliance check found no layering, packaging or comment breach; fixed: VM's
  ordering test's docstring and the documents citing it (claiming a payments
  approval); the test-compatibility delta's scenario, D16 and the state field's
  comment still claiming the lane asserts a pre-approval display; the deal-lifecycle
  delta's `stopped` read beside the new scenario; two help strings saying the
  watchdog "stops" the deal.
  End-to-end: `e2e_vm_recurring_purchase` and `e2e_bare_metal_recurring_purchase`
  exercise V1's fix and F3's renamed stage; no scenario exercises the watchdog,
  as 4F's notes say. Owed by validation: the pipeline's VM lane.

## 6. Qualification scenarios and pre-closeout review

Files: kit/arkhai-payments/test-vectors and vector runner, README.md,
examples/local_e2e.py; focused lifecycle/CLI integration suites. Convergence owns
consumer scenario files and selectors under each compute lane; activation owns
hosted-target evidence.

- [x] 6.1 Update examples/fixtures to USD/6 without hardcoding a production asset.
      Keep published vectors content-identified and separate from double
      traces. Label evidence with test-compatibility's two labels, lane-double
      evidence and live evidence (D8); add no third.
      Run make -C kit/arkhai-payments check-vectors,
      check-generated, test-unit and typecheck as appropriate to changed seams.
      As built: `kit/arkhai-payments/examples/rate.py`, `examples/lifecycle.py` and
      `kit/deal-servicing/examples/preempt_first_use.py` name a fixture `ASSET =
      "USD/6"`, commented that production derivation reads the accepted Agreement's
      asset; `examples/local_e2e.py` carries the comment inline. Amounts keep their
      money (a rate of 60 per hour over a 60-second period is `1000000` per period,
      setup `250000`; the once example's `100000000` and its reverses and case
      effects scaled alike; the preemption fixture funds `10000000000`). The README's
      local funding request names `USD/6`. The published vectors are the producer's
      unchanged bytes (mostly `USD/6`, three `EUR/2` entries); `check-vectors`
      replays them and prints the contract's identity and hashes, apart from any
      double trace. The rate example's third label, `"evidence_class": "fixture"`,
      is now `lane-double evidence`. `make -C kit/arkhai-payments test`: mypy clean
      on 29 files (examples included), vectors and generated models current, 353
      passed (with 6.6's two example tests). `local_e2e.py` was not run (it needs a
      local payments service); its change is two type-checked literals. Not
      converted: the shipped `recurring_options` fixture in
      `market_arkhai_payments.fixtures` (`USD/2`; eight test modules across four
      packages consume it), the kit's term builders `tests/payment_terms.py` and
      `tests/rate_terms.py`, and the VM storefront's `examples/payment_smoke.py`
      with its README. The rate example's test asserts its `USD/6` setup and rate
      amounts.
      Narrowed by the round's triage (implementation review 69 F1, the owner's
      note 67 O2): `USD/6` is the asset of this change's first-use examples and
      their evidence, as D8 and the proposal now say; the fixtures, term builders
      and smoke example above keep `USD/2`, since derivation reads the scale from
      the asset named and none of their tests depends on which.
- [x] 6.2 Supply evidence metadata at the adapter/command first-use boundary:
      contract revision, target class/mode, hashes and control trace. Readiness
      gates scenario runs, not a claim that the target was prepared here.
      Record each scenario's buyer waivers; a buyer that waived a term is not
      evidence of acceptance by default buyers.
      As built: the rate first use's JSON and the seller-preemption first use's
      carry `contract` (`get_contract().metadata`: the published selection, the
      schema's `$id`, and the schema and vector SHA-256, matching
      `schema/SOURCE.md`); the vendored contract has no revision field, so the
      selection and content hashes stand for it. Both carry the target's selector
      and mode (`double_selector: in-process`, `livemode` false) and
      `control_trace`, the fixture's controls in order (the rate example's lost start
      response and two clock steps, 1 s then 29 s; the preemption example's two
      fundings and lost notice response). Waivers: the rate example's
      `buyer_waivers: []`; the preemption example's `default_buyer` `waivers: []` and
      its charged variant's two waivers by name, observed apart; the lists record the
      approvals as built, with no terms policy. Readiness: the preemption example
      refuses any profile but the lane-only, in-process, `livemode = false` one; the
      rate example's in-process target needs no gate; neither claims a target
      prepared. Tests: `kit/arkhai-payments/tests/test_first_use_examples.py` (kit
      library integration as D8 names it: the rate example's `main` chaining preset
      derivation, the buyer's check and the adapter over the clock-injected engine
      behind `FakePaymentsClient`, no storage; in the flat `tests/` root the unowned
      gap row records), asserting the label, the contract, the trace's order, no
      waivers and the `USD/6` parts; and
      `kit/deal-servicing/tests/integration/test_preempt_first_use.py`, extended
      (library integration: the contract, the trace and the default buyer's empty
      waivers).
- [x] 6.3 Reference convergence's sole consolidated rate qualification matrix
      (its design's Scenarios and evidence); do not reproduce it here. Retain
      spot's prepared fixtures and typed entry points for its executor. Activation
      owns hosted qualification. (Replanned against D17, D21 and D24: this change
      produces no re-anchoring evidence, and the matrix carries no rotation row.)
      Consume convergence's lane-time requirements and the lane-double-owned readiness/evidence
      contract; retain kit and vector evidence production
      (test-compatibility's "Rate mechanics qualification consumes the shared lane
      contract"), not a second lane-time contract.
      Activation must list producer snapshot, start and reversal vectors among
      blockers to published qualification; double traces do not satisfy them.
      Check that the matrix consumes maximum-term and on-demand refusal/self-penalty
      filing; report missing coverage to convergence rather than maintain another
      matrix, and report its row 11 (identity rotation overlap) as withdrawn by D21
      if its design has not yet removed it. Require physical release/access closure rather
      than a lease_ended intent report. Promote no unrun consumer requirement here.
      As built: convergence's "Scenarios and evidence", as this branch holds it,
      consumes the maximum term (row 9) and both self-penalty filings, on-demand and
      spot (row 10); its rejection of "end intent as release proof" and its two
      completion facts require physical release and access closure. Its row 11 and
      D7 overlap paragraph remain; its index notes already report them withdrawn
      (D17, carried by D21). Reported in its index notes in
      `openspec/changes/README.md`, not its directory: runs recorded under three
      classes where test-compatibility has two labels; rows 7 and 9 still waiting on
      interim charged terms, though the contract expresses `returned` and this
      change's fixtures are the shipped presets with default buyers and a separately
      waived charged variant; row 10 not observing the on-demand notice refused
      naming `delivery_end` before the filing, which only this change's command
      first use observes. Activation's D1 lists the producer's signed snapshot,
      start and reversal vectors among the blockers to published qualification, and
      double traces satisfy none; its row now notes the same stale three classes.
      Lane time: convergence's lanes run real UTC time with the doubles' clocks never
      jumped; this change defines no lane clock, its examples' injected clocks being
      kit-level, as convergence's library-integration rule allows. Retained for its
      executor: `examples/rate.py`, `preempt_first_use.py` with `preempt.lane.toml`,
      the typed notice client and `deals preempt`, and the adapter's `start` and read
      seams. No consumer requirement is promoted.
- [x] 6.4 Check the changed imports, comments and public artifacts before code
      review. Move touched local imports to module level where safe, retaining
      only verified circularity or deliberate lazy-load reasons. Run focused
      domain integration and typing, then make check-packaging; fix failures
      before committing implementation.
      End-to-end: the payments scenarios (`e2e_vm_payment_deal`,
      `e2e_vm_payment_purchase`, `e2e_bare_metal_payment_deal`,
      `e2e_credits_payment_deal`) and both recurring purchases
      (`e2e_vm_recurring_purchase`, `e2e_bare_metal_recurring_purchase`) cross the
      kit seams this section's examples and evidence metadata touch; validation's
      pipeline run is their evidence. Owed by validation: none.
      Corrected: no end-to-end scenario exercises this section's changes (kit
      examples, their tests, two READMEs, index notes, a comment and a test file's
      whitespace; no production code path). The scenarios above exercise the change
      as a whole, and validation's pipeline run is their evidence for it, not for
      this section. Owed by validation: none.
      As built: the only import the whole change adds below module level (`git diff
      3acfdbf03 -- '*.py'`, the merge base with `dev`) is the watchdog's
      `TYPE_CHECKING` import of `BuyerLifecycle`; at module level it fails on import
      (`lifecycle.py` imports `watchdog.py`), so it stays with that reason beside it;
      buyer half 49 passed (unit). This section's own imports are at module level.
      `git diff --check` against the merge base is clean after removing the extra
      blank line ending `domains/bare_metal/buyer/tests/test_buyer_composition.py`
      (reviews 44 and 63; that module 17 passed, unit). Comments added state the
      fixture asset, the migration bodies a session does not run, and the circular
      import. The payments kit's mypy covers its examples, clean on 29 files;
      deal-servicing's typecheck is clean. Pre-commit: the section's notes.
- [x] 6.5 Obtain pre-closeout code review. Confirm adapter/servicing ownership and
      that partialPeriod is enforceable at the payment authority, with no local
      correction substituted for the buyer's authority/dispute guarantee. Verify
      the command/preset seams here; consumer-enabled
      cross-service acceptance gates convergence and hosted live qualification
      gates activation, not this prerequisite change's archival.
      As reviewed: pre-closeout review 139 at `3ac176071` found nothing; it
      confirmed every earlier accepted finding addressed, the added scope recorded,
      comments and imports ready, and the ownership boundary (rate servicing to
      convergence, hosted qualification to activation). Validation 138 passed at the
      same commit. The triage checked partialPeriod in the code, which the review did
      not take up: the rate mandate carries the end's partialPeriod and each stop
      authority's rule as authority terms (`mandates.py`); the adapter forwards a
      `chosen` stop's treatment and refuses to override a fixed one
      (`rate_parts.py`); the settled treatment is read from the authority's winning
      stop, so no local correction stands in for it.
- [x] 6.6 Before 6.5's review, run the first-use examples no step has run on this
      branch, `make -C kit/arkhai-payments first-use-rate` and `make -C
      kit/deal-servicing first-use`, and record what each shows and any failure's
      fix (round 2 triage, the orchestrating session's observation 46 R1). The
      implementation step's table allows no `make -C * first-use*`, so this needs
      that allow rule, added by the owner or the orchestrating session, or the owner
      running both commands and recording their output here.
      As run: `make -C kit/arkhai-payments first-use-rate` passed before any edit
      and after 6.1 and 6.2: setup and rate derivation in `USD/6`, the default
      buyer's check, `allow` before activation, the lost start response `unknown`
      and its same-key retry `accepted`, disclosure `allow`, the seller's notice
      `accepted` and pending at `+30`, the payer's zero-notice stop `accepted` and
      controlling (`started_period`, final at `+1`), the read `ended`, under the
      lane-double label with the contract hashes and control trace. `make -C
      kit/deal-servicing first-use` failed at its first example, `no such table:
      servicing_evidence_deals`: since `dev`'s stateful-service migration change, a
      storefront chain's migration bodies (`create_schema`,
      `create_payment_observations`) create the servicing tables and no session does,
      and only `respondent_first_use.py` had been updated. Fixed, outside the plan:
      `first_use`, `end_first_use`, `watch_first_use`, `seller_first_use`,
      `ingress_first_use`, `routes_first_use` and `receipt_first_use` apply both
      bodies in a transaction first, commented. All ten examples then ran (evidence
      bytes kept and pruned after the window, end replay and the earliest end, the
      watch's ruling replay, bounded seller views, surrender and site evidence, the
      mounted routes, the budget warnings, respondent answers, both receipt schemes,
      the preemption JSON). The suite now runs all ten:
      `kit/deal-servicing/tests/integration/test_first_use_examples.py` (library
      integration, the eight that hold a database, each over its own SQLite file),
      `tests/unit/test_budget_first_use.py` (unit, the budget example) and the
      preemption test; `make -C kit/deal-servicing test` (typecheck, then the suite)
      111 passed. The payments kit's `make -C kit/arkhai-payments first-use` (the
      once example, `examples/lifecycle.py`) was denied, so it ran through
      `kit/arkhai-payments/tests/test_first_use_examples.py` instead, and failed: the
      authority records the once part's terms end as the transaction's first event,
      so the read held two events where it expected one reverse, and its scripted
      case effects reused sequence 2. Fixed, outside the plan: it counts reverse
      events, its case effects run 3 to 7 (lift of 3, extension 5), and its engine
      holds three events; the test passes.

Evidence levels: conformance and kit integration qualify SCM's contract use;
application integration qualifies both compositions; smoke qualifies wiring/auth;
lane e2e qualifies cross-service behavior under the declared double contract.
Only hosted qualification may claim the deployed service revision works, and only
that service's own suite establishes its ledger/payout internals.

## Section 6 notes and handoff

- **End-to-end:** no scenario exercises this section's changes (6.4's
  correction). Owed by validation: none.
- **Pre-commit** over the finished section passed all three hooks (`make test`:
  payments kit 353, deal-servicing 111, buyer half 49, bare-metal storefront 646).
- **Outside the plan, fixed here** (`docs/guidance/workflow/changes.md#defects-found-during-a-change`):
  seven deal-servicing first-use examples created no table since `dev`'s
  stateful-service migration change, and the payments kit's once example expected
  one event where the authority now records the once part's terms end first (6.6).
  Both broke because nothing ran them; each kit's suite now runs every example its
  `first-use` targets run. Also the extra blank line ending the bare-metal buyer's
  composition test (6.4).
- **The `USD/2` fixtures and helpers** 6.1 names were left for the round's review
  and the owner; the triage's narrowing (6.1) keeps them.
- **Reported to dependents, not maintained here:** convergence's matrix gaps and
  activation's stale evidence classes, in their index rows (6.3).
- **Compliance check** found no layering, comment or packaging breach. Fixed: the
  preemption fixture's funding, cut a hundredfold by the asset change, restored;
  the budget example, which holds no database, moved from the integration test to a
  unit one; 6.1–6.4's notes completed or corrected; an unwrapped README line.
  Declined: nothing.
- 7.8 records the pipeline run; this section's examples are not part of it.

## 7. Closeout

Documentation only, after code review, in the order required by
docs/guidance/workflow/closeout.md, with this repository's parts in
openspec/README.md#this-repositorys-closeout-parts. Any required code fix returns
this change to implementation and review.

- [x] 7.1 **Comment hygiene.** Run make check-comment-hygiene and inspect touched
      comments/docstrings for stale provenance. Do not edit code during closeout.
      Confirmed: `make check-comment-hygiene` passed (no change ids, task numbers or
      change names outside `openspec/`). Every comment line the change added since
      the merge base `840c87887` was read: each describes the current system, and
      none names a change, task, review or migration (log step labels such as
      `[r04]` are scenario stages). No fix round needed.
- [x] 7.2 **Import placement.** Confirm touched imports are at module level unless
      a verified circularity or deliberate lazy-load reason was retained and
      reviewed; a necessary move returns to implementation.
      Confirmed: the one import the change adds below module level since
      `840c87887` is the watchdog's `TYPE_CHECKING` import of `BuyerLifecycle`, kept
      for the verified circular import with its reason beside it (6.4). Nothing to
      move.
- [x] 7.3 **Documentation compliance.** Classify every accepted decision in D1–D26,
      D6a's watchdog status and narrowed probe and bound included; keep external authority behavior as architecture
      context, not SCM normative implementation promises. Confirm adapter versus
      continuation ownership, and that end service's refusal of a rate deal (D12) is
      documented as the current invariant convergence modifies, not as a migration
      step. Confirm no permanent document promises receipt key re-anchoring or an
      overlap that keeps open deals alive past a key change (D17, D24), and that the
      watchdog is described nowhere as detecting more than its disclosed endpoint no
      longer accepting connections (D6a).
      Done: every accepted decision D1–D26 has a home under
      `openspec-documentation.md`'s and `openspec/README.md`'s placement tables,
      recorded in design.md's promotion record (D19–D20, D22–D23 and D25 none, each
      saying why). Authority behaviour is context under deal-lifecycle's "External
      authorities", not SCM requirements. Adapter (stateless, `kit/arkhai-payments`)
      versus continuation (`kit/deal-servicing`) ownership is stated in
      ARCHITECTURE.md's "Kit areas". D12 is documented as the current invariant,
      unconditional until rate servicing replaces it, not as a migration step. No
      permanent document promises re-anchoring or an overlap keeping deals alive:
      settlement-servicing and the settlement configuration state the drain, and
      `deployment-state`'s retiring-window sentence promises neither. The watchdog
      is described only as detecting its disclosed SSH endpoint no longer accepting
      connections. The documents implementation wrote (DEPLOYMENT_AND_CONFIG,
      TESTING, ROADMAP, VALIDATION_RUNBOOK, versioning.md, published-packages.md,
      test-placement.md, the e2e and kit READMEs) read as current state. Stale
      statements found and corrected at promotion: "once-only adapter" claims in
      the deal-lifecycle and settlement-servicing companions, and `teardown` as the
      bare-metal buyer's verb in companions and `docs/bare-metal-seller-quickstart.md`.
- [x] 7.4 **Narrative compression.** Compress completed tasks to final behavior,
      material evidence, residuals and permanent destinations, preserving material
      rationale in design.md.
      Done: sections 1–6 and their notes went from 2,788 to 2,246 lines; no heading,
      task line or planned statement changed, and every "Owed by validation" line
      was kept but one duplicate in section 5's withdrawn record. Removed: session
      logistics, debugging narratives and resolved attempts (4B.5's code trace, 4F's
      replanning options, section 5's withdrawn first-session record, superseded by
      D17–D26), step-by-step compliance-check accounts (now what was fixed and
      declined), pre-commit transcripts (one line each) and repetition of D10, D11
      and D14. Moved to design.md first: the coded refusal's journaling consequences
      for convergence, the barrier's placement and the observation instant as a lower
      bound (D14), and the watchdog's rejected alternatives, resume order and
      accepted limits of its bound (D6a). Implementation detail with no design
      content stays in the task notes.
- [x] 7.5 **Roadmap currency.** Update Goal 8 in docs/development/ROADMAP.md with
      both-domain rate mechanics, seller notice, a recurring purchase run end to end
      through commit in both lanes, delivery refused until rate servicing is composed,
      and the remaining continuation/hosted activation gap. Remove absorbed-change gap
      owners and record promotion. In Goal 8's accepted limitations, the watchdog's
      bound runs from the disclosed endpoint no longer accepting connections, the one
      failure it covers, not from "the loss" of the resource (D6a). Confirm this
      change's and convergence's rows carry no rotation criterion (D24).
      Done: Goal 8's current state gains a paragraph on the payments mechanism —
      both-domain rate and setup derivation with authority-priced `partialPeriod`,
      the buyers' exact check and approval policy, the composed adapter, seller
      notice, the canonical `end` and the watchdog, end service refusing to commit a
      rate deal with the deadline barrier, a recurring purchase through commit in
      both lanes, and the continuation and hosted activation that remain. The stale
      "current payment adapter is once-only" and "no end-to-end run produces a
      per-period Agreement" sentences are corrected, and administrator ends name both
      storefronts' route. This change's row reads archived with its closeout
      evidence, linked to the archive; Goal 8's unowned work gains the receipt key
      re-anchoring row (D24). No absorbed change owned a roadmap gap. The accepted
      limitations already bound the watchdog from the endpoint ceasing to accept
      connections, and neither this change's nor convergence's row carries a
      rotation criterion.
- [x] 7.6 **Campaign index currency.** Update openspec/changes/README.md status,
      dependencies and campaign graph; remove absorbed rows and redirect their
      dependents to this change; confirm 4E.3 closed the per-period gap row, and that
      `converge-ongoing-compute-leases`' row or notes name the end-service refusal it
      lifts and the rotation work D21 withdrew, and that the unowned gap row "A receipt
      key change drains every open payment deal" (D24) stands. Run make
      check-change-index and record disposition.
      Done: the row is `in closeout`, its notes rewritten for closeout, and links
      the archive once archived. Its status and campaign placement are otherwise
      unchanged, so the campaign graph stands; no other row's status or `Depends
      on` changed (archive cleanup releases dependents). No absorbed change has a
      row. 4E.3 closed the per-period gap row. Convergence's notes now name the
      end-service refusal its composition lifts and the commit keying it decides
      (D14), beside D21's withdrawn rotation work. The D24 gap row stands. Two
      residuals of 4B.4 that no review or triage took up are recorded as unowned
      gap rows under this change: VM's composition building no payments stage, and
      the two database-seeded cached-rate tests that duplicate restored cases.
      `scripts/change-workflow check index`: OK.
- [x] 7.7 **Packaging.** Run make check-packaging and
      make check-architecture-change CHANGE=spot-deals-through-arkhai-payments,
      resolving every failure/owned exception. Run make check-agent-skills if
      implementation touched agent instruction directories.
      Done: `scripts/change-workflow run pre-archive` at `e22997442` passed —
      `make check-packaging` (locks, Python version, build constraints, layout,
      layers, scope, dependencies, kinds, release declaration) and `make
      check-architecture-change`, which found no architecture row the change owns.
      No path under `.agents/`, `.claude/` or `.codex/` changed; the skills check
      passed in `run pre-commit`.
- [x] 7.8 **End-to-end pipeline.** Record the complete pipeline run/result and
      applicable scenarios in section 6, `e2e_vm_recurring_purchase` and
      `e2e_bare_metal_recurring_purchase` among them. Name exact prerequisites/owning changes
      for unrun consumer-enabled or hosted validation; do not mark them passed or
      substitute unit evidence. Record 4F.6's transfer of the delivered-deal watchdog
      cases to convergence. The rate-consumer scenarios gate convergence's
      acceptance and hosted scenarios gate activation; record their transfer here
      without making this prerequisite wait for a dependent's archival.
      Recorded: validation 148 at `e22997442`, the merge of `dev` and the closeout
      commit's parent, passed. Its pipeline run 43772719113 (e2e.yml) succeeded,
      with jobs e2e-vm, e2e-bare-metal, e2e-apicredits and native-ansible-gate; its
      local part (`dist-clean`, `check-packaging`, `test`) and Helm part passed; CI
      was owed by no section. Closeout changes no code, so the run describes the
      code the closeout commit carries. Scenarios exercising the change:
      `e2e_vm_recurring_purchase` and `e2e_bare_metal_recurring_purchase`, whose job
      logs show every stage through `r08` — one rate part of one period's price, the
      commit refused with no reservation by delivery and no rate start (VM's
      acceptance hold left), the buyer's `end` recorded with no filing, the payer's
      balance restored; the once-deal payment scenarios on the composed adapter's
      once path and the lifecycle read (`e2e_vm_payment_deal`,
      `e2e_vm_payment_purchase`, the six `e2e_vm_dispute_*`,
      `e2e_bare_metal_payment_deal`, `e2e_credits_payment_deal`); and the bare-metal
      purchase and qualification scenarios running `end`. Owed by validation: the
      pipeline's VM lane (round 2 triage), which the run's e2e-vm job covers.
      Unrun, with their owners: no lane scenario crosses a delivery deadline, calls
      bare metal's interrupt route or runs the watchdog. The watchdog's
      delivered-deal cases (4F.6), delivered rate deals and the consolidated rate
      qualification matrix transfer to `converge-ongoing-compute-leases`, which
      lifts end service's refusal and whose acceptance they gate; hosted live
      qualification transfers to `activate-per-period-compute-servicing`, blocked on
      the hosted payments deployment. This change's archival waits on neither.
- [x] 7.9 **Promotion.** Write openspec/specs/settlement-servicing/architecture.md
      (rate operations and partialPeriod; under "Charge-first payment settlement",
      beside its current/retiring pins, why a receipt key change drains rather than
      re-anchors: no deployed deal outlives a drain, and a retired identity left
      configured can still sign backdated snapshots, D17), storefront-publication/
      architecture.md (presets and independent pricing), deal-lifecycle/
      architecture.md (notice, rate buyer-end flow and External authorities; under
      "One end instant, transactional admission", end service's refusal of a rate deal
      as the one place delivery fails closed before rate servicing, and the deadline
      barrier), compute-delivery/architecture.md ("Commit and hold adoption": the
      refused rate commit and its repair reason), buyer-orchestration/architecture.md
      (a new section "The buyer's watchdog": the conditional bound covering the
      disclosed endpoint no longer accepting connections, the probe using no
      credential, the authenticated probe rejected, and the last-probe status,
      buyer-local and off the wire), test-compatibility/
      architecture.md (evidence labels; "Ordinary Arkhai purchase evidence": the
      recurring purchase through commit), docs/development/ARCHITECTURE.md
      (Kit areas, Settlement servicing and Release),
      openspec/specs/settlement-configuration/configuration.md (servicing,
      `snapshot_freshness_seconds`; in the payments paragraph that calls a receipt
      identity change a cutover: open payment deals drained or refunded before the
      change, refunds first since a refund afterwards finds no verified payment,
      `receipt_identities` listing both keys only for the moment of the switch, and
      buyers updating their receipt identity before approving after it, D17, D26),
      docs/guidance/engineering/versioning.md (the staged rename, promoted in
      implementation) and docs/guidance/repository/package-versions.md (its
      "Compatibility is owed to what a release has shipped": migration and backwards
      compatibility are engineered only for what has been deployed, with a pointer
      from docs/development/ARCHITECTURE.md),
      and openspec/specs/README.md capability index as needed. Promote the owner's
      principles in the wording design.md's promotion record and the owner record's
      R24 settle, at these destinations (review 142 F1): each change mergeable on its
      own merits into the branch it lands on (docs/guidance/workflow/changes.md, "One
      change per branch"; the role names the branch, so no `dev` mapping is written);
      before adding behaviour to one of two parts that handle one concern, check
      whether the other has it or needs it (one sentence in
      docs/guidance/engineering/implementation.md, "Composition from one component",
      and a link to it from docs/guidance/repository/family-kits.md, "Sibling domains
      behave alike", which is not restated); the staged field rename (versioning.md,
      done); migration and backwards compatibility only for what has been deployed
      (package-versions.md, pointer from ARCHITECTURE.md); contradictory classes do
      not subclass one another (implementation.md, a section of its own beside
      "Composition from one component", widening the `implementation` row of
      docs/guidance/engineering/README.md's tag table to name class hierarchies); a
      timestamp is its source's claim (implementation.md, "Deciding which party is
      authoritative"; no ARCHITECTURE.md pointer). The per-boundary
      compatibility posture is not promoted. Complete this change's design-promotion
      record. Preserve the shared mandate requirement's once clauses and archive
      after the foundation; promote rate buyer-end only in deal-lifecycle,
      referenced by buyer-orchestration. Archive writes delta-covered spec.md files
      for settlement-servicing, settlement-configuration, storefront-publication,
      deal-lifecycle, buyer-orchestration, test-compatibility and compute-delivery.
      Written, each as the system now is: settlement-servicing `architecture.md`,
      "Charge-first payment settlement" (the drain beside the pins, the composed
      adapter, rate mandates, authority-priced treatment, pure authorization) and
      "Current limits", and its `configuration.md`; storefront-publication, "The
      servicing declaration and its three doors" and a new "Recurring payments
      presets"; deal-lifecycle, "Parts and terms", "One end instant, transactional
      admission" (the refusal and the barrier), "Buyer surrender and cases" (`end`
      and the rate buyer end), a new "Seller notice and administrator
      interruption", "External authorities" and "Current limits"; compute-delivery,
      "Commit and hold adoption"; buyer-orchestration, "Compute terms before
      approval" (approval under the run's policy), "Delivery-only ends and case
      evidence" (referencing deal-lifecycle's rate end) and a new "The buyer's
      watchdog"; test-compatibility, "Payment evidence ownership" (the two labels,
      first-use evidence) and "Ordinary Arkhai purchase evidence"; ARCHITECTURE.md,
      "Kit areas", "Settlement servicing", "Release" and "Operators"; the settlement
      configuration's "Settlement consumer configuration and cutover" (the drained
      cutover, refunds first, buyers updating first, `receipt_identities` for the
      switch only, `snapshot_freshness_seconds`, the materialization door, lane-only
      declarations, the `chosen` presupposition); package-versions.md's
      deployed-only rule; changes.md's mergeability sentence; implementation.md's
      sibling check, a new "Contradictory classes do not subclass one another" with
      a neutral example, and the timestamp rule, in R24's wording; the engineering
      tag row; family-kits.md's link; `openspec/specs/README.md`'s settlement rows;
      the seller quickstart's real-host `end`. versioning.md's rename was promoted at
      implementation; the per-boundary posture is not promoted. No touched
      capability has an `index.md`. The design-promotion record is complete. Every
      MODIFIED and REMOVED delta targets a requirement the permanent spec holds
      unedited and no ADDED one exists yet, so the deltas merge (no `--skip-specs`);
      the mandate requirement's MODIFIED text keeps the foundation's once clauses.
      Found, for the closeout review: D1's recommendation that the bare-metal
      example configuration price setup for hosts is not in the repository, and an
      example configuration is outside closeout's paths. Settled by closeout review
      150 F2: no shipped configuration publishes a recurring option, so the
      recommendation goes to activate-per-period-compute-servicing's operator
      documentation for recurring offers, named in its change-index notes; D1 and its
      promotion row say so.
- [x] 7.10 **Guidance placement.** Read each guidance section this branch added,
      moved or rewrote since it branched against the layer test, adjacency and
      exception placement (docs/guidance/workflow/README.md#the-layers-of-guidance;
      here, openspec/README.md#documentation-placement): versioning.md's "A field may
      be renamed or retired in stages", test-placement.md's bare-metal buyer CLI
      factory list, the two rewritten rows of published-packages.md's dependency
      table, and every guidance section 7.9 writes or links. Move what is misplaced
      within the inert paths, report a misplacement needing a decision for the
      closeout review, and run make check-guidance (review 142 F2).
      Done, nothing moved: versioning.md's staged rename holds without the workflow
      or this repository (engineering, neutral wording); test-placement.md's
      factory list extends the existing instance of a cross-system rule; the two
      published-packages.md rows sit in their table; implementation.md's three
      edits are engineering and neutral, the class rule with a neutral example and
      the timestamp rule keeping R24's "dispute authority" as a generic role;
      changes.md names the landing branch by its role; family-kits.md links the
      shared rule without restating it; the engineering tag row names what the file
      now covers. For the closeout review, one placement question: the deployed-only
      compatibility rule holds in any repository, so the layer test could place it
      in engineering's versioning.md, but the owner's and review 142's triage's
      destination is package-versions.md's existing section, so it stays.
      `make check-guidance`: OK, 104 guidance files.
      Settled by closeout review 150 F1: the rule is engineering, in versioning.md's
      "Compatibility is owed to what has been deployed", holding only against a named
      record of what has been deployed and, where none is named, treating everything
      released as deployed and settling the release policy with whoever decides
      releases; package-versions.md states this repository's instance, the
      `marketplace-v<semver>` release tags.
- [x] 7.11 **Documentation citations.** Run
      make check-doc-citations CHANGE=spot-deals-through-arkhai-payments after
      promotion and resolve every match; run
      openspec validate spot-deals-through-arkhai-payments --strict with the
      repository-pinned validator.
      Done: `make check-doc-citations CHANGE=spot-deals-through-arkhai-payments`,
      every cited path resolves (11 documents); `scripts/change-workflow openspec
      validate spot-deals-through-arkhai-payments --strict`, valid;
      `scripts/change-workflow run pre-commit`, every check passed (index, tasks,
      skills, OpenSpec strict, and `make check-repository`: comment hygiene,
      citations, specification index, decision destinations, history wording,
      version bumps, local imports, capability index, guidance).
- [x] 7.12 **Archival.** Run openspec archive spot-deals-through-arkhai-payments -y
      last, merging deltas; update the campaign row to the archive. Closeout
      review/triage reads the archived change and promoted permanent documents.
      Done last, with every other part checked: `scripts/change-workflow openspec
      archive spot-deals-through-arkhai-payments -y`, merging the seven
      capabilities' deltas (no `--skip-specs`, 7.9); the merged specs were read
      against the deltas, the change's index row and the roadmap's row point at the
      archive, and `scripts/change-workflow run pre-commit` validated every
      specification strictly.

## Design promotion record

The record is design.md's "Design promotion record", completed at closeout with
each decision's permanent location as promoted.
