## Context

The fulfillment scheduler already filters concrete candidates with authoritative multidimensional availability and uses deterministic round-robin for selection. The `SettlementSchedulingPolicy` boundary is replaceable, but no fairness subject, scope, objective ordering, historical accounting model, or durable policy state has been selected.

A policy receives only eligible concrete candidates. Reservation validation, idempotency, assignment persistence, capacity claims, and provider execution remain orchestration responsibilities outside policy scoring.

## Goals / Non-Goals

**Goals:**

- Select and specify one richer placement/fairness policy.
- Preserve hard multidimensional fit and deterministic behavior.
- Make policy decisions durable, explainable, and recoverable.
- Prove the policy protocol with a second implementation and simulation evidence.

**Non-Goals:**

- Change admission-time capacity accounting or the shared fit predicate.
- Change physical-settlement requests, assignment identity, or provider contracts.
- Treat aggregate capacity across unrelated resources as concrete fit.
- Select a policy before the fairness subject and scope are approved.

## Decisions

### Hard fit precedes policy scoring

The scheduler continues to reject candidates that do not satisfy every required dimension before invoking policy selection. Policies cannot combine unrelated rows or relax eligibility.

**Alternative:** Score pools by aggregate capacity first. Rejected because aggregate fit does not prove any concrete candidate can serve the request.

### Round-robin remains the compatibility baseline

The richer policy is introduced beside deterministic round-robin. Composition can select either without changing caller or provider contracts.

**Alternative:** Replace round-robin immediately. Rejected until persistence, recovery, starvation, and adversarial behavior are proven.

### Policy selection is design-gated

No algorithm is selected yet. Candidate directions include lowest projected dominant utilization, capacity-weighted pool fairness, consumer-aware DRF, or ordered policy composition. Before implementation, the design MUST resolve:

- fairness subject and scope;
- pool weighting;
- precedence among fit, fairness, utilization, spreading, cost, and topology;
- indivisible resources, quotas, priorities, preemption, and starvation;
- historical accounting, persistence, decay, and restart recovery;
- exact-resource accounting;
- provider failure and explicit reassignment.

### Candidate algorithms require simulation

Evaluation compares maintained external libraries and internal scoring approaches using identical workload traces. An external library is acceptable only if it fits behind `SettlementSchedulingPolicy` without importing its worker, queue, task-graph, control-plane, or cluster-lifecycle model.

### Durable state and explanations are part of correctness

If historical state affects selection, it must be committed transactionally with capacity claims and assignments. Stable pool/resource identifiers are the final tie-breakers. Each decision records an operator-safe explanation containing candidate counts, rejection reasons, policy identity/version, fairness subject/scope, normalized score inputs, applied weights or quotas, tie-breaker, and outcome. Provider secrets are excluded.

## Risks / Trade-offs

- **A fairness objective may reduce utilization or increase starvation elsewhere.** Mitigation: approve objective ordering and test long workload traces and adversarial shapes.
- **Historical state can make retries or restarts nondeterministic.** Mitigation: transact policy state with assignments and return existing assignments on retry.
- **External schedulers can expand operational ownership.** Mitigation: reject dependencies that require unrelated runtime machinery.
- **A policy can leak commercial or provider-sensitive data through explanations.** Mitigation: define an allowlisted, operator-safe explanation schema.
- **Indivisible and topology-constrained resources can violate intuitive fairness.** Mitigation: specify fallback and starvation semantics before implementation.

## Migration Plan

1. Resolve and approve the open policy decisions.
2. Simulate candidate policies without changing production selection.
3. Add any required schema through additive migrations.
4. Introduce the second policy behind explicit configuration while retaining round-robin rollback.
5. Validate concurrency, restart recovery, starvation, and deterministic explanations before enabling it by default anywhere.
6. Roll back by selecting round-robin; preserve policy history needed to interpret prior assignments.

## Open Questions

- Is the fairness subject a buyer, agreement, organization, queue, workload class, or another principal?
- Is fairness scoped to a site, provisioning domain, market, provider, compatible pool group, or installation?
- Are pools equal or weighted by usable capacity?
- Which objective dominates when fairness, utilization, spreading, cost, and topology disagree?
- How are quotas, priorities, preemption, decay, and starvation represented?
- How do exact-resource requests affect historical fairness?
- What state survives provider failure and explicit reassignment?
