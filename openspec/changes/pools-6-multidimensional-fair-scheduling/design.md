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

## Candidate capacity model — resolved for pass 1 (design review, 2026-07-20)

The sketch below is now the actual implementation shape, not a future
possibility. `SettlementCandidate.available` and
`SettlementRequirement.dimensions` (`compute_provisioning/physical_settlement.py`)
are `dict[str, Decimal]` maps, e.g. `{"gpu_count": 1, "vcpu_count": 4,
"ram_gb": 16, "disk_gb": 200}` — a generic map was chosen over fixed
named fields to stay multi-domain-ready without a fixed vocabulary baked
into the type. Key names follow the vocabulary `ComputeResource` and
`resource_capacity_validator.py` already used, rather than introducing a
second one (e.g. `memory_mb`) for the same quantities.

```python
class SettlementCandidate(BaseModel):
    resource_id: str
    pool_id: str
    resource_kind: str
    available: dict[str, Decimal]      # replaces available_units
    enabled: bool = True
    provider: str
    attributes: dict[str, Any] = Field(default_factory=dict)


class SettlementRequirement(BaseModel):
    resource_kind: str
    dimensions: dict[str, Decimal]     # replaces units
    attributes: dict[str, Any] = Field(default_factory=dict)
```

Hard fit is evaluated before fairness: for every required dimension, the
candidate must define positive total capacity and have enough unallocated
capacity. `DeterministicRoundRobinPolicy` needs no change — it only sorts
`pool_id`/`resource_id` strings and never inspects dimensions, confirming
the caller-contract-stability goal above.

For the VM domain, dimensions on different concrete resources are never
combined: each requested dimension is checked against the *one*
`SiteResource` row admission targets, not aggregated across rows, so the
row itself is the schedulable bundle. No cross-row bundling machinery
was needed for pass 1. A future domain that needs dimensions spread
across rows (e.g. a bundle spanning multiple discrete cards) will need
to design that explicitly — pass 1 does not generalize to it.

**Correction (code review, 2026-07-20):** an earlier version of this
paragraph claimed a `SiteResource` row is "1:1 with one physical host."
That's wrong — this codebase already registers *multiple* `SiteResource`
rows against the same physical host (see `test_ledger.py`'s
`_shared_host_ledger`/`_register_dual_mode_host` fixtures, which predate
this change: a shareable VM-slice row and an exclusive bare-metal row
can share one `physical_host_id`). `_has_physical_host_conflict` only
guards **exclusive-vs-shareable mode conflicts** between sibling rows on
one host — it has never been a general "sum of sibling capacities ≤ host
total" check, not even for GPU count before pools-6. That invariant has
always been enforced only at data-entry time, by
`resource_capacity_validator.py`, on the storefront's local inventory
table — not by the site ledger. Pass 1 does not introduce a *new* hole
here: vcpu/ram/disk get exactly the level of protection GPU count
already had (checked against the specific resource row admission
targets, not cross-checked against sibling rows sharing a host). But
**ledger-level enforcement that sibling slices sharing a physical host
don't jointly oversubscribe it (on any dimension, not just exclusive
mode) remains an open gap**, unchanged by this change and not claimed to
be closed by it. Recorded here as a known limitation and candidate for a
future change, not silently resolved by this paragraph's earlier
inaccurate framing.

### Ledger and scheduler changes backing this

- `SiteResource` gains a `capacity: dict[str, Decimal]` column.
  `total_units` is kept as a service-maintained mirror of
  `capacity["gpu_count"]` rather than replaced outright — an
  intermediate-state limitation in the same spirit as POOLS-2's
  process-local assignment cursors, chosen to avoid a breaking payload-shape
  migration for existing callers.
- `SiteAllocation` gains a `dimensions: dict[str, Decimal]` column.
  `CapacityLedgerService`'s held-units accounting (`_held_units` and
  friends) generalizes to sum `dimensions` per key across overlapping held
  allocations in a lease window, falling back to `{"gpu_count": units}`
  for pre-migration rows. This gives full per-dimension held/available
  accounting under concurrency — a declared-capacity-only gate (checking
  the request against a host's total without accounting for other current
  holds) was considered and rejected: it would still let two shareable
  allocations on one host jointly overcommit a secondary dimension like
  RAM even though each fits the host's total individually.
