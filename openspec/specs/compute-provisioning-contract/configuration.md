---
tags: [repository, configuration]
---

# Compute provisioning contract configuration

What a deployment's parties must agree on to speak the
[compute provisioning contract](spec.md), a versioned contract as
[`versioning.md`](../../../docs/guidance/engineering/versioning.md) describes one.

The compute provisioning contract is at major 3, and every party accepts major 3
alone: a provisioning service, the storefronts that call it, and the family and
domain clients they use upgrade together and roll back together. A mismatched pair
does not half-work; each request is refused by its contract version, naming the
supported major.
