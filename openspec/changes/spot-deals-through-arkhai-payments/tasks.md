# Tasks — the full hosted rate product on the MVP's mechanics

This is a design-stage plan; no implementation tasks are complete. Goal 8's MVP
changes land first and took reduced forms of several tasks below, each marked as
moved with what its owner took; a task kept with a checkbox holds only the work
that remains after them. The archived foundation's gates are met. No section
implements another verifier, continuation daemon or site renewal policy.

Verification levels follow docs/development/TESTING.md. The targets below extend
the existing owning suites; select their focused cases during implementation.
Full pipeline evidence is required at closeout, not as a substitute for focused
tests.

## 1. Confirm dependency surfaces and freeze the consumer interface

Files: kit/arkhai-payments/schema/SOURCE.md, schema/payments.schema.json,
test-vectors/payments.json; the rate adapter and observations
derive-rate-parts-in-the-payments-kit lands; this design's D1–D8.

- [ ] 1.1 Confirm the archived foundation and the landed
      derive-rate-parts-in-the-payments-kit and serve-running-rate-deals-on-vm
      supply what this change extends: the codec, rate derivation and buyer check,
      the rate adapter with its descriptors and refusal classification, verified
      observations, `authorize`, the materialization gate, the seller notice, the
      buyer rate end and the identity-history verifier. Record the schema and
      vector hashes from SOURCE.md. Do not edit generated models.
- [ ] 1.2 Confirm negotiate-open-ended-compute-terms supplies the servicing
      declaration's list of qualified treatments, the buyer acceptance policy,
      the premature-stop penalty's resolution, the payout-hold term, the injected
      preset-helper interface, and bare metal's publication, horizon and
      whole-second starts. Freeze the setup_amount shape with it. The price
      accessor owns its readings and their inputs; this change adds no
      rate-structure carrier gate.
- [ ] 1.3 Freeze, for convergence, the rate re-anchoring output and the rate-part
      extension and releaseAt observations this change adds. Operation
      descriptors and activation-envelope consumption are
      derive-rate-parts-in-the-payments-kit's.
- [ ] 1.4 Qualify through the kit's vector runner the treatments the MVP does not
      use: returned and prorated stop entries and term ends, a late-start returned
      end at the unchanged absolute end, and `chosen` dispute stops carrying their
      treatment. Confirm delivery_end remains a dispute intent and mediation's
      self-penalty uses its own chosen entry with returned. Record the producer
      gaps — no independent HTTP qualification of chosen, end or reverse, and no
      real lost HTTP response — without replacing them with a double claim.
      Charged-treatment vector conformance is derive-rate-parts-in-the-payments-kit's.

Validation: kit/arkhai-payments check-vectors and check-generated targets.

## 2. Treatments, setup, the payout hold and both-domain presets

Files: kit/arkhai-payments/src/market_arkhai_payments/mandates.py, buyer.py,
settlement_config.py and the preset helper beside mandates.py;
kit/arkhai-payments/tests/test_mandates.py, test_buyer.py,
test_settlement_config.py; both domains' storefront settlement_composition.py,
publication configuration and their focused publication suites.

- [ ] 2.1 Add optional setup_amount (a positive canonical minor-unit string;
      omission means no setup part) and carry premature_stop_penalty through the
      injected preset helper, encoding only the value the terms change supplies.
      Lift derive-rate-parts-in-the-payments-kit's charged-only refusal per
      treatment the composition's servicing declaration lists, never globally.
      Keep setup-bearing presets disabled until a hosted dispute authority is
      qualified on the vendored delivery_end revision. Verify setup opt-out,
      penalty encoding, an undeclared treatment's refusal and a declared one's
      admission. Rate parameters, the period projection, the finite term and
      whole-second starts are the MVP's.
- [ ] 2.2 Derive setup once then rate deterministically; encode setup's end at
      Agreement start with its schema-required partialPeriod; map last_boundary
      and stop through the codec to returned and prorated on stop entries and the
      rate end; verify a late start never extends the absolute bound. Derive the
      dispute stop entry as `chosen`; where the charged fallback is bound in the
      option's settlement parameters, derive that bound treatment, so restoring
      chosen is a new option.
- [ ] 2.2a Derive the rate part's hold from the accepted payout-hold term: the
      default `{afterStop: dispute_window}`, or `{for: <hold>}` where the option
      states a shorter hold. Verify both, and that the hold is bound into the
      option ID.
- [ ] 2.3 Extend the buyer's exact check to mixed parts, their order, the setup
      amount, the penalty, the payout hold and non-charged treatments. Consume the
      terms-owned acceptance policy; an exact mandate match is not policy
      acceptance. Do not claim on-demand prevents physical preemption.
- [ ] 2.4 Supply setup-bearing on-demand and spot presets: VM carries no setup part
      by default and adds one only with a configured price; bare metal requires a
      seller-priced setup part and refuses an incomplete configuration. Verify a
      buyer's stop before activation keeps setup with the seller and the
      self-penalty for non-delivery returns it. Bind all terms into option
      identity; invent no amount or minimum-spend gate.
