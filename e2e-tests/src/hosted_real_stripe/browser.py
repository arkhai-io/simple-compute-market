"""Ephemeral Chromium automation for Stripe-hosted test Checkout."""

from __future__ import annotations

import os
import re
import sys
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
        retain_diagnostics: bool = False,
        headless: bool = True,
        attended: bool = False,
    ) -> None:
        self._timeout_ms = timeout_ms
        self._playwright_factory = playwright_factory
        self._retain_diagnostics = retain_diagnostics
        # A headless browser is itself the signal the provider answers with a
        # CAPTCHA. A development run on a machine with a display may show the
        # window instead; nothing else about the run changes.
        self._headless = headless
        # Whether someone is at the window. A visible browser is not the same
        # claim: it says the page can be seen, not that anyone is watching it.
        # Only this decides whether a CAPTCHA is a dead end or a pause.
        self._attended = attended

    def require_available(self) -> None:
        factory = self._playwright_factory or _load_playwright
        try:
            with factory() as playwright:
                browser = playwright.chromium.launch(
                    headless=self._headless,
                    env=_browser_environment(),
                    proxy=_browser_proxy(),
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
                    headless=self._headless,
                    env=_browser_environment(),
                    proxy=_browser_proxy(),
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
                            diagnose=self._retain_diagnostics,
                        )
                        _fill_required(
                            page,
                            ("input[name='cardExpiry']", "#cardExpiry"),
                            test_inputs.expiry,
                            "card expiry",
                            diagnose=self._retain_diagnostics,
                        )
                        _fill_required(
                            page,
                            ("input[name='cardCvc']", "#cardCvc"),
                            test_inputs.cvc,
                            "card CVC",
                            diagnose=self._retain_diagnostics,
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
                        _fill_ach(
                            page,
                            test_inputs,
                            diagnose=self._retain_diagnostics,
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
                    _submit_checkout(page, submit, outcome)
                    if outcome == "authentication":
                        _complete_authentication(
                            page,
                            self._timeout_ms,
                            attended=self._attended,
                            diagnose=self._retain_diagnostics,
                        )
                    if outcome in {"decline", "insufficient_funds"}:
                        # These outcomes succeed by Checkout refusing and
                        # staying put, so leaving would be the wrong signal.
                        _wait_for_decline(page, self._timeout_ms)
                    else:
                        _await_checkout_left(
                            page,
                            timeout_ms=max(self._timeout_ms, _SETUP_SUBMIT_TIMEOUT_MS),
                            diagnose=self._retain_diagnostics,
                            subject="payment",
                            attended=self._attended,
                        )
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
                    headless=self._headless,
                    env=_browser_environment(),
                    proxy=_browser_proxy(),
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
                    headless=self._headless,
                    env=_browser_environment(),
                    proxy=_browser_proxy(),
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
                            diagnose=self._retain_diagnostics,
                        )
                        _fill_required(
                            page,
                            ("input[name='cardExpiry']", "#cardExpiry"),
                            test_inputs.expiry,
                            "card expiry",
                            diagnose=self._retain_diagnostics,
                        )
                        _fill_required(
                            page,
                            ("input[name='cardCvc']", "#cardCvc"),
                            test_inputs.cvc,
                            "card CVC",
                            diagnose=self._retain_diagnostics,
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
                        _fill_ach(
                            page,
                            test_inputs,
                            diagnose=self._retain_diagnostics,
                        )
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
                    _await_checkout_left(
                        page,
                        timeout_ms=min(_SETUP_SUBMIT_TIMEOUT_MS, self._timeout_ms),
                        diagnose=self._retain_diagnostics,
                    )
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


#: Loopback is never proxied. The staged marketplace, the authority, and the
#: webhook forwarder are all loopback, and routing them through a proxy would
#: break a run that reaches them directly today.
_NEVER_PROXIED = ("localhost", "127.0.0.1", "::1")


def _browser_proxy() -> dict[str, str] | None:
    """The proxy this run reaches the provider through, if it has one.

    Chromium does not read ``HTTP_PROXY``/``HTTPS_PROXY``; it takes a proxy as a
    launch argument or from system configuration. Passing what the rest of the
    run already uses keeps one answer to how this run reaches the internet, and
    keeps a machine whose egress is a proxy from loading a Checkout page that
    mounts no form and failing three steps later as a funding timeout.

    ``ALL_PROXY`` is deliberately not consulted. It is a SOCKS endpoint here,
    and the run's own HTTP client cannot use one without an optional dependency
    it does not install -- so honouring it would let the browser reach the
    provider by a route nothing else in the run could.
    """

    server = os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy")
    server = server or os.environ.get("HTTP_PROXY") or os.environ.get("http_proxy")
    if not server:
        return None
    bypass = [
        item.strip()
        for item in (os.environ.get("NO_PROXY") or os.environ.get("no_proxy") or "").split(",")
        if item.strip()
    ]
    for host in _NEVER_PROXIED:
        if host not in bypass:
            bypass.append(host)
    return {"server": server, "bypass": ",".join(bypass)}


#: How long a hosted Checkout page may take to mount the form this run has to
#: fill. Long enough for a slow render, short enough that a page which will
#: never present the field says so while an operator is still watching.
_FORM_MOUNT_TIMEOUT_MS = 20_000


def _first_visible(
    page: Any, selectors: tuple[str, ...], *, wait_ms: int = 0
) -> Any | None:
    # Checkout mounts its form after the document is ready, so a field this run
    # requires is worth waiting for rather than probing once. A field it merely
    # accepts is not: an immediate probe keeps an absent optional field free.
    if wait_ms > 0:
        try:
            page.wait_for_selector(
                ", ".join(selectors), state="visible", timeout=wait_ms
            )
        except Exception:  # noqa: BLE001 - absence is the caller's to report
            pass
    for selector in selectors:
        locator = page.locator(selector).first
        try:
            if locator.is_visible():
                return locator
        except Exception:
            continue
    return None


def _fill_required(
    page: Any,
    selectors: tuple[str, ...],
    value: str,
    name: str,
    *,
    diagnose: bool = False,
    wait_ms: int = _FORM_MOUNT_TIMEOUT_MS,
) -> None:
    locator = _first_visible(page, selectors, wait_ms=wait_ms)
    if locator is None:
        raise CheckoutContractError(
            f"Checkout {name} field is unavailable"
            + (_offered_inputs(page) if diagnose else "")
        )
    locator.fill(value)


def _offered_inputs(page: Any) -> str:
    """Name the input fields the page did offer, for a development run only.

    A missing field says only that the page is not what the automation
    expected. Which fields it does present is the diagnosis. Field names are
    the page's own public form structure -- never a value typed into one.
    """

    try:
        offered = page.eval_on_selector_all(
            "input:not([type='hidden']), button, iframe",
            "nodes => nodes.map(n => n.tagName.toLowerCase() + ':' + "
            "(n.name || n.id || n.getAttribute('data-testid') || n.type || ''))",
        )
    except Exception as exc:  # noqa: BLE001 - a diagnostic must not mask its subject
        return f"; the page could not be inspected ({type(exc).__name__})"
    if not isinstance(offered, list) or not offered:
        return "; the page offered no form controls"
    return "; the page offered " + ", ".join(sorted({str(item) for item in offered})[:25])


def _fill_optional(page: Any, selectors: tuple[str, ...], value: str) -> None:
    locator = _first_visible(page, selectors)
    if locator is not None:
        locator.fill(value)

def _fill_ach(
    page: Any, test_inputs: StripeTestInputs, *, diagnose: bool = False
) -> None:
    _fill_required(
        page,
        ("input[name='routingNumber']", "#routingNumber"),
        "110000000",
        "ACH routing number",
        diagnose=diagnose,
    )
    _fill_required(
        page,
        ("input[name='accountNumber']", "#accountNumber"),
        "000123456789",
        "ACH account number",
        diagnose=diagnose,
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


#: How long Checkout may take to accept a submitted setup form and redirect.
_SETUP_SUBMIT_TIMEOUT_MS = 30_000


def _await_checkout_left(
    page: Any,
    *,
    timeout_ms: int,
    diagnose: bool,
    subject: str = "setup",
    attended: bool = False,
) -> None:
    """Refuse to call a submission complete until Checkout says it is.

    The submit click is not the outcome. Checkout redirects to the configured
    success URL once the intent is confirmed, and stays where it is otherwise --
    so waiting for the page to leave is the only in-browser signal that
    separates a completed submission from a form that was silently rejected.
    This holds for a payment exactly as it does for a setup: a lane that
    returns success from a page that accepted nothing fails minutes later as a
    funding timeout, naming neither the page nor what it did there.
    """

    for attempt in (0, 1):
        try:
            page.wait_for_url(
                lambda url: "checkout.stripe.com" not in str(url),
                timeout=timeout_ms,
            )
            return
        except Exception:  # noqa: BLE001 - the page is the subject, not the error
            # A challenge answered by hand is not a submission that failed: the
            # page was held, not refused, so the wait is worth one more turn.
            if attempt == 0 and _settle_interactive_captcha(page, attended=attended):
                continue
            raise CheckoutContractError(
                f"Checkout did not accept the submitted {subject} form"
                + (_page_complaint(page) if diagnose else "")
            ) from None


def _page_complaint(page: Any) -> str:
    """Quote what the page says is wrong, for a development run only.

    This is the provider's own public validation text about input this harness
    typed. Never a value, never a session, and never in a protected run.
    """

    try:
        messages = page.eval_on_selector_all(
            "[role='alert'], .Error, [data-testid*='error']",
            "nodes => nodes.map(n => (n.innerText || '').trim()).filter(Boolean)",
        )
    except Exception:  # noqa: BLE001 - a diagnostic must not mask its subject
        return ""
    if not isinstance(messages, list) or not messages:
        return "; the page reported nothing"
    joined = " | ".join(sorted({str(item) for item in messages}))
    return "; the page said " + joined[:300]


def _offered_controls(page: Any) -> str:
    """Name what the page was offering, for a development run only.

    A control that is not found is either absent or renamed, and the error
    alone cannot separate those: a challenge that never appeared and one whose
    button Stripe relabelled both read as `unavailable`. Labels are the
    provider's own public button text -- no value, no session, and never in a
    protected run.
    """

    script = (
        "nodes => nodes.filter(n => n.getClientRects().length > 0"
        " && getComputedStyle(n).visibility !== 'hidden')"
        ".map(n => (n.innerText || n.value || '').trim().replace(/\\s+/g, ' '))"
        ".filter(Boolean)"
    )
    labels: list[str] = []
    try:
        frames = list(page.frames)
    except Exception:  # noqa: BLE001 - a diagnostic must not mask its subject
        return ""
    for frame in frames:
        try:
            found = frame.eval_on_selector_all(
                "button, input[type='submit'], [role='button']", script
            )
        except Exception:  # noqa: BLE001 - one unreachable frame is not the answer
            continue
        if isinstance(found, list):
            labels.extend(str(item)[:40] for item in found)
    if not labels:
        return "; the page offered no controls"
    return "; the page offered " + " | ".join(sorted(set(labels)))[:300]


def _interactive_captcha_visible(frame: Any) -> bool:
    """Whether a challenge is on the screen, asked from the side that knows.

    The challenge frame is loaded on every submitted Checkout whether or not
    anyone is being asked to answer it. hCaptcha builds it, button and all,
    and hides it in the *parent* document. A frame cannot see that: inside it
    the button is laid out and unhidden, so asking the frame about its own
    contents gets `visible` back from a page that is showing nothing -- which
    is how the authentication lane came to report an interactive CAPTCHA on
    runs where a person watching the window saw an ordinary Checkout.

    So the hosting iframe is what gets asked, and being parked off-screen
    counts as hidden however the page spells it.
    """

    host = urlsplit(str(getattr(frame, "url", ""))).hostname or ""
    if host != "hcaptcha.com" and not host.endswith(".hcaptcha.com"):
        return False
    try:
        if not frame.locator("[aria-label='Verify Answers']").first.is_visible():
            return False
        element = frame.frame_element()
        if not element.is_visible():
            return False
        box = element.bounding_box()
    except Exception:
        return False
    return (
        box is not None
        and box["width"] > 0
        and box["height"] > 0
        and box["x"] + box["width"] > 0
        and box["y"] + box["height"] > 0
    )


def _raise_if_interactive_captcha(page: Any) -> None:
    """Name a CAPTCHA as the reason an operation that already failed did.

    Nothing is waited on here. By the time this runs the page has stopped
    being usable, so the only thing left is to say why.
    """

    if any(_interactive_captcha_visible(frame) for frame in page.frames):
        raise ChromiumUnavailable("Stripe Checkout requires an interactive CAPTCHA")


#: How long someone at the browser is given to answer a challenge. Generous by
#: intent: the cost of waiting too long is a slow lane, and the cost of not
#: waiting is failing a run for the one thing it was attended to handle.
_ATTENDED_CAPTCHA_TIMEOUT_S = 300.0


def _settle_interactive_captcha(
    page: Any,
    *,
    attended: bool,
    monotonic: Callable[[], float] = time.monotonic,
) -> float:
    """Fail on a challenge nobody can answer; wait on one somebody can.

    An interactive CAPTCHA is the provider asking for a person, so it is only
    a dead end when there is no person. Reporting `chromium_unavailable` from
    an attended run fails the lane for precisely the reason the run was
    attended, and it misreports besides: Chromium was available and working,
    and it was the provider that stopped.

    Returns the seconds spent waiting, so a caller that had already given up
    can tell a page that was held from one that was refused, and can pay back
    the deadline the wait consumed.
    """

    def challenged() -> bool:
        return any(_interactive_captcha_visible(frame) for frame in page.frames)

    if not challenged():
        return 0.0
    if not attended:
        raise ChromiumUnavailable("Stripe Checkout requires an interactive CAPTCHA")
    print(
        "\n  The provider raised a CAPTCHA. Answer it in the browser window;\n"
        "  the lane goes on by itself once you do.\n",
        file=sys.stderr,
        flush=True,
    )
    started = monotonic()
    deadline = started + _ATTENDED_CAPTCHA_TIMEOUT_S
    while challenged():
        remaining_ms = (deadline - monotonic()) * 1000
        if remaining_ms <= 0:
            raise ChromiumUnavailable("the CAPTCHA Stripe Checkout raised went unanswered")
        page.wait_for_timeout(min(500, remaining_ms))
    return monotonic() - started


def _complete_authentication(
    page: Any,
    timeout_ms: int,
    *,
    attended: bool = False,
    diagnose: bool = False,
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
        # Time spent waiting on a person is not time the challenge took to
        # appear, so it is given back rather than counted against the deadline.
        deadline += _settle_interactive_captcha(page, attended=attended, monotonic=monotonic)
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
    raise CheckoutContractError(
        "Stripe test authentication challenge was unavailable"
        + (_offered_controls(page) if diagnose else "")
    )
