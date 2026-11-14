# Tasks — hosted compute rate parts and seller notice

The owner's design discussion recorded in round 1's owner record stood in for this
change's design review. Round 1 implemented sections 1–4 with task 2.7; round 2
implements sections 4A, 4B, 5 and 6, each committed on its own in its own session,
reviewed and validated together; pre-closeout and closeout follow. No section
implements another verifier, continuation daemon or site renewal policy.

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

- Delivered `mandates.py`, `agreement.py`, `presets.py`, `settlement_config.py`, `operations.py` and `rate_adapter.py` in the payments kit; buyer/seller gates and both compute `settlement_composition.py` integrations. No installed recurring servicing declaration was enabled.
- Reused the shared DeliveryEvidence, lifecycle codec, snapshot verifier, foundation dispute filing and authority fixture. Rate descriptors require caller-persisted digests; disclosure can consume the journaled start outcome with its operation identity. Neutral per-part observations distinguish stop requests from winning final stops; watch observes notice maturity independently of its event cursor and retains the first observation on replay.
- Focused evidence: payments 221, lifecycle servicing 63, mediation 77, VM publication/payment integration 104, bare-metal publication/payment integration 21 existing tests pass. Published vector/generated checks and kit typing pass. Composition-file typechecks pass (bare-metal skips untyped-import diagnostics for existing unmarked dependencies). Permanent rate regression coverage is recorded with section 4; existing projection expectations follow the new public fields.
- `make check-packaging`, comment hygiene, amount-read inventory, change index and pinned OpenSpec strict validation pass. The durable packet and exact commands are in `docs/attachments/spot-deals-sections-1-3/index.md`; `make dist-ci && make -C kit/arkhai-payments first-use-rate` reproduces the prepared fixture with no secrets or resident services.
- E2E did not run in this slice's environment (no Docker). Validation runs the compose lanes with Docker and the local Helm part as end-to-end evidence; section 4's VM compose run stands as interim evidence, and a lane unrun at closeout is a blocker, not a pass.
- Post-review promotion remains the owning permanent specs/companions, architecture/configuration docs, roadmap and campaign index named below; this slice updates the kit README but does not archive or promote unimplemented behavior.

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

- 4.1–4.3: accepted-entitlement notice uses the existing administrator-authenticated submit route, durable command identity and per-part stop descriptors. Async/sync clients and both `deals preempt` verbs retain verified pending/final stops in read/list and recover lost responses without postponing an earlier payer stop. Application tests prove current listing edits can neither grant nor revoke accepted notice rights.
- 4.4: `domains/vms/storefront/examples/preempt.lane.toml` is the committed lane-only approval/command profile for both domains: paired options, explicit authority, in-process doubles, test mode, setup opt-out and explicit charged-term buyer acceptance. Both first-use commands pass; the default buyer separately refuses charged terms and materialization without the rate hook refuses. Runnable setup and observations: `docs/attachments/spot-deals-section-4/index.md`.
- 4.5: ordinary rate end journals the payer stop, then hints, retaining service during notice. Both domain compositions select the rate adapter; the VM `end` and bare-metal `teardown` verbs default to normal end, with `--end-now-regardless` selecting the existing immediate-surrender path. Escalation reuses the original stop. Unknown stop, hint loss and restart preserve independent progress. Application tests observe the effective stop through watch; deployed rate delivery/teardown remains convergence qualification.
- 4.5a was deferred on MVP grounds and no watchdog was built; the owner restored it (task 4B.6).
- 4.6: separate selector commit `a0ae6148d` adds `interruption_kind=preemption|failure` beside the free-text reason. Rate requests must state it; once-only omission retains failure for existing callers. Lawful preemption requires the accepted payee entitlement and delegates notice. Failure ends delivery and files for spot and on-demand, with no automatic rate self-penalty. Both typed admin clients expose the selector and operation key; the storefront CLI has no interrupt verb.
- Permanent coverage includes exact setup/rate derivation and buyer comparison, authorization's phase table and immutable activation bindings, start/stop/reverse keys, unknown-response recovery, refusal classes, verified pending/final stop records and fixed settled figures after held reversal. Seller and buyer application tests use real SQLite, signed typed clients and injected authority doubles; canonical command tests use their own module's factory seams.
- Validation: payments 266, servicing 70, contracts 37, lifecycle client 2, buyer half 22; focused VM storefront 157 and bare-metal storefront 46; buyer suites and final packaging results are in the evidence index. Payments and servicing typing, buyer-half typing, published vectors and generated checks pass.
- Required compose VM run: `PROVISIONING_MODE=mock mise exec -- make -C e2e-tests test-e2e-vm` exits **2**: 290 pass, 2 skip, one failure in the explicitly excluded retained `rate_structure` pricing mismatch (`test_listing_shapes.py::TestStage07_ShapePricing::test_07a2_market_buy_buys_a_smaller_shape_and_reaches_ready`). It is unchanged. The owned stack, volumes/network and leftover test Anvil were stopped.
- Resolved attempts: fixture approval must use its explicit clock and funding; stop requests cannot be in the past; held rate earnings become reversible at the authority's earning/stop boundary. Commands use the caller's operation store rather than its envelope-only store. Bare-metal fixture runway includes approval, delivery and a period. Clear inherited proxy variables for loopback tests. No production behavior was changed for these fixture/environment mistakes.
- Remaining scope is sections 4A, 4B, 5 and 6 and post-review section 7: no installed recurring delivery declaration, self-penalty remedy, watchdog or live qualification is claimed. Charged-term fixtures retain explicit buyer acceptance; default-buyer policy is unchanged. No PR, comments or canonical-branch changes were made.

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

