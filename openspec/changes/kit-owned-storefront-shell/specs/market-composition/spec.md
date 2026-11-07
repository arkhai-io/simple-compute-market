## ADDED Requirements

### Requirement: Kit-owned storefront shell

The storefront route set, executable assembly, and health and system service MUST be
kit-owned and composed by every storefront domain. A domain MUST contribute its codecs,
per-route hooks, extra routes, and loop timings and MUST NOT carry a controller,
server, container, or loop runtime of its own. The kit composition root MUST own the
storefront's loop controller and register every loop a contribution runs with it.

#### Scenario: A domain storefront starts

- **WHEN** a storefront starts with one or more contributions installed
- **THEN** the kit composition root loads the frozen domain registry, mounts the shared
  routes and each contribution's extra routes, and registers and runs every
  contribution's loops through its one loop controller, and no contribution mounts a
  route set or runs a loop of its own
