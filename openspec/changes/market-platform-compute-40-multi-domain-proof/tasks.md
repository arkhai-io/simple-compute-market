# Implementation Tasks

**Rewritten 2026-08-06.** Section 1's completed prerequisite evidence is preserved
verbatim — it remains true and was independently verified. Sections 2 onward are
replaced: the original's implementation work has shipped or moved, and its 2×2 topology
is superseded. The original task list is in Git history.

## 1. Reconciled prerequisite evidence (preserved)

- [x] 1.1 Confirm the common domain contract, capacity-identity contract, and extracted compute service are implemented, synchronized, archived, and covered by focused tests.
- [x] 1.2 Inventory current adapter composition, provider registration, dispatch, release, event sink, cross-mode admission, multi-site aggregation, and domain-conformance coverage; record gaps in `design.md`.
- [x] 1.3 Verify one compute service can compose VM and bare-metal adapter bundles and expose durable jobs through the common compute contract.
- [x] 1.4 Verify both VM-shareable→bare-metal-exclusive and bare-metal-exclusive→VM-shareable conflicts within one site, plus capacity restoration after release.
- [x] 1.5 Verify generic site/compute import boundaries and VM, bare-metal, and API-credit market-domain conformance.
- [x] 1.6 **Re-grounded 2026-08-06.** Confirm what has shipped since: site-pinned routing with no fallback (implemented and promoted to `storefront-publication`), cross-mode conflict (implemented in `kit/site`, normative in `site-capacity`), concurrent adapter composition (`compose_adapter_bundles`). Confirm two implicit `"vm"` fallbacks remain and are owned by `pool-declared-offering-modes`. Confirm no end-to-end scenario references bare metal, API credits, or more than one authority.

## 2. Complete prerequisites

- [ ] 2.1 Confirm `multi-domain-storefront-composition` has landed; the storefront under
      test is one process hosting both compute contracts.
- [ ] 2.2 Confirm the bare-metal deal path exists end to end —
      `market-platform-bare-metal-10-storefront-composition` for the seller side and
      `bare-metal-buyer-domain` for the buyer side.
- [ ] 2.3 Confirm `pools-7-storefront-fulfillment-cutover`'s selected-site scheduling,
      durable fulfillment, pull result, restart recovery, and teardown are accepted.
- [ ] 2.4 Confirm `pool-declared-offering-modes` has removed both implicit executor
      fallbacks and landed the legacy-row policy this change no longer owns.
- [ ] 2.5 Record exact wheel and image versions and the deterministic backend controls
      the topology uses.

## 3. Extend the shared fixtures to a second authority

- [ ] 3.1 Extend the end-to-end fixtures `bare-metal-and-credits-domain-stacks`
      generalizes so a scenario can address more than one authority.
- [ ] 3.2 Do not build a parallel multi-authority harness. If the generalized fixtures
      cannot be extended, that is a finding about those fixtures, not a reason to fork —
      forking guarantees the two drift.
- [ ] 3.3 Add observable job, result, and release barriers so the scenario needs no
      sleeps for correctness.

## 4. Stand up the topology

- [ ] 4.1 Start one compute storefront hosting both market-domain contracts, with
      durable writable state.
- [ ] 4.2 Start authority A and authority B, each composing VM and bare-metal adapter
      bundles with controlled production-compatible backends.
- [ ] 4.3 Configure operator-trusted bindings to both authorities, with no
      buyer-controlled routing credentials.
- [ ] 4.4 Seed authority-local Physical Resource fixtures supporting deterministic
      placement and cross-mode conflict, without assuming identifiers are unique across
      authorities.

## 5. Exercise every domain-to-authority edge

- [ ] 5.1 Complete a VM lifecycle at authority A and at authority B, through reservation,
      scheduling, fulfillment, pull result, teardown, and capacity restoration.
- [ ] 5.2 Complete a bare-metal lifecycle at each authority through the same shared
      contracts.
- [ ] 5.3 Verify each authority executes at least one lifecycle of each domain, and never
      selects an adapter from storefront identity or provider identity.
- [ ] 5.4 Verify the storefront persists the selected authority per lifecycle and routes
      all later state-changing operations only there.
