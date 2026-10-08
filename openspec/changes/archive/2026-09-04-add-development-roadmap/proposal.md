## Why

The repository has no durable home for directional context. `openspec/changes/README.md`
groups active changes into delivery campaigns but deliberately carries only
readiness and acceptance boundaries; `docs/development/ARCHITECTURE.md` describes
the current system and explicitly disclaims being a backlog. The multi-change goals
actually driving the work — consolidating physical-resource authority in the
provisioning service, negotiating full compute capability shapes rather than GPU
count alone, composing several compute-family market domains into one storefront,
and reorganizing the kit layer ahead of new market domains — exist only as
scattered dependency notes inside individual changes.

That scattering has a concrete cost the codebase already pays. `pools-9-retire-local-physical-authority`'s
`design.md` re-states findings from `pools-8-capacity-projection-and-listing-hints`
specifically because "`pools-8` is expected to be archived (and its documents
possibly eventually removed) once its own scope is complete." Goal-level context
that outlives a campaign has nowhere to live except inside changes designed to be
disposed of, so it gets copied, drifts, or is lost. A contributor picking up one
change cannot see which larger goal it serves, and a reader outside the contributor
loop cannot see progress at all.

`openspec/specs/planning-governance/spec.md`'s "Canonical planning homes"
requirement forbids ordinary documentation from maintaining a competing normative
backlog. That prohibition is correct and stays. It is also why three earlier
attempts at durable planning documentation — `docs/development/TODO.md`,
`design-remaining-work.md`, and `provisioning-migration-plan.md` — were reduced to
non-normative redirect stubs. Those stubs have since decayed: `design-remaining-work.md`
points at `genericize-storefront-client-wire` and `prove-multi-domain-capacity`, and
`provisioning-migration-plan.md` points at `migrate-compute-provisioning`, none of
which exist in `openspec/changes/` or `openspec/changes/archive/`. They are
maintenance liabilities that answer a question this change re-answers properly.

## What Changes

- Add `docs/development/ROADMAP.md`: one repository-wide directional document
  stating each current goal, the value it delivers, an evidence-based present-tense
  description of what is true today, and a table mapping each identified gap to the
  OpenSpec change that owns it.
- Constrain that document by requirement rather than convention: it carries goals,
  value, current state, and gap-to-change links, and it carries no implementation
  tasks, no acceptance criteria, no readiness status, and no delivery sequencing.
  Those remain owned by the changes themselves and by `openspec/changes/README.md`.
- Require roadmap currency at change closeout. A change whose completion alters what
  is true about a roadmap goal updates that goal's current-state description as part
  of its own closeout, before implementation is considered complete. Currency is tied
  to change completion, not archival, so a completed-but-unarchived change is
  reflected immediately.
- **BREAKING (contributor workflow):** extend `openspec/README.md#plan-closeout-requirements`
  from five parts to six by adding roadmap currency. Two in-flight changes carry
  written closeout sections today (`pools-8-capacity-projection-and-listing-hints`,
  `fix-vm-fulfillment-capacity-boundary`) and need theirs amended; every other change
  picks up the sixth part when it plans its own closeout.
- Retire the three decayed redirect stubs (`docs/development/TODO.md`,
  `design-remaining-work.md`, `provisioning-migration-plan.md`) as tombstones, and
  repoint the two inbound references that name them:
  `openspec/specs/planning-governance/spec.md`'s Evidence list and
  `provisioning/compute/README.md`'s migration-map pointer.
- Link the roadmap from `docs/development/ARCHITECTURE.md`'s document map and from
  `openspec/README.md`'s documentation-placement table so each of the three
  cross-cutting documents names the other two's jurisdiction.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `planning-governance`: permit exactly one repository-wide directional roadmap under
  named constraints that distinguish it from a competing backlog; require roadmap
  currency as part of change closeout; narrow "Canonical planning homes" so the
  distinction between directional context and a normative backlog is expressed as a
  requirement rather than left to reviewer judgment.

## Non-Goals

