"""Ephemeral Chromium automation for Stripe-hosted test Checkout."""

from __future__ import annotations

import os
import re
import time
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
    checkout_session_id: str | None
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

    def pay(
        self,
        checkout_url: str,
        *,
        outcome: CheckoutOutcome,
        funding_profile: str = "card.v1",
    ) -> BrowserPaymentResult:
        session_id = checkout_session_id(checkout_url)
        if funding_profile not in {"card.v1", "us_ach_debit.v1"}:
            raise CheckoutContractError("selected profile has no Checkout payment form")
        if funding_profile == "us_ach_debit.v1" and outcome != "success":
            raise CheckoutContractError("ACH Checkout supports only the protected success input")
        test_inputs = StripeTestInputs.for_outcome(outcome)
        factory = self._playwright_factory or _load_playwright
        try:
            with factory() as playwright:
                browser = playwright.chromium.launch(
                    headless=True,
                    env=_browser_environment(),
                )
                page: Any | None = None
                try:
                    context = browser.new_context()
                    page = context.new_page()
                    page.set_default_timeout(self._timeout_ms)
                    page.goto(checkout_url, wait_until="domcontentloaded")
                    _fill_optional(page, ("input[name='email']", "#email"), test_inputs.email)
                    if funding_profile == "card.v1":
                        page.locator("input[name='cardNumber'], #cardNumber").first.wait_for(
                            state="visible", timeout=self._timeout_ms
                        )
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
                    else:
                        _fill_ach(page, test_inputs)
                    submit = _first_visible(
                        page,
                        (
                            "button[data-testid='hosted-payment-submit-button']",
                            "button[type='submit']",
                        ),
                    )
                    if submit is None:
                        raise CheckoutContractError("Checkout submit action is unavailable")
                    _submit_checkout(page, submit, outcome)
                    if outcome == "authentication":
                        _complete_authentication(page, self._timeout_ms)
                    if outcome in {"decline", "insufficient_funds"}:
                        _wait_for_decline(page, self._timeout_ms)
                    else:
                        page.wait_for_timeout(min(5_000, self._timeout_ms))
                        _raise_if_interactive_captcha(page)
                except Exception:
                    if page is not None:
                        _raise_if_interactive_captcha(page)
                    raise
                finally:
                    browser.close()
        except (CheckoutContractError, ChromiumUnavailable):
            raise
        except Exception as exc:
            name = type(exc).__name__.lower()
            if "executable" in str(exc).lower() or "playwright" in name:
                raise ChromiumUnavailable("protected Chromium is unavailable") from exc
            raise CheckoutContractError(
                "Stripe test Checkout did not reach the selected outcome"
            ) from exc
        return BrowserPaymentResult(checkout_session_id=session_id, outcome=outcome)

    def confirm(self, action_url: str) -> BrowserPaymentResult:
        parsed = urlsplit(action_url)
        hostname = parsed.hostname or ""
        if parsed.scheme != "https" or not (
            hostname == "hooks.stripe.com" or hostname.endswith(".stripe.com")
        ):
            raise CheckoutContractError("confirmation is not a Stripe-hosted action")
        factory = self._playwright_factory or _load_playwright
        try:
            with factory() as playwright:
                browser = playwright.chromium.launch(
                    headless=True,
                    env=_browser_environment(),
                )
                try:
                    page = browser.new_context().new_page()
                    page.goto(action_url, wait_until="domcontentloaded", timeout=self._timeout_ms)
                    _complete_authentication(page, self._timeout_ms)
                    page.wait_for_timeout(min(5_000, self._timeout_ms))
                    _raise_if_interactive_captcha(page)
                finally:
                    browser.close()
        except (CheckoutContractError, ChromiumUnavailable):
            raise
        except Exception as exc:
            raise CheckoutContractError("Stripe confirmation action did not complete") from exc
        return BrowserPaymentResult(checkout_session_id=None, outcome="success")

    def complete_setup(
        self,
        action_url: str,
        *,
        funding_profile: str,
    ) -> BrowserPaymentResult:
        """Complete one protected setup-mode Checkout without retaining its URL."""

        session_id = checkout_session_id(action_url)
        if funding_profile not in {"card.v1", "us_ach_debit.v1"}:
            raise CheckoutContractError("selected profile has no saved instrument setup")
        test_inputs = StripeTestInputs.for_outcome("success")
        factory = self._playwright_factory or _load_playwright
        try:
            with factory() as playwright:
                browser = playwright.chromium.launch(
                    headless=True,
                    env=_browser_environment(),
                )
                try:
                    page = browser.new_context().new_page()
                    page.set_default_timeout(self._timeout_ms)
                    page.goto(action_url, wait_until="domcontentloaded")
                    _fill_optional(page, ("input[name='email']", "#email"), test_inputs.email)
                    if funding_profile == "card.v1":
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
                    else:
                        _fill_ach(page, test_inputs)
                    submit = _first_visible(
                        page,
                        (
                            "button[data-testid='hosted-payment-submit-button']",
                            "button[type='submit']",
                        ),
                    )
                    if submit is None:
                        raise CheckoutContractError("Checkout setup submit action is unavailable")
                    submit.click()
                    page.wait_for_timeout(min(5_000, self._timeout_ms))
                    _raise_if_interactive_captcha(page)
                finally:
                    browser.close()
        except (CheckoutContractError, ChromiumUnavailable):
            raise
        except Exception as exc:
            raise CheckoutContractError("Stripe test instrument setup did not complete") from exc
        return BrowserPaymentResult(checkout_session_id=session_id, outcome="success")


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

