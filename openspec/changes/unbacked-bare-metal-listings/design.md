# Design — unbacked bare-metal listings

## Context

Split out while designing `publish-indicative-listing-rates`, when it became clear
that Goal 7's primary target domain had no owner for the supply the goal exists to
serve. `bare-metal-publication-reads-pool-declarations` refuses unbacked pools and
records unbacked bare metal as a question with no owner; this change is that owner.

A design review on 2026-10-14, against the tree after
`bare-metal-mock-provisioned-deal` (archived 2026-10-09) and
`pools-9-retire-local-physical-authority` (archived 2026-10-13), revised two of the
original decisions and opened the questions listed at the end. Its first outcome is a
prerequisite change, `encapsulate-capacity-backing`.

## Decisions

### Backing is decided by one delegate both domains share

Unbacked listings already exist for VM through `kit/capacity-publication`
(`UnbackedBinding`, source reconciliation scoped to every listing, capacity
reconciliation scoped to backed listings) and `kit/resource-pools`'s declaration
reader. Introductions settle through the composition
`compose-contact-exchange-across-compute` promoted into the mechanism kit, so the two
domains share one implementation of accepted-state interpretation and one per-origin
contact resolution.

The review found that adopting those kits is not enough: every consumer still decides
what backing means by comparing the label, and VM and bare metal already disagree
about it. Bare metal handling unbacked supply by adding its own branches would
duplicate each decision. So `encapsulate-capacity-backing` first gathers every
decision that differs between backed and unbacked supply into one backing delegate,
selected by the pool's `capacity_backing` label, and moves VM and bare metal onto it,
unifying where they diverge. This change then makes bare metal accept unbacked pools,
with no bare-metal branch on backing: what differs is the delegate's.

### Identity is the site and the Physical Resource; host fields are optional when unbacked

An unbacked listing's derivation identity is its site and Physical Resource, the same
identity a backed listing has, with `host_id` and `physical_host_id` optional because
an unbacked declaration need name no host. This is the resource-granular identity VM
adopted when capacity stopped requiring hosts, applied to bare metal unchanged. The
listing payload itself is reviewed under "Open questions".

### The site emits the bare-metal view for unbacked supply

Decided in the 2026-10-14 review, replacing the original decision that an unbacked
candidate is derived from the capacity declaration rather than from a `bare_metal.v2`
publication view.

The site emits a resource's `bare_metal.v2` view only when its declaration enables
bare-metal publication and names a host, and the bare-metal storefront ignores a
resource without the view. A host-less unbacked declaration is therefore invisible to
bare-metal publication today. Rather than have the storefront read unbacked resources
around the view, the site emits the view for a resource in an unbacked pool, host or
no host. Building the view asks the pool's backing delegate what stands behind the
resource: a backed resource's view carries its host identity and availability; an
unbacked resource's view carries neither. Nothing is fabricated: the view omits what
the delegate says is not there, which is what the original decision's objection to a
"fabricated physical view" was guarding against. The view-building logic is
compute-family code shared with the site's other views and consumes the delegate; it
holds no backing branch of its own.

Consequences, also decided:

- The resource's own `bare_metal_publication` declaration attribute remains the
  opt-in for backed and unbacked pools alike, and it is where the view's access
  methods and capabilities come from. An unbacked pool advertising bare metal lists
  only the resources that enable it, as a backed pool does. Whether an unbacked
  listing should publish access methods at all is open (see "Open questions").
- An unbacked resource is never judged against availability: an enabled, shaped
  resource is a candidate and a disabled one is withdrawn. It never closes as
  unavailable. This is the delegate's decision, consistent with an unbacked listing
  being inexhaustible.
- The region, asking-rate, and override holds apply to an unbacked pool exactly as to
  a backed one, and the shape rules — exactly one `units`, a GPU count and model —
  are unchanged.

### Negotiation and settlement compose the existing kit runtimes

