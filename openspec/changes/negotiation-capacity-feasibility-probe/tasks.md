# Implementation Tasks

## 1. Verify the requested shape during negotiation

- [ ] 1.1 Re-verify `design.md`'s Context, particularly that
      `_place_capacity_hold` is still reached only through the kit's `place_hold`
      hook on acceptance and that `probe()` still shares `_find_candidate` with
      `reserve()`.
- [ ] 1.2 Call the existing non-consuming probe for the round's requested shape, before
      the seller commits to terms, from inside the VM `evaluate_round` composition in
      `negotiation_runtime.py`. **Decide and record** in `design.md` whether the probe
      is a distinct `NegotiationDomainHooks` member (so the kit reports "not checked"
      for a domain that composes none) or a step inside the domain's evaluation.
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
- [ ] 4.3 **Comment hygiene and import placement, before the pre-closeout review.** Run
      `make check-comment-hygiene` and read the comments this change added for any that
      narrate the review or migration that introduced them; move each import the change
      added to module level unless a verified circular import or a recorded lazy-load
      reason keeps it local. Closeout only confirms both. Read the negotiation path's
      docstrings directly, since several describe the site being consulted only at
      acceptance; `negotiation_runtime.py` already uses function-level imports heavily,
      so check whether the existing reason applies to any added here.

## 5. Closeout

Per `openspec/README.md#plan-closeout-requirements`.

- [ ] 5.1 **Comment hygiene — confirm.** Run `make check-comment-hygiene`, and read
      the comments this change added for any that narrate the review or migration that
      introduced them. Do not edit code here: anything to rewrite returns the change to
      implementation.
- [ ] 5.2 **Import placement — confirm.** Check the imports this change added for any
      still local without a recorded reason. One that should move returns the change to
      implementation.
- [ ] 5.3 **Documentation compliance.** Re-check this change's accepted decisions
      against `openspec/README.md`'s placement rules, and the permanent documents
      against the code they describe, including that `ARCHITECTURE.md` reflects when
      the authoritative site is consulted.
- [ ] 5.4 **Narrative compression.** Compress completed-task notes to final behavior,
      material validation evidence, unresolved or deferred work, and
      permanent-documentation destinations, moving durable rationale into `design.md`
      first.
- [ ] 5.5 **Roadmap currency.** Update the affected goal's current state and gap
      mapping in `docs/development/ROADMAP.md`, or record that no goal is affected.
      Expected: Goal 2's gap mapping, noting that this change is a shared prerequisite
      and does not belong exclusively to Goal 2.
- [ ] 5.6 **Campaign index currency.** Update this change's row, and its campaign's
      dependency graph, in `openspec/changes/README.md`, or record that both are
      unchanged. Other rows' `Depends on` are left alone: archive cleanup releases
      dependents after the closeout gate.
- [ ] 5.7 **Packaging.** Run `make check-packaging` and resolve every failure it
      reports (a failure needing a code or lock change returns the change to
      implementation).
- [ ] 5.8 **End-to-end pipeline.** Record the passing run the latest validation names,
      its result, and the scenarios that exercise this change, or an explicit blocker
      naming its cause and the change that owns it, with the validations it gates
      treated as unrun.
- [ ] 5.9 **Promotion.** Write the permanent documents this change owes —
      `docs/development/ARCHITECTURE.md`, "Discovery and negotiation" (when the
      authoritative site is consulted during a deal's lifecycle) — and complete the
      design-promotion record below. The `negotiation-protocol` `spec.md`, which the
      deltas cover, is written by the archive in 5.11, not by hand; the record names it
      all the same.
- [ ] 5.10 **Documentation citations.** After promotion, run
      `make check-doc-citations CHANGE=negotiation-capacity-feasibility-probe` and resolve every
      match, then `openspec validate negotiation-capacity-feasibility-probe --strict`.
- [ ] 5.11 **Archival.** Last, once every other part is checked: `openspec archive
      negotiation-capacity-feasibility-probe -y` merges the deltas into `openspec/specs/` and
      moves the change under `openspec/changes/archive/`; point the index row at the
      archived directory, and run `openspec validate --specs --strict`.

## Design promotion record

| Accepted decision | Permanent location |
|---|---|
| A requested shape is verified against the authoritative site before agreement, consuming nothing | `openspec/specs/negotiation-protocol/spec.md` — "Authoritative capacity verification before agreement" |
| Unservable and seller-declined are distinct outcomes | Same requirement |
| The verification is advisory; the race with concurrent buyers is accepted | Same requirement, concurrency scenario |
| An unreachable site takes an explicit disposition | Same requirement, final scenario |
| When the authoritative site is consulted during a deal's lifecycle | `docs/development/ARCHITECTURE.md`, "Discovery and negotiation" |
| Why probing was chosen over holding, and what holding would have required | This change's `design.md` |
