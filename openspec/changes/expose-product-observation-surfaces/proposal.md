# Expose authoritative product observation

## Why

Judging whether the product behaved requires asking the product what happened,
through a surface that is stable, documented, and not a test fixture.

Today that answer is assembled from whatever a test can reach: internal
identifiers, database state, log lines, and admin endpoints that exist for
operators rather than for observation. Each is a private detail that changes
without notice, and an external consumer binding to one is binding to something
this repository never promised.

The consequence is asymmetric. When an observation surface changes, the consumer
does not fail loudly — it reports a wrong answer confidently, because the shape
it expected is gone and the shape it found is plausible.

## What Changes

- Identifies the deal state an external consumer must be able to observe, stated
  in terms of the deal lifecycle rather than of any service's internals.
- Exposes that state through documented, versioned surfaces with stable
  identifiers, distinct from operator and administrative endpoints.
- Records what each surface does **not** promise, so a consumer cannot mistake
  an incidental field for a contract.
- Establishes that an observation surface is a public contract: changing one is a
  spec change, not an implementation detail.

## Permanent documentation impact

- [x] Existing subsystem specification
- [x] New subsystem specification — observation surfaces

## Impact

- Affected specs: to be determined during grooming; spans several domains
- Depends on `declare-deal-lifecycle-contract` for the vocabulary the surfaces
  report in
- Consumed by an external suite that must not read internal state
