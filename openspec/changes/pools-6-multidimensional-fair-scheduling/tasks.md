# POOLS-6 tasks

This change is split into two implementation passes, decided in design
review (2026-07-20). Pass 1 resolves only the questions blocking pools-7's
admission-time correctness gap and keeps deterministic round-robin as the
selection policy. Pass 2 picks and implements an actual fairness/placement
policy. See `design.md` for the full resolution record.

## Pass 1 — Multidimensional capacity model (unblocks POOLS-7)

Design resolution (2026-07-20, resolved):

- [x] Dimension representation: generic `dict[str, Decimal]` on requirements,
      candidates, `SiteResource.capacity`, and `SiteAllocation.dimensions`
      (not fixed named fields) — multi-domain-ready, matches this file's
      original candidate-model sketch.
- [x] Resource-bundle semantics: a `SiteResource` row already corresponds
      1:1 to one physical host for the VM domain (existing `vm_host`
      attribute) — no new cross-row bundling machinery needed for pass 1.
- [x] Admission-time fit-check correctness: full per-dimension held/available
      accounting, extending `CapacityLedgerService`'s existing lease-window
      held-units machinery rather than a declared-capacity-only gate.
      Storefront-side pre-checks remain projections that can be invalidated
      at actual reserve time — only the site-authority ledger's accounting
      needs to be exact.
- [x] `SiteResource.total_units` becomes a service-maintained mirror of
      `capacity["gpu_count"]`, not a full cutover — same documented
      intermediate-state-limitation pattern POOLS-2 used for its
      process-local assignment cursors.
- [x] `CapacityEvent` payload is extended with per-dimension deltas now,
      not deferred to pass 2.
- [x] VM shape (vcpu/ram/disk) is a **fixed, seller-declared listing
      attribute** for pass 1, not a per-order negotiated dimension.
      Buyer-negotiated VM sizing is real future work but out of scope here
      — it touches the negotiation-protocol boundary and needs a separate
      design discussion before it's picked up (owner's team review
      pending). Do not quietly widen pass 1 to cover it.
- [x] `resource_capacity_validator.py` stays as-is for pass 1. It is a
      storefront-local data-integrity check on operator CSV input, a
      different concern from the admission-time fit gate, and it sits on
      the storefront's local `resources` table that `pools-8`'s
      `CapacityProjection` is already slated to retire. Converge dimension
      vocabulary (`vcpu_count`/`ram_gb`/`disk_gb`) so it can be deleted
      outright when `pools-8` lands, instead of migrated now.
- [x] Package boundary: pass 1 changes stay inside current package
      boundaries (`compute_provisioning`, `kit/site`). The planned move of
      `PhysicalSettlementScheduler`/`DeterministicRoundRobinPolicy` (and the
      shared `resource_satisfies_requirement` predicate) into a new
      `kit/physical-settlement` package is pools-7's decision to make and
      execute, not pools-6's to preempt.

Implementation:

- [x] Add `dimensions`/`available` maps to `SettlementRequirement`/
      `SettlementCandidate` in `compute_provisioning/physical_settlement.py`.
- [x] Add `SiteResource.capacity` and `SiteAllocation.dimensions` columns
      (`kit/site/src/market_site/db.py`) plus additive migrations in
      `domains/vms/provisioning/service/src/db/migrations.py` (also added
      `CapacityEvent.dimensions` for the per-dimension delta feed).
- [x] Generalize `CapacityLedgerService` held/available accounting,
      matching, `register_resource`, `probe`/`reserve`, and payload
      builders to be dimension-aware; keep legacy single-quantity claims
      (`units`/`gpu_count`) working unchanged via internal translation.
- [x] Update `PhysicalSettlementScheduler._requirement`/
      `_eligible_candidates` to build/evaluate `dimensions`.
- [x] ~~Add fixed `vcpu_count`/`ram_gb`/`disk_gb` fields to
      `ComputeResource`~~ — not needed; those fields already existed
      (see `design.md`'s "VM domain wiring" correction). The actual gap
      was `compute_capacity_claim_from_order` never forwarding them.
- [x] Wire `vm_job_spec_service.py`'s claim building to include a
      `dimensions` map (`gpu_count`, `vcpu_count`, `ram_gb`, `disk_gb`)
      from the listing's fixed shape, alongside the existing exact-match
      attributes.
- [x] Wire `capacity_client.py`'s `register_resource` call to populate
      `capacity` from the storefront's local row attributes (same
      vocabulary as `resource_capacity_validator.py`). Plumbed `capacity`
      through the HTTP boundary (`http_models.py`, `router.py`,
      `RemoteCapacityClient`).
- [x] Update/add tests: `kit/site` ledger (10 new + 30 existing passing),
      scheduler (3 new + 9 existing passing), `capacity_client`/
      `sync_site_resources` (1 new, existing passing),
      `vm_job_spec_service` claim-building (2 new, existing passing).
- [x] Promote the shipped pass-1 behavior from this change's spec delta
      into baseline `site-capacity`/`physical-provisioning` specs; record
      the deferred negotiated-VM-sizing question and the pools-8
      validator-deletion dependency in the relevant proposals.

## Pass 2 — Fairness / placement policy (not started)

Design resolution — still open:

- [ ] Confirm domain boundaries and whether VM and pod compute share a
      provisioning domain.
- [ ] Choose the fairness subject and fairness scope (raised in review
      2026-07-20: buyer/agreement was the leading candidate but not
      confirmed — pin this at the start of pass 2).
- [ ] Choose pool weighting and the precedence of fit, fairness,
      utilization, spreading, cost, and topology.
- [ ] Specify indivisible resources, quotas, priorities, preemption, and
      starvation behavior.
- [ ] Specify historical accounting, persistence, decay, restart recovery,
      and exact-resource accounting.
- [ ] Specify provider-failure and explicit reassignment behavior.

Evaluation:

- [ ] Evaluate maintained external scheduler libraries against the policy
      protocol and operational constraints.
- [ ] Compare lowest projected dominant utilization, capacity-weighted pool
      fairness, and consumer-aware DRF through simulations.
- [ ] Define policy explanation, metrics, and debugging surfaces.

Implementation after design approval:

- [ ] Implement a second policy beside round-robin to prove interface
      generality.
- [ ] Persist fairness state transactionally with capacity claims and
      assignments.
- [ ] Add simulation, concurrency, restart, starvation, and
      adversarial-shape tests.
- [ ] Promote approved requirements into baseline OpenSpec and update
      architecture pointers only after behavior becomes current state.
