# Tasks — hosted compute rate parts and seller notice

This is a design-stage plan; no implementation tasks are complete. Work through
the sections in order, committing coherent implementation chunks. The foundation's
round-2 snapshot verifier and revised vendoring must land before rate state is
consumed. No section implements another verifier, continuation daemon or site
renewal policy.

Verification levels follow docs/development/TESTING.md. The targets below extend
the existing owning suites; select their focused cases during implementation.
New fixture/qualification coverage follows maintainer review of this plan. Full
pipeline evidence is required at closeout, not as a substitute for focused tests.

## 1. Confirm dependency gates and freeze the consumer interface

Files: kit/arkhai-payments/schema/SOURCE.md, schema/payments.schema.json,
test-vectors/payments.json; the lifecycle adapter protocols supplied by the
foundation; this design's D1–D7.

- [ ] 1.1 Confirm agreed-evidence-and-early-termination supplies the codec, command
      contracts, hosted once adapter, evidence-store/journal seam, per-part contract
      vendoring and round-2 verified-snapshot interface. Record the actual schema
      and vector hashes. Do not edit generated models to mimic an unvendored contract.
- [ ] 1.2 Confirm negotiate-open-ended-compute-terms supplies the price accessor
      with its period unit, common term shape, listing bounds and two front-door
      servicing gates. Freeze period plus reserve_ahead_seconds and the recommended
      setup_amount shape with that consumer. Require the accepted rate-structure
      carrier/digest from negotiation-driven-capacity-resize gate 2.1a; refuse an
      unresolved pricing reference rather than read the current listing.
- [ ] 1.3 Freeze operation descriptors, ActivatedDeliveryRef, verified rate
      observations and rate re-anchoring output for convergence. Foundation
      in-process contract fakes cover kit library integration; the HTTP lane
      doubles gate only lane/e2e execution. No kit depends on runnable tooling.
- [ ] 1.4 Obtain or explicitly gate on published signed snapshot/start/mixed-part
      vectors and partial-reversal-before/after-stop traces. Identify missing
      authority conformance evidence without replacing it with a double claim.
      Verify required partialPeriod on every stop entry and part end, dispute
      chosen-entry payloads and the confirmed own-term setup mapping. Freeze
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

- [ ] 2.1 Add paired period/reserve_ahead_seconds validation, fixed-unit/positive
      constraints, optional setup_amount, the finite term requirement and
      explicit end_partial_period, whole-second rate Agreement start and
      partialPeriod capability check. Reject fractional rate starts rather than
      rewriting signed Agreement bytes; once-only rounding stays unchanged.
      Keep approval_window distinct from adjudication.
      Verify malformed pairs, calendar periods, setup opt-out and insufficient lead.
- [ ] 2.2 Derive setup-once then rate deterministically through the accessor and
      codec. Include rate end, afterStop hold, maxHoldExtension and exact per-part
      authorities/notices. Require partialPeriod on every stop entry and part end;
      dispute rate stop is {account, notice: PT0S, partialPeriod: chosen} and its
      stop event supplies treatment. Keep start payee-only; omit payee stop on on-demand.
      Verify setup end is activation, and absolute capacity bounds are never
      extended after late activation/start. Map end_partial_period to the end's
      partialPeriod: intended preset returned; recommend explicitly disclosed
      charged for interim spot/on-demand when only charged is expressible.
      Refuse unsupported terms rather than round term durations or downgrade.
- [ ] 2.3 Extend the buyer's exact mandate check for mixed parts, ordering, price,
      asset, hold, cap and stop authorities. Verify explicit zero payer notice is
      preserved exactly. Use the foundation's notice_seconds/settles_through
      authority mapping; reject retired exposure_seconds and stop+exposure.
      Consume the terms-owned buyer acceptance policy: by default refuse payee
      entitlement or term end unless settles_through is last_boundary, naming the
      offending term. Verify explicit buyer opt-in can accept started_period;
      do not mistake an exact mandate match for policy acceptance.
- [ ] 2.4 Supply default setup-bearing on-demand/spot presets with explicit setup
      pricing and seller opt-out. Bind setup and rate terms into option identity.
      Do not invent a setup amount or impose a bare-metal minimum-spend gate.
