---
tags: [engineering, testing]
---

# Contract fixtures

A **contract fixture** is a pair of functions — a builder and a validator — that
define the canonical shape of a message at a package boundary. They are shared
between the producer's tests, which call the validator to assert real code emits the
agreed shape, and the consumer's tests, which call the builder to produce test inputs
of exactly that shape. When the boundary changes, both sides break at once, instead
of the consumer silently doubling a shape the producer no longer emits.

**When to add one:** a boundary earns a contract fixture when both its producer and
its consumer have unit or integration tests. A consumer-only test value with no
corresponding producer test stays a local inline value: a contract fixture without
producer-side enforcement documents an agreement nothing checks.

**The builder** constructs a minimal but complete canonical instance, with defaults
for every field so a test overrides only the fields it cares about. Non-deterministic
fields — timestamps, generated ids — get fixed sentinel values in the builder and
range or type assertions in the validator, never equality checks, which fail brittly
when an incidental field shifts.

**The validator** asserts structural and semantic constraints on a value produced by
real code: field presence, type, and any invariant the consumer depends on. It does
not check incidental fields the consumer ignores.

**Import direction flows from producer to consumer.** A fixture for a boundary inside
one package lives with that package's tests; a fixture for a boundary a separate,
higher-level package consumes ships inside the producer's own package, beside the
client it pairs with, so a consumer that installs the producer gets the fixture with
no further configuration.

**A producer with no tests yet** still gets its fixtures, with validators no test
calls yet: they document the contract and give a future producer test an immediate
hook. Each such validator says which test is expected to call it once the producer
gains coverage.

## Signed protocol messages come from the producer's fixture

Neither a test nor a diagnostic frames or signs a protocol message itself. Code that
frames and signs a message there is a second framing implementation nothing checks
against the producer. Each obtains a signed message from the producer's own fixture, which
uses the same framing function as the producer's verifier and is pinned by the
producer's published test vectors.
