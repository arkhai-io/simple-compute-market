"""Ephemeral Chromium automation for Stripe-hosted test Checkout."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from typing import Any, Callable, Literal
from urllib.parse import urlsplit

CheckoutOutcome = Literal["success", "decline", "insufficient_funds", "authentication"]
_SESSION_ID = re.compile(r"(?:^|/)(cs_(?P<mode>test|live)_[A-Za-z0-9_]+)(?:$|[/?#])")
_SENSITIVE_ENV = re.compile(r"(?:STRIPE|WEBHOOK)", re.IGNORECASE)


class ChromiumUnavailable(RuntimeError):
    """Chromium or its protected automation dependency is unavailable."""


class CheckoutContractError(RuntimeError):
    """The real Checkout page did not expose or complete the selected contract."""


@dataclass(frozen=True)
class StripeTestInputs:
    email: str
    card_number: str
    expiry: str = "12/34"
    cvc: str = "123"
    cardholder_name: str = "Arkhai Hosted E2E"
    postal_code: str = "94107"

    @classmethod
    def for_outcome(cls, outcome: CheckoutOutcome) -> "StripeTestInputs":
        cards = {
            "success": "4242424242424242",
            "decline": "4000000000000002",
            "insufficient_funds": "4000000000009995",
            "authentication": "4000002500003155",
        }
        return cls(
            email=f"arkhai-{outcome.replace('_', '-')}@example.invalid",
            card_number=cards[outcome],
        )


@dataclass(frozen=True)
class BrowserPaymentResult:
    checkout_session_id: str
    outcome: CheckoutOutcome


class ChromiumCheckout:
    """Exercise Checkout without screenshots, traces, logs, or URL persistence."""

    def __init__(
        self,
        *,
        timeout_ms: int = 90_000,
        playwright_factory: Callable[[], Any] | None = None,
    ) -> None:
        self._timeout_ms = timeout_ms
        self._playwright_factory = playwright_factory

    def require_available(self) -> None:
        factory = self._playwright_factory or _load_playwright
        try:
            with factory() as playwright:
                browser = playwright.chromium.launch(
                    headless=True,
                    env=_browser_environment(),
                )
                browser.close()
        except ChromiumUnavailable:
            raise
        except Exception as exc:
            raise ChromiumUnavailable("protected Chromium is unavailable") from exc

    def pay(self, checkout_url: str, *, outcome: CheckoutOutcome) -> BrowserPaymentResult:
        session_id = checkout_session_id(checkout_url)
        test_inputs = StripeTestInputs.for_outcome(outcome)
        factory = self._playwright_factory or _load_playwright
        try:
            with factory() as playwright:
                browser = playwright.chromium.launch(
                    headless=True,
                    env=_browser_environment(),
                )
                try:
                    context = browser.new_context()
                    page = context.new_page()
                    page.set_default_timeout(self._timeout_ms)
                    page.goto(checkout_url, wait_until="domcontentloaded")
                    page.locator("input[name='cardNumber'], #cardNumber").first.wait_for(
                        state="visible", timeout=self._timeout_ms
                    )
                    _fill_optional(page, ("input[name='email']", "#email"), test_inputs.email)
                    _fill_required(
                        page,
                        ("input[name='cardNumber']", "#cardNumber"),
                        test_inputs.card_number,
                        "card number",
                    )
                    _fill_required(
                        page,
                        ("input[name='cardExpiry']", "#cardExpiry"),
                        test_inputs.expiry,
                        "card expiry",
                    )
                    _fill_required(
                        page,
                        ("input[name='cardCvc']", "#cardCvc"),
                        test_inputs.cvc,
                        "card CVC",
                    )
                    _fill_optional(
                        page,
                        ("input[name='billingName']", "#billingName"),
                        test_inputs.cardholder_name,
                    )
                    _fill_optional(
                        page,
                        ("input[name='postalCode']", "#billingPostalCode"),
                        test_inputs.postal_code,
                    )
                    _disable_optional_save_details(page)
                    submit = _first_visible(
                        page,
                        (
                            "button[data-testid='hosted-payment-submit-button']",
                            "button[type='submit']",
                        ),
                    )
                    if submit is None:
                        raise CheckoutContractError("Checkout submit action is unavailable")
                    submit.click()
                    if outcome == "authentication":
                        _complete_authentication(page, self._timeout_ms)
                    if outcome in {"decline", "insufficient_funds"}:
                        _wait_for_decline(page, self._timeout_ms)
                    else:
                        page.wait_for_url(
                            lambda url: urlsplit(str(url)).hostname != "checkout.stripe.com",
                            timeout=self._timeout_ms,
                            wait_until="commit",
                        )
                finally:
                    browser.close()
        except CheckoutContractError:
            raise
        except Exception as exc:
            name = type(exc).__name__.lower()
            if "executable" in str(exc).lower() or "playwright" in name:
                raise ChromiumUnavailable("protected Chromium is unavailable") from exc
            raise CheckoutContractError(
                "Stripe test Checkout did not reach the selected outcome"
            ) from exc
        return BrowserPaymentResult(checkout_session_id=session_id, outcome=outcome)


def checkout_session_id(checkout_url: str) -> str:
    parsed = urlsplit(checkout_url)
    if parsed.scheme != "https" or parsed.hostname != "checkout.stripe.com":
        raise CheckoutContractError("buyer action is not a Stripe-hosted Checkout URL")
    match = _SESSION_ID.search(parsed.path)
    if match is None:
        raise CheckoutContractError("Checkout action has no exact session identity")
    if match.group("mode") != "test":
        raise CheckoutContractError("live Checkout actions are prohibited")
    return match.group(1)


def _load_playwright() -> Any:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise ChromiumUnavailable("protected Chromium automation is unavailable") from exc
    return sync_playwright()


def _browser_environment() -> dict[str, str]:
    return {key: value for key, value in os.environ.items() if not _SENSITIVE_ENV.search(key)}


def _first_visible(page: Any, selectors: tuple[str, ...]) -> Any | None:
    for selector in selectors:
        locator = page.locator(selector).first
        try:
            if locator.is_visible():
                return locator
        except Exception:
            continue
    return None


def _fill_required(page: Any, selectors: tuple[str, ...], value: str, name: str) -> None:
    locator = _first_visible(page, selectors)
    if locator is None:
        raise CheckoutContractError(f"Checkout {name} field is unavailable")
    locator.fill(value)


def _fill_optional(page: Any, selectors: tuple[str, ...], value: str) -> None:
    locator = _first_visible(page, selectors)
    if locator is not None:
        locator.fill(value)


def _disable_optional_save_details(page: Any) -> None:
    save_details = _first_visible(page, ("#enableStripePass",))
    if save_details is not None and save_details.is_checked():
        save_details.uncheck()


def _wait_for_decline(page: Any, timeout_ms: int) -> None:
    error = page.locator("[role='alert'], [data-testid='payment-error'], .Error").first
    try:
        error.wait_for(state="visible", timeout=timeout_ms)
    except Exception as exc:
        raise CheckoutContractError(
            "Stripe Checkout did not expose the documented decline"
        ) from exc
    if urlsplit(str(page.url)).hostname != "checkout.stripe.com":
        raise CheckoutContractError("declined Checkout unexpectedly completed")


def _complete_authentication(page: Any, timeout_ms: int) -> None:
    selectors = (
        "#test-source-authorize-3ds",
        "button[data-testid='test-source-authorize-3ds']",
        "button:has-text('Complete authentication')",
    )
    for frame in page.frames:
        for selector in selectors:
            locator = frame.locator(selector).first
            try:
                locator.wait_for(state="visible", timeout=timeout_ms)
                locator.click()
                return
            except Exception:
                continue
    raise CheckoutContractError("Stripe test authentication challenge was unavailable")
