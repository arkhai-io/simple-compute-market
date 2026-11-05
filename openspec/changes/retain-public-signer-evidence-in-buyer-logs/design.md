# Design

## Context

See `proposal.md`. Run-log validation currently rejects every field named
`signer`, including the canonical public identity carried by a signed
end-delivery claim in the acknowledgement. The effect is already accepted
when logging fails; retry must keep its existing operation identity.

## Decisions

- Permit `signer` only when its value is a mapping with exactly `scheme` and
  `identifier`, validates through the existing identity codec and equals its
  canonical public projection. Retain all other secret/provider field checks.
- Reject malformed, noncanonical or extended mappings and signer objects.
  A field-name-only exception was rejected because it would admit raw secrets.
- Preserve the evidence unchanged. Dropping the public signer or replacing the
  signed evidence was rejected because it would lose the original proof.
- Keep this schema-opaque check in core buyer; import no domain or mediation
  implementation. The existing identity dependency suffices.

## Private settlement progress

The shared polling helper currently copies the authenticated result into public
progress callbacks. Project those observations to `status` only; the final return
retains the complete authenticated result. Both the VM payment hook and the shared
legacy settlement caller already display only status from this callback. Other
public commitment references have their own progress events. A blacklist of known
credential fields was rejected because a future result field could leak again.
Do not tighten retained-run reads or rewrite old signed logs: they are recovery
evidence. Verify a real signed HTTP status sequence and final result with a canary
credential, then assert it never appears in the produced run log.

## Compatibility and validation

No run-log version, wire, persistence or configuration change is required.
Existing records remain readable; an older client retains the logging defect.
Test canonical public evidence round trips, nested private/extended carriers
remain rejected, and an actual VM end succeeds under the same durable operation
without duplicating the accepted surrender.

## Cadence and promotion

One independent patch; focused tests and packaging precede commit. Reuse one
applicable full-suite/end-to-end/independent-review round for the frozen candidate.
Promote the public-evidence distinction into buyer-orchestration specification
and architecture; repository-wide authority and dependency rules are unchanged.
