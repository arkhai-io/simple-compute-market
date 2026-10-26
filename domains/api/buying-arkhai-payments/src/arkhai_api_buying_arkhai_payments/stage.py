"""The buyer's Arkhai payments stage: payer selection, mandate approval, and resumption."""

from __future__ import annotations

import json
from collections.abc import Callable, Iterable, Mapping
from dataclasses import replace
from typing import Any

import typer
from arkhai_api_buying.credentials import error_text
from arkhai_api_buying.stages import BuyRequest, BuyRun, SettlementResume
from market_arkhai_payments import ARKHAI_PAYMENTS_MECHANISM, create_arkhai_payments_registration
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from arkhai_api_buying_arkhai_payments.payments import (
    configured_payer_account,
    payment_selection_for_listing,
    settle_negotiation,
    settle_payment,
)


def _confirm_payment_interactive(
    *, mandate: Any, transaction_id: str, listing: dict, quantity: int, console: Console
) -> bool:
    """Show the validated Arkhai mandate before approving its payment."""
    table = Table.grid(padding=(0, 2))
    table.add_column(style="bold")
    table.add_column()
    table.add_row(
        "Seller",
        str(listing.get("storefront_url") or listing.get("seller_url") or ""),
    )
    table.add_row("Listing", str(listing.get("listing_id") or ""))
    table.add_row("Quantity", str(quantity))
    table.add_row("Transaction", transaction_id)
    console.print(Panel(table, title="Confirm Arkhai payment", border_style="yellow"))
    console.print(
        Panel(
            json.dumps(mandate.model_dump(mode="json", by_alias=True), indent=2),
            title="Validated mandate",
            border_style="dim",
        )
    )
    try:
        return typer.confirm("Approve this payment mandate?", default=True)
    except typer.Abort:
        return False


class PaymentBuySession:
    """The payments part of one buy; the payer account is read once, when payments is enabled."""

    def __init__(self, stage: PaymentBuyerStage, request: BuyRequest) -> None:
        self._stage = stage
        self._request = request
        self._payer_account = (
            stage.payer_account() if request.enabled else None
        )

    @property
    def available(self) -> bool:
        return self._request.enabled

    def prepare(self) -> None:
        pass

    def missing(self) -> tuple[tuple[str, str], ...]:
        return ()

    def scale_explicit_prices(
        self, initial: Any, maximum: Any, matches: Iterable[Mapping[str, Any]],
    ) -> tuple[Any, Any]:
        return initial, maximum

    def propose(self, listing: Mapping[str, Any], *, expiration_unix: int) -> Any | None:
        return payment_selection_for_listing(
            self._request.settlement,
            listing,
            expiration_unix=expiration_unix,
            payer_account=self._payer_account,
            prefer_payment=True,
        )

    def run_fields(self) -> Mapping[str, Any]:
        return {}

    def header_rows(self) -> tuple[tuple[str, str], ...]:
        return ()

    def settle(self, negotiation: Any, on_event: Any, run: BuyRun) -> Any:
        self._stage.validate_acceptance(negotiation.outcome)
        confirm = None
        if run.interactive:
            console = self._request.console

            def confirm(mandate, transaction_id):
                return _confirm_payment_interactive(
                    mandate=mandate, transaction_id=transaction_id,
                    listing=negotiation.match or {}, quantity=run.quantity, console=console,
                )

        return settle_negotiation(
            negotiation=negotiation,
            buyer=self._request.identity,
            buy_config=run.config,
            settlement_config=self._request.settlement.config,
            payer_account=self._payer_account,
            poll_interval=run.poll_interval,
            total_timeout=run.settlement_timeout,
            on_event=on_event,
            confirm_payment=confirm,
        )


class PaymentBuyerStage:
    """``payer_section`` is the buyer configuration table holding the payer account; ``load_config`` reads the buyer's configuration."""

    mechanism_id = ARKHAI_PAYMENTS_MECHANISM
    escrow_codec = None
    options = ()
    registration = staticmethod(create_arkhai_payments_registration)

    def __init__(
        self, payer_section: str, *, load_config: Callable[[], Mapping[str, Any]] | None = None,
    ) -> None:
        if not payer_section.strip():
            raise ValueError("payer_section must be non-empty")
        self.payer_section = payer_section
        self._load_config = load_config

    def payer_account(self) -> str:
        return configured_payer_account(self.payer_section, self._load_config)

    def resources(self) -> dict[str, Any]:
        return {}

    def chain_config_paths(self) -> Mapping[str, str | None]:
        return {}

    def negotiation_run_fields(self, options: Any, selected: Any | None) -> Mapping[str, Any]:
        return {}

    def prepare_selection(self, selected: Any, **_unused: Any) -> Any:
        return replace(selected, selection=selected.selection.model_copy(update={
            "params": {"payer_account": self.payer_account()},
        }))

    def accepted_entry(self, selected: Any) -> None:
        return None

    def negotiation_prices(
        self, selected: Any, *, initial_price: Any, max_price: Any, **_unused: Any,
    ) -> tuple[Any, Any]:
        return initial_price, max_price

    def proposal(self, listing: Any, selected: Any) -> Any:
        return selected.selection

    def validate_acceptance(self, outcome: Any) -> None:
        if not outcome.agreement or not outcome.agreement_bytes:
            raise ValueError("payment acceptance requires the exact Agreement")
        data = outcome.settlement_data
        if not isinstance(data, Mapping) or not data.get("mandate"):
            raise ValueError("payment acceptance requires its accepted mandate")

    def enrich(self, deal: Any) -> None:
        pass

    def listing_rows(self, listing: Mapping[str, Any]) -> tuple[tuple[str, str], ...]:
        return ()

    def open_buy(self, request: BuyRequest) -> PaymentBuySession:
        return PaymentBuySession(self, request)

    def resume(self, resume: SettlementResume) -> dict[str, Any]:
        """Approve the recovered Agreement's mandate, then ask the seller to issue and poll."""
        deal = resume.deal
        if not deal.agreement or not deal.agreement_bytes:
            typer.secho(
                "Run-log is missing the accepted Agreement required for payments.",
                err=True,
                fg=typer.colors.RED,
            )
            raise typer.Exit(2)
        log = resume.open_log()
        buy_config = resume.buy_config()
        resume.show_header()
        try:
            transaction, final = settle_payment(
                seller_url=deal.seller_url,
                listing=resume.trust_listing(),
                negotiation_id=deal.negotiation_id,
                buyer=resume.identity,
                buy_config=buy_config,
                settlement_config=resume.settlement_config(),
                payer_account=self.payer_account(),
                agreement=deal.agreement,
                agreement_bytes=deal.agreement_bytes,
                settlement_selection=deal.settlement_selection,
                settlement_data=deal.settlement_data,
                poll_interval=resume.poll_interval,
                total_timeout=resume.settlement_timeout,
                on_event=lambda event, body: log.event(event, **body),
            )
        except Exception as exc:
            reason = error_text(exc, log.secrets)
            log.event("settlement_failed", error=reason)
            log.end("error", error=reason)
            typer.secho(
                f"Payment settlement failed: {reason}", err=True, fg=typer.colors.RED
            )
            raise typer.Exit(5) from exc
        return resume.finish(
            log,
            final,
            reference=("Settlement ref", transaction),
            end_fields={"settlement_ref": transaction},
            unready_border="red",
        )
