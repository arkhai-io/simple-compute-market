from __future__ import annotations

from src.hosted_real_stripe.browser import _disable_optional_save_details


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
