# Tasks — rate-part servicing inside end service

This is an implementation plan, not completed runtime work. All tasks are pending.
Goal 8's MVP set lands first; tasks it took are marked as moved, and partly taken
tasks keep only the residual work, built on what `serve-running-rate-deals-on-vm`
leaves. Review the landed `deal-lifecycle`, `compute-delivery` and lane-double
requirements and the MVP changes at their landed revisions before code starts.

## 1. Dependency and composition gate

- [ ] 1.1 Bind the landed `deal-lifecycle` contracts and record the exact bindings:
      lifecycle commands, read/list/watch, per-record cursors, evidence stores,
      end-service admission, buyer stop/end_delivery/delivery_end, dispute adapter
      delivery_end intents and mediation's request vocabulary and published mapping.
      Verify one payee-agreed delivery_end rule under mapping/time/replay guards;
      other claims stay triaged without silence defaults. Consume the atomic
      end/filing journal with none/intent/pending-classification and later filing
      resolution, never-future timing and pre-start filing at Agreement start.
      Buyer half journals/retries its payment stop under the same key; storefront
      signs receipt evidence only and has no authority to stop billing for the buyer.
      Confirm the MVP's VM composition, physical fact, meaning of *ended*, per-deal
      step-order helper and stop-cause classifier as landed. Stop on a missing
      interface rather than duplicating it.
- [ ] 1.2 Confirm spot supplies what the MVP leaves out: setup parts, `returned` and
      `prorated` treatment with per-stopper and term-end partialPeriod mapping, the
      premature-stop penalty, afterStop holds and rotation re-anchoring. Confirm
      seller stop entries exist only for entitlements such as spot notice;
      emergencies file delivery_end. Verify mediation's PT0S/chosen stop entry,
      standard returned rate stops, rate reversals since at, once unserved shares,
      then the premature-stop penalty capped by earned amounts still held across
      parts in mandate order; bond award stays reserved. Seller sends no stop/reverse
      for self-penalty. No seller restitution entry, implicit favourable permission,
      notice waiver, payer early release or multi-stop-entry payments dependency
      remains. Verify shared original filing identities and qualified
      dispute-adapter revised-request/prior-ruling mapping.
- [ ] 1.3 Residual after `serve-running-rate-deals-on-vm` (VM composition): compose
      the rate adapter and authorization hook in the bare-metal storefront's
      settlement composition and runtime registration, following the VM pattern.
      Add only required declarations to affected pyproject.toml files; refresh
      locks through existing tooling. Validate direction with
      `make check-architecture` and the affected package typing checks.

## 2. Durable state, queues and recovery

- [ ] 2.1 Residual after `serve-running-rate-deals-on-vm` (the physical fact, and the
      simple financial fact the meaning of *ended* reads): extend `kit/deal-servicing` and its persistence
      ports/migrations with the end-revision-scoped financial fact (pending and
      unknown operations, case and ruling revisions), completion history, immutable
      effect identities and, when the seller enables it, the funding observation and
      timer (D2, D3). Keep exact bytes in the evidence store. Watching/retention
      continues after both facts, reopening on earlier evidence. Persist
      spot-produced re-anchoring evidence and retiring-key dependency status for
      rate and once-only deals.
- [ ] 2.2 Residual after `serve-running-rate-deals-on-vm` (the per-deal step-order
      helper, loop registration through `kit/storefront` and a durable VM cursor):
      replace the two storefront cycles with one `kit/deal-servicing` loop with
      whole-page physical, bounded authority and second physical passes (D3),
      built on the per-deal step-order helper `serve-running-rate-deals-on-vm`
      introduces and registered through `kit/storefront`. Each composition supplies
      its own recovery steps to the loop. Keep independent pass errors and
      foundation cursor/journal reuse so a newly due end runs without another
      polling interval. Outages skip unverified facts, never pending physical work.
- [ ] 2.3 Residual after `serve-running-rate-deals-on-vm` (stop-cause classification
      without timers): compose the classifier in bare metal. Add the seller's
      opt-in funding timer setting, off by default: replaceable timers without
      speculative lease truncation; read payments before ending at expiry.
      Verified renewal replaces the timer; verified exhaustion supplies an authority
      end without classification. Only an unreachable/unverifiable read journals a
      bare-timer end with pending classification through foundation record_end.
      Later atomic filing resolution discharges exhaustion at/before T or journals
      delivery_end(cause=payee) if billing continued. No synthetic final request or
      second journal. Unverifiable classification stays pending. With the setting
      off, authority-recorded stops remain the only end source.
