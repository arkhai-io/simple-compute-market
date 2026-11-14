---
tags: [engineering, dependencies]
---

# Dependencies

Whether a package is in the right place, what counts as depending on another, and
what a package declares. The forms these rules take in Python are
[Dependencies in Python](dependencies-python.md).

## Three questions place a package

Three questions decide whether a package is in the right place, and they are
independent:

- **Direction.** May this package depend on that one? A reusable capability must not
  depend on an application that composes it. A dependency graph answers it.
- **Knowledge.** May this package know about that product, customer, or integration?
  Code meant to be neutral must not learn a specific one by accident. A dependency
  graph answers it too.
- **Ownership.** Does this package hold the right responsibilities, even where every
  edge points a permitted way? A web handler that imports a billing library's
  internal pricing rule, or a shared library that reads one application's
  configuration file, passes the first two questions. This one is architectural
  judgement, and review answers it.

A change whose edges all point a permitted way has answered the first two questions,
not the third. Direction and knowledge can be stated as rules a check holds; ownership
is stated as placement tests that review applies.

## Any import is a dependency

Any import is an architectural dependency, wherever it sits and however it is
guarded: a "lazy" or "call-path" import does not soften the edge. If the edge is
wrong, move the code rather than defer the import. A boundary check therefore walks
every import, not only those at the top of a module.

## Declare what you import

A package declares every distribution it imports. An internal distribution declared
but never imported is removed, or kept for a stated runtime reason — an entry point,
a driver, an optional extra — recorded beside the declaration.
