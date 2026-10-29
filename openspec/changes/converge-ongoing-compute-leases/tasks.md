# Tasks — rate-part servicing inside end service

This is an implementation plan, not completed runtime work. All tasks are pending.
Review the foundation/spot/unified-delivery contracts at their landing revisions
before code starts; no superseded Goal 8 change is an implementation gate.

## 1. Dependency and composition gate

- [ ] 1.1 Confirm `agreed-evidence-and-early-termination` supplies lifecycle commands,
      read/list/watch, per-record cursors, evidence stores, end-service admission,
      buyer stop/end_delivery/buyer_end and dispute adapter exceptional_end intents,
      mediation request vocabulary and published mapping. Verify only qualifying
      payee self-penalty is mechanical; buyer_end is human triage. Consume the atomic
      end/filing journal with none/intent/pending-classification and later filing
      resolution, never-future timing and pre-start filing at Agreement start.
      Buyer half journals/retries its payment stop under the same key; storefront
      signs receipt evidence only and has no authority to stop billing for the buyer.
      Foundation owns these neutral interfaces and start journal before unify.
      Record exact bindings; stop on a missing interface rather than duplicating it.
- [ ] 1.2 Confirm spot supplies verified rate authorize/start_billing adapter operations,
      per-stopper and term-end partialPeriod mapping without term rounding, afterStop holds
      and rotation re-anchoring. Foundation supplies the neutral adapter protocol
      and source-classified self-penalty filing. Confirm seller stop entries exist
      only for entitlements such as spot notice; emergencies file exceptional_end.
      Verify mediation's PT0S/chosen stop entry, standard returned rate stops, rate
      reversals since at, once unserved shares and full bond award once supported.
      Seller sends no stop/reverse for self-penalty. No seller restitution entry,
      implicit favourable permission, notice waiver, payer early release or
      multi-stop-entry payments dependency remains. Verify shared original filing
      identities and qualified dispute-adapter revised-request/prior-ruling mapping.
      Unify tasks 1–3 supply path/protocol consumption, activation/undelivered ports
      and start-journal reference. This is a section handoff, not an archive gate; converge tasks 1–3 then feed
      unify 4.4/converge 4 qualification. Gate scenarios on runnable double sections.
- [ ] 1.3 Name the composition edits in both storefronts' settlement_composition.py
      and runtime registration: extend the existing lifecycle/end-service wiring,
      inject domain ports and adapters, register the loop on kit/storefront's loop
      controller. Add only required declarations to affected pyproject.toml files;
      refresh locks through existing tooling. Validate direction with
      `make check-architecture` and the affected package typing checks.

## 2. Durable state, queues and recovery

- [ ] 2.1 Extend `kit/deal-servicing` and its persistence ports/migrations with the
      commitment-bound state, funding timer, earliest final request, immutable
      effect identities and physical/financial completion history (D2). Keep exact
      bytes in the evidence store. Financial completion is end-revision-scoped;
      watching/retention continues after both facts, reopening on earlier evidence.
      Physical completion requires proven capacity release/no dispatch/manual audit,
      not lease_ended intent; apply both facts to once-only deals too. Persist spot-produced re-anchoring
      evidence and retiring-key dependency status for rate and once-only deals.
- [ ] 2.2 Implement one registered loop step with physical, bounded authority and
      second physical passes (D3), independent errors, and foundation cursor/journal
      reuse so a newly due end runs without another polling interval. Outages skip
      unverified facts, never pending physical work. Reuse foundation watch and journal mechanisms.
- [ ] 2.3 Implement replaceable funding timers without speculative lease truncation;
      read payments before ending at expiry. Verified renewal replaces the timer;
      verified exhaustion supplies an authority end without classification. Only an
      unreachable/unverifiable read journals a bare-timer end with pending
      classification through foundation record_end. Later atomic filing resolution
      discharges exhaustion at/before T or journals exceptional_end(T) if billing
      continued. No synthetic final request or second journal.
      Unverifiable classification stays pending. Preserve future effective notice times
      from authority records and compose earliest-final-request semantics.
