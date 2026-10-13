#!/usr/bin/env python3
"""Fail if a package imports an internal distribution it does not declare.

Rules (docs/development/ARCHITECTURE.md, "Repository layers"):

- ``undeclared_import``: an internal distribution the source imports and the
  ``pyproject.toml`` does not declare. Fails: the environment that resolves it
  transitively is the next one to break;
- ``unused_declaration``: an internal distribution declared and never imported,
  with no row in the declarations table of docs/development/ARCHITECTURE.toml
  giving the runtime reason. Warns, because a declaration may install a driver
  or an extension point's contributor; declaring a plugin needs no row;
- ``declaration_expiry``: a declarations row whose dependency is no longer
  declared, or is now imported. Fails.

Third-party distributions are not examined: mapping an import root to a
third-party distribution needs installed metadata this check does not have.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import architecture  # noqa: E402

GROUP = "dependencies"


def problems(root: Path = architecture.ROOT) -> list[str]:
    """The failing findings of this script's rules, rendered one per line."""
    model = architecture.build(root)
    found = architecture.problems(model, architecture.GROUPS[GROUP])
    return [f.render() for f in found if f.severity == "fail" and not f.excused_by]


if __name__ == "__main__":
    raise SystemExit(architecture.main(GROUP))
