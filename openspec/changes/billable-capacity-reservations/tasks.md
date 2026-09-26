# Implementation Tasks

Sections 1–2 are inert without Section 3, which is the buyer-visible deployment
boundary described in `design.md`.

## 1. Reservation carries a rate and a funded bound

- [ ] 1.1 Re-verify `design.md`'s Context, particularly that `CapacityReservation`
      still carries no rate or funding reference, that `capped_hold_seconds` still
      caps a configured TTL, and that hold placement is still the kit's `place_hold`
      hook.
- [ ] 1.2 Add the burn rate and funded bound to the reservation, both nullable and
      unused at this stage.
- [ ] 1.3 Add the hold rate beside the lease rate in each resolution tier —
      `kit/pool-overrides`' VM terms contract, the pool pricing hint, and
      `[pricing.defaults.<family>]` — in the same family-grouped form, and resolve it
      through the same tiers, falling back to the lease rate at any tier that states
      no hold rate.
- [ ] 1.3a Derive the burn rate by evaluating the hold rate structure against the held
      shape through `capacity-shape-pricing`'s aggregation interface, in exact integer
      arithmetic with upward rounding; refuse a burn rate the asset's amount type
      cannot represent. Do not reconstruct a total from individual dimension rates.
      The negotiated lease multiplier is not an input.
- [ ] 1.4 Focused tests: burn rate derived for a multi-dimension shape; a stated hold
      rate wins over the lease rate at its tier; an unstated hold rate falls back to
      the lease rate at that tier; a lease-rate change moves an unstated hold rate
      with it and leaves a stated one alone; a base-unit amount above 2^63 survives
      derivation.

## 2. Hold obligation lifecycle

- [ ] 2.1 Generate the hold obligation from the burn rate and funded maximum duration,
      reusing `add-settlement-plan-shapes`' per-obligation identity, materialization,
      collection, reclaim, and receipt machinery.
- [ ] 2.2 Do **not** reuse interval generation: those escrows derive from an accepted
      total, duration, and schedule, and no accepted total exists before agreement.
      Reusing the lifecycle while replacing the generation rule is the whole
      integration.
- [ ] 2.3 Determine the collectable amount from time actually held; return the
      unconsumed remainder on early end, whether by commitment, release, or abandonment.
- [ ] 2.4 Gate collection on capacity having been held exclusively, not on elapsed clock
      time alone, so a hold the seller did not honor is not charged.
- [ ] 2.5 Focused tests: full-duration hold collects fully; early release returns the
      remainder; unhonored hold is not collectable; servicing restart resumes without
      double-collecting or double-returning.

## 3. Derived maximum duration

The behavioral boundary. After this section a hold without committed funds cannot be
placed.

- [ ] 3.1 Derive maximum hold duration from committed funds divided by burn rate.
- [ ] 3.2 Demote `hold_ttl_seconds` and the pool's `max_reservation_hold_seconds` to
      ceilings on the derived value. Keep their names and capping behavior; change only
      which value is primary.
- [ ] 3.3 Assert the direction explicitly: a hold must not expire with committed funds
      unconsumed. `design.md` records the inverse reading as the plausible-looking
      mistake, and it silently overcharges relative to service delivered.
- [ ] 3.4 Confirm funds exhaustion is ordinary expiry through the existing path, not a
      special case.
- [ ] 3.5 Restore a non-zero `hold_ttl_seconds` default for both storefronts, reversing
      `default-no-pre-settlement-capacity-hold`, and replace that change's security
      justification comment with one describing the new posture. The restoration is
      safe only because holding now costs the holder; state that in the comment rather
      than silently raising the value.
- [ ] 3.6 Focused tests: funded bound governs below the ceiling; ceiling governs above
      it; exhaustion lapses the hold normally.

## 4. Supersede repricing

- [ ] 4.1 Recompute burn rate and remaining affordable duration inside
      `resize_reservation`'s existing atomic transaction.
- [ ] 4.2 Ensure the superseding reservation never inherits the superseded rate.
- [ ] 4.3 Verify a rolled-back supersede leaves the original rate and remaining duration
      untouched — the transaction already rolls back the ledger; repricing must roll
      back with it.
- [ ] 4.4 Focused tests: resize into a more expensive shape charges the new rate; failed
      resize changes neither. `design.md` names a resize that succeeds at the ledger but
      fails to reprice as the most likely miss.

## 5. Funds verification

- [ ] 5.1 Choose between reading committed balance and consuming a buyer-supplied proof.
      Record the choice and its reasoning in `design.md` rather than leaving it implicit
      in the implementation; both satisfy the requirement and they differ in how they
      interact with the deferred standing-account work.
