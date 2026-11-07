"""Test helper for overriding dynaconf settings inside a test."""

from __future__ import annotations

from contextlib import contextmanager
from copy import deepcopy
from typing import Any, Iterator

from apicredits_storefront.utils import config as _config


@contextmanager
def replaced_setting(key: str, value: Any) -> Iterator[None]:
    """Temporarily replace one root key on the storefront ``settings``
    singleton whole, restoring it, or its absence, on exit.

    Unlike ``settings_overrides``, nothing is left behind: a table it added
    is removed rather than set to ``None``.
    """
    settings = _config.settings
    original = deepcopy(settings.get(key))
    settings.unset(key, force=True)
    settings.set(key, deepcopy(value))
    try:
        yield
    finally:
        settings.unset(key, force=True)
        if original is not None:
            settings.set(key, original)


@contextmanager
def settings_overrides(**overrides: Any) -> Iterator[None]:
    """Temporarily set dotted keys on the storefront ``settings`` singleton."""
    settings = _config.settings
    originals: dict[str, Any] = {}
    try:
        for key, value in overrides.items():
            dotted = key.replace("__", ".")
            originals[dotted] = settings.get(dotted)
            settings.set(dotted, value)
        yield
    finally:
        for dotted, value in originals.items():
            settings.set(dotted, value)
