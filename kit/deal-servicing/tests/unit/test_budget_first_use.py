"""The budget first-use example stays runnable as documented.

``make -C kit/deal-servicing first-use`` runs it; it holds no database, so its
test is a unit one, beside the integration tests of the examples that do.
"""

import asyncio
import runpy
from pathlib import Path

EXAMPLE = Path(__file__).resolve().parents[2] / "examples" / "budget_first_use.py"


def test_the_budget_first_use_warns_and_keeps_servicing(capsys):
    example = runpy.run_path(str(EXAMPLE), run_name="budget_first_use")
    asyncio.run(example["main"]())
    assert "both servicing cycles still run" in capsys.readouterr().out
