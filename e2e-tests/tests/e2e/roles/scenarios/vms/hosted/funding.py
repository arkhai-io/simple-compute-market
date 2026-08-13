from __future__ import annotations

from dataclasses import dataclass
from typing import Literal
from urllib.parse import urlsplit

from .control import ReleasedControlCli, stable_operation_ref
from .driver import BuyerAction, FundingResult


@dataclass
class PrivateFundingDriver:
    """Funds a transient Checkout action through the released control CLI.

    The URL and its provider-facing Checkout reference exist only on the call
    stack. Neither is retained on the driver, DealState, report, or pytest output.
    """

    control: ReleasedControlCli
    event_action: Literal["withhold", "release", "duplicate", "reorder"] | None = None

    def fund(self, action: BuyerAction, *, operation_ref: str) -> FundingResult:
        checkout_ref = self._checkout_ref(action.url)
        self.control.checkout_transition(
            checkout_ref=checkout_ref,
            transition="fund",
            request_id=stable_operation_ref("request-fund", checkout_ref),
        )
        event_ref = f"event:checkout:{checkout_ref}:2:checkout.completed"
        if self.event_action is not None:
            self.control.event(
                action=self.event_action,
                event_refs=(event_ref,),
                request_id=stable_operation_ref(f"request-event-{self.event_action}", event_ref),
            )
        self.control.wait_state(
            resource_kind="checkout",
            resource_ref=checkout_ref,
            state="complete",
            request_id=stable_operation_ref("request-wait-funded", checkout_ref),
        )
        del checkout_ref, event_ref
        return FundingResult(funded=True)

    def expire(self, action: BuyerAction) -> None:
        checkout_ref = self._checkout_ref(action.url)
        self.control.checkout_transition(
            checkout_ref=checkout_ref,
            transition="expire",
            request_id=stable_operation_ref("request-expire", checkout_ref),
        )
        self.control.wait_state(
            resource_kind="checkout",
            resource_ref=checkout_ref,
            state="expired",
            request_id=stable_operation_ref("request-wait-expired", checkout_ref),
        )
        del checkout_ref

    @staticmethod
    def _checkout_ref(url: str) -> str:
        parsed = urlsplit(url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise AssertionError("hosted buyer action is not an absolute Checkout URL")
        checkout_ref = parsed.path.rstrip("/").rsplit("/", 1)[-1]
        if not checkout_ref:
            raise AssertionError("hosted buyer action has no Checkout reference")
        return checkout_ref