- [ ] 2.4 Residual after `serve-running-rate-deals-on-vm` (one operator signal):
      expose both completion facts, gap ages, pending operations/cases, end revision
      and manual recovery provenance on lifecycle read/list. Implement D2's warning
      policy using deployment retry/watchdog budgets; leave loops running on
      warning. Surface pending self-penalty cases, unanchored rate deals and
      once-only must-drain retirement dependencies. Measure cadence/teardown budgets
      as seller risk recommendations, never another notice or codec/config gate.
- [ ] 2.5 Residual after `serve-running-rate-deals-on-vm` (stop to teardown,
      authority outage and VM restart): validate at the lowest meaningful level —
      pure timer/fact/revision selection in unit coverage; database
      journal/cursor/restart and pass independence of the one loop in
      `kit/deal-servicing/tests` library-integration coverage. Exercise unknown
      dispatch adoption, late evidence after completion, intent/release_failed
      without release proof, partial-ruling earlier evidence, append/close race,
      reachable last-poll top-up (no end) and outage-hidden top-up after bare-timer
      expiry with the timer enabled. Include runner/online case adoption and
      interruption before result export without reconstructing command bytes.
      Prove bare-metal restart by rebuilding its production application over the
      same database. Kits use the kit-owned clock-injected payments authority
      engine directly, not runnable tooling dependencies. Use injected
      deterministic clocks/ports, not sleeps.

## 3. Delivery and authority work

- [ ] 3.1 Residual after `serve-running-rate-deals-on-vm` (the VM rate delivery
      binding): bind the rate adapter's authorize/start_billing through
      domains/compute/delivery in the bare-metal composition root; do not define the
      protocol or interpret hosted part fields here. Verify the bare-metal storefront
      integration suite. Matrix rows 4 and 8, which drive the delivery path under
      the rate hook, run in task 4.1 here.
- [ ] 3.2 Consume foundation's classified end/self-penalty filing journal for
      unentitled site/operator/failed delivery, never future-dated; pre-start failure
      journals immediately and files at Agreement start. Route delivery_end only
      through the dispute adapter to the Agreement authority; seller sends no stop
      or reverse. Qualify mediation's sole mechanical ruling for a payee request at
      least as strong as standard, using its own PT0S/chosen entry for returned rate
      stops, rate reversals since at, time-based once refunds, then the premature-stop
      penalty capped by earned amounts still held, across parts in mandate order;
      bond award stays reserved for hosted bonds. Matrix row 10 must prove an
      on-demand emergency pays it at both ends of the cap — the stated amount late
      in a deal, the setup charge alone minutes after activation, zero with no setup
      charge — and entitled spot notice pays none. Add opt-in timer classification
      via foundation's atomic filing resolution. Resolve unknown original filings
      before revised requests; consume the dispute adapter's qualified revision
      mapping and prior-ruling netting, not local monetary deltas or
      append-as-amendment. Adopt equivalent runner cases under shared original
      identities without duplicate filings. Missing safe coverage is repair
      required. delivery_end uses receipt concurrence or later payee agreement for
      mechanical ruling under the foundation guards, otherwise human triage, carries
      exact Agreement verified against mandate deal hash and uses payer
      notice/partialPeriod.
- [ ] 3.3 Consume foundation site-report ingestion as a final-request source and
      attribution evidence, not completion proof; use capacity-release proof for
      that. Exercise, do not reimplement, its buyer evidence projection,
      stop-plus-hint for nonzero notice, explicit end-now and delivery_end fallback.
      Verify late-evidence paths in both domains and bare-metal outage paths with
      injected payment and mediation adapters in library/service integration
      coverage.
