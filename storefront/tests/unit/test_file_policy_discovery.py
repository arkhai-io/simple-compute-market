"""File-based negotiation middleware discovery.

Verifies that subdirectories of ``$XDG_CONFIG_HOME/arkhai/policies/``
and ``[negotiation] extra_policy_paths`` are picked up as
middlewares named after the folder. Each subdir is expected to expose
``policy.py`` with a callable ``middleware(history, context) -> (decision, context)``.
"""

from __future__ import annotations

import textwrap
from pathlib import Path

from market_policy.negotiation_middleware import (
    NegotiationContext,
    NegotiationDecision,
    NegotiationRound,
    _REGISTRY,
    load_negotiation_chain,
)
from market_storefront.utils import sync_negotiation
from tests._settings_overrides import settings_overrides


_STUB_POLICY = textwrap.dedent("""
    from market_policy.negotiation_middleware import NegotiationDecision

    _MARKER = "stub-default"

    def middleware(history, context):
        return NegotiationDecision(action="exit", reason=_MARKER), context
""")


def _write_policy(root: Path, name: str, body: str = _STUB_POLICY) -> Path:
    folder = root / name
    folder.mkdir(parents=True)
    (folder / "policy.py").write_text(body)
    return folder


def _force_rediscover():
    sync_negotiation._FILE_POLICIES_DISCOVERED = False


def _ctx() -> NegotiationContext:
    return NegotiationContext(direction="maximize", our_reference_price=100.0)


def test_extra_policy_paths_register_each_subdir(tmp_path):
    _write_policy(tmp_path, "myfast")
    _write_policy(tmp_path, "myslow")

    _force_rediscover()
    _REGISTRY.pop("myfast", None)
    _REGISTRY.pop("myslow", None)

    with settings_overrides(**{"negotiation.extra_policy_paths": [str(tmp_path)]}):
        sync_negotiation._discover_file_policies()

    assert "myfast" in _REGISTRY
    assert "myslow" in _REGISTRY

    chain = load_negotiation_chain(["myfast"])
    decision, _ = chain[0]([], _ctx())
    assert isinstance(decision, NegotiationDecision)
    assert decision.action == "exit"
    assert decision.reason == "stub-default"


def test_xdg_default_path_is_discovered(tmp_path, monkeypatch):
    policies_root = tmp_path / "arkhai" / "policies"
    _write_policy(policies_root, "myxdg")

    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    _force_rediscover()
    _REGISTRY.pop("myxdg", None)

    with settings_overrides(**{"negotiation.extra_policy_paths": []}):
        sync_negotiation._discover_file_policies()

    assert "myxdg" in _REGISTRY


def test_file_policy_overrides_builtin(tmp_path):
    # A folder named "bisection" should overwrite the built-in middleware
    # — that's the local-tuning override UX.
    body = _STUB_POLICY.replace("stub-default", "from-file")
    _write_policy(tmp_path, "bisection", body=body)

    original = _REGISTRY.get("bisection")
    try:
        _force_rediscover()
        with settings_overrides(**{"negotiation.extra_policy_paths": [str(tmp_path)]}):
            sync_negotiation._discover_file_policies()

        chain = load_negotiation_chain(["bisection"])
        decision, _ = chain[0]([], _ctx())
        assert decision.reason == "from-file"
    finally:
        if original is not None:
            _REGISTRY["bisection"] = original
        _force_rediscover()


def test_broken_policy_does_not_block_siblings(tmp_path):
    _write_policy(tmp_path, "good")
    # Missing middleware.
    broken = tmp_path / "bad"
    broken.mkdir()
    (broken / "policy.py").write_text("x = 1\n")
    # Folder with no policy.py at all — should be silently skipped.
    (tmp_path / "empty").mkdir()

    _force_rediscover()
    _REGISTRY.pop("good", None)
    _REGISTRY.pop("bad", None)

    with settings_overrides(**{"negotiation.extra_policy_paths": [str(tmp_path)]}):
        sync_negotiation._discover_file_policies()

    assert "good" in _REGISTRY
    assert "bad" not in _REGISTRY
    assert "empty" not in _REGISTRY


def test_discovery_runs_once_per_process(tmp_path):
    _write_policy(tmp_path, "once")
    _force_rediscover()
    _REGISTRY.pop("once", None)

    with settings_overrides(**{"negotiation.extra_policy_paths": [str(tmp_path)]}):
        sync_negotiation._discover_file_policies()
    assert "once" in _REGISTRY

    # Drop the registration; a second call should NOT re-register (cached).
    _REGISTRY.pop("once", None)
    with settings_overrides(**{"negotiation.extra_policy_paths": [str(tmp_path)]}):
        sync_negotiation._discover_file_policies()
    assert "once" not in _REGISTRY

    # …unless we force.
    with settings_overrides(**{"negotiation.extra_policy_paths": [str(tmp_path)]}):
        sync_negotiation._discover_file_policies(force=True)
    assert "once" in _REGISTRY
