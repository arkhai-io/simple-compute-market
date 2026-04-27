from __future__ import annotations

import importlib
import logging
import pkgutil
from types import ModuleType

logger = logging.getLogger(__name__)


def discover_and_register(package: str) -> None:
    """Import all submodules under the given package so decorators run.

    Example: discover_and_register("core.agent.app.policy")
    """
    try:
        pkg = importlib.import_module(package)
    except Exception as e:
        logger.warning("Failed to import package %s: %s", package, e)
        return

    if not hasattr(pkg, "__path__"):
        # Single module
        return

    for m in pkgutil.walk_packages(pkg.__path__, pkg.__name__ + "."):
        try:
            importlib.import_module(m.name)
        except Exception as e:
            logger.warning("Failed to import module %s: %s", m.name, e)
