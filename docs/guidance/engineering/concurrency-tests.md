---
tags: [engineering, testing, persistence]
---

# Database-concurrency tests

Database-concurrency tests use independent sessions and connections against the same
database, establish transaction ownership through explicit synchronization at a
semantic persistence boundary, and assert final durable state. They never depend on
uncontrolled thread races, scheduler timing, or elapsed-time ordering. Synchronization
waits are bounded, so a lock regression fails rather than hangs. A test-only subclass
or adapter may pause a narrow persistence interface after a meaningful write;
production code exposes no test-only hook.
