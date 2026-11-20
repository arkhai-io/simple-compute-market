---
tags: [engineering, comments]
---

# Comments

What comments and documentation strings say, and what they never say. A comment is
read beside the code as it is, so it describes the system as it is.

## Comments describe the current system

Comments and documentation strings describe the current system, not the history of
how it came to be. They do not reference:

- previous file locations;
- the feature, migration, or review that introduced the code;
- tombstones or generated-artifact instructions;
- temporary implementation phases as though they were permanent rationale.

Temporary migration and changelog commentary is removed from production code. Say *why* the current invariant holds instead.

## What comments are for

Use comments, and documentation strings, to communicate local rationale:

- non-obvious invariants;
- safety and correctness constraints;
- reasons an apparently simpler implementation is invalid;
- lifecycle or concurrency assumptions;
- behaviour that cannot be made clear through naming and structure.

## State the rule locally

When broader context is needed, state the applicable rule locally and link to a
stable heading of a permanent document. A bare documentation pointer is not a
substitute for a useful local explanation.

Prefer:

```python
# A refund never exceeds the captured amount: the payment provider accepts an
# over-refund and settles it a day later, too late to reverse.
# See the payments specification, "Refund limits".
```
