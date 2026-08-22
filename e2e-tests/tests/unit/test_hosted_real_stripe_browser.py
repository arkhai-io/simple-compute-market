from __future__ import annotations
from dataclasses import dataclass

import pytest


from src.hosted_real_stripe.browser import (
    CheckoutContractError,
    ChromiumUnavailable,
    ChromiumCheckout,
    _await_checkout_left,
    _browser_proxy,
    _complete_authentication,
    _disable_optional_save_details,
    _submit_checkout,
)


class _UnavailablePlaywright:
    def __enter__(self) -> None:
        raise ChromiumUnavailable("interactive CAPTCHA")

    def __exit__(self, *_args: object) -> None:
        return None


def test_checkout_preserves_external_chromium_unavailability() -> None:
    checkout = ChromiumCheckout(playwright_factory=lambda: _UnavailablePlaywright())

    with pytest.raises(ChromiumUnavailable, match="interactive CAPTCHA"):
        checkout.pay(
            "https://checkout.stripe.com/c/pay/cs_test_example",
            outcome="authentication",
        )


class _SaveDetailsLocator:
    def __init__(self, *, checked: bool) -> None:
        self.first = self
        self._checked = checked
        self.unchecked = False

    def is_visible(self) -> bool:
        return True

    def is_checked(self) -> bool:
        return self._checked

    def uncheck(self) -> None:
        self.unchecked = True


class _Page:
    def __init__(self, locator: _SaveDetailsLocator) -> None:
        self._locator = locator

    def locator(self, selector: str) -> _SaveDetailsLocator:
        assert selector == "#enableStripePass"
        return self._locator


def test_checkout_disables_optional_link_save_details_before_submit() -> None:
    locator = _SaveDetailsLocator(checked=True)

    _disable_optional_save_details(_Page(locator))

    assert locator.unchecked is True


def test_checkout_leaves_unselected_link_save_details_unchanged() -> None:
    locator = _SaveDetailsLocator(checked=False)

    _disable_optional_save_details(_Page(locator))

    assert locator.unchecked is False


class _Mouse:
    def __init__(self) -> None:
        self.clicked_at: tuple[float, float] | None = None

    def click(self, x: float, y: float) -> None:
        self.clicked_at = (x, y)


class _SubmitPage:
    def __init__(self) -> None:
        self.mouse = _Mouse()


class _Submit:
    def __init__(self) -> None:
        self.clicked = False

    def click(self) -> None:
        self.clicked = True

    def bounding_box(self) -> dict[str, float]:
        return {"x": 10, "y": 20, "width": 30, "height": 40}


@pytest.mark.parametrize("outcome", ["success", "authentication"])
def test_checkout_positive_submit_does_not_wait_for_navigation(outcome: str) -> None:
    page = _SubmitPage()
    submit = _Submit()

    _submit_checkout(page, submit, outcome)

    assert page.mouse.clicked_at == (25, 40)
    assert submit.clicked is False


def test_checkout_decline_submit_uses_locator_click() -> None:
    page = _SubmitPage()
    submit = _Submit()

    _submit_checkout(page, submit, "decline")

    assert submit.clicked is True
    assert page.mouse.clicked_at is None


@dataclass
class _Clock:
    value: float = 0.0

    def __call__(self) -> float:
        return self.value


class _MissingChallenge:
    first: "_MissingChallenge"

    def __init__(self) -> None:
        self.first = self

    def is_visible(self) -> bool:
        return False


class _ChallengeFrame:
    def locator(self, _selector: str) -> _MissingChallenge:
        return _MissingChallenge()


class _ChallengePage:
    def __init__(self, clock: _Clock, frame_count: int) -> None:
        self.frames = [_ChallengeFrame() for _ in range(frame_count)]
        self._clock = clock
        self.waited_ms = 0.0

    def wait_for_timeout(self, timeout_ms: float) -> None:
        self.waited_ms += timeout_ms
        self._clock.value += timeout_ms / 1000


def test_authentication_challenge_uses_one_total_timeout_across_frames() -> None:
    clock = _Clock()
    page = _ChallengePage(clock, frame_count=20)

    with pytest.raises(CheckoutContractError, match="challenge was unavailable"):
        _complete_authentication(page, 500, monotonic=clock)

    assert page.waited_ms == 500


