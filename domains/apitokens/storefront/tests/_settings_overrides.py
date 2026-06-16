"""Test helper for overriding dynaconf settings inside a test."""

from __future__ import annotations

from contextlib import contextmanager
from typing import Any, Iterator

from apitokens_storefront.utils import config as _config


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
