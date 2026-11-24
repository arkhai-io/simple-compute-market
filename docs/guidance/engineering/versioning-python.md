---
tags: [engineering, versioning, python]
---

# Versioning Python

The Python form of declaring which versions of another package a package is
compatible with ([Versioning](versioning.md)).

## Compatibility is declared by lower bounds

Cross-package compatibility is enforced by the dependency constraints in
`pyproject.toml`. Use `>=X.Y` (a lower bound) for forward compatibility, or
`>=X.Y,<X+1` when a breaking major release is anticipated.
