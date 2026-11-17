# The local evidence kind

The `local` kind shows that the tree under validation builds and passes every suite on
this machine: the wheelhouse cleared, so every wheel tested is built from that tree
rather than left in `.dist` by another branch; then the packaging check; then every
unit and integration suite, run against the worktree as it stands. The functional
checks before an implementation, triage, or merge commit leave an attempt of this kind
for the tree they tested, so a commit made just after them usually finds its `local`
evidence present.

## Reading its evidence

Each attempt is a directory named by the UTC time it started,
`%Y%m%dT%H%M%S.%fZ`, so path order is time order and the last attempt is the
current one. It holds `summary.json`, JSON, and one log per step. The summary names
the `kind`, the `tree` it describes, the `commit` `HEAD` was as it started — which,
for an attempt the functional checks made before their commit, is the commit before
the one it describes: the tree is the identity — the `attempt`, each step's result,
duration, detail, and log, and whether it `passed`. As it ends, the kind prints the
summary as text, its first line `local evidence for the tree <the tree's first twelve
characters>, attempt <attempt>: PASSED`, or `FAILED`, then each step, and last the
attempt's path; one that could not start prints an `ERROR:` line instead and leaves
no attempt. While it runs it prints one line as each step starts, naming the step's
log, and one as it ends.

The steps are `tree before`; `dist-clean`, the wheelhouse cleared; `check-packaging`;
`test`, every suite; and `tree after`. The first step to fail ends the attempt, but
for `tree after`, and the tree is checked again after every step.

## Telling its failures apart

- **The worktree changed.** A step that fails with "the worktree changed", listing
  what the worktree holds against `HEAD`, means something wrote into the checkout
  while the kind ran, or `HEAD` moved ("HEAD is now …"). The attempt describes no one
  tree: it is neither the commit's failure nor the environment's, and validation
  stops, since the evidence no longer belongs to one commit.
- **A tree it was not given.** An attempt refused before anything ran, because the
  worktree holds another tree than the one it was asked to describe, kept no
  evidence; the gathering's own refusal of a worktree whose tree is not `HEAD`'s comes
  first.
- **The packaging check.** Its log names each check that failed: a stale lock, a
  version not bumped, a dependency edge the architecture forbids. Each is the
  commit's: validation never relocks, since a relock would hide the stale lock the
  check exists to report.
- **A suite.** Its log holds pytest's output: the failing test, its assertion, and
  the lines that show it. A test that fails on a timing, a port, or a daemon it
  reaches is diagnosed from its log like any failure before it is called
  environmental.

## Its section of the record

`## Local` is a table of each attempt's steps, with their results and durations:

```markdown
## Local

| Attempt | Step | Result | Duration |
|---|---|---|---|
```

Name the attempt by its directory, and say for an attempt validation found present
that it was left by the functional checks, when its summary's `commit` is not the
validated one.

## Its cleanup

None: its attempts are evidence, kept where Git ignores them, and no cluster or image
outlives them.

## In a plan

A section's verification names the suites it adds or extends, by level; this kind
runs them all, so a plan names no `local` evidence of its own.
