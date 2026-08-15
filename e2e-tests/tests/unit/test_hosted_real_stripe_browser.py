from __future__ import annotations
from dataclasses import dataclass

import pytest


from src.hosted_real_stripe.browser import (
    CheckoutContractError,
    ChromiumUnavailable,
    ChromiumCheckout,
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
