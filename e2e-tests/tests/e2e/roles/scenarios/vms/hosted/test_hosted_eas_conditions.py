from __future__ import annotations

import pytest

from .cases import EAS_CONDITION_CASES
from .recovery import run_eas_condition_case

pytestmark = pytest.mark.e2e_hosted_settlement_eas


@pytest.mark.parametrize("case", EAS_CONDITION_CASES, ids=lambda case: case.name)
def test_local_anvil_eas_allowlisted_arbiter_condition_boundary(
    eas_condition_port,
    case,
) -> None:
    """Use simulator finance while testing only the EAS/arbiter condition seam."""

    assert run_eas_condition_case(eas_condition_port, case) == case.expected_condition_state
