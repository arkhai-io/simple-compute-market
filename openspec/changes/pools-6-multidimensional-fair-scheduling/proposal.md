# POOLS-6: Multidimensional Fair Scheduling Policies

## Context

POOLS-2 deliberately chooses a deterministic round-robin MVP. That policy is easy to explain and proves the scheduler/policy boundary, but it treats eligible pools and resources as equal line items. It does not account for heterogeneous reservation shapes, unequal pool capacity, consumer shares, utilization, topology, priority, or historical allocations.

The earlier POOLS-2 draft used a maximum aggregate utilization by resource type and described it as DRF. That was misleading. Classical Dominant Resource Fairness allocates multiple dimensions among competing consumers and tracks each consumer's dominant share. Aggregating unrelated capacity rows across different physical resources neither proves that one concrete resource can satisfy a reservation nor establishes consumer fairness.

POOLS-6 preserves the problem analysis and design questions needed to select a richer policy later without expanding POOLS-2.

## Why

Future domains may schedule requests with very different shapes: CPU and memory for VMs or pods, GPUs and accelerator memory for inference, indivisible bare-metal nodes, throughput and storage for object services, or provider-specific capabilities. Equal round-robin may be unfair to larger pools, ignore stranded capacity, and produce poor utilization.

A richer scheduler must still preserve the durable properties established by POOLS-2: idempotent Capacity Settlement Assignments, deterministic tie-breaking, concrete candidate locality, atomic capacity claims, draining pool semantics, explicit-resource eligibility, and executor-neutral contracts.

## Goals

- Define multidimensional reservation and candidate capacity vectors.
- Evaluate maintained external scheduler libraries against the existing policy protocol.
- Define one or more fair or utilization-aware policies without changing caller contracts.
- Distinguish pool balancing, concrete placement, and fairness among consumers.
- Make policy decisions explainable and observable.
- Preserve deterministic behavior under equal scores.
- Prove policy generality by implementing a second policy beside round-robin.
- Specify persistence, concurrency, simulation, and adversarial testing requirements.

## Non-goals

- Selecting a final fairness subject or algorithm in this placeholder change.
- Replacing round-robin before a policy is specified and tested.
- Moving provider-specific health, credentials, or execution checks into generic policy code.
- Treating abstract aggregate capacity as proof that one concrete resource can fit a request.
- Changing Capacity Settlement Assignment or physical-settlement caller contracts solely to accommodate one algorithm.
- Making VM shape (vcpu/ram/disk) a buyer-negotiated, per-order dimension. Pass 1 treats it as a fixed, seller-declared listing attribute; negotiated sizing is deferred future work requiring its own design review of the negotiation-protocol boundary.

## Concrete, currently-unenforced gap (found during POOLS-7 design review, 2026-07-17)

While designing `pools-7-storefront-fulfillment-cutover`'s reservation/
scheduling retrofit, we confirmed this change's abstract problem
statement has a concrete, currently-live instance, not just a future
risk: **`Host` (`domains/vms/provisioning/service/src/db/models.py`) has
no memory, disk, or vCPU capacity field — only `gpu_count`.** Reservation
admission (`kit/site/ledger.py`) can therefore correctly bin-pack on GPU
count against real hosts, but nothing in the capacity layer verifies a
negotiated shape's memory/disk/vCPU actually fits any physical host
before a Capacity Reservation is admitted. `VmFulfillmentRequirements`
(`pools-3`) carries these fields, but only at fulfillment time — downstream
of the point where admission has already committed to a reservation.

Net effect: **a Capacity Reservation can be admitted today for a shape no
physical machine can serve**, with the mismatch only surfacing later, at
fulfillment or scheduling time, as an unexplained failure rather than a
clean admission-time rejection. `pools-7` treats resolving this as a
prerequisite it consumes from this change, not something it re-derives
piecemeal (e.g. adding an ad hoc memory column to `Host` without going
through the dimension-normalization questions below) — see `pools-7`'s
`design.md`, "Dependency on POOLS-6."

