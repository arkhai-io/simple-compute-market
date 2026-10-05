"""Print production branch candidates for the settlement closeout inventory.

This diagnostic is deliberately broader than concrete-ID greps. Its output
needs caller inspection: identity comparisons and carrier projections are not
settlement dispatch.
"""

import ast
import subprocess
from pathlib import Path

paths = subprocess.check_output(
    ["git", "ls-files", "core", "domains"], text=True
).splitlines()
excluded = {"tests", "examples", ".venv", "build", "__pycache__", "docs"}
count = 0
for name in paths:
    path = Path(name)
    if path.suffix != ".py" or excluded.intersection(path.parts) or not path.exists():
        continue
    source = path.read_text()
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if not isinstance(node, (ast.Compare, ast.If, ast.IfExp, ast.Match)):
            continue
        expression = node.test if isinstance(node, (ast.If, ast.IfExp)) else node
        segment = ast.get_source_segment(source, expression) or ""
        if any(term in segment for term in (
            "mechanism", "config_key", "accepted_escrow", "accepted_proposal",
            "escrow_proposal", "picked_entry", "chain_name", "settlement_data",
        )):
            count += 1
            print(f"{name}:{node.lineno}: {' '.join(segment.split())}")
print(f"candidate_branches={count}")

path = Path("domains/vms/buyer/negotiate_cli.py")
source = path.read_text()
for forbidden in (
    'config_key == "alkahest"', "picked_entry is None", "payer_selection(",
    "resolve_buyer_wallet(", "resolve_chain_settings(",
):
    print(f"vm_negotiate {forbidden!r} present={forbidden in source}")
for hook in ("prepare_selection", "accepted_entry", "negotiation_prices", "proposal"):
    print(f"vm_negotiate selected_stage.{hook} present={'selected_stage.' + hook in source}")
