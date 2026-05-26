"""File-based aggregation-policy discovery.

Verifies that subdirectories of ``$XDG_CONFIG_HOME/arkhai/aggregation_policies/``
and ``[aggregation] extra_policy_paths`` are picked up as policies
named after the folder. Each subdir is expected to expose ``policy.py``
with a callable ``factory(cfg) -> AggregationPolicy``.

Mirror of ``storefront/tests/unit/test_file_policy_discovery.py`` for
the buyer side. Cleans up registry state between tests so re-registering
a folder name doesn't leak into the next test's assertions.
"""

from __future__ import annotations

import asyncio
import textwrap
from pathlib import Path
from unittest.mock import patch

import pytest

from market_buyer import aggregation as agg


# Trivial factory: returns a policy that records its own marker and exits
# without negotiating. We only need to confirm the policy was registered
# under the right name and is callable through `load_aggregation_policy`.
_STUB_POLICY = textwrap.dedent("""
    async def _stub(candidates, negotiate):
        return None

    def factory(cfg):
        # cfg is the buyer's full TOML config; ignore it for the stub.
        return _stub
""")


def _write_policy(root: Path, name: str, body: str = _STUB_POLICY) -> Path:
    folder = root / name
    folder.mkdir(parents=True)
    (folder / "policy.py").write_text(body)
    return folder


def _force_rediscover():
    agg._FILE_POLICIES_DISCOVERED = False


@pytest.fixture
def restore_registry():
    """Snapshot the registry, restore it after the test.

    Each test mutates _REGISTRY (registers file policies). Without
    cleanup, leftover folder-named policies leak across tests and
    break ordering assertions in test_aggregation.py.
    """
    snapshot = dict(agg._REGISTRY)
    yield
    agg._REGISTRY.clear()
    agg._REGISTRY.update(snapshot)
    _force_rediscover()


def test_extra_policy_paths_register_each_subdir(tmp_path, restore_registry):
    _write_policy(tmp_path, "myfast")
    _write_policy(tmp_path, "myslow")
    _force_rediscover()

    with patch.object(
        agg, "_resolve_extra_policy_paths",
        lambda _cfg: [str(tmp_path)],
    ):
        agg._discover_file_policies()

    assert "myfast" in agg._REGISTRY
    assert "myslow" in agg._REGISTRY

    # Loading through the public API returns the registered policy and
    # the policy is invokable as an aggregation policy.
    policy = agg.load_aggregation_policy("myfast")
    assert asyncio.run(policy([], lambda _: None)) is None


def test_xdg_default_path_is_discovered(tmp_path, monkeypatch, restore_registry):
    policies_root = tmp_path / "arkhai" / "aggregation_policies"
    _write_policy(policies_root, "myxdg")

    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    _force_rediscover()
    # No extras configured — only the XDG default should be scanned.
    with patch.object(agg, "_resolve_extra_policy_paths", lambda _cfg: []):
        agg._discover_file_policies()

    assert "myxdg" in agg._REGISTRY


def test_file_policy_overrides_builtin(tmp_path, restore_registry):
    """A folder named ``cheapest_first`` overrides the built-in.

    This is the local-tuning override UX — same as the storefront's
    negotiation-policy discovery.
    """
    body = textwrap.dedent("""
        _MARKER = "from-file"

        async def _override(candidates, negotiate):
            # Carry the marker on the function so the test can assert it.
            return None

        _override.marker = _MARKER

        def factory(cfg):
            return _override
    """)
    _write_policy(tmp_path, "cheapest_first", body=body)

    _force_rediscover()
    with patch.object(
        agg, "_resolve_extra_policy_paths",
        lambda _cfg: [str(tmp_path)],
    ):
        agg._discover_file_policies()

    overridden = agg.load_aggregation_policy("cheapest_first")
    assert getattr(overridden, "marker", None) == "from-file", (
        "file policy should win over the built-in cheapest_first"
    )


def test_broken_policy_does_not_block_siblings(tmp_path, restore_registry):
    _write_policy(tmp_path, "good")
    # Missing factory.
    bad = tmp_path / "bad"
    bad.mkdir()
    (bad / "policy.py").write_text("x = 1\n")
    # Folder with no policy.py at all — silently skipped.
    (tmp_path / "empty").mkdir()
    # Factory exists but raises at construction time.
    raises = tmp_path / "raises"
    raises.mkdir()
    (raises / "policy.py").write_text(textwrap.dedent("""
        def factory(cfg):
            raise RuntimeError("boom")
    """))
    # Factory returns a non-callable.
    not_callable = tmp_path / "not_callable"
    not_callable.mkdir()
    (not_callable / "policy.py").write_text(textwrap.dedent("""
        def factory(cfg):
            return 42
    """))

    _force_rediscover()
    with patch.object(
        agg, "_resolve_extra_policy_paths",
        lambda _cfg: [str(tmp_path)],
    ):
        agg._discover_file_policies()

    assert "good" in agg._REGISTRY
    for skipped in ("bad", "empty", "raises", "not_callable"):
        assert skipped not in agg._REGISTRY, f"{skipped} should not register"


def test_discovery_runs_once_per_process(tmp_path, restore_registry):
    _write_policy(tmp_path, "once")
    _force_rediscover()

    with patch.object(
        agg, "_resolve_extra_policy_paths",
        lambda _cfg: [str(tmp_path)],
    ):
        agg._discover_file_policies()
    assert "once" in agg._REGISTRY

    # Drop the registration; a second call should not re-scan (cached).
    agg._REGISTRY.pop("once", None)
    with patch.object(
        agg, "_resolve_extra_policy_paths",
        lambda _cfg: [str(tmp_path)],
    ):
        agg._discover_file_policies()
    assert "once" not in agg._REGISTRY

    # …unless force=True.
    with patch.object(
        agg, "_resolve_extra_policy_paths",
        lambda _cfg: [str(tmp_path)],
    ):
        agg._discover_file_policies(force=True)
    assert "once" in agg._REGISTRY


def test_load_aggregation_policy_triggers_discovery(tmp_path, monkeypatch, restore_registry):
    """The public entry point should kick off discovery on first call —
    callers shouldn't have to know about ``_discover_file_policies``."""
    policies_root = tmp_path / "arkhai" / "aggregation_policies"
    _write_policy(policies_root, "via_load")

    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    _force_rediscover()
    agg._REGISTRY.pop("via_load", None)

    with patch.object(agg, "_resolve_extra_policy_paths", lambda _cfg: []):
        policy = agg.load_aggregation_policy("via_load")

    assert callable(policy)
    assert "via_load" in agg._REGISTRY