- Unit (payments kit): `make -C kit/arkhai-payments test` — mypy clean over 28 files,
  published vectors and generated models current, 318 passed (was 287 passed and 5
  failed with 9 typing errors). New: `tests/test_presets.py` (deadline, one
  conversion, precision refusal), freshness-window and skew cases in
  `test_rate_adapter.py`, waived/unwaived approval in `test_rate_mandates.py`.
- Unit and application (buyers): VM buyer 323 passed, including
  `test_recurring_option_selection.py`, which had failed at collection, and the new
  `test_payment_approval_waivers.py`; bare-metal buyer 68 passed (was 66 and 2
  failed), the waiver test now asserting the run's policy reaches approval.
- Unit and application (storefronts): bare-metal storefront 631 passed; VM
  storefront 1194 unit passed (1 skipped) and 591 integration passed. Both
  compositions' declaration tests assert the stage carries the composition's
  declaration and the kit's wiring is installed.
- Not run in this session: the two first-use examples (`examples/rate.py`,
  `examples/preempt.py`), whose execution this step's tooling refused; `rate.py` is
  type-checked with the kit.
- The repository's change checks also moved round 1's function-local imports in
  `domains/vms/storefront/examples/preempt.py` and
  `tests/integration/test_spot_notice.py` to module level, and R3's removal of
  deal-lifecycle's "Returned treatment is not expressible" scenario is a REMOVED
  requirement with an ADDED successor, since a MODIFIED block cannot drop a scenario.
- Fresh-context compliance check of the diff against `dab8d06b8`: it found
  `preempt.py` still passing the removed `allow_unprotected_terms` to
  `BuyerTermsPolicy` (now per-term `waivers`, the charged term end and, on spot, the
  charged payee stop), two spacing slips, a VM composition comment claiming an
  invariant only the factory keeps (reworded), and untested seams: the configured
  window reaching the seller stage's adapter, the setting's bounds, `build()`
  refusing another mechanism's declaration, and the wiring reading authorities at
  each projection (tests added; payments kit 323 passed, VM `test_spot_notice.py`
  and `test_settlement_composition.py` 23 passed). Declined: moving the two new
  test files into `unit/`/`integration/` directories, since both packages' test
  roots are flat today.
- `make test`'s release tooling found `docs/development/RELEASING.md`'s dependency
  table missing `arkhai-kit-deal-lifecycle-client` for both storefronts, which
  section 4 made a runtime dependency; the rows now list it.
