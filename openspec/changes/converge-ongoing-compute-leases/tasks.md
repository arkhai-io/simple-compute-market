# Tasks — rate-part servicing inside end service

This is an implementation plan, not completed runtime work. All tasks are pending.
Review the foundation/spot/unified-delivery contracts at their landing revisions
before code starts; no superseded Goal 8 change is an implementation gate.

## 1. Dependency and composition gate

- [ ] 1.1 Confirm `agreed-evidence-and-early-termination` supplies lifecycle commands,
      read/list/watch, per-record cursors, evidence stores, end-service admission,
      buyer stop/end_delivery/buyer_end and mediation request mapping. Record exact
      contract bindings; stop on a missing interface rather than duplicating it.
- [ ] 1.2 Confirm `spot-deals-through-arkhai-payments` supplies rate-part verification,
      payee-only start, authority-hosted notices, afterStop holds, corrections,
      cumulative-target operation keys, period arithmetic and rotation re-anchoring.
      Confirm `unify-compute-delivery-path` supplies dispatch/start/activation/
      disclosure and physical ports. Gate scenario runs on payment/mediation doubles.
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
- [ ] 2.2 Implement physical-first independent queues (D3), bounded authority I/O,
      per-record cursor advancement after journaling, and prompt physical scheduling
      when authority work learns a due end. Make outages skip unverified facts,
      never pending physical work. Reuse foundation watch and journal mechanisms.
- [ ] 2.3 Implement replaceable funding timers without speculative lease truncation;
      persist final requests only on expiry. Preserve future effective notice times
      from authority records and compose earliest-final-request semantics.
- [ ] 2.4 Expose both completion facts, gap ages, pending operations/cases and manual
      recovery provenance on lifecycle read/list. Implement D2's recommended warning
      policy using deployment retry/watchdog budgets; leave loops running on warning.
      Verify configured cadence and teardown against measured domain latencies and
      the foundation's exposure_seconds publication/acceptance/config-change gates.
- [ ] 2.5 Validate at the lowest meaningful level: pure timer/fact/revision selection
      in unit coverage; database journal/cursor/restart and queue independence in
      `kit/deal-servicing/tests` library-integration coverage. Exercise no dispatch,
      unknown dispatch adoption, physical failure, authority outage and late evidence
      after completion. Use injected deterministic clocks/ports, not sleeps.

## 3. Delivery and authority work

- [ ] 3.1 Implement the rate-part authorization phases in `kit/deal-servicing` using
      injected adapter evidence; wire both domain delivery ports. Provision before
      start, persist stable start key/evidence before I/O, resolve unknown outcomes,
      and serialize due ends with dispatch and disclosure. Refusal follows the one
      unified undelivered path. Verify in both storefront integration suites.
- [ ] 3.2 Journal exceptional_end(at) atomically with an unentitled final request;
      failed/never-started delivery uses deal start. Drive dispute submission/append
      through its adapter and observe authority effects, including post-stop reverse
      and case extensions. Consume the spot adapter's cumulative target and period
      rules rather than implementing financial arithmetic in end service.
- [ ] 3.3 Ingest exact site-signed lease_ended once and expose it on buyer lifecycle
      read through the foundation-owned route contract; keep buyer end_delivery
      acknowledgements. Compose, do not reimplement, the buyer's stop-first and
      buyer_end fallback flow. Verify outage and late-evidence paths with injected
      payment and mediation adapters in library/service integration coverage.
- [ ] 3.4 Compose the seller half for offline operator recovery against the stopped
      storefront's owned persistence. Entitled notice goes to payment authority;
      unentitled exit files exceptional_end. Add audited manual physical recovery
      separately; it never confirms money. Verify authentication, reason retention,
      stable operation key and refusal of a competing writer in focused integration.
- [ ] 3.5 Implement startup coherence and declaration withdrawal behavior in both
      compositions. Reuse spot identity-rotation re-anchoring. Run relevant existing
      tests in `kit/arkhai-payments/tests`, `kit/deal-servicing/tests`,
      `domains/vms/storefront/tests/integration` and
      `domains/bare_metal/storefront/tests/integration`, plus affected package typing.
      During implementation fix changed comments/import placement before review.

## 4. Lane qualification and pre-closeout review

- [ ] 4.1 Extend `e2e-tests/tests/e2e/roles/scenarios` and shared stages with the nine
      D-scenarios in design.md for VM and bare metal, using the in-lane payment and
      mediation doubles. Gate on lane readiness, pause/step every dependent loop,
      and assert authority effects, evidence and both facts at each transition.
- [ ] 4.2 Exercise additional remote-stop windows, both-authority outage replay,
      lost acknowledgement plus earlier evidence, stale/invalid/regressed snapshots,
      buyer ends before/during/after provisioning, late evidence after completion
      with an open-case append or a new revision-bound filing for a closed case, manual recovery, declaration checks, setup
      once churn pricing and rotation across a running deal. Reuse lowest-level
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
      nine-scenario qualification with exact provenance. Missing prerequisite or
      pipeline failure is an explicit blocker, not passing evidence.
- [ ] 5.9 Promotion: after code review, write current-state rationale in
      `openspec/specs/settlement-servicing/architecture.md`, composition ownership
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
| D2 two facts, revision-scoped finance, gap diagnostics | settlement-servicing spec/architecture |
| D3 independent queues, timers, cursor/retry behavior | settlement-servicing spec/architecture |
| D4 admission, physical revocation and exposure | settlement-servicing spec/architecture; ARCHITECTURE authority boundaries |
| D5 holds, self-filing, late evidence, honest residual | settlement-servicing spec/architecture; ARCHITECTURE settlement servicing |
| D6 composed buyer/seller commands and kept evidence | settlement-servicing spec/architecture; foundation-owned lifecycle docs cross-reference |
| D7 activation/declaration boundary | market-composition spec/architecture; activation-owned configuration docs cross-reference |
| Nine scenarios/evidence classes | test-compatibility spec/architecture; docs/development/diagrams/ |
| Goal 8 servicing and residual gaps | docs/development/ROADMAP.md, at closeout |
| Row/status/dependency graph | openspec/changes/README.md, at closeout |
