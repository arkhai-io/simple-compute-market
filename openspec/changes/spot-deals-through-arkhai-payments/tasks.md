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
      shared parts in the new `transaction.py` (`VerifiedSnapshots`,
      `record_descriptors`, `classify_failure`, `recorded_by`), rate behaviour in
      `rate_parts.py` (`RateParts`, renamed from `rate_adapter.py`; no adapter class),
      composed in when the mandate has a rate part. `RatePaymentAdapter`,
      `_allow_rate`, `operations_digest` and both buyers' and the seller stage's class
      choice are gone. The protocol (`kit/deal-lifecycle`) is
      `authorize(phase, evidence, billing: JournaledBillingStart | None = None)` and
      `start_billing(keys: OperationKeys, evidence)`; `OnceDeliveryPolicy`, the
      Alkahest adapter and end service follow. End service builds the keys over its
      own `SQLiteOperationStore` and passes the journaled billing start at disclosure
      only. Every pre-read is gone, the once reverse's too: a stop the authority
      answers with an already winning stop is accepted only when that stop is
      effective no later (D4's repeated-stop rule, now applied after the send).
      Tests: payments `test_payment_adapter.py` (unit, a mixed mandate in one adapter,
      a once-only no-op billing start, once-only refusal of every rate command, a
      changed stop retry refused before any call, a seller stop answered by the
      payer's earlier winning stop accepted with that stop's record),
      `test_rate_adapter.py` updated (unit); deal-lifecycle `test_adapters.py`,
      Alkahest `test_payment_adapter.py` (unit); servicing `test_end.py` (library
      integration, real SQLite: the billing keys carry a `SQLiteOperationStore` over
      the journal's own database, which refuses a changed digest; once the intent is
      journaled, commit, dispatch and start receive no billing start and disclosure
      receives its key and recorded result).
- [x] 4A.2 Descriptor recording through the caller's operation store (D4): every
      monetary rate call (start, `start_billing`, stop, notice, reverse) requires
      `OperationKeys.store` and records each descriptor's digest with
      `check_and_record` under a part-derived key before any I/O; remove the
      `journaled_digest` parameter; keep `PaymentOperation` and `describe()` exported.
      Tests: a changed retry is refused before any authority call; an identical
      retry reuses its request identity.
      As built: the key is `keys.part_event(part, "<kind>-descriptor")`. A rate
      deal's operations refuse without a store. A once-only reverse records when a
      store is supplied (`submit_payment` always supplies one) and otherwise relies
      on the authority's `request_id_reused`: the seller's refund path
      (`PaymentSellerStage.reverse_now`) holds no store and calls the adapter's
      synchronous `submit_now`, which refuses for a rate deal, as it already did.
      Tests: unit, `test_rate_adapter.py` (changed reverse refused with no
      `reverse` call; identical start retry resends one request identity) and
      `test_payment_adapter.py` (changed stop retry: no send, no read).
- [x] 4A.3 Stop requests stay distinct, wire-compatible (D10): the lifecycle `read`
      and `list` routes omit empty `parts` and null `settles_through`; minor-bump
      `kit/deal-lifecycle-contracts`; a test validates a once-deal read against the
      0.1.0 model. Add D10's requirement to the deal-lifecycle and
      settlement-servicing deltas.
      As built: the omission lives in the contracts, so every producer of the wire
      shape omits them: `ReleasedReadShape` drops `PaymentEvent.settles_through`,
      `AuthorityView.parts` and `DealSummary.parts` at their defaults when dumped;
      contracts 0.1.0 → 0.2.0. Tests: contracts `test_released_reads.py` (unit,
      against `released_0_1_0.py`, a frozen copy of 0.1.0's read and list models: a
      once-deal read and list validate, a reader of 0.2.0 restores them exactly, a
      rate observation is refused by 0.1.0). Deltas: deal-lifecycle "Stop requests are
      distinct from final stops, readable by released clients"; settlement-servicing
      "Rate stop requests are projected apart from final stops".
- [x] 4A.4 The staged `approval_window` rename, release N (D9): readers of
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
      As built: `PaymentsOptionParams.one_approval_term` refuses a document giving
      both a value (even when they agree), `approval_term` reads either; a null
      names neither, since the VM publication path dumps its validated clause input
      with the unset name as null (the VM storefront's
      `test_a_once_payment_option_publishes_its_clause_s_deadline_where_the_pool_supplies_none`
      failed until the reader allowed it); the once option
      builder writes `window` whatever its clause named; `arkhai_payments.window`
      projects only for once options. No released document carried both names:
      `approval_window` is new since `dev`. The gap row is under "Unowned work found
      by `spot-deals-through-arkhai-payments`" and names only the rename; 4B.2 adds
      the `teardown` alias's removal to it. Tests: payments `test_approval_window.py`
      (unit); registry `test_listings.py::test_rate_option_naming_approval_window_round_trips`
      (application integration, the registry app through its typed client). Rate
      fixtures carrying both names were corrected: payments `rate_terms.py`, VM
      `test_lifecycle_admin.py`, bare-metal `test_spot_notice.py`.
- [x] 4A.5 Kit-level tests (R19): the preset helper (setup, encoding, asset
      mismatch, beyond `tests/test_presets.py`); the watch's final-stop recording
      (`kit/deal-servicing`, unit); the composed adapter (a mixed mandate in one
      adapter, a once-only `start_billing` no-op); the alias; the 0.1.0
      compatibility. Add D11's requirement to the settlement-servicing delta.
      As built: `test_presets.py` gains encoding under the option identity with and
      without setup, `approval_window` written whichever name the clause used, the
      asset-mismatch refusal and the timing projection (unit). The watch's
      final-stop recording is `kit/deal-servicing/tests/integration/test_final_stop.py`,
      library integration rather than unit: the watch persists through its own
      SQLite path, and `TESTING.md` puts a test against a real embedded database in
      `integration/` (a pending request records no end; a maturity with no new
      sequence records once; a changed replay is refused). Delta:
      settlement-servicing "One payments transaction adapter serves every part kind
      by composition", and deal-lifecycle's MODIFIED "Neutral delivery decisions
      delegate payment interpretation" for the protocol.

Validation: payments, servicing, lifecycle, contracts and buyer-half unit suites and
typing; both buyers' and both storefronts' suites (the adapter is constructed in
each); `make check-architecture`.

## Section 4A notes and handoff

- Versions, each one step from `dev`: `arkhai-kit-deal-lifecycle-contracts` 0.2.0,
  `arkhai-kit-deal-lifecycle` 0.4.0 (protocol), `arkhai-kit-arkhai-payments` 0.8.0
  (`RatePaymentAdapter` and `operations_digest` removed), `arkhai-kit-deal-servicing`
  0.3.0, `arkhai-kit-alkahest` 0.13.0. The bare-metal storefront's and buyer's exact
  `arkhai-payments` pins moved to 0.8.0; the VM storefront, VM buyer and compute
  delivery raised their bounds to 0.8.0. Every package implementing or calling the
  protocol raised its bounds to deal-lifecycle 0.4.0, and the composers of end
  service and the Alkahest adapter (both storefronts, compute delivery) to
  deal-servicing 0.3.0 and Alkahest 0.13.0. The domain packages whose bounds moved
  keep their versions, as for their earlier edits in this change.
- Event projection rule, decided here: in a once-only mandate a part's stop stays the
  deal's payment end (`kind="stop"`, as before); beside a rate part every raw stop is a
  `stop_request`, the setup part's terms end at Agreement start included, which the
  once rule would otherwise have recorded as the deal's end. Whole-part reverse amount
  inference now applies to every once part, the setup part in a mixed mandate too.
- Refusal reasons now begin with the authority's code (`insufficient_held_funds: …`,
  `hold_matured: …`), which the seller's refund classification matches by code.
