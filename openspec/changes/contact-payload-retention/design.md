# Design — contact payload retention

## Context

The mechanism's PII posture was designed carefully and is mostly implemented. Its
own design records the reasoning: options and listings carry prose terms and a
channel descriptor only, because "the registry is public and scrapable, and a
contact-bearing listing is a spam directory"; payloads persist only for deals
whose introduction has been started, so a deal that never starts persists no
contact data at all; both payloads persist atomically at start so that "available
to both parties" is a well-defined terminal condition.

The one part left as a requirement without an implementation is the end of that
lifecycle. The same design named it as a risk — "Contact payloads are deliberate
PII persistence. Bound the size, record the retention posture in the capability
spec, and treat deletion as part of the deal lifecycle rather than an
afterthought" — and the first two were done. The third was not.

**More of the third exists than the proposal originally claimed, and the
correction shrinks this change.** `delete_introduction(conn, obligation_ref)` is
already in `kit/contact-exchange/src/market_contact_exchange/migrations.py`,
alongside `insert_introduction` and `load_introduction`, exported from the kit's
`__init__.py`, and unit-tested for exactly the idempotency wanted here — the test
asserts `True` then `False` across a repeat. The `contact_introductions` table
already carries `created_at`.

Neither has a production caller. So this change is not building a deletion path;
it is building everything that would invoke one, and adding the select-by-age
query beside the delete.

## Goals / Non-Goals

**Goals.** Make the existing retention requirement executable. Let a party find
out the window before committing contact data, and confirm it at reveal. Keep the
deal intact when its payloads go.

**Non-Goals.** No change to the reveal surface, no aliasing, no change to what is
persisted at start, no registry or listing-shape change.

## Decisions

### Retention is an aggregate policy over the storefront's dataset

The window is a property of the storefront's data holdings, not a term of any
deal. Nothing in the settlement plan, the obligation, or `service_terms` carries
it; it is not negotiated, not agreed, and not something a counterparty consents
to.

That matters because it settles who decides. The storefront pays for the storage
and carries the liability for holding the data, so the storefront sets the policy.
Parties exercise choice by selecting a storefront whose retention they find
acceptable — which is why the window has to be discoverable, and is the whole
reason for the disclosure decision below — rather than by negotiating a window
per deal.

It also settles a mechanism question. An earlier version of this design proposed
recording the effective window on each row at reveal and having the sweep enforce
the recorded value, on the reasoning that the disclosed window and the enforced
window would then agree by construction. **Rejected.** An operator who shortens
the policy — for cost, an incident, or a legal instruction — would find the new
policy does not apply to the data they most want gone, which inverts the purpose
of having a policy. And the operator can delete any row directly regardless, so a
per-row pin protects nothing: it is performative for the parties and an obstacle
for the operator. The window is therefore read live at sweep time and applies to
the dataset in aggregate.

Setting a finite window is consent to delete existing rows past it. Unsetting it
stops deletion. Both are the operator's to choose.

### The default is 30 days, and unset means indefinite

30 days is an unremarkable retention period for transactional contact data, so it
is a defensible default rather than an arbitrary one. Nothing here is released,
so no deployment holds historical payloads that a first sweep would delete — the
upgrade-deletion problem a shipped default would otherwise raise does not arise,
and defending against it would be defending against a case that cannot occur.

An operator wanting indefinite retention unsets the value. That is a different and
better state than an implicit unbounded default, which reads as the absence of a
policy and is what exists today.

### Both invocation paths, one handler

The sweep runs unattended on a configurable interval and an operator can invoke
deletion for a single introduction on request. Neither substitutes for the other:
a policy honoured only when an operator remembers is the hand-written-SQL status
quo with a nicer interface, and an unattended sweep cannot serve an
out-of-schedule deletion request for one party.

Both call the same underlying operation. `ARCHITECTURE.md`'s operator lifecycle
rule requires it — a manual cycle must invoke the same production handler as the
timer-driven worker — and `kit/storefront`'s negotiation watchdog is the shape to
follow: `sweep_stale_negotiations` performs one cycle and returns a count, and
`run_negotiation_watchdog` loops over it after an initial delay. Both composing
storefronts already start that watchdog unconditionally from configuration, so the
scheduling seam and its configuration pattern exist.

### Deletion preserves the obligation record

This is already the requirement's wording and it is worth restating why. The
settled obligation record is the deal's durable identity: `obligation_ref` is the
universal deal-settlement identity, and cross-mechanism status and tooling
correlate deals by it. Removing it to remove contact data would erase the deal
rather than its payloads, and would break correlation for a deal that legitimately
happened.

So deletion is scoped to the payload columns, which is what the existing
primitive already does. The introduction remains a real settled deal with a
terminal state; what it no longer carries is anyone's contact details.

### Deletion is idempotent

The reveal path is already built on idempotency — the read is idempotent, the
start converges on retry, and the mechanism's persistence contract is written so
a retried operation converges rather than failing. The existing
`delete_introduction` already returns a boolean rather than raising on a missing
row, so this decision is about preserving a property rather than adding one. A
sweep that failed on an already-deleted row would be the one operation in this
surface that does not converge, and a partially-failed sweep is exactly when a
retry happens.