This is offered as a concrete, scoped starting point for design work on
this change — unlike the rest of this document, which is deliberately
abstract and names no selected direction. It does not itself answer the
"Non-Work / Deferred Decisions" questions below (what dimensions are
first-class, how units normalize, whether pools are weighted, etc.); it
just establishes that at minimum, VM memory/disk/vCPU must become
first-class, admission-time-checked dimensions before `pools-7`'s
reservation-admission path can be considered correct.

**Correction (implementation, 2026-07-20):** the framing above is
accurate for `Host` (the provisioning service's own inventory table,
used for Ansible dispatch) but overstates the gap on the listing side.
`ComputeResource` (`domains/vms/listings/models.py`) already has
`vcpu_count`/`ram_gb`/`disk_gb` fields — a per-slice, seller-declared
shape, populated the same way `gpu_model`/`gpu_count` are. The actual gap
was narrower: `compute_capacity_claim_from_order`
(`vm_job_spec_service.py`) never forwarded those already-existing fields
past claim-building, so nothing downstream ever saw them. No schema
change to `ComputeResource` was needed; the fix was in claim-building and
the ledger's admission check. See `design.md`'s "Pass 1 design resolution"
section for the corrected account.

## Two-pass implementation split (decided in design review, 2026-07-20)

This change is split into two passes so the concrete admission-correctness
gap doesn't wait on the much larger fairness-policy question:

- **Pass 1** — give the capacity model a real multidimensional
  representation and make reservation admission check it, so a reservation
  can never be admitted for a shape no physical host could serve. Selection
  among fitting candidates stays deterministic round-robin (POOLS-2)
  unchanged. This closes the "Concrete, currently-unenforced gap" section
  above and is what `pools-7` is blocked on.
- **Pass 2** — pick and implement an actual fairness/placement policy
  (lowest projected dominant utilization, consumer-aware DRF, or another
  candidate direction below) as a second `SettlementSchedulingPolicy`,
  proving the protocol's generality.

Pass 1's design questions are resolved below. Pass 2's are not — see
`design.md` and the "Non-Work / Deferred Decisions" section, which now
only tracks pass-2 questions.

## Pass 1 design resolution (2026-07-20)

- **Dimension representation:** a generic `dict[str, Decimal]` map (e.g.
  `{"gpu_count": 1, "vcpu": 4, "memory_mb": 16384, "disk_gb": 200}`) on
  requirements, candidates, `SiteResource.capacity`, and
  `SiteAllocation.dimensions` — not fixed named fields. Multi-domain-ready,
  matches `design.md`'s original candidate-model sketch.
- **Resource-bundle semantics:** for the VM domain, a `SiteResource` row
  already corresponds 1:1 to one physical host (existing `vm_host`
  attribute). No new cross-row bundling machinery is needed for pass 1;
  bundling is deferred to whenever a domain needs dimensions spread across
  rows.
- **Fit-check correctness:** full per-dimension held/available accounting,
  extending `CapacityLedgerService`'s existing lease-window held-units
  machinery, not a declared-capacity-only gate. The storefront's
  pre-reservation checks remain projections that can be invalidated at
  actual reserve time — only the site-authority ledger's own accounting
  needs to be exact under concurrency.
- **`total_units` handling:** stays as a service-maintained mirror of
  `capacity["gpu_count"]` rather than a full cutover of every existing
  reader — the same documented intermediate-state-limitation pattern
  POOLS-2 used for its process-local assignment cursors.
- **`CapacityEvent` payload:** extended with per-dimension deltas in pass 1,
  not deferred.
- **VM shape scope:** vcpu/ram/disk are a **fixed, seller-declared
  listing attribute** (like `gpu_model` already is) for pass 1, not a
  per-order negotiated dimension. `ComputeResource` already has
  `vcpu_count`/`ram_gb`/`disk_gb` fields (correcting the "concrete gap"
  framing above, which understated what already existed) — the gap was
  that claim-building never forwarded them. Making VM shape
  buyer-negotiable is real, larger future work that touches the
  negotiation-protocol boundary; it needs its own design review with
  stakeholder sign-off before it's picked up. Do not let pass 1 or pass 2
  quietly grow to cover it.
