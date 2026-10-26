"""The buyer stage a mechanism library supplies, and what the flows hand it.

The buy, negotiate, and settle flows name no mechanism: each step that differs
by mechanism is a method of the stage the accepted or selected option names.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any, Protocol

import typer
from core_buyer.buyer_config import ResolvedBuyerIdentity
from core_buyer.deal_helpers import open_run_log
from core_buyer.orchestration import make_publisher_trust_resolver
from core_buyer.orchestrator import BuyConfig, BuyResult, NegotiationResult
from core_buyer.run_log import RunLog
from core_buyer.settlement import BuyerSettlementPolicy
from market_settlement_runtime import MechanismRegistration, SettlementConfig
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from arkhai_api_buying import common
from arkhai_api_buying.contributions import BuyingContributions
from arkhai_api_buying.credentials import (
    CredentialStore,
    DeliveryRunLog,
    end_run,
    public_text,
    record_delivery,
)


class EscrowCodec(Protocol):
    """Encodes the buyer's escrow proposal and decodes the seller's accepted escrow payloads."""

    def encode_proposal(self, proposal: Any) -> dict[str, Any]: ...

    def decode_proposal(self, value: Any) -> Any: ...

    def decode_terms(self, value: Any) -> Any: ...


@dataclass(frozen=True)
class StageOption:
    """A command-line option a stage adds to one command; its value reaches the stage by ``name``."""

    command: str
    name: str
    flags: tuple[str, ...]
    annotation: Any
    help: str
    default: Any = None


StageOptions = Mapping[str, Any]
"""The values of every stage's options for one command, by option name."""


@dataclass(frozen=True)
class BuyRequest:
    """What a stage opens a buy with; ``enabled`` is whether the buyer enabled its mechanism."""

    identity: ResolvedBuyerIdentity
    settlement: BuyerSettlementPolicy
    policy: Any
    enabled: bool
    options: StageOptions
    assume_yes: bool
    console: Console


@dataclass(frozen=True)
class BuyRun:
    """The run a selected negotiation settles in."""

    config: BuyConfig
    quantity: int
    poll_interval: float
    settlement_timeout: float
    interactive: bool


class BuySession(Protocol):
    """One stage's part in one buy, opened for every stage whether its mechanism is enabled or not."""

    @property
    def available(self) -> bool: ...

    def prepare(self) -> None:
        """Resolve the stage's resources once registries are known; may prompt."""

    def missing(self) -> tuple[tuple[str, str], ...]:
        """The unset settings, as ``(name, configuration key)``, that leave it unavailable."""

    def scale_explicit_prices(self, initial: Any, maximum: Any) -> tuple[Any, Any]: ...

    def propose(self, listing: Mapping[str, Any], *, expiration_unix: int) -> Any | None: ...

    def run_fields(self) -> Mapping[str, Any]:
        """What the buy's run-log records of this stage; never a credential."""

    def header_rows(self) -> tuple[tuple[str, str], ...]: ...

    def settle(
        self,
        negotiation: NegotiationResult,
        on_event: Callable[[str, dict[str, Any]], None],
        run: BuyRun,
    ) -> BuyResult: ...


class BuyerStage(Protocol):
    """One mechanism's buyer stage, an entry of the plugin's stage table."""

    mechanism_id: str
    escrow_codec: EscrowCodec | None
    options: tuple[StageOption, ...]

    def registration(self) -> MechanismRegistration: ...

    def resources(self) -> dict[str, Any]: ...

    def chain_config_paths(self) -> Mapping[str, str | None]:
        """Per settlement chain, the configuration path the negotiation guards read this stage's payloads with."""

    def prepare_selection(
        self, selected: Any, *, listing: Any, settlement_policy: Any, policy: Any,
        options: StageOptions, assume_yes: bool, console: Console,
    ) -> Any: ...

    def accepted_entry(self, selected: Any) -> dict[str, Any] | None: ...

    def negotiation_prices(
        self, selected: Any, *, initial_price: Any, max_price: Any,
        initial_explicit: bool, max_explicit: bool, options: StageOptions,
    ) -> tuple[Any, Any]: ...

    def negotiation_run_fields(
        self, options: StageOptions, selected: Any | None,
    ) -> Mapping[str, Any]:
        """What a negotiation's run-log records of this stage, never a credential; ``selected`` when it was chosen."""

    def proposal(self, listing: Any, selected: Any) -> Any: ...

    def validate_acceptance(self, outcome: Any) -> None: ...

    def enrich(self, deal: Any) -> None: ...

    def listing_rows(self, listing: Mapping[str, Any]) -> tuple[tuple[str, str], ...]: ...

    def open_buy(self, request: BuyRequest) -> BuySession: ...

    def resume(self, resume: SettlementResume) -> dict[str, Any]: ...


