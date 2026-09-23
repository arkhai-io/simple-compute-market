# Design — bare-metal publication reads pool declarations

## Context

Found while `unbacked-listing-publication` moved the site-generation declaration
reader out of the VM domain and into `kit/resource-pools`. Fixing it there would have
added a resource-pool projection read to a domain that change otherwise touched only
for backing disclosure and the durable seller close, late in a large change. It was
recorded and split out here instead.

## Decisions

### Read the projection through the kit reader, not a bare-metal copy

The joint per-generation rule, the older-producer reading, and enablement are not
specific to an offering mode; that is why the reader lives in the kit. Bare metal
asks `ResolvedPool.advertises("bare_metal")` and applies nothing of its own.

### An unbacked pool yields no bare-metal listing

Every bare-metal listing is published as `capacity_backing: backed`, and its binding
writers record `backed`. A pool declaring itself unbacked could only yield a listing
whose published backing contradicts its pool, so it yields none, with an operator
notice naming the pool. Unbacked bare metal is a separate question with no owner.

### A pool read fails closed per pool, as VM's does

An unresolvable pool holds its listings rather than closing them, because an unknown
declaration is not a withdrawn one. A site whose pool projection has not loaded
derives nothing new and closes nothing.

## Open questions

- **Where the capacity snapshot and the pool projection disagree about a resource's
  pool.** VM reads both from the same projection generation. Bare metal reads the
  snapshot's `pool_id`; the implementation decides whether to switch its candidate
  source to the projection or to join the two, and records why.
