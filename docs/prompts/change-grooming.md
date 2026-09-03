# Openspec change grooming session prompt

`AGENTS.md` and the documents it requires reading have very important context you should study.
* `docs/development/ARCHITECTURE.md`
* `openspec/README.md`

`ARCHITECTURE.md` contains the normative vocabulary. Several terms are
deliberately narrower than their ordinary meaning and it also lists
terms that must not reappear. Check it before naming anything.

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