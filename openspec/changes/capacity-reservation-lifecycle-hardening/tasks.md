# Implementation Tasks

## 1. Comparable, indexed hold expiry

- [ ] 1.1 Re-verify `design.md`'s Context findings before editing, particularly that
      `_expire_stale_holds` still materializes all held rows and that `hold_expires_at`
      is still an unindexed ISO string.
- [ ] 1.2 Store the hold-expiry instant in a datastore-comparable form and index it.
- [ ] 1.3 Migrate existing rows. Fail loudly on an unparseable value — a defaulted
      expiry either leaks capacity or releases it early, and both are worse than a
      failed migration.
- [ ] 1.4 Ensure no code path reads both representations; convert rather than adding an
      opportunistically-read parallel column.
- [ ] 1.5 Validate the migration per `TESTING.md`: fresh bootstrap, idempotent rerun,
      drift detection.

## 2. Bounded expiry evaluation

- [ ] 2.1 Replace the full scan with a range query selecting due rows only.
- [ ] 2.2 Narrow the lazy check to operations whose own correctness depends on current
      availability; remove it from read-only paths. Do **not** remove it wholesale —
      `design.md` records this as the decision most likely to be over-applied, and
      dropping it from admission converts a correctness property into a timing race.
- [ ] 2.3 Confirm `expire_due_holds()` and its watchdog remain the bulk sweep for an
      idle site, as that method's own docstring describes.
- [ ] 2.4 Focused tests: many outstanding holds and none due loads nothing; a hold
      expiring between sweeps does not block admission; an idle site still releases
      expired holds.

## 3. Generalized reservation idempotency

- [ ] 3.1 Accept a durable pre-settlement identity as an idempotency key alongside the
      existing settlement identity, without replacing the latter.
- [ ] 3.2 Supply that identity from the storefront's hold placement, which today passes
      `listing_id` and a negotiation identity but no key the ledger reads.
- [ ] 3.3 Assert the near-miss explicitly: keying on listing identity alone must not be
      possible, since two counterparties on one listing would collapse into one
      reservation.
- [ ] 3.4 Focused tests: retried placement returns the same reservation; two
      counterparties on one listing get two; placement after expiry admits fresh.

## 4. Terminal reservation retention

- [ ] 4.1 Add retention bounded by age **and** by reference, never by row count.
- [ ] 4.2 Default the window conservatively; the problem is unbounded growth, not disk
      pressure.
- [ ] 4.3 Focused tests: aged and unreferenced is removed; aged and referenced is
      retained; heavy volume does not evict earlier.

## 5. Validation

- [ ] 5.1 Run the `kit/site` ledger suites, the provisioning watchdog tests, and
      migration validation. Disclose any suite not run.
- [ ] 5.2 Run `openspec validate --all --strict` against the baseline current at
      implementation time.

## 6. Closeout

Per `openspec/README.md#plan-closeout-requirements`.

- [ ] 6.1 **Comment hygiene.** Run `make check-comment-hygiene`. Read `reserve()`'s
      idempotency docstring and `_expire_stale_holds`' directly; both describe the
      behavior this change alters.
- [ ] 6.2 **Import placement.** Review imports this change adds or touches.
- [ ] 6.3 **Documentation compliance.** Confirm the three rules landed in
      `openspec/specs/site-capacity/spec.md` and the rejected alternatives (replacing
      rather than generalizing the key; count-based retention; removing lazy expiry
      wholesale) stayed in `design.md`.
- [ ] 6.4 **Narrative compression.** Compress completed-task notes to final behavior,
      validation evidence, and promotion destinations.
- [ ] 6.5 **Roadmap currency.** Record the disposition. This change closes no roadmap
      goal's gap on its own; if the capacity-economics work has by then been recorded as
      a goal, update its current state instead of skipping the step.
- [ ] 6.6 **Promotion.** Complete the design-promotion record below.
- [ ] 6.7 **Campaign index currency** (part seven, added when
      `openspec/README.md#plan-closeout-requirements` was extended from six parts to seven).
      Appended rather than folded into an existing task, per `AGENTS.md`'s rule to amend
      rather than replace implementation history. Update this change's row, and its
      campaign's dependency graph, in `openspec/changes/README.md` to match its state at
      completion, or record the disposition here if its status and campaign placement are
      both unchanged.

## Design promotion record

| Accepted decision | Permanent location |
|---|---|
| A durable pre-settlement identity is an idempotency key alongside the settlement identity, and must distinguish separate placements | `openspec/specs/site-capacity/spec.md` — "Pre-settlement reservation idempotency" |
| Expiry costs in proportion to due holds, is scheduled, and admission still evaluates due holds | `openspec/specs/site-capacity/spec.md` — "Bounded hold expiry evaluation" |
| Terminal reservations are retained by age and reference, never by count | `openspec/specs/site-capacity/spec.md` — "Terminal reservation retention" |
| Why the key was generalized rather than replaced, and why keying on listing identity is the dangerous near-miss | This change's `design.md` |
