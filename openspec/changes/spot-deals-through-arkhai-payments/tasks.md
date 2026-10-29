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
      setup_amount shape with that consumer.
- [ ] 1.3 Confirm add-arkhai-payments-lane-double supplies payment and mediation
      doubles, the revised per-part behavior, and deterministic clocks/outage controls.
      Freeze operation descriptors, target/delta inputs, rate observations and
      re-anchoring output for converge-ongoing-compute-leases to consume.
- [ ] 1.4 Obtain or explicitly gate on published signed snapshot/start/mixed-part
      vectors and partial-reversal-before/after-stop traces. Identify missing
      authority conformance evidence without replacing it with a double claim.

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
      reserve-ahead/exposure check. Keep approval_window distinct from adjudication.
      Verify malformed pairs, calendar periods, setup opt-out and insufficient lead.
- [ ] 2.2 Derive setup-once then rate deterministically through the accessor and
      codec. Include rate end, afterStop hold, maxHoldExtension and exact per-part
      authorities/notices. Keep start payee-only; omit payee stop on on-demand.
      Verify maximum term is absolute even after late start.
- [ ] 2.3 Extend the buyer's exact mandate check for mixed parts, ordering, price,
      asset, hold, cap and stop authorities. Verify explicit zero payer notice is
      not silently replaced by exposure or charged twice.
- [ ] 2.4 Supply default setup-bearing on-demand/spot presets with explicit setup
      pricing and seller opt-out. Bind setup and rate terms into option identity.
      Do not invent a setup amount or impose a bare-metal minimum-spend gate.
- [ ] 2.5 Wire the common builder into VM and bare-metal publication so the same
      pool can offer independently priced options. Preserve accepted option bytes
      across later publication changes and leave reserved/API-credit once options
      alone.
- [ ] 2.6 Add the materialization servicing-declaration gate: refuse undeclared
      rate servicing, including for accepted options after declaration withdrawal.
      The terms change retains publication/acceptance gate ownership.

Validation: unit targets test_mandates.py, test_buyer.py and
test_settlement_config.py; vector conformance for mixed and rate mandates;
application-integration targets under domains/vms/storefront/tests/integration
and domains/bare_metal/storefront/tests/integration for each publication adapter.
Run kit/arkhai-payments typecheck and the affected domain typing targets.
No running continuation is required for these option/approval seams.

## 3. Stateless rate adapter and correction mechanics

Files: kit/arkhai-payments/src/market_arkhai_payments/client.py, the foundation's
hosted adapter module, new operations.py and rate_math.py;
kit/arkhai-payments/tests/test_client.py, test_seller.py and
tests/integration/ for real journal consumers injected at the public adapter seam.
Journal persistence itself belongs to convergence.

- [ ] 3.1 Translate rate start, entitled stop/notice and partial reverse into
      explicit per-part commands with operation-derived stable keys. Require
      provisioned-delivery evidence for start. Verify lost response and identical
      retry against the HTTP double; changed-content key reuse is refused locally.
- [ ] 3.2 Expose verified per-part start/pendingStop/stop, funded-through, extension
      refs, releaseAt and event ordering to lifecycle read/watch. Verify exhaustion
      and maximum-term causes, missing pre-start funding as unknown, and refusal to
      use unverified/regressing snapshots through the foundation verifier.
- [ ] 3.3 Export immutable operation descriptors for caller write-before-call,
      then resolve unknown from authority events before another monetary delta.
      Implement D4's refusal classification, including transaction_stopped start
      failure, read-before-insufficient-funds reconciliation and matured shortfall.
- [ ] 3.4 Implement the pure half-open period helper and cumulative return target:
      buyer incomplete period retained, seller incomplete period returned, exact
      boundaries and no-start cases, reservation return distinguished from earned
      reversal, all actors' confirmed returns counted, no negative delta/clawback.
- [ ] 3.5 Expose lawful-preemption correction descriptors for post-stop voluntary
      reverse while held. Use the dispute adapter's exceptional_end intent for
      unentitled/past physical ends, without computing ruling amounts or inventing
      a post-release refund operation.

Validation: unit arithmetic/serialization cases in the kit, shared vector
conformance and library-integration through its HTTP boundary for unknown retry,
another actor's reversal, later target increase, partial reversal before/after
stop and held-money extensions. Verify no mechanism import of kit/deal-servicing
or either domain with make check-architecture. Do not replicate the foundation's
cryptographic proof test matrix.

## 4. Seller notice command and operator first use

Files: kit/deal-lifecycle-contracts command/outcome models and route contracts,
kit/deal-lifecycle-client typed methods, the hosted adapter's notice admission;
domains/vms/storefront/src/market_storefront/cli.py and operator command group;
domains/bare_metal/storefront/src/arkhai_bare_metal_storefront/cli.py and
admin_cli.py. Reuse the foundation seller-half submit/journal seam; do not add a
second preemption endpoint or a local payment-stop scheduler.

