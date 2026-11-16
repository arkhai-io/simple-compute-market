---
tags: [repository, testing]
---

# Testing the negotiation runtime

**Negotiation-runtime convention:** a shared runtime is tested once
([`test-seams.md`, "A shared runtime is tested once"](../../../docs/guidance/engineering/test-seams.md#a-shared-runtime-is-tested-once)).
Protocol invariants are tested once in
`kit/negotiation-runtime/tests/unit` with an in-memory recording repository and
injected opaque domain hooks. Those tests prove canonical-principal checks,
round and terminal ordering, transcript recovery, acceptance persistence, and
fail-before-effect behavior for recorded binding mismatches. Storefront tests
then prove only their domain adapters: term decoding, seller policy input,
accepted-artifact construction, and domain persistence/effect hooks. A domain
test must invoke `NegotiationRuntime`; reintroducing a local lifecycle helper
would test the duplication rather than the production composition.