- [ ] 5.5 Verify each domain retains its own market semantics, agreement state, receipts,
      and results while sharing authorities. **Amended 2026-08-06:** the original also
      required separate databases; under multi-domain composition the domains share one
      storefront store, so separation is of semantics and state ownership, not of
      persistence.

## 6. Prove recovery and isolation

- [ ] 6.1 Restart the storefront after reservation and verify durable selected-authority
      lookup resumes fulfillment without fan-out or cross-authority fallback.
- [ ] 6.2 Restart an authority during accepted work and verify recovery converges without
      duplicate infrastructure dispatch.
- [ ] 6.3 Make a selected authority unavailable and verify the owning lifecycle reports or
      retries there rather than submitting elsewhere.
- [ ] 6.4 Re-run both cross-mode conflict directions and verify rejection precedes
      executor job creation.
- [ ] 6.5 Verify pool, provider, and access aliases within an authority cannot represent
      one Physical Resource as independent capacity, and that textually equal identifiers
      across authorities are never conflated.
- [ ] 6.6 Verify duplicate polling and teardown are idempotent and capacity is restored
      exactly once.
- [ ] 6.7 Verify a missing, unknown, or conflicting executor identity fails before adapter
      or infrastructure work, with no default substituted.

## 7. Verification and promotion

- [ ] 7.1 Run the topology scenario, the storefront integration suites, compute service
      unit and integration suites, site and fulfillment suites, and domain conformance
      suites. Disclose any suite not run.
- [ ] 7.2 Rebuild affected wheels and images; verify the storefront and both authorities
      install without editable sibling paths or undeclared domain dependencies.
- [ ] 7.3 Run deployment-render and configuration tests for the multi-authority bindings.
- [ ] 7.4 Treat any defect the proof exposes as a defect in the owning capability. Fix it
      there and reference it here; do not patch the harness and do not absorb the fix.
- [ ] 7.5 Promote the deterministic topology evidence to
      `openspec/specs/test-compatibility/spec.md` and `architecture.md`, and the accepted
      topology map to `docs/development/ARCHITECTURE.md`.
- [ ] 7.6 **Amended 2026-08-06.** The original promoted "the one-domain storefront
      boundary" to `market-composition/architecture.md`. That position is superseded;
      promote instead that one storefront hosting a family's contracts shares authorities
      without sharing market semantics. Verify nothing in this change's promotion
      reintroduces the superseded boundary.
- [ ] 7.7 Run strict OpenSpec validation and archive only after the proven behavior is
      represented as current permanent architecture.

## 8. Closeout

Per `openspec/README.md#plan-closeout-requirements`.

- [ ] 8.1 **Comment hygiene.** Run `make check-comment-hygiene`.
- [ ] 8.2 **Import placement.** Review imports this change adds or touches; a proof
      harness must not acquire production dependencies to reach internals.
- [ ] 8.3 **Documentation compliance.** Confirm the topology requirement landed in
      `test-compatibility` and the topology map in `ARCHITECTURE.md`, and that no
      requirement promoted here asserts one market domain per storefront process.
- [ ] 8.4 **Narrative compression.** Compress completed-task notes to final behavior and
      validation evidence, including whether the topology ran live.
- [ ] 8.5 **Roadmap currency.** Update Goal 3's current-state description and gap mapping
      in `docs/development/ROADMAP.md`, including removing the unreconciled-contradiction
      note this rewrite resolves.
- [ ] 8.6 **Promotion.** Complete the design-promotion record below.

## Design promotion record

| Accepted decision | Permanent location |
|---|---|
| A deterministic multi-authority topology proves every domain-to-authority edge, restart, isolation, cross-mode rejection, and executor strictness | `openspec/specs/test-compatibility/spec.md` — "Deterministic multi-authority topology proof" |
| The accepted topology map | `docs/development/ARCHITECTURE.md` |
| One storefront hosting a family's contracts shares authorities without sharing market semantics | `openspec/specs/market-composition/architecture.md` |
| Why many-to-many storefront-to-authority ownership was removed rather than deferred, and why the second storefront was never what made the proof work | This change's `design.md` |
