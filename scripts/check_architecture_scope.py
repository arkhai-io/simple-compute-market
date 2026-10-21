#!/usr/bin/env python3
"""Fail if a package depends on, or names, something outside its scope.

Rules (docs/development/ARCHITECTURE.md, "Scope"):

- ``scope``: a dependency, imported or declared, whose scope is not a subset of
  the package's own; a composition's scope includes the mechanisms of what it
  composes;
- ``vocabulary``: a string literal that is a family's, domain's, or
  mechanism's identity outside the package's scope. Fails in the layers
  docs/development/ARCHITECTURE.toml lists under ``[vocabulary] fail_layers``
  and warns elsewhere, where a domain's own tokens are expected.

An exception row excuses one finding of the rule it names and fails once it
excuses nothing.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import architecture  # noqa: E402

GROUP = "scope"


def problems(root: Path = architecture.ROOT) -> list[str]:
    """The failing findings of this script's rules, rendered one per line."""
    model = architecture.build(root)
    found = architecture.problems(model, architecture.GROUPS[GROUP])
    return [f.render() for f in found if f.severity == "fail" and not f.excused_by]


if __name__ == "__main__":
    raise SystemExit(architecture.main(GROUP))
