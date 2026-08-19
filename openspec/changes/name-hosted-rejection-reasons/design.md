## Context

The hosted mechanism talks to a released, independently signed authority through
a client the marketplace does not own. `_released_call` in
`kit/hosted-settlement` is the seam where that client's errors become the
marketplace's own failure vocabulary, and it deliberately severs the cause with
`from None` so a provider message cannot reach persistence, a response, or a log.

Everything downstream is built on that seam. A non-retryable rejection becomes
`SettlementManualRequired("hosted settlement <operation> rejected")`, the runtime
records `manual_required` with `last_error=str(error)` and no mechanism
reference, and each domain's projection reports a status. Nothing in that chain
is wrong on its own; the composition loses the one fact an operator needs.

A real `card.v1` lane against the real Stripe test account reaches exactly this
state: materialization returns `status='manual_required'` with no settlement
identity, no action, and no reason. The lane cannot proceed and the obligation
cannot be repaired, because nothing recorded what the authority objected to.

## Goals / Non-Goals

**Goals.** A refused hosted operation names itself in the authority's own
vocabulary. An obligation parked for manual intervention says why, identically
across the three domains that adopt the mechanism. The rejection the real lane
then names is diagnosed.

**Non-Goals.** Relaxing redaction. Provider messages, identifiers, payloads,
Checkout and Account Link URLs, and raw provider state stay out of persistence
and responses exactly as they are today. This change also does not qualify any
hosted lane — a development run qualifies nothing, and the protected matrix
stays with `add-bare-metal-hosted-settlement`.

## Decisions

### The code is not the message

`HostedSettlementError` carries `code`, `message`, `retryable`, and
`status_code`. Only `message` can contain provider detail; `code` is the
authority's own stable enumeration, which the marketplace already branches on
(`_UNCERTAIN_RESPONSE_CODES` reads it to decide retryability). Keeping the code
while dropping the message is therefore not a weakening of the boundary — it is
the boundary applied precisely rather than to the whole exception.

`from None` stays. The severed cause is the point: the released client's
traceback can carry request and response fragments, and nothing downstream
should be able to reach them.

### A parked obligation owes an explanation to whoever holds it

`manual_required` means a human has to act. A state that requires human action
and withholds the reason for it is a defect regardless of who is at fault for
the underlying rejection. The reason travels in the field consumers already read
for a funding reason, so no consumer needs a new field to see it.

### One projection, not three

`domains/vms/storefront`, `domains/apicredits/storefront`, and
`domains/bare_metal/storefront` each build the hosted status projection
independently, and all three would otherwise need the same edit. That
duplication is why the projection drifts. The reason is added once to the shared
surface the three build on, which is also the direction the settlement
neutrality work has been moving: a mechanism's projection belongs to the
mechanism, not to each domain that adopts it.

### The e2e reports the result it rejected

The hosted materialization assertion held the whole response and raised a
sentence that did not include any of it. It now names the status, the action
kind, the funding reason, and which fields were populated — enough to
distinguish the failure modes, without emitting an action URL.

### The reason rides in state the record already has

`last_error` reaches the obligation row, but it is free text written by whichever
mechanism raised, so projecting it would leak for a mechanism that never agreed
to be quoted. The code instead travels on the exception, and the manual-required
finish path writes it into the mechanism state the record already carries, under
one key. No schema migration, no new field for a consumer to learn, and a
projection reads it structurally rather than parsing a sentence back apart.

An obligation parked before this existed carries no key and reports no reason,
which is correct: absence is not an invented explanation.

## Risks / Trade-offs

An authority could put provider detail in a `code`. That would be a defect in
the authority, not in this boundary, and the code is already trusted for
retryability decisions — trusting it for diagnosis adds no new exposure.

The diagnosis this enables may turn out to be an authority-side or configuration
matter rather than a marketplace defect. That outcome is recorded for
`add-bare-metal-hosted-settlement` rather than forced into this change.

## Migration Plan

No schema, wire, or configuration change. Obligations already parked as
`manual_required` keep whatever `last_error` they were recorded with; the
projection reports a reason when one is present and the absence of a reason on a
pre-existing row is not treated as an error.

## Open Questions

Which rejection the real `card.v1` lane names is unknown until the code is
carried. The task sequence deliberately does not assume it.