- [ ] 5.2 Implement the chosen shape at the domain layer, with no on-chain write for the
      verification itself.
- [ ] 5.3 Reject stale or replayed evidence of commitment.
- [ ] 5.4 Focused tests: sufficient commitment verifies; insufficient is refused; stale
      or reused evidence does not satisfy.

## 6. Validation

- [ ] 6.1 Run the `kit/site` ledger suites, settlement servicing suites, negotiation
      acceptance paths, and an e2e path proving a hold is charged and the remainder
      returned. Disclose any suite not run.
- [ ] 6.2 Confirm no non-exclusive operation became chargeable — feasibility
      verification reserves nothing and must remain free.
- [ ] 6.3 Run `openspec validate --all --strict` against the baseline current at
      implementation time.

## 7. Closeout

Per `openspec/README.md#plan-closeout-requirements`.

- [ ] 7.1 **Comment hygiene.** Run `make check-comment-hygiene`. Read
      `_place_capacity_hold`'s and `capped_hold_seconds`' docstrings directly; both
      describe TTL as the primary source of hold duration.
- [ ] 7.2 **Import placement.** Review imports this change adds or touches.
- [ ] 7.3 **Documentation compliance.** Confirm the derived-duration and charged-hold
      rules landed in the two specs, `ARCHITECTURE.md`'s capacity-reservation section
      states what a hold costs, and the priced-not-rate-limited reasoning stayed in
      `design.md`.
- [ ] 7.4 **Narrative compression.** Compress completed-task notes to final behavior,
      validation evidence, and promotion destinations.
- [ ] 7.5 **Roadmap currency.** Record the disposition. If the capacity-economics work
      has been recorded as a roadmap goal by then, update its current state; otherwise
      record explicitly that no goal's current state changes.
- [ ] 7.6 **Promotion.** Complete the design-promotion record below.
- [ ] 7.7 **Campaign index currency** (part seven, added when
      `openspec/README.md#plan-closeout-requirements` was extended from six parts to seven).
      Appended rather than folded into an existing task, per `AGENTS.md`'s rule to amend
      rather than replace implementation history. Update this change's row, and its
      campaign's dependency graph, in `openspec/changes/README.md` to match its state at
      completion, or record the disposition here if its status and campaign placement are
      both unchanged.

- [ ] 7.8 **Documentation citations.** Run
      `make check-doc-citations CHANGE=billable-capacity-reservations` and resolve every match.
      An unresolvable citation is a blocking defect under `AGENTS.md`'s
      cross-reference rule, and the target also rejects a citation whose
      target is a *tombstone*: a tombstoned file still exists on disk while
      its content is gone, so a plain existence test cannot fail on a
      rename-to-tombstone.
- [ ] 7.9 **End-to-end pipeline.** Confirm the end-to-end pipeline passes and
      record the evidence: the run, its result, and the scenarios that
      exercise this change's behaviour. Green unit and integration suites do
      not substitute -- this is the tier that catches a wire contract whose
      two sides disagree, a service that starts cleanly and cannot settle,
      and a configuration gap no in-process test can see. If the pipeline
      cannot run for a reason unrelated to this change, record that as an
      explicit blocker naming the cause and the change that owns it, and
      treat the validations it gates as unrun rather than passed.
## Design promotion record

| Accepted decision | Permanent location |
|---|---|
| A reservation carries a burn rate from the commercial rate structure; maximum duration is derived from committed funds, with configuration as a ceiling | `openspec/specs/site-capacity/spec.md` — "Reservations carry a burn rate and a funded bound" |
| Supersede reprices within the same atomic operation and never inherits the old rate | `openspec/specs/site-capacity/spec.md` — "Superseding a reservation reprices it" |
| Non-exclusive operations are never charged | `openspec/specs/site-capacity/spec.md` — "Non-exclusive capacity operations are not charged" |
| Held capacity is charged as a serviced obligation, generated from rate and funded duration, remainder returned, collection gated on actual exclusivity | `openspec/specs/settlement-servicing/spec.md` — "Held capacity is charged as a serviced obligation" |
| Committed funds are verifiable without a chain write, by read or by proof | `openspec/specs/settlement-servicing/spec.md` — "Committed funds are verifiable without a chain write" |
| What a hold costs and what bounds its duration | `docs/development/ARCHITECTURE.md`, capacity reservation |
| Why exclusivity is priced rather than rate-limited, and why identity-based caps were rejected | This change's `design.md` |
