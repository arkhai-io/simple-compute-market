# Tasks — hosted compute rate parts and seller notice

Sections 1–3 are authorized for implementation on the stacked open-ended-terms base; sections 4–6 and closeout remain pending maintainer review. Work through
the sections in order, committing coherent implementation chunks. The foundation's
round-2 snapshot verifier and revised vendoring must land before rate state is
consumed. No section implements another verifier, continuation daemon or site
renewal policy.

Verification levels follow docs/development/TESTING.md. The targets below extend
the existing owning suites; select their focused cases during implementation.
New fixture/qualification coverage follows maintainer review of this plan. For the sections 1–3 assignment, checked tasks record delivered library interfaces and focused validation; the enumerated full qualification matrix remains section 6 work, not evidence claimed by those checkmarks. Full
pipeline evidence is required at closeout, not as a substitute for focused tests.

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
      `duration_seconds` before signature, including whole-second rate starts. Freeze period plus reserve_ahead_seconds and the recommended setup_amount shape with that consumer. Require the accepted rate-structure
      carrier/digest from negotiation-driven-capacity-resize gate 2.1a; refuse an
      unresolved pricing reference rather than read the current listing.
- [x] 1.3 Freeze operation descriptors, consume the foundation-owned versioned
      activation envelope (including site activation reference/instant), verified rate
      observations and rate re-anchoring output for convergence. Foundation
      in-process contract fakes cover kit library integration; the HTTP lane
      doubles gate only lane/e2e execution. No kit depends on runnable tooling.
- [x] 1.4 Obtain or explicitly gate on published signed snapshot/start/mixed-part
      vectors and partial-reversal-before/after-stop traces. Identify missing
      authority conformance evidence without replacing it with a double claim.
      Verify explicit partialPeriod on rate stop entries and rate ends on the
      returned-capable revision and dispute chosen-entry payloads. The published schema requires an inert returned partialPeriod on once ends too; preserve the foundation encoding (see dependency-contracts.md).
      Confirm delivery_end remains a dispute intent/request and mediation's
      published standard self-penalty uses its own chosen stop entry with returned.
      Producer evidence gates that package; there is no seller restitution entry
      or several-stop-entries-per-account dependency.
      Record absent treatment fields and fixed charged dispute-stop semantics on
      the interim revision; it cannot qualify returned delivery_end. Freeze
      timestamp precision and per-end partialPeriod/late-start semantics with
      the vendored contract. Unexpressible terms fail closed; never hand-edit
      generated models. The authority, not SCM, computes a returned/prorated
      partial period at the unchanged absolute end.

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
      Gate setup-bearing presets on foundation 12.1 vendoring delivery_end and both signature vectors, not another payments wire change; rate-only opt-out remains available. Verify malformed pairs, calendar periods, setup opt-out, the pending-revision refusal and insufficient lead.
- [x] 2.2 Derive setup-once then rate deterministically through the accessor and
      codec. Include rate end, afterStop hold, maxHoldExtension and exact per-part
      authorities/notices. On the returned-capable revision require partialPeriod
      on rate stop entries and rate ends; retain the inert once-end field required by the published schema;
      dispute rate stop is {account, notice: PT0S, partialPeriod: chosen} and its
      stop event supplies treatment. Keep rate start payee-only and seller stop
      entries only for accepted entitlements: spot notice, none on on-demand.
      Derive no restitution entry or implicit favourable-payee stop privilege;
      once-only options without early-termination entitlements authorize no start/stop.
      Verify setup's encoded end is Agreement start, effectively clamped to approval if later, and absolute
      capacity bounds are never extended after late activation/start. Map early_termination.settles_through
      through the foundation codec to end.partialPeriod: preset last_boundary;
      explicitly disclosed started_period for interim spot/on-demand when only charged is expressible.
      Refuse unsupported terms rather than round term durations or downgrade.
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
      seller's self-penalty for non-delivery returns it. The bare-metal preset
      ships no setup default; VM's may default to zero. Bind all terms into option
      identity; invent no amount or bare-metal minimum-spend gate.
- [x] 2.5 Supply the preset helper to the terms-owned VM/bare-metal publication
      adapters through their injected preset-helper interface; helper availability
      gates rate emission, not the terms change's archive. Do not implement generic
      option emission a second time. Prove
      accepted option plus bound rate structure survive repricing before
      materialization/restart; preserve reserved/API-credit once behavior.