- [ ] 2.4 Expose both completion facts, gap ages, pending operations/cases and manual
      recovery provenance on lifecycle read/list. Implement D2's recommended warning
      policy using deployment retry/watchdog budgets; leave loops running on warning.
      Bind diagnostics/state mapping to the deal-lifecycle read/list contract, with
      manual principal/reason and revision identity. Terminal parts mean verified
      stop/end, not payout. Surface pending self-penalty cases and billing after delivery end,
      unanchored rate deals and once-only must-drain retirement dependencies. Measure cadence/teardown budgets
      as seller risk recommendations, never another notice or codec/config gate.
- [ ] 2.5 Validate at the lowest meaningful level: pure timer/fact/revision selection
      in unit coverage; database journal/cursor/restart and queue independence in
      `kit/deal-servicing/tests` library-integration coverage. Exercise no dispatch,
      unknown dispatch adoption, physical failure, authority outage and late evidence
      after completion, intent/release_failed without release proof, partial-ruling
      earlier evidence, append/close race, reachable last-poll top-up (no end) and outage-hidden top-up
      after bare-timer expiry. Include runner/online case adoption and
      interruption before result export without reconstructing command bytes.
      Prove restart by rebuilding each production application over the same database;
      kits use the kit-owned clock-injected payments authority engine directly,
      not runnable tooling dependencies; HTTP doubles wrap that same engine.
      Use injected deterministic clocks/ports, not sleeps.

## 3. Delivery and authority work

- [ ] 3.1 Compose and verify foundation's phase/decision protocol and spot's hosted
      authorize/start_billing implementation through provisioning/compute/delivery;
      do not define the protocol or interpret hosted part fields here. Bind both
      storefront composition roots and drive the shared start journal from the loop.
      Accept activation to the Agreement end or verified earlier end, including
      truncation before activation and between lost acknowledgement and retry.
      Consume foundation's sole intent and unify's reference/undelivered handoff;
      verify both storefront integration suites. Spot's adapter plus this composition
      gate unify 4.4; foundation's protocol precedes unify 1–3.
- [ ] 3.2 Consume foundation's classified end/self-penalty filing journal for
      unentitled site/operator/failed delivery, never future-dated; pre-start failure
      journals immediately and files at Agreement start. Route exceptional_end only
      through the dispute adapter to the Agreement authority; seller sends no stop
      or reverse. Qualify mediation's sole mechanical ruling for a payee request at
      least as strong as standard, using its own PT0S/chosen entry for returned rate
      stops, rate reversals since at, time-based once refunds and full bond once
      supported. Add timer classification via foundation's atomic filing resolution.
      Resolve unknown original filings before revised requests; consume the dispute
      adapter's qualified revision mapping and prior-ruling netting, not local
      monetary deltas or append-as-amendment. Adopt equivalent runner cases under
      shared original identities without duplicate filings. Missing safe coverage
      is repair required. Buyer_end stays human triage, carries exact Agreement
      verified against mandate deal hash and uses payer notice/partialPeriod.
      end_delivery signs receipt evidence only; buyer half stops first or journals
      and retries the same payment stop key during outage, with billing until landing.
      End service has no authority to stop billing for the buyer.
- [ ] 3.3 Consume foundation site-report ingestion as a final-request source and
      attribution evidence, not completion proof; use capacity-release proof for that.
      Exercise, do not reimplement, its buyer evidence projection, stop-plus-hint for
      nonzero notice, explicit end-now and buyer_end fallback. Verify outage and
      late-evidence paths with injected payment and mediation adapters in library/service integration coverage.
