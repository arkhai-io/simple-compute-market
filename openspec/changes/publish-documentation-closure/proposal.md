# Make the published documentation closure pinnable

## Why

The quickstart links to other documents, which link to others. A reader follows
all of them, so what they actually received is the transitive closure — and
nothing here can currently state what that closure was at a given revision.

Without it, two claims are impossible. Nobody can say which documentation a
reader had when something did not work for them, and nobody can tell whether a
documentation change altered what a reader receives, because a link target three
hops away can change with no visible edit to the entry document.

This is a documentation-integrity property. It happens to be a prerequisite for
testing documentation executability, but a reader reporting that the quickstart
does not work is already asking a question this repository cannot answer.

## What Changes

- Defines the entry documents whose closures are published.
- Computes the transitive closure of internal links from each entry document, and
  publishes it as a content-addressed manifest per revision.
- Fails when a closure member is missing, so a broken internal link is a build
  failure rather than a reader's discovery.
- Distinguishes internal links, which are closure members, from external links,
  which are recorded but not pinned.

## Permanent documentation impact

- [x] New subsystem specification — documentation closure
- [x] `docs/development/` contributor guidance

## Impact

- Affected code: `docs/`, documentation build
- Consumed by an external suite that must state exactly which bytes a reader
  received