- [x] 2.6 Add the materialization servicing-declaration gate: refuse undeclared
      rate servicing, including for accepted options after declaration withdrawal.
      The terms change retains publication/acceptance gate ownership.

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
      value on vendored capability at publication and acceptance; interim spot
      and on-demand use fixed charged semantics on all present entries and ends,
      with absent wire fields and no chosen-entry payload support. Qualify boundary/no-start/terms stops,
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
- E2E is **unobservable**, not passed: with the required Podman Compose provider set, the invocation-owned VM lane failed before setup with `/bin/sh: 1: docker: not found`, Makefile:240 Error 127. No stack, readiness or scenario result is claimed; no SCM containers were started.
- Resume at section 4 after maintainer code/design review; sections 4–6, full qualification and section 7 closeout are untouched. Post-review promotion remains the owning permanent specs/companions, architecture/configuration docs, roadmap and campaign index named below; this slice updates the kit README but does not archive or promote unimplemented behavior.

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
      entries, test mode and double selector. Use explicit setup opt-out for the
      interim; include priced setup fixtures only on a qualified setup revision. Document
      one runnable invocation per domain that lands on its preemption surface.
      Before convergence, use lane-only approval/command fixtures and assert
      delivery refuses without the rate hook; do not commit/deliver an unserviced
      live rate option. This fixture is the explicit lane-only door exception.
      Any interim spot or on-demand fixture must explicitly configure its buyer to accept
      started_period on the payee entitlement and any charged term end. Include
      default-buyer refusal as a separate observation; returned-capable fixtures
      may use default buyers only once the matching contract is vendored.
- [x] 4.5 Re-drive both domains' canonical rate buyer end: stop then hint, keep
      service during nonzero payer notice, and end through watch at effective
      stop. Consume foundation 7.5 round 2 (after 12.3 and 13.3) and
      buyer-orchestration's “The buyer's end is backed by its own stop or a case”
      for immediate surrender and outage handling; do not implement those paths here.
      Coordinate rate notice display.
- [ ] 4.5a **Deferred beyond Goal 8 MVP:** the foreground buyer watchdog is excluded
      from the MVP set. It would trigger an irreversible stop from reachability
      probes and would run only while the foreground buy process lives. Build no
      watchdog in this slice.
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
- 4.5a is deferred beyond Goal 8 MVP: a foreground reachability probe would trigger an irreversible stop and run only while buy remains alive. No watchdog was built.
- 4.6: separate selector commit `a0ae6148d` adds `interruption_kind=preemption|failure` beside the free-text reason. Rate requests must state it; once-only omission retains failure for existing callers. Lawful preemption requires the accepted payee entitlement and delegates notice. Failure ends delivery and files for spot and on-demand, with no automatic rate self-penalty. Both typed admin clients expose the selector and operation key; the storefront CLI has no interrupt verb.
- Permanent coverage includes exact setup/rate derivation and buyer comparison, authorization's phase table and immutable activation bindings, start/stop/reverse keys, unknown-response recovery, refusal classes, verified pending/final stop records and fixed settled figures after held reversal. Seller and buyer application tests use real SQLite, signed typed clients and injected authority doubles; canonical command tests use their own module's factory seams.
- Validation: payments 266, servicing 70, contracts 37, lifecycle client 2, buyer half 22; focused VM storefront 157 and bare-metal storefront 46; buyer suites and final packaging results are in the evidence index. Payments and servicing typing, buyer-half typing, published vectors and generated checks pass.
- Required compose VM run: `PROVISIONING_MODE=mock mise exec -- make -C e2e-tests test-e2e-vm` exits **2**: 290 pass, 2 skip, one failure in the explicitly excluded retained `rate_structure` pricing mismatch (`test_listing_shapes.py::TestStage07_ShapePricing::test_07a2_market_buy_buys_a_smaller_shape_and_reaches_ready`). It is unchanged. The owned stack, volumes/network and leftover test Anvil were stopped.
- Resolved attempts: fixture approval must use its explicit clock and funding; stop requests cannot be in the past; held rate earnings become reversible at the authority's earning/stop boundary. Commands use the caller's operation store rather than its envelope-only store. Bare-metal fixture runway includes approval, delivery and a period. Clear inherited proxy variables for loopback tests. No production behavior was changed for these fixture/environment mistakes.
- Remaining scope is sections 5–6 and post-review section 7: no installed recurring delivery declaration, self-penalty remedy, watchdog or live qualification is claimed. Charged-term fixtures retain explicit buyer acceptance; default-buyer policy is unchanged. No PR, comments or canonical-branch changes were made.

