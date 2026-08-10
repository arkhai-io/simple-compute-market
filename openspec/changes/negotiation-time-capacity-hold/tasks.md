# Implementation Tasks

Both prerequisites must have landed. Landing this change first is the sequencing error
`design.md` names: it converts hold placement into uncompensated exclusion and raises
hold population before expiry and idempotency are ready for it.

## 1. Negotiation-scoped reservation identity

- [ ] 1.1 Re-verify `design.md`'s Context findings, particularly that hold placement is
      still guarded by `decision.action == "accept"` at three call sites and that
      `resize_reservation` still has no caller.
- [ ] 1.2 Record the negotiation's reservation identity on the negotiation thread so the
      supersede and release paths can find it.
- [ ] 1.3 Supply the pre-settlement idempotency key from
      `capacity-reservation-lifecycle-hardening`, so a retried proposal returns the
      existing reservation rather than admitting a second.

## 2. Move placement to first commitment

The behavioral boundary.

- [ ] 2.1 Define "proposes terms differing from the offering's own" precisely enough to
      be testable. A restated-terms counter-offer must not qualify — `design.md` records
      that treating it as genuine reopens inquiry-time holding through the back door.
- [ ] 2.2 Place the hold at that point instead of at terms acceptance.
- [ ] 2.3 Keep the acceptance path idempotent, so a negotiation reaching agreement
      without ever counter-offering still holds capacity before settlement.
- [ ] 2.4 Confirm inquiry and non-consuming feasibility verification hold nothing and
      require nothing. `design.md` names this as a property to defend rather than assume.
- [ ] 2.5 Focused tests: differing-terms proposal places a hold; restated-terms proposal
      does not; inquiry and verification hold nothing; acceptance without a counter-offer
      still holds before settlement.

## 3. Supersede on shape change

- [ ] 3.1 Supersede the negotiation's reservation when the requested shape changes,
      giving `resize_reservation` its first caller.
- [ ] 3.2 Respect that method's documented ordering constraint: resize before
      `schedule_resource()` runs for the affected reservation, never after.
- [ ] 3.3 Confirm exactly one live reservation per negotiation across a multi-round
      shape negotiation, rather than one per round.
- [ ] 3.4 Focused tests: shape change supersedes; ten rounds leave one live reservation;
      a failed supersede leaves the prior reservation held.

## 4. Release on terminal negotiation state

- [ ] 4.1 Release the reservation when a negotiation reaches a terminal state without
      agreement.
- [ ] 4.2 Cover the watchdog's abandonment path explicitly. It matters more than the
      explicit terminal paths, because a crashed counterparty is exactly the case that
      would otherwise hold capacity for its full bound.
- [ ] 4.3 Carry the existing reservation into settlement on success rather than
      reserving again.
- [ ] 4.4 Focused tests: failed negotiation releases; abandoned negotiation releases;
      successful negotiation commits the reservation it already held.

## 5. Validation

- [ ] 5.1 Run the negotiation unit suites, abandonment paths, storefront capacity-client
      suites, and an e2e path proving a second buyer cannot hold capacity another buyer
      is negotiating for. Disclose any suite not run.
- [ ] 5.2 Confirm hold population is bounded by live negotiations rather than by
      historical ones — the property both prerequisites were built to support.
- [ ] 5.3 Run `openspec validate --all --strict` against the baseline current at
      implementation time.

## 6. Closeout

Per `openspec/README.md#plan-closeout-requirements`.

- [ ] 6.1 **Comment hygiene.** Run `make check-comment-hygiene`. Read
      `_place_capacity_hold`'s docstring directly; it describes a hold placed at terms
      acceptance and explains at length why the shape held is the listing's own, which
      this change and its prerequisites together make false.
- [ ] 6.2 **Import placement.** Review imports this change adds or touches.
- [ ] 6.3 **Documentation compliance.** Confirm the placement and one-reservation rules
      landed in `openspec/specs/negotiation-protocol/spec.md`, that `ARCHITECTURE.md`
      states when capacity becomes held in a deal's lifecycle, and that the three
      rejected placement points stayed in `design.md`.
- [ ] 6.4 **Narrative compression.** Compress completed-task notes to final behavior,
      validation evidence, and promotion destinations.
- [ ] 6.5 **Roadmap currency.** Record the disposition. If the capacity-economics work
      has been recorded as a roadmap goal by then, update its current state; otherwise
      record explicitly that no goal's current state changes.
- [ ] 6.6 **Promotion.** Complete the design-promotion record below.

## Design promotion record

| Accepted decision | Permanent location |
|---|---|
| Capacity is held from the first differing-terms proposal; inquiry and verification hold nothing and require no funds | `openspec/specs/negotiation-protocol/spec.md` — "Capacity is held from first commitment, not from agreement" |
| A negotiation holds at most one reservation, superseded on shape change, released on terminal state including abandonment | `openspec/specs/negotiation-protocol/spec.md` — "One reservation spans a negotiation" |
| When capacity becomes held in a deal's lifecycle | `docs/development/ARCHITECTURE.md`, capacity reservation and negotiation |
| Why inquiry-time holding was rejected, and why the trigger must exclude restated terms | This change's `design.md` |