- `scripts/change-workflow run pre-commit`, after the owner restored a build
  environment file outside this checkout that an earlier run had found missing:
  `[change-workflow] after-functional-change at dab8d06b8…: passed, exit 0`
  (`make lock`); `[change-workflow] pre-commit-functional at dab8d06b8…: passed,
  exit 0` (`make dist-clean`, `make check-packaging`, `make test`, every suite);
  `[change-workflow] pre-commit at dab8d06b8…: passed, exit 0` (index, tasks,
  skills, OpenSpec strict, and the repository's change checks: comment hygiene,
  documentation citations, specification index, decision destinations, history
  wording, version bumps, local imports, capability index).

## 4A. Payments kit and contracts

Files: kit/arkhai-payments (adapter.py, rate_adapter.py, operations.py, seller.py,
buyer.py, mandates.py, settlement_config.py, presets.py and their tests);
kit/deal-lifecycle/src/market_deal_lifecycle/adapters.py (the protocol);
kit/deal-lifecycle-contracts (models and version); kit/deal-lifecycle-buyer and both
buyers' adapter construction; docs/development/RELEASING.md;
openspec/changes/README.md (the staged-rename gap row). Owner record points R9, R12,
R13, R15 and R19.

- [ ] 4A.1 One payments transaction adapter by composition (D11): implement the
      foundation's `PaymentAdapter` protocol from shared components (mandate binding,
      verified snapshot reads, reverse, event projection, refusal classification,
      descriptor recording) and per-part-kind behaviour (`once`: reverse, extend,
      observations; `rate`: start, stop, notice, observations, the `authorize`
      phases). A once-only mandate's `start_billing` is a no-op. Remove `_allow_rate`,
      the class choice in the seller stage and both buyers, and the stop path's
      pre-read. The protocol's `authorize` gains an optional journaled billing-start
      argument and `start_billing` takes `OperationKeys`.
- [ ] 4A.2 Descriptor recording through the caller's operation store (D4): every
      monetary rate call (start, `start_billing`, stop, notice, reverse) requires
      `OperationKeys.store` and records each descriptor's digest with
      `check_and_record` under a part-derived key before any I/O; remove the
      `journaled_digest` parameter; keep `PaymentOperation` and `describe()` exported.
      Tests: a changed retry is refused before any authority call; an identical
      retry reuses its request identity.
- [ ] 4A.3 Stop requests stay distinct, wire-compatible (D10): the lifecycle `read`
      and `list` routes omit empty `parts` and null `settles_through`; minor-bump
      `kit/deal-lifecycle-contracts`; a test validates a once-deal read against the
      0.1.0 model. Add D10's requirement to the deal-lifecycle and
      settlement-servicing deltas.
- [ ] 4A.4 The staged `approval_window` rename, release N (D9): readers of
      `arkhai.payments.v1` option parameters accept `window` and `approval_window` as
      one term and refuse both; rate options write `approval_window`; once options keep
      writing `window`; the `arkhai_payments.approval_window` discovery field replaces
      the duplicate projection, `arkhai_payments.window` kept for once options. The
      alias carries a comment stating its invariant. Add the staged-rename rule to
      `docs/development/RELEASING.md` in the owner's wording (design.md's promotion
      record), and one unowned gap row in `openspec/changes/README.md` for release
      N+1 (once writers switch) and N+2 (alias removed), joined by task 4B.2's
      `teardown` alias removal. A registry acceptance test proves rate options
      carrying `approval_window` pass the registry. Add D9 to the
      settlement-configuration delta.
- [ ] 4A.5 Kit-level tests (R19): the preset helper (setup, encoding, asset
      mismatch, beyond `tests/test_presets.py`); the watch's final-stop recording
      (`kit/deal-servicing`, unit); the composed adapter (a mixed mandate in one
      adapter, a once-only `start_billing` no-op); the alias; the 0.1.0
      compatibility. Add D11's requirement to the settlement-servicing delta.

Validation: payments, servicing, lifecycle, contracts and buyer-half unit suites and
typing; both buyers' and both storefronts' suites (the adapter is constructed in
each); `make check-architecture`.

## 4B. Surfaces, fixtures and lanes

Files: kit/deal-servicing (seller half), both storefronts' administrator routes and
typed admin clients, kit/deal-lifecycle-buyer, both buyers' end verbs and `buy`,
kit/arkhai-payments fixtures and a shared kit location for the preempt example,
`carried-tests/` and the modules it names, both compute lanes' E2E scenarios. Owner
record points R6, R11, R18, R20, R21 #48 and task 4.5a.

