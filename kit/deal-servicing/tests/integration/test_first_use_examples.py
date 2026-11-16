"""The kit's database-backed first-use examples stay runnable as documented.

``make -C kit/deal-servicing first-use`` runs each of these examples against its
own temporary database, created by the storefront chain's migration bodies, since
a session creates no table. Running each ``main`` here holds the examples to the
kit's schema and sessions as they are, rather than leaving a first use that only
fails when someone follows the instructions. The seller-preemption example, which
takes a lane profile, has its own test beside this one; the budget example, which
holds no database, is run by the unit suite.
"""

import asyncio
import runpy
from pathlib import Path

import pytest

EXAMPLES = Path(__file__).resolve().parents[2] / "examples"


@pytest.mark.parametrize("name", [
    "first_use", "end_first_use", "watch_first_use", "seller_first_use", "ingress_first_use",
    "routes_first_use", "respondent_first_use", "receipt_first_use",
])
def test_a_first_use_example_runs(name, capsys):
    example = runpy.run_path(str(EXAMPLES / f"{name}.py"), run_name=name)
    asyncio.run(example["main"]())
    assert capsys.readouterr().out
