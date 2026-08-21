## Context

`_validate_evidence` in `e2e-tests/src/hosted_real_stripe/evidence.py` runs
after the scenario, from `write_evidence`, and is the last thing a run does.
It validates two identity halves. The consumer half is already mode-aware:
`_validate_attested_consumer` runs only when the recorded mode is attested, and
otherwise the half must merely name the image it ran. The producer half is not:
its source commit, workflow run id, workflow ref, and three digests are
required to be exact in every mode.

`gates.py` — which decides whether a run is admitted at all — already draws the
distinction correctly. `_require_hosted_half` branches on
`_hosted_half_is_released`, refuses a half that is partly both, and for a local
half requires an image with no registry digest plus an exact manifest digest.
Every coordinate it cannot supply becomes `LOCAL_COORDINATE`, the literal
string `local`, chosen to be self-describing on sight.

So the binding gate and the evidence writer disagree about the same run: one
admits it, the other refuses to record it. The gate is right.

## Goals / Non-Goals

**Goals:**

- A development run records its outcome, whatever that outcome was.
- The evidence writer and the binding gate apply one rule, so a run that was
  admitted can always be recorded and a combination that was never admitted is
  never accepted.
- A locally built half names what it actually ran, rather than six markers.

**Non-Goals:**

- Changing what is admitted. This does not relax a single binding check.
- Letting a development run claim attestation. Mode still comes from what was
  bound, and the `local` marker is what makes an unattested coordinate
  obvious in a report without cross-referencing the mode.
- Rewriting evidence for the marketplace half, which is already correct.

## Decisions

**D1 — Judge each half on its own coordinates, not on the run's mode.** The
recorded mode is `local` when *either* half is local, so branching the producer
check on the mode alone would accept a released producer that lost its
coordinates whenever the consumer happened to be local. Instead each released
coordinate of a half must be exact, or every one of them must be the marker.
This is `_hosted_half_is_released`'s rule, applied where the run is recorded.

**D2 — Refuse a half that is partly both, explicitly.** Falling back to "accept
if any coordinate looks local" would silently record a half with three real
digests and three markers, which no admitted run can produce. Making it an
error means a future change that half-populates the group is caught at the
point where the report is written rather than by whoever reads the report.

**D3 — Record the image and the manifest digest for the producer half.** A
locally built producer whose evidence is six markers names no producer at all,
and two development runs against different builds would be indistinguishable.
The image and the reported manifest digest are what the gate already required
that half to supply, so they exist by the time evidence is written. The
consumer half already records its image for the same reason.

Alternative considered and rejected: put the local build's manifest digest in
the `manifest_sha256` field, since it is a sha256. It is not the same thing —
`manifest_sha256` is the digest of a signed release manifest, and a build has
no manifest to sign. Reusing the field would make a build indistinguishable
from a release by inspection, which is the property the marker exists to
preserve.

## Risks / Trade-offs

- **The evidence document gains two fields.** Any reader that validates the
  producer identity shape strictly will need them. Nothing in this repository
  reads the document other than the writer and its tests; the schema id is
  unchanged because the contract is extended, not altered, and attested
  evidence keeps every field it has today.
- **More evidence is written than before**, including for runs that failed.
  That is the point — a failed development run's report is the diagnosis — and
  the mode field already prevents any of it from qualifying a protected task.
