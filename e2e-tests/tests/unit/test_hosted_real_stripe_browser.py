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
    _settle_interactive_captcha,
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


class _HostIframe:
    """The `<iframe>` as the parent document sees it, which is the deciding view."""

    def __init__(self, *, visible: bool = True, box: dict | None = None) -> None:
        self._visible = visible
        self._box = {"x": 20.0, "y": 120.0, "width": 300.0, "height": 150.0} if box is None else box

    def is_visible(self) -> bool:
        return self._visible

    def bounding_box(self) -> dict | None:
        return self._box


class _CaptchaFrame:
    url = "https://newassets.hcaptcha.com/captcha/v1"

    def __init__(self, host: _HostIframe | None = None) -> None:
        self._host = host or _HostIframe()

    def locator(self, _selector: str) -> _SaveDetailsLocator:
        return _SaveDetailsLocator(checked=False)

    def frame_element(self) -> _HostIframe:
        return self._host


#: What hCaptcha actually leaves behind on an ordinary submitted Checkout,
#: measured from a live test-mode page: the button is there and reports itself
#: visible inside its own frame, while the parent has the iframe hidden and
#: parked far off the top of the page.
_HIDDEN_CHALLENGE = _HostIframe(
    visible=False, box={"x": 17.0, "y": -8880.5, "width": 300.0, "height": 150.0}
)
_OFFSCREEN_CHALLENGE = _HostIframe(
    visible=True, box={"x": 9.0, "y": -9999.0, "width": 300.0, "height": 150.0}
)


def test_authentication_challenge_classifies_interactive_captcha_as_external() -> None:
    page = _ChallengePage(_Clock(), frame_count=0)
    page.frames = [_CaptchaFrame()]

    with pytest.raises(ChromiumUnavailable, match="interactive CAPTCHA"):
        _complete_authentication(page, 500)


@pytest.mark.parametrize(
    ("label", "host"),
    [("hidden by the parent", _HIDDEN_CHALLENGE), ("parked off-screen", _OFFSCREEN_CHALLENGE)],
)
def test_a_challenge_the_page_never_showed_is_not_a_challenge(
    label: str, host: _HostIframe
) -> None:
    """hCaptcha leaves this behind on every submitted Checkout, asking nothing.

    The button inside the frame reports itself visible either way, so a lane
    that trusts the frame's own answer fails every authentication run on a
    page the person watching it saw nothing wrong with.
    """

    page = _ChallengePage(_Clock(), frame_count=0)
    page.frames = [_CaptchaFrame(host)]

    assert _settle_interactive_captcha(page, attended=True) == 0.0
    assert _settle_interactive_captcha(page, attended=False) == 0.0


class _AnsweredCaptcha:
    """A challenge that stops being visible once someone has answered it."""

    url = "https://newassets.hcaptcha.com/captcha/v1"

    def __init__(self, clock: _Clock, *, answered_at: float) -> None:
        self.first = self
        self._clock = clock
        self._answered_at = answered_at

    def locator(self, _selector: str) -> "_AnsweredCaptcha":
        return self

    def frame_element(self) -> _HostIframe:
        return _HostIframe(visible=self._clock.value < self._answered_at)

    def is_visible(self) -> bool:
        return self._clock.value < self._answered_at


class _AuthorizeButton:
    def __init__(self) -> None:
        self.first = self
        self.clicked = False

    def is_visible(self) -> bool:
        return True

    def click(self) -> None:
        self.clicked = True


class _AuthorizeFrame:
    url = "https://hooks.stripe.com/3d_secure"

    def __init__(self, button: _AuthorizeButton) -> None:
        self._button = button

    def locator(self, selector: str) -> object:
        if selector == "#test-source-authorize-3ds":
            return self._button
        return _MissingChallenge()


def test_an_attended_run_waits_for_the_person_to_answer_the_captcha() -> None:
    """The person at the window is the whole reason the run is attended."""

    clock = _Clock()
    button = _AuthorizeButton()
    page = _ChallengePage(clock, frame_count=0)
    page.frames = [_AnsweredCaptcha(clock, answered_at=30.0), _AuthorizeFrame(button)]

    _complete_authentication(page, 500, attended=True, monotonic=clock)

    assert button.clicked is True
    assert clock.value >= 30.0


def test_the_time_a_person_spends_answering_is_not_charged_to_the_challenge() -> None:
    """Otherwise every answered challenge fails the timeout it just cleared."""

    clock = _Clock()
    button = _AuthorizeButton()
    page = _ChallengePage(clock, frame_count=0)
    # Answered well past the challenge's own half-second budget.
    page.frames = [_AnsweredCaptcha(clock, answered_at=120.0), _AuthorizeFrame(button)]

    _complete_authentication(page, 500, attended=True, monotonic=clock)

    assert button.clicked is True


def test_a_captcha_nobody_answers_still_fails_an_attended_run() -> None:
    clock = _Clock()
    page = _ChallengePage(clock, frame_count=0)
    page.frames = [_AnsweredCaptcha(clock, answered_at=float("inf"))]

    with pytest.raises(ChromiumUnavailable, match="went unanswered"):
        _settle_interactive_captcha(page, attended=True, monotonic=clock)


def test_an_unchallenged_page_waits_for_nothing() -> None:
    clock = _Clock()
    page = _ChallengePage(clock, frame_count=3)

    assert _settle_interactive_captcha(page, attended=True, monotonic=clock) == 0.0
    assert page.waited_ms == 0.0


class _HeldCheckoutPage:
    """Checkout that never leaves until its challenge is answered."""

    url = "https://checkout.stripe.com/c/pay/cs_test_example"

    def __init__(self, clock: _Clock, *, answered_at: float) -> None:
        self._clock = clock
        self._captcha = _AnsweredCaptcha(clock, answered_at=answered_at)
        self.frames = [self._captcha]
        self.waits = 0
        self.waited_ms = 0.0

    def wait_for_url(self, _predicate, *, timeout: float) -> None:
        self.waits += 1
        if self._captcha.is_visible():
            self._clock.value += timeout / 1000
            raise TimeoutError("still on Checkout")

    def wait_for_timeout(self, timeout_ms: float) -> None:
        self.waited_ms += timeout_ms
        self._clock.value += timeout_ms / 1000


def test_a_page_held_by_a_captcha_is_waited_on_again_once_it_clears() -> None:
    """A challenge answered by hand is a held page, not a refused submission."""

    clock = _Clock()
    page = _HeldCheckoutPage(clock, answered_at=20.0)

    _await_checkout_left(page, timeout_ms=1_000, diagnose=False, attended=True)

    assert page.waits == 2


def test_a_page_held_by_a_captcha_is_not_retried_when_nobody_is_watching() -> None:
    clock = _Clock()
    page = _HeldCheckoutPage(clock, answered_at=float("inf"))

    with pytest.raises(ChromiumUnavailable, match="interactive CAPTCHA"):
        _await_checkout_left(page, timeout_ms=1_000, diagnose=False)

    assert page.waits == 1


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
