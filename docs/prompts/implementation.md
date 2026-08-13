# Implementation session prompt

This session we'll be working on the simple-compute-market project and
implementing `<change or section>`. `AGENTS.md` and the documents it
requires reading — `docs/development/ARCHITECTURE.md`,
`docs/development/TESTING.md`, `docs/development/DEPLOYMENT_AND_CONFIG.md`,
and `openspec/README.md` — have very important context you should study.

## Documentation and implementation workflow

Follow the repository documentation guidance in `AGENTS.md` and the
documents it references.

Use a discuss → plan → implement workflow:

1. During discussion, we will clarify any outstanding design decisions
   and weigh alternative implementation options in this chat. At the
   end of the design phase, update the active
   `openspec/changes/<change>/` documents and return a packaged
   fileset.
2. During planning, preserve existing completed tasks and append or
   amend the implementation plan. Identify the exact files affected
   by each accepted design decision. End the plan with the closeout
   task defined in `openspec/README.md#plan-closeout-requirements`.
   Update the active `openspec/changes/<change>/` documents and
   return a packaged fileset.
3. During implementation
   a. implement the plan.
   b. run tests covering all code changes.
   c. pause for design review if the plan premise is invalidated by
      discovered code.
   d. ensure production comments describe present intent, invariants,
      and constraints and reference only stable permanent documentation
      when broader context is required.
   e. when a mechanical rewrite touches many files — a rename, a move, a
      changed signature — audit what a text substitution cannot see:
      dynamic imports, names in configuration or manifests, entry points,
      re-exports a linter will remove as unused, and tests whose subject
      moved to a package their own project does not depend on.
   f. state a claim about the code and a claim about the documentation as
      separate claims. A permanent document asserting an invariant the code
      does not hold is a defect in the change, not a wording problem.

`openspec/changes` is the temporary proposal, discussion, planning, and
migration layer. Production code must not reference it — see
`AGENTS.md`'s "Documentation ownership" for the full breakdown of what
belongs where.

## Deliverables

When returning implementation artifacts, include only updated files in
a zip in the original directory structure of the provided repository.

State the baseline every fileset is measured against, and make each one
**cumulative from that baseline** unless asked for an increment. A fileset
assembled from "files I touched in this step" is not a fileset the baseline can
receive: a file changed two steps ago and not since is absent from it, while any
manifest entry pointing at that file is present. Announcing a fileset as
superseding an earlier one while assembling it that way will break the build.

Verify a fileset by applying it to a clean copy of the baseline and running the
build and test targets there — not by running them in the working tree, which
contains files the fileset may not carry. Two defects reached the repository
owner this way: a moved module absent from a fileset that still shipped its
manifest entry, and a test rewritten to import a package its own project does
not depend on, which passed only because the working environment had every
package installed.

A fileset should contain only paths version control would track. Deriving it by
diffing a working tree against a baseline picks up whatever that tree
accumulated, and a tree used for testing accumulates exactly the things that
resemble source: `*.egg-info/` from editable installs, `build/lib/` from wheel
builds, databases written by tests.

Represent a file requiring deletion by replacing its entire contents
with a single-line tombstone comment stating the reason, at the file's
original path:

```python
# TOMBSTONE: delete this file — <one-sentence reason>
```

Do not create a separate deletion manifest or a suffixed copy alongside
the original — one file, one mechanism. Tombstone references must not
remain in final production code or permanent documentation.

A tombstone is a pending deletion the recipient actions, so a later fileset
carrying the same tombstone restores it rather than the deletion. Run
`make prune-tombstones` after applying one. A binary file cannot carry a
tombstone comment; name those explicitly for deletion instead.

## Verification honesty

Report what was run, by the command the repository actually uses. Naming a test
path directly overrides the `testpaths` a package configures, so a suite can be
reported green when `make test` never collects it.

Distinguish a defect in the code from an absence in the session environment
before attributing a failure to either. A missing third-party package, an
uninstalled sibling project, or a stale installed wheel shadowing edited source
each produce failures that look like defects. Equally, do not assume
an environment limitation: don't assume native packages are unavailable before
checking if they are available from PyPi.

Where a claim cannot be verified in the session, say which claim and why, rather
than reporting the suites that did run and letting the gap pass silently.
