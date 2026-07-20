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

## Status of the requirement delta

The `## ADDED Requirements` in this change's `specs/physical-provisioning/spec.md` use the standard openspec delta header — openspec's delta model has no separate "proposed but not yet decided" state, every change is a proposal until archived. That header does **not** mean this is implementation-ready: the "Non-Work / Deferred Decisions" list below and the open questions in `design.md` must be resolved in a dedicated design session before any of these requirements are implemented or this change is archived. Treat this change directory as a placeholder for problem framing, not a ready-to-build spec.

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

## Non-Work / Deferred Decisions

This change records questions for a future design session; it does not answer them now.

- What is the fairness subject: buyer, agreement, organization, queue, workload class, or another principal?
- What is the fairness scope: provisioning domain, market, provider, compatible pool group, or global installation?
- Which dimensions are first-class, what units do they use, and how are quantities normalized?
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
