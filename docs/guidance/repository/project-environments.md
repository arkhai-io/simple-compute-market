---
tags: [repository, packaging, uv]
---

# Project environments

How each Python project here gets its environment, and what its `Makefile` must
allow.

## The interpreter stays configurable

A project's own `Makefile` must keep its interpreter selection configurable so the
offline review environment can use the wheelhouse's declared Python version
([`TESTING.md`, "Offline Review Validation"](../../development/TESTING.md#offline-review-validation)).
