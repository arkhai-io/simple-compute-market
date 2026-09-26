## ADDED Requirements

### Requirement: Kit-owned storefront shell

The storefront route set, executable assembly, health and system service, and
timer-loop lifecycle MUST be kit-owned and composed by every storefront domain. A
domain MUST contribute its codecs, per-route hooks, extra routes, and loop timings and
MUST NOT carry a controller, server, container, or loop runtime of its own. Every loop
a domain runs MUST be registered with the kit lifecycle so one pause holds it and one
control steps it.

#### Scenario: A domain storefront starts

- **WHEN** a storefront starts with one or more contributions installed
- **THEN** the kit composition root loads the frozen domain registry, mounts the shared
  routes and each contribution's extra routes, and runs every registered loop, and no
  contribution mounts a route set or runs a loop of its own

#### Scenario: A loop is paused and stepped

- **WHEN** an authenticated operator pauses the storefront and steps one loop
- **THEN** every registered loop holds, the stepped loop runs exactly the cycle its
  timer runs, and the behavior is the same for every domain
