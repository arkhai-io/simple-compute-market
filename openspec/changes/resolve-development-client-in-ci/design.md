## Context

See proposal.md — Why.

The workflow already derives four values from the trust configuration — repository,
version, manifest filename, wheel filename — and hardcodes the rest. The Makefile now
derives all of them, so the pattern to follow already exists in this repository.

The client wheel resolves through `--find-links .dist` and every lockfile records it as
a path. Nothing about that has to change for CI to work: what CI lacks is the file, not
a way to name it.

## Goals / Non-Goals

**Goals:**

- A dev-pace workflow that can test against the version the repository pins, whether or
  not that version has been released.
- One place that decides which channel applies, derived rather than configured.

**Non-Goals:**

- Changing how anything resolves locally. A developer with `.dist` populated needs no
  credential, before or after.
- Weakening what release verification does where it still applies.

## Decisions

### D1. The pin and the trust configuration decide, together

The workflow compares the version the consumer pins with the version the trusted release
names. Equal means the pinned version is released: download the assets and verify them.
Different means the pin is ahead of the last signed release: take the wheel from the
internal index and verify nothing, because there is nothing to verify.

*Alternative considered:* a workflow input or repository variable selecting the channel.
Rejected — it is a third place stating which release is in play, and the first thing to
disagree with the other two. The pin and the trust configuration are already both in the
tree and already both authoritative.

*Alternative considered:* try the release download and fall back on failure. Rejected —
a network failure and an unreleased version would produce the same behaviour, so a
transient outage would silently downgrade a released version to an unattested wheel.

### D2. Fetch the wheel, do not change how it resolves

The internal path downloads the wheel into `.dist` and stops there. Lockfiles keep their
path source, local development is untouched, and the change is confined to the step that
puts a file on disk.

*Alternative considered:* declare the internal index in `pyproject.toml` as an explicit
index and pin the package to it, which is the documented direction for internal wheels.
Rejected for this change: it rewrites the source of that dependency in every lockfile
and makes a credential necessary for ordinary local work, to solve a problem that only
exists in CI. It remains the right eventual shape, for all the internal wheels at once.

### D3. An unreachable channel is a prerequisite, not a failure

Missing credentials produce a message naming the version and the channel, before any
resolution is attempted. A resolver error would name a wheel that does not exist
anywhere the job can see, which is true and useless.

This matters more than usual here, because the credential does not exist yet. Until the
federation is in place, every run of these two jobs takes this path, and what it says is
the whole of what a reader gets.

### D4. The release-pace workflow is left alone

`publish-pypi.yml` verifies the signed release before publishing, and should: it
publishes what consumers install. It keeps requiring a release because at that point one
is genuinely required.

## Risks / Trade-offs

- **CI cannot pass until the federation exists.** → It cannot pass now either, for the
  same underlying reason, and today it says so by failing to resolve a wheel. The change
  makes the two hosted jobs state what is missing. The other jobs are unaffected, and
  the wider CI failures that predate this are untouched either way.

- **A dev-pace suite now compiles against an artifact with no provenance.** → That is
  what a development version is, and the spec now says so rather than leaving it
  implied. Nothing that requires signed inputs accepts it, and the protected lane is
  unchanged.

- **The comparison is between a pin in one file and a version in another.** → Both are
  committed, both are read in the same step, and a disagreement is exactly the signal
  the comparison exists to detect.

## Migration Plan

The workflow change is inert while the pinned version and the trusted version agree: it
takes the same download-and-verify path it takes today. It only diverges once the pin
moves ahead, which it already has. Reverting is reverting the workflow file.