- [ ] 4.1 Admit notice against the accepted payee entitlement and adapter support,
      journal its operation/correction obligation, and immediately submit stop
      with explicit parts and optional at. Return the authority's effective time
      and pending/unknown/refused status. Verify current listing edits cannot
      grant or revoke the accepted permission.
- [ ] 4.2 Surface verified pendingStop in lifecycle read/list. Preserve an earlier
      buyer stop, immutable retry identity and the authority's notice minimum.
      On-demand refusal points to exceptional_end, not an override payment stop.
- [ ] 4.3 Add the typed notice method and recommended deals preempt CLI verb to
      both domains, taking negotiation ID, operation key and optional --at.
      Delegate through lifecycle submit and its existing seller authentication.
      Output authority status/time, including unknown; do not report local
      command acceptance as an authoritative scheduled end.
- [ ] 4.4 Prepare committed first-use configuration/examples for both domains
      under the lane profile, with default setup price, paired on-demand/spot
      options, explicit authority entries, test mode and double selector. Document
      one runnable invocation per domain that lands on its preemption surface.

Validation: lifecycle client/contract unit suites; application-integration at each
storefront for seller authentication, accepted-option admission, refusal before
adapter effect and response-loss read; each domain's focused operator CLI suite.
First use runs deals preempt against a double-backed accepted spot deal and reads
the pending stop. Before convergence lands, this proves the command and authority
record only, not domain teardown.

## 5. Proposed declarations and identity re-anchoring

Files: kit/arkhai-payments/src/market_arkhai_payments/settlement_config.py and
adapter re-anchoring helper; kit/arkhai-payments/tests/test_settlement_config.py,
test_receipts.py as verifier consumers (not proof implementation);
lane profile configuration under e2e-tests/config. Foundation evidence stores and
convergence persist outputs through their existing ports.

- [ ] 5.1 Bind proposed servicing to the explicit lane profile's double target and
      test mode. Refuse external endpoint substitution and livemode evidence.
      Keep published production enablement with activate-per-period-compute-servicing,
      gated only on deployment of the contract revision, never a horizon.
- [ ] 5.2 Add configured retiring identities with retirement dates alongside the
      current identity. Return a fresh current-key snapshot as re-anchoring
      evidence only after foundation verification of mandate, parties, mode and
      sequence; embedded old receipt is attested by that snapshot.
- [ ] 5.3 Integrate durable anchor replacement via the evidence-store port while
      keeping original bytes; expose dependent/unanchored deals for convergence's
      status. Refuse stale-anchor rollback and mode-change re-anchoring. Document
      retirement only after dependent deals re-anchor or drain.

Validation: configuration unit cases for invalid proposed composition and mode;
kit integration with the double rotating identities across an existing deal.
Use the foundation's verified-snapshot fixtures. Consumer persistence/restart
evidence waits for convergence; do not claim it from a stateless adapter test.

## 6. Qualification scenarios and pre-closeout review

Files: kit/arkhai-payments/test-vectors and vector runner, README.md,
examples/local_e2e.py; e2e-tests/tests/e2e/roles/helpers/payments.py and
compute_deal_stages.py; scenarios under each compute lane; e2e-tests/README.md.

- [ ] 6.1 Update examples/fixtures to USD/6 without hardcoding a production asset.
      Keep published vectors content-identified and separate from proposed
      qualification traces. Run make -C kit/arkhai-payments check-vectors,
      check-generated, test-unit and typecheck as appropriate to changed seams.
- [ ] 6.2 Add readiness-gated entry points and evidence metadata for both compute
      lanes. Record contract revision, target class/mode, hashes and control trace;
      missing deployment, credentials or hardware is an explicit prerequisite.
      Stop before browser/scenario execution on an unready deployment.
- [ ] 6.3 Deliver shared scenario entry points for buyer stop including priced
      notice; seller notice with storefront down past due time; earlier buyer stop
      during notice; exhaustion; maximum term; on-demand payee refusal then
      mechanical exceptional end; stop/start race; rotation overlap. Hand their
      execution to converge-ongoing-compute-leases when it composes the consumer:
      that change must observe authority records and actual capacity/access end
      in both domains. Record consumer-dependent execution as unrun here rather
      than create a reverse archival dependency.
- [ ] 6.4 Check the changed imports, comments and public artifacts before code
      review. Move touched local imports to module level where safe, retaining
      only verified circularity or deliberate lazy-load reasons. Run focused
      domain integration and typing, then make check-packaging; fix failures
      before committing implementation.
- [ ] 6.5 Obtain pre-closeout code review. Confirm adapter/servicing ownership and
      that cooperative reversal never replaces the buyer's authority/dispute
      guarantee. Verify the command/publication seams here; consumer-enabled
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
      (rate operations, arithmetic and rotation), storefront-publication/
      architecture.md (presets and independent pricing), deal-lifecycle/
      architecture.md (notice and External authorities), test-compatibility/
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