- End-to-end scenarios exercising this section once deployed: the once-deal payment
  scenarios on the composed adapter's once path and the lifecycle read wire —
  `e2e_vm_payment_deal`, the six `e2e_vm_dispute_*`, `e2e_vm_payment_purchase`,
  `e2e_bare_metal_payment_deal`, `e2e_credits_payment_deal`. None exercises a rate
  deal; 4B.5 adds the recurring purchase. Owed by validation: none.
- `build-constraints.txt` at the repository root, the build-requirement pins every
  `uv build` reads through `UV_BUILD_CONSTRAINT`, is committed with this section,
  byte-identical to `dev`'s (commit `cd2506b76`), on the owner's direction: this
  branch's builds need it and `dev` has it, so the merge sees two identical adds.
- Evidence: payments kit `make test` (mypy 29 files, vectors, generated models)
  345 passed; deal-lifecycle 82; contracts 40; servicing 74; Alkahest 465; buyer half
  22; compute delivery 126; VM buyer 323; bare-metal buyer 68; bare-metal storefront
  631; VM storefront 1194 unit (1 skipped) and 591 integration, after
  `test_spot_notice.py` was corrected to the new retry (an identical retry resends
  under one request identity: two sends, one recorded stop); registry
  `test_listings.py` round-trip tests 2; `make check-architecture` and
  `make check-comment-hygiene` pass. Not run here: the payments first-use examples
  (`examples/rate.py`, VM `examples/preempt.py`), whose execution this step's tooling
  refuses; `rate.py` is type-checked with the kit.
