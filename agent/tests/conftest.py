"""Test configuration for agent tests.

Pre-registers the ``app`` package so that imports like
``from domain.compute.agent.app.policy.arkhai_common import ...`` work without triggering
``app/__init__.py`` (which pulls in ``core.agent.app.agent`` and its full
dependency chain — incompatible with the agent venv's Python 3.10).
"""
import sys
import types
from pathlib import Path

_REPO_ROOT = str(Path(__file__).resolve().parents[2])
_AGENT_ROOT = str(Path(__file__).resolve().parents[1])

if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

# Pre-register the 'app' package so sub-module imports bypass
# app/__init__.py (avoids core.agent.app.agent import chain).
if "app" not in sys.modules:
    _app = types.ModuleType("app")
    _app.__path__ = [str(Path(_AGENT_ROOT) / "app")]
    sys.modules["app"] = _app
