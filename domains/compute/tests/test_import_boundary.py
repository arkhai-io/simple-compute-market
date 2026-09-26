"""The compute-family vocabulary sits beneath every compute domain.

It may use the standard library and the capability-shape foundation kit, and
nothing else: importing a compute domain would make one domain's vocabulary
depend on another's, and importing the market core would put compute
vocabulary where every market reads it.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src" / "arkhai_compute"
ALLOWED = {"arkhai_compute", "market_capability_shape"}


def test_imports_only_the_standard_library_and_the_shape_kit():
    violations = []
    for path in sorted(SRC.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            names = []
            if isinstance(node, ast.Import):
                names = [alias.name.split(".")[0] for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                names = [node.module.split(".")[0]]
            for name in names:
                if name not in sys.stdlib_module_names and name not in ALLOWED:
                    violations.append(f"{path.name}: imports {name}")
    assert not violations, violations
