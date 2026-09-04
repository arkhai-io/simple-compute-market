# Implementation Tasks

## 1. Verify the requested shape during negotiation

- [ ] 1.1 Re-verify `design.md`'s Context findings, particularly that
      `_place_capacity_hold` is still reached only on `decision.action == "accept"` and
      that `probe()` still shares `_find_candidate` with `reserve()`.
- [ ] 1.2 Call the existing non-consuming probe for the round's requested shape, before
      the seller commits to terms.
- [ ] 1.3 Order the check after any available admissibility evaluation, so a shape the
      seller would never sell does not cause a site round trip. Degrade correctly when
      `capacity-shape-envelope` is absent.
- [ ] 1.4 Choose and implement the explicit disposition for an unreachable site.
      Proceeding — leaving the hold at acceptance authoritative — preserves today's
      behavior; whichever is chosen, it must be deliberate and tested, not incidental.
- [ ] 1.5 Focused tests: unservable shape rejected before agreement; servable shape
      proceeds; nothing is reserved or held by the check; unreachable site takes the
      chosen disposition.

## 2. Distinguish the outcomes

- [ ] 2.1 Add an unservable outcome alongside the existing seller-declines outcome,
      keeping the two distinguishable to the counterparty.
- [ ] 2.2 Confirm the existing categorical guard's outcome is unchanged, so this change
      adds a case rather than reclassifying one.
- [ ] 2.3 Focused tests: each outcome reported distinctly; a shape failing both reports
      the seller's decline, since it never reaches the site.

## 3. Prove concurrency behavior

- [ ] 3.1 Test that two concurrent verifications of the same scarce capacity may both
      report servable, and that the reservation remains authoritative. This encodes the
      accepted race rather than leaving it to be discovered.
- [ ] 3.2 One e2e path proving an unservable shape fails during negotiation rather than
      at settlement.

## 4. Validation

- [ ] 4.1 Run the negotiation unit suites, the storefront capacity-client suites, and
      the VM e2e scenarios. Disclose any suite not run.
- [ ] 4.2 Run `openspec validate --all --strict` against the baseline current at
      implementation time.

## 5. Closeout

Per `openspec/README.md#plan-closeout-requirements`.

- [ ] 5.1 **Comment hygiene.** Run `make check-comment-hygiene`. Read the negotiation
      path's docstrings directly; several describe the site being consulted only at
      acceptance.
- [ ] 5.2 **Import placement.** Review imports this change adds or touches;
      `sync_negotiation.py` already uses function-level imports heavily, so check
      whether the existing reason applies to any added here.
- [ ] 5.3 **Documentation compliance.** Confirm the verification rule landed in
      `openspec/specs/negotiation-protocol/spec.md` and that `ARCHITECTURE.md` reflects
      when the authoritative site is consulted.
- [ ] 5.4 **Narrative compression.** Compress completed-task notes to final behavior,
      validation evidence, and promotion destinations.
- [ ] 5.5 **Roadmap currency.** Update Goal 2's gap mapping in
      `docs/development/ROADMAP.md`. Note that this change is a shared prerequisite and
      does not belong exclusively to Goal 2.
- [ ] 5.6 **Promotion.** Complete the design-promotion record below.
- [ ] 5.7 **Campaign index currency** (part seven, added when
      `openspec/README.md#plan-closeout-requirements` was extended from six parts to seven).
      Appended rather than folded into an existing task, per `AGENTS.md`'s rule to amend
      rather than replace implementation history. Update this change's row, and its
      campaign's dependency graph, in `openspec/changes/README.md` to match its state at
      completion, or record the disposition here if its status and campaign placement are
      both unchanged.

## Design promotion record

| Accepted decision | Permanent location |
|---|---|
| A requested shape is verified against the authoritative site before agreement, consuming nothing | `openspec/specs/negotiation-protocol/spec.md` — "Authoritative capacity verification before agreement" |
| Unservable and seller-declined are distinct outcomes | Same requirement |
| The verification is advisory; the race with concurrent buyers is accepted | Same requirement, concurrency scenario |
| An unreachable site takes an explicit disposition | Same requirement, final scenario |
| When the authoritative site is consulted during a deal's lifecycle | `docs/development/ARCHITECTURE.md`, "Discovery and negotiation" |
| Why probing was chosen over holding, and what holding would have required | This change's `design.md` |