- The fresh-context compliance check found: stale locks and unrun storefront suites
  (relocked by the pre-commit hook; suites run, above); composers' lower bounds below the new protocol (raised); two
  overstated `test_end.py` claims (the test now proves both); planned behaviour and
  a version note in the deltas (removed); decisions only in these notes (recorded in
  design.md D10 and D11); docstrings claiming recording for every operation
  (qualified); "still" in a comment (removed); no test of the post-send repeated-stop
  rule (added); a test importing another module's private helper (made local).
  Declined: moving the kit's tests into `unit/`/`integration/`, a restructuring of
  the whole flat test root recorded as an unowned gap in `openspec/changes/README.md`;
  a route-level test of the read omission, since the routes dump these models and the
  model test proves the shape.

## 4B. Surfaces, fixtures and lanes

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
      `interrupt_operation_key` (the key derived from the request when the caller
      sends none, the same digest VM's route derived) and `SellerServicing.interrupt`
      (the administrator evidence item under the operation's key, then notice, or the
      journaled operator end with filing and the injected `physical` drive run side by
      side), returning `InterruptResult(kind, outcome, delivery)` with its
      `settlement_action`. A rate deal is recognised by `SellerDeal.once_only`, the
      committed projection, rather than the Agreement's `period`. VM's
      `VmDealLifecycle.interrupt` and its route delegate to it. Bare metal gains
      `POST /api/v1/admin/deals/{negotiation_id}/interrupt` (payments deals only, 409
      for any other mechanism, 400 for a caller-supplied time) with
      `BareMetalInterruptDealRequest`/`Response`; the canonical
      `StorefrontClient.admin_interrupt_deal`, sync and async, already signs this route
      and exposes the kind and key, so it is bare metal's typed admin client unchanged.
      The capability owning both routes is `compute-delivery` (new delta "Both compute
      storefronts mount the administrator interrupt route"); the deal-lifecycle delta's
      "Administrator interruption explicitly classifies its cause" now names the kit
      classification and the attribution refusal. Tests: deal-servicing
      `tests/unit/test_interrupt.py` (unit: each kind, the once-only default, every
      refusal, the derived key); bare-metal storefront
      `tests/integration/test_admin_interrupt.py` (application integration, the
      composed app through the canonical storefront client: a preemption's dry run
      records nothing and its send leaves a pending stop, no end or filing; a failure
      records the operator end with its reason and journals a `delivery_end` filing
      with cause payee; a same-key retry changing the reason is 409; a caller-supplied
      time is 400; an unclassifiable request is 409 with nothing recorded). The 409 for
      a non-payments deal is untested: the harness composes no Alkahest deal. VM's
      `test_lifecycle_admin.py` passes unchanged against the delegated path. The
      deal-lifecycle MODIFIED "Lifecycle routes are authenticated per role" now defers
      to the classification for both storefronts' route.
- [x] 4B.2 The canonical `end` verb (D6a): `bare-metal end` joins `market end`,
      registered from shared buyer code; `bare-metal teardown` is a deprecated alias
      printing a notice naming `end` for one release (its removal joins task 4A.4's
      gap row); once-only end behaviour as `teardown` had it in v0.3.0 is preserved.
      As built: `market_deal_lifecycle_buyer.commands.register_end_command` registers
      `end` (and an optional deprecated alias) from an `EndTarget` the domain opens for
      a run; `end_deal` ends, then always reads the delivery back once and polls to
      `--wait-timeout`; `end_exit_code` keeps VM's exit rule. Run options accept
      `--from`, `--run`, `--run-id` and `-r`, so both domains' existing spellings work;
      `--config` exists where the domain reads one (bare metal). The output is VM's
      shape (`progress`, `delivery_view`, `capacity_released`, `delivery_read_error`),
      and both domains record `delivery_end` and `delivery_end_observed` in the run
      log. `bare-metal teardown` prints its notice on stderr and keeps the output its
      callers parse: the end's progress alone on stdout, exit 0 whatever the outcome.
      Beside v0.3.0 the progress carries the `mode` and `hint` later rounds added, a
      `ValueError` exits 2 through `BadParameter`, and the alias writes the run-log
      events; all are additive for a caller parsing stdout.
      A once-only end still goes through `BuyerLifecycle.end`, which for a non-rate
      deal is the `end_delivery` v0.3.0's `teardown` called. `arkhai-kit-deal-lifecycle-buyer` 0.1.0 → 0.2.0
      (earlier sections changed it without a bump); both buyers and `e2e-tests` raised
      their bound. The e2e bare-metal purchase and real-host scenario now run `end` and
      read `result["progress"]`; `RECOVERY_COMMANDS` names `end`. Deltas:
      buyer-orchestration MODIFIED "Compute buyers end delivery through the canonical
      lifecycle client"; test-compatibility MODIFIED for the two bare-metal purchase
      requirements naming the verb; deal-lifecycle's rate buyer end names the shared
      verb. The gap row now carries the alias's removal. `TESTING.md`,
      `e2e-tests/README.md`, `VALIDATION_RUNBOOK.md` and the kit README name `end`;
      the deal-lifecycle and buyer-orchestration companions are closeout's (design.md's
      record). Tests: buyer half `tests/unit/test_end_command.py` (unit: one read
      without a wait, a fake-time wait to release, an unavailable read, the exit rule,
      the alias's preserved output and exit code); bare-metal buyer
      `test_rate_end_cli.py` (unit, `end` and `teardown` through the command module's
      `end_target` factory with a mocked lifecycle: surrender forwarded, the record
      hook called, each verb's output, the notice only on the alias); VM
      `test_rate_end_cli.py` unchanged. The bare-metal storefront's
      `test_the_buy_command_settles_over_a_run_log_a_later_command_reloads`
      (application integration, the real buyer CLI against the composed storefront)
      runs `teardown` twice over a once-only deal through the real `end_target` and run
      log, and checks the two progress outputs' `observed_at` and receipt agree: the
      once-only end, the progress-only shape and exit 0. VM's test patches
      `end_context`, beneath its real `end_target`. No test reads the recorded run-log
      events back.
- [x] 4B.3 Fixtures on the shipped presets (D8): 4.4's fixtures use the shipped presets
      with default buyers under a lane declaration listing `returned`; the charged
      variant is a separate observation using the per-term waiver, not
      `allow_unprotected_terms`; move `preempt.py` and `preempt.lane.toml` from
      `domains/vms/storefront/examples` to a shared kit location, and update
      `docs/attachments/spot-deals-section-4/index.md`.
      As built: `kit/deal-servicing/examples/preempt_first_use.py` and its
      `preempt.lane.toml`, beside the kit's other seller first uses, in its `first-use`
      target. The declaration lists `charged` and `returned`: the shipped presets
      return on the payee's stop and at the term end, and the payer's stop always
      charges its started period, which the declaration check reads too. A default
      buyer approves both shipped options; the charged spot variant is refused by a
      default buyer and approved by one waiving `charged_term_end` and
      `charged_preemption`. A kit cannot import a domain, so the first use drives
      `SyncSellerLifecycleClient.notice`, the client both `deals preempt` verbs
      delegate to, instead of each domain's CLI; both CLIs' delegation stays proven by
      the VM storefront's `tests/integration/test_spot_notice.py`, which installs the
      bare-metal storefront and drives each domain's `deals preempt`. The examples
      keep `USD/2` until task 6.1 moves fixtures to `USD/6`. The dropped
      `one_seller_stop` count no longer held since
      4A's identical retry resends. `arkhai-core-storefront-client` joins the kit's dev
      group (the seller client signs through it). Test:
      `kit/deal-servicing/tests/integration/test_preempt_first_use.py` (library
      integration: runs the entry point's `main` on its profile, real SQLite and the
      in-process routes) — this step's tooling refuses running examples directly.
- [x] 4B.4 Restore the carried tests: every case in `carried-tests/` returns to the
      module its file names, each `recurring_world` reduced to the injected servicing
      declaration and the pool's delivery deadline (the helper, timing projection,
      billing projection and payments stage are the installed ones). Where a world's
      fixture helper encoded differently from the installed one, correct the restored
      assertion only to settled behaviour and raise anything else. Delete
      `carried-tests/` and the index row's sentence about the storefront tests it
      holds once empty.
      As built: `tests/recurring_world.py` returns to each storefront (VM
      `domains/vms/storefront/tests/`, bare metal `domains/bare_metal/storefront/tests/`)
      without its fixture helper, term timing, billing projection or accepted-data
      placeholder. Each world now supplies only what a deployment configures: the
      declaration, the pool's deadline and the penalty multiple, which a carried
      case sets. The declaration is one mutable mapping behind one `RateServicing`,
      which publication, acceptance and the stage all read. The VM world leaves
      `rate_preset_helpers` and `rate_term_projections` unset, so
      `VmSettlementComposition` installs `payments_rate_wiring`, and it leaves
      `project_billing` to the negotiation runtime's default, the registry's.
      `VmSettlementComposition` builds no stage of its own; bare metal's builds one in
      `__post_init__`. So the VM world builds the stage itself with
      `servicing_stage(..., rate_servicing=)` over the declaration, the call
      `build_vm_settlement_composition` makes. If the root stopped making that call,
      no VM test would notice. Building the stage in VM's composition, as bare metal
      does, is a production change outside this task, left for the round's review. `tests/publication_app.py` now
      hands the composition's `arkhai_payments_stage` to the negotiation runtime, as
      `server.py` does (the composition double has none, so other tests see `None` as
      before). The VM world keeps `accepted_obligation_dispatch={payments: None}`,
      which is the entry the composition's own dispatch gives payments, since only
      contact exchange registers an accepted-obligation builder. The bare-metal world
      replaces the configured composition with `rate_preset_helpers=None` and
      `rate_term_projections=None`, so `__post_init__` reinstalls the kit's wiring
      over the world's dispute policy: copied, the configured composition's wiring
      would read the authorities of the dispute policy it was built with.
      No restored assertion needed correcting. The installed helper writes
      `approval_window` where the fixture wrote `window`, which changes option IDs
      and settlement bytes, but no case asserts either. One restored call changed
      its input. The VM shape-priced case's `verify_pricing_acceptance` takes the
      installed buyer projection, `buyer_settlement_registry().project_billing`, in
      place of the fixture `billing`. The carried comment saying the production
      buyer client cannot open these negotiations, because the installed payments
      projection refuses rate parameters, was dropped: that projection now projects
      a complete pair `per_period`. The cases still open through the storefront's
      typed client. The
      shape-priced case passes the installed helper's explicit-price check because
      publication composes the clause's rate from the family rates before the helper
      reads it. The fixture's `SHAPE_RATE` fallback was therefore never needed.
      Placement: VM `test_publication_loop.py` takes five cases and
      `test_buyer_selection_negotiation.py` takes three; bare-metal
      `test_http_publication_rates.py` takes four and `test_http_negotiation.py` takes
      two. Each restored deadline case replaces its module's once-only
      `test_a_once_payment_option_publishes_its_clause_s_deadline_where_the_pool_supplies_none`,
      as `carried-tests/README.md` directed: the restored case covers the once
      option too. The bare-metal module's payments fixtures that served only that test
      went with it. The lowest-level tests the README listed stay. The docstrings of the two
      `test_a_cached_rate_option_whose_treatment_is_withdrawn_is_refused_through_the_app`
      tests and their composition helpers no longer claim that no mechanism publishes
      a rate option or that no encoder is composed. `carried-tests/` is removed
      (`git rm`), and so is the index row's "Holds the storefront tests …" sentence.
      Raised, not changed: those two seeded tests keep their database-seeded option,
      as R6 directs. `TESTING.md` prefers service-internal setup only where the state
      is unreachable through an API, and publication now reaches it: each
      restored cached-recurring case publishes the option and then narrows the
      declaration. Each seeded test now duplicates a restored case at the same level,
      on the same door with the same assertions. Removing both is the triage's call.
      Tests, application integration (each served storefront app through its typed
      clients, real SQLite, the installed recurring encoder and term timing): bare
      metal's restored cases reach publication and the selection door only, since both
      of its negotiation cases are refusals. The VM world also reaches acceptance
      through the stage it builds, in two buyer-selection cases and the accepted half
      of the third. VM storefront
      `make -C domains/vms/storefront test-integration` 598 passed (was 591: nine
      restored items added and the two parametrized once-deadline items removed);
      bare-metal storefront `uv run pytest` after `make -C domains/bare_metal/storefront reinit`
      641 passed (was 636: seven restored items added, two removed). Every restored
      item is named PASSED in the verbose output.
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

## Section 4B notes and handoff

- Stopped after 4B.3 on the session's size: 4B.4 (eight carried cases and two
  `recurring_world` modules, about 680 lines of fixtures to reduce), 4B.5 (a scenario
  per compute lane) and 4B.6 (the watchdog across the buyer half, both `buy`
  commands, the profile and the deal read, with an application test per domain) are
  unstarted, and each is a session's work on its own. The owner accepted the split:
  4B.1–4B.3 are committed on their own, and 4B.4, 4B.5 and 4B.6 each take a fresh
  session, from section 4B's first unchecked task, before sections 5 and 6.
- 4B.4 has a commit of its own; 4B.5 and 4B.6 remain, each for its own session.
  For 4B.5, the VM world's acceptance cases show what a recurring option needs from
  a served storefront with the installed wiring:
  - a servicing declaration listing `charged` and `returned`;
  - a dispute entry advertising payments;
  - a payments section with a service URL and receipt identity, so the stage exists
    to derive acceptance data;
  - the token cache payments readiness reads.

  Bare metal's restored cases stop before acceptance, so they show none of this for
  its stage.
- End-to-end scenarios exercising 4B.4: none. It restores storefront tests and
  changes no deployed behaviour. Owed by validation: none.
- Evidence for 4B.4: the suites in its task note, then `scripts/change-workflow run
  pre-commit`. after-functional-change (`make lock`) passed with no lock change;
  pre-commit-functional (`make dist-clean`, `make check-packaging`, `make test`,
  every suite) passed; pre-commit (index, tasks, skills, OpenSpec strict, `make
  check-repository`) passed. A second full run after the fresh-context check's
  fixes passed all three hooks too, with VM storefront integration 598 passed and
  the bare-metal storefront 641 passed. Only `tasks.md` notes changed after that
  run.
- The 4B.4 fresh-context check found no blocking breach. It found:
  - the VM world's docstring claiming the composition installs the stage and the
    billing projection (reworded);
  - a restored cached case comparing a row count where the carried case compared
    rows (restored to rows, with the carried `_negotiation_rows` helper);
  - the shape-priced case's changed billing input and the dropped carried comment,
    both undisclosed (now in the task note);
  - note claims broader than the tests: the declaration reaching acceptance and
    the stage, and "installed wiring" for bare metal, which reaches no acceptance
    (narrowed);
  - the two seeded cached-rate tests no longer meeting `TESTING.md`'s exception
    for service-internal setup (raised in the task note for the triage, kept per
    R6; their docstrings now state the setup without claiming the exception);
  - the VM stage being built by the world rather than by the composition
    (recorded in the task note as a production follow-up).

  Declined: removing the duplicate payments constants and composition helpers that
  the seeded tests' modules keep beside the world's. They serve those kept tests,
  and folding them into the world would rewrite tests R6 keeps unchanged.
- Never run a kit's or the VM storefront's tests with a plain `uv run pytest`: without
  `--find-links` uv relocks the project against PyPI's released internal packages (it
  rewrote the buyer half's lock to contracts 0.1.0 until `make lock` restored it), and
  the VM storefront's resolution fails outright. Run `make -C <package> test` (or its
  `test-unit`/`test-integration`), after `make dist` when a kit changed. `uv run
  --no-sync`, `uv run --find-links …`, `git restore` and `git checkout --` are refused
  by this step's tooling; `cd domains/bare_metal/storefront && uv run pytest <files>`
  after `make -C domains/bare_metal/storefront reinit` works.