- [ ] 4B.1 Administrator interrupt classification in kit (D6): move the kind-to-command
      classification (preemption → `notice`, refused without a payee entitlement;
      failure → end delivery and file `delivery_end`; the reason requirement) into
      `kit/deal-servicing`'s seller half; VM's route calls it; bare metal gains the
      route and its typed admin client. Tests at unit (kit classification) and
      application (bare metal's route). Name the capability owning bare metal's route
      and add the requirement to its delta and to deal-lifecycle's.
- [ ] 4B.2 The canonical `end` verb (D6a): `bare-metal end` joins `market end`,
      registered from shared buyer code; `bare-metal teardown` is a deprecated alias
      printing a notice naming `end` for one release (its removal joins task 4A.4's
      gap row); once-only end behaviour as `teardown` had it in v0.3.0 is preserved.
- [ ] 4B.3 Fixtures on the shipped presets (D8): 4.4's fixtures use the shipped presets
      with default buyers under a lane declaration listing `returned`; the charged
      variant is a separate observation using the per-term waiver, not
      `allow_unprotected_terms`; move `preempt.py` and `preempt.lane.toml` from
      `domains/vms/storefront/examples` to a shared kit location, and update
      `docs/attachments/spot-deals-section-4/index.md`.
- [ ] 4B.4 Restore the carried tests: every case in `carried-tests/` returns to the
      module its file names, each `recurring_world` reduced to the injected servicing
      declaration and the pool's delivery deadline (the helper, timing projection,
      billing projection and payments stage are the installed ones). Where a world's
      fixture helper encoded differently from the installed one, correct the restored
      assertion only to settled behaviour and raise anything else. Delete
      `carried-tests/` and the index row's sentence about the storefront tests it
      holds once empty.
- [ ] 4B.5 The recurring-purchase E2E (D8): one scenario per compute lane, from a
      lane-only servicing declaration listing `charged` and `returned`, through
      approval against the payments double, asserting the published per-period price,
      the buyer's pre-approval display (per-period charge, setup, initial reserve,
      maximum term) and the approved mandate's single rate part charging one period's
      price, and that delivery is refused without the rate continuation. Labelled
      lane-double evidence; it closes the change index's recurring-purchase gap row.
- [ ] 4B.6 The buyer's watchdog per D6a: the probe loop in `kit/deal-lifecycle-buyer`
      with a per-domain injected probe; the opt-in flag on both domains' `buy` commands,
      which then stay in the foreground from `available` until the stop is sent, the deal
      ends or the buyer stops them; the opt-in, interval and threshold persisted per deal
      in the buyer's profile and re-entered by `buy --resume`; `monitored` / `stopped` /
      `unmonitored` in the deal read; the budget `interval × threshold + probe timeout`
      in the display. Verify in the kit's unit suite with a clock-injected probe fake
      (threshold, no stop below it, one stop and one journal entry at it, idempotent on
      restart); in one application-level test per domain that starts the real `buy
      --watch`, loses access with the storefront stopped, restarts into `buy --resume`
      and observes a single buyer stop; and in convergence's rows 1 and 2 as the buyer's
      stop landing with the storefront absent. Add D6a's watchdog to the deal-lifecycle
      delta.

Validation: deal-servicing, buyer-half and both buyers' unit suites; both storefronts'
application suites; the compose lanes with Docker and the local Helm part for 4B.5.

## 5. Identity re-anchoring

Files: kit/arkhai-payments/src/market_arkhai_payments/settlement_config.py and
adapter re-anchoring helper; kit/arkhai-payments/tests/test_settlement_config.py,
test_receipts.py as verifier consumers (not proof implementation);
lane profile configuration under e2e-tests/config. Foundation evidence stores and
convergence persist outputs through their existing ports.

- 5.1 The lane-only proposed declaration is dropped: the servicing declaration is
      treatments and a setup flag (D7), and identity is the receipt verifier's.
