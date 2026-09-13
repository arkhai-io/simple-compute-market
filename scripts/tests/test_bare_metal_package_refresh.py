"""Bare-metal review builds must consume fresh, lock-stable internal wheels."""

from __future__ import annotations

import re
import tomllib
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
ROOT_MAKE = (REPO_ROOT / "Makefile").read_text(encoding="utf-8")
STOREFRONT_MAKE = (
    REPO_ROOT / "domains" / "bare_metal" / "storefront" / "Makefile"
).read_text(encoding="utf-8")
ALKAHEST_MAKE = (REPO_ROOT / "kit" / "alkahest" / "Makefile").read_text(
    encoding="utf-8"
)
E2E_MAKE = (REPO_ROOT / "e2e-tests" / "Makefile").read_text(encoding="utf-8")
E2E_PROJECT = tomllib.loads(
    (REPO_ROOT / "e2e-tests" / "pyproject.toml").read_text(encoding="utf-8")
)


def _target(makefile: str, name: str) -> str:
    match = re.search(
        rf"^{re.escape(name)}:.*?(?=^\S[^\n]*:|\Z)",
        makefile,
        re.MULTILINE | re.DOTALL,
    )
    assert match, f"missing Make target {name}"
    return match.group(0)


def test_bare_metal_storefront_builds_every_directly_refreshed_producer() -> None:
    declaration = _target(ROOT_MAKE, "dist-bare-metal-storefront").splitlines()[0]

    for prerequisite in (
        "dist-registry-client",
        "dist-config",
        "dist-alkahest",
    ):
        assert prerequisite in declaration


def test_e2e_declares_bare_metal_contract_test_packages_directly() -> None:
    dependencies = E2E_PROJECT["project"]["dependencies"]

    assert "arkhai-bare-metal-buyer>=0.1.4" in dependencies
    assert "arkhai-bare-metal-storefront>=0.2.5" in dependencies


def _flag_packages(target: str, flag: str) -> tuple[str, ...]:
    return tuple(re.findall(rf"--{re.escape(flag)}\s+(\S+)", target))


def test_locked_reinit_preserves_exact_wheel_reinstall_inventory() -> None:
    expected = (
        (
            _target(STOREFRONT_MAKE, "reinit"),
            (
                "arkhai-bare-metal-storefront",
                "arkhai-bare-metal",
                "arkhai-core",
                "arkhai-core-registry-client",
                "arkhai-core-storefront",
                "arkhai-compute-provisioning",
                "arkhai-kit-alkahest",
                "arkhai-kit-capacity-publication",
                "arkhai-kit-config",
                "arkhai-kit-contact-exchange",
                "arkhai-kit-identity",
                "arkhai-kit-policy",
                "arkhai-kit-site-client",
                "arkhai-kit-settlement-runtime",
                "arkhai-kit-storefront",
            ),
        ),
        (
            _target(ALKAHEST_MAKE, "reinit"),
            ("arkhai-core", "arkhai-kit-settlement-runtime"),
        ),
        (
            _target(E2E_MAKE, "reinit"),
            (
                "arkhai-core",
                "arkhai-core-buyer",
                "arkhai-core-storefront",
                "arkhai-core-registry-client",
                "arkhai-core-storefront-client",
                "arkhai-kit-config",
                "arkhai-kit-identity",
                "arkhai-kit-policy",
                "arkhai-kit-settlement-runtime",
                "arkhai-kit-storefront",
                "arkhai-kit-alkahest",
                "arkhai-hosted-settlement-client",
                "arkhai-kit-hosted-settlement",
                "arkhai-kit-site",
                "arkhai-kit-site-client",
                "arkhai-kit-resource-pools",
                "arkhai-kit-fulfillment",
                "arkhai-vms",
                "arkhai-vms-buyer",
                "arkhai-vms-storefront",
                "arkhai-bare-metal",
                "arkhai-bare-metal-buyer",
                "arkhai-bare-metal-storefront",
                "arkhai-compute-provisioning",
                "arkhai-vms-provisioning-operator-client",
                "arkhai-apicredits-buyer",
            ),
        ),
    )

    for target, packages in expected:
        assert _flag_packages(target, "reinstall-package") == packages
        assert _flag_packages(target, "upgrade-package") == ()


def test_review_setup_uses_locks_without_disabling_wheel_reinstallation() -> None:
    targets = (
        _target(STOREFRONT_MAKE, "init"),
        _target(STOREFRONT_MAKE, "reinit"),
        _target(ALKAHEST_MAKE, "reinit"),
        _target(E2E_MAKE, "init"),
        _target(E2E_MAKE, "reinit"),
    )

    for target in targets:
        assert "uv sync" in target
        assert "--locked" in target

    for target in (
        _target(STOREFRONT_MAKE, "reinit"),
        _target(ALKAHEST_MAKE, "reinit"),
        _target(E2E_MAKE, "reinit"),
    ):
        assert "--reinstall-package" in target
        assert "--frozen" not in target