@dataclass(frozen=True)
class SettlementResume:
    """A deal recovered from its run-log, and the steps every stage's resume shares."""

    contributions: BuyingContributions
    run_id: str
    deal: Any
    identity: ResolvedBuyerIdentity
    settlement_config: Callable[[], SettlementConfig]
    options: StageOptions
    poll_interval: float
    settlement_timeout: float
    console: Console
    credential_store: CredentialStore

    def open_log(self) -> DeliveryRunLog:
        log = DeliveryRunLog.of(open_run_log(
            self.run_id, signer=self.identity.signer, profile_id=self.identity.profile_id,
        ))
        log.event("settle_resumed")
        return log

    def trust_listing(self) -> dict[str, Any]:
        deal = self.deal
        return {
            "listing_id": deal.listing_id,
            "publisher_id": deal.publisher_id,
            "publisher_principals": deal.publisher_principals.model_dump(mode="json"),
            "storefront_url": deal.seller_url,
            "source_registry_url": deal.source_registry_url,
            "source_registry_authority": deal.source_registry_authority,
        }

    def buy_config(self) -> BuyConfig:
        registry_urls = common.resolve_indexer_urls()
        return BuyConfig.from_resolved_identity(
            identity=self.identity,
            registry_urls=registry_urls,
            registry_authorities=common.resolve_registry_authorities(registry_urls),
            discovery_timeout=common.resolve_discovery_timeout(),
            registry_api_keys=common.resolve_registry_api_keys(),
        )

    def seller_principals(self, log: RunLog, config: BuyConfig) -> Callable[..., Any]:
        return make_publisher_trust_resolver(
            config=config,
            listing=self.trust_listing(),
            on_update=lambda event, fields: log.event(event, **fields),
        )

    def show_header(self, *rows: tuple[str, str]) -> None:
        deal = self.deal
        header = Table.grid(padding=(0, 2))
        header.add_column(style="bold")
        header.add_column()
        header.add_row("Run ID", self.run_id)
        header.add_row("Seller", deal.seller_url)
        header.add_row("Negotiation", deal.negotiation_id)
        header.add_row("Agreed amount (total)", str(deal.agreed_amount))
        for label, value in rows:
            header.add_row(label, value)
        self.console.print(
            Panel(header, title=f"{self.contributions.command_path} settle", border_style="cyan")
        )

    def finish(
        self,
        log: DeliveryRunLog,
        final: dict[str, Any],
        *,
        reference: tuple[str, str],
        end_fields: Mapping[str, Any],
        unready_border: str,
    ) -> dict[str, Any]:
        """Keep any issued credential privately, record the terminal status, show both, and exit unless ready."""
        delivery = record_delivery(log, final.get("tenant_credentials"), self.credential_store)
        delivery = end_run(
            log,
            delivery,
            final.get("status") or "unknown",
            **end_fields,
            fulfillment_uid=final.get("fulfillment_uid"),
        )
        result = Table.grid(padding=(0, 2))
        result.add_column(style="bold")
        result.add_column()
        result.add_row("Status", str(final.get("status")))
        result.add_row(*reference)
        if final.get("fulfillment_uid"):
            result.add_row("Fulfillment UID", str(final["fulfillment_uid"]))
        if final.get("reason"):
            result.add_row("Reason", public_text(str(final["reason"]), log.secrets))
        border = "green" if final.get("status") == "ready" else unready_border
        self.console.print(Panel(result, title="Settlement complete", border_style=border))
        if delivery is not None:
            common.render_credentials(
                self.console, delivery,
                run_id=self.run_id, command_path=self.contributions.command_path,
            )
        if final.get("status") != "ready":
            raise typer.Exit(7)
        return final
