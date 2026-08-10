## Why

A capacity hold is placed only when a negotiation reaches terms acceptance
(`decision.action == "accept"`). Until that moment nothing is reserved, so two buyers can
negotiate the same scarce capacity to completion and one discovers at settlement that
there is nothing to give. The failure lands after both parties have committed, which is
the worst place for it.

`negotiation-capacity-feasibility-probe` moves the *detection* earlier without reserving
anything, which is the right first step and deliberately avoids the exclusivity problem.
It does not close the race: a probe answers for an instant and guarantees nothing.

Closing the race means holding capacity while a buyer is still negotiating for it — and
holding capacity is exclusion, which is only acceptable if it is compensated.
`billable-capacity-reservations` makes it compensated. This change is what that enables:
the hold moves from terms acceptance to the buyer's first genuine counter-offer, the
point at which the buyer has demonstrated intent by spending a signed round-trip and is
willing to fund the hold.

Placing it at the buyer's first inquiry was considered and rejected: it would require a
funded commitment before a buyer could ask anything, turning browsing into an on-chain
act.

## What Changes

- Place the capacity hold when a counterparty first makes a genuine counter-offer,
  rather than at terms acceptance.
- Keep inquiry free and unfunded. A buyer discovering a listing, asking about it, and
  verifying feasibility holds nothing, funds nothing, and is charged nothing.
- Carry one reservation through the remainder of a negotiation, superseding it when the
  requested shape changes rather than accumulating a reservation per round.
- Commit the existing hold at settlement, unchanged, so the two-phase reserve the
  current hold already provides is preserved with an earlier first phase.
- Release the hold promptly when a negotiation ends without agreement, rather than
  leaving it to lapse on its funded bound.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `negotiation-protocol`: capacity is held from the counterparty's first genuine
  counter-offer rather than from terms acceptance, one reservation spans a negotiation,
  and inquiry remains unfunded and unheld.

## Non-Goals

- Do not hold capacity at inquiry. Explicitly rejected; inquiry stays free.
- Do not make holds billable — `billable-capacity-reservations` owns that and is a
  prerequisite. Moving holds earlier without billing them is the uncompensated-exclusion
  problem.
- Do not add the round payload that carries a shape change —
  `negotiation-driven-capacity-resize` owns it. This change supersedes the reservation
  when the requested shape changes, by whatever mechanism carries it.
- Do not change what settlement does with a held reservation; commit is unchanged.
- Do not remove the non-consuming feasibility verification. It stays, and remains the
  only capacity interaction before a counter-offer.
- Do not change admission, matching, or scheduling.

## Impact

- Affected code: `domains/vms/storefront/src/market_storefront/utils/sync_negotiation.py`
  (hold placement moves from the three acceptance call sites to the first counter-offer,
  and gains a release path on negotiation end), and the negotiation thread's record of
  its reservation.
- Affected behavior: hold population grows from accepted-but-unsettled deals to
  negotiations past their first counter-offer. This is the reason both prerequisites
  exist.
- Affected tests: negotiation unit suites, abandonment paths, and an e2e path proving a
  second buyer cannot reserve capacity another buyer is negotiating for.
- Not affected: settlement's commit, fulfillment, admission semantics.

## Permanent documentation impact

- [x] `docs/development/ARCHITECTURE.md` — the capacity-reservation and negotiation
      sections, on when in a deal's lifecycle capacity becomes held.
- [x] Existing subsystem specification — `openspec/specs/negotiation-protocol/spec.md`.
- [ ] New subsystem specification — none.

### Knowledge to promote

- Capacity is held from the first genuine counter-offer; inquiry is unheld and unfunded
  — `openspec/specs/negotiation-protocol/spec.md`.
- One reservation spans a negotiation and is superseded rather than accumulated — same
  requirement.

## Dependencies and Related Changes

- **Depends on `billable-capacity-reservations`.** Without it this change is the
  uncompensated-exclusion problem, not a fix for it.
- **Depends on `capacity-reservation-lifecycle-hardening`.** It supplies the
  pre-settlement idempotency key this change's holds need (no escrow exists at
  counter-offer time), and the bounded expiry that a larger hold population requires.
- Complements `negotiation-capacity-feasibility-probe`, which keeps inquiry answerable
  without a hold. The two together are the full "fail early" story: verify at inquiry,
  hold at commitment.
- Interacts with `negotiation-driven-capacity-resize`, whose shape-change payload is
  what triggers a supersede here. Neither blocks the other; if that change has not
  landed, the requested shape cannot change and no supersede occurs.
