"""Observe pricing pins through existing real-SQLite runtime scenarios."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from arkhai_vms_negotiation.amounts import has_rate_structure, rate_structure_digest
from core_storefront.models.negotiation_models import NegotiateContinueResponse
from market_storefront import negotiation_runtime


class PinObservation:
    def __init__(self):
        self.original = negotiation_runtime._build_response_artifacts
        self.identities = {}
        self.acceptances = 0

    def pytest_sessionstart(self, session):
        def observed(domain, acceptance, accepted, *args, **kwargs):
            artifacts = self.original(domain, acceptance, accepted, *args, **kwargs)
            if has_rate_structure(acceptance.listing_record):
                digest = rate_structure_digest(acceptance.listing_record)
                key = acceptance.negotiation_id
                assert self.identities.setdefault(key, digest) == digest
                assert artifacts["rate_structure_digest"] == digest
                wire = NegotiateContinueResponse(
                    action="accept" if accepted else "counter",
                    buyer_principal=acceptance.buyer_principal,
                    seller_principal=acceptance.seller_principal,
                    **artifacts,
                )
                decoded = type(wire).model_validate_json(wire.model_dump_json())
                assert decoded.rate_structure_digest == digest
                if accepted and acceptance.uses_scalar_amount:
                    assert decoded.pricing_pin == {
                        "multiplier": str(acceptance.agreed_amount), "rate_structure_digest": digest,
                    }
                    self.acceptances += 1
            return artifacts
        negotiation_runtime._build_response_artifacts = observed

    def pytest_sessionfinish(self, session, exitstatus):
        negotiation_runtime._build_response_artifacts = self.original


def main():
    # The driver's storefront checkout owns the fixture/runtime target.
    sys.path.insert(0, str(Path.cwd()))
    probe = PinObservation()
    result = pytest.main([
        "tests/integration/test_vm_multiplier.py",
        "tests/unit/test_sync_negotiation_seller_round_hook.py", "-q",
    ], plugins=[probe])
    assert result == 0, result
    assert probe.acceptances > 0
    print(f"real-SQLite opening/round/acceptance digest and HTTP carrier preservation: PASS ({probe.acceptances} acceptances)")
    print("LIMIT: runtime plus carrier check, not application HTTP, deployment, funding or E2E")


if __name__ == "__main__":
    main()