## 5. Proposed declarations and identity re-anchoring

Files: kit/arkhai-payments/src/market_arkhai_payments/settlement_config.py and
adapter re-anchoring helper; kit/arkhai-payments/tests/test_settlement_config.py,
test_receipts.py as verifier consumers (not proof implementation);
lane profile configuration under e2e-tests/config. Foundation evidence stores and
convergence persist outputs through their existing ports.

- [ ] 5.1 Consume the terms-owned proposed-declaration validator at materialization,
      for neutral lane/target validation; layer the payments-specific identity and
      livemode check here rather than assigning it to that neutral validator.
      Bind the lane-only proposed declaration's fixture payments identity to configured
      SERVICE_IDENTITY with livemode=false; refuse mismatch or production/live use.
      Keep published production enablement with activate-per-period-compute-servicing,
      gated on deployment qualification of the offered contract revision.
- [ ] 5.2 Add configured retiring identities with retirement dates alongside the
      current identity. Return a fresh current-key snapshot as re-anchoring
      evidence only after foundation verification of mandate, parties, mode and
      sequence; embedded old receipt is attested by that snapshot. Gate on the
      foundation verifier accepting identity sets with validity windows, embedded
      receipt attestation and a caller-supplied minimum sequence; do not implement
      a parallel proof verifier.
- [ ] 5.3 Integrate durable anchor replacement via the evidence-store port while
      keeping original bytes; expose dependent/unanchored deals for convergence's
      status. Refuse stale-anchor rollback and mode-change re-anchoring. Document
      retirement only after rate deals re-anchor or drain and once-only deals
      drain. Inventory all dependent hosted deals; do not claim durable once-only
      re-anchoring without a consumer.

Validation: configuration unit cases for invalid proposed composition and mode;
kit integration with the in-process contract fake rotating identities across a
rate deal.
Use the foundation's verified-snapshot fixtures. Consumer persistence/restart
evidence waits for convergence; do not claim it from a stateless adapter test.

## 6. Qualification scenarios and pre-closeout review

Files: kit/arkhai-payments/test-vectors and vector runner, README.md,
examples/local_e2e.py; focused lifecycle/CLI integration suites. Convergence owns
consumer scenario files and selectors under each compute lane; activation owns
hosted-target evidence.

- [ ] 6.1 Update examples/fixtures to USD/6 without hardcoding a production asset.
      Keep published vectors content-identified and separate from proposed
      qualification traces. Name the lane-double-owned aggregate evidence classes
      exactly: Qualification against the published contract, Qualification against
      a proposed contract, and Live evidence. Do not redefine them here.
      Run make -C kit/arkhai-payments check-vectors,
      check-generated, test-unit and typecheck as appropriate to changed seams.
- [ ] 6.2 Supply evidence metadata at the adapter/command first-use boundary:
      contract revision, target class/mode, hashes and control trace. Readiness
      gates scenario runs, not a claim that the target was prepared here.
      Record buyer acceptance-policy configuration for interim spot/on-demand evidence;
      an opted-in buyer is not evidence of acceptance by default buyers.
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
      architecture.md (evidence classes), docs/development/ARCHITECTURE.md
      (Kit areas, Settlement servicing and Release),
      docs/development/DEPLOYMENT_AND_CONFIG.md (servicing and identity overlap),
      and openspec/specs/README.md capability index as needed. Complete this
      change's design-promotion record. Preserve the shared mandate requirement's
      once clauses and archive after the foundation; promote rate buyer-end only
      in deal-lifecycle, referenced by buyer-orchestration. Archive writes delta-covered spec.md files
      for settlement-servicing, settlement-configuration, storefront-publication,
      deal-lifecycle and test-compatibility.
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
