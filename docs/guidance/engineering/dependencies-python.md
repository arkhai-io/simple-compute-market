---
tags: [engineering, dependencies, python]
---

# Dependencies in Python

The Python forms of [Dependencies](dependencies.md): which imports count, where they
are declared, and where an import is placed.

## Every import form counts

An import is a dependency at module level, inside a function, under
`TYPE_CHECKING`, or behind `try`/`except` ([Any import is a
dependency](dependencies.md#any-import-is-a-dependency)). A boundary check walks all
of them, and a contract moved across a boundary is checked for each of them,
`TYPE_CHECKING` imports included.

## Declared in `pyproject.toml`

A package declares each distribution it imports in its `pyproject.toml`
([Declare what you import](dependencies.md#declare-what-you-import)).

## Imports go at module level

Place each import a piece of work adds at module level, wherever safe. This is not a
blanket move: check each import the work actually added or touched for a real reason
to stay local first — a genuine circular import, verified by attempting the move and
reading the actual failure rather than by assuming, or a documented, deliberate
lazy-load reason, such as avoiding import cost for a rarely exercised code path —
and record that reason in a comment beside it. Check what the work added, not every
pre-existing local import in a file it touched: this is not a general-purpose
cleanup. Verify each move against the real test suite, not a syntax check alone,
since an import that succeeds at definition time does not show that no circular
dependency exists at call time.
