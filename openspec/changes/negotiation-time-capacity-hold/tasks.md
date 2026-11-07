# Implementation Tasks

Both prerequisites must have landed. Landing this change first is the sequencing error
`design.md` names: it converts hold placement into uncompensated exclusion and raises
hold population before expiry and idempotency are ready for it.

## 1. Negotiation-scoped reservation identity

- [ ] 1.1 Re-verify `design.md`'s Context, particularly that hold placement is still
      the acceptance-only `place_hold` hook, that the hooks still have no release
      counterpart, that the watchdog is still `kit/storefront`'s, and that
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
- [ ] 2.2 Place the hold at that point instead of at terms acceptance: the kit calls
      `place_hold` when it evaluates a differing-terms proposal, with the posted hold
      rate as the burn rate; the VM implementation is `_place_capacity_hold` over the
      proposal's shape rather than the listing record.
- [ ] 2.3 Keep the acceptance path idempotent, so a negotiation reaching agreement
      without ever counter-offering still holds capacity before settlement.
- [ ] 2.4 Confirm inquiry and non-consuming feasibility verification hold nothing and
      require nothing. `design.md` names this as a property to defend rather than assume.
- [ ] 2.5 Focused tests: differing-terms proposal places a hold; restated-terms proposal
      does not; inquiry and verification hold nothing; acceptance without a counter-offer
      still holds before settlement.

## 3. Supersede on shape change

Depends on `negotiation-driven-capacity-resize`, which lets a round carry a revised
shape.

- [ ] 3.1 Supersede the negotiation's reservation when the requested shape changes,
      giving `resize_reservation` its first caller.
- [ ] 3.2 Respect that method's documented ordering constraint: resize before
      `schedule_resource()` runs for the affected reservation, never after.
- [ ] 3.2a Make `resize_reservation`'s release step honour `site-capacity`'s "Only a
      forced release MAY free an `unmanaged` reservation": it frees the old
      reservation with the release guard's permission alone, so an `unmanaged`
      reservation can be superseded today. Refuse to resize one, and add a focused
      test that a resize of an `unmanaged` reservation leaves it held.
- [ ] 3.3 Confirm exactly one live reservation per negotiation across a multi-round
      shape negotiation, rather than one per round.
- [ ] 3.4 Focused tests: shape change supersedes; ten rounds leave one live reservation;
      a failed supersede leaves the prior reservation held.

## 4. Release on terminal negotiation state

- [ ] 4.1 Add a release hook to `NegotiationDomainHooks`, called by the kit on every
      terminal transition without agreement; release the reservation there. A domain
      that holds nothing implements it as a no-op.
- [ ] 4.2 Cover the watchdog's abandonment path explicitly: `kit/storefront`'s
      negotiation watchdog calls the release hook when it marks a thread abandoned.
      It matters more than the explicit terminal paths, because a crashed counterparty
      is exactly the case that would otherwise hold capacity for its full bound.
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
- [ ] 5.4 **Comment hygiene and import placement, before the pre-closeout review.** Run
      `make check-comment-hygiene` and read the comments this change added for any that
      narrate the review or migration that introduced them; move each import the change
      added to module level unless a verified circular import or a recorded lazy-load
      reason keeps it local. Closeout only confirms both. Read `_place_capacity_hold`'s
      docstring directly; it describes a hold placed at terms acceptance and explains at
      length why the shape held is the listing's own, which this change and its
      prerequisites together make false.

## 6. Closeout

Per `openspec/README.md#plan-closeout-requirements`.

- [ ] 6.1 **Comment hygiene — confirm.** Run `make check-comment-hygiene`, and read
      the comments this change added for any that narrate the review or migration that
      introduced them, including `_place_capacity_hold`'s docstring (5.4). Do not edit
      code here: anything to rewrite returns the change to implementation.
- [ ] 6.2 **Import placement — confirm.** Check the imports this change added for any
      still local without a recorded reason. One that should move returns the change to
      implementation.
- [ ] 6.3 **Documentation compliance.** Re-check this change's accepted decisions
      against `openspec/README.md`'s placement rules, and the permanent documents
      against the code they describe: `ARCHITECTURE.md` states when capacity becomes
      held in a deal's lifecycle, and the three rejected placement points stay in
      `design.md`.
- [ ] 6.4 **Narrative compression.** Compress completed-task notes to final behavior,
      material validation evidence, unresolved or deferred work, and
      permanent-documentation destinations, moving durable rationale into `design.md`
      first.
- [ ] 6.5 **Roadmap currency.** Update the affected goal's current state and gap
      mapping in `docs/development/ROADMAP.md`, or record that no goal is affected. If
      the capacity-economics work has been recorded as a roadmap goal by then, update
      its current state; otherwise record explicitly that no goal's current state
      changes.
- [ ] 6.6 **Campaign index currency.** Update this change's row, and its campaign's
      dependency graph, in `openspec/changes/README.md`, or record that both are
      unchanged. Other rows' `Depends on` are left alone: archive cleanup releases
      dependents after the closeout gate.
- [ ] 6.7 **Packaging.** Run `make check-packaging` and resolve every failure it
      reports (a failure needing a code or lock change returns the change to
      implementation).
- [ ] 6.8 **End-to-end pipeline.** Record the passing run the latest validation names,
      its result, and the scenarios that exercise this change, or an explicit blocker
      naming its cause and the change that owns it, with the validations it gates
      treated as unrun.
- [ ] 6.9 **Promotion.** Write the permanent documents this change owes —
      `docs/development/ARCHITECTURE.md`, capacity reservation and negotiation (when
      capacity becomes held in a deal's lifecycle) — and complete the design-promotion
      record below. A `spec.md` the deltas cover — here
      `openspec/specs/negotiation-protocol/spec.md` — is written by the archive in 6.11,
      not by hand; the record names it all the same.
- [ ] 6.10 **Documentation citations.** After promotion, run
      `make check-doc-citations CHANGE=negotiation-time-capacity-hold` and resolve every
      match, then `openspec validate negotiation-time-capacity-hold --strict`.
- [ ] 6.11 **Archival.** Last, once every other part is checked: `openspec archive
      negotiation-time-capacity-hold -y` merges the deltas into `openspec/specs/` and
      moves the change under `openspec/changes/archive/`; point the index row at the
      archived directory, and run `openspec validate --specs --strict`.

## Design promotion record

| Accepted decision | Permanent location |
|---|---|
| Capacity is held from the first differing-terms proposal; inquiry and verification hold nothing and require no funds | `openspec/specs/negotiation-protocol/spec.md` — "Capacity is held from first commitment, not from agreement" |
| A negotiation holds at most one reservation, superseded on shape change, released on terminal state including abandonment | `openspec/specs/negotiation-protocol/spec.md` — "One reservation spans a negotiation" |
| When capacity becomes held in a deal's lifecycle | `docs/development/ARCHITECTURE.md`, capacity reservation and negotiation |
| Why inquiry-time holding was rejected, and why the trigger must exclude restated terms | This change's `design.md` |
