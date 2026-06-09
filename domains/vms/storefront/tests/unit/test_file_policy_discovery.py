"""File-based negotiation middleware discovery.

Verifies that subdirectories of ``$XDG_CONFIG_HOME/arkhai/policies/``
and ``[negotiation] extra_policy_paths`` are picked up as
middlewares named after the folder. Each subdir is expected to expose
``policy.py`` with a callable ``middleware(history, context) -> (decision, context)``.
"""

from __future__ import annotations

import textwrap
from pathlib import Path
from types import SimpleNamespace

from market_policy.negotiation_middleware import (
    NegotiationContext,
    NegotiationDecision,
    NegotiationRound,
    _REGISTRY,
    load_negotiation_chain,
)
from domains.vms.negotiation import storefront_round


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
    storefront_round._FILE_POLICIES_DISCOVERED = False


def _ctx() -> NegotiationContext:
    return NegotiationContext(direction="maximize", our_reference_amount=100.0)


def test_extra_policy_paths_register_each_subdir(tmp_path):
    _write_policy(tmp_path, "myfast")
    _write_policy(tmp_path, "myslow")

    _force_rediscover()
    _REGISTRY.pop("myfast", None)
    _REGISTRY.pop("myslow", None)

    storefront_round._discover_file_policies(
        extra_policy_paths=[tmp_path],
    )

    assert "myfast" in _REGISTRY
    assert "myslow" in _REGISTRY

    chain = load_negotiation_chain(["myfast"])
    decision, _ = chain[0]([], _ctx())
    assert isinstance(decision, NegotiationDecision)
    assert decision.action == "exit"
    assert decision.reason == "stub-default"


def test_load_storefront_chain_builds_dispatch_for_policy_table():
    chain = storefront_round._load_storefront_chain(
        negotiation_config=SimpleNamespace(
            policies={
                "erc20": "erc20_bisection",
                "native_token": {"policy": "native_token_bisection"},
            },
            policy_mode="",
        ),
        extra_policy_paths=[],
    )

    assert [getattr(item, "__name__", "") for item in chain] == [
        "round_zero_opening_guard",
        "has_matching_inventory_guard",
        "escrow_shape_guard",
        "escrow_kind_dispatch_middleware",
    ]


def test_xdg_default_path_is_discovered(tmp_path, monkeypatch):
    policies_root = tmp_path / "arkhai" / "policies"
    _write_policy(policies_root, "myxdg")

    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    _force_rediscover()
    _REGISTRY.pop("myxdg", None)

    storefront_round._discover_file_policies(extra_policy_paths=[])

    assert "myxdg" in _REGISTRY


def test_file_policy_overrides_builtin(tmp_path):
    # A folder named "bisection" should overwrite the built-in middleware
    # — that's the local-tuning override UX.
    body = _STUB_POLICY.replace("stub-default", "from-file")
    _write_policy(tmp_path, "bisection", body=body)

    original = _REGISTRY.get("bisection")
    try:
        _force_rediscover()
        storefront_round._discover_file_policies(
            extra_policy_paths=[tmp_path],
        )

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

    storefront_round._discover_file_policies(
        extra_policy_paths=[tmp_path],
    )

    assert "good" in _REGISTRY
    assert "bad" not in _REGISTRY
    assert "empty" not in _REGISTRY


def test_discovery_runs_once_per_process(tmp_path):
    _write_policy(tmp_path, "once")
    _force_rediscover()
    _REGISTRY.pop("once", None)

    storefront_round._discover_file_policies(
        extra_policy_paths=[tmp_path],
    )
    assert "once" in _REGISTRY

    # Drop the registration; a second call should NOT re-register (cached).
    _REGISTRY.pop("once", None)
    storefront_round._discover_file_policies(
        extra_policy_paths=[tmp_path],
    )
    assert "once" not in _REGISTRY

    # …unless we force.
    storefront_round._discover_file_policies(
        force=True,
        extra_policy_paths=[tmp_path],
    )
    assert "once" in _REGISTRY
