"""File-based negotiation policy discovery.

Verifies that subdirectories of ``$XDG_CONFIG_HOME/arkhai/policies/``
and ``[seller.negotiation] extra_policy_paths`` are picked up as
strategies named after the folder. Each subdir is expected to expose
``policy.py`` with a callable ``factory(cfg) -> NegotiationStrategy``.
"""

from __future__ import annotations

import dataclasses
import textwrap
from pathlib import Path
from unittest.mock import patch

from market_policy.negotiation_strategy import (
    NegotiationDecision,
    NegotiationRoundInput,
    _REGISTRY,
    load_strategy,
)
from market_storefront.utils import config as agent_config
from market_storefront.utils import sync_negotiation


_STUB_POLICY = textwrap.dedent("""
    from market_policy.negotiation_strategy import NegotiationDecision

    class _Stub:
        def __init__(self, marker):
            self._marker = marker

        def decide(self, ri):
            return NegotiationDecision(action="exit", reason=self._marker)

    def factory(cfg):
        return _Stub(marker=cfg.get("marker", "stub-default"))
""")


def _write_policy(root: Path, name: str, body: str = _STUB_POLICY) -> Path:
    folder = root / name
    folder.mkdir(parents=True)
    (folder / "policy.py").write_text(body)
    return folder


def _patched_config(**overrides):
    """Build a Config copy with the given overrides, dropping any
    test-specific reload of the module singleton."""
    base = agent_config.load_config()
    return dataclasses.replace(base, **overrides)


def _force_rediscover():
    sync_negotiation._FILE_POLICIES_DISCOVERED = False


def test_extra_policy_paths_register_each_subdir(tmp_path):
    _write_policy(tmp_path, "myfast")
    _write_policy(tmp_path, "myslow")

    cfg = _patched_config(extra_policy_paths=[str(tmp_path)])
    _force_rediscover()
    _REGISTRY.pop("myfast", None)
    _REGISTRY.pop("myslow", None)

    with patch.object(agent_config, "CONFIG", cfg):
        sync_negotiation._discover_file_policies()

    assert "myfast" in _REGISTRY
    assert "myslow" in _REGISTRY

    strat = load_strategy("myfast", config={"marker": "via-extra"})
    decision = strat.decide(NegotiationRoundInput(
        direction="maximize",
        our_reference_price=100,
        their_proposed_price=10,
    ))
    assert isinstance(decision, NegotiationDecision)
    assert decision.action == "exit"
    assert decision.reason == "via-extra"


def test_xdg_default_path_is_discovered(tmp_path, monkeypatch):
    policies_root = tmp_path / "arkhai" / "policies"
    _write_policy(policies_root, "myxdg")

    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    cfg = _patched_config(extra_policy_paths=[])
    _force_rediscover()
    _REGISTRY.pop("myxdg", None)

    with patch.object(agent_config, "CONFIG", cfg):
        sync_negotiation._discover_file_policies()

    assert "myxdg" in _REGISTRY


def test_file_policy_overrides_builtin(tmp_path):
    # A folder named "bisection" should overwrite the built-in factory
    # — that's the local-tuning override UX.
    body = _STUB_POLICY.replace("stub-default", "from-file")
    _write_policy(tmp_path, "bisection", body=body)

    original = _REGISTRY.get("bisection")
    try:
        cfg = _patched_config(extra_policy_paths=[str(tmp_path)])
        _force_rediscover()
        with patch.object(agent_config, "CONFIG", cfg):
            sync_negotiation._discover_file_policies()

        strat = load_strategy("bisection")
        decision = strat.decide(NegotiationRoundInput(
            direction="maximize",
            our_reference_price=100,
            their_proposed_price=10,
        ))
        assert decision.reason == "from-file"
    finally:
        if original is not None:
            _REGISTRY["bisection"] = original
        _force_rediscover()


def test_broken_policy_does_not_block_siblings(tmp_path):
    _write_policy(tmp_path, "good")
    # Missing factory.
    broken = tmp_path / "bad"
    broken.mkdir()
    (broken / "policy.py").write_text("x = 1\n")
    # Folder with no policy.py at all — should be silently skipped.
    (tmp_path / "empty").mkdir()

    cfg = _patched_config(extra_policy_paths=[str(tmp_path)])
    _force_rediscover()
    _REGISTRY.pop("good", None)
    _REGISTRY.pop("bad", None)

    with patch.object(agent_config, "CONFIG", cfg):
        sync_negotiation._discover_file_policies()

    assert "good" in _REGISTRY
    assert "bad" not in _REGISTRY
    assert "empty" not in _REGISTRY


def test_discovery_runs_once_per_process(tmp_path):
    folder = _write_policy(tmp_path, "once")
    cfg = _patched_config(extra_policy_paths=[str(tmp_path)])
    _force_rediscover()
    _REGISTRY.pop("once", None)

    with patch.object(agent_config, "CONFIG", cfg):
        sync_negotiation._discover_file_policies()
    assert "once" in _REGISTRY

    # Drop the registration; a second call should NOT re-register
    # (cached).
    _REGISTRY.pop("once", None)
    with patch.object(agent_config, "CONFIG", cfg):
        sync_negotiation._discover_file_policies()
    assert "once" not in _REGISTRY

    # …unless we force.
    sync_negotiation._discover_file_policies(force=True)
    with patch.object(agent_config, "CONFIG", cfg):
        sync_negotiation._discover_file_policies(force=True)
    assert "once" in _REGISTRY