### The window is queryable from the storefront, and disclosed again at reveal

Disclosure at reveal alone is too late to be useful for choice. The buyer's
contact payload accompanies the start request — `IntroductionStart.contact_payload`
is required on the route that reveals — so a party reading the retention policy in
the reveal projection learns it immediately after the point they could have
declined.

So the effective window is readable from the storefront before a buyer negotiates,
on the storefront's existing public readiness projection, which both composing
storefronts already serve at `/health` and `/api/v1/system/health`. That
projection is already a public storefront self-description rather than a bare
liveness check — bare metal's carries the seller principal, its sites, and a
resource count — so a policy field belongs there without inventing a surface. It
goes in a nested object rather than as a flat field, so operator tooling parsing
the readiness shape is unaffected and later storefront-configuration disclosures
have one place to land.

`/api/v1/system/status` was the obvious candidate and is **not** usable: it is
admin-gated in both domains, through `_admin(...)` on bare metal and through the
admin-identity and service-peer middleware on VM. A buyer cannot read it.

The reveal-time disclosure stays as well. It costs nothing, both parties read that
projection, and it reads the same live value, so the two agree by construction.

**Rejected: publishing the window into the registry.** The natural carriers were
the settlement option's published parameters, which already project `profile`,
`channel`, and `terms` from storefront-wide profile configuration into every
listing's `settlement_options`. That would be in the registry, pre-negotiation,
and filterable. Rejected because it puts a storefront-scoped value on every row a
storefront publishes to serve a minority use case, and buyer-side filtering on
storefront configuration is a facility that wants a storefront metadata surface
rather than a field smeared across listings.

**Rejected for now: publisher-level registry metadata.** This is the right scope —
the registry's `Publisher` row already holds one storefront-scoped attribute,
`storefront_url`, set from the publish payload on first sighting — and it is where
a filterable storefront-configuration facility should eventually live, so a buyer
could exclude listings by storefront policy at query time. It needs a
publish-payload field, indexer handling, a read surface, and a capability that is
not `contact-exchange-settlement`. Out of scope here; recorded so a later reader
knows the storefront-query answer was chosen as the minimal step toward it rather
than instead of it.

**Disclosure must be accurate about what it is.** It states current storefront
policy, not a commitment: the operator may change the window or delete a row
directly at any time, and nothing binds them to the value a party read. It is also
scoped to storefront retention specifically — delivery sinks hand each side a copy
of the reveal at settlement, dispatched to whatever file, webhook, mail, or local
program the operator configured, and deleting the storefront's copy does not reach
those. Wording that implied either a guarantee or total coverage would be a false
statement about where the data is and who controls it.

### Aliasing is adjacent and out of scope

A seller's exposure at their revealed address is a real concern and the natural
mitigation is a severable alias. Two observations, neither of which makes it this
change's work:

A per-storefront alias needs no code at all — the seller's contact payload is
bound from configuration, so an operator can put an alias there today. Only a
per-deal alias needs a change, and it needs the payload to become a resolver
rather than a static value, which is the same hook that a storefront serving
several sellers would need. That coupling means the two should be designed
together, and neither is retention.

## Risks / Trade-offs

- **[Deletion races an in-flight read]** → The read is idempotent and
  authenticated; a read arriving after deletion must return a clean
  already-deleted outcome rather than a partially populated record. Cover the
  interleaving directly.
- **[A party is told one window and the policy changes]** → Accepted, and the
  reason the disclosure is worded as current policy rather than a guarantee. The
  operator owns the data and can delete it at any time, so no wording the
  storefront could offer would bind them; claiming otherwise would mislead the
  party rather than protect them.
- **[Disclosure is read as covering delivered copies]** → The reason the
  disclosure text is scoped explicitly rather than left to the reader.
- **[The window is only discoverable per storefront, not filterable]** → A buyer
  comparing many storefronts must query each one after finding its listings, which
  is workable for a minority use case and poor as a general facility. Accepted for
  this version; the publisher-metadata surface above is the eventual answer.
- **[A sweep deletes payloads for a deal still being serviced]** → The obligation
  lifecycle and the retention window are independent, and a long-running
  servicing path could in principle outlive a short window. Confirm the servicing
  path never re-reads the payloads after the reveal; if it does, the window's
  floor is a real constraint rather than an operator preference.

## Open questions

None. The sweep's invocation model, the default, and the disclosure surface are
all decided above.

## Migration Plan

1. Add the select-by-age query beside the existing deletion primitive, and confirm
   the primitive's idempotency and the read-after-delete outcome.
2. Add the configured window with its 30-day default, expose it on the public
   readiness projection, and disclose it at reveal.
3. Add the operator-invoked path and the scheduled sweep over the shared handler.

Nothing here is released, so there is no historical payload set for a first sweep
to act on and no deployment whose behaviour changes on upgrade. An operator who
wants indefinite retention unsets the window before enabling the sweep.
