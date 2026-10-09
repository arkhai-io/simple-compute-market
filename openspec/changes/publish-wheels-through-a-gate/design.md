## Context

Twenty-eight distributions reach public PyPI on merge to `main`. Three wheels
plus images, charts, and the CLI reach Artifact Registry when a human runs
`push-runtime-artifacts`. The two paths enumerate their contents separately —
`packages.json` in the workflow, a hardcoded list in the Makefile — and neither
knows about the other.

The recorded cross-repository promotion model is that artifacts move between
environments by copying and are never rebuilt from source at promotion time,
and that promotion operates on an inventory of components rather than on
individual artifacts. Nothing in this repository publishes that way, and the
pipeline that would is deferred behind a runtime that does not exist.

## Goals / Non-Goals

**Goals:** no public publication without a deliberate act; one enumeration of
what this repository publishes; bytes on a public index identical to bytes
already published to the development registry; a conflicting version fails
loudly before anything is uploaded.

**Non-Goals:** a durable promotion system, automatic deployment, semver
enforcement, and any change to what a distribution contains.

## Decisions

### D1. Merging publishes to the development registry, not to a public index

The trigger is unchanged; the destination is not. This keeps the convenience of
publish-on-merge for the internal case while removing the property that made it
dangerous, which is that a merge could put a permanent artifact on a public
index under a version that already meant something else.

### D2. Promotion copies bytes and verifies them against PyPI first

The step downloads from Artifact Registry, and for each distribution fetches
PyPI's recorded `sha256` from its JSON API — no download needed, the digest is
in the metadata. Three outcomes: absent from PyPI, upload; present with
matching bytes, skip; present with differing bytes, **fail the entire
promotion before uploading anything**.

All-or-nothing is the point. A per-distribution skip would let a partially
promoted set reach PyPI with one distribution's version silently describing
different code from its sibling's, which is the failure the inventory exists to
prevent. Checking all twenty-eight before uploading any is cheap because the
check is metadata-only.

This is meaningful only because the wheels are reproducible — the build backend
stamps a fixed timestamp, so identical source yields identical bytes. Were that
not so, every comparison would report a false conflict.

*Open question for implementation:* PyPI holds both a wheel and an sdist for at
least one current distribution. The step needs a stated position on whether
sdists are promoted, verified, or ignored.

### D3. One enumeration, read from the release inventory

`push-wheels` and the publish matrix both read the same source. Two lists that
must agree, in two languages, in two files, is the failure this repository has
already seen in the hosted-release variables: a fact extracted into a second
representation drifts silently, and the copy that drifts is the one nobody
reads.

Until the inventory format exists, a plain manifest file serves. The
substitution is mechanical and does not reopen the decision.

### D4. Wheels are promoted without relabelling

A wheel's version is inside the artifact — filename, `METADATA`, `RECORD`. It
cannot be retagged the way an image can, and rebuilding under a new version
changes the digest and violates copy-don't-rebuild. So wheel semver is fixed at
build time and promotion may only accept or reject it.

The corollary is that a product version is not a wheel version. The product
version is the human-assigned label at the gate; the inventory binds a set of
independently versioned wheels to it; images are retagged to it. The same
distinction is being recorded against the cross-repository promotion model,
whose current text describes one artifact type in language that reads as
covering all four.

### D5. The interim section is documented by condition, not by intention

The section states what is true — that this repository publishes directly
because no promotion pipeline consumes its artifacts — rather than that it is
temporary or scheduled for removal. A condition is checkable and becomes false
on its own; a stated intention is a migration narrative that rots in place and
is exactly what `AGENTS.md` excludes from permanent code.

**Removal condition:** a promotion pipeline consumes this repository's
artifacts from the development registry. At that point the promotion script,
its target, and this section are deleted rather than adapted.

### D6. Promotion is human-invoked

No schedule, webhook, or trigger. This matches the promotion model's own
decision that semver is human-supplied at a gate, and it introduces no
mechanism capable of publishing without a human — a property other systems
consuming these artifacts are entitled to rely on.

## Risks / Trade-offs

- **[Byte comparison reports a conflict for a benign reason]** → Would mean the
  builds are not reproducible, which is a defect worth surfacing. Fail and
  investigate rather than widening the comparison.
- **[A distribution is stranded: version on PyPI, different code in the
  registry]** → Already true for `arkhai-kit-hosted-settlement` 0.1.4 and
  undetected. This change surfaces it as a hard failure. Resolution is a
  version bump, not a mechanism change.
- **[The interim mechanism outlives its condition]** → The condition is
  checkable and named. It is also cheap: a script and a target.
- **[Contributors expect merge to publish]** → An intended break. Announce it
  in `RELEASING.md` rather than leaving it to be discovered.
- **[Two enumerations reappear because the inventory is late]** → The interim
  manifest is a single file both paths read from day one. Do not ship the
  registry path with its own list.

## Migration Plan

1. Single manifest; both existing paths read it. No behaviour change.
2. Writer identity and merge-to-`main` publication to the development registry,
   all twenty-eight distributions.
3. Remove publication from `publish-pypi.yml`.
4. Add the promotion script and its target, byte-verified and all-or-nothing.
5. Bump and promote `arkhai-kit-hosted-settlement` once its dependency resolves
   publicly, repairing the live breakage.
6. Substitute the inventory for the manifest when the format lands.

## Permanent Documentation Promotion

The publication and promotion model, the byte-conflict rule, and the removal
condition belong in `docs/development/RELEASING.md`. The distinction between a
product version and a distribution version belongs in
`openspec/specs/deployment-state/spec.md`; its cross-repository half belongs
with whatever owns promotion and is not this repository's to place. Registry
coordinates and credentials are never recorded in repository artifacts.
