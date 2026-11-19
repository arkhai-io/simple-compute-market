"""Try the installed mandate and exact escrow price boundaries without service I/O."""
from __future__ import annotations

import runpy
from pathlib import Path
from types import SimpleNamespace

from core_buyer.deal_helpers import exact_agreed_amount
from market_arkhai_payments import MandatePolicyError, PaymentSettlementData
from market_core.schemas import PriceBasis

ROOT = Path(__file__).resolve().parents[3]
fixture = runpy.run_path(str(ROOT / "kit/arkhai-payments/tests/payment_terms.py"))
amount = 2**100 + 1  # Within payments' 38-digit limit, beyond float precision.
agreement = fixture["agreement"](amount=str(amount))
data = PaymentSettlementData.for_agreement(agreement, fixture["config"]())
data.require_bound_to(agreement)
assert int(data.to_wire()["mandate"]["parts"][0]["amount"]) == amount
print("installed once mandate derives exact accepted money and re-verifies its binding: PASS")

deal = SimpleNamespace(agreement=agreement, agreed_amount=float(amount))
assert exact_agreed_amount(
    deal, project_billing=lambda _: PriceBasis(unit="total"),
) == amount
for projection, fragment in (
    (None, "requires a billing projection"),
    (lambda _: PriceBasis(unit="per_period", period="PT1M", period_seconds=60), "requires an accepted total"),
):
    try:
        exact_agreed_amount(deal, project_billing=projection)
    except ValueError as exc:
        assert fragment in str(exc), str(exc)
    else:
        raise AssertionError("escrow must refuse an unlabelled or recurring quote")
print("exact escrow recovery preserves uint256 precision and refuses missing/per-period projections: PASS")

changed = fixture["agreement"](amount="20000")
try:
    data.require_bound_to(changed)
except MandatePolicyError:
    pass
else:
    raise AssertionError("mandate accepted changed Agreement money")
rate = fixture["agreement"]()
rate["settlement"]["settlement"]["period"] = "PT1M"
try:
    PaymentSettlementData.for_agreement(rate, fixture["config"]())
except MandatePolicyError:
    pass
else:
    raise AssertionError("once adapter accepted unsupported recurring pricing")
print("changed Agreement money and unsupported hosted recurring mandate refused: PASS")

# Confirmation receives a total from the installed once mechanisms.
from io import StringIO
from rich.console import Console
from arkhai_vms_buyer import buy_cli

output = StringIO()
buy_cli.typer.confirm = lambda *args, **kwargs: False
assert not buy_cli._confirm_settlement_interactive(
    terms=SimpleNamespace(
        seller_url="https://seller.example", listing_id="listing", negotiation_id="negotiation",
        agreed_amount=5000000, duration_seconds=7200,
    ), listing={}, console=Console(file=output, width=120, color_system=None),
)
assert "5000000 (total, raw token units)" in output.getvalue()
assert "5000000 (raw token units)" in output.getvalue()
assert "10000000" not in output.getvalue()
print("two-hour confirmation displays accepted 5000000 total without scaling it again: PASS")
print("LIMIT: invocation-local fixture, no deployed service, approval or recurring execution")
