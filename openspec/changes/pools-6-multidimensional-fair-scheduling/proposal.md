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
