---
tags: [engineering, versioning]
---

# Versioning

How a package's version signals what changed, before and after 1.0.0, how a contract
that carries its own version changes, and how often a unit of work bumps a package.
The Python form of declaring compatible versions is
[Versioning Python](versioning-python.md).

## Semantic versioning

Each package follows Semantic Versioning (SemVer):

- **Major** — incompatible API change (e.g. removing a public function, changing a
  returned shape that consumers index into).
- **Minor** — new public API, backwards compatible.
- **Patch** — bug fix or internal change.

## Before 1.0.0

Before a package reaches 1.0.0 its major version stays at zero: an incompatible change
to anything the package publishes — its API, a wire format it sends or accepts, or the
meaning of a configuration key it reads — takes a **minor** bump in place of a major
one, and the other rules apply unchanged. Its users are expected to update; a consumer
that depends on the incompatible behaviour raises its lower bound to the new minor
version. Moving a package to 1.0.0 is a deliberate decision that sets its
compatibility commitment, not a consequence of shipping an incompatible change.

## A versioned contract is never changed in place

A contract that carries its own version — a versioned envelope's kind and schema
version, a contract version, a protocol identifier — is never changed in place, before
1.0.0 or after. An incompatible change defines a new version, and each party states
the versions it accepts and refuses the others, naming what it supports. Before 1.0.0
the release that introduces a version may stop accepting the one before, so the parties
to it upgrade, and roll back, together. Persisted state keeps its own migration rules.
Neither pre-1.0 allowance applies at or above 1.0.0.

## A field may be renamed or retired in stages

A field of a versioned contract may be renamed or retired without a new contract
version, in stages: one release's readers accept both forms, a later release's writers
switch, and a release after that removes the old form. This is a path for deprecating a
field, not a limit on how a contract may change: a field that changes meaning, or a
structure replaced by a richer one, is judged under the rules above on its own merits.

## Compatibility is owed to what has been deployed

Migration paths, compatibility shims and recovery machinery are built only for forms a
deployment has run: a kind of record, a message, a configuration key's use. A form
changed again before any deployment ran it affects no one, so it is revised with no
migration or deprecation and none is built ahead of it; a form a deployment does run
keeps the path the rules above give it.

The rule holds only against a named record of what has been deployed, such as a
release tag cut only once production runs the release. A project relaxing
compatibility under it names where that record is, and a design that leaves out a
migration or compatibility path under it names the release it read. Where no record is
named, or the record is unclear, everything released or published is treated as
deployed, and the release policy is settled with whoever decides releases before a
migration or compatibility path is designed or left out.

## The version numbers are the record

Incompatibility is signalled by the version numbers and the versioned contracts alone;
no per-release list of incompatible changes is kept.

## One bump per unit of work

A unit of work merged as one — a change, a pull request, a branch — bumps each package
it changes at most once, measured against the package's version on the branch it
merges into: that is the version a release sees. A package already bumped on the
work's branch is bumped again only when a later edit needs a larger bump than the one
it has, such as an incompatible edit to a package bumped only for a fix, and exact pins
on it move only with that bump. Bumping an unreleased version again changes nothing a
release sees and moves every exact pin on it for nothing.