- [ ] 5.2 Add configured retiring identities with retirement dates alongside the
      current identity, as operator configuration with no hard-coded overlap.
      Return a fresh current-key snapshot as re-anchoring
      evidence only after foundation verification of mandate, parties, mode and
      sequence; embedded old receipt is attested by that snapshot. Gate on the
      foundation verifier accepting identity sets with validity windows, embedded
      receipt attestation and a caller-supplied minimum sequence; do not implement
      a parallel proof verifier.
- [ ] 5.3 Integrate durable anchor replacement via the evidence-store port while
      keeping original bytes; expose dependent/unanchored deals for convergence's
      status. Refuse stale-anchor rollback and mode-change re-anchoring. Document
      retirement only after rate deals re-anchor or drain and once-only deals
      drain; a deal not re-anchored when a key must retire drains first. Inventory
      all dependent hosted deals; do not claim durable once-only re-anchoring
      without a consumer. Re-anchoring evidence comes through dev's verifier
      ("Snapshot verification accepts bounded identity history"). Record in the
      settlement-configuration and settlement-servicing deltas, and in
      `docs/development/DEPLOYMENT_AND_CONFIG.md` at closeout.

Validation: configuration unit cases for retiring identities, rollback and mode
change; kit integration with an in-process engine signing under two keys across a
rate deal.
Use the foundation's verified-snapshot fixtures. Consumer persistence/restart
evidence waits for convergence; do not claim it from a stateless adapter test.

## 6. Qualification scenarios and pre-closeout review

Files: kit/arkhai-payments/test-vectors and vector runner, README.md,
examples/local_e2e.py; focused lifecycle/CLI integration suites. Convergence owns
consumer scenario files and selectors under each compute lane; activation owns
hosted-target evidence.

- [ ] 6.1 Update examples/fixtures to USD/6 without hardcoding a production asset.
      Keep published vectors content-identified and separate from double
      traces. Label evidence with test-compatibility's two labels, lane-double
      evidence and live evidence (D8); add no third.
      Run make -C kit/arkhai-payments check-vectors,
      check-generated, test-unit and typecheck as appropriate to changed seams.
- [ ] 6.2 Supply evidence metadata at the adapter/command first-use boundary:
      contract revision, target class/mode, hashes and control trace. Readiness
      gates scenario runs, not a claim that the target was prepared here.
      Record each scenario's buyer waivers; a buyer that waived a term is not
      evidence of acceptance by default buyers.
