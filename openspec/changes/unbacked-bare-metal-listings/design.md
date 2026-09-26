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

### Identity is the site and the Physical Resource; host fields are optional when unbacked

An unbacked listing's derivation identity is its site and Physical Resource, the same
identity a backed listing has, with `host_id` and `physical_host_id` optional because
an unbacked declaration names no host. This is the resource-granular identity VM
adopted when capacity stopped requiring hosts, applied to bare metal unchanged.

### The candidate comes from the capacity declaration

An unbacked candidate is derived from the pool's capacity declaration through the
kit's declaration reader, as VM's is, not from a `bare_metal.v2` publication view
produced by a configuration-free provider. A fabricated physical view of supply
nothing stands behind is what backing-as-a-listing-property exists to avoid.

### This is a publication change

Negotiation and settlement composition for an unbacked bare-metal listing sit on the
kit negotiation runtime, which bare metal composes through
`bare-metal-and-credits-domain-stacks` Section 4a; that section's own prerequisite,
the negotiation runtime kit, is in place. This change adds the unbacked candidate to
publication and relies on that composition for the rest, unless planning finds a
piece neither owns.

## Open questions

None.