- [ ] 3.4 Add stateless recovery runner in kit/deal-servicing and domain CLI adapter
      composition. Add seller-authenticated read-only evidence export through
      kit/deal-lifecycle-contracts, kit/deal-lifecycle-client and both storefronts;
      retain exact Agreement/mandate/commitment and evidence, never credentials.
      Persist D6's immutable command envelope/descriptors before I/O and replay from
      it after interruption before result export. Export original filing identities;
      read/adopt equivalent existing seller cases and enforce same-intent resolution
      plus qualified dispute revision mapping; self-penalty has no direct seller
      payment effects. Never open
      storefront persistence offline. Export exact results and verify watch adoption
      after restart. Extend contracts/client with local administrator submit kind
      acknowledge_physical_recovery, observed non-future at, local audit acceptance,
      principal/reason/resource/revision binding and same-key result recovery; it
      cannot certify money.
- [ ] 3.5 Implement startup coherence and declaration withdrawal behavior in both
      compositions. During overlap request spot's rate re-anchoring evidence, persist it before
      retirement and expose unanchored rate / once-only must-drain dependencies.
      This change solely owns startup/continued-servicing qualification; terms
      supplies declarations and activation consumes this behavior. Run relevant existing
      tests in `kit/arkhai-payments/tests`, `kit/deal-servicing/tests`,
      `domains/vms/storefront/tests/integration` and
      `domains/bare_metal/storefront/tests/integration`, plus affected package typing.
      During implementation fix changed comments/import placement before review.

## 4. Lane qualification and pre-closeout review

- [ ] 4.1 Extend e2e-tests/tests/e2e/roles/scenarios and shared stages with D's full
      rate matrix (0–11), executing spot's prepared entry points and recording maximum
      term plus on-demand/spot emergency exceptional_end filings, sole mechanical
      payee self-penalty and on-demand returned treatment. Record buyer case/held
      money/bond remedy, not mandate-enforced non-preemption. Exercise buyer-half
      same-key payment-stop retry with billing until landing; end_delivery receipt
      grants no storefront payment authority. Rows 7/9 record interim non-default
      buyer acceptance, separate default-policy refusal and returned-capable acceptance once vendored. Drop once-only
      activation duplication (unify owns it). Gate on readiness and coherent UTC/skew
      checks; consume typed due-work barriers with per-authority watermarks, pending
      effects and blocked dependencies (never completed while blocked). Doubles use
      wall-clock mode, short fixture deadlines and event-bounded
      waits, never isolated clock jumps. Pause/step the one three-pass loop; assert
      authority effects, evidence and both facts. Lane pause is not restart proof.
- [ ] 4.2 Exercise additional remote-stop windows, both-authority outage replay,
      lost acknowledgement plus earlier evidence, stale/invalid/regressed snapshots,
      buyer ends before/during/after provisioning, late evidence after completion
      with a revision correction during partial effects or append/close races, manual
      recovery, declaration checks, setup once churn pricing and rotation across a running deal. Reuse lowest-level
      adapter coverage for arithmetic rather than cloning it in e2e.
- [ ] 4.3 Record each run as proposed- or published-contract qualification; no double
      run is live evidence. Commit reproducible setup/evidence indexes with public
      fixture aliases and no secrets/private logs. Ensure both domain complete-deal
      pipelines pass. No production declaration is enabled by this change.
- [ ] 4.4 Run affected suites/typing, `make check-packaging` and pre-closeout code
      review. Repair comments/imports and all findings in implementation, then
      re-drive changed scenarios. Closeout below changes documentation only.

## 5. Closeout

Perform in order; a required code repair returns to implementation and review.

- [ ] 5.1 Comment hygiene: confirm changed code describes current invariants; run
      `make check-comment-hygiene`. Stop closeout on failure; do not edit code here.
- [ ] 5.2 Import placement: confirm every touched local import has a verified cycle
      or deliberate lazy-load reason, or was moved/tested before pre-closeout review.
      A needed move returns to implementation.
- [ ] 5.3 Documentation compliance: classify every D1–D7 decision as permanent,
      temporary, rejected or superseded and check OpenSpec placement rules directly.