- [ ] 2.5 Supply the preset helper to the terms-owned VM/bare-metal publication
      adapters; do not implement generic option emission a second time. Prove
      accepted option plus bound rate structure survive repricing before
      materialization/restart; preserve reserved/API-credit once behavior.
- [ ] 2.6 Add the materialization servicing-declaration gate: refuse undeclared
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
hosted adapter module and new operations.py;
kit/arkhai-payments/tests/test_client.py, test_seller.py and
tests/integration/ for real journal consumers injected at the public adapter seam.
Journal persistence itself belongs to convergence.

- [ ] 3.1 Translate rate start, entitled stop/notice and partial reverse into
      explicit per-part commands with operation-derived stable keys. Require
      ActivatedDeliveryRef after verified site activation for start. Delivery
      authorization remains pure; implement the separate start_billing effect using
      the end service's sole stable operation key. End service journals key and
      activated evidence before I/O; delivery stores only its reference. Derive
      per-part keys from that intent, never a second keyed start. Missing,
      malformed or mismatched evidence refuses before effects. Verify lost response
      and identical retry against the in-process contract fake; changed-content
      key reuse is refused locally.
- [ ] 3.2 Expose verified per-part start/pendingStop/stop, funded-through, extension
      refs, releaseAt and event ordering to lifecycle read/watch. Verify exhaustion
      and maximum-term causes, missing pre-start funding as unknown, and refusal to
      use unverified/regressing snapshots through the foundation verifier.
- [ ] 3.3 Export immutable operation descriptors for caller write-before-call,
      then resolve unknown from authority events before another monetary delta.
      Implement D4's refusal classification, including transaction_stopped start
      failure, read-before-insufficient-funds reconciliation and matured shortfall.
- [ ] 3.4 Map settles_through to partialPeriod through the foundation codec:
      started_period/charged, last_boundary/returned, stop/prorated. Gate each
      value on vendored capability at publication and acceptance; interim spot
      uses charged for payer and payee. Qualify boundary/no-start/terms stops,
      superseded and equal-time requests from authority vectors; compute no
      local end-correction delta or clawback. Periods stay reserved until their
      end or part stop; afterStop payout is unchanged. Mediation requires no
      particular seller rule. Negotiation decides treatment; SCM seller presets
      offer last_boundary, and the terms-owned buyer policy refuses other payee
      or term-end treatments by default, with an explicit buyer override.
      Verify chosen-entry stop payloads follow payer/payee terms or the operator ruling.
- [ ] 3.5 Keep exceptional_end filing with the dispute adapter for seller
      non-delivery or unentitled past physical failure, without computing ruling
      amounts. A controlling lawful end before disclosure preserves attribution
      and does not self-file solely because delivery never became available. No automatic lawful
      notice reverse, target API or correction-obligation journal remains.
      Independent discounts and ruling effects are not end-pricing credits.

Validation: unit derivation/serialization cases, shared vector conformance and
library integration with in-process contract fakes for unknown retry, per-stopper
partialPeriod, winning-record attribution, independent discounts, partial reversal
before/after stop and held-money extensions. Lane HTTP doubles test deployed wiring,
not kit library behavior. Verify no mechanism import of kit/deal-servicing
or either domain with make check-architecture. Do not replicate the foundation's
cryptographic proof test matrix.

## 4. Seller notice command and operator first use

Files: kit/deal-lifecycle-contracts command/outcome models and route contracts,
kit/deal-lifecycle-client typed methods, the hosted adapter's notice admission;
domains/vms/storefront/src/market_storefront/cli.py and operator command group;
domains/bare_metal/storefront/src/arkhai_bare_metal_storefront/cli.py and
admin_cli.py; kit/deal-lifecycle-buyer and each domain's canonical buyer end verbs.
Reuse the foundation's command identity/recovery contract; do not add a
second preemption endpoint or a local payment-stop scheduler.

- [ ] 4.1 Admit notice against the accepted payee entitlement and adapter support,
      preserve its command operation identity, and immediately submit stop
      with explicit parts and optional at. Return the authority's effective time
      and pending/unknown/refused status. Verify current listing edits cannot
      grant or revoke the accepted permission.