- [ ] 2.5 Supply the preset helper to bare metal's terms-owned publication adapter,
      and setup, penalty and last_boundary variants to VM's. Once a composition
      declares returned, its shipped presets carry last_boundary on the payee
      entitlement and at the term end under new option IDs. Preserve
      reserved/API-credit once behaviour.
- 2.6 — moved to `derive-rate-parts-in-the-payments-kit`: the materialization
  servicing-declaration gate.

Validation: unit targets test_mandates.py, test_buyer.py and
test_settlement_config.py; vector conformance for mixed and treatment mandates;
application integration under domains/vms/storefront/tests/integration and
domains/bare_metal/storefront/tests/integration for each publication adapter;
kit/arkhai-payments typecheck and the affected domain typing targets.

## 3. Adapter additions and authority-enforced period treatment

Files: kit/arkhai-payments/src/market_arkhai_payments/ rate adapter and
operations modules; kit/arkhai-payments/tests/test_client.py, test_seller.py and
tests/integration/. Journal persistence belongs to convergence.

- 3.1 — moved to `derive-rate-parts-in-the-payments-kit`: rate start, entitled
  stop with notice and partial reverse as per-part commands with stable keys, the
  activation envelope and the start_billing key.
- [ ] 3.2 Expose verified rate-part extension refs, releaseAt and money held under
      open extensions to lifecycle read and watch. Started, pending stop, stop,
      funded-through and their causes are the MVP's.
- [ ] 3.3 Resolve a matured hold: on hold_matured surface the shortfall and the case
      path, never a retried refund or post-release refund journal. Descriptors and
      the rest of refusal classification are the MVP's.
- [ ] 3.4 Observe returned, prorated and chosen treatment from verified stop
      records; qualify boundary, no-start, superseded and equal-time requests and
      winning-record attribution against the in-process engine; compute no local
      end correction or clawback. Verify a chosen ruling's stop reports the
      treatment its event carries.
- [ ] 3.5 Verify the adapter against the foundation's journaled delivery_end filing
      path and mediation mapping: filing response-loss read and retry, spot
      emergency filing, on-demand returned treatment and the capped penalty after
      refunds, on deals whose dispute entry is chosen. Verify no seller payment
      calls, exceptional-end payment operation, direct-payment fallback or second
      correction journal.
- 3.6 — moved to `derive-rate-parts-in-the-payments-kit`: the pure rate authorize
  hook.

Validation: unit and vector cases; library integration with the in-process engine
for per-stopper partialPeriod, chosen rulings, independent discounts, partial
reversal before and after a stop, held-money extensions and matured shortfalls;
make check-architecture for no mechanism import of kit/deal-servicing or a domain.

## 4. Seller notice, buyer end and operator first use beyond the MVP

Files: domains/bare_metal/storefront/src/arkhai_bare_metal_storefront/cli.py and
admin_cli.py; domains/vms/storefront operator command group;
kit/deal-lifecycle-buyer and the bare-metal buyer's canonical end verb.

- 4.1 — moved to `serve-running-rate-deals-on-vm`: notice admission against the
  accepted payee entitlement and immediate submission of the stop.
- [ ] 4.2 After 3.5, change the on-demand refusal of notice to name delivery_end
      as the path for actual seller non-delivery, in place of the operator
      procedure; never a self-interested override or an automatic filing.
      Pending stop in read and list is the MVP's.
- [ ] 4.3 Add bare metal's deals preempt, taking negotiation ID, operation key and
      optional --at, through the typed lifecycle client. VM's is the MVP's.
- [ ] 4.4 Prepare bare-metal first-use configuration and examples, priced setup
      fixtures, and returned-treatment fixtures taken by default buyers under a
      declaration that lists returned. VM's charged fixtures are the MVP's.
- [ ] 4.5 Re-drive bare metal's canonical rate buyer end onto the buyer half's
      stop-then-hint flow. VM's is the MVP's.
- [ ] 4.5a Add the buyer's watchdog per D6a: the probe loop in `kit/deal-lifecycle-buyer`
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
      stop landing with the storefront absent.
- [ ] 4.6 After 3.5, have the VM admin route file delivery_end through the dispute
      adapter for a seller-caused emergency failure, spot hardware failure
      included. Its notice delegation is the MVP's.

Validation: lifecycle client and contract unit suites; application integration at
each storefront for seller authentication and refusal before adapter effect; each
domain's operator CLI suite; bare-metal buyer-CLI cases for priced notice,
immediate surrender, hint failure and payment-authority outage.

## 5. Identity re-anchoring

Files: kit/arkhai-payments/src/market_arkhai_payments/settlement_config.py and an
adapter re-anchoring helper; kit/arkhai-payments/tests/test_settlement_config.py,
test_receipts.py as verifier consumers.

- 5.1 — moved to `serve-running-rate-deals-on-vm`: the lane's test-mode servicing
  declaration.
- [ ] 5.2 Add configured retiring identities with retirement dates alongside the
      current identity, with windows following the payments service's
      key-retention commitment. Return a fresh current-key snapshot as
      re-anchoring evidence only after the foundation verifier checks mandate,
      parties, mode, sequence and the embedded old receipt's attestation.
