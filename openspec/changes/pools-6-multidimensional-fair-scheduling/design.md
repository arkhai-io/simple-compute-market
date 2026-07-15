# Design notes: Multidimensional Fair Scheduling

## Foundation inherited from POOLS-2

POOLS-6 builds on the `SettlementSchedulingPolicy` protocol. The scheduler remains responsible for reservation validation, idempotency, eligibility, explicit-resource handling, assignment persistence, and transactional capacity claims. A policy receives a sequence of concrete eligible candidates and returns one candidate plus, potentially, an explanation object.

Round-robin remains a valid policy and compatibility baseline. A second policy must be swappable without changing `PhysicalSettlementRequest`, Capacity Settlement Assignment identity, or provider-facing physical settlement.

## Why the earlier aggregate algorithm was insufficient

The previous draft grouped independent resource rows by `resource_type`, calculated the maximum used/total ratio for each pool, and chose the least utilized pool. That approach had several flaws:

- it did not evaluate the requested reservation shape;
- it could aggregate CPU, memory, GPU, or other dimensions across unrelated physical resources;
- it did not prove that one concrete resource could satisfy all dimensions;
- it selected a concrete resource independently after scoring the pool;
- it had no consumer identity or dominant-share history;
- it used unstable tie-breaking.

A future policy must score actual concrete candidates or explicitly model a schedulable resource bundle whose dimensions are co-located.

## Candidate capacity model

A future candidate may expose maps such as:

```python
class MultidimensionalCandidate:
    resource_id: str
    pool_id: str
    total: Mapping[str, Decimal]
    allocated: Mapping[str, Decimal]
    attributes: Mapping[str, object]
```

A reservation may expose:

```python
class MultidimensionalRequirement:
    dimensions: Mapping[str, Decimal]
    attributes: Mapping[str, object]
```

Hard fit is evaluated before fairness. For every required dimension, the candidate must define positive total capacity and have enough unallocated capacity. Dimensions on different concrete resources cannot be combined unless the resource model explicitly declares them one schedulable bundle.

## Projected dominant utilization

One possible placement score is the maximum projected utilization among requested dimensions:

```text
max((allocated[d] + requested[d]) / total[d])
```

Selecting the lowest score can spread heterogeneous requests while accounting for their shape. This is more accurately called lowest projected dominant utilization than DRF because it does not by itself allocate fairly among competing consumers.

Pool fairness could be layered by selecting the pool whose best eligible candidate has the lowest projected score, then selecting the best candidate in that pool. Alternatives include scoring candidates globally or weighting pools by usable capacity.

## Consumer-aware DRF

Classical DRF requires:

- a defined consumer identity;
- multidimensional allocations attributed to each consumer;
- total capacity for the fairness scope;
- each consumer's dominant share;
- an allocation loop that favors the consumer with the lowest dominant share while respecting fit.

Before this term is used, POOLS-6 must specify the consumer, scope, accounting history, treatment of exact-resource requests, weights, quotas, and recovery behavior.

## Policy composition

A likely future pipeline is:

1. hard reservation and entity validation;
2. concrete candidate eligibility and fit;
3. quota and policy constraints;
4. fairness or utilization scoring;
5. topology and affinity adjustments;
6. deterministic tie-breaking;
7. atomic capacity claim and assignment persistence;
8. decision explanation and metrics.

The ordering is a design decision because each layer can change fairness and starvation behavior.

## Determinism and idempotency

Policies must define stable tie-breakers such as pool ID and resource ID after numerical scores. Retrying an unchanged reservation returns the durable assignment and never recomputes a policy decision. Historical fairness state and score inputs must be transactionally consistent with capacity claims if they affect selection.

## External dependency evaluation

A library is suitable only if it can operate behind the policy protocol without requiring Arkhai to adopt its worker registration, queue, task graph, control plane, or cluster lifecycle. Evaluation should cover maintenance, license, concurrency model, multidimensional and indivisible resources, deterministic behavior, persistence assumptions, observability, and extensibility.

Using a large scheduler merely to avoid owning a scoring function may increase rather than reduce operational ownership.

## Observability

A future policy should provide a structured explanation containing at least:

- eligible and rejected candidate counts;
- hard rejection reasons;
- fairness subject and scope;
- score dimensions and normalized values;
- weights, quotas, or priorities applied;
- deterministic tie-breaker;
- selected pool and resource;
- policy name and version.

Explanations must avoid leaking opaque provider secrets.

## Testing strategy

The policy should be tested through simulations and invariants rather than only examples:

- all selected candidates fit the complete shape;
- no dimension is overclaimed under concurrency;
- deterministic results for identical durable state;
- restart-safe idempotency;
- fairness convergence over long sequences;
- behavior with unequal pool sizes;
- indivisible and scarce resources;
- adversarial request shapes;
- starvation and quota boundaries;
- exact-resource accounting;
- topology-constrained candidate sets;
- failure and explicit reassignment workflows.

## Non-Work / Deferred Decisions

The proposal's deferred questions are intentionally unresolved. This design must be revised in a later discuss → plan → implement session before normative requirements or code are added.