def _fill_ach(page: Any, test_inputs: StripeTestInputs) -> None:
    _fill_required(
        page,
        ("input[name='routingNumber']", "#routingNumber"),
        "110000000",
        "ACH routing number",
    )
    _fill_required(
        page,
        ("input[name='accountNumber']", "#accountNumber"),
        "000123456789",
        "ACH account number",
    )
    _fill_optional(
        page,
        ("input[name='billingName']", "#billingName"),
        test_inputs.cardholder_name,
    )
    mandate = _first_visible(
        page,
        (
            "input[name='mandateConsent']",
            "input[data-testid='mandate-consent-checkbox']",
        ),
    )
    if mandate is not None and not mandate.is_checked():
        mandate.check()


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


def _submit_checkout(page: Any, submit: Any, outcome: CheckoutOutcome) -> None:
    if outcome in {"decline", "insufficient_funds"}:
        submit.click()
        return
    bounds = submit.bounding_box()
    if bounds is None:
        raise CheckoutContractError("Checkout submit action is unavailable")
    page.mouse.click(
        bounds["x"] + bounds["width"] / 2,
        bounds["y"] + bounds["height"] / 2,
    )


def _interactive_captcha_visible(frame: Any) -> bool:
    host = urlsplit(str(getattr(frame, "url", ""))).hostname or ""
    if host != "hcaptcha.com" and not host.endswith(".hcaptcha.com"):
        return False
    try:
        return frame.locator("[aria-label='Verify Answers']").first.is_visible()
    except Exception:
        return False


def _raise_if_interactive_captcha(page: Any) -> None:
    if any(_interactive_captcha_visible(frame) for frame in page.frames):
        raise ChromiumUnavailable("Stripe Checkout requires an interactive CAPTCHA")


def _complete_authentication(
    page: Any,
    timeout_ms: int,
    *,
    monotonic: Callable[[], float] = time.monotonic,
) -> None:
    selectors = (
        "#test-source-authorize-3ds",
        "button[data-testid='test-source-authorize-3ds']",
        "button:has-text('Complete authentication')",
        "button:has-text('Complete')",
        "button:has-text('Authorize')",
    )
    deadline = monotonic() + timeout_ms / 1000
    while True:
        _raise_if_interactive_captcha(page)
        for frame in page.frames:
            for selector in selectors:
                locator = frame.locator(selector).first
                try:
                    if locator.is_visible():
                        locator.click()
                        return
                except Exception:
                    continue
        remaining_ms = (deadline - monotonic()) * 1000
        if remaining_ms <= 0:
            break
        page.wait_for_timeout(min(100, remaining_ms))
    raise CheckoutContractError("Stripe test authentication challenge was unavailable")