- End-to-end scenarios exercising 4B.1–4B.3 once deployed: `e2e_vm_payment_deal` and
  `e2e_vm_dispute_lost_filing` call the VM interrupt route, now over the kit
  classification; `e2e_bare_metal_payment_deal` and `e2e_bare_metal_qualification`
  end their purchases with `market bare-metal end` and read its `progress`;
  `e2e_bare_metal_deal`, which no lane selects (it needs a real host), recovers with
  `end` too. No lane scenario calls bare metal's new interrupt route or a rate deal.
  Owed by validation: none.
- Evidence for 4B.1–4B.3, after `make dist` and relocking: deal-servicing 86;
  buyer half 27; VM buyer 323; bare-metal buyer 71; VM storefront 1194 unit (1
  skipped) and 591 integration; bare-metal storefront 636. Then
  `scripts/change-workflow run pre-commit`: after-functional-change (`make lock`)
  passed; pre-commit-functional (`make dist-clean`, `make check-packaging`, `make
  test`, every suite) passed; pre-commit (index, tasks, skills, OpenSpec strict,
  `make check-repository`: comment hygiene, citations, specification index, decision
  destinations, history wording, version bumps, local imports, capability index)
  passed. The first pre-commit run failed on the bare-metal storefront's buy-and-
  teardown test, which parses `teardown`'s progress-only output, and on MODIFIED
  deltas missing permanent scenarios; the alias now keeps that output and the deltas
  carry every scenario. Docstring, help-text and wording edits after that run
  (the alias's help, `SellerServicing.interrupt`'s raises, a test comment) were
  followed by the buyer half's suite only; the commit's own pre-commit run covers
  them.
