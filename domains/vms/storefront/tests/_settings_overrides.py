"""Test helper for overriding dynaconf settings inside a test.

Used by unit and integration tests that need to inject specific config values
without writing files or touching env vars.

Example::

    from tests._settings_overrides import settings_overrides

    with settings_overrides(port=9999, **{"chain.rpc_url": "http://test"}):
        ...
"""

from __future__ import annotations

from contextlib import contextmanager
from copy import deepcopy
from typing import Any, Iterator

from market_storefront.utils import config as _agent_config


@contextmanager
def settings_overrides(**overrides: Any) -> Iterator[None]:
    """Temporarily set dotted keys on the storefront ``settings`` singleton.

    Restores prior values on exit. Use double-underscore keyword form for
    nested keys, e.g. ``chain__rpc_url="http://..."`` (then translated to
    ``chain.rpc_url``), or pass them as a dict::

        settings_overrides(**{"chain.rpc_url": "http://..."})
    """
    settings = _agent_config.settings
    originals: dict[str, tuple[bool, Any]] = {}
    try:
        for key, value in overrides.items():
            dotted = key.replace("__", ".")
            root = dotted.split(".", 1)[0]
            if root not in originals:
                existing = settings.get(root)
                originals[root] = (existing is not None, deepcopy(existing))
            settings.set(dotted, value)
        yield
    finally:
        for root, (existed, value) in originals.items():
            settings.unset(root, force=True)
            if existed:
                settings.set(root, value)