- [ ] 4.2 Surface verified pendingStop in lifecycle read/list. Preserve an earlier
      buyer stop, immutable retry identity and the authority's notice minimum.
      On-demand refusal points to exceptional_end only for seller non-delivery,
      not an override payment stop or automatic filing after a lawful end.
- [ ] 4.3 Add the typed notice method and recommended deals preempt CLI verb to
      both domains, taking negotiation ID, operation key and optional --at.
      Delegate through lifecycle submit and its existing seller authentication.
      Output authority status/time, including unknown; do not report local
      command acceptance as an authoritative scheduled end.
- [ ] 4.4 Prepare committed first-use configuration/examples for both domains
      under the lane profile, with default setup price, paired on-demand/spot
      options, explicit authority entries, test mode and double selector. Document
      one runnable invocation per domain that lands on its preemption surface.
      Before convergence, use lane-only approval/command fixtures and assert
      delivery refuses without the rate hook; do not commit/deliver an unserviced
      live rate option. This fixture is the explicit lane-only door exception.
      Any interim spot fixture must explicitly configure its buyer to accept
      started_period on the payee entitlement and any charged term end. Include
      default-buyer refusal as a separate observation; returned-capable fixtures
      may use default buyers only once the matching contract is vendored.
- [ ] 4.5 Re-drive both domains' canonical rate buyer end: stop then hint, keep
      service during nonzero payer notice, and end through watch at effective
      stop. Keep explicit end-now-regardless and unreachable-authority
      end_delivery/buyer_end(at) paths distinct. Preserve signed evidence and
      report stop, delivery and case progress separately. Coordinate terms display.
- [ ] 4.6 Verify the foundation-owned VM admin route delegates notice for accepted
      payee entitlement and exceptional_end otherwise; request a foundation fix
      rather than implement a second entitlement switch here.

Validation: lifecycle client/contract unit suites; application-integration at each
storefront for seller authentication, accepted-option admission, refusal before
adapter effect and response-loss read; each domain's focused operator CLI suite.
Buyer-half and canonical buyer-CLI cases re-drive priced notice, explicit immediate
surrender, hint failure, payment-authority outage and both-authorities-down retry.
First use runs deals preempt against a double-backed approved spot fixture and
reads pending stop while asserting delivery is refused without the rate hook.
Before convergence lands, this proves command and authority record, not teardown.

## 5. Proposed declarations and identity re-anchoring

Files: kit/arkhai-payments/src/market_arkhai_payments/settlement_config.py and
adapter re-anchoring helper; kit/arkhai-payments/tests/test_settlement_config.py,
test_receipts.py as verifier consumers (not proof implementation);
lane profile configuration under e2e-tests/config. Foundation evidence stores and
convergence persist outputs through their existing ports.

- [ ] 5.1 Consume the terms-owned proposed-declaration validator at materialization,
      including its lane target and test-mode binding; do not duplicate it.
      Bind the lane-only proposed declaration's fixture payments identity to configured
      SERVICE_IDENTITY with livemode=false; refuse mismatch or production/live use.
      Keep published production enablement with activate-per-period-compute-servicing,
      gated only on deployment of the contract revision, never a horizon.
- [ ] 5.2 Add configured retiring identities with retirement dates alongside the
      current identity. Return a fresh current-key snapshot as re-anchoring
      evidence only after foundation verification of mandate, parties, mode and
      sequence; embedded old receipt is attested by that snapshot.
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
      Record the buyer acceptance-policy configuration for interim spot evidence;
      an opted-in buyer is not evidence of acceptance by default buyers.
- [ ] 6.3 Reference convergence's sole consolidated rate qualification matrix
      (its design's Scenarios and evidence); do not reproduce it here. Retain
      spot's prepared fixtures and typed entry points for its executor. Activation
      owns hosted qualification.
      Use wall-time lanes, short advertised windows and the tooling-owned typed
      due-work barriers/client; report per-authority progress, pending effects and
      blocked dependencies. No lane-wide clock advancement or fabricated completion;
      injected clocks are confined to isolated tooling state-machine tests.
      Activation must list producer snapshot, start and reversal vectors among
      blockers to published qualification; double traces do not satisfy them.
      Check that the matrix consumes maximum-term, on-demand refusal/self-filing
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
      change's design-promotion record. Archive writes delta-covered spec.md files
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
