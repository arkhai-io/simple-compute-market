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

## Design promotion record

| Accepted decision | Permanent location | State |
|---|---|---|
| Canonical public signer evidence remains loggable; private delivery is excluded from progress | `openspec/specs/buyer-orchestration/architecture.md#identity-first-execution` | Promoted to specification and companion |
| Existing authority, dependency, wire and persistence boundaries remain applicable | `docs/development/ARCHITECTURE.md` | Verified no repository-wide change needed |

Qualification scope and current-state summary are reconciled in
`docs/development/ROADMAP.md#payment-qualification-boundaries`.

## Validation provenance

The following preserves pre-archive implementation and qualification observations
compressed from the task ledger. Final promotion and review are recorded above.

Round validation: core buyer 169 tests passed, including signed HTTP status/result
handling with a private-delivery canary. The actual ordinary VM end retry passed
using the same durable operation and receipt, with no repeated native release or
signed financial event. Existing journals remain historical; new status-only
progress does not rewrite them. Supported-tool packaging and comment checks
passed. The exact executable commit 6c2fa5004 passed all 20 root make-test targets in
[Tests CI 41998371221](https://github.com/arkhai-io/simple-compute-market/actions/runs/41998371221);
independent Standards/Spec review reported no confirmed finding. The applicable
automated hosted-payment system journey passed; the default Compose workflow
and its named markers remain unrun, not passed. Formal validation/closeout records
and permanent documentation remain outstanding.

Documentation promotion: the companion architecture records the accepted current
behavior at `openspec/specs/buyer-orchestration/architecture.md#identity-first-execution`. The design-promotion record identifies the unchanged
repository-wide boundaries and roadmap destination. Normative deltas and archival
remain outstanding; documentation edits change no executable package input.

Closeout checks: comment/import discipline and changed/permanent citations pass;
`make check-change` and `make check-architecture-change CHANGE=retain-public-signer-evidence-in-buyer-logs`
pass with pinned strict validation. Packaging is reused from the unchanged reviewed
executable inputs; no package, lock, code or architecture-rule input changed.
All root make-test targets pass in Tests CI41998371221 on6c2fa5004; subsequent
dev integration adds only workflow/introduction-test changes, with2176tooling and
505E2E-unit tests and packaging passing on the exact resolved code. Applicable
automated ordinary-buyer Arkhai qualification is recorded separately from the
unrun default Compose/Alkahest workflow. No fresh unassisted VM financial run
or LIVE financial processing is claimed. Normative merge/archive and its
independent documentation review remain the final unchecked closeout task.

Normative promotion: `openspec/specs/buyer-orchestration/spec.md#requirement-public-signer-evidence-remains-loggable`.
The archived documentation was independently reviewed at b829afbdb, with no
confirmed Standards or Spec finding.