- [ ] 5.4 Narrative compression: retain final behavior, material validation, remaining
      work and destinations in completed notes; move unique rationale to design.
- [ ] 5.5 Roadmap currency: update `docs/development/ROADMAP.md` Goal 8's storefront
      servicing gap, held-money/buyer-stop safety and seller-liveness limitation;
      retain hosted activation as a gap. Record the update in the promotion record.
- [ ] 5.6 Campaign index currency: update this row/status and dependency graph in
      `openspec/changes/README.md`; preserve dependents until archive cleanup. Record
      the update and run `make check-change-index`.
- [ ] 5.7 Packaging: run `make check-packaging` and
      `make check-architecture-change CHANGE=converge-ongoing-compute-leases`;
      own no expired exception. Run `make check-agent-skills` if agent instructions
      changed. Any failure needing code returns to implementation.
- [ ] 5.8 End-to-end pipeline: record passing VM/bare-metal complete-deal runs and
      full rate-matrix qualification including spot entry points, and both-domain
      production-application rebuild evidence, with exact provenance. Missing
      prerequisite or pipeline failure is an explicit blocker, not passing evidence.
- [ ] 5.9 Promotion: after code review, write current-state rationale in
      `openspec/specs/deal-lifecycle/architecture.md` for end service/guarantee limits,
      `openspec/specs/settlement-servicing/architecture.md` for the journal exception
      and adapter-mediated mechanism-owned continuation, composition ownership
      in `openspec/specs/market-composition/architecture.md`, evidence rationale in
      `openspec/specs/test-compatibility/architecture.md`, and repository-wide
      servicing/authority boundaries in `docs/development/ARCHITECTURE.md`.
      Promote the nine reconciled drawio/SVG pairs to `docs/development/diagrams/`
      and update their citations. Update `openspec/specs/README.md` if needed;
      complete the promotion record. Spec deltas merge at archival, not by hand.
- [ ] 5.10 Documentation citations: run
      `make check-doc-citations CHANGE=converge-ongoing-compute-leases`, resolve all
      citations, then pinned `openspec validate converge-ongoing-compute-leases --strict`
      (repository invocation: `bunx @fission-ai/openspec@1.14.0 validate converge-ongoing-compute-leases --strict`).
      Run `make check-change CHANGE=converge-ongoing-compute-leases` before archival.
- [ ] 5.11 Archival: only after every preceding task passes, run
      `openspec archive converge-ongoing-compute-leases -y` using the repository pin,
      merging deltas and linking the archived directory from the index. Closeout
      review/triage reads archived documents; archive cleanup rechecks dependents.

## Design promotion record

All destinations below are planned, not yet promoted.

| Accepted decision | Permanent location |
|---|---|
| D1/D7 neutral storefront ownership, loop and startup | market-composition spec/architecture; ARCHITECTURE kit areas and settlement servicing |
| D2 two facts, revision-scoped finance, diagnostics/manual command | deal-lifecycle spec/architecture |
| D3 three-pass loop, timers and classification | deal-lifecycle spec/architecture |
| D4 neutral adapter hook and activation-following start | deal-lifecycle spec/architecture; ARCHITECTURE authority boundaries |
| D5 timer classification, self-penalty filings/revised rulings, honest residual | deal-lifecycle spec/architecture; ARCHITECTURE settlement servicing |
| D6 stateless recovery/export/envelope, foundation buyer/evidence consumption | deal-lifecycle spec/architecture |
| Adapter-journal exception and stage-owned continuation | settlement-servicing spec/architecture; market-composition architecture |
| D7 activation/declaration boundary | market-composition spec/architecture; activation-owned configuration docs cross-reference |
| Full rate matrix, integration restart boundary and coherent lane time | test-compatibility spec/architecture; docs/development/diagrams/ |
| Goal 8 servicing and residual gaps | docs/development/ROADMAP.md, at closeout |
| Row/status/dependency graph | openspec/changes/README.md, at closeout |