- [ ] 3.4 Add stateless recovery runner in kit/deal-servicing and domain CLI adapter
      composition. Add seller-authenticated read-only evidence export through
      kit/deal-lifecycle-contracts, kit/deal-lifecycle-client and both storefronts;
      retain exact Agreement/mandate/commitment and evidence, never credentials.
      Persist D6's immutable command envelope/descriptors before I/O and replay from
      it after interruption before result export. Export original filing identities;
      read/adopt equivalent existing seller cases and enforce same-intent resolution
      plus qualified dispute revision mapping; self-penalty has no direct seller
      payment effects. Never open storefront persistence offline. Export exact
      results and verify watch adoption after restart. Extend contracts/client with
      local administrator submit kind acknowledge_physical_recovery, observed
      non-future at, local audit acceptance, principal/reason/resource/revision
      binding and same-key result recovery; it cannot certify money.
- [ ] 3.5 Residual after `serve-running-rate-deals-on-vm` (VM startup coherence and
      withdrawal): implement startup coherence and declaration withdrawal in the
      bare-metal composition. During a payments identity overlap request spot's rate
      re-anchoring evidence in both compositions, persist it before retirement and
      expose unanchored rate / once-only must-drain dependencies. Run relevant
      existing tests in `kit/arkhai-payments/tests`, `kit/deal-servicing/tests`,
      `domains/vms/storefront/tests/integration` and
      `domains/bare_metal/storefront/tests/integration`, plus affected package
      typing. During implementation fix changed comments/import placement before
      review.
- [ ] 3.5a Make the mediation double execute a programmed ruling's `stop` and
      `penalty` effects at the payments double — a stop's partial period and time
      against payments' own now, and a penalty's reverse of earned amounts still
      held across parts in mandate order — in `tools/mediation-lane-double`,
      removing their refusal at install. Prove each through the double's suite over
      HTTP before any row that programs them runs.

## 4. Lane qualification and pre-closeout review

- [ ] 4.1 Residual after `serve-running-rate-deals-on-vm` (rows 0, 6, 7 and 9 in
      their reduced VM form): extend e2e-tests/tests/e2e/roles/scenarios and shared
      stages with the rest of D's rate matrix — rows 0, 6, 7 and 9 in the bare-metal
      lane and their VM residual variants (a seller-enabled setup part, the opt-in
      timer variants, the earlier payer stop, returned treatment, late start and
      mid-period end), and rows 1–5, 8 and 10–13 in both lanes — executing spot's
      prepared entry points, including:
      - scenario 4, stop between start and disclosure, both domains: the
        activate/start/disclose races, no start before activation and no duplicate
        start key across crashes;
      - scenario 8, activated but never disclosed, both domains: post-activation
        start refusal and the started-but-undisclosed failure, filed at the deal
        start with the buyer-case backstop.
      Record maximum term plus on-demand/spot emergency delivery_end filings, sole
      mechanical payee self-penalty and on-demand returned treatment. Record buyer
      case/held money plus premature-stop-penalty remedy, not mandate-enforced
      non-preemption. Record rows 12, 12a, 12b and 13: the seller that never files,
      remedied by the buyer's stop and case from kept evidence alone with the
      storefront stopped, not flagged; the late anchor, where the site's longer
      physical deadline changes nothing about the ruling from the buyer's kept
      approval record; the asserted availability, the seller's timely `available`
      weighed against the buyer's kept observation and conclusive on its own for
      neither; and the case over paid-out money, accepted, `not_held` per part,
      displayed as such. Exercise buyer-half same-key payment-stop retry with
      billing until landing; end_delivery receipt grants no storefront payment
      authority. Rows 7/9 record the buyer acceptance policy and preset treatment
      the terms change ships. Once-only activation expiry stays compute delivery's.
      Follow `TESTING.md`'s discipline: wait only for a stage's own effect or an
      Agreement-fixed instant, and drive elapsed time by advancing every perceived
      clock together through the joint lane clock fixture. A row that holds a
      ruling at its gate steps no storefront servicing while the ruling waits.
      Pause/step the one loop; assert authority effects, evidence and both facts.
      Lane pause is not restart proof.
- [ ] 4.1a Compose a perceived clock in the bare-metal storefront from the mechanism
      `drive-the-storefront-clock-in-lanes` keeps shareable: wall time by default and
      refused in production, routes mounted only when enabled, and the bare-metal
      lane's clock fixture moving it with both doubles' clocks and resetting all of
      them whatever a module's outcome.
- [ ] 4.2 Exercise additional remote-stop windows, both-authority outage replay,
      lost acknowledgement plus earlier evidence, stale/invalid/regressed snapshots,
      buyer ends before/during/after provisioning, late evidence after completion
      with a revision correction during partial effects or append/close races,
      manual recovery, declaration checks, setup once churn pricing and rotation
      across a running deal. Reuse lowest-level adapter coverage for arithmetic
      rather than cloning it in e2e.
