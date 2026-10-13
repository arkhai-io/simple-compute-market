#!/usr/bin/env python3
"""Fail if a package depends outside its allowlist or a plugin is imported.

Rules (docs/development/ARCHITECTURE.md, "Kind"):

- ``kind_allowlist``: a ``contracts`` or ``client`` package depending on
  something its kind's allowlist in docs/development/ARCHITECTURE.toml does not
  name. Fails for a kind whose allowlist sets ``enforce = true`` and warns for
  the others;
- ``package_allowlist``: a package whose own ``pyproject.toml`` lists
  ``allowed-dependencies`` declaring or importing a distribution the list does
  not name, or importing a third-party distribution it does not declare. Fails;
- ``plugin_in_degree``: any package importing a plugin, a package that
  registers into a listed plugin entry-point group. Fails; declaring a plugin
  to install it is permitted.

An exception row excuses one finding of the rule it names and fails once it
excuses nothing.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import architecture  # noqa: E402

GROUP = "kinds"


def problems(root: Path = architecture.ROOT) -> list[str]:
    """The failing findings of this script's rules, rendered one per line."""
    model = architecture.build(root)
    found = architecture.problems(model, architecture.GROUPS[GROUP])
    return [f.render() for f in found if f.severity == "fail" and not f.excused_by]


if __name__ == "__main__":
    raise SystemExit(architecture.main(GROUP))