Negotiation and settlement for an unbacked bare-metal listing sit on the kit
negotiation runtime and settlement composition that `bare-metal-mock-provisioned-deal`
(archived) composed for bare metal. Settlement, the introduction reveal, per-origin
contact resolution, seller-side delivery, and retention key only on the listing's
origin site and need no change.

The original decision called this "a publication change" relying on that composition
for the rest. The review found pieces outside publication that neither change owns —
the opening source check, the capacity-effect guards, and the listing payload's
readers — which are open below.

### This change removes bare metal's temporary refusal of unbacked pools

`encapsulate-capacity-backing` moves every backing decision into the backing delegate
except one: bare-metal publication's refusal of an unbacked pool. It keeps that refusal
deliberately, as an explicit and tested comparison of the pool's backing label in
bare-metal publication's pool reading, because it adds no unbacked bare-metal supply
and the delegate cannot express the refusal — bare metal composes contact exchange, so
the delegate's settlement admissibility would otherwise publish a contact-only
unbacked listing. It is the only comparison of the label that change leaves in the
tree.

This change deletes that check and its `pool_unbacked` report, after which bare metal
derives listings from every enabled pool advertising `bare_metal` whatever its
backing, like every other domain, and nothing outside the delegate compares the label.
No other mechanism replaces it.

## Open questions

From the 2026-10-14 review. Each is to be decided with the maintainer, after the
prerequisite's delegate operations are known where it depends on them, and recorded
here as a decision.

1. **The unbacked listing payload.** `BareMetalListing` declares
   `capacity_backing: Literal["backed"]` and requires non-empty host fields, and
   `access_methods` defaults to `["ssh"]`, a commitment nothing delivers for unbacked
   supply. Decide the payload and every reader of host fields.
2. **Backing on refresh and reopen.** Settled by the prerequisite: every domain,
   bare metal included, applies one shared backing comparison first on every refresh,
   reopen, and source check, and backing is no longer a bare-metal term field
   (`encapsulate-capacity-backing`, "Divergence: backing disagreement on refresh and
   reopen"). Nothing further is owed here.
3. **Settlement options for unbacked listings.** Bare metal already declares per
   seller stage whether a mechanism provisions through capacity (`SellerStage.physical`),
   but publication applies no filter and accepts an empty payload. Decide how the
   delegate's settlement admissibility applies, the operator notice, and the empty
   refusal.
4. **The opening source check.** It refuses every unbacked bare-metal listing today,
   and `storefront-publication`'s inventory guard forbids contacting a site authority
   for an unbacked listing, while bare metal's recheck reads the site's live
   projection. The prerequisite routes the check through the backing delegate, so an
   unbacked listing's availability is never consulted; what remains is the live read
   of declarations. Either bare metal reads a projection its storefront holds — which
   needs VM's held per-site projection state extracted into the kit, owned by
   `kit-owned-listing-and-fulfillment-lifecycles` — or the requirement is scoped to
   availability. Decide which.
5. **The fulfillment routes for an unbacked deal.** The prerequisite routes every
   bare-metal capacity effect through `CapacityRuntime` and the delegate's admission
   guard, so an unbacked binding is refused before any site call. What remains here:
   the fulfillment routes load a context requiring a Physical Resource and host, and
   answer a binding with no host with an unhandled error rather than a clean refusal.
6. **The permanent documentation delta.** Besides the requirement this change
   removes, "A bare-metal listing sells one whole unit", "Bare-metal opening rechecks
   its listing against its source", the publication architecture companion, and the
   bare-metal seller quickstart state that every bare-metal listing is backed.
7. **The bare-metal system evidence.** The existing bare-metal introduction scenario
   uses a backed pool and the typed client and has no delivery; the bare-metal lane has
   no mail sink; the bare-metal chart forwards no delivery or registry configuration.
   Decide the evidence and whether it includes a Helm release.
8. **The two-seller topology for both lanes (task 2.2).** Adding a second site to
   either existing lane breaks single-site assertions and configuration. Decide the
   topology, and whether it stays in this change.
