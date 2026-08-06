# Implementation Tasks

Sections 1–3 are additive and inert; Section 4 is the behavioral boundary.

## 1. Declared-mode vocabulary

- [ ] 1.1 Re-verify `design.md`'s Context findings, particularly the ledger's
      executor-kind inference at both the reserve and supersede sites and the second
      implicit fallback in `deal_event_sink`.
- [ ] 1.2 Add a deliverable-modes policy tag to `kit/resource-pools`' hint vocabulary
      with a typed reader, matching the existing tags' validation posture — well-formed
      set, no knowledge of which modes are meaningful.
- [ ] 1.3 Confirm the declaration inherits projection, precedence, and administration
      from the existing hint mechanism with no new configuration channel.
- [ ] 1.4 Focused tests: declared set projects and resolves; malformed declaration
      rejected at the reader; absent declaration resolves to empty rather than to a
      permissive default.

## 2. Explicit requested mode

- [ ] 2.1 Carry the requested offering mode on the capacity claim, and make
      `authority.py`'s existing `executor_kind` parameters authoritative rather than
      advisory.
- [ ] 2.2 Remove the ledger's inference at **both** sites — the reserve path and the
      supersede path.
- [ ] 2.3 Remove `deal_event_sink`'s `or "vm"` fallback. `design.md` names this as the
      second fallback that survives if only the first is removed. Coordinate with
      `market-platform-compute-40-multi-domain-proof`, which also requires it gone.
- [ ] 2.4 **Moved here 2026-08-06 from `market-platform-compute-40-multi-domain-proof`
      task 3.2.** Define and implement an explicit migration, backfill, or quarantine
      policy for durable reservation and lease rows that carry no recorded executor
      identity. This change removes the fallback those rows rely on, so it owns the
      migration for what depended on it; the proof change it came from should not gate a
      production data migration. Removing the fallbacks without this is a regression for
      every such row.
- [ ] 2.5 Inventory every remaining `executor_kind or "vm"`, default executor, and
      missing-identity compatibility path across compute contracts, persistence,
      dispatch, result handling, and release — not only the two fallbacks `design.md`
      names, which were found by inspection rather than by exhaustive search.
- [ ] 2.6 Focused tests: recorded executor identity comes from the request; a claim
      omitting the mode does not acquire one from the matched resource; supersede
      carries the request's mode; a legacy row with no identity takes the defined policy
      rather than a default.

## 3. Derivation migration

- [ ] 3.1 Derive declared modes for every existing pool, including the system-owned
      `default`, from the configuration that demonstrably produces each mode — provider
      kind, playbook, requirement delegate — not from reservation history.
- [ ] 3.2 Report the derived set at INFO, matching how the existing seeding steps report
      theirs, so an operator can see what was concluded on their behalf.
- [ ] 3.3 Validate the migration per `TESTING.md`: fresh bootstrap, idempotent rerun,
      drift detection.
- [ ] 3.4 Focused tests: a pool serving VMs today derives the VM mode; the default pool
      is included; derivation never widens a pool beyond what it can deliver.

## 4. Enforcement

- [ ] 4.1 Refuse an undeclared mode at reservation, before a hold exists, with the
      refusal naming the undeclared mode.
- [ ] 4.2 Enforce independently at scheduling and before provisioning. Share one
      predicate across all three; do not reimplement per layer.
- [ ] 4.3 Ensure a held reservation whose pool declaration is later narrowed does not
      proceed to provisioning in the withdrawn mode.
- [ ] 4.4 Confirm this check is separate from `Cross-mode physical accounting` and that
      neither subsumes the other: a pool may declare two modes and still refuse an
      exclusive claim against a host with a live shareable slice.
- [ ] 4.5 Focused tests: undeclared mode refused at each layer independently; withdrawn
      declaration blocks provisioning of a held reservation; both mode checks apply
      together.

## 5. Validation

- [ ] 5.1 Run the `kit/site`, `kit/resource-pools`, and provisioning scheduling suites,
      plus an e2e path proving an undeliverable mode is refused at reservation rather
      than at provisioning. Disclose any suite not run.
- [ ] 5.2 Confirm no implicit executor-kind default survives anywhere — search rather
      than assume; there were two.
- [ ] 5.3 Run `openspec validate --all --strict` against the baseline current at
      implementation time.

## 6. Closeout

Per `openspec/README.md#plan-closeout-requirements`.

- [ ] 6.1 **Comment hygiene.** Run `make check-comment-hygiene`. Read the ledger's
      executor-kind lines and their surrounding comments directly; they describe
      inference this change removes.
- [ ] 6.2 **Import placement.** Review imports this change adds or touches; kit must
      acquire no service or domain dependency.
- [ ] 6.3 **Documentation compliance.** Confirm the declaration rule landed in
      `resource-pool-management`, the enforcement rules in `site-capacity`, and that
      `ARCHITECTURE.md`'s authority table states which side decides how hardware may be
      delivered.
- [ ] 6.4 **Narrative compression.** Compress completed-task notes to final behavior,
      validation evidence, and promotion destinations.
- [ ] 6.5 **Roadmap currency.** Update Goal 3's current-state description and gap
      mapping in `docs/development/ROADMAP.md`.
- [ ] 6.6 **Promotion.** Complete the design-promotion record below.

## Design promotion record

| Accepted decision | Permanent location |
|---|---|
| A pool declares its deliverable offering modes; declaring none delivers nothing; existing pools are derived | `openspec/specs/resource-pool-management/spec.md` — "Pool-declared offering modes" |
| The requested mode is explicit, never inferred from a matched resource attribute | `openspec/specs/site-capacity/spec.md` — "Requested offering mode is explicit and bounded by the pool" |
| Enforcement is independent at reservation, scheduling, and provisioning | `openspec/specs/site-capacity/spec.md` — "Offering mode is enforced through fulfillment" |
| Which side decides how hardware may be delivered | `docs/development/ARCHITECTURE.md` authority boundaries |
| Why declaration is per pool rather than per host, and why capability and conflict are separate checks | This change's `design.md` |
