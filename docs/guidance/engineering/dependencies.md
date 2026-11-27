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

## A port is satisfied structurally

Where a lower component needs a fact a component beside it owns, it defines a port —
the operation it calls and the values it gets back — and the composition that wires
both supplies an implementation. The port is structural, the values it returns
included, so the implementing component answers it with types of its own and never
imports the port's owner. A concrete value type owned by the port's definer would
make every implementation import it, and reverse the edge the port removed.

For example, a scheduler that must not book a suspended account defines a standing
reader returning a value with one member, whether the account is suspended. The
billing component implements the reader with a record of its own carrying that member,
and the application that composes both hands billing's reader to the scheduler.
Neither component imports the other. Had the scheduler defined the returned record as
a concrete type, billing would import the scheduler to build one.

Nothing then checks that the implementation still fits the port when either changes,
so where no type checker relates the two, the composition root, which imports both,
holds a test that every member of the port's values is one the implementation's
values carry.
