"""Numerical payment disclosure supplied by the selected mechanism's owner."""

from collections.abc import Callable

from market_core.schemas import AgreedPrice, PriceBasis, SettlementOption, compute_rate_total
from pydantic import BaseModel, ConfigDict, Field


class PaymentPresentation(BaseModel):
    """Separate amounts in the quote's asset and minor-unit scale.

    Zero states that no such charge/reserve exists; None states that the owner
    cannot determine it. Reserve is reserved funds, not spend or a loss cap.
    """

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    quote: AgreedPrice
    setup_once: int | None = Field(ge=0, le=2**256 - 1)
    initial_reserve: int | None = Field(ge=0, le=2**256 - 1)


PaymentPresenter = Callable[[SettlementOption, int | None, AgreedPrice | None], PaymentPresentation]


def amount_rate_quote(
    option: SettlementOption, duration_seconds: int | None, basis: PriceBasis,
) -> AgreedPrice:
    """Shared advertised-rate arithmetic for mechanism owners that use truncation."""
    if basis.unit == "total" and duration_seconds is None:
        raise ValueError("reserved selections require an explicit duration (--duration-hours or --duration-seconds)")
    rates = option.price_rates
    if len(rates) != 1 or rates[0].field != "amount":
        raise ValueError("purchase pays only an amount rate; other priced fields are unsupported")
    seconds = basis.period_seconds if basis.unit == "per_period" else duration_seconds
    if seconds is None or seconds <= 0:
        raise ValueError("quote requires a positive term or billing period")
    return AgreedPrice(
        **basis.model_dump(), amount=compute_rate_total(rates[0], seconds), asset=option.price_asset,
    )