class _CaptchaFrame:
    url = "https://newassets.hcaptcha.com/captcha/v1"

    def locator(self, _selector: str) -> _SaveDetailsLocator:
        return _SaveDetailsLocator(checked=False)


def test_authentication_challenge_classifies_interactive_captcha_as_external() -> None:
    page = _ChallengePage(_Clock(), frame_count=0)
    page.frames = [_CaptchaFrame()]

    with pytest.raises(ChromiumUnavailable, match="interactive CAPTCHA"):
        _complete_authentication(page, 500)


# ---------------------------------------------------------------------------
# Reaching the provider
# ---------------------------------------------------------------------------


def test_the_browser_takes_the_proxy_this_run_reaches_the_provider_through(
    monkeypatch,
) -> None:
    """Chromium reads no proxy variable, so a page loads its shell and no form."""

    monkeypatch.delenv("ALL_PROXY", raising=False)
    monkeypatch.delenv("all_proxy", raising=False)
    monkeypatch.setenv("HTTPS_PROXY", "http://127.0.0.1:10809")
    monkeypatch.setenv("NO_PROXY", "example.invalid")

    proxy = _browser_proxy()

    assert proxy is not None
    assert proxy["server"] == "http://127.0.0.1:10809"
    bypass = proxy["bypass"].split(",")
    assert "example.invalid" in bypass
    # Loopback is the staged marketplace, the authority, and the webhook
    # forwarder; proxying any of them breaks a run that works today.
    for host in ("localhost", "127.0.0.1", "::1"):
        assert host in bypass


def test_a_run_with_no_proxy_launches_without_one(monkeypatch) -> None:
    for name in ("HTTPS_PROXY", "https_proxy", "HTTP_PROXY", "http_proxy"):
        monkeypatch.delenv(name, raising=False)

    assert _browser_proxy() is None


def test_the_socks_proxy_is_never_taken(monkeypatch) -> None:
    """A route only the browser could use is worse than no route.

    The run's own HTTP client refuses a SOCKS proxy without an optional
    dependency it does not install, so every other call in the run has to have
    it stripped.
    """

    for name in ("HTTPS_PROXY", "https_proxy", "HTTP_PROXY", "http_proxy"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("ALL_PROXY", "socks5h://127.0.0.1:10808")

    assert _browser_proxy() is None


# ---------------------------------------------------------------------------
# A payment says whether it happened
# ---------------------------------------------------------------------------


class _RedirectingPage:
    """A page that behaves the way Checkout behaves for a given submission."""

    def __init__(self, *, leaves: bool) -> None:
        self._leaves = leaves
        self.complaints: list[str] = []
        # No CAPTCHA: the page rejected the form on its own terms, which is a
        # different report from an environment that refused to serve it.
        self.frames: list[object] = []

    def wait_for_url(self, predicate, *, timeout: int) -> None:
        if not self._leaves:
            raise TimeoutError("still on checkout.stripe.com")

    def eval_on_selector_all(self, selector: str, script: str) -> list[str]:
        return ["Your card number is incomplete."]

    def content(self) -> str:
        return "<html></html>"


def test_a_payment_claims_its_outcome_only_after_checkout_leaves() -> None:
    _await_checkout_left(
        _RedirectingPage(leaves=True),
        timeout_ms=1_000,
        diagnose=False,
        subject="payment",
    )


def test_a_silently_rejected_payment_is_reported_at_the_browser() -> None:
    """Otherwise the lane fails minutes later as a funding timeout.

    That report names neither the page nor what was done there, which is three
    steps and several minutes removed from the thing that went wrong.
    """

    with pytest.raises(CheckoutContractError, match="submitted payment form"):
        _await_checkout_left(
            _RedirectingPage(leaves=False),
            timeout_ms=1,
            diagnose=False,
            subject="payment",
        )


def test_a_rejected_setup_still_names_the_setup() -> None:
    with pytest.raises(CheckoutContractError, match="submitted setup form"):
        _await_checkout_left(
            _RedirectingPage(leaves=False), timeout_ms=1, diagnose=False
        )


def test_a_development_run_quotes_what_the_page_said_was_wrong() -> None:
    with pytest.raises(CheckoutContractError, match="card number is incomplete"):
        _await_checkout_left(
            _RedirectingPage(leaves=False),
            timeout_ms=1,
            diagnose=True,
            subject="payment",
        )
