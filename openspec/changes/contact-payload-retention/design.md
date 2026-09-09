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

## Goals / Non-Goals

**Goals.** Make the existing retention requirement executable. Tell both parties
what the window is. Keep the deal intact when its payloads go.

**Non-Goals.** No change to the reveal surface, no aliasing, no change to what is
persisted at start.

## Decisions

### The window is configured with an explicit default, not left unbounded

An implicit unbounded default reads as "no policy" and is what exists today. A
configured window with an explicit default forces the operator to have made a
decision, and makes the value available to disclose. An operator who genuinely
wants indefinite retention can say so, which is a different and better state than
never having considered it.

### Deletion preserves the obligation record

This is already the requirement's wording and it is worth restating why. The
settled obligation record is the deal's durable identity: `obligation_ref` is the
universal deal-settlement identity, and cross-mechanism status and tooling
correlate deals by it. Removing it to remove contact data would erase the deal
rather than its payloads, and would break correlation for a deal that legitimately
happened.

So deletion is scoped to the payload columns. The introduction remains a real
settled deal with a terminal state; what it no longer carries is anyone's contact
details.

### Deletion is idempotent

The reveal path is already built on idempotency — the read is idempotent, the
start converges on retry, and the mechanism's persistence contract is written so
a retried operation converges rather than failing. A sweep that failed on an
already-deleted row would be the one operation in this surface that does not, and
a partially-failed sweep is exactly when a retry happens.

### Disclosure travels with the reveal

The window is disclosed through the projection that already carries the reveal,
rather than through separate documentation or an operator-published notice. Both
parties already read that projection to obtain the contact details; it is the one
point where both are guaranteed to be looking.

**Disclosure must be accurate about its scope.** Delivery sinks hand each side a
copy of the reveal at settlement, dispatched to whatever file, webhook, mail, or
local program the operator configured. Deleting the storefront's copy does not
reach those. Saying "your details are deleted after N days" without that
qualification would be a false statement about where the data is, so disclosure
describes storefront retention specifically.

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
- **[An operator sets a window shorter than the parties expect]** → Mitigated by
  disclosure at reveal, which is when a party can still choose not to proceed.
- **[Disclosure is read as covering delivered copies]** → The reason the
  disclosure text is scoped explicitly rather than left to the reader.
- **[A sweep deletes payloads for a deal still being serviced]** → The obligation
  lifecycle and the retention window are independent, and a long-running
  servicing path could in principle outlive a short window. Confirm the servicing
  path never re-reads the payloads after the reveal; if it does, the window's
  floor is a real constraint rather than an operator preference.

## Open questions

- **Is the sweep storefront-scheduled or operator-invoked only?** A scheduled
  sweep honours the policy without operator action and is the reason this is
  called automation; an operator-invoked path alone is simpler and cannot delete
  unexpectedly. Both are in `What Changes` because the single-introduction path is
  needed regardless — for an on-request deletion — but whether the sweep runs
  unattended by default is deferred. No task prescribes a default.

## Migration Plan

1. Add the deletion path and its idempotency.
2. Add the configured window with an explicit default and disclose it at reveal.
3. Add the sweep.

Existing deployments hold payloads with no recorded window. The migration does
not delete them: an operator setting a window applies it going forward, and
deleting historical payloads on upgrade would be a data loss the operator never
requested.