- 4B.5 is not started: its premise does not hold, so the change returns to design.
  The task and test-compatibility's "A buyer approves a recurring option" both
  require the scenario to assert that delivery is refused without the rate
  continuation. The design says the same: "delivery fails closed without the rate
  hook" ("Dependencies and ownership"). No code refuses it, and the delivery path
  has no rate-hook seam to refuse at. Once a lane declares
  `[Settlement.rate_servicing.arkhai_payments] treatments = ["charged",
  "returned"]`, a recurring purchase would be delivered:
  - Materialization admits it. `PaymentSellerStage.settlement_data` derives the
    mandate under the composition's declaration
    (`kit/arkhai-payments/src/market_arkhai_payments/seller.py:203`).
  - The storefront starts delivery on a verified receipt with no rate check
    (VM `VmPaymentsCoordinator.start` → `_provision`,
    `domains/vms/storefront/src/market_storefront/payment_settlement.py:182`).
  - The shared path authorizes each phase with whatever payment adapter the domain
    port supplies, `adapter=deal.accepted.payment`
    (`domains/compute/delivery/src/compute_delivery/path.py:884`). For a rate
    mandate that is the composed `PaymentAdapter`: VM's
    `VmDealLifecycle.payment_adapter`, bare metal's `lifecycle.py:109`.
  - `RateParts.authorize` allows commit on a timely approval, and allows dispatch
    and start on a verified initial reservation
    (`kit/arkhai-payments/src/market_arkhai_payments/rate_parts.py:255`).
  - End service journals the billing start and calls `start_billing`
    (`kit/deal-servicing/src/market_deal_servicing/end.py:182`). The lane's
    payments double, which runs the vendored engine, would start the rate.

  A search of `domains/compute/delivery`, both storefronts and
  `kit/deal-servicing` for a rate hook, a continuation gate or a rate check at
  delivery finds none. The comment in VM's `test_lifecycle_admin.py`'s
  `approve_rate` ("the installed delivery hook stays closed") refers to a fixture
  that skips delivery. Nothing was run: the conclusion is from the code. What
  design must decide:
  - **A fail-closed door in end service (recommended).** `kit/deal-servicing`'s
    `EndService.authorize_delivery` refuses a deal registered as not once-only
    (`SellerDeal.once_only`) unless the composition installs a rate continuation.
    It refuses at commit, before any dispatch, and names its reason. Convergence
    installs the continuation in place of the door. The door is
    mechanism-neutral, sits where convergence's rate servicing will live, and is
    shared by both domains. It needs a requirement in the deal-lifecycle or
    settlement-servicing delta, a library-integration test, and design text
    saying where "fails closed" is enforced.
  - **A door in each storefront's payments settle path**, before provisioning.
    Each domain would duplicate it, against the sibling-parity principle.
  - **Re-scope the scenario to end at approval**, with no commit, and reword the
    delta's "delivery is refused" clause. This needs a buyer path that approves
    without committing; neither buyer's was checked for one.
  - **Let the scenario run through rate delivery.** That is convergence's row 0,
    outside this change.

  Whichever is chosen, the scenario's cleanup needs a rule of its own. The seller's
  refund (`PaymentSellerStage.reverse_now` → `submit_now`) refuses a rate deal,
  so the buyer's own payer stop has to release the unearned reservation.
  Shipped presets carry no setup charge, so nothing else would stay held.
  Findings that still hold for the scenario: a lane publishes a recurring option
  through a payments publication clause carrying `recurring: {period,
  reserve_ahead_seconds[, payee_notice_seconds]}`, from a pool override or VM's
  listing creation; both go through `ClausePublication.publish`. The clause's
  approval `window` must leave runway, since approval window + delivery deadline +
  period must fit within `max_duration_seconds`; VM's purchase states `P7D` as its
  `window`, which leaves none for a one-hour listing. The buyers print the
  pre-approval display on stderr: the "Accepted Agreement: price, horizon and
  lifecycle terms before approval" rows from `compute_disclosure` ("Accepted
  price … per_period", "Setup once charge", "Initial reserve", "Maximum accepted
  end"). The harness's `MarketRun.stderr()` reads it once the command exits.
- `bare-metal-and-credits-domain-stacks` has a buyer-orchestration delta requiring
  `market bare-metal teardown --from <run_id>`; whichever of the two changes lands
  second reconciles it with `end` and the alias.
- The fresh-context check's findings declined: a third copy of the run-on-a-thread
  helper (`_run` in the buyer half beside each domain's `run_sync`), since moving the
  domains' other commands onto it is outside these tasks; bare metal's route answers
  422 for VM's Alkahest payout fields, which it does not model, where VM answers 400;
  the canonical `admin_interrupt_deal` returns a dict rather than a validated model,
  as every admin method of that client does; the first use's `market_core` and
  `market_settlement_runtime` arrive through the payments kit rather than the dev
  group.

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
