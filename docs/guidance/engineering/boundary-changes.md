---
tags: [engineering, testing, dependencies]
---

# Boundary changes

Moving or renaming a contract at a package boundary needs more than relocated unit
tests. Validate:

- the package build and the contents of what it ships;
- typing markers and static type checks where the contract moved;
- the allowed dependency direction, every import counted, with the repository's
  architecture check, writing a package's own boundary test only for what that
  check cannot express, such as which module of a package may import what;
- old import removal, or an explicit, deliberate compatibility path;
- every changed consumer's unit and integration suites, not just the producer's;
- composition startup and duplicate-registration checks;
- deterministic, idempotent retry behaviour;
- observable lifecycle events, verified without arbitrary sleeps
  ([Deterministic tests](test-determinism.md)).