- `probe`/`reserve` claims gain an optional `dimensions` map, authoritative
  when present. Legacy single-quantity claims (`units`/`gpu_count`) keep
  working unchanged via internal translation to
  `dimensions={"gpu_count": n}` — no existing caller's claim shape breaks.
- `CapacityEvent` payloads are extended with per-dimension deltas in pass 1
  (not deferred to pass 2), matching the observability goal below.
- `PhysicalSettlementScheduler._requirement`/`_eligible_candidates` build
  and evaluate `dimensions` the same way.
- **Decimal precision (resolved, code review 2026-07-20):** JSON storage
  serializes non-integral `Decimal` amounts as Python `float`
  (`_serialize_dimensions`), which loses exact precision for values like
  0.1. Pass 1's actual VM dimensions are always integral in practice, so
  this is documented as a known limitation rather than fixed now. A real
  fix (canonical decimal strings, parsed back through `Decimal` on read)
  is not confined to that one function: `PhysicalSettlementScheduler`
  does raw arithmetic directly on ledger payloads in the same process (no
  JSON boundary to hide behind), so a string-valued `available` map would
  need the scheduler updated too, plus every test asserting numeric
  literals against these payloads. Revisit if a real fractional dimension
  is ever needed.

### VM domain wiring — deliberately scoped down for pass 1

`ComputeResource` (`domains/vms/listings/models.py`) already has
`vcpu_count`/`ram_gb`/`disk_gb` fields — a per-slice, seller-declared
shape, populated the same way `gpu_model`/`gpu_count` are. (Correcting the
proposal's original "concrete gap" framing, which said `ComputeResource`
had no such fields at all — that was wrong; the actual gap was narrower.)
What was missing was purely in claim-building:
`compute_capacity_claim_from_order` (`vm_job_spec_service.py`) only ever
forwarded `pool_id`/`resource_id`/`region`/`gpu_model`/`gpu_count` into the
reservation claim, so the already-existing shape fields never reached
admission. Pass 1 adds a `dimensions` map (`gpu_count`, and
`vcpu_count`/`ram_gb`/`disk_gb` when the listing declares them) to that
claim, and `capacity_client.py`'s `sync_site_resources` forwards the same
vocabulary from the storefront's local inventory into
`SiteResource.capacity`. No schema change to `ComputeResource` was needed.
VM shape is still a **fixed, seller-declared listing attribute** for pass
1, not a per-order negotiated dimension — every order against a listing
gets the same shape, and buyer-selectable VM sizing remains real future
work (long-term direction, per the change owner) that needs its own
design review and stakeholder team sign-off before it's picked up.
Nothing here should be read as precedent for skipping that future review
when negotiated sizing is eventually designed.

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

## Package boundary (resolved, 2026-07-20)

Pass 1 keeps all its changes inside the current package boundaries
(`compute_provisioning`, `kit/site`). `pools-7`'s design already planned to
move `PhysicalSettlementScheduler`, `DeterministicRoundRobinPolicy`, and a
shared `resource_satisfies_requirement` predicate into a new
`kit/physical-settlement` package (final home between that and `kit/site`
left to `pools-7`'s own planning). That package doesn't exist yet because
`pools-7` hasn't started. Pools-6 does not create it or preempt that
decision — the pass-1 dimension model is written against the existing
`compute_provisioning`/`kit/site` locations and pools-7 inherits the move.

## `resource_capacity_validator.py` (resolved, 2026-07-20)

Left as-is for pass 1 rather than migrated or deleted. It's a
storefront-local data-integrity check on operator CSV input (does an
import overcommit a host's declared totals), a different concern from the
admission-time fit gate this change adds to `CapacityLedgerService`. It
also operates on the storefront's local `resources` table, which
`pools-8`'s `CapacityProjection` is already slated to retire — extracting
a shared kit helper now would invest in a mechanism scheduled for deletion
in a change that hasn't started. Dimension vocabulary
(`vcpu_count`/`ram_gb`/`disk_gb`) is converged between the two so the
validator can be deleted outright, not migrated, once `pools-8` lands.

## Non-Work / Deferred Decisions (pass 2)

Pass 1's dimension model, admission correctness, and VM-domain wiring are
resolved above and ready to implement. Everything below is pass 2 —
fairness/placement policy selection — and remains genuinely open. This
design must be revised in a later discuss → plan → implement session
before pass-2 normative requirements or code are added. Confirmed so far:
fairness subject leaned toward buyer/agreement in the 2026-07-20 review
but was not pinned down; treat it as still open.