- Do not create the OpenSpec changes that per-goal gap analysis identifies. Each
  identified gap becomes its own change with its own acceptance boundary; this change
  owns the roadmap and its maintenance rule, not the work the roadmap points at.
- Do not restate change status, readiness, blocking relationships, delivery
  sequencing, or acceptance boundaries in the roadmap. `openspec/changes/README.md`
  keeps all of them.
- Do not create a general exemption for planning content in `docs/`. The permitted
  document is singular, named, and constrained; anything else in `docs/` remains
  bound by the existing prohibition.
- Do not retroactively amend the closeout sections of archived changes.
- Do not delete or alter the `migrate-planning-to-openspec` archive ledger, which
  independently satisfies the "Complete migration provenance" requirement once the
  three stubs are gone.
- Do not resolve the goal-level design questions the roadmap will record as open —
  notably whether multi-domain storefront composition multiplexes several
  `MarketDomainContract`s in one process or federates single-domain processes behind
  a shared publication surface. The roadmap records the question; a later change
  answers it.

## Impact

- **Documentation:** new `docs/development/ROADMAP.md`; three stubs tombstoned;
  `docs/development/ARCHITECTURE.md` document map gains a roadmap row;
  `openspec/README.md` gains a documentation-placement row and a sixth closeout part;
  `provisioning/compute/README.md` migration pointer repointed at
  `openspec/specs/physical-provisioning/spec.md`.
- **Specifications:** `openspec/specs/planning-governance/spec.md` gains two
  requirements, modifies one, and has its Evidence list updated. The Evidence edit is
  a direct spec edit — OpenSpec's delta synchronizer covers requirements only.
- **Contributor workflow:** every future `tasks.md` closeout gains a sixth part; two
  in-flight changes need theirs amended.
- **Not affected:** no production code, wire contract, database schema, deployment
  topology, or packaging change. `make check-comment-hygiene` scans `*.py`, `*.yml`,
  and `*.yaml` only, so the roadmap's links into `openspec/changes/` do not trip it,
  and its own link discipline (see `design.md`) keeps those links from decaying the
  way the retired stubs' did.

## Permanent documentation impact

- [x] `docs/development/ARCHITECTURE.md` — document-map entry pointing at the roadmap
      and naming its jurisdiction, so the three cross-cutting documents are mutually
      discoverable.
- [x] Existing subsystem specification — `openspec/specs/planning-governance/spec.md`.
- [ ] New subsystem specification — none; this is a governance and documentation-strategy
      change within an existing capability.
- [ ] No permanent documentation change — not applicable.

### Knowledge to promote

- The permitted-roadmap constraints (no tasks, no acceptance criteria, no readiness
  status, singular and named) and the closeout-currency rule —
  `openspec/specs/planning-governance/spec.md`, as the two requirements this change
  adds.
- Why directional context belongs in `docs/development/` rather than
  `openspec/changes/` (change directories are designed to be archived and deleted;
  goal context must outlive them) — `openspec/specs/planning-governance/spec.md`'s
  modified "Canonical planning homes" requirement, with the fuller reasoning in this
  change's `design.md` and the resulting division of labor stated in the roadmap's own
  preamble.

## Dependencies and Related Changes

- No blocking dependency on any active change.
- `pools-8-capacity-projection-and-listing-hints` and `fix-vm-fulfillment-capacity-boundary`
  are the two changes whose existing closeout sections this change amends. Neither
  needs to complete first; the amendment is additive to their task lists.
- Every goal the roadmap records maps to changes across the POOLS, Market Platform
  compute, and negotiation campaigns. This change does not modify any of them. Where
  a goal contradicts a recorded non-goal in an existing change — notably the
  one-market-domain-per-storefront-process position in
  `market-platform-bare-metal-10-storefront-composition` and
  `market-platform-compute-40-multi-domain-proof` — reconciling that change's own
  documents is the work of the goal's own later change, not this one. The roadmap
  records the contradiction so it is not discovered by surprise.