- [ ] 6.3 Reference convergence's sole consolidated rate qualification matrix
      (its design's Scenarios and evidence); do not reproduce it here. Retain
      spot's prepared fixtures and typed entry points for its executor. Activation
      owns hosted qualification.
      Consume convergence's lane-time requirements and the lane-double-owned readiness/evidence
      contract; retain adapter re-anchoring evidence production, not a second lane-time contract.
      Activation must list producer snapshot, start and reversal vectors among
      blockers to published qualification; double traces do not satisfy them.
      Check that the matrix consumes maximum-term, on-demand refusal/self-penalty filing
      and rotation-overlap preparation; report missing coverage to convergence
      rather than maintain another matrix. Require physical release/access closure rather
      than a lease_ended intent report. Promote no unrun consumer requirement here.
- [ ] 6.4 Check the changed imports, comments and public artifacts before code
      review. Move touched local imports to module level where safe, retaining
      only verified circularity or deliberate lazy-load reasons. Run focused
      domain integration and typing, then make check-packaging; fix failures
      before committing implementation.
- [ ] 6.5 Obtain pre-closeout code review. Confirm adapter/servicing ownership and
      that partialPeriod is enforceable at the payment authority, with no local
      correction substituted for the buyer's authority/dispute guarantee. Verify
      the command/preset seams here; consumer-enabled
      cross-service acceptance gates convergence and hosted live qualification
      gates activation, not this prerequisite change's archival.

Evidence levels: conformance and kit integration qualify SCM's contract use;
application integration qualifies both compositions; smoke qualifies wiring/auth;
lane e2e qualifies cross-service behavior under the declared double contract.
Only hosted qualification may claim the deployed service revision works, and only
that service's own suite establishes its ledger/payout internals.

## 7. Closeout

Documentation only, after code review, in the order required by
openspec/README.md#plan-closeout-requirements. Any required code fix returns this
change to implementation and review.

- [ ] 7.1 **Comment hygiene.** Run make check-comment-hygiene and inspect touched
      comments/docstrings for stale provenance. Do not edit code during closeout.
- [ ] 7.2 **Import placement.** Confirm touched imports are at module level unless
      a verified circularity or deliberate lazy-load reason was retained and
      reviewed; a necessary move returns to implementation.
- [ ] 7.3 **Documentation compliance.** Classify every accepted decision in D1–D8;
      keep external authority behavior as architecture context, not SCM normative
      implementation promises. Confirm adapter versus continuation ownership.
- [ ] 7.4 **Narrative compression.** Compress completed tasks to final behavior,
      material evidence, residuals and permanent destinations, preserving material
      rationale in design.md.
- [ ] 7.5 **Roadmap currency.** Update Goal 8 in docs/development/ROADMAP.md with
      both-domain rate mechanics, seller notice and the remaining continuation/
      hosted activation gap. Remove absorbed-change gap owners and record promotion.
- [ ] 7.6 **Campaign index currency.** Update openspec/changes/README.md status,
      dependencies and campaign graph; remove absorbed rows and redirect their
      dependents to this change. Run make check-change-index and record disposition.
- [ ] 7.7 **Packaging.** Run make check-packaging and
      make check-architecture-change CHANGE=spot-deals-through-arkhai-payments,
      resolving every failure/owned exception. Run make check-agent-skills if
      implementation touched agent instruction directories.
- [ ] 7.8 **End-to-end pipeline.** Record the complete pipeline run/result and
      applicable scenarios in section 6. Name exact prerequisites/owning changes
      for unrun consumer-enabled or hosted validation; do not mark them passed or
      substitute unit evidence. The rate-consumer scenarios gate convergence's
      acceptance and hosted scenarios gate activation; record their transfer here
      without making this prerequisite wait for a dependent's archival.
- [ ] 7.9 **Promotion.** Write openspec/specs/settlement-servicing/architecture.md
      (rate operations, partialPeriod and rate-only rotation), storefront-publication/
      architecture.md (presets and independent pricing), deal-lifecycle/
      architecture.md (notice, rate buyer-end flow and External authorities), test-compatibility/
      architecture.md (evidence labels), docs/development/ARCHITECTURE.md
      (Kit areas, Settlement servicing and Release, and the two principles below),
      docs/development/DEPLOYMENT_AND_CONFIG.md (servicing, `snapshot_freshness_seconds`
      and identity overlap), docs/development/RELEASING.md (the staged rename),
      and openspec/specs/README.md capability index as needed. Promote the owner's
      principles in the wording design.md's promotion record and the owner record's
      R24 settle: each change mergeable to dev on its own merits (openspec/README.md
      or docs/agents/change-workflow.md); sibling-domain parity (one line in
      AGENTS.md, "Package and dependency discipline"); the staged field rename
      (RELEASING.md); contradictory classes do not subclass one another, and a
      timestamp is its source's claim (ARCHITECTURE.md). The per-boundary
      compatibility posture is not promoted. Complete this change's design-promotion
      record. Preserve the shared mandate requirement's once clauses and archive
      after the foundation; promote rate buyer-end only in deal-lifecycle,
      referenced by buyer-orchestration. Archive writes delta-covered spec.md files
      for settlement-servicing, settlement-configuration, storefront-publication,
      deal-lifecycle, buyer-orchestration and test-compatibility.
- [ ] 7.10 **Documentation citations.** Run
      make check-doc-citations CHANGE=spot-deals-through-arkhai-payments after
      promotion and resolve every match; run
      openspec validate spot-deals-through-arkhai-payments --strict with the
      repository-pinned validator.
- [ ] 7.11 **Archival.** Run openspec archive spot-deals-through-arkhai-payments -y
      last, merging deltas; update the campaign row to the archive. Closeout
      review/triage reads the archived change and promoted permanent documents.

## Design promotion record

Planned destinations are recorded in design.md. Fill actual headings and evidence
at implementation closeout; do not promote unimplemented behavior during this
design consolidation.
