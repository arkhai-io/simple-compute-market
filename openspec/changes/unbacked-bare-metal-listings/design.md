# Design — unbacked bare-metal listings

## Context

Split out while designing `publish-indicative-listing-rates`, when it became clear
that Goal 7's primary target domain had no owner for the supply the goal exists to
serve. `bare-metal-publication-reads-pool-declarations` refuses unbacked pools and
records unbacked bare metal as a question with no owner; this change is that owner.

## Decisions

### The same mechanisms as VM, not a bare-metal copy

Unbacked listings already exist for VM through `kit/capacity-publication`
(`UnbackedBinding`, source reconciliation scoped to every listing, capacity
reconciliation scoped to backed listings) and `kit/resource-pools`'s declaration
reader. Bare metal adopts them rather than implementing a parallel unbacked path.
Introductions likewise settle through the composition
`compose-contact-exchange-across-compute` promotes into the mechanism kit, so the two
domains share one implementation of accepted-state interpretation and one
per-origin contact resolution.

## Open questions

- **Listing identity without a host.** A bare-metal listing's identity is its site and
  Physical Resource, and its schema requires a `host_id` and `physical_host_id`. An
  unbacked pool's capacity declaration need name no host. Whether an unbacked listing's
  identity is its Physical Resource alone, and which listing fields become optional for
  it, is undecided.
- **Where the candidate comes from.** Backed bare-metal candidates come from each
  Physical Resource's `bare_metal.v2` publication view. Whether an unbacked candidate
  uses the same view, produced by a configuration-free provider, or is derived from the
  capacity declaration directly.
- **Whether this is one change or several.** Publication, negotiation, and settlement
  composition may be separable; decide when planning.
