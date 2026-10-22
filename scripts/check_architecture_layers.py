#!/usr/bin/env python3
"""Fail if a package depends upward, a layer has a cycle, or a project is misclassified.

Rules (docs/development/ARCHITECTURE.md, "Package and dependency layers"):

- ``unclassified``: a project whose path yields no layer, kind, and scope and
  that has no override row in docs/development/ARCHITECTURE.toml;
- ``layer``: a dependency, imported or declared, on a higher layer;
- ``cycle``: packages of one layer that depend on each other;
- ``layer_scope``: a scope its layer may not hold, such as a kit that knows a
  family or a mechanism other than its own;
- ``override_expiry``: an override row whose path now classifies the same, or
  that grants a mechanism none of the project's dependencies knows.

All fail. An exception row excuses one finding of the rule it names and fails
once it excuses nothing.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import architecture  # noqa: E402

GROUP = "layers"


def problems(root: Path = architecture.ROOT) -> list[str]:
    """The failing findings of this script's rules, rendered one per line."""
    model = architecture.build(root)
    found = architecture.problems(model, architecture.GROUPS[GROUP])
    return [f.render() for f in found if f.severity == "fail" and not f.excused_by]


if __name__ == "__main__":
    raise SystemExit(architecture.main(GROUP))