- [ ] 4.3 Residual after `serve-running-rate-deals-on-vm` (the lane-double evidence
      label): label every row this change adds lane-double evidence, never live.
      Commit reproducible setup/evidence indexes with public fixture aliases and no
      secrets/private logs. Ensure both domain complete-deal pipelines pass. No
      production declaration is enabled by this change.
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
      servicing gap, held-money/buyer-stop safety, seller-liveness limitation and
      the lane-wide perceived clock row (the bare-metal storefront's share); retain
      hosted activation as a gap. Record the update in the promotion record.
- [ ] 5.6 Campaign index currency: update this row/status and dependency graph in
      `openspec/changes/README.md`; preserve dependents until archive cleanup. Record
      the update and run `make check-change-index`.
- [ ] 5.7 Packaging: run `make check-packaging` and
      `make check-architecture-change CHANGE=converge-ongoing-compute-leases`;
      own no expired exception. Run `make check-agent-skills` if agent instructions
      changed. Any failure needing code returns to implementation.
- [ ] 5.8 End-to-end pipeline: record passing VM/bare-metal complete-deal runs and
      the remaining rate-matrix qualification including spot entry points, and
      bare-metal production-application rebuild evidence, with exact provenance.
      Missing prerequisite or pipeline failure is an explicit blocker, not passing
      evidence.
- [ ] 5.9 Promotion: after code review, write current-state rationale in
      `openspec/specs/deal-lifecycle/architecture.md` for end service/guarantee limits
      and the opt-in funding timer, composition ownership in
      `openspec/specs/market-composition/architecture.md`, evidence rationale in
      `openspec/specs/test-compatibility/architecture.md`, the timer setting in
      `docs/development/DEPLOYMENT_AND_CONFIG.md`, and repository-wide
      servicing/authority boundaries in `docs/development/ARCHITECTURE.md`.
      Promote the nine drawio/SVG pairs to `docs/development/diagrams/` and update
      their citations. Update `openspec/specs/README.md` if needed; complete the
      promotion record. Spec deltas merge at archival, not by hand; requirements
      marked owned by another change are removed from this change's deltas once
      that change's delta carries them.
- [ ] 5.10 Documentation citations: run
      `make check-doc-citations CHANGE=converge-ongoing-compute-leases`, resolve all
      citations, then `scripts/change-workflow openspec validate
      converge-ongoing-compute-leases --strict`. Run
      `make check-change CHANGE=converge-ongoing-compute-leases` before archival.
- [ ] 5.11 Archival: only after every preceding task passes, run
      `openspec archive converge-ongoing-compute-leases -y` using the repository pin,
      merging deltas and linking the archived directory from the index. Closeout
      review/triage reads archived documents; archive cleanup rechecks dependents.

## Design promotion record

All destinations below are planned, not yet promoted.

| Accepted decision | Permanent location |
|---|---|
| D1/D7 neutral storefront ownership, the one kit loop and bare-metal startup | market-composition spec/architecture; ARCHITECTURE kit areas and settlement servicing |
| D2 financial fact under the MVP's meaning of *ended*, diagnostics/manual command | deal-lifecycle spec/architecture |
| D3 whole-page passes and the opt-in funding timer | deal-lifecycle spec/architecture; DEPLOYMENT_AND_CONFIG timer setting |
| D4 bare-metal rate binding | deal-lifecycle spec; ARCHITECTURE authority boundaries |
| D5 timer classification, self-penalty filings/revised rulings, honest residual | deal-lifecycle spec/architecture; ARCHITECTURE settlement servicing |
| D6 stateless recovery/export/envelope, foundation buyer/evidence consumption | deal-lifecycle spec/architecture |
| D7 rotation overlap consumption | deal-lifecycle spec/architecture |
| Remaining rate matrix, integration restart boundary, lane time, bare-metal storefront clock and the mediation double's ruling effects | test-compatibility spec/architecture; docs/development/diagrams/ |
| Goal 8 servicing and residual gaps | docs/development/ROADMAP.md, at closeout |
| Row/status/dependency graph | openspec/changes/README.md, at closeout |
