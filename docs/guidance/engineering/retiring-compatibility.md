---
tags: [engineering, versioning]
---

# Retiring compatibility

How code that exists only for older deployments is added together with its end,
recorded where releases are decided, and removed. Which deployments are owed
compatibility at all is
[Versioning, "Compatibility is owed to what has been deployed"](versioning.md#compatibility-is-owed-to-what-has-been-deployed);
how a stored form stays readable while it is retained is
[Persistence, "A retained record stays readable"](persistence.md#a-retained-record-stays-readable).

## What a compatibility path is

A compatibility path is code, configuration, or documentation that exists only
because a deployment may still hold an older form: a reader of a stored
representation no writer produces any longer, an upgrade branch that adopts
records an older release wrote, a fallback accepting an older wire form or
configuration key, a refusal naming a retired setting's replacement, a stage of
a staged rename. Code serving the forms current releases write is not one,
however old it is. The tests and fixtures that hold a path are part of it.

## Every path is added with its retirement

The unit of work that adds a compatibility path states, in the same unit of
work, when the path retires. The statement names:

- **what retires**: the code, its tests and fixtures, the configuration only it
  reads, and every document describing it;
- **when**: a release, counted from the release that first carries the path,
  such as "the second release after the one that first carries it", or a named
  version together with that count, whichever is later, so a renumbered release
  does not strand it. A condition that cannot be checked when a release is
  prepared, such as "once nothing uses it", is not a retirement;
- **what a deployment still holding the old form meets afterwards**: a refusal
  naming the form and how to recover, or the path's strict successor, never the
  old form silently read as something else;
- **how an operator learns, before then, whether a deployment still holds the old
  form**, where the service can tell: a status or readiness report naming what
  remains.

A path whose retirement cannot be stated is a design question, not a
compatibility path: settle what the system does for that form permanently and
write it as current behaviour.

## Retirements are recorded where releases are decided

A repository keeps one list of pending retirements, read by whoever prepares a
release. The unit of work adding a path adds its row; the one retiring it removes
the row. The list holds only what is pending: what retired is recorded by the
version numbers ([Versioning, "The version numbers are the record"](versioning.md#the-version-numbers-are-the-record)).
A comment does not carry the schedule, because a comment describes the code as it
is, and a date in one is a plan that no release step reads.

## A retirement falls due

Preparing a release, each row due at it is retired before the release candidate
is taken, or moved to a later release with its reason recorded on the row. No row
is left silently past its release. A row moved a second time is reconsidered:
either the path serves a form that is in fact still current, and is rewritten as
current behaviour, or its retirement depended on something that cannot be
observed, and is restated.

## Retiring removes everything the path carried

A retirement removes, in one unit of work, the path's code, its tests and
fixtures, the configuration keys only it read, and every document describing it,
and bumps each package it changes as an incompatible change, which it is for a
deployment still holding the old form ([Versioning](versioning.md)). A path is not
due while removing it would leave a deployment without the recovery its row
names.

## A staged change names each stage's release

A field renamed or retired in stages
([Versioning, "A field may be renamed or retired in stages"](versioning.md#a-field-may-be-renamed-or-retired-in-stages))
names the release of each later stage when its first stage lands, and each later
stage is a row.