- [ ] 5.3 Integrate durable anchor replacement via the evidence-store port while
      keeping original bytes; expose dependent and unanchored deals for
      convergence's status. Refuse stale-anchor rollback and mode-change
      re-anchoring. Retire a key only after rate deals re-anchor or drain and
      once-only deals drain; inventory every dependent hosted deal.

Validation: configuration unit cases; kit integration with the in-process engine
rotating identities across a rate deal. Consumer persistence and restart evidence
waits for convergence.

## 6. Qualification evidence and pre-closeout review

Files: kit/arkhai-payments/test-vectors and vector runner, README.md,
examples/local_e2e.py; focused lifecycle and CLI integration suites.

- [ ] 6.1 Update examples and fixtures to USD/6 without hardcoding a production
      asset. Label evidence as the archived lane double defines it: lane-double
      evidence or live evidence. Run make -C kit/arkhai-payments check-vectors,
      check-generated, test-unit and typecheck as appropriate.
- [ ] 6.2 Supply evidence metadata at the adapter and command first-use boundary:
      installed contract hashes, the declaration's treatment list, the evidence
      label and the control trace.
- [ ] 6.3 Reference convergence's consolidated rate matrix without reproducing it;
      the MVP's four VM rows are serve-running-rate-deals-on-vm's. Check that the
      matrix consumes returned maximum-term, on-demand self-penalty filing,
      chosen ruling, rotation-overlap and bare-metal preparation, and report
      missing coverage to convergence.
- [ ] 6.4 Check the changed imports, comments and public artifacts before code
      review. Move touched local imports to module level where safe, retaining
      only verified circularity or deliberate lazy-load reasons. Run focused
      domain integration and typing, then make check-packaging; fix failures
      before committing implementation.
- [ ] 6.5 Obtain pre-closeout code review. Confirm adapter and servicing ownership
      and that every treatment is enforced at the payment authority, with no local
      correction substituted for the buyer's authority and dispute guarantee.

## 7. Closeout

Documentation only, after code review, in the order required by
openspec/README.md#plan-closeout-requirements. Any required code fix returns this
change to implementation and review.

- [ ] 7.1 **Comment hygiene.** Run make check-comment-hygiene and inspect touched
      comments and docstrings for stale provenance. Do not edit code during closeout.
- [ ] 7.2 **Import placement.** Confirm touched imports are at module level unless
      a verified circularity or deliberate lazy-load reason was retained and
      reviewed; a necessary move returns to implementation.
- [ ] 7.3 **Documentation compliance.** Classify every accepted decision in D1–D8;
      keep external authority behaviour as architecture context, not SCM normative
      promises. Confirm adapter versus continuation ownership.
- [ ] 7.4 **Narrative compression.** Compress completed tasks to final behaviour,
      material evidence, residuals and permanent destinations, preserving material
      rationale in design.md.
- [ ] 7.5 **Roadmap currency.** Update Goal 8 in docs/development/ROADMAP.md with
      the treatments, setup, payout hold, self-penalty observation, watchdog,
      rotation and bare-metal surfaces this change adds, and the remaining
      continuation and hosted gaps; record promotion.
- [ ] 7.6 **Campaign index currency.** Update openspec/changes/README.md status,
      dependencies and campaign graph. Run make check-change-index and record
      disposition.
- [ ] 7.7 **Packaging.** Run make check-packaging and
      make check-architecture-change CHANGE=spot-deals-through-arkhai-payments,
      resolving every failure and owned exception. Run make check-agent-skills if
      implementation touched agent instruction directories.
- [ ] 7.8 **End-to-end pipeline.** Record the complete pipeline run and result and
      the applicable scenarios. Name exact prerequisites and owning changes for
      unrun consumer or hosted validation; do not mark them passed or substitute
      unit evidence.
- [ ] 7.9 **Promotion.** Write openspec/specs/settlement-servicing/architecture.md
      (treatments, setup, payout hold, extensions and rotation),
      storefront-publication/architecture.md (presets by declared treatment and
      setup), deal-lifecycle/architecture.md (bare metal's notice and buyer end,
      the watchdog, External authorities), docs/development/ARCHITECTURE.md (Kit
      areas and Settlement servicing), docs/development/DEPLOYMENT_AND_CONFIG.md
      (identity overlap), and the openspec/specs/README.md capability index as
      needed. Complete this change's design-promotion record. Archive writes the
      delta-covered spec.md files for settlement-servicing,
      settlement-configuration, storefront-publication, deal-lifecycle and
      test-compatibility.
- [ ] 7.10 **Documentation citations.** Run
      make check-doc-citations CHANGE=spot-deals-through-arkhai-payments after
      promotion and resolve every match; run
      openspec validate spot-deals-through-arkhai-payments --strict with the
      repository-pinned validator.
- [ ] 7.11 **Archival.** Run openspec archive spot-deals-through-arkhai-payments -y
      last, merging deltas; update the campaign row to the archive. Closeout
      review and triage read the archived change and promoted permanent documents.

## Design promotion record

Planned destinations are recorded in design.md. Fill actual headings and evidence
at implementation closeout; do not promote unimplemented behaviour during design.
