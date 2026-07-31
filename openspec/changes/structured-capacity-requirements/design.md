# Design

## Discuss phase (2026-08-01)

This section preserves the alternatives considered during POOLS-7 Section
11's code review, where these questions first came up. Nothing here is
implemented; this is discussion carried forward into its own change so it
isn't lost, re-derived, or silently dropped when Section 11 closes.

### Nested requirements shape vs. flat dimensions

**Rejected:** putting categorical fields inside `dimensions`:

```json
{"dimensions": {"gpu": {"model": "A100", "count": 4}}}
```

`dimensions` has one clean invariant today: every value is quantitative,
matched by sufficiency (`available >= requested`). Mixing in `model`
(matched by equality) means the matcher must know, per nested field,
which comparison applies — the name `dimensions` no longer describes
the contract it holds.

**Accepted direction:** a `requirements` object grouped by hardware
family, with each family's own schema defining which of its fields are
quantitative and which are categorical:

```json
{
    "requirements": {
        "gpu": {"count": 4, "model": "A100"},
        "cpu": {"count": 16},
        "memory": {"gib": 64},
        "storage": {"gib": 200}
    }
}
```

**Important scoping decision, reached after the initial proposal:** this
nested shape does not eliminate the type-awareness problem — it
relocates it one level down (something still has to know `gpu.count` is
quantitative and `gpu.model` isn't). The resolution is that this is
fine, *as long as it's resolved before reaching the generic matcher*: a
domain-layer parser (the natural evolution of
`compute_capacity_claim_from_order`) decomposes `requirements` into the
existing flat `dimensions`/`attributes` split before calling
`capacity.probe`/`reserve`. The generic matching contract
(`resource_satisfies_requirement`, `dict_resource_satisfies_claim`)
never needs to understand nested, per-family semantics — it keeps
working exactly as POOLS-7 Section 11.2 left it.

### `resource_type` vs. a buyer-facing offering concept

Three distinct concepts were conflated under `resource_type` in the
original Section 11.2 implementation:

1. **Market/product type** — what the buyer is purchasing: VM, bare
   metal, Kubernetes pod, API credits.
2. **Requested resource shape** — CPUs, memory, GPUs, storage, network.
3. **Provider inventory representation** — the site's own internal
   adapter/record kind: `compute.gpu`, `token.erc20`,
   `information.note`, `api_credits`.

`resource_type` as it exists today (`kit/site`'s
`_split_claim_requirement`'s `required_resource_kind`, and Section
11.2's `_VM_RESOURCE_TYPE = "compute.gpu"` constant) is concept 3 — a
site-internal inventory-adapter discriminator. The buyer should not need
to know a VM site models capacity through a `compute.gpu` adapter; a
site might satisfy an `offering_type: "vm"` request from several
internal resource rows (host CPU capacity, host RAM capacity, GPU
capacity, VM quota capacity) without the buyer ever seeing
`resource_type` at all.

**Naming alternatives considered for the new, separate concept:**
`market_type`, `fulfillment_type`, `offering_type`. `offering_type` is
preferred: it describes what the buyer is purchasing without overloading
"domain" (an internal repository-layering term) or "resource type" (the
existing inventory-adapter term).

**Open question, not yet resolved:** whether `offering_type` needs to be
a real wire field at all. If a storefront can only ever reach
domain-matching site endpoints (true today — VM's storefront never talks
to a bare-metal site), the domain boundary itself already establishes
the type, and repeating it inside the claim may be unnecessary. It only
becomes load-bearing once a single aggregate capacity authority serves
multiple offering types through one endpoint. Confirm which architecture
is actually true before implementing this field.

### Vocabulary rename: cheap part vs. expensive part

Proposed staged rename, evaluated for cost before committing to it:

1. Rename local variables (`required_attributes` → `capacity_claim`)
   immediately, wherever touched — zero blast radius, since these never
   leave the function they're declared in.
2. Design `ResourceRequirement`/`requirements` (this change) before
   renaming anything wire- or storage-level, so the vocabulary doesn't
   get renamed twice.
3. Introduce the new stored/wire field with explicit compatibility
   handling once §1's shape is settled.
4. Remove the old `"required_attributes"` name only after every
   persisted/resume path has migrated.

Step 1 already happened during POOLS-7 Section 11.7.5 (confirmed: the
local variable in `vm_job_spec_service.py` is renamed; the wire key
`"required_attributes"` is untouched, correctly, since it's real
external/persisted surface — checked its full blast radius: admin API
request/response bodies, `fulfillment_resume_runtime.py`'s durable
resume context, and `core/storefront-client`'s external client library).
Steps 2–4 are this change's job.

## Unresolved questions

- Does `capacity.probe(requirement=...)` replace or sit alongside
  `capacity.probe(claim=...)`? A pure rename has no behavior change but
  touches every caller; an additive parameter avoids that but leaves two
  names for the same concept indefinitely.
- Should `ResourceFeasibilityView`-style matching ever become a
  `core`-layer concept, given `core/storefront`'s `CapacityClient`
  protocol is meant to be backend-agnostic? (Answered narrowly for
  Section 11.2's specific bug already — no, injection at the domain
  composition layer is correct, not a `core` promotion — but the
  question may recur as more domains need exact matching.)
- Where does the domain-layer `requirements` → `dimensions`/`attributes`
  parser live for a second domain (bare-metal, apicredits) once VM has
  one? A shared kit-layer parser is tempting but needs the same
  dependency-direction scrutiny Section 11.2 already applied to
  `ResourceFeasibilityView`.

## Design promotion record

Not started. No decisions in this document are implemented yet.
