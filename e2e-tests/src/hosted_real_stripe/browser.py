"""Ephemeral Chromium automation for Stripe-hosted test Checkout."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable
from urllib.parse import urlsplit


class ChromiumUnavailable(RuntimeError):
    """Chromium or its protected automation dependency is unavailable."""


class CheckoutContractError(RuntimeError):
    """The real Checkout page did not expose or complete the test contract."""


@dataclass(frozen=True)
class StripeTestInputs:
    email: str = "arkhai-hosted-e2e@example.invalid"
    card_number: str = "4242424242424242"
    expiry: str = "12/34"
    cvc: str = "123"
    cardholder_name: str = "Arkhai Hosted E2E"
    postal_code: str = "94107"


class ChromiumCheckout:
    """Complete a hosted Checkout without screenshots, traces, or URL persistence."""

    def __init__(
        self,
        *,
        timeout_ms: int = 90_000,
        playwright_factory: Callable[[], Any] | None = None,
    ) -> None:
        self._timeout_ms = timeout_ms
        self._playwright_factory = playwright_factory

    def complete(self, checkout_url: str, inputs: StripeTestInputs | None = None) -> None:
        parsed = urlsplit(checkout_url)
        if parsed.scheme != "https" or parsed.hostname != "checkout.stripe.com":
            raise CheckoutContractError("buyer action is not a Stripe-hosted Checkout URL")
        test_inputs = inputs or StripeTestInputs()
        factory = self._playwright_factory or _load_playwright
        try:
            context_manager = factory()
            with context_manager as playwright:
                browser = playwright.chromium.launch(headless=True)
                try:
                    context = browser.new_context()
                    page = context.new_page()
                    page.set_default_timeout(self._timeout_ms)
                    page.goto(checkout_url, wait_until="domcontentloaded")
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
                    page.wait_for_url(
                        lambda url: urlsplit(str(url)).hostname != "checkout.stripe.com",
                        timeout=self._timeout_ms,
                        wait_until="domcontentloaded",
                    )
                finally:
                    browser.close()
        except CheckoutContractError:
            raise
        except Exception as exc:
            name = type(exc).__name__.lower()
            if "executable" in str(exc).lower() or "playwright" in name:
                raise ChromiumUnavailable("protected Chromium is unavailable") from exc
            raise CheckoutContractError("Stripe test Checkout did not complete") from exc


def _load_playwright() -> Any:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise ChromiumUnavailable("protected Chromium automation is unavailable") from exc
    return sync_playwright()


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
