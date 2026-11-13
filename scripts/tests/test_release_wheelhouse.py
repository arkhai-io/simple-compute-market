"""The wheelhouse the build makes holds every declared distribution's wheel.

CI builds the wheelhouse (`make dist-ci`) before this suite runs, so a declared
distribution that no build target makes, or that builds under another name or
version, fails here rather than when a release candidate is loaded.
"""

from __future__ import annotations

from release_components import REPO_ROOT, declared_wheels, load

DIST_DIR = REPO_ROOT / ".dist"


def test_every_declared_distribution_resolves_against_the_wheelhouse() -> None:
    missing = [wheel.name for wheel in declared_wheels(load(), REPO_ROOT, DIST_DIR)
               if not wheel.is_file()]

    assert not missing, (
        f"{DIST_DIR} holds no wheel for {len(missing)} declared distribution(s); "
        "build the wheelhouse with `make dist`: " + ", ".join(missing)
    )