- **`resource_capacity_validator.py`:** left as-is. It validates operator
  CSV input against the storefront's local `resources` table, a different
  concern from the admission-time fit gate, and that local table is
  already slated for retirement by `pools-8`'s `CapacityProjection`.
  Dimension vocabulary (`vcpu_count`/`ram_gb`/`disk_gb`) is converged so
  the validator can be deleted outright when `pools-8` lands, instead of
  migrated now — recorded as a dependency in `pools-8`'s proposal.
- **Package boundary:** pass 1 stays inside current package boundaries
  (`compute_provisioning`, `kit/site`). Moving
  `PhysicalSettlementScheduler`/`DeterministicRoundRobinPolicy` and the
  shared `resource_satisfies_requirement` predicate into a new
  `kit/physical-settlement` package is `pools-7`'s decision and its scope
  to execute, not pools-6's to preempt.

## Status of the requirement delta

The `## ADDED Requirements` in this change's `specs/physical-provisioning/spec.md` use the standard openspec delta header — openspec's delta model has no separate "proposed but not yet decided" state, every change is a proposal until archived. Pass 1's design is now resolved (above) and ready to implement; pass 2's is not. The "Non-Work / Deferred Decisions" list below and the open questions in `design.md` cover only pass 2 and must be resolved in a follow-up design session before pass-2 requirements are implemented or this change is archived.

## Candidate directions

Potential designs include:

- lowest projected dominant utilization on each concrete candidate;
- capacity-weighted pool fairness followed by resource placement;
- consumer-aware DRF using buyer, agreement, organization, queue, or workload-class shares;
- policy composition where hard eligibility precedes quotas, fairness, placement, and deterministic tie-breaking;
- external scheduler integration behind the `SettlementSchedulingPolicy` protocol.

No candidate is selected by this change.

## Risks and concerns

- Dimensions may use incompatible units or represent indivisible resources.
- Pool-level aggregation can hide that dimensions live on different physical resources.
- A utilization policy can conflict with consumer fairness or operational spreading.
- Historical accounting can make retries and recovery nondeterministic unless assignment state is durable.
- Weights, quotas, priorities, and preemption can undermine intuitive fairness.
- Topology and affinity can sharply reduce the candidate set and produce starvation.
- External scheduler dependencies may bring worker, queue, or cluster-runtime assumptions larger than the policy boundary.
- Explainability is required so operators can understand why a resource won or why no candidate fit.

## Non-Work / Deferred Decisions (pass 2)

Pass 1's dimension-representation and admission-correctness questions are
resolved above. These remaining questions are pass 2's — a future design
session must answer them before a fairness/placement policy is implemented.

- What is the fairness subject: buyer, agreement, organization, queue, workload class, or another principal? (Buyer/agreement was the leading candidate raised in the 2026-07-20 review — it matches the Market Agreement identity already in the system — but it was not confirmed; pin this at the start of pass 2.)
- What is the fairness scope: provisioning domain, market, provider, compatible pool group, or global installation?
- Are pools equal participants or weighted by total usable capacity?
- Is the primary objective spreading, dominant-share fairness, utilization, bin packing, cost, or an ordered combination?
- How are indivisible resources such as bare-metal nodes represented?
- How is historical usage retained, decayed, and recovered after restart?
- How do quotas, reservations, priorities, and preemption interact with fairness?
- How are topology, affinity, anti-affinity, failure domains, and data locality represented?
- When the fairest candidate cannot fit, what fallback ordering applies?
- Do exact-resource requests affect fairness accounting even though they bypass policy choice?
- What happens after provider failure: preserve assignment, explicitly invalidate it, or reschedule?
- Which policy decisions and score components must be emitted for observability?
- Can a maintained external library satisfy the contracts without importing an incompatible runtime model?
